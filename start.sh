#!/usr/bin/env bash
# ---------------------------------------------------------
# Script: start.sh
# Localização: /Users/jorgepeixinho/Documents/NetxCloud/projectos/bwb/desenvolvimento/bwb-stream2yt/start.sh
# Objetivo: Ativar o ambiente virtual e entrar no branch my-sty
# Uso recomendado: source ./start.sh
# ---------------------------------------------------------

set -e
set -u

echo "---------------------------------------------------------"
echo "[BWB-STREAM2YT] Inicialização do ambiente de desenvolvimento"
echo "---------------------------------------------------------"

# Detectar se este script está a ser 'sourced'
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

PROJECT_PATH="/Users/jorgepeixinho/Documents/NetxCloud/projectos/bwb/desenvolvimento/bwb-stream2yt"

# Entrar na pasta do projeto
cd "$PROJECT_PATH" || {
  echo "❌ ERRO: Pasta do projeto não encontrada em $PROJECT_PATH"
  ( ! is_sourced ) && exit 1 || return 1
}

# Ativar o venv
if [ -d ".venv" ]; then
  echo "✅ Ambiente virtual encontrado. A ativar..."
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "⚠️  Ambiente virtual não encontrado. Criar novo? (y/n)"
  read -r create_venv
  if [[ "$create_venv" =~ ^[Yy]$ ]]; then
    echo "🔧 A criar novo venv..."
    /opt/homebrew/bin/python3 -m venv .venv --system-site-packages
    # shellcheck disable=SC1091
    source .venv/bin/activate
  else
    echo "❌ Operação cancelada."
    ( ! is_sourced ) && exit 1 || return 1
  fi
fi

# Verificar/mudar de branch
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "")
if [ "$CURRENT_BRANCH" != "my-sty" ]; then
  echo "🔁 A mudar para o branch my-sty..."
  git fetch origin my-sty || echo "⚠️ Não foi possível obter informações remotas."
  git checkout my-sty
else
  echo "✅ Já se encontra no branch my-sty."
fi

# Atualizar o repositório
echo "🔄 A atualizar o código local..."
git pull origin my-sty || echo "⚠️ Não foi possível atualizar o repositório (pode estar offline)."

# Mostrar status do repositório e Python ativo
echo "📦 Estado do repositório:"
git status -sb || true

echo "🐍 Python ativo: $(command -v python3 || true)"
echo "📦 Pip versão: $(pip --version || true)"

echo "---------------------------------------------------------"
if is_sourced; then
  echo "✅ Ambiente pronto e venv ATIVO nesta shell."
else
  echo "ℹ️  Nota: executou o script como './start.sh'."
  echo "    Para ficar com o venv ativo na shell atual, use:  source ./start.sh"
fi
echo "---------------------------------------------------------"
