# Integração Web do Canal YouTube

Esta pasta documenta e reúne artefactos auxiliares para criar um "add-on" web que permite incorporar o canal e a transmissão ao vivo do YouTube num site personalizado. O objectivo é facilitar o acesso ao vídeo oficial (URL primária) diretamente no browser, preservando a arquitectura actual em que a droplet apenas trata de autenticação e automatismos, sem redistribuir o sinal.

## Componentes chave

- **Serviço backend** na droplet, responsável por consultar a API do YouTube com o token OAuth já existente e expor um endpoint JSON público ou autenticado.
- **Integração front-end** que consome esse endpoint e apresenta o player embebido do YouTube com mensagens de fallback adequadas.
- **Guias operacionais** com recomendações de segurança, deployment e manutenção.

## Como navegar nesta pasta

| Ficheiro | Conteúdo |
| --- | --- |
| `backend-service.md` | Passos para levantar um microserviço HTTP na droplet que expõe o estado do canal.
| `status-endpoint.md` | Contrato de dados do endpoint JSON (campos, exemplos e caching recomendado).
| `frontend-integration.md` | Boas práticas para embutir o player do YouTube e lidar com diferentes estados do stream.

## Workflow sugerido

1. **Preparar o backend** seguindo `backend-service.md`, sincronizando o repositório e executando `post_deploy.sh` na droplet para configurar automaticamente o serviço FastAPI e a firewall.
2. **Validar o contrato** comparando a resposta real com o documento `status-endpoint.md` e ajustando conforme necessário.
3. **Implementar o site** com base nas orientações de `frontend-integration.md`, mantendo o tráfego de vídeo sempre através do YouTube.

## Manutenção

- Actualize esta pasta sempre que novos requisitos web surgirem (ex.: chat ao vivo, agenda de eventos).
- Registe alterações relevantes no repositório e comunique à equipa de operações para alinhamento com as dependências existentes.

