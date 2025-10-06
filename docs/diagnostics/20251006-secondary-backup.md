# Diagnóstico 2025-10-06 — Falha no envio pela URL secundária do YouTube

Fonte: [`diags/history/diagnostics-antes-restart-20251006-002341Z.txt`](../../diags/history/diagnostics-antes-restart-20251006-002341Z.txt)

## Resumo
- O `youtube-fallback.service`, responsável por enviar o slate para a URL secundária, está a ser terminado repetidamente pelo OOM killer (código de saída 137) e por falhas subsequentes do `ffmpeg` logo após o reinício.
- A máquina analisada tem apenas 957 MiB de RAM disponível e **sem swap**, com ~412 MiB já utilizados no momento da recolha, o que deixa pouca margem para o `ffmpeg` operar de forma estável.
- A queda do serviço secundário coincide temporalmente com falhas no `yt-decider-daemon`, que não consegue contactar `oauth2.googleapis.com` (falhas DNS temporárias) para renovar as credenciais, impedindo qualquer automatização de recuperação.

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
1. **Mitigar falta de memória**
   - Aumentar a memória RAM do droplet ou configurar swap (por ex. 1–2 GiB) para evitar que o kernel elimine o processo `ffmpeg` durante picos de uso.
   - Rever parâmetros de `ffmpeg`/resolução/bitrate caso não seja possível aumentar recursos.
2. **Verificar conectividade DNS/Internet**
   - Garantir que o servidor consegue resolver `oauth2.googleapis.com` de forma estável (verificar `/etc/resolv.conf`, firewall, eventuais problemas de rede temporários).
3. **Monitorizar recuperação automática**
   - Confirmar se, após estabilizar os pontos acima, o `yt-decider-daemon` volta a gerir o fallback e se o stream secundário retoma de forma contínua.

