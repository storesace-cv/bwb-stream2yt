# bwb-stream2yt

Pipeline redundante para transmissão para o YouTube do canal **BeachCam | Praia dos Surfistas | Cabo Ledo | Angola**, com fonte primária em Windows e backup secundário num droplet Linux.

> ⚠️ **Segredos (chaves/tokens) NÃO vão para o repositório.** Consulte `SECURITY.md`.

## Visão geral

O sistema automatiza o fluxo RTSP → YouTube, garantindo resiliência através de duas cadeias de transmissão:

- **Transmissão principal (Windows):** envia o RTSP (ou DirectShow) diretamente para a URL primária do YouTube.
- **Fallback secundário (Droplet Linux):** mantém serviços de imagem e texto, comutados automaticamente por um daemon decisor (`yt-decider-daemon`).
- **Integração com a API do YouTube:** monitoriza o estado da transmissão para ativar/desativar o fallback conforme necessário.

## Componentes principais

- **primary-windows/** – aplicação que empacota e envia o RTSP (ou DirectShow) para o YouTube (URL primária).
- **secondary-droplet/** – serviços de fallback no droplet (imagem + texto) e daemon "decider" (liga/desliga o fallback).
- **scripts/** – utilitários de deploy/atualização para o droplet via SSH/rsync.
- **docs/** – documentação complementar (visão geral, guias de codificação e prompts de suporte).

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

Execute os testes antes de publicar alterações para garantir que o daemon decisor continua a tomar decisões corretas:

```bash
python -m pip install --upgrade pip
pip install -r secondary-droplet/requirements.txt
pip install pytest
pytest
```

Os testes ficam em `secondary-droplet/tests/` e simulam diferentes estados da API do YouTube, sem necessidade de contactar serviços externos.

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
