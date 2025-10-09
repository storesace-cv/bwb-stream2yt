# 2025-10-09 — YouTube fallback em conflito com ingest primário

## Resumo do alerta
A consola do YouTube reportou, entre as 15:09 e as 15:10 (hora de Luanda), que as ingestões "Principal" e "Cópia de segurança" recebiam vídeo com resoluções e framerates diferentes, em simultâneo. Esse alerta só ocorre quando ambas as URLs estão a receber dados e os perfis de codificação não coincidem.

## O que o log da droplet mostra
O ficheiro `tests/droplet_logs/time_line_droplet_091025_1515.log` regista eventos do systemd em UTC. O decider usa um `TZ_OFFSET` de +1 para Luanda, portanto 14:10 UTC corresponde a 15:10 locais, coincidindo com a janela do alerta.【F:secondary-droplet/bin/yt_decider_daemon.py†L18-L23】

Na janela 14:10:32–14:14:03 UTC o serviço `youtube-fallback.service` foi arrancado e interrompido repetidamente em ciclos de ~20 s, apesar de ser mandado parar. Cada arranque volta a empurrar vídeo de 720p para a ingest de backup:

- 14:10:53 → serviço iniciado; 14:11:15 → parado.【F:tests/droplet_logs/time_line_droplet_091025_1515.log†L20985-L20990】
- 14:11:36 → iniciado; 14:11:57 → parado.【F:tests/droplet_logs/time_line_droplet_091025_1515.log†L20992-L20997】
- 14:12:18 → iniciado; 14:12:39 → parado.【F:tests/droplet_logs/time_line_droplet_091025_1515.log†L20999-L21004】
- 14:13:00 → iniciado; 14:13:21 → parado.【F:tests/droplet_logs/time_line_droplet_091025_1515.log†L21017-L21021】
- 14:13:42 → iniciado; 14:14:03 → parado.【F:tests/droplet_logs/time_line_droplet_091025_1515.log†L21025-L21033】

Como o script de fallback gera continuamente uma slate a 1280×720@30 fps, com bitrates predefinidos, sempre que o serviço está activo o YouTube recebe um fluxo com parâmetros diferentes do feed principal (1080p60), disparando o alerta de discrepância.【F:secondary-droplet/bin/youtube_fallback.sh†L26-L37】【F:secondary-droplet/bin/youtube_fallback.sh†L113-L178】

## Interpretação
O decider diurno deveria desligar o fallback após três ciclos consecutivos com o primário "good/ok" (`STOP_OK_STREAK = 3`). Porém, assim que o serviço é parado ele é reactivado no ciclo seguinte, indicando que o decider continuou a interpretar o estado do primário como "mau" (`streamStatus`≠`active` ou `health` ∈ {`noData`,`bad`,…}) e volta a chamar `start_fallback()`.【F:secondary-droplet/bin/yt_decider_daemon.py†L218-L246】 Sem consultar `/root/bwb_services.log` não é possível ver a mensagem exacta (`decision_csv`) que levou a cada decisão, mas o padrão sugere que o primário ainda não era considerado estável.

## Recomendações imediatas
1. Abrir `/root/bwb_services.log` na droplet e filtrar as entradas `[yt_decider]` entre 14:09–14:15 UTC para confirmar o `stream_status` e o `health` que motivaram cada arranque/paragem.
2. Se o primário já estava a emitir vídeo válido, avaliar se é necessário aumentar `STOP_OK_STREAK` ou relaxar os estados considerados "maus" para evitar reactivação prematura enquanto o YouTube ainda está a comparar ingestões.
3. Confirmar manualmente (via `systemctl status youtube-fallback`) se o serviço ficou parado após as 14:14 UTC; caso contrário, forçar `systemctl disable --now youtube-fallback.service` antes do início do directo principal.
