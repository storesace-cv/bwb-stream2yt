# 2025-10-09 Stream outage investigation

## Summary
- `ensure-broadcast.service` falhou às 07:55 UTC ao chamar a API do YouTube com o parâmetro `broadcastStatus="active,upcoming"`, que não é aceito; o systemd abortou o serviço com status 1.
- O snapshot de recursos coletado às 09:46 UTC mostra ~107 MiB de RAM livre e 335 MiB disponíveis, sem swap configurado, indicando que o host não estava sem memória quando o relatório foi gerado.
- Não há mensagens do kernel sobre OOM killer ou processos terminados por falta de memória; o `ffmpeg` permanece em execução consumindo ~105 MiB de RAM.
- O mesmo serviço já havia falhado no dia anterior (08/10) às 07:55 UTC, sugerindo regressão de configuração ou bug recente.

## Evidências
- Falha do serviço e mensagem de erro do script Ensure Broadcast: `tests/droplet_logs/time_line_droplet_091025_1100.log` linhas 21041-21045.
- Uso de memória e presença de `ffmpeg` em execução: `tests/droplet_logs/time_line_droplet_091025_1100.log` linhas 93-101.
- Ausência de registros do OOM killer (somente thread `oom_reaper` listado no `top`): `tests/droplet_logs/time_line_droplet_091025_1100.log` linhas 120.
- Falha do mesmo serviço em 08/10 às 07:55 UTC: `tests/droplet_logs/time_line_droplet_091025_1100.log` linhas 516-517.

## Próximas ações sugeridas
1. Corrigir o parâmetro `broadcastStatus` passado para a verificação de transmissão (provavelmente enviar apenas `active` ou `upcoming`).
2. Validar manualmente a execução de `ensure-broadcast.service` após aplicar a correção.
3. (Opcional) Configurar swap leve ou monitoramento adicional, mas não há evidências atuais de exaustão de memória.
