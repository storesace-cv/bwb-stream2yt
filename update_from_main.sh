#!/usr/bin/env bash
# ---------------------------------------------------------
# Script: update_from_main.sh
# Objetivo: Trazer as novidades do origin/main para o branch my-sty e fazer push
# ---------------------------------------------------------

set -euo pipefail

PROJECT_PATH="/Users/jorgepeixinho/Documents/NetxCloud/projectos/bwb/desenvolvimento/bwb-stream2yt"

echo "---------------------------------------------------------"
echo "[BWB-STREAM2YT] merge de origin/main -> my-sty"
echo "---------------------------------------------------------"

cd "$PROJECT_PATH"

# Garante que estamos no repositório certo
[ -d ".git" ] || { echo "❌ Não é um repositório Git em: $PROJECT_PATH"; exit 1; }

# 1) Ir para o branch my-sty
echo "📍 A mudar para o branch my-sty..."
git switch my-sty

# 2) Buscar atualizações
echo "🔄 git fetch origin"
git fetch origin

# 3) Merge de origin/main para o branch atual (my-sty)
echo "🔗 git merge origin/main (pode criar merge commit se necessário)"
git merge --no-edit origin/main

# 4) Push do my-sty atualizado
echo "⬆️  git push origin my-sty"
git push origin my-sty

echo "✅ Concluído: my-sty contém as mudanças de origin/main."
