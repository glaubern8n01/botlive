# Compatibilidade

A branch limpa foi criada sobre `origin/main` em `3f2eca1`. O dashboard legado continua passando em typecheck e builds com a feature flag ligada e desligada. A suíte anterior de 151 testes pertencia a 90 commits não relacionados e não foi transplantada.

## Fase 1 preservada

Continuam isolados: endpoints, WebSocket, origem permitida, autenticação local, persistência, migrações, simulador, compliance e auditoria.

## Isolamento da Fase 2

- novas tabelas somente com prefixo `shop_live_`;
- extensão sem acesso ao domínio TikTok;
- content script limitado a `127.0.0.1:8765` e `localhost:8765`;
- biblioteca não move, publica ou reproduz arquivos automaticamente;
- OBS não é dependência;
- nenhuma importação dos módulos legados do BotLive.

Os testes da fase cobrem migrações, biblioteca, autorização de mídia, roteiros, ordem/duração e permissões da extensão.
