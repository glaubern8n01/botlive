# Compatibilidade e isolamento

A entrega parte de `origin/main` no SHA `6368f255d0719aa9b01ed5b9a1dbf866abe14c65` e preserva integralmente o BotLive legado.

- Windows 10/11: scripts PowerShell, Python 3.12+, Node 20+, Chrome/Chromium e FFmpeg/FFprobe.
- Linux CI: backend, Alembic, TypeScript, builds e Chromium/Playwright.
- Dashboard: feature flag `VITE_SHOP_LIVE_ENABLED` desligada por padrão.
- Agente: somente `127.0.0.1`, prefixo `/shop-live/v1`, tabelas `shop_live_*`, autenticação e dados próprios.
- Extensão: Manifest V3, IDs explicitamente permitidos e host permissions somente para localhost.
- TikTok/OBS/VPS: nenhuma dependência ou acesso.

Tickets HMAC temporários protegem URLs de mídia e WebSocket; o token principal não aparece nessas URLs. Arquivos, banco, backups e PIDs permanecem fora do Git.
