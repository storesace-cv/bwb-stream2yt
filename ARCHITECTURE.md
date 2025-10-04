# ARCHITECTURE

```
bwb-stream2yt/
├─ primary-windows/        # App de envio (Windows)
│  ├─ README.md
│  └─ src/
│     ├─ stream_to_youtube.py
│     └─ .env.example
│
├─ secondary-droplet/      # Fallback + Decider (Droplet Ubuntu)
│  ├─ bin/
│  │  ├─ youtube_fallback.sh
│  │  ├─ yt_decider_daemon.py
│  │  └─ yt_api_probe_once.py
│  ├─ config/
│  │  └─ youtube-fallback.env.example
│  ├─ requirements.txt
│  ├─ systemd/
│  │  ├─ youtube-fallback.service
│  │  └─ yt-decider-daemon.service
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
