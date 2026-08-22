# Relatório — Botlive/Vigia em produção real (13/07/2026)

> Documento de handoff. Pode ser colado numa sessão nova do Claude para dar
> contexto completo do estado do sistema. Não contém segredos — os locais de
> cada credencial estão indicados.

## O que é o sistema

**Botlive** (repo `G:\botlive`, GitHub `glaubern8n01/botlive`, branch `main`):
robô que corta highlights de lives/VODs da Twitch (nicho GTA RP pt-BR), gera
vertical 9:16 com legenda de IA (claude-haiku-4-5) e posta no YouTube (canal
"GTA6 Brasil cortes oficial") e Instagram (Reels). O **Vigia** (`watcher.py`)
é o orquestrador 24/7: descobre lives, despacha jobs de captura ao vivo
(Etapa C, pipe streamlink) e de reprocesso de VOD, controla orçamento de
uploads e agora promove Reels.

## Estado em produção (fim de 13/07/2026)

- **VPS**: 69.62.96.161 (EasyPanel em easypanel.gmspeed.com, 4 vCPU/15.6GB).
  Serviço swarm `botlive_botlive-app`, imagem `easypanel/botlive/botlive-app:latest`
  buildada do commit **`bbe362a`**. SSH root por chave a partir do PC do Glauber.
- **Vigia LIGADO** (`enabled=true`): poll de 60s, descoberta aberta (top GTA pt
  ≥100 viewers, máx 3/ciclo) + 7 canais manuais (paulinholokobr prio 1;
  quinnyrp, 4rthurtv, vovo, sorrisodozorlak, dantas, ventura prio 10).
- **Post YouTube LIGADO**: modo live → cortes em tempo real sobem como
  **private** (rascunho; Glauber publica no Studio) com teto próprio
  `max_posts_per_day_live=2` uploads/dia; modo VOD → **unlisted** com teto
  `max_posts_per_day=4` uploads/dia. Cada corte = 2 uploads (HD + vertical).
  Quota do YouTube ≈ 6 uploads/dia (10.000 units, 1.600/upload).
- **Crédito dinâmico**: cada corte leva `@<canal de origem>` na tarja do
  vertical, título, descrição e tags. Vale enquanto `vigia_config.credito_streamer`
  ficar **NULL** (preencher no dashboard tornaria fixo para todos — não fazer).
- **Primeiros resultados reais**: cortes do vovo e do chapo_dizona postados
  private, revisados e publicados pelo Glauber (HD público: R5sy-GntJc4 e
  HUdG72ngRW0). Primeiro job VOD automático rodou para sorrisodozorlak.

## Instagram/Reels — pronto no código, aguardando 3 passos

**Fluxo implementado (commit `bbe362a`)**: "aprovou no YouTube → sai no
Instagram". Quando o Glauber muda um corte postado para **público** no Studio,
o promotor do vigia (`watcher._promover_instagram`, roda a cada ciclo, 1 unit
de quota por lote de 50 vídeos) detecta e posta o vertical como Reel
(`instagram_publisher.py`: container REELS + upload resumável local via
rupload.facebook.com + poll + publish). Nenhum Reel sai sem aprovação manual
(Reel é sempre público; a API não tem rascunho). Idempotente pelo bloco
`postagens.instagram` do publish.json; na dúvida (API fora), não posta.

**Pendências para ativar (em ordem):**
1. **Glauber**: vincular a conta Instagram do GTA à Página do Facebook
   "Gta6brasilcortes" (id 1129299193609513) — app do Instagram → Editar perfil
   → (virar conta Profissional) → Página. Verificado várias vezes via
   `/me/accounts`: a Página segue SEM `instagram_business_account`; sem isso a
   Graph API não tem destino. A Página "Fluminutotricolor" tem IG vinculado e
   serviu para validar todo o fluxo de auth.
2. **Glauber**: rodar no SQL Editor do Supabase:
   `alter table vigia_config add column if not exists post_instagram_enabled boolean not null default false;`
   (seção 6 do `supabase/vigia_schema.sql`; sem a coluna o promotor fica
   inerte por design).
3. **Autorizar a conta** (1 comando na VPS; token Meta já staged em
   `/root/ig_token.txt`, chmod 600):
   `docker cp` do token pro container + `python instagram_publisher.py autorizar --conta principal --token-file ... --pagina Gta6brasilcortes`
   → grava `.tokens/instagram/principal.json` no volume. Depois ligar o toggle
   "Reels no Instagram" no dashboard.

**Token Meta**: System User do app "glauberatende" (plataforma Facebook,
NUNCA expira, escopos instagram_basic + instagram_content_publish + outros).
Guardado no `.env` local (`IG_SYSTEM_USER_TOKEN`, gitignored) e na VPS.
⚠️ Foi colado em chat em 13/07 — recomendado regenerar no Business Settings.

## Dashboard web

- **Público**: https://painel.vextriq.online — Basic Auth do traefik (usuário
  `glauber`; senha entregue no chat de 13/07), HTTPS Let's Encrypt, DNS A
  `painel` → VPS criado na Hostinger. Páginas: Painel, Configuração (todos os
  toggles/tetos, confirmação nos críticos), Canais, Histórico, Índice de Cortes.
- Serviço swarm `botlive_dashboard` (nginx:alpine com build do Vite) foi criado
  **manualmente** (`docker service create`, redes easypanel + easypanel-botlive)
  porque o Deploy do EasyPanel exige imagem de registry (pull denied para
  imagem local). **Não usar o botão Deploy do serviço "dashboard" no painel.**
  Para atualizar: rebuild do Vite local → tar → `docker build` em
  `/root/dashboard-site` na VPS → `docker service update --force botlive_dashboard`.
- Segurança: a anon key do Supabase vai no bundle e as policies RLS são
  abertas (`dashboard_all` para anon) — o Basic Auth é o gate real. Melhorar
  com Supabase Auth + policies restritas em fase futura.

## Incidentes e quirks importantes (para não redescobrir)

1. **Token OAuth do YouTube expira em 7 dias**: o app no Google Cloud Console
   está em modo *Testing*. Expirou em 13/07 e derrubou o post do primeiro
   corte (recuperado com repost). **PENDENTE CRÍTICO: Glauber publicar o app
   "Em produção" no Console**, senão o post quebra de novo em ~20/07.
   Re-autorização que funciona nesta máquina (AVG MITM + Python 3.14 estrito
   quebram TLS local até com bundle de CAs): rodar o fluxo num container na
   VPS com `run_local_server(bind_addr='0.0.0.0', port=8765, open_browser=False)`
   + `docker run -p 127.0.0.1:8765:8765` + túnel `ssh -L 8765:127.0.0.1:8765`
   do PC + abrir a URL no navegador padrão do Glauber. Token cai direto no
   volume `botlive-tokens`.
2. **EasyPanel guarda env em LMDB binário**; envs adicionadas só via
   `docker service update` somem num Deploy do painel. Mitigação implementada:
   `twitch_api.py` tem fallback de credenciais em
   `.tokens/twitch/app_credentials.json` (arquivo já gravado no volume).
3. **Trava de post é otimista por despacho**: dois jobs despachados no mesmo
   ciclo não veem os uploads previstos um do outro — pode passar do teto até
   (capturas simultâneas × cortes × 2). FIX PENDENTE (simples): somar
   uploads previstos dos jobs em voo na checagem.
4. **Content ID**: cortes de GTA RP pegam claims de música (rádio do jogo /
   som do streamer). Claim ≠ strike: sem impacto no canal; só divide receita
   futura daquele vídeo. Como o fluxo público passa pela revisão manual do
   Glauber, ele filtra antes. No Instagram a Meta MUTA/derruba Reel com música
   reivindicada — cortes com música dominante não devem ser aprovados para
   Reel. FIX OPCIONAL pendente: detector heurístico de música no pipeline
   (marcar `musica_detectada` no publish.json e segurar o post).
5. **Twitch live via streamlink**: ads SCTE quebravam o segmentador
   (`-c copy`); solução em produção é pipe `streamlink --stdout | ffmpeg`
   só para live da Twitch (commit c8a0580), validada local e na VPS.
6. **Máquina local do Glauber**: AVG intercepta TLS; yt-dlp/streamlink locais
   precisam `BOTLIVE_TLS_NO_VERIFY=1`; urllib para *.facebook.com também
   quebra — testes de Meta/Google sempre na VPS.

## Configuração atual da vigia_config (Supabase projeto bxvfsrnbublirnzoufbr)

| Campo | Valor |
|---|---|
| enabled | true |
| manual_channels_enabled / discovery_enabled | true / true |
| live_mode_enabled / vod_mode_enabled | true / true |
| discovery: game/lang/min_viewers/max_channels | GTA V / pt / 100 / 3 |
| max_cortes_live / max_cortes_vod | 1 / 2 |
| post_youtube_enabled (VOD unlisted) | true, teto 4 uploads/dia |
| post_live_enabled (live private) | true, teto 2 uploads/dia |
| post_instagram_enabled | (coluna ainda não criada — passo 2 acima) |
| credito_streamer | NULL (= dinâmico por canal; manter NULL) |
| credito_canal | @GTA6brasilcortesoficial |
| max_concurrent_captures / renders | 2 / 1 |

## Roadmap curto

1. Glauber: vincular IG à Página + SQL da seção 6 + publicar app OAuth no Google.
2. Autorizar conta IG na VPS + ligar toggle → primeiros Reels (os 2 cortes já
   públicos disparam sozinhos).
3. Fix da trava otimista (uploads em voo).
4. Detector de música (opcional).
5. V6 do plano: dedup live×VOD por stream_id (tabela vigia_clip_index pronta).
6. Compliance do YouTube para posts public direto + Supabase Auth no dashboard.
