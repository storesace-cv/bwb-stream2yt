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

## Decider (se usado)

- Ver `journalctl -u yt-decider-daemon -f -l`
- Consultar o histórico consolidado em `/root/bwb_services.log` (contém decisões do decider, eventos do fallback e notas do primário).

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
