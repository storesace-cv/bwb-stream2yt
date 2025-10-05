pasta não versionada pala colocação de ficheiros log para análise durante o desenvolvimento.

### Entradas de progresso do fallback do YouTube

O serviço `youtube_fallback.sh` passa agora a registar periodicamente linhas como:

```
2024-05-18 12:34:56 [youtube_fallback] Progresso ffmpeg: frame=900 fps=30.0 bitrate=1540.0kbits/s drop=0 tamanho=5.4MiB tempo=00:00:30
```

Estas entradas são obtidas do ficheiro `/run/youtube-fallback.progress` produzido pelo `ffmpeg` e surgem, por omissão, a cada 30 segundos (`PROGRESS_LOG_INTERVAL`).

- **frame**: número de frames de vídeo já enviados.
- **fps**: velocidade de processamento reportada pelo `ffmpeg` — útil para perceber se o encoder está a acompanhar o tempo real.
- **bitrate**: bitrate instantâneo médio do stream. Valores baixos ou instáveis podem indicar estrangulamentos de rede.
- **drop**: contagem de frames descartados por `ffmpeg`; qualquer aumento sugere problemas de desempenho.
- **tamanho**: volume total de dados enviados desde o arranque (convertido para unidades legíveis).
- **tempo**: timestamp do stream (HH:MM:SS) que ajuda a confirmar que o conteúdo está a avançar.

Quando estiver a diagnosticar interrupções, confirme se estes valores continuam a crescer. Caso deixem de aparecer entradas novas, é sinal de que o `ffmpeg` deixou de escrever progresso (ou terminou) e deve verificar o restante log para erros.
