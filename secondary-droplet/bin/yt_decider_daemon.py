#!/usr/bin/env python3
"""Production decider tuned for the current deployment."""

import csv
import datetime
import os
import time
from pathlib import Path
from subprocess import run

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube",
]
TOKEN = "/root/token.json"
CSV = "/root/yt_decider_log.csv"
CYCLE = 20  # seconds
DAY_START = 8
DAY_END = 19
TZ_OFFSET = 1  # Luanda

LOG_FILE = Path("/root/bwb_services.log")


def log_event(component: str, message: str) -> None:
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp} [{component}] {message}\n"
    try:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


def local_hour() -> int:
    """Return current local hour using the configured offset."""

    return (datetime.datetime.utcnow() + datetime.timedelta(hours=TZ_OFFSET)).hour


def build_api():
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def get_state(yt):
    broadcast = (
        yt.liveBroadcasts()
        .list(part="id,contentDetails,status", mine=True, maxResults=5)
        .execute()
    )
    items = broadcast.get("items", [])
    live = next(
        (
            it
            for it in items
            if it.get("status", {}).get("lifeCycleStatus") in ("live", "testing")
        ),
        None,
    )
    if not live:
        return {"streamStatus": "?", "health": "?", "note": "sem broadcast"}

    sid = live["contentDetails"]["boundStreamId"]
    streams = yt.liveStreams().list(part="id,status,cdn", id=sid).execute()
    stream_items = streams.get("items", [])
    if not stream_items:
        return {
            "streamStatus": "?",
            "health": "?",
            "note": "stream não encontrado",
        }

    st = stream_items[0]
    hs = st["status"].get("healthStatus", {})
    return {
        "streamStatus": st["status"].get("streamStatus"),
        "health": hs.get("status", "?"),
        "note": "",
    }


def csv_log(row):
    exists = os.path.exists(CSV)
    with open(CSV, "a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if not exists:
            writer.writerow(
                [
                    "cycle",
                    "hora",
                    "streamStatus",
                    "health",
                    "acao",
                    "detalhe",
                ]
            )
        writer.writerow(row)


def is_active(unit):
    return (
        run(["systemctl", "is-active", unit], capture_output=True, text=True).returncode
        == 0
    )


def start_fallback():
    log_event("yt_decider", "Enabling youtube-fallback.service")
    run(["systemctl", "enable", "--now", "youtube-fallback.service"], check=False)


def stop_fallback():
    log_event("yt_decider", "Stopping youtube-fallback.service")
    run(["systemctl", "stop", "youtube-fallback.service"], check=False)


def main():
    print("== yt_decider_daemon — PRODUÇÃO (STOP diurno quando primário OK) ==")
    log_event("yt_decider", "Daemon started")
    cycle = 0
    while True:
        cycle += 1
        try:
            yt = build_api()
            state = get_state(yt)
        except Exception as exc:  # noqa: BLE001 - log error and continue looping
            log_event(
                "yt_decider",
                f"Exception during cycle {cycle}: {exc.__class__.__name__}: {exc}",
            )
            csv_log(
                [
                    cycle,
                    datetime.datetime.now().strftime("%H:%M"),
                    "?",
                    "?",
                    "KEEP",
                    f"exc: {exc.__class__.__name__}",
                ]
            )
            time.sleep(CYCLE)
            continue

        hour = local_hour()
        stream_status, health = state["streamStatus"], state["health"]
        fallback_on = is_active("youtube-fallback.service")

        action = "KEEP"
        detail = state["note"] or ""
        # Night: 19:00–08:00 keep fallback if no primary
        if not (DAY_START <= hour < DAY_END):
            if stream_status in ("inactive", "?") or health in ("noData", "?", "bad"):
                if not fallback_on:
                    start_fallback()
                    action = "START secondary"
                    detail = "night + no primary"
            else:
                action = "KEEP"
        else:
            # Day: stop fallback if primary OK, else keep/start
            if stream_status == "active" and health in ("good", "ok"):
                if fallback_on:
                    stop_fallback()
                    action = "STOP secondary"
                    detail = "day primary OK"
            else:
                if not fallback_on:
                    start_fallback()
                    action = "START secondary"
                    detail = "day but no primary"

        csv_log(
            [
                cycle,
                datetime.datetime.now().strftime("%H:%M"),
                stream_status,
                health,
                action,
                detail,
            ]
        )
        time.sleep(CYCLE)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log_event("yt_decider", "Daemon interrupted by user")
        raise SystemExit(130)
