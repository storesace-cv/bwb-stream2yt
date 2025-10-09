# OPERATIONS

## Verificar fallback

```
systemctl status youtube-fallback --no-pager -l
journalctl -fu youtube-fallback -l
ss -tnp | grep -Ei 'youtube|rtmps|ffmpeg' || pgrep -fa ffmpeg
```

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

- Ver `journalctl -u yt-decider-daemon -f -l`
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
