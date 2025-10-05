# Integração front-end

Este guia apresenta recomendações para construir uma página web que consome o endpoint `live-status` e apresenta o vídeo oficial do canal via player do YouTube.

## Fluxo básico

1. No carregamento da página, fazer `fetch` ao endpoint (`GET /api/live-status`).
2. Avaliar o campo `status` e decidir o que renderizar:
   - `live`: inserir `<iframe>` com `https://www.youtube.com/embed/{videoId}?autoplay=1&rel=0`.
   - `starting`: mostrar o player com uma sobreposição de “vai começar dentro de momentos”.
   - `offline` ou `unknown`: esconder o iframe e apresentar a mensagem devolvida pelo backend (ex.: imagem de fundo usada na transmissão secundária).
3. Actualizar periodicamente (ex.: a cada 60s) para detectar mudanças de estado.

## Exemplo de código

```html
<div id="live-container" class="live-container">
  <p>Carregando…</p>
</div>

<script type="module">
async function renderLive() {
  const container = document.getElementById('live-container');
  try {
    const response = await fetch('/api/live-status', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    if (data.status === 'live' && data.videoId) {
      container.innerHTML = `
        <iframe
          width="100%"
          height="100%"
          src="https://www.youtube.com/embed/${data.videoId}?autoplay=1&rel=0"
          title="${data.title ?? 'Transmissão ao vivo'}"
          frameborder="0"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowfullscreen
        ></iframe>`;
    } else {
      container.innerHTML = `<div class="live-fallback">${data.message ?? 'Voltamos já.'}</div>`;
    }
  } catch (error) {
    console.error('Falha ao consultar live-status', error);
    container.innerHTML = '<div class="live-error">Não foi possível carregar a transmissão.</div>';
  }
}

renderLive();
setInterval(renderLive, 60000);
</script>
```

## Boas práticas de UX

- **Responsividade**: envolva o iframe numa `div` com proporção 16:9 usando `padding-top` ou `aspect-ratio`.
- **Acessibilidade**: forneça texto alternativo nas mensagens de fallback e traduza conforme o público-alvo.
- **Indicadores de estado**: considere mostrar o `data.updatedAt` formatado (“actualizado há X segundos”) para reforçar a frescura dos dados.

## Considerações de segurança

- Carregue o endpoint via HTTPS para evitar mistura de conteúdo.
- Não exponha chaves ou tokens no front-end; toda a autenticação permanece na droplet.
- Respeite as políticas de reprodução automática do navegador — alguns exigem interação do utilizador para iniciar áudio.

## Extensões possíveis

- Integrar o chat ao vivo com `https://www.youtube.com/live_chat?v={videoId}&embed_domain=<domínio>`.
- Mostrar a agenda de próximas emissões usando `nextEvents` quando disponível.
- Disparar webhooks internos quando o estado mudar para `offline` para alertar a equipa.

