# 2025-10-11 – Captura do endpoint `/status`

## Contexto
O operador capturou tráfego na droplet `104.248.134.44` usando `tcpdump` para observar a comunicação da aplicação Windows (User-Agent `BWBPrimary/2024.09`). O objetivo era confirmar que a aplicação está a contactar o serviço HTTP interno e recolher detalhes da carga útil.

## Principais observações
- **Origem/Destino:** o cliente (`105.174.31.242`) estabelece TCP para `104.248.134.44:8080`, confirmando que o serviço está acessível na porta 8080 pública.
- **Ciclo de pedidos:** foram vistos pedidos `POST /status` a cada ~20 segundos. Cada ligação é encerrada após o pedido/resposta (`Connection: close` em ambos os lados).
- **Cabeçalhos do cliente:** `Content-Type: application/json`, `Content-Length: 753`, `Accept-Encoding: identity`. Isto confirma que envia JSON em texto claro sem compressão.
- **Resposta do servidor:** `HTTP/1.1 200 OK` com `Server: BWBStatusMonitor/1.0 Python/3.10.12` e corpo JSON de 140 bytes. O servidor fecha a ligação com um FIN logo após enviar a resposta.
- **Integridade do handshake:** o 3-way handshake completa-se corretamente; não há retransmissões nem resets. O checksum reportado como "incorrect" pelo `tcpdump` é esperado porque a offload da NIC é aplicada após a captura.

## Próximos passos sugeridos
1. **Recolha do payload completo:** guardar para ficheiro `pcap` (`-w`) e abrir no Wireshark para analisar os 753 bytes de JSON enviados pelo cliente.
2. **Correlacionar com logs da aplicação:** ativar logging de debug no serviço Python para confirmar que o payload chega e é processado.
3. **Monitorizar periodicidade:** usar `tcpdump -tttt` ou `watch -n` para confirmar se a periodicidade continua estável e se surgem outros endpoints além de `/status`.
4. **Verificar TLS futuro:** se se pretender proteger estes dados, planear migração para HTTPS (terminação TLS com `nginx` ou `caddy`).

Esta captura demonstra que a aplicação Windows comunica corretamente com o endpoint `/status` na droplet e que o serviço responde com sucesso.
