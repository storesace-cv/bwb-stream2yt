# SECURITY

- **NUNCA** comitar:
  - `token.json` (tokens OAuth YouTube)
  - `.env` com `YT_KEY`/credenciais
  - `client_secret.json`
- Manter segredos *apenas* no servidor (Droplet) ou em gestores de segredos.
- Usar os ficheiros `*.env.example` como referência sem segredos reais.
