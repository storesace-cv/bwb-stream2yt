# CODER_GUIDE

## Objetivo

- Manter transmissão **primária** (Windows) e garantir **backup** no **Droplet** quando não há dados/erros na primária.
- Minimizar falsos positivos: desligar/ligar o fallback com histerese/tempo de estabilização.

## O que procurar neste repo

- **windows-primary/**: app `stream_to_youtube.py` para enviar RTSP/DirectShow → RTMP(S) primário (A-endpoint do YouTube).
- **linux-secondary/**:
  - `youtube_fallback.sh`: envia slate 720p 30fps para **backup** (B-endpoint do YouTube).
  - `youtube-fallback.service`: unit systemd.
  - `yt_decider_daemon.py`: decide **quando** ligar/desligar o fallback (ligar à API YouTube).
  - `yt_api_probe_once.py`: utilitário de debug (lista `liveStreams`/health).
  - `regen_token.py`: fluxo OAuth (gerar `token.json` noutro host com browser).

## Tarefas pedidas

1. **Robustez** do decider:
   - ignorar o **primeiro "Sem dados"** imediatamente após desligar o backup;
   - reforçar janela de confirmação (ex.: 2-3 iterações) antes de trocar estado.

2. **Auto-recuperação** do fallback:
   - se ffmpeg crashar, systemd relança (já feito). Ajustar `RestartSec` se necessário.

3. **Atualizador de droplet**:
   - Criar utilitário que, a partir do branch `my-sty`, faça sync incremental para 104.248.134.44,
     **sem** copiar `.env`, `token.json`, `client_secret.json`.
   - Após sync, executa `scripts/post_deploy.sh` no droplet para `daemon-reload` e restarts controlados.

## Estilo e limites

- Não introduzir segredos no código.
- Manter os caminhos e nomes de serviços conforme o `DEPLOY.md`.
- Não alterar *silentemente* os nomes das systemd units.

