# Operations Checklist

## Daily sanity
- `systemctl status yt-decider-daemon youtube-fallback`
- `journalctl -u yt-decider-daemon -n 60 -l --no-pager`
- `tail -n 50 /root/yt_decider_log.csv`

## If backup URL reuses `${YT_KEY}` literal
- Confirm `/etc/youtube-fallback.env` contains only `YT_KEY="..."
- Ensure **no** `YT_URL_BACKUP` line remains stale.
- `systemctl daemon-reload && systemctl restart youtube-fallback`

## Night/Day behaviour
- **Night**: keep backup ON if primary absent.
- **Day**: stop backup if primary healthy; keep ON if primary absent.
