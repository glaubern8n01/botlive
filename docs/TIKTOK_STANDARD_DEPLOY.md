# Deploy seguro — TikTok Standard

O serviço `tiktok-public` deve ser criado isoladamente no projeto BotLive do
EasyPanel, sem alterar os serviços existentes. Ele executa
`python tiktok_public_server.py`, usa porta interna `8080`, volume dedicado para
`/app/.tokens/tiktok-standard` e domínio HTTPS público próprio. Dashboard e
worker permanecem nos seus serviços e volumes atuais.

Variáveis protegidas exclusivas do serviço público:

```text
TIKTOK_STANDARD_CLIENT_KEY=<portal>
TIKTOK_STANDARD_CLIENT_SECRET=<portal>
TIKTOK_STANDARD_REDIRECT_URI=https://<host>/auth/tiktok/callback
TIKTOK_STANDARD_TOKEN_ENCRYPTION_KEY=<aleatória e persistente>
TIKTOK_STANDARD_TOKEN_ROOT=/app/.tokens/tiktok-standard
BOTLIVE_DASHBOARD_URL=https://painel.vextriq.online/tiktok
BOTLIVE_PRIVACY_CONTACT=<contato verdadeiro>
```

Nunca copiar valores secretos para build args, variáveis `VITE_*`, Git,
Supabase, screenshots ou logs. O dashboard recebe apenas
`VITE_TIKTOK_AUTH_BASE_URL`.

Antes da migration, exportar as linhas/tabelas relevantes ou criar snapshot do
banco. Antes do deploy, preservar `.env`, `.tokens`, outputs, logs e volumes.
Depois validar que Kwai, YouTube, Instagram e workers continuam saudáveis.

Critérios de liberação:

- OAuth válido e revogação testada;
- escopos reais registrados;
- `TIKTOK_STANDARD_API_ENABLED=0` durante o primeiro OAuth;
- rascunho somente após `video.upload` disponível e consentimento;
- Direct Post permanece desligado até revisão/aprovação;
- nenhuma publicação pública de teste.
