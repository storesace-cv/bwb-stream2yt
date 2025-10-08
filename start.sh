#!/usr/bin/env bash
# ---------------------------------------------------------
# Script: start.sh
# Objetivo: Ativar o ambiente virtual e entrar no branch my-sty
# Uso recomendado: source ./start.sh
# ---------------------------------------------------------

set -euo pipefail

TARGET_BRANCH="${TARGET_BRANCH:-my-sty}"

is_sourced() {
  # Bash
  if [ -n "${BASH_SOURCE:-}" ] && [ "${BASH_SOURCE[0]}" != "$0" ]; then
    return 0
  fi
  # Zsh
  if [ -n "${ZSH_EVAL_CONTEXT:-}" ] && [[ "$ZSH_EVAL_CONTEXT" == *:file ]]; then
    return 0
  fi
  return 1
}

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
  echo "❌ ERRO: Pasta do projeto não encontrada em $PROJECT_PATH"
  ( ! is_sourced ) && exit 1 || return 1
fi

# Entrar na pasta do projeto
cd "$PROJECT_PATH"

echo "---------------------------------------------------------"
echo "[BWB-STREAM2YT] Inicialização do ambiente de desenvolvimento"
echo "---------------------------------------------------------"

echo "📁 Projeto: $PROJECT_PATH"

# Ativar o venv
if [ -d ".venv" ]; then
  echo "✅ Ambiente virtual encontrado. A ativar..."
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "⚠️  Ambiente virtual não encontrado. Criar novo? (y/n)"
  read -r create_venv
  if [[ "${create_venv:-}" =~ ^[Yy]$ ]]; then
    echo "🔧 A criar novo venv..."
    PYTHON_BIN="$(command -v python3 || command -v python || true)"
    if [ -z "$PYTHON_BIN" ]; then
      echo "❌ Python não encontrado no PATH."
      ( ! is_sourced ) && exit 1 || return 1
    fi
    "$PYTHON_BIN" -m venv .venv --system-site-packages
    # shellcheck disable=SC1091
    source .venv/bin/activate
  else
    echo "❌ Operação cancelada."
    ( ! is_sourced ) && exit 1 || return 1
  fi
fi

if ! command -v git >/dev/null 2>&1; then
  echo "⚠️  Git não está disponível. A saltar operações de sincronização."
else
  # Verificar/mudar de branch
  CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "")
  if [ "$CURRENT_BRANCH" != "$TARGET_BRANCH" ]; then
    echo "🔁 A mudar para o branch $TARGET_BRANCH..."
    git fetch origin "$TARGET_BRANCH" >/dev/null 2>&1 || echo "⚠️ Não foi possível obter informações remotas."
    git checkout "$TARGET_BRANCH"
  else
    echo "✅ Já se encontra no branch $TARGET_BRANCH."
  fi

  # Atualizar o repositório
  echo "🔄 A atualizar o código local..."
  git pull --ff-only origin "$TARGET_BRANCH" || echo "⚠️ Não foi possível atualizar o repositório (pode estar offline)."
fi

# Mostrar status do repositório e Python ativo
echo "📦 Estado do repositório:"
git status -sb || true

echo "🐍 Python ativo: $(command -v python3 || command -v python || true)"
if command -v pip >/dev/null 2>&1; then
  echo "📦 Pip versão: $(pip --version)"
else
  echo "⚠️  Pip não disponível."
fi

echo "---------------------------------------------------------"
if is_sourced; then
  echo "✅ Ambiente pronto e venv ATIVO nesta shell."
else
  echo "ℹ️  Nota: executou o script como './start.sh'."
  echo "    Para ficar com o venv ativo na shell atual, use:  source ./start.sh"
fi
echo "---------------------------------------------------------"
