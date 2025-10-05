# primary-windows

Ferramenta oficial para enviar o feed (RTSP/DirectShow) para a URL **primária** do YouTube.

## Utilização rápida

1. Configure as variáveis de ambiente:
   - Copie `src/.env.example` para `src/.env` e edite `YT_URL` ou `YT_KEY`; ou
   - Defina-as manualmente antes de executar (`set YT_KEY=xxxx`).
2. Execute a partir de `primary-windows/src/` (o `.env` é lido automaticamente):
   ```bat
   setlocal
   cd /d %~dp0src
   python stream_to_youtube.py
   ```

## Configuração (variáveis opcionais)

`stream_to_youtube.py` aceita overrides através de variáveis ou do `.env`:

- `YT_DAY_START_HOUR`, `YT_DAY_END_HOUR` e `YT_TZ_OFFSET_HOURS` controlam a janela de transmissão.
- `YT_INPUT_ARGS` / `YT_OUTPUT_ARGS` permitem ajustar os argumentos do ffmpeg.
- `FFMPEG` aponta para o executável do ffmpeg (por omissão `C:\bwb\ffmpeg\bin\ffmpeg.exe`).
- `BWB_LOG_FILE` define onde o log compartilhado é gravado. Por padrão usamos
  `logs/bwb_services.log` ao lado do script/executável, criando a pasta
  automaticamente no Windows.

## Build (one-file) com PyInstaller

- Use Python 3.11 para evitar problemas do 3.13 com o PyInstaller.
- Instale dependências e faça o build:

```bat
py -3.11 -m pip install -U pip wheel
py -3.11 -m pip install -U pyinstaller==6.10
py -3.11 -m PyInstaller --clean --onefile src/stream_to_youtube.py
```

O executável ficará em `dist/stream_to_youtube.exe`.

> ⚠️ Antes de lançar o `.exe`, certifique-se de que `YT_URL` ou `YT_KEY` estão definidos no ambiente ou num `.env` ao lado do executável. Nunca embuta chaves no binário.
