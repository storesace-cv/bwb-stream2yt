#!/usr/bin/env python3
# stream_to_youtube.py — Windows primary sender (one-file capable)
# - Keeps process alive 24/7 but only transmits during day-part window if desired.
# - Robust ffmpeg process handling and auto-restarts on error.
# - Default input is RTSP; change to dshow as needed.

import os, sys, time, subprocess, signal, datetime

# === CONFIG (edit if needed) ===
# YouTube Primary URL (hardcoded as requested)
YT_URL = "rtmps://a.rtmps.youtube.com/live2/f4ex-ztrk-vc4h-2pvc-2kg4"

# Day window (Africa/Luanda time offset)
DAY_START_HOUR = 8
DAY_END_HOUR = 19
TZ_OFFSET_HOURS = 1  # Luanda currently UTC+1

# FFmpeg input/output (example: RTSP)
INPUT_ARGS = [
    "-rtsp_transport","tcp","-rtsp_flags","prefer_tcp",
    "-fflags","nobuffer","-flags","low_delay","-use_wallclock_as_timestamps","1",
    "-i","rtsp://BEACHCAM:QueriasEntrar123@10.0.254.50:554/Streaming/Channels/101"
]
OUTPUT_ARGS = [
    "-vf","scale=1920:1080:flags=bicubic,format=yuv420p",
    "-r","30",
    "-c:v","libx264","-preset","veryfast","-profile:v","high","-level","4.2",
    "-b:v","5000k","-maxrate","6000k","-bufsize","12000k","-g","60","-sc_threshold","0",
    "-pix_fmt","yuv420p",
    "-filter:a","aresample=async=1:first_pts=0, aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo",
    "-c:a","aac","-b:a","128k","-ar","44100","-ac","2",
]

FFMPEG = os.environ.get("FFMPEG", r"C:\bwb\ffmpeg\bin\ffmpeg.exe")

def in_day_window(now_utc=None):
    if now_utc is None:
        now_utc = datetime.datetime.utcnow()
    local = now_utc + datetime.timedelta(hours=TZ_OFFSET_HOURS)
    return DAY_START_HOUR <= local.hour < DAY_END_HOUR

def run_loop():
    print("===== START {} =====".format(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    print("CMD:", FFMPEG, "-hide_banner -loglevel warning", *INPUT_ARGS, *OUTPUT_ARGS, "-f", "flv", YT_URL)
    while True:
        if not in_day_window():
            # Still keep process alive but don't transmit: short sleep and re-check
            print("[primary] Night period — holding (no transmit).")
            time.sleep(30)
            continue

        cmd = [FFMPEG, "-hide_banner", "-loglevel", "warning", *INPUT_ARGS, *OUTPUT_ARGS, "-f", "flv", YT_URL]
        proc = subprocess.Popen(cmd)
        try:
            code = proc.wait()
            print(f"[primary] ffmpeg exited code {code}; restarting in 5s.")
            time.sleep(5)
        except KeyboardInterrupt:
            try:
                proc.terminate()
            except Exception:
                pass
            print("[primary] Stopped by user.")
            break

if __name__ == "__main__":
    run_loop()
