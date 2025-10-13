# Revisão dos logs gerados pelo serviço NSSM (2025-10-13)

## Contexto
- Serviço criado manualmente via `nssm` para executar `stream_to_youtube.exe`.
- Foram disponibilizados três ficheiros em `logs/`:
  1. `bwb_services-2025-10-13.log`
  2. `stream2yt-service-startup.log`
  3. `heartbeat-status.jsonl  # valor padrão gerado automaticamente`

## Observações principais
- O arranque inicial continua a decorrer sem erros, com PID 8380 registado e resolução configurada para 360p. O log de arranque confirma a limpeza de sentinelas e a validação da configuração antes de iniciar o loop principal.【F:logs/stream2yt-service-startup.log†L1-L9】【F:logs/bwb_services-2025-10-13.log†L1-L7】
- A aplicação continua a registar no log o caminho `C\caminho\para\ffprobe.exe  # valor padrão gerado automaticamente` e a desativar a verificação da câmara, o que provoca erros `[WinError 2]` nos heartbeats.【F:logs/bwb_services-2025-10-13.log†L7-L10】【F:logs/heartbeat-status.jsonl  # valor padrão gerado automaticamente†L1-L28】
- A configuração real, no entanto, já aponta para `C\bwb\ffmpeg\bin\ffprobe.exe`, pelo que a ocorrência acima sugere que o serviço ainda está a arrancar com valores de template (provavelmente porque o `.env` atualizado não foi lido durante este ciclo).【F:logs/env/.env†L1-L56】
- Algo semelhante ocorre com o endpoint: os heartbeats falham com `InvalidURL` devido ao sufixo "  # valor padrão gerado automaticamente", mas o ficheiro `.env` mostra `http://104.248.134.44:8080/status` sem espaços adicionais. Recomenda-se validar se o serviço foi reiniciado após a alteração ou se existe outro ficheiro `.env` prioritário.【F:logs/bwb_services-2025-10-13.log†L5-L18】【F:logs/heartbeat-status.jsonl  # valor padrão gerado automaticamente†L1-L28】【F:logs/env/.env†L57-L78】

## Estado das recomendações anteriores
| Item | Resultado da verificação | Evidências |
| --- | --- | --- |
| Corrigir o URL do heartbeat | **Não confirmado** – os pedidos desta execução ainda falham com `InvalidURL`, possivelmente porque o serviço não recarregou o `.env` atualizado. | Log do serviço e heartbeat continuam a incluir o sufixo `# valor padrão gerado automaticamente`, embora o `.env` esteja correto.【F:logs/bwb_services-2025-10-13.log†L5-L18】【F:logs/heartbeat-status.jsonl  # valor padrão gerado automaticamente†L1-L28】【F:logs/env/.env†L57-L78】 |
| Instalar/ajustar o `ffprobe` | **Não confirmado** – a execução ainda reporta `[WinError 2]`, mas a configuração aponta para `C\bwb\ffmpeg\bin\ffprobe.exe`. | Logs desta amostra versus valores presentes em `logs/env/.env` sugerem que o binário pode não estar no caminho esperado pelo processo atual.【F:logs/bwb_services-2025-10-13.log†L7-L10】【F:logs/heartbeat-status.jsonl  # valor padrão gerado automaticamente†L12-L28】【F:logs/env/.env†L33-L56】 |
| Verificar a emissão do log de serviço | **Resolvido** – `stream2yt-service-startup.log` volta a ser criado em cada arranque, confirmando o fluxo de arranque pelo NSSM. | O ficheiro de arranque documenta todo o processo de inicialização sem erros adicionais.【F:logs/stream2yt-service-startup.log†L1-L9】 |
