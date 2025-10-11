# CODER_GUIDE

## Objetivo

- Manter transmissão **primária** (Windows) e garantir **backup** no **Droplet** quando não há dados/erros na primária.
- Minimizar falsos positivos: desligar/ligar o fallback com histerese/tempo de estabilização.

## O que procurar neste repo

- **primary-windows/**: app `stream_to_youtube.py` para enviar RTSP/DirectShow → RTMP(S) primário (A-endpoint do YouTube).
- **secondary-droplet/**:
  - `bin/youtube_fallback.sh`: envia slate 720p 30fps para **backup** (B-endpoint do YouTube).
  - `systemd/youtube-fallback.service`: unit systemd.
  - `bin/bwb_status_monitor.py`: serviço HTTP que recebe heartbeats do primário e comanda o fallback.
  - `bin/yt_api_probe_once.py`: utilitário de debug (lista `liveStreams`/health).
  - `tools/regen_token.py`: fluxo OAuth (gerar `token.json` noutro host com browser).

## Tarefas pedidas

1. **Monitor e heartbeats**:
   - garantir que o `bwb_status_monitor.py` reage apenas à ausência/presença de heartbeats;
   - evitar oscilações com thresholds configuráveis via env.

2. **Auto-recuperação** do fallback:
   - se ffmpeg crashar, systemd relança (já feito). Ajustar `RestartSec` se necessário.

3. **Atualizador de droplet**:
   - Criar utilitário que, a partir do branch `my-sty`, faça sync incremental para 104.248.134.44 (porta 2202),
     **sem** copiar `.env`, `token.json`, `client_secret.json`.
   - Após sync, executa `scripts/post_deploy.sh` no droplet para `daemon-reload` e restarts controlados.

## Estilo e limites

- Não introduzir segredos no código.
- Manter os caminhos e nomes de serviços conforme o `DEPLOY.md`.
- Não alterar *silentemente* os nomes das systemd units.

