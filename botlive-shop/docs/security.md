# Segurança e modelo de ameaças

Ativos: catálogo, roteiros, arquivos autorizados, auditoria, relatórios e futuros tokens oficiais. Ameaças principais: path traversal, arquivo disfarçado, origem não autorizada, exposição de token, replay, XSS, mídia órfã e automação incompatível com a plataforma.

Controles: payloads Pydantic; extensão/MIME/assinatura/tamanho; nomes UUID e confinamento por caminho resolvido; agente em `127.0.0.1`; CORS e IDs MV3 explícitos; comparação de token em tempo constante; segredo apenas em `sessionStorage`/`chrome.storage.session`; tickets HMAC curtos em URLs; `nosniff` e `no-store`; auditoria append-only; Alembic como fonte do schema; backup local; limpeza apenas de órfãos; arquivos de dados ignorados pelo Git.

Logs não devem conter token, cookie, senha, mídia ou conteúdo de câmera/microfone. Autenticação só pode ser desativada em testes controlados. São proibidos seletores frágeis, cookies TikTok, evasão de moderação, comentários automáticos, repetição disfarçada, avatar/voz artificial fingindo presença e operação autônoma.
