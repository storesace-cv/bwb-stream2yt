#!/usr/bin/env bash
# ---------------------------------------------------------
# Script: update_from_main.sh
# Objetivo: tornar o branch atual idêntico ao origin/main
# Modos: --stash | --backup | --force | (interativo por omissão)
# ---------------------------------------------------------
set -euo pipefail

MODE="${1:-}"   # vazio => interativo | --stash | --backup | --force

echo "---------------------------------------------------------"
echo "[BWB-STREAM2YT] Sincronização do branch atual com 'main'"
echo "---------------------------------------------------------"

PROJECT_PATH="/Users/jorgepeixinho/Documents/NetxCloud/projectos/bwb/desenvolvimento/bwb-stream2yt"
cd "$PROJECT_PATH" || { echo "❌ Pasta não encontrada: $PROJECT_PATH"; exit 1; }
[ -d .git ] || { echo "❌ Não é um repositório Git."; exit 1; }

CUR=$(git rev-parse --abbrev-ref HEAD)
echo "📍 Branch atual: $CUR"
[ "$CUR" != "main" ] || { echo "⚠️ Já estás em 'main'. Nada a fazer."; exit 0; }

echo "🔄 A buscar refs remotas..."
git fetch origin main "$CUR"

has_dirty=0
git diff-index --quiet HEAD -- || has_dirty=1
if [ $has_dirty -eq 1 ]; then
  case "$MODE" in
    --stash)
      echo "🧰 Alterações locais detectadas → a guardar em stash (com untracked)..."
      git stash push -u -m "pre-sync $(date '+%Y%m%d-%H%M%S')"
      ;;
    --backup)
      bname="backup/pre-sync-$(date '+%Y%m%d-%H%M%S')"
      echo "🛟 Alterações locais detectadas → a criar branch de backup: $bname"
      git switch -c "$bname"
      git switch "$CUR"
      ;;
    --force)
      echo "⚠️ Alterações locais detectadas → a descartar (reset + clean)..."
      git reset --hard
      git clean -fd
      ;;
    *)
      echo "⚠️  Existem alterações locais não commitadas."
      echo "    Usa um dos modos:  --stash  |  --backup  |  --force"
      echo "    Ex.: ./update_from_main.sh --stash"
      exit 1
      ;;
  esac
fi

echo "🧩 A alinhar '$CUR' com 'origin/main'..."
git checkout "$CUR" >/dev/null 2>&1 || true
git reset --hard origin/main

# Atualiza refs locais (idempotente)
git pull --rebase origin main || true

echo "✅ '$CUR' agora é idêntico a 'origin/main'."
echo "---------------------------------------------------------"
git status -sb || true
echo "---------------------------------------------------------"
