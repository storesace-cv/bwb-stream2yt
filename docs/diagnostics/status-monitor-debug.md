# Recolha de evidências do `yt-restapi`

O script `scripts/status-monitor-debug.sh` recolhe, numa única execução, os principais artefactos para diagnosticar falhas no mecanismo de heartbeats entre o emissor primário e o fallback.

## O que o script recolhe
- **Contexto do host** (hostname, kernel e janela temporal em UTC).
- **`journalctl -u yt-restapi.service`** nas últimas 48 horas (janela configurável via `STATUS_MONITOR_WINDOW`).
- **`systemctl status yt-restapi.service`** para capturar o estado actual do serviço.
- **`/var/log/bwb_status_monitor.log`** filtrado pela janela temporal ou, se não for possível interpretar os timestamps, um `tail -n 400` de segurança.
- **`/var/lib/bwb-status-monitor/status.json`** com o histórico recente de heartbeats.
- **Resposta HTTP do endpoint `/status`** (HEAD+GET) para confirmar a disponibilidade do serviço.
- **Conteúdo de `/etc/yt-restapi.env`** com o token redigido automaticamente.

O resultado é gravado no ficheiro `status-monitor-<timestamp>.log` no directório onde o script é executado.

## Como executar na droplet
```bash
# Entrar via SSH no host secundário
ssh -p 2202 root@<ip-da-droplet>

# A partir do directório do repositório clonado na droplet
cd /root/bwb-stream2yt
bash scripts/status-monitor-debug.sh
```

Durante a execução, o script mostra o destino do ficheiro (`status-monitor-YYYYMMDDTHHMMSSZ.log`). Após concluído, transfira-o para o seu computador (por exemplo, com `scp`) ou anexe-o directamente ao relatório de incidente.

## Quando utilizar
- O fallback permaneceu desligado apesar da ausência de heartbeats do primário.
- O `yt-restapi` reinicia continuamente ou não consegue contactar o endpoint configurado.
- Necessidade de anexar evidências consolidadas a um *post-mortem*.

Para orientar a interpretação dos dados recolhidos, consulte também os guias existentes:
- [Diagnóstico da interrupção de 6 de Outubro de 2025](20251006-secondary-backup.md)
- [Checklist geral de logs do fallback](youtube-fallback-logs.md)
- [Análise da interrupção de 9 de Outubro de 2025](20251009-stream-crash.md)
