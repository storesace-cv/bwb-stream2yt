# stream2yt – versão v1.50.p

Este documento regista o estado de produção alcançado em `v1.50.p`, servindo de referência para futuras atualizações ou reversões.

## Aplicação Windows (primary-windows)

- Executável headless que mantém o FFmpeg ativo, gera logs diários com retenção automática e pode ser controlado por flags `--start/--stop`, incluindo presets de resolução e opção `--showonscreen` para acompanhar a consola.【F:primary-windows/README.md†L7-L19】
- A primeira execução cria `.env` ao lado do binário, atualiza-o automaticamente quando o template muda e aceita credenciais RTSP para montar a URL de entrada; o caminho do FFmpeg pode ser sobrescrito conforme necessário.【F:primary-windows/README.md†L16-L18】
- Disponibiliza instalador como serviço Windows (`stream2yt-service.exe`) e launcher em Python, com suporte para auto-start, preservação de configuração em `%ProgramData%`, partilha do `.env` e logs no mesmo diretório definido por `BWB_LOG_FILE`.【F:primary-windows/README.md†L23-L67】
- O modo desenvolvimento lê `src/.env`, executa diretamente `run_forever()` e aceita overrides para janela diária, argumentos do ffmpeg, resolução, caminhos de log e autotune com `psutil` para ajuste dinâmico de bitrate.【F:primary-windows/README.md†L68-L97】
- O worker recolhe snapshots do estado atual, monitoriza ping da câmara, regista heartbeat ativo/detalhes e guarda informação sobre PID, sentinela de paragem e parâmetros FFmpeg para diagnóstico rápido.【F:primary-windows/src/stream_to_youtube.py†L821-L904】
- Um `HeartbeatReporter` envia periodicamente o estado para a droplet secundária quando configurado, incluindo limites de bitrate, janela diária e sinalização de pedidos de paragem, e é encerrado com o worker.【F:primary-windows/src/stream_to_youtube.py†L1697-L1759】【F:primary-windows/src/stream_to_youtube.py†L2488-L2553】

## Stack droplet (secondary-droplet)

### Serviço de fallback

- `youtube_fallback.sh` escreve logs uniformizados, carrega defaults geridos por deploy e utiliza configuração `/etc/youtube-fallback.env` para gerar slate 1280×720 a 30 fps com textos “BEACHCAM | CABO LEDO | ANGOLA” e “VOLTAREMOS DENTRO DE MOMENTOS”.【F:secondary-droplet/bin/youtube_fallback.sh†L1-L92】【F:secondary-droplet/config/youtube-fallback.defaults†L3-L22】
- O script lê o modo desejado (`life` ou `smpte`), sanitiza a `YT_KEY`, normaliza a URL RTMPS de backup e anuncia parâmetros completos de vídeo/áudio e atraso configurado antes de iniciar o ffmpeg.【F:secondary-droplet/bin/youtube_fallback.sh†L52-L160】
- Implementa traps para sinais do systemd, encaminhando-os ao FFmpeg, e regista progressos periódicos a partir de `/run/youtube-fallback.progress`, permitindo auditar frames, bitrate e tempo de saída.【F:secondary-droplet/bin/youtube_fallback.sh†L161-L200】

### Monitor HTTP e automações

- `bwb_status_monitor.py` recebe heartbeats do emissor Windows e decide iniciar/parar o serviço `youtube-fallback.service`, expondo configuração de porta, thresholds e ficheiros de log/mode, além de autenticação opcional e ping à câmara configuráveis por variáveis de ambiente.【F:secondary-droplet/bin/bwb_status_monitor.py†L1-L207】
- O monitor suporta refresh da ingestão primária via API do YouTube após paragens, respeitando cooldown configurável e executando a ação em *thread* dedicada.【F:secondary-droplet/bin/bwb_status_monitor.py†L341-L407】
- A gestão do serviço utiliza `systemctl` (com fallback para `sudo`) para garantir arranque/paragem fiável, registando erros e orientando correções quando `NoNewPrivileges` bloqueia a elevação necessária.【F:secondary-droplet/bin/bwb_status_monitor.py†L266-L338】

### Serviços systemd e verificação da transmissão

- `yt-restapi.service` executa o monitor HTTP como utilizador dedicado com reinício automático, isolamento de sistema de ficheiros e `NoNewPrivileges=false` para permitir que o monitor controle o fallback.【F:secondary-droplet/systemd/yt-restapi.service†L1-L23】
- `youtube-fallback.service` mantém o slate secundário ativo, recarregando variáveis de `/etc/youtube-fallback.env`, com `Restart=always` e limites de *file descriptors* elevados para o FFmpeg.【F:secondary-droplet/systemd/youtube-fallback.service†L1-L18】
- `ensure-broadcast.service` agenda a verificação pontual através de `ensure_broadcast.py`, que confirma se existe transmissão ativa/upcoming associada à stream correta na API do YouTube antes de regressar com sucesso.【F:secondary-droplet/systemd/ensure-broadcast.service†L1-L12】【F:secondary-droplet/bin/ensure_broadcast.py†L1-L158】

## Como usar esta referência

Use este documento em conjunto com os guias operacionais e de deploy para introduzir mudanças incrementais. Caso precise restaurar este estado, procure o commit identificado como `v1.50.p` (que introduz esta documentação) e aplique o procedimento de reversão apropriado.
