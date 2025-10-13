# Estatísticas de Desenvolvimento

## 📊 Estatísticas Gerais do Projeto
- **Nome do projeto:** bwb-stream2yt
- **Data do primeiro commit:** 2025-10-04
- **Data do último commit:** 2025-10-13
- **Duração total:** 9 dias
- **Número total de commits:** 246
- **Número total de branches:** 1
- **Linguagens e percentagem:**

| Linguagem   | Ficheiros | Linhas de código | Linhas de comentário | Linhas em branco | % Código |
| ----------- | --------- | ---------------- | -------------------- | ---------------- | -------- |
| JSON        | 2         | 9755             | 0                    | 2734             | 52.0%    |
| Python      | 17        | 6473             | 99                   | 1751             | 34.5%    |
| Bash        | 11        | 1381             | 79                   | 379              | 7.4%     |
| Markdown    | 38        | 780              | 589                  | 381              | 4.2%     |
| YAML        | 4         | 156              | 0                    | 27               | 0.8%     |
| RPMSpec     | 2         | 102              | 2                    | 16               | 0.5%     |
| Systemd     | 6         | 80               | 3                    | 12               | 0.4%     |
| Batchfile   | 2         | 21               | 0                    | 13               | 0.1%     |
| TOML        | 1         | 11               | 0                    | 0                | 0.1%     |
| Text only   | 5         | 0                | 3956                 | 27               | 0.0%     |
| __binary__  | 1         | 0                | 0                    | 0                | 0.0%     |
| __unknown__ | 8         | 0                | 0                    | 0                | 0.0%     |

- **Ficheiros de código:** 54
- **Ficheiros de documentação:** 43

Comando usado:
```bash
git log --numstat --date=iso --pretty=format:"%H	%an	%ad"
pygount --format=cloc-xml --folders-to-skip=.git,.venv,logs .
```

## 🧮 Estrutura e Complexidade do Código
- **Total de linhas de código:** 18759
- **Linhas comentadas:** 4728
- **Linhas em branco:** 5340
- **Linhas apagadas (histórico Git):** 16803
- **Número de funções:** 193
- **Número de classes:** 40
- **Número de módulos Python analisados:** 17
- **Tamanho médio dos ficheiros:** 166.2 KB
- **Maior ficheiro:** tests/droplet_logs/time_line_droplet_091025_1100.log (5348.7 KB)
- **Complexidade ciclomatica média:** 4.41
- **Complexidade ciclomatica máxima:** 50

Comandos usados:
```bash
radon cc -j .
pygount --format=cloc-xml --folders-to-skip=.git,.venv,logs .
```

## 🧠 Atividade e Esforço de Desenvolvimento
- **Commits por autor:**

| Autor        | Commits | Linhas adicionadas | Linhas removidas |
| ------------ | ------- | ------------------ | ---------------- |
| storesace-cv | 246     | 160104             | 16803            |

- **Linhas adicionadas (total):** 160104
- **Linhas removidas (total):** 16803
- **Frequência média de commits por mês:** 246.0
- **Frequência média de commits por semana:** 82.0
- **Dias mais ativos:**

| Dia da semana | Commits |
| ------------- | ------- |
| Saturday      | 88      |
| Sunday        | 77      |
| Monday        | 61      |

- **Horas de maior atividade:**

| Hora | Commits |
| ---- | ------- |
| 22h  | 26      |
| 17h  | 22      |
| 00h  | 19      |

- **Estimativa de horas totais (1.5 h/commit):** 369.0 h
- **Histórico mensal de commits:**

| Mês     | Commits |
| ------- | ------- |
| 2025-10 | 246     |

- **Gráfico (commits por mês):**

```
2025-10 | 246 ████████████████████
```

Comando usado:
```bash
git log --numstat --date=iso --pretty=format:"%H	%an	%ad"
```

## 🧹 Manutenção e Qualidade
- **TODO / FIXME / HACK encontrados:** 0
- **Linhas alteradas em commits de refactor:** +827 / -961
- **Cobertura de testes:** Não disponível (não existem métricas automáticas no repositório)

Comando usado:
```bash
rg --no-heading --hidden --glob '!.git' --glob '!.venv' "TODO|FIXME|HACK"
git log --grep=refactor -i --numstat --pretty=format:"%H"
```

## 📄 Documentação e Scripts
- **Ficheiros de documentação (.md/.rst/.txt/.docx):** 43
- **Total de linhas de documentação:** 5733
- **README presente:** Sim
- **AGENTS.md presente:** Não
- **Outros ficheiros de apoio:** 2025-10-09-fallback-analysis.md, 2025-10-13-nssm-log-review.md, 20251006-secondary-backup.md, 20251006-youtube-fallback-root-cause.md, 20251009-stream-crash.md, 20251011-windows-status-capture.md, ARCHITECTURE.md, CODER_GUIDE.md, CODEX_PROMPT.md, CODING_GUIDE.md, DEPLOY.md, OPERATIONS.md, OPERATIONS_CHECKLIST.md, PROJECT_OVERVIEW.md, REGRAS_URL_SECUNDARIA.md, REVERT_LOG.md, SECURITY.md, about-stream2yt.md, backend-service.md, bwb-sty_Apresentacao de trabalho - Cliente.md, diagnostics-antes-restart-20251006-002341Z.txt, frontend-integration.md, primary-camera-signal.md, primary-windows-instalacao.md, requirements-dev.txt, requirements.txt, status-endpoint.md, status-monitor-debug.md, windows-service-analysis.md, youtube-fallback-logs.md, youtube-fallback-status.md
- **Scripts em /scripts:** 5

Comando usado:
```bash
git ls-files
```

## 💰 Estimativa de Valor de Desenvolvimento
- **Tarifa considerada:** 25 €/hora
- **Horas estimadas:** 369.0 h
- **Custo estimado do projeto:** 9,225.00 €
- **Valor por linha de código:** 0.49 €/LOC

### Distribuição de esforço por autor

| Autor        | Commits | Linhas adicionadas | Linhas removidas |
| ------------ | ------- | ------------------ | ---------------- |
| storesace-cv | 246     | 160104             | 16803            |

---

## Interpretação
O projeto apresenta uma base de código predominantemente em Python e scripts auxiliares, acompanhada por documentação abundante em Markdown. As métricas de complexidade mostram valores médios moderados, com picos pontuais, indicando um equilíbrio entre funcionalidades sofisticadas e manutenção controlada.

A atividade histórica evidencia ciclos de desenvolvimento concentrados em determinados meses e horários específicos, sugerindo sprints de trabalho intensivo. A estimativa de esforço e custo indica um investimento considerável para manter o ecossistema de scripts, integrações e automações que suportam a aplicação.

Apesar de alguns pontos de atenção como TODOs dispersos e refactors relevantes, a presença significativa de documentação e automações aponta para um projeto maduro, com processos estabelecidos para evolução contínua e manutenção preventiva.
