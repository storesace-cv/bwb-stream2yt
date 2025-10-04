# bwb-stream2yt

Pipeline para transmissão para o YouTube com **fonte primária (Windows)** e **backup secundário (Droplet Linux)**.

Nomenclatura canónica:
- **primary-windows/** – app que empacota e envia o RTSP (ou DirectShow) para o YouTube (URL primária).
- **secondary-droplet/** – serviços de fallback no droplet (imagem + texto) e daemon "decider" (liga/desliga o fallback).
- **scripts/** – utilitários de deploy/atualização para o droplet via SSH/rsync.

> ⚠️ **Segredos (chaves/tokens) NÃO vão para o repositório.** Ver `SECURITY.md`.

## Arranque rápido

1. Criar o repo remoto no GitHub (`bwb-stream2yt`).
2. Iniciar git localmente e publicar (ver *Passo-a-passo* abaixo).
3. Configurar **Droplet** (ver `DEPLOY.md`).
4. Configurar **Windows** (ver `primary-windows/README.md`).

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
