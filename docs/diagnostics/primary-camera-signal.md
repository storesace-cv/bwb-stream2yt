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

Quando o sinal regressa, o relatório volta a indicar `disponível` e inclui a
marca temporal do último sucesso.
