# BWB Stream2YT — Overview

This repository contains **two logical modules**:

1) **Primary (Windows)** — `primary-windows/`
   - Real camera ingest (RTSP/dshow) → **YouTube Primary** (rtmps://a.rtmps.youtube.com/live2/<KEY>)
   - Always-on process, but **muted (no transmission)** between `08:00–19:00 Africa/Luanda` is disabled here. The Windows app enforces day-part rules if desired.
   - Built with **PyInstaller (one-file)** on Windows.

2) **Secondary (Droplet/Linux)** — `secondary-droplet/`
   - Always-ready **backup/“slate”** stream to **YouTube Backup** (rtmps://b.rtmps.youtube.com/live2?backup=1/<KEY>).
   - `yt-decider-daemon` decides when to **start/stop** backup based on YouTube Live API health:
     - Starts if **noData/inactive** or **health=bad** while primary is absent.
     - Stops during daytime when the primary is good.
   - Managed via `systemd` units.


## Key paths on production droplet

- Token: `/root/token.json` (Google OAuth — YouTube API)
- Decider: `/usr/local/bin/yt_decider_daemon.py`
- Fallback sender: `/usr/local/bin/youtube_fallback.sh`
- Fallback env: `/etc/youtube-fallback.env`
- Unit files: `/etc/systemd/system/*.service`
- Logs (csv): `/root/yt_decider_log.csv`

> **Stream Key**: manter apenas em ficheiros `.env` / secrets seguros; nunca o commits no repositório público.
