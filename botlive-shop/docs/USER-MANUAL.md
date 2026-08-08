# Manual do Shop LIVE assistido

## Fluxo completo

1. Instale com `scripts/Install-ShopLive.ps1`; use `-InstallFFmpeg` somente se desejar que o `winget` instale FFmpeg.
2. Inicie com `scripts/Start-ShopLive.ps1 -Mode production`, abra `http://127.0.0.1:3017/shop-live` e informe o token local.
3. Na Biblioteca, cadastre produtos e roteiros e envie apenas MP4, WebM, MP3, WAV ou M4A próprios/autorizados. Pesquise, filtre, edite, duplique, arquive e organize por tags.
4. Em Montagem, crie a sessão, arraste a fila e associe produto, roteiro e duração a cada mídia.
5. Em Câmera e microfone, escolha dispositivos e conceda permissão. O teste permanece no navegador local e não grava nem transmite.
6. Complete o checklist. Abra e configure o TikTok LIVE Studio manualmente, confira a conta e mantenha o operador presente.
7. Use **Iniciar ensaio** para percorrer câmera, microfone, fila, teleprompter e atalhos sem plataforma externa.
8. Em operação assistida, o Shop LIVE mostra instruções; somente o operador inicia, altera ou encerra a LIVE no TikTok LIVE Studio.
9. Encerre a sessão e exporte relatório JSON/CSV. Faça backup local em Configurações.

## Atalhos padrão

- `Espaço`: pausar/continuar mídia.
- `Seta direita` / `Seta esquerda`: próximo/anterior.
- `T`: pausar/continuar teleprompter.

Nenhum atalho atua sobre páginas ou contas TikTok. Não há loop automático, comentários automáticos, avatar, voz artificial ou operação autônoma.
