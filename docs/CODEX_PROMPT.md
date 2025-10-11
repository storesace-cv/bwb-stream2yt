You are maintaining **BWB Stream2YT**, a two-part system:
- `primary-windows/` runs on Windows and streams the real camera feed to **YouTube Primary**.
- `secondary-droplet/` runs on Ubuntu and streams a slate to **YouTube Backup**, controlado pelo serviço `yt-restapi` (executa `bwb_status_monitor.py`) via heartbeats enviados pelo primário.

Your tasks:
1. Keep modules **separated** by platform.
2. Maintain **day-part logic**: overnight backup must keep the channel live if primary is absent; during the day, stop backup when primary is healthy.
3. Ensure **resilience**: restart policies, clean logs, and robust ffmpeg args.
4. Implement and maintain **deploy tool** `deploy/update_droplet.py` that syncs changes in `secondary-droplet/` to droplet `104.248.134.44` (SSH port 2202) over SSH, with dry-run and include/exclude rules.
5. Do not hardcode secrets; read the YouTube stream key from env files.

Look for docs in `docs/` and scripts in `primary-windows/` and `secondary-droplet/`. Follow the README checklists.
