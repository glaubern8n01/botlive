# Fase 2 — mídia local autorizada

Esta fase mantém o Shop LIVE atrás de `VITE_SHOP_LIVE_ENABLED=false` por padrão e não altera o BotLive legado. O agente continua ligado somente em `127.0.0.1`; os arquivos mutáveis ficam exclusivamente no caminho absoluto `botlive-shop/data/`, ignorado pelo Git.

## Fluxo implementado

1. O operador escolhe um arquivo próprio/autorizado no dashboard e confirma sua origem.
2. O agente valida extensão, MIME, assinatura básica e limite de tamanho antes de aceitar MP4, WebM, MP3, WAV ou M4A.
3. O arquivo recebe nome UUID interno, fica confinado à raiz de mídia e tem duração, formato, tamanho e resolução obtidos por `ffprobe` (WAV possui fallback nativo).
4. A fila usa a ordem persistida em `shop_live_session_materials`. Os comandos manuais iniciar, pausar, continuar, avançar e encerrar atualizam `shop_live_media_playback` e são publicados pelo WebSocket ao dashboard e ao side panel.
5. A fila encerra no último item; não há loop. A exclusão física é recusada enquanto qualquer sessão referencia a mídia.

Eventos de upload, falha, reprodução, avanço, bloqueio e exclusão são append-only em `shop_live_audit_events`. O schema é criado exclusivamente pelas migrações Alembic.

## Limites deliberados

Não há download automático, TikTok, OBS, VPS, publicação externa ou LIVE autônoma. A reprodução ocorre no player local do navegador e requer ação do operador. O simulador de audiência/comentários da Fase 1 permanece simulado e separado do arquivo local.
