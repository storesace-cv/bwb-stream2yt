# 2025-10-09 Stream outage investigation

## Summary
- `ensure-broadcast.service` falhou às 07:55 UTC ao chamar a API do YouTube com o parâmetro `broadcastStatus="active,upcoming"`, que não é aceito; o systemd abortou o serviço com status 1. O script agora consulta `active` e `upcoming` em chamadas separadas.
- O snapshot de recursos coletado às 09:46 UTC mostra ~107 MiB de RAM livre e 335 MiB disponíveis, sem swap configurado, indicando que o host não estava sem memória quando o relatório foi gerado.
- Não há mensagens do kernel sobre OOM killer ou processos terminados por falta de memória; o `ffmpeg` permanece em execução consumindo ~105 MiB de RAM.
- O mesmo serviço já havia falhado no dia anterior (08/10) às 07:55 UTC, sugerindo regressão de configuração ou bug recente. O script de deploy agora ativa automaticamente 512 MiB de swap para dar margem adicional.
- Apesar da falha do `ensure-broadcast.service`, o antigo `yt-decider-daemon` manteve o fallback ligado (não há transições para *off* nos logs `[yt_decider]` dentro da janela). Na arquitectura actual este papel é desempenhado pelo `bwb-status-monitor`; recolha o ficheiro `status-monitor-*.log` via `scripts/status-monitor-debug.sh` para incidentes semelhantes.

## Evidências
- Falha do serviço e mensagem de erro do script Ensure Broadcast: `tests/droplet_logs/time_line_droplet_091025_1100.log` linhas 21041-21045.
- Uso de memória e presença de `ffmpeg` em execução: `tests/droplet_logs/time_line_droplet_091025_1100.log` linhas 93-101.
- Ausência de registros do OOM killer (somente thread `oom_reaper` listado no `top`): `tests/droplet_logs/time_line_droplet_091025_1100.log` linhas 120.
- Falha do mesmo serviço em 08/10 às 07:55 UTC: `tests/droplet_logs/time_line_droplet_091025_1100.log` linhas 516-517.
- Validação manual pós-correção (rodar `systemctl start ensure-broadcast.service && systemctl status ensure-broadcast.service --no-pager` após deploy).

## Próximas ações sugeridas
1. Corrigir o parâmetro `broadcastStatus` passado para a verificação de transmissão (provavelmente enviar apenas `active` ou `upcoming`). ✅ Implementado em `secondary-droplet/bin/ensure_broadcast.py`.
2. Validar manualmente a execução de `ensure-broadcast.service` após aplicar a correção. ✅ Executar `systemctl start ensure-broadcast.service` e confirmar `Active: inactive (dead)` com `Status=0/SUCCESS`.
3. (Opcional) Configurar swap leve ou monitoramento adicional, mas não há evidências atuais de exaustão de memória. ✅ `scripts/post_deploy.sh` cria/ativa swapfile de 512 MiB caso ausente.
4. Avaliar reinícios periódicos apenas se surgirem sintomas de leak; com swap e monitorização atual não é necessário reiniciar serviços a cada 30 minutos.
5. Caso o fallback volte a comportar-se de forma errática, recolher rapidamente o pacote de evidências com `bash scripts/status-monitor-debug.sh` (ver [guia dedicado](status-monitor-debug.md)) para comparar os heartbeats recebidos com as decisões automáticas.
