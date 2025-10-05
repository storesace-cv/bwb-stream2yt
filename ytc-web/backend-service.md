# Serviço backend na droplet

Este guia descreve como montar um microserviço HTTP na droplet secundária que consulta a API do YouTube e expõe um endpoint com o estado do canal. O serviço **não** deve retransmitir vídeo; limita-se a autenticar, recolher metadados e devolver um JSON seguro para uso no website.

## Requisitos prévios

- Droplet já configurada com o token OAuth (`/root/token.json`) utilizado pelos scripts `yt_api_probe_once.py`.
- Python 3.11 (o mesmo usado no repositório) e dependências listadas em `requirements-dev.txt` para reuso do cliente da API.
- Pacote `python3-venv` instalado (`apt install python3-venv`) para permitir a criação do ambiente virtual do serviço.
- Acesso SSH privilegiado para configurar `systemd`, firewalls e variáveis de ambiente.

## Passos de implementação

1. **Criar um ambiente isolado**
   - Crie uma pasta, por exemplo `/opt/ytc-web-service`.
   - Configure um `virtualenv` e instale as dependências mínimas (`google-api-python-client`, `fastapi`/`uvicorn` ou `Flask`).

2. **Reutilizar a lógica existente**
   - Copie ou refatore a função que consulta `liveBroadcasts.list` e `liveStreams.list` a partir de `scripts/yt_api_probe_once.py`.
   - Envolva a chamada numa função `fetch_live_status()` que devolve um dicionário pronto para serializar.

3. **Expor um endpoint HTTP**
   - Monte uma aplicação (ex.: FastAPI) com uma rota `GET /api/live-status` que:
     - Lê o token OAuth do caminho definido em variável de ambiente (`YT_OAUTH_TOKEN_PATH`).
     - Aplica cache in-memory de alguns segundos (ex.: 30s) para respeitar a quota da API.
     - Devolve JSON conforme descrito em `status-endpoint.md`.

4. **Configurar `systemd`**
   - Crie um serviço em `/etc/systemd/system/ytc-web.service` que execute o servidor (ex.: `uvicorn app:app --host 127.0.0.1 --port 8081`).
   - Active `systemctl enable --now ytc-web.service` e monitorize os logs com `journalctl -u ytc-web -f`.

5. **Proteger o acesso**
   - A porta do serviço (por omissão `8081`) deve aceitar ligações apenas do IP `94.46.15.210`; os scripts de deploy aplicam esta regra via `ufw`/`iptables`.
   - Após o deploy, confirme que a regra está activa executando `ufw status numbered | grep 94.46.15.210` na droplet secundária.
   - Caso seja necessário acesso público adicional, aplique autenticação básica ou token de acesso simples via cabeçalho.
   - Mantenha os tokens OAuth fora do repositório e com permissões restritas (`chmod 600`).

## Operação e manutenção

- **Monitorização**: inclua métricas básicas (tempo de resposta, contagem de erros) e alertas caso a API retorne falhas persistentes.
- **Actualizações**: quando a especificação do endpoint mudar, sincronize com `status-endpoint.md` e notifique a equipa web.
- **Fallback**: em caso de indisponibilidade da API, devolva um JSON com `status="unknown"` e mensagem amigável, permitindo que o front-end apresente o aviso secundário.

## Automação disponível no repositório

- O deploy automático é orquestrado por `scripts/deploy_to_droplet.sh`, que sincroniza `secondary-droplet/` (incluindo `ytc-web-backend/`) e executa `scripts/post_deploy.sh`.
- O script `secondary-droplet/bin/ytc_web_backend_setup.sh` prepara `/opt/ytc-web-service`, cria o virtualenv, instala as dependências (`secondary-droplet/requirements.txt` + `ytc-web-backend/requirements.txt`) e aplica o unit file `secondary-droplet/systemd/ytc-web-backend.service`.
- Caso o virtualenv fique corrompido (ex.: `pip` ausente), o deploy remove automaticamente `/opt/ytc-web-service/venv` e recria tudo na execução seguinte; confirme o estado com `ls /opt/ytc-web-service/venv/bin/pip` para garantir que o binário existe e é executável.
- As variáveis sensíveis vivem em `/etc/ytc-web-backend.env`. Edite `YT_OAUTH_TOKEN_PATH` (padrão: `/root/token.json`) e `YTC_WEB_BACKEND_CACHE_TTL_SECONDS` conforme a necessidade; o ficheiro é criado com `chmod 600`.
- Após o deploy, valide o serviço com `systemctl status ytc-web-backend.service` e analise logs recentes via `journalctl -u ytc-web-backend.service -n 50`.

