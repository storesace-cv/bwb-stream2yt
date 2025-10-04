# Operations Checklist

## Daily sanity
- `systemctl status yt-decider-daemon youtube-fallback`
- `journalctl -u yt-decider-daemon -n 60 -l --no-pager`
- `tail -n 100 /root/bwb_services.log` (event log para primário, fallback e daemon)

### Log centralizado (`/root/bwb_services.log`)
- Consultar com `less +F /root/bwb_services.log` para acompanhar eventos em tempo real.
- O ficheiro inclui todos os eventos anteriormente registados no CSV `yt_decider_log`, além dos estados dos serviços primário e fallback.
- A rotação de 24h é automática via logrotate (mantém apenas eventos das últimas 24 horas).
- Rodar manualmente se necessário: `logrotate -f /etc/logrotate.d/bwb-services`.

## If backup URL reuses `${YT_KEY}` literal
- Confirm `/etc/youtube-fallback.env` contains only `YT_KEY="..."
- Ensure **no** `YT_URL_BACKUP` line remains stale.
- `systemctl daemon-reload && systemctl restart youtube-fallback`

## Night/Day behaviour
- **Night**: keep backup ON if primary absent.
- **Day**: stop backup if primary healthy; keep ON if primary absent.
