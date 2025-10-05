# Guia de instalação do módulo primário (Windows)

Este guia explica como preparar um host Windows para executar o módulo **primary-windows**, priorizando o uso do executável distribuído (`C:\bwb\apps\YouTube\stream_to_youtube.exe`) e mantendo a execução via código-fonte como alternativa de manutenção.

## 1. Preparação do host Windows

1. **Organize as pastas padrão da BWB**:
   - Crie `C:\bwb\apps\YouTube\` para armazenar o executável e arquivos auxiliares.
   - Garanta permissão de escrita para o usuário que operará o serviço (necessário para criação de logs).
2. **Instale o FFmpeg e configure o caminho padrão**:
   - Crie a pasta `C:\bwb\ffmpeg\bin\`.
   - Copie ou extraia `ffmpeg.exe` (e os demais binários do pacote FFmpeg) para esse diretório.
   - O módulo procura o executável em `C:\bwb\ffmpeg\bin\ffmpeg.exe` através da variável `FFMPEG`; se preferir outro local, ajuste essa variável no `.env`.
3. **(Opcional) Prepare o ambiente de desenvolvimento**:
   - Instale o Python 3.11 caso seja necessário executar diretamente a partir do código-fonte ou gerar novos builds com o PyInstaller.
   - Obtenha o repositório `bwb-stream2yt` (via Git ou ZIP) somente se for atuar nessa modalidade.

## 2. Executável distribuído

1. **Posicione o binário oficial** em `C:\bwb\apps\YouTube\stream_to_youtube.exe`.
2. **Crie o arquivo de configuração**:
   - No mesmo diretório do executável, copie `example.env` (quando fornecido) para `.env` ou crie o arquivo manualmente.
   - Defina ao menos `YT_KEY=<CHAVE_DO_STREAM>`.
   - Opcionalmente informe `YT_URL` (`rtmps://a.rtmps.youtube.com/live2/<CHAVE>`) caso queira fixar a URL completa.
   - Ajuste `FFMPEG` apenas se o binário estiver em local diferente do padrão `C:\bwb\ffmpeg\bin\ffmpeg.exe`.
3. **Execute o serviço**:
   - Abra um *Prompt de Comando*, navegue até `C:\bwb\apps\YouTube\` e rode `stream_to_youtube.exe`; também é possível criar um atalho ou agendamento apontando para esse caminho.
   - O `.env` será carregado automaticamente durante a inicialização do executável.
4. **Verifique os logs**:
   - Os registros são gravados em `C:\bwb\apps\YouTube\logs\bwb_services.log` (a pasta `logs\` é criada se necessário).
   - Utilize esse arquivo para confirmar a inicialização do FFmpeg e eventuais erros de autenticação.
5. **Homologação rápida**:
   - Confirme, durante o primeiro teste, se o YouTube recebe o stream na URL primária e se o log indica status `connected`.

## 3. Execução via código-fonte

1. **Requisitos**:
   - Python 3.11 instalado e acessível no `PATH`.
   - Repositório `bwb-stream2yt` disponível localmente (clone ou pacote ZIP extraído).
2. **Configuração do `.env`**:
   - No diretório `primary-windows\src\`, copie `example.env` (ou `.env.example`) para `.env`.
   - Preencha as variáveis `YT_KEY` e, se desejado, `YT_URL` e demais parâmetros (`YT_INPUT_ARGS`, `YT_OUTPUT_ARGS`, `FFMPEG`, etc.).
3. **Execução**:
   - Abra um *Prompt de Comando* em `primary-windows\src\` e execute `python stream_to_youtube.py`.
   - O log compartilhado é gravado em `primary-windows\src\logs\bwb_services.log`.
4. **Validação**:
   - Monitore o mesmo log para verificar a inicialização do FFmpeg e confirme a recepção do stream no painel do YouTube.

## 4. Build one-file com PyInstaller (referência)

1. Instale o PyInstaller (exige Python 3.11):
   ```bat
   py -3.11 -m pip install -U pip wheel
   py -3.11 -m pip install -U pyinstaller==6.10
   ```
2. Gere o executável a partir do diretório `primary-windows\`: `py -3.11 -m PyInstaller --clean --onefile src/stream_to_youtube.py`.
3. O binário será produzido em `dist/stream_to_youtube.exe` e deve ser movido para `C:\bwb\apps\YouTube\` junto com um `.env` válido.
4. Durante a distribuição, reforce a necessidade do `ffmpeg.exe` presente em `C:\bwb\ffmpeg\bin\` ou documente o caminho alternativo via variável `FFMPEG`.

## 5. Checklist de verificação

- [ ] `stream_to_youtube.exe` posicionado em `C:\bwb\apps\YouTube\`.
- [ ] `.env` criado no mesmo diretório com `YT_KEY` (e, se necessário, `YT_URL`/`FFMPEG`).
- [ ] `ffmpeg.exe` disponível em `C:\bwb\ffmpeg\bin\` ou caminho ajustado na configuração.
- [ ] Execução do executável gera `C:\bwb\apps\YouTube\logs\bwb_services.log` sem erros críticos.
- [ ] Dashboard do YouTube confirma conexão do stream durante o teste.
- [ ] (Opcional) Ambiente Python 3.11 preparado para manutenção via código-fonte ou geração de novos builds.

Seguindo estes passos, o host Windows estará pronto para transmitir pelo módulo primário com segurança e previsibilidade, seja utilizando o executável distribuído ou o código-fonte.
