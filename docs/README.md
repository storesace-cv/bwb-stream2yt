# BWB Stream2YT

Two-module setup:
- `primary-windows/` → streams camera to **YouTube Primary** (Windows).
- `secondary-droplet/` → backup slate stream to **YouTube Backup** (Linux, DigitalOcean).

> The `docs/` folder also ships `youtube-data-api.v3.discovery.json`, an offline copy of the YouTube Data API discovery document for tooling without external network access.

## Quick start

### Primary (Windows)

- 📘 Consulte o [guia completo de instalação no Windows](primary-windows-instalacao.md#2-executável-distribuído) para seguir o fluxo recomendado com o executável distribuído.

1. Posicione `stream_to_youtube.exe` em `C:\bwb\apps\YouTube\` e mantenha o FFmpeg em `C:\bwb\ffmpeg\bin\ffmpeg.exe`.
2. Crie um `.env` ao lado do executável com `YT_KEY=<CHAVE_DO_STREAM>` (e, se necessário, `YT_URL` ou um caminho alternativo para `FFMPEG`).
3. Rode `stream_to_youtube.exe` a partir desse diretório e verifique os logs em `C:\bwb\apps\YouTube\logs\bwb_services.log`.
4. (Opcional) Para manutenção via código-fonte ou geração de novos builds, siga as seções 3 e 4 do mesmo guia.

### Secondary (Droplet)
1. Defaults ship in `/usr/local/config/youtube-fallback.defaults`; adjust there if the standard slate settings need to change.
2. Put stream key in `/etc/youtube-fallback.env` (`YT_KEY="..."`). O `post_deploy.sh` reescreve este ficheiro preservando `YT_KEY` e restaurando as linhas comentadas com os defaults para referência — use-o apenas para segredos ou overrides conscientes.
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
