# BotLive Shop LIVE

Módulo isolado e desabilitado por padrão para preparação e acompanhamento humano de TikTok Shop LIVE. Não publica, comenta, inicia LIVE nem fixa produtos em conta real.

## Agente local

Configure um `SHOP_LIVE_LOCAL_TOKEN` longo, instale `apps/local-agent/requirements-dev.txt`, execute `alembic upgrade head` e rode `uvicorn app.main:app --reload --port 8765`. O dashboard solicita o token e o mantém apenas na sessão da aba.

## Extensão simulada

Carregue `apps/extension/` como extensão descompactada no Chrome. Ela possui side panel e content script somente para `http://127.0.0.1:8765/shop-live/simulator-page`; não possui acesso ao TikTok.

Capacidades reais de TikTok e DOM são `UNVERIFIED` e desabilitadas. OBS é futuro, opcional e não faz parte do fluxo principal. Nenhum cookie ou senha é armazenado.

Consulte `docs/architecture.md`, `docs/roadmap.md`, `docs/research.md`, `docs/security.md` e `docs/compatibility.md`.

A mídia local autorizada da Fase 2 está descrita em `docs/PHASE-2-LOCAL-MEDIA.md`; o armazenamento é configurável, ignorado pelo Git e não envolve OBS.

Para instalar e operar a entrega completa, consulte `docs/INSTALL-WINDOWS.md`, `docs/USER-MANUAL.md`, `docs/TROUBLESHOOTING.md` e `docs/TIKTOK-OFFICIAL-INTEGRATION.md`.
