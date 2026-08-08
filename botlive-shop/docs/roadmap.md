# Roadmap do Shop LIVE

Atualizado em 2026-08-08 após análise dos vídeos de referência.

## Concluído — Fase 1

Agente FastAPI isolado, autenticação local, SQLite/Alembic, sessões, produtos, auditoria append-only, simulador determinístico, WebSocket, compliance e dashboard protegido por feature flag.

## Em andamento — Fase 2: operação assistida no navegador

1. Biblioteca administrável de produtos e mídias próprias/autorizadas.
2. Blocos de roteiro vinculados aos produtos.
3. Ordem e duração planejada dos materiais por sessão.
4. Extensão Chrome MV3 com side panel e comunicação autenticada com o agente local.
5. Página simulada local para validar content scripts.
6. Produto atual/próximo, roteiro, comentários e alertas no painel lateral.
7. Checklist assistido para preparação humana no TikTok LIVE Studio.
8. Ações manuais assistidas sempre que não houver API oficial.

## Próxima — Fase 3: presença humana e diagnóstico

Captura consentida e diagnóstico real de câmera/microfone, sem gravação por padrão; luz, FPS, silêncio, clipping, congelamento e presença. Nenhuma transmissão será iniciada automaticamente.

## Futuro opcional, sem prioridade

`ObsWebSocketAdapter` permanece apenas como capacidade futura, separada, desabilitada e dispensável. O Shop LIVE não exigirá instalação ou configuração do OBS.

## Bloqueado por política

Avatar/voz de IA fingindo ser apresentador, vídeo gravado em repetição, comentários automáticos, LIVE autônoma 24h, seletores frágeis, ocultação de alertas e qualquer ação em conta real sem autorização explícita.
