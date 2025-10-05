# Contrato do endpoint `/api/live-status`

Este documento define o formato recomendado para o endpoint JSON exposto pela droplet. O objectivo é fornecer ao front-end dados suficientes para decidir se deve mostrar o player da transmissão principal, o aviso secundário ou outra informação complementar.

## Estrutura da resposta

```json
{
  "status": "live",
  "videoId": "<ID do vídeo YouTube>",
  "title": "Nome do programa ou transmissão",
  "scheduledStartTime": "2024-01-30T19:00:00Z",
  "actualStartTime": "2024-01-30T19:05:12Z",
  "health": {
    "streamStatus": "active",
    "healthStatus": "good"
  },
  "updatedAt": "2024-01-30T19:06:00Z",
  "message": "Estamos ao vivo!"
}
```

### Campos obrigatórios

- `status`: estado agregado do canal. Valores sugeridos:
  - `live` — transmissão ao vivo confirmada.
  - `starting` — broadcast encontrado em `testing` ou `ready`.
  - `offline` — nenhum broadcast activo; mostrar última emissão ou aviso padrão.
  - `unknown` — erro na API ou dados indisponíveis.
- `updatedAt`: timestamp ISO8601 do momento em que a API foi consultada.

### Campos opcionais

- `videoId`: presente quando `status` for `live` ou `starting`.
- `title`, `scheduledStartTime`, `actualStartTime`: metadados obtidos de `liveBroadcasts.list`.
- `health`: resumo de `streamStatus` e `healthStatus` devolvidos por `liveStreams.list`.
- `message`: texto amigável para ser exibido no site (ex.: “Voltamos já” quando `status=offline`).

## Regras de caching

- **Cache interno**: mínimo 30 segundos para evitar exceder quotas da API YouTube.
- **Cache HTTP**: permitir `Cache-Control: public, max-age=10` para reduzir carga na droplet, mantendo actualizações quase em tempo real.
- **Etag opcional**: pode facilitar invalidação quando o `updatedAt` muda.

## Tratamento de erros

- Em falha temporária da API, devolver `status="unknown"` e `message` apropriada.
- Registar (logar) o `error.code` e `error.message` recebidos, sem repassar detalhes sensíveis para o cliente.
- Evitar devolver stack traces ou dados internos.

## Extensões futuras

- `nextEvents`: lista com próximas transmissões agendadas.
- `chatEmbedUrl`: link para incorporar o chat ao vivo, quando aplicável.
- `analytics`: contadores agregados não sensíveis (ex.: espectadores simultâneos), se a quota permitir.

