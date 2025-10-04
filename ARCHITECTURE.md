# ARCHITECTURE

```
bwb-stream2yt/
├─ windows-primary/        # App de envio (Windows)
│  ├─ stream_to_youtube.py
│  ├─ stream_to_youtube.spec
│  ├─ README.md
│  └─ example.env
│
├─ linux-secondary/        # Fallback + Decider (Droplet Ubuntu)
│  ├─ youtube_fallback.sh
│  ├─ youtube-fallback.service
│  ├─ youtube-fallback.env.example
│  ├─ yt_decider_daemon.py
│  ├─ yt_api_probe_once.py
│  ├─ regen_token.py
│  └─ requirements.txt
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
