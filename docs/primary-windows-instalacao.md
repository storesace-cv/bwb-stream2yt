# Guia de instalação do módulo primário (Windows)

Este guia explica como preparar um host Windows para executar o módulo **primary-windows**, priorizando o uso do executável distribuído (`C:\myapps\stream_to_youtube.exe`) e mantendo a execução via código-fonte como alternativa de manutenção.

## 1. Preparação do host Windows

1. **Organize o diretório padrão da aplicação**:
   - Crie `C:\myapps\` para armazenar o executável e arquivos auxiliares.
   - Garanta permissão de escrita para o usuário que operará o serviço (necessário para criação de logs).
2. **Instale o FFmpeg e configure o caminho padrão**:
   - Crie a pasta `C:\bwb\ffmpeg\bin\` (ou adapte caso utilize um drive diferente).
   - Copie ou extraia `ffmpeg.exe` (e os demais binários do pacote FFmpeg) para esse diretório, garantindo que o caminho final seja `C:\bwb\ffmpeg\bin\ffmpeg.exe`.
   - O módulo utiliza esse caminho por padrão através da variável `FFMPEG`. Se preferir outro local, sobrescreva `FFMPEG` no `.env` posicionado ao lado do executável ou no diretório `primary-windows\src\` (para execuções via código-fonte).
3. **(Opcional) Prepare o ambiente de desenvolvimento**:
   - Instale o Python 3.11 caso seja necessário executar diretamente a partir do código-fonte ou gerar novos builds com o PyInstaller.
   - Obtenha o repositório `bwb-stream2yt` (via Git ou ZIP) somente se for atuar nessa modalidade.

### 1.1 Obter o repositório (Git ou ZIP)

Escolha uma das opções abaixo para copiar o conteúdo do repositório para o seu computador antes de seguir para as próximas etapas.

#### Método A — Git for Windows e `git clone`

1. Acesse <https://git-scm.com/download/win> e faça o download do instalador **Git for Windows** compatível com a sua arquitetura.
2. Execute o instalador, mantendo as opções padrão recomendadas (incluindo a instalação do **Git Bash**).
3. Após concluir a instalação, abra o **Git Bash** e navegue até a pasta em que deseja manter o código, por exemplo:
   ```bash
   cd /c/myapps
   ```
4. Faça o clone do repositório oficial com o comando:
   ```bash
   git clone https://github.com/storesace-cv/bwb-stream2yt.git
   ```
5. Ao término do processo, você terá os arquivos disponíveis em `C:\myapps\bwb-stream2yt\` (ou no diretório escolhido no passo 3).

#### Método B — Download direto do GitHub (ZIP)

1. Visite <https://github.com/storesace-cv/bwb-stream2yt> em um navegador.
2. Clique no botão **Code ▸ Download ZIP** para baixar o pacote compactado com os arquivos do projeto.
3. Extraia o conteúdo do arquivo ZIP utilizando o Explorador de Arquivos do Windows (ou outra ferramenta de sua preferência).
4. Mova a pasta extraída para o local desejado, como `C:\myapps\bwb-stream2yt\`, mantendo a estrutura de diretórios original.
5. Caso venha a utilizar scripts ou caminhos predefinidos, ajuste referências para apontar para o diretório onde posicionou a pasta extraída.

## 2. Executável distribuído

1. **Posicione o binário oficial** em `C:\myapps\stream_to_youtube.exe`.
2. **Ajuste o arquivo de configuração**:
   - Ao executar o binário pela primeira vez, o script cria automaticamente um `.env` no mesmo diretório usando o template padrão.
   - Em seguida, edite o `.env` recém-criado e configure ao menos `YT_KEY=<CHAVE_DO_STREAM>` (ou `YT_URL` completo, se preferir).
   - Ajuste `YT_INPUT_ARGS`, `YT_OUTPUT_ARGS`, as credenciais RTSP e `FFMPEG` conforme a necessidade do equipamento local.
3. **Controle da execução**:
   - O fluxo é direto, sem criação de serviço do Windows: execute `stream_to_youtube.exe /start` (ou apenas `stream_to_youtube.exe`) para iniciar o worker em segundo plano.
   - O binário grava `stream_to_youtube.pid` com o PID ativo e utiliza a sentinela `stream_to_youtube.stop` para registrar pedidos de parada; ambos ficam na mesma pasta do executável.
   - Para interromper com segurança, abra um *Prompt de Comando* em `C:\myapps\` e execute `stream_to_youtube.exe /stop`. O comando localiza o PID registrado, gera a sentinela e remove os arquivos de controle assim que o worker encerra.
   - Em caso de desligamentos inesperados, basta executar novamente; o script elimina automaticamente registros obsoletos antes de reiniciar.
4. **Verifique os logs**:
   - Os registros são gravados em arquivos diários `C:\myapps\logs\bwb_services-YYYY-MM-DD.log` (a pasta `logs\` é criada se necessário e mantemos somente os últimos sete dias).
   - Utilize esses arquivos para confirmar a inicialização do FFmpeg e eventuais erros de autenticação.
5. **Homologação rápida**:
   - Confirme, durante o primeiro teste, se o YouTube recebe o stream na URL primária e se o log indica status `connected`.

## 3. Execução via código-fonte

1. **Requisitos**:
   - Python 3.11 instalado e acessível no `PATH`.
   - Repositório `bwb-stream2yt` disponível localmente (clone ou pacote ZIP extraído).
2. **Configuração do `.env`**:
   - A primeira execução de `python stream_to_youtube.py` cria automaticamente `primary-windows\src\.env` com o template padrão.
   - Edite o arquivo para preencher `YT_KEY` (ou `YT_URL`) e personalize os parâmetros `YT_INPUT_ARGS`, `YT_OUTPUT_ARGS`, credenciais RTSP e `FFMPEG` conforme necessário.
3. **Execução**:
   - Abra um *Prompt de Comando* em `primary-windows\src\` e execute `python stream_to_youtube.py`.
   - O log compartilhado é gravado em arquivos diários `primary-windows\src\logs\bwb_services-YYYY-MM-DD.log` com retenção automática de sete dias.
4. **Validação**:
   - Monitore o mesmo log para verificar a inicialização do FFmpeg e confirme a recepção do stream no painel do YouTube.

## 4. Build one-file com PyInstaller (referência)

Para gerar o executável sem acesso à internet, utilize o kit de build localizado em [`primary-windows/via-windows/`](../primary-windows/via-windows/README.md):

1. Instale o Python 3.11 e siga o passo a passo descrito no `README.md` do diretório `via-windows` (ou execute `prepare-env.bat` e `build.bat`).
2. O spec file `stream_to_youtube.spec` encapsula os mesmos parâmetros da nossa pipeline (`--onefile`, `--noconsole` e demais ajustes necessários) sem dependências específicas de serviço do Windows.
3. Ao término do processo, copie `primary-windows\via-windows\dist\stream_to_youtube.exe` para `C:\myapps\` juntamente com um `.env` atualizado.
4. Durante a distribuição, reforce a necessidade do `ffmpeg.exe` presente em `C:\bwb\ffmpeg\bin\` ou documente o caminho alternativo via variável `FFMPEG` (caso a equipe opte por outro diretório, basta sobrescrever o valor no `.env`).

## 5. Checklist de verificação

- [ ] `stream_to_youtube.exe` posicionado em `C:\myapps\`.
- [ ] `.env` ajustado no mesmo diretório com `YT_KEY` (e, se necessário, `YT_URL`/`FFMPEG`).
- [ ] `ffmpeg.exe` disponível em `C:\bwb\ffmpeg\bin\` ou caminho ajustado na configuração.
- [ ] Execução do executável gera arquivos `C:\myapps\logs\bwb_services-YYYY-MM-DD.log` (com retenção automática de sete dias) sem erros críticos.
- [ ] Dashboard do YouTube confirma conexão do stream durante o teste.
- [ ] (Opcional) Ambiente Python 3.11 preparado para manutenção via código-fonte ou geração de novos builds.

Seguindo estes passos, o host Windows estará pronto para transmitir pelo módulo primário com segurança e previsibilidade, seja utilizando o executável distribuído ou o código-fonte.
