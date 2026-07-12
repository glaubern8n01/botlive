# BotLive — Painel do Vigia

Dashboard web (React + Vite + Tailwind + Supabase) para controlar o vigia
automático de canais Twitch (`PLANO-VIGIA.md` §4): liga/desliga módulos, edita
a config remota (`vigia_config`), gerencia a lista manual de canais
(`vigia_channels`) e acompanha o ledger de execução (`vigia_streams`) e o
índice de dedup (`vigia_clip_index`).

## Rodar local

1. `npm install`
2. Copiar `.env.example` para `.env.local` e preencher `VITE_SUPABASE_URL` e
   `VITE_SUPABASE_ANON_KEY` (Supabase Studio > Settings > API — chave **anon**,
   nunca a service key).
3. `npm run dev` → http://localhost:3000 (senha default: `admin`, muda via
   `VITE_DASHBOARD_PASSWORD`).

## Segurança — ler antes de publicar

A senha é uma checagem **client-side** (cosmética): ela impede curioso casual,
não protege os dados. Quem tiver a anon key (que vai no bundle) fala com o
Supabase direto. Enquanto as tabelas `vigia_*` estiverem sem RLS, **não
publicar este painel em URL pública** — usar só localmente. Para publicar de
verdade: habilitar RLS nas 4 tabelas + Supabase Auth com policies de escrita
para usuário autenticado (o robô não é afetado: usa service key, que bypassa
RLS).

## O que cada página faz

- **Painel** — status geral, canais ativos, lives detectadas hoje, uploads
  hoje vs teto (`max_posts_per_day`).
- **Configuração** — todas as colunas de `vigia_config` (linha única id=1),
  com confirmação extra nos toggles críticos (`enabled`,
  `post_youtube_enabled`).
- **Canais** — CRUD da lista manual (`login`, `priority`, `enabled`, `notes`).
- **Histórico** — ledger `vigia_streams` com status live/VOD separados, erro e
  uploads por transmissão.
- **Índice de cortes** — leitura do `vigia_clip_index` (dedup live×VOD, V6).
  Revisão/aprovação de cortes exige backend de mídia (fase futura).
