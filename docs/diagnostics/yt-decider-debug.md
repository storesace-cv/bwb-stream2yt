# Colectar logs do `yt-decider-daemon`

O script `scripts/yt-decider-debug.sh` facilita a recolha de evidências quando a automação do fallback apresenta falhas (por exemplo, o backup não liga automaticamente ou o daemon reinicia repetidamente).

## O que o script recolhe
- **Contexto do host** (hostname, kernel e janela temporal em UTC).
- **`journalctl -u yt-decider-daemon`** filtrado para mensagens com a tag `[yt_decider]` das últimas 48 horas.
- **`systemctl status yt-decider-daemon`** para capturar o estado actual.
- **`/root/bwb_services.log`** filtrado pela mesma tag, limitado à mesma janela temporal ou, se necessário, às últimas 10 000 linhas.

O resultado é gravado no ficheiro `yt-decider-<timestamp>.log` no directório onde o script é executado.

## Como executar na droplet
```bash
# Entrar via SSH no host secundário
ssh -p 2202 root@<ip-da-droplet>

# A partir do directório do repositório clonado na droplet
cd /root/bwb-stream2yt
bash scripts/yt-decider-debug.sh
```

Durante a execução, o script mostra o destino do ficheiro (`yt-decider-YYYYMMDDTHHMMSSZ.log`). Após concluído, transfira-o para o seu computador (por exemplo, com `scp`) ou anexe-o directamente ao relatório de incidente.

## Quando utilizar
- O fallback permaneceu desligado apesar de a primária estar em falha.
- O `yt-decider-daemon` reinicia continuamente ou apresenta erros de autenticação (por exemplo, `Temporary failure in name resolution`).
- Necessidade de anexar evidências consolidadas a um *post-mortem*.

Para orientar a interpretação dos dados recolhidos, consulte também os guias existentes:
- [Diagnóstico da interrupção de 6 de Outubro de 2025](20251006-secondary-backup.md)
- [Checklist geral de logs do fallback](youtube-fallback-logs.md)
- [Análise da interrupção de 9 de Outubro de 2025](20251009-stream-crash.md)
