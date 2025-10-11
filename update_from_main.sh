#!/usr/bin/env bash
#
# update_from_main.sh — Mantém o branch atual SEMPRE igual ao 'main' remoto.
# - Descarta TODOS os commits locais (sem perguntar).
# - Alinha o índice e a working tree com origin/main (reset --hard).
# - Remove ficheiros/pastas não versionados que não existam em main (git clean -ffd).
#   (Mantém ficheiros ignorados por .gitignore; para também limpar ignorados, export IGNORE_GITIGNORE=1)
# - Faz push forçado do branch atual para o remoto para garantir que não fica à frente do main.
#
# Uso:
#   ./update_from_main.sh
#
# Requisitos: git >= 2.20
set -euo pipefail

REQUIRED_VERSION="2.20.0"

version_ge() {
  # Returns success if $1 >= $2 using version sort.
  local current="$1" required="$2"
  [ "$(printf '%s\n%s\n' "$required" "$current" | sort -V | head -n1)" = "$required" ]
}

# ---------- UI helpers ----------
info()  { printf "🔹 %s\n" "$*"; }
ok()    { printf "✅ %s\n" "$*"; }
warn()  { printf "⚠️  %s\n" "$*"; }
err()   { printf "❌ %s\n" "$*" >&2; }

# ---------- Sanity checks ----------
if ! command -v git >/dev/null 2>&1; then
  err "git não encontrado no PATH."
  exit 1
fi

GIT_VERSION="$(git --version | awk '{print $3}')"
if ! version_ge "$GIT_VERSION" "$REQUIRED_VERSION"; then
  err "Git ${REQUIRED_VERSION} ou superior é obrigatório (detetado ${GIT_VERSION})."
  exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  err "Este diretório não é um repositório Git."
  exit 1
fi

# Garante que não há operações em curso (rebase/merge)
if [ -d .git/rebase-apply ] || [ -d .git/rebase-merge ] || [ -f .git/MERGE_HEAD ]; then
  err "Existe um rebase/merge em curso. Conclui ou aborta antes de continuar."
  exit 1
fi

# ---------- Descoberta ----------
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" = "HEAD" ]; then
  err "HEAD está em detached mode. Faz checkout de um branch antes de continuar."
  exit 1
fi

if [ -n "$(git status --short)" ]; then
  warn "Existem alterações locais que serão descartadas."
fi
REMOTE_NAME="${REMOTE_NAME:-origin}"
MAIN_BRANCH="${MAIN_BRANCH:-main}"

info "Repositório: $(basename "$(git rev-parse --show-toplevel)")"
info "Branch atual: ${CURRENT_BRANCH}"
info "Objetivo: espelhar ${REMOTE_NAME}/${MAIN_BRANCH} (nunca à frente)."

# ---------- Fetch ----------
info "A atualizar referências remotas (${REMOTE_NAME})…"
git fetch --prune --tags "${REMOTE_NAME}"

# Confirma que origin/main existe
if ! git show-ref --verify --quiet "refs/remotes/${REMOTE_NAME}/${MAIN_BRANCH}"; then
  err "Não existe ${REMOTE_NAME}/${MAIN_BRANCH}. Verifica o remoto/branch."
  exit 1
fi

# ---------- Hard reset ao origin/main ----------
info "A fazer reset HARD do branch atual para ${REMOTE_NAME}/${MAIN_BRANCH}…"
git reset --hard "${REMOTE_NAME}/${MAIN_BRANCH}"

# ---------- Limpeza de ficheiros não rastreados ----------
if [ "${IGNORE_GITIGNORE:-0}" = "1" ]; then
  warn "Limpeza agressiva: também vai remover ficheiros ignorados (.gitignore)."
  git clean -ffdx
else
  info "A remover apenas ficheiros/pastas não rastreados (mantém os ignorados)…"
  git clean -ffd
fi

ok "Working tree alinhada com ${REMOTE_NAME}/${MAIN_BRANCH}."

# ---------- Upstream & push ----------
# Garante que o branch atual tem upstream definido; se não tiver, aponta para REMOTE/CURRENT_BRANCH
if ! git rev-parse --abbrev-ref --symbolic-full-name "@{u}" >/dev/null 2>&1; then
  warn "Upstream não definido para ${CURRENT_BRANCH}. A definir para ${REMOTE_NAME}/${CURRENT_BRANCH}…"
  git branch --set-upstream-to "${REMOTE_NAME}/${CURRENT_BRANCH}" || true
fi

# Agora força o remoto do branch atual a coincidir com origin/main.
# Estratégia: publica exatamente o HEAD atual (que já é origin/main) no remoto do branch atual.
info "A publicar estado atual no remoto (${REMOTE_NAME}/${CURRENT_BRANCH}) com --force-with-lease…"
# Se o remoto não tiver o branch, o push cria-o; se tiver, será substituído.
git push --force-with-lease "${REMOTE_NAME}" "HEAD:${CURRENT_BRANCH}"

ok "O branch '${CURRENT_BRANCH}' está agora 100%% igual a '${REMOTE_NAME}/${MAIN_BRANCH}' (local e remoto)."

# ---------- Dica opcional ----------
cat <<'TIP'

ℹ️  Dicas:
   - Para correr isto em CI, define REMOTE_NAME e MAIN_BRANCH se necessário.
     Ex.: REMOTE_NAME=origin MAIN_BRANCH=main ./update_from_main.sh
   - Para também limpar ficheiros ignorados (ex.: .venv, dist, etc.):
     IGNORE_GITIGNORE=1 ./update_from_main.sh

TIP
