# Revisão dos logs gerados pelo serviço NSSM (2025-10-13)

## Contexto
- Serviço configurado via `nssm` para executar `stream_to_youtube.exe`.
- Foram fornecidos três ficheiros na pasta `logs/`:
  1. `stream2yt-service-startup.log`
  2. `bwb_services-2025-10-13.log`
  3. `heartbeat-status.jsonl`
- O ficheiro `logs/env/.env` acompanha os valores de configuração efetivamente carregados pelo serviço.

## Observações principais
- O arranque decorre sem erros: o log de arranque mostra a limpeza das sentinelas, o registo de PID e a validação da configuração antes do loop principal.【F:logs/stream2yt-service-startup.log†L1-L9】
- O serviço agora lê corretamente o `.env`: o log operacional regista o heartbeat em `http://104.248.134.44:8080/status` e a deteção do `ffprobe` em `C:\\bwb\\ffmpeg\\bin\\ffprobe.exe`, confirmando que os valores fornecidos estão ativos.【F:logs/bwb_services-2025-10-13.log†L1-L7】【F:logs/env/.env†L45-L60】
- Os heartbeats deixam de falhar; há respostas HTTP 200 consistentes e a telemetria reporta `ffprobe_available=true`, o que valida a correção aplicada tanto ao endpoint como ao caminho do `ffprobe`.【F:logs/bwb_services-2025-10-13.log†L7-L9】【F:logs/heartbeat-status.jsonl†L1-L3】

## Estado das recomendações anteriores
| Item | Resultado da verificação | Evidências |
| --- | --- | --- |
| Corrigir o URL do heartbeat | **Resolvido** – o serviço publica heartbeats com HTTP 200 para `http://104.248.134.44:8080/status` e sem espaços residuais. | Entradas em `bwb_services-2025-10-13.log` e `heartbeat-status.jsonl` confirmam envios bem-sucedidos.【F:logs/bwb_services-2025-10-13.log†L4-L9】【F:logs/heartbeat-status.jsonl†L1-L3】 |
| Instalar/ajustar o `ffprobe` | **Resolvido** – o processo valida `C:\\bwb\\ffmpeg\\bin\\ffprobe.exe` e os heartbeats assinalam `ffprobe_available=true`. | Log operacional e payloads de heartbeat evidenciam a deteção do binário.【F:logs/bwb_services-2025-10-13.log†L5-L7】【F:logs/heartbeat-status.jsonl†L1-L3】 |
| Verificar a emissão do log de serviço | **Resolvido** – `stream2yt-service-startup.log` é criado no arranque e cobre todas as etapas iniciais. | O ficheiro de arranque documenta todo o processo sem erros adicionais.【F:logs/stream2yt-service-startup.log†L1-L9】 |
