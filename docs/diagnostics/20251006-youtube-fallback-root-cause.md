# Falha na URL secundária — análise de logs (5 de Outubro de 2025)

> **Nota histórica:** relatório elaborado antes da substituição do `yt-decider-daemon` pelo serviço `yt-restapi` (que executa `bwb_status_monitor.py`). Ajuste as recomendações conforme a arquitectura actual.

## Resumo
- O serviço `youtube-fallback` está a ser terminado repetidamente pelo OOM killer, interrompendo o envio para a URL secundária e obrigando o `systemd` a reiniciar o `ffmpeg` a cada poucos segundos.【F:tests/droplet_logs/20251005-youtube-fallback-timeline.log†L1-L24】
- A máquina tem apenas 957 MiB de RAM e **sem swap**, deixando o `ffmpeg` sem margem para estabilizar; o ficheiro de progresso mostra que apenas ~3 s de vídeo são enviados antes de cada corte.【F:diags/history/diagnostics-antes-restart-20251006-002341Z.txt†L41-L46】【F:diags/history/diagnostics-antes-restart-20251006-002341Z.txt†L618-L666】
- Durante a mesma janela, o `yt-decider-daemon` falha ao contactar `oauth2.googleapis.com` (erro DNS), perdendo a automação que poderia tentar recuperar o fallback.【F:tests/droplet_logs/20251005-youtube-fallback-timeline.log†L5-L9】【F:diags/history/diagnostics-antes-restart-20251006-002341Z.txt†L300-L348】

## Observações chave
1. **Ciclo de OOM/restart** — Entre 20:18 UTC e 23:51 UTC, o `systemd` regista múltiplos `oom-kill` seguidos de reinícios imediatos do serviço, culminando em saídas com código 143 (SIGTERM) ou 137.【F:tests/droplet_logs/20251005-youtube-fallback-timeline.log†L1-L24】 Estes eventos explicam porque a transmissão secundária desaparece do YouTube após alguns minutos: o `ffmpeg` é morto antes de conseguir manter a ligação RTMPS.
2. **Recursos insuficientes** — O snapshot do diagnóstico confirma 957 MiB de RAM total, 0 B de swap e ~412 MiB já ocupados, deixando o fallback sem buffer quando precisa de codificar vídeo H.264.【F:diags/history/diagnostics-antes-restart-20251006-002341Z.txt†L41-L46】 O ficheiro `/run/youtube-fallback.progress` prova que o processo chega apenas a 17 frames (~3,3 s) antes da interrupção.【F:diags/history/diagnostics-antes-restart-20251006-002341Z.txt†L618-L666】
3. **Automação degradada** — Logo após o primeiro `oom-kill`, o `yt-decider-daemon` tenta renovar o token OAuth e falha por DNS (`Temporary failure in name resolution`), terminando com `status=1/FAILURE` antes de reiniciar.【F:tests/droplet_logs/20251005-youtube-fallback-timeline.log†L5-L9】【F:diags/history/diagnostics-antes-restart-20251006-002341Z.txt†L300-L348】 Sem o decider estável, não há lógica extra a monitorizar e recuperar a URL secundária.

## Recomendações imediatas
1. **Mitigar pressão de memória** — Aumentar para pelo menos 2 GiB de RAM ou criar swap persistente de 1–2 GiB (`fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile`, adicionando a `/etc/fstab`). Depois de aplicar, validar com `free -h` e monitorizar `journalctl -u youtube-fallback` para confirmar ausência de novos `oom-kill`.
2. **Rever perfis do ffmpeg** — Enquanto a mitigação estrutural não chega, considerar reduzir temporariamente `-b:v`, `-maxrate` ou resolução para diminuir picos de RAM. Monitorizar `/run/youtube-fallback.progress` após cada ajuste para garantir que supera os 10–15 minutos sem interrupções.
3. **Garantir conectividade DNS** — Testar `dig oauth2.googleapis.com` na droplet; se falhar, ajustar DNS (por ex. `1.1.1.1`/`8.8.8.8`) e confirmar que a firewall permite saídas TCP/443. Reiniciar `yt-decider-daemon` após estabilizar a rede para restaurar a automação (ou verificar se o `yt-restapi` mantém heartbeats válidos na arquitectura nova).
4. **Adicionar alerta proactivo** — Configurar monitorização para eventos `oom-kill` e falhas do `yt-decider` (ex. `journalctl --since` com scripts cron ou Prometheus) para detectar regressões antes de impactarem o YouTube. Hoje, complemente com alertas para ausência de heartbeats e reinícios do `yt-restapi`.

## Próximos passos
- Após estabilizar os serviços, recolher novos logs (`journalctl -u youtube-fallback --since "-2h"`) e anexar à pasta `tests/droplet_logs/` para comparação histórica.
- Documentar qualquer alteração de bitrate/resolução aplicada, mantendo `/etc/youtube-fallback.env` e o repositório (`secondary-droplet/config/youtube-fallback.env`) sincronizados.
