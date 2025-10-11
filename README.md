# bwb-stream2yt

Pipeline redundante para transmissão para o YouTube do canal **BeachCam | Praia dos Surfistas | Cabo Ledo | Angola**, com fonte primária em Windows e backup secundário num droplet Linux.

> ⚠️ **Segredos (chaves/tokens) NÃO vão para o repositório.** Consulte `SECURITY.md`.
>
> 🚫 **Logs locais ficam fora do Git.** O diretório `logs/` já está no `.gitignore`; não remova essa regra nem execute `git add` em ficheiros gerados.

## Visão geral

O sistema automatiza o fluxo RTSP → YouTube, garantindo resiliência através de duas cadeias de transmissão:

- **Transmissão principal (Windows):** envia o RTSP (ou DirectShow) diretamente para a URL primária do YouTube.
- **Fallback secundário (Droplet Linux):** mantém serviços de imagem e texto, comutados automaticamente pelo serviço `yt-restapi` (monitor HTTP) que reage aos heartbeats enviados pelo primário.
- **Integração com a API do YouTube:** continua disponível via scripts auxiliares (`yt_api_probe_once.py`), mas a decisão de failover é agora feita exclusivamente com base na comunicação entre emissor e droplet.

## Componentes principais

- **primary-windows/** – aplicação que empacota e envia o RTSP (ou DirectShow) para o YouTube (URL primária).
- **secondary-droplet/** – serviços de fallback no droplet (imagem + texto) e monitor HTTP que liga/desliga o fallback.
- **scripts/** – utilitários de deploy/atualização para o droplet via SSH/rsync.
- **docs/** – documentação complementar (visão geral, guias de codificação e prompts de suporte).

## Documentação reorganizada

O conteúdo está agora agrupado por tema para acelerar a navegação:

- **Mapa geral:** [`docs/README.md`](docs/README.md) apresenta o índice completo e descreve em que momento consultar cada documento.
- **Visão geral e arquitectura:** [`ARCHITECTURE.md`](ARCHITECTURE.md) e [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) detalham a redundância entre emissor primário e fallback.
- **Configuração e deploy:** [`DEPLOY.md`](DEPLOY.md), [`docs/primary-windows-instalacao.md`](docs/primary-windows-instalacao.md) e [`deploy/`](deploy) cobrem requisitos, variáveis de ambiente e fluxo de publicação.
- **Operações do dia a dia:** [`OPERATIONS.md`](OPERATIONS.md), [`docs/OPERATIONS_CHECKLIST.md`](docs/OPERATIONS_CHECKLIST.md) e [`docs/REGRAS_URL_SECUNDARIA.md`](docs/REGRAS_URL_SECUNDARIA.md) consolidam verificações, rotinas e políticas de mudança.
- **Diagnósticos e troubleshooting:** [`docs/diagnósticos.md`](docs/diagn%C3%B3sticos.md) resume a evolução dos scripts e aponta para relatórios históricos em [`docs/diagnostics/`](docs/diagnostics).
- **Desenvolvimento e qualidade:** [`docs/CODING_GUIDE.md`](docs/CODING_GUIDE.md), [`CODER_GUIDE.md`](CODER_GUIDE.md) e [`tests/`](tests) documentam padrões de código, prompts de suporte e suites automatizadas.
- **Segurança e governança:** [`SECURITY.md`](SECURITY.md) e [`docs/OPERATIONS_CHECKLIST.md`](docs/OPERATIONS_CHECKLIST.md) listam salvaguardas para credenciais e acessos.

## Estrutura do repositório

```
primary-windows/
  └── src/
      └── stream_to_youtube.py
secondary-droplet/
  ├── bin/
  ├── config/
  ├── systemd/
  └── tools/
docs/
  ├── PROJECT_OVERVIEW.md
  ├── CODING_GUIDE.md
  └── CODEX_PROMPT.md
scripts/
```

## Arranque rápido

1. Criar o repo remoto no GitHub (`bwb-stream2yt`).
2. Iniciar git localmente e publicar (ver *Passo-a-passo* abaixo).
3. Configurar **Droplet** (ver `DEPLOY.md`).
4. Configurar **Windows** (ver `primary-windows/README.md`).

## Testes automatizados

Execute os testes antes de publicar alterações para garantir que o monitor continua a tomar decisões corretas:

```bash
python -m pip install --upgrade pip
pip install -r secondary-droplet/requirements.txt
pip install pytest
pytest
```

Os testes ficam em `secondary-droplet/tests/` e simulam diferentes cenários de heartbeats (ausência prolongada, recuperação, etc.) sem necessidade de contactar serviços externos.

## Lint e formatação

Utilizamos [Black](https://github.com/psf/black) para formatação automática e [Flake8](https://flake8.pycqa.org/) para garantir estilo consistente. Instale as dependências de desenvolvimento e execute as ferramentas antes de enviar alterações:

```bash
python -m pip install --upgrade pip
pip install -r requirements-dev.txt

# Formatar código automaticamente
python -m black .

# Validar formatação e regras de estilo
python -m black --check .
python -m flake8
```

---

## Passo-a-passo (terminal)

```bash
# Dentro de /Users/jorgepeixinho/Documents/NetxCloud/projectos/bwb/desenvolvimento/bwb-stream2yt

git init
git add .
git commit -m "bootstrap: estrutura inicial (2025-10-04 14:32 UTC)"

# criar o repo remoto (use um dos métodos)
# A) via GitHub Web: crie 'bwb-stream2yt' e depois associar o remote:
git remote add origin https://github.com/<a-sua-conta>/bwb-stream2yt.git

# B) OU via GitHub CLI:
# gh repo create bwb-stream2yt --public --source=. --remote=origin --push

# publicar main
git branch -M main
git push -u origin main

# criar o branch de trabalho
git checkout -b my-sty
git push -u origin my-sty
```
