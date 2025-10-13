# Revisão dos logs gerados pelo serviço NSSM (2025-10-13)

## Contexto
- Serviço criado manualmente via `nssm` para executar `stream_to_youtube.exe`.
- Foram disponibilizados três ficheiros em `logs/`:
  1. `bwb_services-2025-10-13.log`
  2. `stream2yt-service-startup.log`
  3. `heartbeat-status.jsonl  # valor padrão gerado automaticamente`

## Observações principais
- O arranque inicial continua a decorrer sem erros, com PID 8380 registado e resolução configurada para 360p. O log de arranque confirma a limpeza de sentinelas e a validação da configuração antes de iniciar o loop principal.【F:logs/stream2yt-service-startup.log†L1-L9】【F:logs/bwb_services-2025-10-13.log†L1-L7】
- O `ffprobe` permanece ausente do caminho configurado (`C:\caminho\para\ffprobe.exe`). O processo volta a desativar a verificação do sinal da câmara no arranque e os heartbeats reportam o erro `[WinError 2]` ao tentar invocar a ferramenta.【F:logs/bwb_services-2025-10-13.log†L7-L10】【F:logs/heartbeat-status.jsonl  # valor padrão gerado automaticamente†L1-L28】
- O endpoint de heartbeat ainda contém espaços sobrantes (`http://104.248.134.44:8080/status  `), levando a falhas `InvalidURL` a cada tentativa e impedindo a telemetria externa, apesar do `ffmpeg` se manter ativo (PID 9780).【F:logs/bwb_services-2025-10-13.log†L11-L18】【F:logs/heartbeat-status.jsonl  # valor padrão gerado automaticamente†L1-L28】

## Estado das recomendações anteriores
| Item | Resultado da verificação | Evidências |
| --- | --- | --- |
| Corrigir o URL do heartbeat | **Não resolvido** – os pedidos ainda falham com `InvalidURL` devido a espaços adicionais. | `bwb_services-2025-10-13.log` regista falhas contínuas e o ficheiro JSONL preserva o endpoint mal formatado.【F:logs/bwb_services-2025-10-13.log†L11-L18】【F:logs/heartbeat-status.jsonl  # valor padrão gerado automaticamente†L1-L28】 |
| Instalar/ajustar o `ffprobe` | **Não resolvido** – a rotina ainda sinaliza o executável em falta e desativa a verificação da câmara. | Mensagem `ffprobe ausente` no log principal e erros `[WinError 2]` no heartbeat.【F:logs/bwb_services-2025-10-13.log†L7-L10】【F:logs/heartbeat-status.jsonl  # valor padrão gerado automaticamente†L12-L28】 |
| Verificar a emissão do log de serviço | **Resolvido** – `stream2yt-service-startup.log` volta a ser criado em cada arranque, confirmando o fluxo de arranque pelo NSSM. | O ficheiro de arranque documenta todo o processo de inicialização sem erros adicionais.【F:logs/stream2yt-service-startup.log†L1-L9】 |
