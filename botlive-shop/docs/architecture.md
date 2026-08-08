# Arquitetura e isolamento

Data: 2026-08-08. O módulo vive em `botlive-shop/`. O BotLive existente mantém seu fluxo captura/replay → cortes → fila → adapters. Nenhum serviço legado é importado ou alterado pelo Shop LIVE.

A integração visível é uma aba React condicionada por `VITE_SHOP_LIVE_ENABLED=true`. O agente FastAPI usa processo, prefixo `/shop-live/v1`, SQLite, Alembic, WebSocket e autenticação próprios. A Fase 1 permanece: simulador seed 42 → eventos tipados → compliance → auditoria e dashboard.

## Fluxo principal corrigido

Biblioteca local autorizada → produto → roteiro/blocos → ordem e duração da sessão → agente local autenticado → extensão MV3/side panel → checklist humano no TikTok LIVE Studio.

A extensão inicia limitada à página simulada local e não possui host permission para TikTok. Ações sem API oficial são instruções manuais assistidas. Nenhuma ação real ocorre sem autorização explícita.

OBS não pertence ao fluxo principal. Um possível `ObsWebSocketAdapter` fica fora das próximas prioridades, opcional, desabilitado e sem dependência para instalação ou operação.

As tabelas usam exclusivamente o prefixo `shop_live_`; Alembic é a única fonte do schema. A biblioteca registra caminhos locais, duração e evidência de autorização, mas não publica nem reproduz mídia automaticamente.
