# OPERATIONS

## Verificar fallback

```
systemctl status youtube-fallback --no-pager -l
journalctl -fu youtube-fallback -l
ss -tnp | grep -Ei 'youtube|rtmps|ffmpeg' || pgrep -fa ffmpeg
```

## Monitor de heartbeats do primário

O serviço `bwb-status-monitor.service` recebe relatórios do Windows e aciona o
fallback quando necessário.

```
systemctl status bwb-status-monitor --no-pager -l
journalctl -u bwb-status-monitor -n 50 -l
tail -n 20 /var/log/bwb_status_monitor.log
cat /var/lib/bwb-status-monitor/status.json
```

- O ficheiro `/var/lib/bwb-status-monitor/status.json` mantém apenas os
  últimos 5 minutos de heartbeats.
- Logs da instalação: `/var/log/bwb_post_deploy.log`.

## Reset rápido da droplet secundária

Use o script `scripts/reset_secondary_droplet.sh` para libertar caches de memória e reiniciar os serviços principais (fallback, decider e backend da YTC Web). O script deve ser executado como root diretamente na droplet:

```bash
cd /root/bwb-stream2yt
sudo ./scripts/reset_secondary_droplet.sh
```

No final, o script executa `ensure-broadcast.service` para garantir que a transmissão continua agendada.

## YouTube API (debug rápido)

```
python3 /root/bwb-stream2yt/secondary-droplet/bin/yt_api_probe_once.py
```

- Offline schema for manual API calls: `/root/bwb-stream2yt/docs/youtube-data-api.v3.discovery.json`.

## Ensure broadcast manual

```
systemctl start ensure-broadcast.service
systemctl status ensure-broadcast.service --no-pager -l
journalctl -u ensure-broadcast.service -n 50 -l
```

- Saída esperada: `Status=0/SUCCESS` com log `[ensure] Transmissão ... com stream ...`.

## Decider (se usado)

- Ver `journalctl -u bwb-status-monitor -f -l`
- Consultar o histórico consolidado em `/root/bwb_services.log` (contém decisões do decider, eventos do fallback e notas do primário).

## Diagnósticos rápidos da URL secundária

- Gere um snapshot completo da droplet secundária com `./diags/run_diagnostics.py`.
- Os relatórios ficam em `diags/history/diagnostics-<timestamp>.txt` e incluem estado dos serviços, tail de logs, ficheiros de configuração relevantes e versão do repositório.
- É seguro anexar o ficheiro num ticket porque a `YT_KEY` é mascarada automaticamente.

## Testes

Use `pytest` para validar rapidamente a lógica do decider antes de qualquer deploy:

```bash
cd /root/bwb-stream2yt
python -m pip install --upgrade pip
pip install -r secondary-droplet/requirements.txt
pip install pytest
pytest
```

## Lint e formatação

Antes de subir código novo, garanta que o repositório está formatado e sem avisos de lint:

```bash
cd /root/bwb-stream2yt
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
python -m black --check .
python -m flake8
```
