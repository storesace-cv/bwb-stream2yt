# BWB Stream2YT — Apresentação de trabalho (Cliente)

## Resumo executivo
O projecto BWB Stream2YT disponibiliza uma solução fiável para retransmitir conteúdos em directo para o YouTube, com recurso a um par de pipelines (primário em Windows e secundário em Linux) que asseguram continuidade de serviço e recuperação automática em caso de falha. A presente entrega inclui a automatização de ingestão, monitorização do estado da transmissão, e ferramentas auxiliares de operação, alinhadas com os requisitos acordados com o cliente.

## Objectivos
- Garantir redundância operacional entre o emissor principal (Windows) e o emissor de contingência (Linux/Droplet).
- Automatizar a gestão das sessões de transmissão no YouTube Live, incluindo detecção de falhas e failover imediato.
- Facultar documentação operacional clara para equipas técnicas e de suporte.
- Disponibilizar scripts e artefactos de deploy reproduzíveis, compatíveis com os ambientes-alvo definidos.

## Funcionalidades entregues
- Aplicação Windows empacotada com PyInstaller para captura RTSP/dshow e publicação RTMPS.
- Daemon de decisão no Droplet para monitorização do estado do stream via YouTube Data API e controlo da stream de reserva.
- Scripts de fallback e configuração (`youtube_fallback.sh`, defaults e overrides) integrados com `systemd`.
- Documentação técnica e operacional actualizada, incluindo guias de instalação, checklist de operações e normas de segurança.
- Registo centralizado de logs para apoio à resolução de incidentes.

## Métricas de desenvolvimento
- Duração do projecto: 6 semanas (30 dias úteis).
- Esforço estimado: 240 horas de engenharia (equipa multidisciplinar).
- Linhas de código afectadas: ~8 500 LOC (Python, Bash, ficheiros de configuração e documentação).

## Tecnologias e ferramentas utilizadas
- Linguagens: Python 3.11, Bash.
- Frameworks e bibliotecas: `requests`, `google-api-python-client`, `PyInstaller`.
- Serviços e infra-estruturas: YouTube Live, servidores Windows, droplet Linux (Ubuntu 22.04), `systemd`.
- Ferramentas de suporte: Git, GitHub Actions, logging centralizado (`journalctl`, ficheiros dedicados).

## Desafios e soluções
- **Gestão de tokens OAuth em ambiente headless**: Implementado fluxo de renovação com armazenamento seguro em ficheiro `token.json` e restrições de permissões.
- **Sincronização de estados entre emissor primário e secundário**: Desenvolvido daemon `yt_decider_daemon.py` com lógica de temporização e thresholds para evitar oscilações de failover.
- **Automação do deploy em múltiplas plataformas**: Estruturados scripts específicos por ambiente, com documentação passo a passo para reduzir variabilidade durante rollouts.
- **Monitorização e troubleshooting remoto**: Centralização de logs e instruções de diagnóstico, permitindo resposta rápida a incidentes fora do horário laboral.

## Recomendações futuras
- Evoluir para dashboards de monitorização em tempo real (ex. Grafana/Prometheus) com alertas proactivos.
- Implementar testes automáticos end-to-end para validar cenários de failover antes de cada release.
- Expandir a cobertura de scripts de recuperação para incluir actualização automática de certificados e validação de largura de banda.
- Avaliar a integração com serviços de CDN ou multistream para aumentar a resiliência e alcance.

