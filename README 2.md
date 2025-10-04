# BWB Stream to YouTube

Sistema automatizado de streaming redundante para o canal **BeachCam | Praia dos Surfistas | Cabo Ledo | Angola**.

Inclui:
- Transmissão RTSP → YouTube (primário e secundário);
- Decisor automático (yt-decider-daemon);
- Fallback automático (imagem + textos com FFmpeg);
- Integração com API YouTube para detecção do estado da transmissão.

## Estrutura
```
scripts/
  ├── yt_api_probe_once.py
  └── youtube_fallback.sh
systemd/
  └── youtube-fallback.service
docs/
  ├── PROJECT_OVERVIEW.md
  ├── CODING_GUIDE.md
  └── CODEX_PROMPT.md
```
