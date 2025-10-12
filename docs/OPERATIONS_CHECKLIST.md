# Operations Checklist

## Daily sanity
- `systemctl status yt-restapi youtube-fallback`
- `systemctl show -p NoNewPrivileges yt-restapi.service` deve indicar `NoNewPrivileges=no`
- `journalctl -u yt-restapi -n 60 -l --no-pager`
- `tail -n 100 /root/bwb_services.log` (event log para primário, fallback e daemon)

### Log centralizado (`/root/bwb_services.log`)
- Consultar com `less +F /root/bwb_services.log` para acompanhar eventos em tempo real.
- O ficheiro inclui todos os eventos anteriormente registados no CSV `yt_decider_log`, além dos estados dos serviços primário e fallback.
- A rotação de 24h é automática via logrotate (mantém apenas eventos das últimas 24 horas).
- Rodar manualmente se necessário: `logrotate -f /etc/logrotate.d/bwb-services`.

## If backup URL reuses `${YT_KEY}` literal
- Confirmar que `/etc/youtube-fallback.d/life.env` e `bars.env` contêm a URL correta (`YT_URL="rtmp://.../CHAVE"`).
- `yt-fallback current` deve indicar o perfil ativo; use `yt-fallback set life|bars` conforme necessário.
- Garantir que `/etc/youtube-fallback.env` é um symlink válido para o perfil pretendido.
- `systemctl daemon-reload && systemctl restart youtube-fallback`

## Night/Day behaviour
- **Night**: keep backup ON if primary absent.
- **Day**: stop backup if primary healthy; keep ON if primary absent.
