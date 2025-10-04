# OPERATIONS

## Verificar fallback

```
systemctl status youtube-fallback --no-pager -l
journalctl -fu youtube-fallback -l
ss -tnp | grep -Ei 'youtube|rtmps|ffmpeg' || pgrep -fa ffmpeg
```

## YouTube API (debug rápido)

```
python3 /root/bwb-stream2yt/linux-secondary/yt_api_probe_once.py
```

## Decider (se usado)

- Ver `journalctl -u yt-decider-daemon -f -l`
- CSV de eventos (se existir) em `/root/yt_decider_log.csv`.
