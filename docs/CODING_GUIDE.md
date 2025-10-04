# Coding Guide

## Python
- Target **Python 3.11** for PyInstaller one-file stability on Windows.
- Use **`subprocess.Popen`** for ffmpeg lifetime control and **graceful shutdown** on CTRL+C or service stop.
- Avoid heavy external deps; keep it pure stdlib + `google-api-python-client` for API tools on the droplet.

## ffmpeg
- Conservative defaults:
  - 1080p30 primary (Windows) with `-preset veryfast`, `-g 60`, `-b:v 5000k` (or tune for your uplink).
  - 720p30 backup (Droplet) with `-b:v 1500k`, `-g 60`, scroll/static texts overlay to indicate fallback.

## Logs
- Human-oriented console logs + ficheiro unificado (`/root/bwb_services.log`) com transições relevantes do decider e estado dos serviços.

## Windows build
- Build with **PyInstaller 6.10** (or compatible) targeting Python 3.11.
- Use the provided `stream_to_youtube.spec` for **one-file** builds.
