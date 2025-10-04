# BWB Stream2YT

Two-module setup:
- `primary-windows/` → streams camera to **YouTube Primary** (Windows).
- `secondary-droplet/` → backup slate stream to **YouTube Backup** (Linux, DigitalOcean).

> The `docs/` folder also ships `youtube-data-api.v3.discovery.json`, an offline copy of the YouTube Data API discovery document for tooling without external network access.

## Quick start

### Primary (Windows)
1. Install Python 3.11 and PyInstaller.
2. Configure the stream credentials via environment variables or a `.env` file:
   - `YT_URL` — URL completo `rtmps://a.rtmps.youtube.com/live2/<KEY>`.
   - `YT_KEY` — apenas a chave; o URL é construído automaticamente.
   Copie `primary-windows/src/.env.example` para `.env` (no mesmo diretório) ou defina as variáveis antes de executar.
3. Ajuste `primary-windows/src/stream_to_youtube.py` apenas se precisar alterar o dispositivo de entrada.
4. Build: `py -3.11 -m pip install -U pyinstaller==6.10` then `py -3.11 -m PyInstaller --clean --onefile primary-windows/src/stream_to_youtube.py`.
5. Run the generated `dist/stream_to_youtube.exe`, garantindo que `YT_URL` ou `YT_KEY` estejam presentes no ambiente.

### Secondary (Droplet)
1. Defaults ship in `/usr/local/config/youtube-fallback.defaults`; adjust there if the standard slate settings need to change.
2. Put stream key in `/etc/youtube-fallback.env` (`YT_KEY="..."`). Use this file only for secrets or conscious overrides.
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
secondary-droplet/
  bin/
    youtube_fallback.sh
    yt_decider_daemon.py
    yt_api_probe_once.py
  config/
    youtube-fallback.defaults
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
  youtube-data-api.v3.discovery.json
```
