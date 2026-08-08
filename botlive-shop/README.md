# BotLive Shop LIVE

Módulo isolado e desabilitado por padrão para preparação e acompanhamento humano de TikTok Shop LIVE. A versão inicial opera somente com simulador determinístico; não publica, comenta, inicia LIVE nem fixa produtos em conta real.

## Uso

Ative `VITE_SHOP_LIVE_ENABLED=true` no dashboard e rode `npm run dev`. Para testar o núcleo: `python -m unittest discover botlive-shop/tests -v`.

O agente local independente fica em `apps/local-agent`, usa a rota própria `/shop-live/v1` e porta 8765. Instale `requirements-dev.txt` em ambiente virtual, execute `alembic upgrade head` e rode `uvicorn app.main:app --reload --port 8765`. O dashboard conecta em `VITE_SHOP_LIVE_API_URL`.

Capacidades reais de TikTok e DOM são `UNVERIFIED`, desabilitadas e exigem validação e autorização específicas. OBS também não conecta automaticamente. Nenhum cookie ou senha é armazenado.

Consulte `docs/architecture.md`, `docs/research.md`, `docs/security.md` e `docs/compatibility.md`.
