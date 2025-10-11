# ARCHITECTURE

```
bwb-stream2yt/
├─ primary-windows/        # App de envio (Windows)
│  ├─ README.md
│  └─ src/
│     ├─ stream_to_youtube.py
│     └─ .env.example
│
├─ secondary-droplet/      # Fallback + monitor HTTP (Droplet Ubuntu)
│  ├─ bin/
│  │  ├─ youtube_fallback.sh
│  │  ├─ bwb_status_monitor.py
│  │  └─ yt_api_probe_once.py
│  ├─ config/
│  │  └─ youtube-fallback.env.example
│  ├─ requirements.txt
│  ├─ systemd/
│  │  ├─ youtube-fallback.service
│  │  └─ bwb-status-monitor.service
│  └─ tools/
│     └─ regen_token.py
│
├─ scripts/                # Deploy/atualização para o droplet
│  ├─ deploy_to_droplet.sh
│  └─ post_deploy.sh
│
├─ SECURITY.md
├─ DEPLOY.md
├─ OPERATIONS.md
└─ CODER_GUIDE.md
```
