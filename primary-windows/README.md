# primary-windows

Ferramenta oficial para enviar o feed (RTSP/DirectShow) para a URL **primária** do YouTube.

## Utilização rápida

- O executável roda em **modo headless** e mantém o FFmpeg ativo em segundo plano enquanto houver janela de transmissão configurada. Utilize os logs gerados automaticamente para acompanhar o estado do worker.
- Caso ainda não tenha obtido os arquivos locais, siga o passo a passo de download descrito em [docs/primary-windows-instalacao.md](../docs/primary-windows-instalacao.md#11-obter-o-repositorio-git-ou-zip).

## Notas de versão

- **Minimização automática do console (Windows):** ao arrancar o `stream_to_youtube.py` interativamente, a janela do console é minimizada com `SW_SHOWMINNOACTIVE` e redimensionada para um tamanho compacto. Isso evita que a aplicação roube o foco do operador e mantém o terminal discreto durante a transmissão.

### Executável distribuído

- Siga o [guia de instalação](../docs/primary-windows-instalacao.md#2-executável-distribuído) para posicionar o `stream_to_youtube.exe` em `C:\myapps\`. A primeira execução gera automaticamente o `.env` ao lado do binário; edite-o em seguida para informar `YT_KEY`/`YT_URL`. Caso deixe `YT_INPUT_ARGS` em branco, basta preencher `RTSP_HOST`/`RTSP_PORT`/`RTSP_PATH` (e, se necessário, `RTSP_USERNAME`/`RTSP_PASSWORD`) para que o script monte o endereço RTSP automaticamente. O valor padrão de `FFMPEG` aponta para `C:\bwb\ffmpeg\bin\ffmpeg.exe`, mas é possível sobrescrevê-lo nesse arquivo se desejar outro diretório.
- A execução gera arquivos diários em `C:\myapps\logs\bwb_services-YYYY-MM-DD.log` (retenção automática de sete dias). Utilize-os para homologar a conexão com o YouTube.
- O controle é feito diretamente via flags: execute `stream_to_youtube.exe /start` (ou apenas `stream_to_youtube.exe`) para iniciar o worker e `stream_to_youtube.exe /stop` para interromper. O aplicativo mantém `stream_to_youtube.pid` com o PID ativo e usa a sentinela `stream_to_youtube.stop` para sinalizar a parada; ambos ficam no mesmo diretório do executável.

### Código-fonte (desenvolvimento)

1. Configure as variáveis de ambiente:
   - A primeira execução gera `src/.env` automaticamente a partir do template `src/.env.example`; edite `YT_URL`/`YT_KEY`, argumentos e credenciais antes de iniciar a transmissão.
   - Alternativamente, defina as variáveis manualmente antes de executar (`set YT_KEY=xxxx`).
2. Execute a partir de `primary-windows/src/` (o `.env` é lido automaticamente):
   ```bat
   setlocal
   cd /d %~dp0src
   python -c "from stream_to_youtube import run_forever; run_forever()"
   ```

## Configuração (variáveis opcionais)

`stream_to_youtube.py` aceita overrides através de variáveis ou do `.env`:

- `YT_DAY_START_HOUR`, `YT_DAY_END_HOUR` e `YT_TZ_OFFSET_HOURS` controlam a janela de transmissão.
- `YT_INPUT_ARGS` / `YT_OUTPUT_ARGS` permitem ajustar os argumentos do ffmpeg. Se `YT_INPUT_ARGS` ficar vazio, o script tenta montar a URL RTSP com `RTSP_HOST`, `RTSP_PORT`, `RTSP_PATH` e, opcionalmente, `RTSP_USERNAME`/`RTSP_PASSWORD`.
- `FFMPEG` aponta para o executável do ffmpeg (por omissão `C:\bwb\ffmpeg\bin\ffmpeg.exe`; defina outro caminho no `.env` se preferir).
- `BWB_LOG_FILE` define o caminho base dos logs. Gravamos arquivos diários no formato
  `<nome>-YYYY-MM-DD.log` e mantemos automaticamente somente os últimos sete dias.

## Build (one-file) com PyInstaller

- Utilize o kit offline documentado em [`primary-windows/via-windows/`](./via-windows/README.md) para reproduzir o executável oficial com Python 3.11, requirements e o `stream_to_youtube.spec` configurado com os mesmos parâmetros da pipeline.
- O `build.bat` presente nesse diretório executa o PyInstaller com `--onefile` e `--noconsole`, gerando `dist/stream_to_youtube.exe` pronto para distribuição.
- O script `prepare-env.bat` cria o ambiente virtual e instala as dependências necessárias antes do build.

> ⚠️ Antes de lançar o `.exe`, certifique-se de que `YT_URL` ou `YT_KEY` estão definidos no ambiente ou num `.env` ao lado do executável. Nunca embuta chaves no binário.
