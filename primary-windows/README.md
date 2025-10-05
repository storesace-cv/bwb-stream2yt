# primary-windows

Ferramenta oficial para enviar o feed (RTSP/DirectShow) para a URL **primária** do YouTube.

## Utilização rápida

- O executável roda em **modo headless** e mantém o FFmpeg ativo em segundo plano enquanto houver janela de transmissão configurada. Utilize os logs gerados automaticamente para acompanhar o estado do worker.
- Caso ainda não tenha obtido os arquivos locais, siga o passo a passo de download descrito em [docs/primary-windows-instalacao.md](../docs/primary-windows-instalacao.md#11-obter-o-repositorio-git-ou-zip).

### Executável distribuído

- Siga o [guia de instalação](../docs/primary-windows-instalacao.md#2-executável-distribuído) para posicionar o `stream_to_youtube.exe` em `C:\myapps\`. A primeira execução gera automaticamente o `.env` ao lado do binário; edite-o em seguida para informar `YT_KEY`/`YT_URL`, argumentos do FFmpeg e credenciais RTSP conforme o equipamento (o valor padrão de `FFMPEG` aponta para `C:\bwb\ffmpeg\bin\ffmpeg.exe`, mas é possível sobrescrevê-lo nesse arquivo se desejar outro diretório).
- A execução gera arquivos diários em `C:\myapps\logs\bwb_services-YYYY-MM-DD.log` (retenção automática de sete dias). Utilize-os para homologar a conexão com o YouTube.
- O executável mantém um arquivo `stream_to_youtube.pid` ao lado do binário para garantir execução única. Utilize `stream_to_youtube.exe /stop` para encerrar a instância em segundo plano; novas execuções (inclusive duplo clique) reutilizam o mesmo fluxo de inicialização e falham com mensagem caso já haja um processo ativo.

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
- `YT_INPUT_ARGS` / `YT_OUTPUT_ARGS` permitem ajustar os argumentos do ffmpeg.
- `FFMPEG` aponta para o executável do ffmpeg (por omissão `C:\bwb\ffmpeg\bin\ffmpeg.exe`; defina outro caminho no `.env` se preferir).
- `BWB_LOG_FILE` define o caminho base dos logs. Gravamos arquivos diários no formato
  `<nome>-YYYY-MM-DD.log` e mantemos automaticamente somente os últimos sete dias.

## Build (one-file) com PyInstaller

- Utilize o kit offline documentado em [`primary-windows/via-windows/`](./via-windows/README.md) para reproduzir o executável oficial com Python 3.11, requirements e o `stream_to_youtube.spec` configurado com os mesmos parâmetros da pipeline.
- O `build.bat` presente nesse diretório executa o PyInstaller com `--onefile` e `--noconsole`, gerando `dist/stream_to_youtube.exe` pronto para distribuição.
- O script `prepare-env.bat` cria o ambiente virtual e instala as dependências necessárias antes do build.

> ⚠️ Antes de lançar o `.exe`, certifique-se de que `YT_URL` ou `YT_KEY` estão definidos no ambiente ou num `.env` ao lado do executável. Nunca embuta chaves no binário.
