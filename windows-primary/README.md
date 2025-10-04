# windows-primary

Ferramenta para enviar vídeo (RTSP/DirectShow) para a URL **primária** do YouTube.

## Utilização rápida

1. Configure as variáveis de ambiente:
   - Copie `.env.example` para `.env` e edite `YT_URL` ou `YT_KEY`; ou
   - Defina-as manualmente antes de executar (`set YT_KEY=xxxx`).
2. Execute no diretório do script (o ficheiro `.env` será lido automaticamente):
   ```bat
   setlocal
   python stream_to_youtube.py
   ```

## Build (one-file) com PyInstaller

- Use Python 3.11 para evitar problemas do 3.13 com PyInstaller.
- Instale dependências e faça o build:

```
py -3.11 -m pip install -U pip wheel
py -3.11 -m pip install -U pyinstaller==6.10
py -3.11 -m PyInstaller --clean --onefile stream_to_youtube.spec
```

O executável ficará em `dist/`.

> ⚠️ Antes de lançar o `.exe`, certifique-se de que `YT_URL` ou `YT_KEY` estão definidos no ambiente (`set YT_KEY=...` ou coloque um `.env` ao lado do executável). Nenhuma chave deve ser embutida no binário.
