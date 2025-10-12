# Diagnóstico da app Windows (2025-10-12 16:25 UTC)

## Contexto
- A app Windows foi reportada como "a correr sem receber sinal da câmara".
- No droplet, o monitor ativa o fallback "life" em vez do padrão `smptehdbars` esperado.
- Foi analisado o ficheiro de log `logs/stream2yt-diags2025-10-12T162555.00.txt`.

## Observações principais
- O diagnóstico aponta `Sinal da câmara: indisponível (ffprobe excedeu timeout de 7.0s)`.
- O worker principal encontra-se no estado `não inicializado`, indicando que a pipeline de streaming não chegou a arrancar.
- O `ffprobe` localiza-se em `C:\bwb\ffmpeg\bin\ffprobe.exe` e está acessível, mas a verificação obrigatória do sinal falhou.
- Último erro registado: `ffprobe excedeu timeout de 7.0s` durante o probe obrigatório.
- O heartbeat continua ativo e configurado para o endpoint `http://104.248.134.44:8080/status`.
- O RTSP alvo configurado é `rtsp://BEACHCAM:***@10.0.254.50:554/Streaming/Channels/101` com transporte TCP e `nobuffer` ativado.

## Interpretação
- O timeout de 7s sugere que a câmara não respondeu em tempo útil via RTSP (possível indisponibilidade da câmara, problemas de rede ou credenciais).

## Clarificação sobre os modos de fallback
- Quando a app Windows fica sem internet e deixa de conseguir falar com o droplet, o monitor muda para o padrão "life".
- Quando a app Windows tem internet, consegue comunicar, mas confirma que não está a receber imagem da câmara, o monitor deve utilizar o padrão "smptehdbars".

## Esclarecimento direto
- Resposta (não técnica): **Sim**, a app Windows está a comunicar ao servidor no droplet que não recebe sinal da câmara, logo deveria estar em modo "smptehdbars".

## Porque é que o monitor continua em "life"?
- Explicação (não técnica): o monitor mantém o último modo de fallback em que entrou enquanto não recebe uma ordem de reinício. Como a última falha foi de comunicação (sem internet), ele ficou preso no "life". Agora que a app voltou a falar com o droplet e informa que não há sinal de câmara, falta apenas reiniciar o fallback para que passe para "smptehdbars".

