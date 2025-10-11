# Diagnóstico 2025-10-06 — Falha no envio pela URL secundária do YouTube

> **Nota histórica:** este relatório descreve a arquitectura anterior baseada no `yt-decider-daemon`. Após a migração para o serviço `yt-restapi` (que executa `bwb_status_monitor.py`), substitua mentalmente as referências a esse serviço quando aplicar recomendações em ambientes actuais.

Fonte: [`diags/history/diagnostics-antes-restart-20251006-002341Z.txt`](../../diags/history/diagnostics-antes-restart-20251006-002341Z.txt)

## Resumo
- O `youtube-fallback.service`, responsável por enviar o slate para a URL secundária, está a ser terminado repetidamente pelo OOM killer (código de saída 137) e por falhas subsequentes do `ffmpeg` logo após o reinício.
- A máquina analisada tem apenas 957 MiB de RAM disponível e **sem swap**, com ~412 MiB já utilizados no momento da recolha, o que deixa pouca margem para o `ffmpeg` operar de forma estável.
- A queda do serviço secundário coincide temporalmente com falhas no `yt-decider-daemon`, que não consegue contactar `oauth2.googleapis.com` (falhas DNS temporárias) para renovar as credenciais, impedindo qualquer automatização de recuperação. (Na arquitectura recente, o serviço `yt-restapi` não depende da API do YouTube, mas continua a necessitar de conectividade com o emissor primário.)
- O mini-projecto **ytc-web** é independente destes serviços de fallback; na época, `yt-decider-daemon` e `youtube-fallback` integravam a infraestrutura de emissão secundária e deviam permanecer activos mesmo quando o backend web estava em manutenção. Hoje o serviço `yt-restapi` substitui o decider.

## Evidências principais

### Recursos do sistema
- Memória física limitada (957 MiB) e ausência de swap disponíveis: ver bloco `free -h` no diagnóstico.
- O serviço `youtube-fallback` é relançado muitas vezes e volta a consumir rapidamente CPU/memória antes de ser terminado (registos do `systemd`).

### Terminações do `youtube-fallback.service`
- Diversas entradas com `A process of this unit has been killed by the OOM killer.` entre `20:18` e `23:51 UTC` do dia 5 de Outubro, seguidas de código de saída `137` (processo terminado pelo kernel).
- Depois dos reinícios automáticos, o `ffmpeg` não chega a estabilizar a saída; o ficheiro de progresso (`/run/youtube-fallback.progress`) mostra apenas 11 frames enviados (~3,3 s de vídeo) antes da interrupção.

### Falhas do `yt-decider-daemon`
- Às `20:21:50 UTC`, o daemon termina com `ServerNotFoundError: Unable to find the server at oauth2.googleapis.com`, demonstrando problemas de resolução DNS/ligação à Internet naquele momento.
- Após a falha, o serviço é reiniciado, mas volta a parar mais tarde, deixando o fallback sem orquestração automática.

## Conclusões e próximos passos
1. **Mitigar falta de memória (bloqueador principal)**
   - Aumentar os recursos do droplet (mínimo 2 GiB de RAM) **ou** criar swap persistente de 1–2 GiB (`fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile`), adicionando ` /swapfile swap swap defaults 0 0` a `/etc/fstab` para tornar a alteração permanente.
   - Se já aumentou a RAM para 1 GiB, confirme com `free -h`/`grep MemTotal /proc/meminfo` que o SO vê efectivamente esse valor e que não existe sobre-alocação por outros serviços (`ps --sort=-%mem -eo pid,cmd,%mem | head`). Caso contrário, a pressão de memória continuará a desencadear o OOM killer mesmo com o dobro da RAM.
   - Reiniciar o `youtube-fallback.service` apenas depois de garantir que a memória adicional está disponível e confirmar que o processo `ffmpeg` já não termina com código 137 (`journalctl -u youtube-fallback --since "2025-10-05 20:00"`).
   - Caso o consumo continue elevado, ajustar o `ffmpeg` para um perfil mais leve (por exemplo, reduzir `-b:v` ou resolução) e acompanhar o impacto em `/run/youtube-fallback.progress`.
2. **Verificar conectividade DNS/Internet**
   - Validar resolução DNS para `oauth2.googleapis.com` com `dig`/`systemd-resolve`; se falhar, rever os servidores DNS configurados e garantir que a firewall (ou `ufw`) permite saídas TCP/443.
   - Assim que a conectividade for restabelecida, forçar a renovação das credenciais (`systemctl restart yt-decider-daemon`) e monitorizar `journalctl -u yt-decider-daemon` em busca de novos erros. (Em instalações actuais, valide antes se o `yt-restapi.service` permanece activo e a receber heartbeats.)
3. **Monitorizar recuperação automática**
   - Utilizar `systemctl status youtube-fallback yt-decider-daemon` para confirmar que ambos os serviços permanecem activos durante pelo menos 10–15 minutos após as correcções (substitua por `yt-restapi` nas versões actuais).
   - Adicionar alarmes em `prometheus`/`grafana` (ou scripts existentes) para alertar sobre novos eventos do OOM killer e falhas de DNS, evitando regressões futuras.

