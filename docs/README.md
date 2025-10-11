# Guia rápido da documentação

Este índice agrupa todos os materiais de apoio por tema. Use os links abaixo para chegar rapidamente ao documento certo consoante a tarefa em mãos.

## 1. Visão geral e arquitectura
- [README](../README.md): visão macro do projecto e avisos operacionais.
- [ARCHITECTURE.md](../ARCHITECTURE.md): redundância entre emissor Windows e fallback Linux.
- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md): narrativa funcional e papéis de cada módulo.

## 2. Configuração e deploy
- [DEPLOY.md](../DEPLOY.md): preparar a droplet secundária e automatizar sincronizações.
- [docs/primary-windows-instalacao.md](primary-windows-instalacao.md): instalar o emissor principal em Windows.
- [deploy/](../deploy): scripts Python para `rsync`/SSH, com exemplos de `--dry-run`.
- [start.sh](../start.sh) e [update_from_main.sh](../update_from_main.sh): atalhos internos para bootstrap/actualizações locais.

## 3. Operações do dia a dia
- [OPERATIONS.md](../OPERATIONS.md): comandos de verificação rápida (serviços, logs, reset da droplet).
- [OPERATIONS_CHECKLIST.md](OPERATIONS_CHECKLIST.md): checklist sequencial para handovers ou turnos.
- [REGRAS_URL_SECUNDARIA.md](REGRAS_URL_SECUNDARIA.md): políticas para mexer na URL de backup.

## 4. Diagnósticos e histórico
- [diagnósticos.md](diagnósticos.md): linha temporal dos scripts de diagnóstico e quando usar cada um.
- [diagnostics/](diagnostics): relatórios pós-incidente e guias específicos (logs do fallback, capturas do monitor, etc.).
- [diags/README.md](../diags/README.md): referência de baixo nível para os scripts Python de recolha.

## 5. Desenvolvimento e qualidade
- [CODING_GUIDE.md](CODING_GUIDE.md): convenções de código e boas práticas para contribuições.
- [CODER_GUIDE.md](../CODER_GUIDE.md) e [CODEX_PROMPT.md](CODEX_PROMPT.md): suporte ao fluxo de trabalho assistido por IA.
- [tests/](../tests): suites de validação automatizada (pytest) usadas no fallback.
- [requirements-dev.txt](../requirements-dev.txt) e [pyproject.toml](../pyproject.toml): dependências para lint/format.

## 6. Segurança e conformidade
- [SECURITY.md](../SECURITY.md): política de segredos, gestão de acessos e protecção de logs.
- [OPERATIONS_CHECKLIST.md](OPERATIONS_CHECKLIST.md): secção final com lembretes de segurança antes de fechar um turno.

## 7. Referências complementares
- [OPERATIONS.md](../OPERATIONS.md): secção de testes, lint e scripts auxiliares.
- [docs/bwb-sty_Apresentacao de trabalho - Cliente.md](bwb-sty_Apresentacao%20de%20trabalho%20-%20Cliente.md): apresentação executiva do projecto.
- [youtube-data-api.v3.discovery.json](youtube-data-api.v3.discovery.json): ficheiro offline para chamadas manuais à API do YouTube.
