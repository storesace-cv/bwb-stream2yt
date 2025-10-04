# BWB Stream2YT

Two-module setup:
- `primary-windows/` → streams camera to **YouTube Primary** (Windows).
- `secondary-droplet/` → backup slate stream to **YouTube Backup** (Linux, DigitalOcean).

## Quick start

### Primary (Windows)
1. Install Python 3.11 and PyInstaller.
2. Edit `primary-windows/src/stream_to_youtube.py` (input device) and set `YT_URL` to your **primary URL**.
3. Build: `py -3.11 -m pip install -U pyinstaller==6.10` then `py -3.11 -m PyInstaller --clean primary-windows/stream_to_youtube.spec`.
4. Run the generated `dist/stream_to_youtube.exe`.

### Secondary (Droplet)
1. Put stream key in `/etc/youtube-fallback.env` (`YT_KEY="..."`).  
2. Install units & scripts from `secondary-droplet/` and run:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now youtube-fallback.service
   sudo systemctl enable --now yt-decider-daemon.service
   ```

### Deploy tool
- Configure `deploy/deploy_config.json` with SSH user/identity.
- Run: `python3 deploy/update_droplet.py --dry-run` then without `--dry-run` to apply.


## Folder structure

```
primary-windows/
  src/
    stream_to_youtube.py
  stream_to_youtube.spec

secondary-droplet/
  bin/
    youtube_fallback.sh
    yt_decider_daemon.py
    yt_api_probe_once.py
  config/
    youtube-fallback.env.example
  systemd/
    youtube-fallback.service
    yt-decider-daemon.service
  tools/
    regen_token.py

deploy/
  update_droplet.py
  deploy_config.json

docs/
  PROJECT_OVERVIEW.md
  CODING_GUIDE.md
  CODEX_PROMPT.md
  OPERATIONS_CHECKLIST.md
```
