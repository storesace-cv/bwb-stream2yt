# 2025-10-09 — YouTube fallback em conflito com ingest primário

## Resumo do alerta
A consola do YouTube reportou, entre as 15:09 e as 15:10 (hora de Luanda), que as ingestões "Principal" e "Cópia de segurança" recebiam vídeo com resoluções e framerates diferentes, em simultâneo. Esse alerta só ocorre quando ambas as URLs estão a receber dados e os perfis de codificação não coincidem.

## O que o log da droplet mostra
O ficheiro `tests/droplet_logs/time_line_droplet_091025_1515.log` regista eventos do systemd em UTC. O decider usa um `TZ_OFFSET` de +1 para Luanda, portanto 14:10 UTC corresponde a 15:10 locais, coincidindo com a janela do alerta.【F:secondary-droplet/bin/yt_decider_daemon.py†L18-L23】

Entre 14:02 e 14:14 UTC o serviço é ligado/desligado quase a cada ciclo de decisão de 20 s, com apenas um período mais longo (1m22) imediatamente antes das 14:10. Exemplos:

- 14:02:05 → serviço iniciado; 14:02:26 → parado.【F:tests/droplet_logs/time_line_droplet_091025_1515.log†L20892-L20907】
- 14:04:11 → iniciado; 14:04:33 → parado.【F:tests/droplet_logs/time_line_droplet_091025_1515.log†L20925-L20930】
- 14:05:36 → iniciado; 14:05:57 → parado.【F:tests/droplet_logs/time_line_droplet_091025_1515.log†L20939-L20944】
- 14:09:50 → paragem após 1m22 de slate contínua.【F:tests/droplet_logs/time_line_droplet_091025_1515.log†L20973-L20976】
- 14:10:53 → iniciado; 14:11:15 → parado.【F:tests/droplet_logs/time_line_droplet_091025_1515.log†L20985-L20990】
- 14:11:36 → iniciado; 14:11:57 → parado.【F:tests/droplet_logs/time_line_droplet_091025_1515.log†L20992-L20997】
- 14:12:18 → iniciado; 14:12:39 → parado.【F:tests/droplet_logs/time_line_droplet_091025_1515.log†L20999-L21004】
- 14:13:00 → iniciado; 14:13:21 → parado.【F:tests/droplet_logs/time_line_droplet_091025_1515.log†L21017-L21021】
- 14:13:42 → iniciado; 14:14:03 → parado.【F:tests/droplet_logs/time_line_droplet_091025_1515.log†L21025-L21033】

Como o script de fallback gera continuamente uma slate a 1280×720@30 fps, com bitrates predefinidos, sempre que o serviço está activo o YouTube recebe um fluxo com parâmetros diferentes do feed principal (1080p60), disparando o alerta de discrepância.【F:secondary-droplet/bin/youtube_fallback.sh†L26-L37】【F:secondary-droplet/bin/youtube_fallback.sh†L113-L178】

## Interpretação
O decider diurno deveria desligar o fallback após três ciclos consecutivos com o primário "good/ok" (`STOP_OK_STREAK = 3`). Porém, assim que o serviço é parado ele é reactivado no ciclo seguinte, indicando que o decider continuou a interpretar o estado do primário como "mau" (`streamStatus`≠`active` ou `health` ∈ {`noData`,`bad`,…}) e volta a chamar `start_fallback()`.【F:secondary-droplet/bin/yt_decider_daemon.py†L194-L244】 A captura `time_line_droplet_091025_1515.log` não inclui as linhas `[yt_decider]`, pelo que não é possível confirmar, a partir deste ficheiro, qual o `stream_status`/`health` recebido em cada ciclo.【1209fb†L1-L2】

Enquanto o YouTube está a verificar a ingest principal, é comum devolver `streamStatus='testing'` ou `health='noData'` durante alguns ciclos antes de estabilizar. Como ambos são tratados como estados "maus", o contador `primary_ok_streak` volta sempre a zero e o fallback é religado assim que o serviço é desligado.【F:secondary-droplet/bin/yt_decider_daemon.py†L194-L239】 Isto sugere dois caminhos complementares:

- **Aumentar a tolerância a falsos negativos:** elevar `STOP_OK_STREAK` (actualmente 3) para permitir alguns ciclos adicionais de comparação do YouTube antes de desligar definitivamente o fallback.【F:secondary-droplet/bin/yt_decider_daemon.py†L22-L24】【F:secondary-droplet/bin/yt_decider_daemon.py†L232-L243】
- **Relaxar os estados "maus" pós-reactivação:** considerar `streamStatus` em `{testing, liveStarting}` com `health='noData'` como aceitáveis durante o arrefecimento, ou introduzir um cooldown que impeça novo `start_fallback()` durante X ciclos após um `STOP`.

## Recomendações imediatas
1. Recolher `/root/bwb_services.log` (ou `journalctl -u yt-decider-daemon`) directamente na droplet e filtrar as entradas `[yt_decider]` entre 14:09–14:15 UTC, visto que o snapshot disponibilizado não contém esses registos. Isto permitirá confirmar os pares `stream_status`/`health` que motivaram cada arranque/paragem.
2. Aplicar uma alteração temporária nos thresholds (`STOP_OK_STREAK` maior ou cooldown adicional) e monitorizar se o primário estabiliza sem reactivar o fallback enquanto o YouTube ainda compara ingestões.【F:secondary-droplet/bin/yt_decider_daemon.py†L22-L24】【F:secondary-droplet/bin/yt_decider_daemon.py†L232-L244】
3. O ficheiro termina às 14:14 UTC; validar nos logs actuais (`journalctl -u youtube-fallback --since '2025-10-09 14:14'`) o arranque/paragem reportado às 14:41 UTC e garantir que o serviço permanece parado após a verificação do primário.
