# Solução de problemas

- **401 / offline:** confira o token de `.env.local`; ele não é registrado em logs. Reabra o dashboard e autentique novamente.
- **Extensão recusada:** inclua exatamente o ID MV3 em `SHOP_LIVE_ALLOWED_EXTENSION_IDS` e reinicie o agente.
- **Mídia recusada:** confirme extensão, MIME, assinatura do arquivo, autorização e limites `SHOP_LIVE_MEDIA_MAX_BYTES` / `SHOP_LIVE_MEDIA_TOTAL_MAX_BYTES`.
- **Sem duração/resolução:** execute `ffprobe -version`; WAV possui fallback, demais formatos exigem FFprobe.
- **Câmera/microfone:** conceda permissão somente para `127.0.0.1`, escolha o dispositivo e feche aplicativos que o estejam usando.
- **Câmera congelada / silêncio:** reconecte o dispositivo e repita o diagnóstico antes da operação.
- **Recuperação:** reinicie agente/dashboard, autentique e selecione a sessão; fila, runtime, auditoria e progresso persistido são restaurados. Sessões interrompidas permanecem identificadas.
- **Banco:** não apague manualmente. Use backup e `alembic upgrade head`.
- **Portas ocupadas:** encerre os processos com `Stop-ShopLive.ps1` ou altere os scripts conscientemente; nunca exponha `0.0.0.0`.
