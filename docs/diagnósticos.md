# Histórico de scripts de diagnóstico

Este índice centraliza a evolução das ferramentas criadas para recolher evidências na infraestrutura da URL secundária. Use-o como porta de entrada rápida antes de executar qualquer script: cada secção resume quando surgiu, o problema que motivou a criação e como o utilizar em produção.

## 2025-10 — `status-monitor-debug.sh`
**Objectivo:** capturar, numa única execução, o estado completo do serviço `yt-restapi` (logs, `systemctl`, `status.json`, ficheiro `.env` e resposta HTTP) para analisar falhas do mecanismo de heartbeats entre o emissor Windows e o fallback no droplet.

**Contexto histórico:** adoptado após a migração do papel de orquestração para o `yt-restapi`, permitindo recolher provas sempre que o fallback permanece activo ou inactivo de forma inesperada (ver incidentes de 9 de Outubro de 2025).

**Como executar:** ligue-se por SSH à droplet, aceda ao directório do repositório e corra `bash scripts/status-monitor-debug.sh`; o script anuncia o ficheiro `status-monitor-<timestamp>.log` gerado localmente para posterior partilha.

**Documentação de apoio:** guia detalhado em [`docs/diagnostics/status-monitor-debug.md`](diagnostics/status-monitor-debug.md) com exemplos de interpretação.

## 2025-10 — `monitor_heartbeat_window.py`
**Objectivo:** observar uma janela curta (60 s por defeito) de heartbeats reportados pelo `yt-restapi`, confrontando-os com o estado real do serviço `youtube-fallback.service` para validar se a automação está alinhada com o comportamento esperado.

**Como executar:** `cd /root/bwb-stream2yt/diags && ./monitor_heartbeat_window.py` numa sessão SSH; o resumo é apresentado directamente no terminal para decisões rápidas.

**Quando usar:** após recolher um pacote com o `status-monitor-debug.sh`, confirme de imediato se novos heartbeats chegam dentro da janela de observação antes de reiniciar serviços.

## 2025-09 — `run_diagnostics.py`
**Objectivo:** gerar um snapshot completo da máquina secundária (recursos do sistema, estado dos serviços, logs chave, ficheiros de configuração com `YT_KEY` mascarada e estado do repositório) para anexar a *post-mortems* ou pedidos de suporte.

**Como executar:** `cd /root/bwb-stream2yt/diags && ./run_diagnostics.py --label "antes-restart"`; o relatório é gravado em `diags/history/diagnostics-<timestamp>.txt` e pode ser limpo quando não for mais necessário.

**Automatização planeada:** o script é distribuído via `scripts/deploy_to_droplet.sh` e continua a ser a base para snapshots completos enquanto outras ferramentas são iteradas.
