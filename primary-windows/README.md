# primary-windows

Ferramenta oficial para enviar o feed (RTSP/DirectShow) para a URL **primária** do YouTube.

## Utilização rápida

- O executável roda em **modo headless** e mantém o FFmpeg ativo em segundo plano enquanto houver janela de transmissão configurada. Utilize os logs gerados automaticamente para acompanhar o estado do worker.
- Caso ainda não tenha obtido os arquivos locais, siga o passo a passo de download descrito em [docs/primary-windows-instalacao.md](../docs/primary-windows-instalacao.md#11-obter-o-repositorio-git-ou-zip).

## Notas de versão

- **Minimização automática do console (Windows):** ao arrancar o `stream_to_youtube.py` interativamente, a janela do console é minimizada com `SW_SHOWMINNOACTIVE` e redimensionada para um tamanho compacto. Isso evita que a aplicação roube o foco do operador e mantém o terminal discreto durante a transmissão.

### Executável distribuído

- Siga o [guia de instalação](../docs/primary-windows-instalacao.md#2-executável-distribuído) para posicionar o `stream_to_youtube.exe` em `C:\myapps\`. A primeira execução gera automaticamente o `.env` ao lado do binário; edite-o em seguida para informar `YT_KEY`/`YT_URL`. Caso deixe `YT_INPUT_ARGS` em branco, basta preencher `RTSP_HOST`/`RTSP_PORT`/`RTSP_PATH` (e, se necessário, `RTSP_USERNAME`/`RTSP_PASSWORD`) para que o script monte o endereço RTSP automaticamente. O valor padrão de `FFMPEG` aponta para `C:\bwb\ffmpeg\bin\ffmpeg.exe`, mas é possível sobrescrevê-lo nesse arquivo se desejar outro diretório.
- Sempre que o template for atualizado (novas variáveis ou remoções), o `stream_to_youtube.py` faz backup automático do `.env` existente, gera uma cópia atualizada com os novos parâmetros (pré-preenchidos com valores padrão) e comenta qualquer opção obsoleta para revisão manual.
- A execução gera arquivos diários em `C:\myapps\logs\bwb_services-YYYY-MM-DD.log` (retenção automática de sete dias). Utilize-os para homologar a conexão com o YouTube.
- O controle é feito diretamente via flags: execute `stream_to_youtube.exe --start` (ou apenas `stream_to_youtube.exe`) para iniciar o worker e `stream_to_youtube.exe --stop` para interromper. Ao iniciar, é possível informar a resolução desejada — `stream_to_youtube.exe --start --360p`, `stream_to_youtube.exe --start --720p` ou `stream_to_youtube.exe --start --1080p`. O aplicativo mantém `stream_to_youtube.pid` com o PID ativo e usa a sentinela `stream_to_youtube.stop` para sinalizar a parada; ambos ficam no mesmo diretório do executável. Adicione a flag opcional `--showonscreen` (por exemplo, `stream_to_youtube.exe --start --showonscreen`) para impedir a minimização automática do console e acompanhar em tempo real cada log gravado durante a execução.

### Execução como Serviço do Windows

O diretório `src/` inclui `windows_service.py`, um *launcher* dedicado que registra o emissor como serviço do Windows, ocultando a janela de console e mantendo apenas um PID ativo (o *service host* do SCM).

#### Executável (`stream2yt-service.exe`)

1. Posicione `stream2yt-service.exe` (e o respetivo `.env`) numa pasta estável, por exemplo `C:\myapps\stream2yt-service\`.
2. Abra um `PowerShell` com privilégios de administrador e navegue até essa pasta.
3. Registe e inicie o serviço (adicione `--startup auto` se quiser *auto-start* após reboot):
   ```powershell
   .\stream2yt-service.exe install --startup auto
   .\stream2yt-service.exe start
   ```
4. Para interromper/remover o serviço utilize:
   ```powershell
   .\stream2yt-service.exe stop
   .\stream2yt-service.exe remove
   ```

#### Código-fonte (`windows_service.py`)

1. Abra um `PowerShell` com privilégios de administrador e navegue até `primary-windows\src`.
2. Registe o serviço (adicione `--startup auto` se quiser *auto-start* após reboot):
   ```powershell
   python windows_service.py install --startup auto --720p
   python windows_service.py start
   ```
3. Para interromper/remover o serviço utilize:
   ```powershell
   python windows_service.py stop
   python windows_service.py remove
   ```

O wrapper regista o serviço como `stream2yt-service`, refletindo esse nome tanto no *Service Name* quanto no *Display Name* apresentados pelo SCM.

> 💡 Use as flags padrão do `win32serviceutil` caso precise especificar outra conta (`--username`/`--password`).

- Para selecionar antecipadamente a resolução aplicada em cada arranque do serviço, acrescente `--360p`, `--720p` ou `--1080p`
  ao comando `install` (ou `update`). O valor é persistido em `stream2yt-service.config.json` junto ao executável e é reutilizado
  sempre que o SCM inicializa o worker. Execute `python windows_service.py update --1080p` para voltar ao preset padrão.

#### Configuração para o serviço

- O serviço partilha o mesmo `.env` do executável. Se estiver a usar o binário, garanta que o `.env` permanece ao lado do `stream2yt-service.exe`. Caso pretenda manter os ficheiros de configuração em `%ProgramData%\stream2yt-service`, defina `BWB_ENV_DIR=%ProgramData%\stream2yt-service` antes de instalar o serviço (ou ajuste a variável de ambiente nas *System Properties*).
- Como alternativa, use `BWB_ENV_FILE`/`BWB_ENV_PATH` apontando diretamente para o ficheiro `.env`. O wrapper carrega esse ficheiro antes dos demais caminhos padrão.
- Os logs continuam a ser gravados em `logs/bwb_services-YYYY-MM-DD.log` junto ao executável ou no caminho definido por `BWB_LOG_FILE`, o que facilita a observabilidade em modo serviço.

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
- `YT_RESOLUTION` define a resolução padrão aplicada aos parâmetros de saída (`360p`, `720p` ou `1080p`). O valor pode ser sobrescrito ao iniciar o executável com `--start --<resolução>`.
- `FFMPEG` aponta para o executável do ffmpeg (por omissão `C:\bwb\ffmpeg\bin\ffmpeg.exe`; defina outro caminho no `.env` se preferir).
- `BWB_LOG_FILE` define o caminho base dos logs. Gravamos arquivos diários no formato
  `<nome>-YYYY-MM-DD.log` e mantemos automaticamente somente os últimos sete dias.

## Build (one-file) com PyInstaller

- Utilize o kit offline documentado em [`primary-windows/via-windows/`](./via-windows/README.md) para reproduzir o executável oficial com Python 3.11, requirements e o `stream_to_youtube.spec` configurado com os mesmos parâmetros da pipeline.
- O `build.bat` presente nesse diretório executa o PyInstaller com `--onefile` e `--noconsole`, gerando `dist/stream_to_youtube.exe` pronto para distribuição.
- O script `prepare-env.bat` cria o ambiente virtual e instala as dependências necessárias antes do build.

> ⚠️ Antes de lançar o `.exe`, certifique-se de que `YT_URL` ou `YT_KEY` estão definidos no ambiente ou num `.env` ao lado do executável. Nunca embuta chaves no binário.
