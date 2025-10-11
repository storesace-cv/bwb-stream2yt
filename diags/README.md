# Diagnostic tooling for the secondary stream

Esta pasta contém a aplicação responsável por recolher informação de diagnóstico
sobre a stack da URL secundária. O objectivo é simplificar a recolha de dados
quando o backup não está a enviar vídeo para a ingestão do YouTube.

## Estrutura

- `run_diagnostics.py`: script principal que executa todas as verificações e
  produz um ficheiro de relatório.
- `monitor_heartbeat_window.py`: observa, durante uma janela temporária
  (60 s por defeito), os heartbeats recebidos do primário e confirma se o
  fallback está a actuar conforme esperado.
- `history/`: directório ignorado pelo Git onde os relatórios gerados são
  guardados. Pode ser limpo sempre que necessário.

## Pré-requisitos

O script foi desenhado para ser executado directamente na droplet secundária,
onde os serviços `ytc-web-backend`, `yt-restapi` e `youtube-fallback`
estão configurados via `systemd`. É necessário Python 3.8+.

## Execução

```bash
cd /root/bwb-stream2yt/diags
./run_diagnostics.py --label "antes-restart"
```

Para uma verificação rápida da comunicação no próximo minuto:

```bash
cd /root/bwb-stream2yt/diags
./monitor_heartbeat_window.py
```

O script apresenta, no terminal, o número de heartbeats recebidos, o intervalo
médio, o estado reportado pelo monitor (`fallback_active`) e o estado real do
serviço `youtube-fallback.service`, indicando se a URL secundária está a
emitir ou parada.

O comando acima cria um ficheiro em `history/diagnostics-<timestamp>.txt` com
os seguintes blocos de informação:

1. **Informações de sistema**: versão do SO, uptime, utilização de disco,
   versões de Python/ffmpeg e sockets em escuta.
2. **Serviços principais**: estado e últimos registos (`journalctl`) das
   unidades `ytc-web-backend`, `yt-restapi` e `youtube-fallback`.
3. **Ambiente**: conteúdos relevantes (com a chave `YT_KEY` mascarada) de
   `/etc/youtube-fallback.env`, do ficheiro de defaults em
   `/usr/local/config/youtube-fallback.defaults`, do progresso actual do
   ffmpeg e do log partilhado em `/root/bwb_services.log`.
4. **Repositório**: estado do Git para confirmar que a droplet está alinhada
   com o repositório.

## Personalização

- Use `--services` para acrescentar ou remover unidades `systemd`.
- Use `--commands` para adicionar comandos extra (em JSON), por exemplo:
  `./run_diagnostics.py --commands '["curl", "-fsS", "http://127.0.0.1:8081/api/live-status"]'`.
- Use `--log-path`, `--env-path`, `--defaults-path` ou `--progress-path` caso o
  deployment utilize localizações alternativas.

## Automatização futura

O script é pensado para ser sincronizado via `scripts/deploy_to_droplet.sh` e
executado manualmente sempre que precisarmos de um snapshot completo dos
serviços secundários.
