# Arquitetura e isolamento

Data: 2026-08-08. O módulo vive em `botlive-shop/`. O BotLive atual segue o fluxo captura/replay → cortes → fila → adapters e seu dashboard Vite consulta Supabase/servidor local. Nada desse fluxo foi acoplado ao novo backend.

A única integração é uma rota e aba React condicionadas por `VITE_SHOP_LIVE_ENABLED=true`. O agente FastAPI usa processo, prefixo `/shop-live/v1`, armazenamento, WebSocket e dependências próprios. Dashboard → simulador seed 42 → eventos tipados → compliance → alertas/métricas. TikTok e OBS reais permanecem desligados.

Código existente estudado para evolução: feature flags, contratos de publicação, fila append-only, entrega de mídia e identidade visual. Não foi reutilizado diretamente para evitar regressão.

Na Fase 1, o dashboard abre um WebSocket somente quando a aba protegida pela flag é carregada. O agente gera o cenário seed 42, avalia sinais no compliance engine, transmite cada evento e persiste produtos, sessões e auditoria append-only em tabelas `shop_live_*`. Alembic é a fonte de migração; `create_all` existe apenas para conveniência segura de desenvolvimento local.
