# Guia de instalação do módulo primário (Windows)

Este guia explica como preparar um host Windows para executar o módulo **primary-windows**, desde a instalação de dependências até a primeira transmissão e empacotamento opcional com o PyInstaller.

## 1. Pré-requisitos do host Windows

1. **Instale o Python 3.11**:
   - Baixe o instalador oficial em <https://www.python.org/downloads/windows/> e escolha a opção *Add python.exe to PATH*.
   - Verifique a instalação em um *Prompt de Comando* executando `python --version` (deve retornar `Python 3.11.x`).
2. **Obtenha o código do projeto**:
   - Via Git: `git clone https://github.com/bubble-wb/bwb-stream2yt.git` e abra o diretório `bwb-stream2yt`.
   - Via ZIP: faça o download do pacote, extraia para um diretório acessível (ex.: `C:\bwb\bwb-stream2yt`).
3. **Instale o FFmpeg e configure o caminho padrão**:
   - Crie a pasta `C:\bwb\ffmpeg\bin\`.
   - Copie ou extraia `ffmpeg.exe` (e os demais binários do pacote FFmpeg) para esse diretório.
   - O script procura automaticamente o executável em `C:\bwb\ffmpeg\bin\ffmpeg.exe` através da variável `FFMPEG`; se preferir outro local, ajuste essa variável manualmente.

## 2. Preparação das variáveis de ambiente

1. No diretório `primary-windows\src\`, copie `example`: `copy .env.example .env`.
2. Abra o novo arquivo `.env` e preencha as variáveis obrigatórias:
   - `YT_KEY`: apenas a chave do stream.
   - `YT_URL`: URL completa `rtmps://a.rtmps.youtube.com/live2/<CHAVE>` (opcional se preferir derivar a partir da `YT_KEY`).
3. Outros ajustes podem ser feitos no mesmo arquivo (ex.: horários de transmissão, parâmetros de entrada/saída do FFmpeg e caminho do log).
4. O script `stream_to_youtube.py` carrega o `.env` automaticamente durante a inicialização, portanto não é necessário executar comandos extras para exportar as variáveis.

> Se optar por definir variáveis manualmente (via `set`/`setx`), garanta que correspondam aos nomes acima; valores presentes no `.env` têm precedência quando o arquivo existe.

## 3. Primeira execução e logs

1. Abra um *Prompt de Comando* e navegue até `primary-windows\src\`.
2. Execute o script com o Python 3.11: `python stream_to_youtube.py`.
3. O log compartilhado é gravado em `logs\bwb_services.log` ao lado do script. A pasta é criada automaticamente se não existir.
4. Durante o primeiro teste, verifique no log as mensagens de inicialização do FFmpeg e confirme na interface do YouTube que o stream está conectado à URL primária.

## 4. Build one-file com PyInstaller

1. Instale o PyInstaller (exige Python 3.11):
   ```bat
   py -3.11 -m pip install -U pip wheel
   py -3.11 -m pip install -U pyinstaller==6.10
   ```
2. Gere o executável: `py -3.11 -m PyInstaller --clean --onefile src/stream_to_youtube.py`.
3. O binário será produzido em `dist/stream_to_youtube.exe`.
4. Para execução, posicione um `.env` atualizado no mesmo diretório do `.exe` (ou defina as variáveis no ambiente) e mantenha o diretório `logs\` acessível para escrita.
5. Ao distribuir o executável, inclua uma verificação manual da presença de `ffmpeg.exe` em `C:\bwb\ffmpeg\bin\` ou documente o caminho alternativo via variável `FFMPEG`.

## 5. Checklist de verificação

- [ ] Python 3.11 instalado e reportando a versão correta.
- [ ] Repositório disponível localmente (clone ou ZIP extraído).
- [ ] `ffmpeg.exe` presente em `C:\bwb\ffmpeg\bin\` e acessível.
- [ ] Arquivo `primary-windows\src\.env` preenchido com `YT_KEY` (e opcionalmente `YT_URL`).
- [ ] Execução de `python stream_to_youtube.py` gera logs em `logs\bwb_services.log`.
- [ ] Dashboard do YouTube confirma conexão na URL primária durante o teste.
- [ ] (Opcional) Build `stream_to_youtube.exe` criado e `.env` copiado para o diretório do binário.

Seguindo estes passos o host Windows estará pronto para transmitir pelo módulo primário com segurança e previsibilidade.
