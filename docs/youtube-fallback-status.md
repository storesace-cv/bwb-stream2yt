# Estado do youtube-fallback.service

## Observações da telemetria

Os registos apresentados indicam que o `youtube-fallback-watcher.service` está activo e a reportar `fallback_active=False` durante todos os ciclos de verificação. Isto significa que, do ponto de vista do watcher, o fluxo principal está saudável e o fallback não deveria estar a ser usado.

Apesar disso, o `systemctl status youtube-fallback.service` mostra o serviço de fallback como `active (running)` com um processo `ffmpeg` em execução. Portanto, neste momento o serviço encontra-se ligado.

## Conclusão

Com base nestes dados, seria expectável que o `youtube-fallback.service` estivesse desligado quando `fallback_active=False`. O facto de continuar em execução sugere que o serviço foi iniciado manualmente ou que existe uma discrepância na lógica que deveria pará-lo automaticamente. Recomenda-se verificar os triggers do watcher e o comportamento configurado para o serviço de fallback.
