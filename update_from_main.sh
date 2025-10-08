#!/usr/bin/env bash
# ---------------------------------------------------------
# Script: update_from_main.sh
# Objetivo: Trazer as novidades do origin/main para o branch my-sty e fazer push
# ---------------------------------------------------------

set -euo pipefail

TARGET_BRANCH="${TARGET_BRANCH:-my-sty}"
SOURCE_REF="${SOURCE_REF:-origin/main}"

resolve_project_path() {
  local source_path script_dir repo_root
  source_path="${BASH_SOURCE[0]:-$0}"
  while [ -h "$source_path" ]; do
    script_dir=$(cd -P "$(dirname "$source_path")" >/dev/null 2>&1 && pwd)
    source_path=$(readlink "$source_path")
    [[ $source_path != /* ]] && source_path="$script_dir/$source_path"
  done
  script_dir=$(cd -P "$(dirname "$source_path")" >/dev/null 2>&1 && pwd)

  repo_root=$(cd "$script_dir" && git rev-parse --show-toplevel 2>/dev/null || true)
  if [ -n "$repo_root" ]; then
    printf '%s\n' "$repo_root"
  else
    printf '%s\n' "$script_dir"
  fi
}

PROJECT_PATH=$(resolve_project_path)

if [ ! -d "$PROJECT_PATH" ]; then
  echo "❌ Não é possível localizar o projeto em: $PROJECT_PATH"
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "❌ Git não está disponível no PATH."
  exit 1
fi

cd "$PROJECT_PATH"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "❌ Não é um repositório Git válido: $PROJECT_PATH"
  exit 1
fi

echo "---------------------------------------------------------"
echo "[BWB-STREAM2YT] merge de $SOURCE_REF -> $TARGET_BRANCH"
echo "---------------------------------------------------------"

echo "📁 Projeto: $PROJECT_PATH"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "❌ Existem alterações locais. Faça commit ou stash antes de prosseguir."
  exit 1
fi

# 1) Ir para o branch alvo
echo "📍 A mudar para o branch $TARGET_BRANCH..."
git switch "$TARGET_BRANCH"

# 2) Buscar atualizações
echo "🔄 git fetch origin"
git fetch origin

# 3) Merge da referência origem
if [[ "$SOURCE_REF" == origin/* ]]; then
  REMOTE_BRANCH="${SOURCE_REF#origin/}"
  if ! git show-ref --quiet "refs/remotes/$SOURCE_REF"; then
    echo "⚠️  A referência remota $SOURCE_REF não existe."
    exit 1
  fi
  echo "🔗 git merge --no-edit $SOURCE_REF"
  git merge --no-edit "$SOURCE_REF"
else
  echo "🔗 git merge --no-edit $SOURCE_REF"
  git merge --no-edit "$SOURCE_REF"
fi

# 4) Push do branch atualizado
echo "⬆️  git push origin $TARGET_BRANCH"
git push origin "$TARGET_BRANCH"

echo "✅ Concluído: $TARGET_BRANCH contém as mudanças de $SOURCE_REF."
