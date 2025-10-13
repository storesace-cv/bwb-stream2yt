# Interpretando o campo "Sinal da câmara" no diagnóstico da aplicação Windows

O ficheiro `stream2yt-diags-*.txt`, gerado pela aplicação Windows (`primary`),
resume na secção **"Sinal da câmara"** o resultado do `ffprobe` configurado
para validar se o stream RTSP continua acessível.

## Estados possíveis

| Linha no relatório | Significado | Ação recomendada |
| --- | --- | --- |
| `Sinal da câmara: disponível (último sucesso: …)` | O `ffprobe` conseguiu ligar-se ao RTSP dentro do timeout configurado. | Nenhuma ação: a câmara está a responder. |
| `Sinal da câmara: indisponível (<detalhe do erro>)` | O `ffprobe` não obteve dados a tempo. O detalhe inclui erros como *timeout* ou *autenticação falhada*. | Verifique rede, credenciais e se a câmara está ligada. Enquanto este estado persistir, a aplicação **não tem feed da câmara**. |
| `Sinal da câmara: não foi possível determinar (…)` | O `ffprobe` não chegou a executar (por exemplo, binário ausente). | Corrija a configuração antes de tentar transmitir. |

## Exemplo concreto (13 de outubro de 2025)

O diagnóstico `logs/stream2yt-diags-13T003745.txt` apresenta:

```
- Sinal da câmara: indisponível (ffprobe excedeu timeout de 7.0s)
```

Este texto confirma que, naquele instante, o `ffprobe` não recebeu frames
antes do limite de 7 s — logo, **não havia comunicação ativa com a câmara**.
Mesmo que outros componentes (como o watcher remoto) reportem `camera_snapshot_present=True`,
confie no diagnóstico local da aplicação Windows para aferir a conectividade da câmara,
pois ele resulta de uma tentativa direta de leitura do stream RTSP.

### Porque é que o watcher pode indicar `camera_snapshot_present=True` mesmo sem câmara

O watcher que corre no droplet secundário só consegue ver o último *heartbeat*
enviado pelo emissor Windows. O campo `camera_snapshot_present` é calculado a
partir dessa mensagem HTTP: indica apenas que o emissor conseguiu gerar e
enviar uma captura de ecrã em algum momento recente. O watcher **não** volta a
consultar o RTSP; por isso, se a câmara perder alimentação ou ficar inacessível
(por exemplo, não responde a `ping`), o valor pode continuar a ser `True` até
que a aplicação Windows volte a reportar explicitamente a falha.

> ℹ️ **Novo:** o watcher secundário passa agora a tentar um `ping` directo para a câmara
> sempre que recebe um heartbeat. Se o equipamento estiver sem energia ou
> inacessível na rede, o campo `network_ping.reachable` será `false` e o
> `camera_snapshot_present` será forçado para `false`, mesmo antes do
> diagnóstico Windows actualizar o estado. Use esta informação como segunda
> camada de confirmação.

Assim, perante alarmes vindos do watcher mas com `camera_snapshot_present=True`
ou `network_ping.reachable=false`, siga estes passos:

1. Consulte o relatório `stream2yt-diags-*.txt` mais recente e confirme a
   linha **"Sinal da câmara"**.
2. Verifique manualmente a câmara (ping, alimentação eléctrica, LEDs de
   actividade). Quando o watcher já reportar `network_ping.reachable=false`,
   tem indícios de falha de rede/alimentação vindos do droplet.
3. Aguarde pelo próximo relatório gerado pela aplicação Windows: quando ela
   detetar a falha, a linha passará para `indisponível` com o detalhe do erro
   (p. ex. timeout do `ffprobe`).

Enquanto essa confirmação não chegar, trate o estado real da câmara como
desconhecido — o watcher apenas reflecte o último *heartbeat*, não uma
verificação em tempo real do dispositivo físico.

Quando o sinal regressa, o relatório volta a indicar `disponível` e inclui a
marca temporal do último sucesso.
