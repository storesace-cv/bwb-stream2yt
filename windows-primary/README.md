# windows-primary

Ferramenta para enviar vídeo (RTSP/DirectShow) para a URL **primária** do YouTube.

## Utilização rápida

1. Configure as variáveis (exemplo em `example.env`).
2. Execute:
   ```bat
   setlocal
   call example.env
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
