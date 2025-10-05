# primary-windows

Ferramenta oficial para enviar o feed (RTSP/DirectShow) para a URL **primária** do YouTube.

## Utilização rápida

- O executável roda em **modo headless** e mantém o FFmpeg ativo em segundo plano enquanto houver janela de transmissão configurada. Utilize os logs gerados automaticamente para acompanhar o estado do worker.
- Caso ainda não tenha obtido os arquivos locais, siga o passo a passo de download descrito em [docs/primary-windows-instalacao.md](../docs/primary-windows-instalacao.md#11-obter-o-repositorio-git-ou-zip).

### Executável distribuído

- Siga o [guia de instalação](../docs/primary-windows-instalacao.md#2-executável-distribuído) para posicionar o `stream_to_youtube.exe` em `C:\myapps\`. A primeira execução gera automaticamente o `.env` ao lado do binário; edite-o em seguida para informar `YT_KEY`/`YT_URL`, argumentos do FFmpeg e credenciais RTSP conforme o equipamento.
- A execução gera arquivos diários em `C:\myapps\logs\bwb_services-YYYY-MM-DD.log` (retenção automática de sete dias). Utilize-os para homologar a conexão com o YouTube.
- Para instalar o serviço do Windows, execute o binário uma vez com `stream_to_youtube.exe /service`. Em seguida:
  - Inicie com `stream_to_youtube.exe /start`.
  - Interrompa com `stream_to_youtube.exe /stop`.
  - Remova com `stream_to_youtube.exe /noservice`.
  Todos os comandos registram eventos no log compartilhado descrito acima.

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
- `FFMPEG` aponta para o executável do ffmpeg (por omissão `C:\myapps\ffmpeg\bin\ffmpeg.exe`).
- `BWB_LOG_FILE` define o caminho base dos logs. Gravamos arquivos diários no formato
  `<nome>-YYYY-MM-DD.log` e mantemos automaticamente somente os últimos sete dias.

## Serviço do Windows

O executável expõe flags para administrar a instalação do serviço `BWBStreamToYouTube`:

```bat
stream_to_youtube.exe /service   & rem instala/atualiza o serviço apontando para o executável atual
stream_to_youtube.exe /start     & rem inicia o serviço registrado
stream_to_youtube.exe /stop      & rem interrompe o serviço
stream_to_youtube.exe /noservice & rem remove o serviço do Windows
```

O serviço executa o mesmo worker da versão em foreground (com logs em `logs\bwb_services-*.log`). Após instalar, abra `services.msc` para ajustar credenciais ou comportamento de inicialização se necessário.

## Build (one-file) com PyInstaller

- Utilize o kit offline documentado em [`primary-windows/via-windows/`](./via-windows/README.md) para reproduzir o executável oficial com Python 3.11, requirements e o `stream_to_youtube.spec` configurado com os mesmos parâmetros da pipeline.
- O `build.bat` presente nesse diretório executa o PyInstaller com `--onefile`, `--noconsole` e inclui automaticamente os binários do `pywin32`, gerando `dist/stream_to_youtube.exe` pronto para distribuição.
- O script `prepare-env.bat` cria o ambiente virtual e instala as dependências necessárias antes do build.

> ⚠️ Antes de lançar o `.exe`, certifique-se de que `YT_URL` ou `YT_KEY` estão definidos no ambiente ou num `.env` ao lado do executável. Nunca embuta chaves no binário.
