# ytc-web-backend

## Verificando dependências do sistema

Antes de executar o script de setup (`bin/ytc_web_backend_setup.sh`) confirme que a droplet possui o módulo `venv` instalado para o Python 3. Sem ele, a criação do ambiente virtual irá falhar.

Execute um dos comandos abaixo:

- `dpkg -s python3-venv` — retorna o estado do pacote e confirma se está instalado.
- `python3 -m venv --help` — imprime a ajuda do módulo `venv` quando está disponível.

Caso os comandos indiquem ausência do módulo/pacote, instale-o com `apt install python3-venv` (ou a variante específica da versão, por exemplo `python3.11-venv`).
