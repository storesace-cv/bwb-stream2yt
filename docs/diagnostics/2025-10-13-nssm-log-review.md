# Revisão dos logs gerados pelo serviço NSSM (2025-10-13)

## Contexto
- Serviço criado manualmente via `nssm` para executar `stream_to_youtube.exe`.
- Foram disponibilizados três ficheiros em `logs/`:
  1. `bwb_services-2025-10-13.log`
  2. `stream2yt-service-startup.log`
  3. `heartbeat-status.jsonl  # valor padrão gerado automaticamente`

## Observações principais
- O arranque inicial decorreu sem erros, com PID 8380 registado e resolução configurada para 360p. O log de arranque confirma a limpeza de sentinelas e a validação da configuração antes de iniciar o loop principal.【F:logs/stream2yt-service-startup.log†L1-L9】【F:logs/bwb_services-2025-10-13.log†L1-L7】
- O `ffprobe` não foi encontrado no caminho predefinido (`C:\caminho\para\ffprobe.exe`), pelo que a verificação do sinal da câmara foi desativada automaticamente. Esta ausência surge tanto no log principal como nos registos de heartbeat.【F:logs/bwb_services-2025-10-13.log†L7-L10】【F:logs/heartbeat-status.jsonl  # valor padrão gerado automaticamente†L1-L12】
- O endpoint de heartbeat inclui espaços no URL (`http://104.248.134.44:8080/status  `), causando erros `InvalidURL` a cada tentativa. Apesar disso, o processo principal manteve-se ativo e a instância do `ffmpeg` (PID 9780) arrancou, enviando frames com bitrate estável entre 1000-1500 kbps.【F:logs/bwb_services-2025-10-13.log†L11-L18】【F:logs/heartbeat-status.jsonl  # valor padrão gerado automaticamente†L12-L28】

## Recomendações
- **Corrigir o URL do heartbeat** removendo espaços sobrantes no ficheiro de configuração para restabelecer o envio de estatísticas.
- **Instalar ou referenciar corretamente o `ffprobe`** para reativar as verificações de sinal da câmara e permitir diagnósticos automáticos mais completos.
- Verificar se o `nssm` continua a gerar o `stream2yt-service-startup.log` em cada arranque; se o serviço migrar para esta abordagem em definitivo, considerar integrar estes logs na rotina de recolha automática.
