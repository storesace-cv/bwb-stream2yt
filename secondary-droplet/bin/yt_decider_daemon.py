#!/usr/bin/env python3
"""Production decider tuned for the current deployment."""

import datetime
import time
from dataclasses import dataclass
from pathlib import Path
from subprocess import run

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube",
]
TOKEN = "/root/token.json"
CYCLE = 20  # seconds
DAY_START = 8
DAY_END = 19
TZ_OFFSET = 1  # Luanda
STOP_OK_STREAK = 3
START_BAD_STREAK = 2

LOG_FILE = Path("/root/bwb_services.log")


@dataclass
class DeciderContext:
    """Stateful information preserved between cycles."""

    primary_ok_streak: int = 0
    primary_bad_streak: int = 0


context = DeciderContext()


def log_event(component: str, message: str) -> None:
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp} [{component}] {message}\n"
    try:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


def log_cycle_decision(
    *,
    cycle: int,
    hour: str,
    stream_status: str,
    health: str,
    action: str,
    detail: str,
) -> None:
    """Send the decision information to the shared service log."""

    message = "decision_csv=" + ",".join(
        str(value if value is not None else "")
        for value in (cycle, hour, stream_status, health, action, detail)
    )
    log_event("yt_decider", message)


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


def is_active(unit):
    return (
        run(["systemctl", "is-active", unit], capture_output=True, text=True).returncode
        == 0
    )


def start_fallback():
    log_event(
        "yt_decider",
        "fallback: start requested service=youtube-fallback.service",
    )
    proc = run(
        ["systemctl", "enable", "--now", "youtube-fallback.service"],
        check=False,
        capture_output=True,
        text=True,
    )
    stderr = proc.stderr.strip()
    stdout = proc.stdout.strip()
    log_event(
        "yt_decider",
        "fallback: start result returncode="
        f"{proc.returncode} stdout={stdout or '-'} stderr={stderr or '-'}",
    )


def stop_fallback():
    log_event(
        "yt_decider",
        "fallback: stop requested service=youtube-fallback.service",
    )
    proc = run(
        ["systemctl", "stop", "youtube-fallback.service"],
        check=False,
        capture_output=True,
        text=True,
    )
    stderr = proc.stderr.strip()
    stdout = proc.stdout.strip()
    log_event(
        "yt_decider",
        "fallback: stop result returncode="
        f"{proc.returncode} stdout={stdout or '-'} stderr={stderr or '-'}",
    )


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
            log_cycle_decision(
                cycle=cycle,
                hour=datetime.datetime.now().strftime("%H:%M"),
                stream_status="?",
                health="?",
                action="KEEP",
                detail=f"exc: {exc.__class__.__name__}",
            )
            time.sleep(CYCLE)
            continue

        hour = local_hour()
        stream_status, health = state["streamStatus"], state["health"]
        fallback_on = is_active("youtube-fallback.service")

        action = "KEEP"
        detail = state["note"] or ""

        primary_ok = stream_status == "active" and health in ("good", "ok")
        primary_bad = stream_status in (
            "inactive",
            "?",
            "error",
        ) or health in (
            "noData",
            "?",
            "bad",
            "revoked",
        )
        # Discovery doc (https://developers.google.com/youtube/v3/live/docs/liveStream#status)
        # notes that ``error`` and ``revoked`` indicate primary ingest failure, so treat them
        # like other fatal states even if the stream was previously active.

        if primary_ok:
            context.primary_ok_streak += 1
        else:
            context.primary_ok_streak = 0

        if primary_bad:
            context.primary_bad_streak += 1
        else:
            context.primary_bad_streak = 0
        # Night: 19:00–08:00 keep fallback if no primary
        if not (DAY_START <= hour < DAY_END):
            if primary_bad:
                if not fallback_on:
                    start_fallback()
                    action = "START secondary"
                    detail = "night + no primary"
                else:
                    detail = detail or ""
            else:
                action = "KEEP"
        else:
            # Day: stop fallback if primary OK, else keep/start
            if primary_ok:
                if fallback_on and context.primary_ok_streak >= STOP_OK_STREAK:
                    stop_fallback()
                    action = "STOP secondary"
                    detail = "day primary OK"
                    context.primary_bad_streak = 0
                else:
                    detail = (
                        detail
                        or f"aguardar ok streak {context.primary_ok_streak}/{STOP_OK_STREAK}"
                    )
            else:
                if not fallback_on and context.primary_bad_streak >= START_BAD_STREAK:
                    start_fallback()
                    action = "START secondary"
                    detail = "day but no primary"
                    context.primary_ok_streak = 0
                else:
                    detail = (
                        detail
                        or f"aguardar bad streak {context.primary_bad_streak}/{START_BAD_STREAK}"
                    )

        log_event(
            "yt_decider",
            "decision: cycle="
            f"{cycle} status={stream_status} health={health} "
            f"fallback={'on' if fallback_on else 'off'} "
            f"action={action} detail={detail or '-'}",
        )

        log_cycle_decision(
            cycle=cycle,
            hour=datetime.datetime.now().strftime("%H:%M"),
            stream_status=stream_status,
            health=health,
            action=action,
            detail=detail,
        )
        time.sleep(CYCLE)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log_event("yt_decider", "Daemon interrupted by user")
        raise SystemExit(130)
