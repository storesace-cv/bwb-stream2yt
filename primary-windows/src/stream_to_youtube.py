#!/usr/bin/env python3
# stream_to_youtube.py — Windows primary sender (one-file capable)
# - Keeps process alive 24/7 but only transmits during day-part window if desired.
# - Robust ffmpeg process handling and auto-restarts on error.
# - Default input is RTSP; change to dshow as needed.

import os
import sys
import time
import subprocess
import datetime
import shlex
from pathlib import Path


LOG_FILE = Path("/root/bwb_services.log")


def log_event(component: str, message: str) -> None:
    """Append a timestamped entry to the shared services log."""

    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp} [{component}] {message}\n"
    try:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        # Logging should never interrupt the streaming loop.
        pass


def _load_env_files():
    """Populate os.environ with values from nearby .env files."""
    script_dir = Path(__file__).resolve().parent
    env_paths = [
        script_dir / ".env",
        script_dir.parent / ".env",
        Path.cwd() / ".env",
    ]

    seen = set()
    for path in env_paths:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            with path.open("r", encoding="utf-8") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if len(value) >= 2 and (
                        (value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")
                    ):
                        value = value[1:-1]
                    os.environ.setdefault(key, value)
        except OSError:
            continue


_load_env_files()


def _resolve_yt_url():
    url = os.environ.get("YT_URL", "").strip()
    if url:
        return url

    key = os.environ.get("YT_KEY", "").strip()
    if key:
        return f"rtmps://a.rtmps.youtube.com/live2/{key}"

    print("[primary] ERRO: defina YT_URL ou YT_KEY (consulte README).", file=sys.stderr)
    sys.exit(2)


# === CONFIG (edit if needed) ===
# YouTube Primary URL (lido de variáveis/env file)
YT_URL = _resolve_yt_url()

# Day window (Africa/Luanda time offset — overridable via env)
DAY_START_HOUR = int(os.environ.get("YT_DAY_START_HOUR", "8"))
DAY_END_HOUR = int(os.environ.get("YT_DAY_END_HOUR", "19"))
TZ_OFFSET_HOURS = int(
    os.environ.get("YT_TZ_OFFSET_HOURS", "1")
)  # Luanda currently UTC+1


# FFmpeg input/output (example: RTSP)
def _split_args(value: str, default: list[str]) -> list[str]:
    value = value.strip()
    if not value:
        return default
    return shlex.split(value)


INPUT_ARGS = _split_args(
    os.environ.get("YT_INPUT_ARGS", ""),
    [
        "-rtsp_transport",
        "tcp",
        "-rtsp_flags",
        "prefer_tcp",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-use_wallclock_as_timestamps",
        "1",
        "-i",
        "rtsp://BEACHCAM:QueriasEntrar123@10.0.254.50:554/Streaming/Channels/101",
    ],
)
OUTPUT_ARGS = _split_args(
    os.environ.get("YT_OUTPUT_ARGS", ""),
    [
        "-vf",
        "scale=1920:1080:flags=bicubic,format=yuv420p",
        "-r",
        "30",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-profile:v",
        "high",
        "-level",
        "4.2",
        "-b:v",
        "5000k",
        "-maxrate",
        "6000k",
        "-bufsize",
        "12000k",
        "-g",
        "60",
        "-sc_threshold",
        "0",
        "-pix_fmt",
        "yuv420p",
        "-filter:a",
        (
            "aresample=async=1:first_pts=0,"
            " aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"
        ),
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-ac",
        "2",
    ],
)

FFMPEG = os.environ.get("FFMPEG", r"C:\bwb\ffmpeg\bin\ffmpeg.exe")


def in_day_window(now_utc=None):
    if now_utc is None:
        now_utc = datetime.datetime.utcnow()
    local = now_utc + datetime.timedelta(hours=TZ_OFFSET_HOURS)
    return DAY_START_HOUR <= local.hour < DAY_END_HOUR


def run_loop():
    print(
        "===== START {} =====".format(
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    )
    print(
        "CMD:",
        FFMPEG,
        "-hide_banner -loglevel warning",
        *INPUT_ARGS,
        *OUTPUT_ARGS,
        "-f",
        "flv",
        YT_URL,
    )
    log_event("primary", "Streaming loop started")
    while True:
        if not in_day_window():
            # Still keep process alive but don't transmit: short sleep and re-check
            print("[primary] Night period — holding (no transmit).")
            time.sleep(30)
            continue

        cmd = [
            FFMPEG,
            "-hide_banner",
            "-loglevel",
            "warning",
            *INPUT_ARGS,
            *OUTPUT_ARGS,
            "-f",
            "flv",
            YT_URL,
        ]
        log_event("primary", "Launching ffmpeg process")
        proc = subprocess.Popen(cmd)
        try:
            code = proc.wait()
            print(f"[primary] ffmpeg exited code {code}; restarting in 5s.")
            log_event("primary", f"ffmpeg exited with code {code}; retrying in 5s")
            time.sleep(5)
        except KeyboardInterrupt:
            try:
                proc.terminate()
            except Exception:
                pass
            print("[primary] Stopped by user.")
            log_event("primary", "Streaming loop interrupted by user")
            break

    log_event("primary", "Streaming loop finished")


if __name__ == "__main__":
    run_loop()
