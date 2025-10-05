# Serviço backend na droplet

Este guia descreve como montar um microserviço HTTP na droplet secundária que consulta a API do YouTube e expõe um endpoint com o estado do canal. O serviço **não** deve retransmitir vídeo; limita-se a autenticar, recolher metadados e devolver um JSON seguro para uso no website.

## Requisitos prévios

- Droplet já configurada com o token OAuth (`/root/token.json`) utilizado pelos scripts `yt_api_probe_once.py`.
- Pacote `python3-venv` (ou `python3.10-venv`) disponível no sistema. O `post_deploy.sh` instala automaticamente caso falte, mas convém validar com `python3 -m ensurepip --help`.
- Acesso SSH privilegiado para configurar `systemd`, firewalls e variáveis de ambiente.

## Passos de implementação

1. **Automação via scripts**
   - Depois de sincronizar o repositório com `./scripts/deploy_to_droplet.sh`, execute manualmente `bash /root/bwb-stream2yt/scripts/post_deploy.sh` na droplet.
   - O `post_deploy.sh` chama `secondary-droplet/bin/ytc_web_backend_setup.sh`, que cria/actualiza o virtualenv em `/opt/ytc-web-service`, instala dependências com `pip --no-cache-dir` (para reduzir consumo de memória) e sincroniza o código da aplicação FastAPI.

2. **Reutilizar a lógica existente**
   - A aplicação (`secondary-droplet/ytc-web-backend/app.py`) reaproveita a consulta `liveBroadcasts.list`/`liveStreams.list`, encapsulando-a em `fetch_live_status()` com cache de 30 s e resposta conforme `status-endpoint.md`.

3. **Serviço `systemd`**
   - O unit file `secondary-droplet/systemd/ytc-web-backend.service` é copiado para `/etc/systemd/system`. Ele arranca o `uvicorn` a partir do virtualenv e lê configurações de `/etc/ytc-web-backend.env`.
   - O `post_deploy.sh` executa `systemctl daemon-reload`, `enable --now` e `restart` garantindo idempotência.

4. **Firewall e segurança**
   - O script de setup aplica regra `ufw` limitando o acesso HTTP à porta 8081 apenas ao IP `94.46.15.210`. Ajuste a variável `YTC_WEB_ALLOWED_IP` (ex.: `YTC_WEB_ALLOWED_IP=1.2.3.4 bash post_deploy.sh`) antes de executar o `post_deploy.sh` se precisar mudar.
   - Mantenha os tokens OAuth fora do repositório e com permissões restritas (`chmod 600`).

## Operação e manutenção

- **Monitorização**: inclua métricas básicas (tempo de resposta, contagem de erros) e alertas caso a API retorne falhas persistentes.
- **Actualizações**: quando a especificação do endpoint mudar, sincronize com `status-endpoint.md` e notifique a equipa web.
- **Fallback**: em caso de indisponibilidade da API, devolva um JSON com `status="unknown"` e mensagem amigável, permitindo que o front-end apresente o aviso secundário.
- **Execução de scripts**: execute primeiro `./scripts/deploy_to_droplet.sh` (que apenas sincroniza ficheiros) e depois, já na droplet, `bash /root/bwb-stream2yt/scripts/post_deploy.sh`. O script instala `python3-venv` se necessário, aplica firewall e deixa a shell fora do virtualenv ao concluir.

