# Guia rápido — Logs do `youtube-fallback`

Este guia explica onde encontrar e como interpretar os logs que ajudam a diagnosticar paragens no envio da URL secundária do YouTube.

## 1. Log principal do serviço

O serviço `youtube-fallback` corre como uma unidade `systemd`. Os registos ficam disponíveis via `journalctl`:

```bash
sudo journalctl -u youtube-fallback -n 200
```

Use `-f` para seguir em tempo real ou `--since "2025-10-05 20:00"` para delimitar o período a analisar. Os eventos mais úteis são:

- `Serviço iniciado (PID XXXX)` — confirma um arranque automático.
- `Recebido SIGTERM, encerrando` / `exit 255` — indica que o serviço recebeu uma ordem externa para terminar.
- Mensagens `ffmpeg` logo após o arranque (por exemplo, `Failed to update header with correct duration.`) — podem revelar erros na ligação ao RTMP.

O ficheiro `logs/bwb_services_004.log` deste repositório é um exemplo real exportado da droplet, mostrando reinícios sucessivos quando o serviço recebe SIGTERM.【F:logs/bwb_services_004.log†L1-L35】

## 2. Ficheiro de progresso do `ffmpeg`

Além do journal, o serviço gera `/run/youtube-fallback.progress` com actualizações a cada ~30 s. No repositório, essas entradas são arquivadas em `logs/bwb_services_004.log` sob a tag `[youtube_fallback] Progresso ffmpeg`. Se estas linhas deixarem de aparecer ou o valor `frame=` estagnar, o `ffmpeg` deixou de enviar dados e deve procurar o motivo nos restantes logs.【F:logs/readme.md†L6-L24】

Para inspeccionar directamente na droplet:

```bash
sudo tail -f /run/youtube-fallback.progress
```

## 3. Correlacionar com outros serviços

Quando o fallback pára, verifique também o `yt-decider-daemon`, responsável por decidir quando activar/desactivar o envio secundário:

```bash
sudo journalctl -u yt-decider-daemon -n 200
```

Erros de autenticação (por exemplo, falhas ao contactar `oauth2.googleapis.com`) podem impedir a retoma automática. A análise detalhada de 6 de Outubro de 2025 (`docs/diagnostics/20251006-secondary-backup.md`) mostra como uma combinação de OOM killer e problemas DNS causou paragens recorrentes.【F:docs/diagnostics/20251006-secondary-backup.md†L1-L61】

## 4. Próximos passos sugeridos

1. **Confirmar causa imediata** — procurar no `journalctl` por `exit`/`SIGTERM` e mensagens de erro do `ffmpeg`.
2. **Verificar recursos** — usar `free -h` e `ps --sort=-%mem` para garantir que há RAM suficiente; o OOM killer termina o serviço quando a memória escasseia.
3. **Monitorizar após correcções** — depois de aplicar ajustes (ex.: aumentar memória ou corrigir DNS), monitorizar os logs durante 10–15 min para assegurar estabilidade.

Seguindo estes passos, terá evidências concretas para explicar porque é que o envio pela URL secundária foi interrompido e poderá actuar rapidamente na droplet.
