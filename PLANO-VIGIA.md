# PLANO — Vigia automático de canais Twitch

> Fase de plano (11/07/2026, sessão Fable). Sem código ainda. Este doc é a referência
> pra implementação continuar em qualquer sessão futura (Opus). Regra nº 1: nada do
> que existe (VOD manual, live manual, lote, auto-post) muda de comportamento.

## 1. Arquitetura geral

### O que o vigia É
Um processo orquestrador de longa duração (`watcher.py`, novo arquivo), exposto como
`--modo vigia` no `main.py` e `BOTLIVE_MODO=vigia` no entrypoint. Ele NÃO processa
vídeo: ele decide O QUE processar e dispara **subprocessos** `python main.py ...`
com os modos que já existem e já estão validados na VPS:

- live ao vivo  → subprocesso `--modo live-clips` (Etapa C, captura contínua)
- VOD pós-live  → subprocesso `--modo vod-clips` (o fluxo validado na VPS em 11/07)

### Por que subprocessos (decisão de arquitetura)
1. Zero risco de regressão: o pipeline atual não é tocado; o vigia só monta argv.
2. Isolamento de falha: um job que crasha não derruba o vigia (mesma filosofia do
   `_processar_lote`, que já captura exceção por link).
3. Os modos manuais continuam funcionando identicamente (vigia usa `session_id`
   com prefixo próprio `vigia_<stream_id>_<live|vod>`, sem colidir com sessões manuais).

### Loop do vigia (ciclo a cada `poll_interval_seconds`, default 60s)
1. Lê config do Supabase (com cache em disco; ver §4). Se `enabled=false`, dorme.
2. Monta a lista de canais-alvo:
   a. manuais (`vigia_channels` com `enabled=true`), em ordem de `priority`;
   b. descoberta aberta (se ligada): Helix `Get Streams?game_id=<GTA>` → top canais
      por `viewer_count` respeitando `discovery_min_viewers` e `discovery_max_channels`.
3. Uma chamada Helix `Get Streams?user_login=...` (até 100 logins por request) diz
   quem está AO VIVO agora + `stream_id` + `started_at` + `viewer_count`.
4. Para cada live nova (stream_id que não está em `vigia_streams`):
   - insere em `vigia_streams` (INSERT com unique em stream_id = lock natural);
   - se `live_mode_enabled` e houver vaga de captura: dispara job live e grava
     `capture_start_utc` (âncora do dedup, ver §3).
5. Para cada stream que SAIU da lista de lives (ou cuja captura terminou):
   - marca `ended_at`; agenda job VOD para `ended_at + vod_delay_minutes`.
6. Para cada stream com VOD pendente e delay vencido (se `vod_mode_enabled`):
   - Helix `Get Videos?user_id=<id>&type=archive` → acha o VOD cujo campo
     `stream_id` bate → dispara `vod-clips` com `--dedup-stream-id <stream_id>`.
7. Colhe subprocessos terminados, atualiza status em `vigia_streams`.

Estado persistente = `vigia_streams` no Supabase. O vigia é **stateless entre
restarts**: ao subir, relê `vigia_streams` e retoma (jobs `running` órfãos viram
`failed` com motivo `orphaned_restart` e o VOD-depois cobre o buraco).

### Mudanças no código existente (mínimas, todas opt-in)
- `main.py`: novo `--modo vigia` (não exige `source`); nova flag opcional
  `--dedup-stream-id` no vod-clips (sem a flag, comportamento idêntico ao atual).
- `docker-entrypoint.sh`: aceitar `BOTLIVE_MODO=vigia` sem `BOTLIVE_SOURCE`.
- Nada mais. `live_watcher`, `post_live_processor`, `publisher`, `yt_publisher`
  não mudam (o dedup filtra ENTRE a etapa 1 e a etapa 2 do vod-clips, ver §3).

### Deploy
Mesmo container/imagem, segundo serviço EasyPanel (`botlive-vigia`) com
`BOTLIVE_MODO=vigia` — o serviço atual `botlive-app` continua existindo pros
disparos manuais. O vigia é serviço contínuo: restart policy do swarm passa a ser
desejável (hoje evitamos loop parando o serviço; o vigia é idempotente via
`vigia_streams`, então restart é seguro).

## 2. Twitch Helix API

### O que o Glauber precisa cadastrar (uma vez, grátis)
1. https://dev.twitch.tv/console → "Register Your Application".
2. Nome: qualquer (ex. `botlive-vigia`); OAuth Redirect URL: `http://localhost`
   (não será usada — client credentials não tem redirect); Category: Application
   Integration; Client Type: **Confidential**.
3. Copiar **Client ID** e gerar **Client Secret**.
4. Envs novas: `TWITCH_CLIENT_ID` e `TWITCH_CLIENT_SECRET` (EasyPanel + .env local).
   NÃO confundir com `TWITCH_OAUTH_TOKEN` existente (só chat IRC; continua igual).

### Fluxo de token (client credentials — sem usuário)
- `POST https://id.twitch.tv/oauth2/token` com client_id, client_secret,
  grant_type=client_credentials → app access token (validade ~60 dias).
- Módulo novo `twitch_api.py` guarda o token em memória + disco
  (`.tokens/twitch/app_token.json`), renova quando expirar ou em 401.

### Endpoints usados (todos GET, header Client-Id + Bearer)
| Endpoint | Uso | Nota |
|---|---|---|
| `helix/games?name=Grand Theft Auto V` | resolver game_id 1x (GTA V = 32982; config permite trocar pra GTA VI) | cachear |
| `helix/streams?game_id=X&first=100&language=pt` | descoberta aberta; **já vem ordenado por viewer_count desc** | paginação por cursor se precisar |
| `helix/streams?user_login=a&user_login=b...` | status dos canais manuais (até 100 por request) | 1 request cobre a lista toda |
| `helix/videos?user_id=X&type=archive&first=5` | achar o VOD pós-live | payload traz `stream_id` → match exato com a live vigiada |

Campos que importam do Get Streams: `id` (**stream_id**, único por transmissão),
`user_id`, `user_login`, `started_at`, `viewer_count`, `title`, `game_id`, `tags`.

### LIMITAÇÃO Brasil × Portugal na descoberta (14/07/2026)
O foco do canal é público **brasileiro**, mas `language="pt"` na Helix junta
Brasil e Portugal: a Twitch tem **um único** broadcast language ("Português") e
**não expõe país/região** do canal (removido há anos por privacidade). Não há
filtro 100% técnico possível. O único sinal disponível são as `tags` freeform,
inconsistentes — a maioria das lives só traz `"Português"` (ambígua, e
majoritariamente BR porque a cena BR é muito maior que a PT).
Mitigação implementada (`watcher.parece_portugal`, só na **descoberta**; lista
manual intocada): **denylist de alta confiança** enviesada para PRECISÃO —
exclui só com sinal forte de Portugal (nome de servidor RP PT como `PortugáliaRP`
/`AtlanticRP` no título ou tags, ou login terminando em `_pt`) e **nunca** quando
há marcador BR explícito (`Brasil`/`Br`/`PTBR`). PT que escapar vira rascunho que
o Glauber não aprova (a revisão manual é a rede de segurança final). Ajustar as
listas `PT_SERVER_MARKERS`/`PT_REGION_TAGS`/`BR_TAGS` no topo do `watcher.py`.

### Rate limit
800 pontos/min por client-id (1 request ≈ 1 ponto). Nosso uso: 2–4 requests por
ciclo de 60s ≈ 4 pontos/min. Margem de 200x. Ainda assim: respeitar header
`Ratelimit-Remaining` e fazer backoff exponencial em 429/5xx.

## 3. Dedup live × VOD (o desenho crítico)

### Chave de identidade: stream_id
O `stream_id` do Get Streams é o MESMO que aparece no campo `stream_id` do VOD
(Get Videos type=archive). É o elo perfeito entre "o que cortei ao vivo" e "o VOD
que vou reprocessar". Toda entrada de corte do vigia carrega stream_id.

### O problema real: alinhar as duas linhas do tempo
- Corte ao vivo: timestamps relativos ao INÍCIO DA CAPTURA (Etapa C, offset de bloco).
- Corte de VOD: timestamps relativos ao INÍCIO DA TRANSMISSÃO.
- Conversão: `ts_vod ≈ ts_live + (capture_start_utc - stream_started_at)`.
  - `stream_started_at` vem do Helix no momento da detecção;
  - `capture_start_utc` o vigia grava no instante em que o subprocesso live sobe
    (+ ajuste fino: o primeiro bloco da Etapa C nasce na borda do HLS, erro típico
    de ±5–15s; o manifesto da Etapa C tem `wall_open_utc` por bloco — se disponível,
    usar o do bloco 0 como âncora melhora a precisão).

### Índice de cortes: tabela `vigia_clip_index`
Cada corte concluído (pelos jobs do vigia, nos dois modos) grava:
`stream_id, mode (live|vod), ts_vod_estimated, clip_start_vod, clip_end_vod,
session_id, corte_ref, created_at`.
Quem grava é o VIGIA (observando o resultado do subprocesso — fila_local.jsonl /
publish.json da sessão), não o pipeline — mais um motivo de zero mudança no core.

### Regra de dedup (aplicada no vod-clips, entre etapa 1 e etapa 2)
Com `--dedup-stream-id <id>`, depois do scan salvar timestamps e ANTES do render:
1. Busca no índice os cortes existentes do stream_id (qualquer mode).
2. Um candidato do scan é DUPLICADO se o intervalo dele
   `[pico - clip/2, pico + clip/2]` sobrepõe o intervalo de um corte existente
   expandido por `dedup_window_seconds` (default 60s).
   - 60s = tolerância p/ erro de alinhamento (±15s) + o mesmo evento gerar picos
     ligeiramente diferentes nas duas análises (±20s) + folga.
3. Duplicado → não renderiza (loga `[dedup] pulado t=... colide com corte live t=...`).
   Não-duplicado → segue pro render normal (é o "complemento" que o live perdeu).
4. Sem `--dedup-stream-id` (todos os fluxos atuais): NADA disso executa.

### Casos de borda decididos
- Live com modo live DESLIGADO → índice vazio → VOD processa tudo (correto).
- Streamer reconecta (novo stream_id) → ciclos independentes; VODs separados; ok.
- VOD sub-only/desligado/apagado → Get Videos não acha em N tentativas
  (`vod_max_attempts`, default 6 × 10min) → `vod_job_status=vod_unavailable`. Fim.
- Live caiu no meio da captura → captura morre, vigia marca ended; VOD-depois pega
  o resto. Dedup protege o trecho já cortado.
- Duas instâncias do vigia por engano → INSERT unique(stream_id) em `vigia_streams`
  falha na segunda → ela ignora o stream. Sem corrida.

## 4. Config no Supabase (o contrato do dashboard futuro)

### `vigia_config` — linha única (id=1), colunas tipadas (dashboard = UPDATE simples)
| Campo | Tipo | Default | Controla |
|---|---|---|---|
| enabled | bool | false | master switch do vigia inteiro |
| manual_channels_enabled | bool | true | usar lista `vigia_channels` |
| discovery_enabled | bool | false | descoberta aberta por categoria |
| live_mode_enabled | bool | false | disparar live-clips ao detectar live |
| vod_mode_enabled | bool | true | reprocessar VOD pós-live |
| discovery_game | text | 'Grand Theft Auto V' | categoria vigiada |
| discovery_language | text | 'pt' | filtro de idioma no Get Streams |
| discovery_min_viewers | int | 100 | corte de qualidade |
| discovery_max_channels | int | 3 | quantos canais descobertos vigiar ao mesmo tempo |
| poll_interval_seconds | int | 60 | frequência do ciclo |
| max_concurrent_captures | int | 2 | capturas live simultâneas (ffmpeg -c copy, leve) |
| max_concurrent_renders | int | 1 | jobs vod-clips/render simultâneos (pesado) |
| vod_delay_minutes | int | 15 | espera pós-live antes de buscar VOD |
| vod_max_attempts | int | 6 | tentativas de achar o VOD |
| dedup_window_seconds | int | 60 | tolerância do dedup (§3) |
| max_cortes_live / max_cortes_vod | int | 3 / 3 | passa pro --max-cortes de cada modo |
| clip_duration_seconds | int | 45 | passa pro --clip-duration |
| post_youtube_enabled | bool | false | liga --post-youtube nos jobs do vigia |
| post_visibilidade | text | 'unlisted' | visibilidade dos posts |
| max_posts_per_day | int | 4 | teto diário de uploads (quota YouTube, ver §6) |
| updated_at | timestamptz | now() | dashboard escreve; vigia loga mudanças |

Leitura: a cada ciclo, com cache local `vigia_config_cache.json` (última config
válida) — Supabase fora do ar não para o vigia. Escrita: só o dashboard.

### `vigia_channels` — lista manual (dashboard: CRUD simples)
`id, login text unique, enabled bool, priority int, added_by text
('manual'|'discovery'), last_seen_live timestamptz, notes text`.
Config opcional futura: descoberta "promove" canal bom pra lista com
added_by='discovery' (fica auditável e desligável por canal).

### `vigia_streams` — ledger de execução (dashboard: leitura/monitor)
`id, stream_id text unique, channel_login, started_at, detected_at,
capture_start_utc, ended_at, live_job_status, vod_job_status, vod_url,
error_message, updated_at`.
Status live: `disabled|skipped_no_slot|running|done|failed`.
Status vod: `pending|waiting_vod|running|done|failed|vod_unavailable|deduped_all`.

### `vigia_clip_index` — dedup (§3)
`id, stream_id, mode, ts_vod_estimated int, clip_start_vod int, clip_end_vod int,
session_id, corte_ref, created_at`. Index em (stream_id).

RLS: robô usa service key (bypassa RLS). Pro dashboard futuro, criar policies de
leitura/escrita autenticada quando ele existir — fora do escopo agora.

## 5. Sub-etapas testáveis (ordem de risco crescente)

| # | Etapa | Entrega testável | Risco |
|---|---|---|---|
| V1 | `twitch_api.py` (token + get_streams por game e por login + get_videos) | CLI: `python twitch_api.py top-gta` lista top canais c/ viewers; `status <canal>`; `vods <canal>` mostra stream_id | BAIXO |
| V2 | Tabelas Supabase + leitor de config c/ cache | mudar flag no Supabase Studio e ver o vigia (dry) refletir no ciclo seguinte | BAIXO |
| V3 | Vigia DRY-RUN (`--vigia-dry-run`): loop completo, decide e LOGA o que faria, grava `vigia_streams`, não dispara nada | rodar 1h contra lives reais e auditar decisões no log/tabela | BAIXO/MÉDIO |
| V4 | Modo VOD-depois real (sem dedup): fim de live → achar VOD → subprocesso vod-clips | 1 canal manual, live curta de teste; cortes saem sozinhos pós-live | MÉDIO |
| V5 | Modo live real: subprocesso live-clips + âncora capture_start_utc + concorrência | live de teste; preview clips saindo ao vivo; âncora gravada | MÉDIO/ALTO |

> **V5 — RESULTADO DO TESTE REAL (12/07/2026, VPS, live cirilobang):** a camada do
> VIGIA passou inteira — despacho idempotente (disabled/skipped_no_slot despacham;
> running/done/failed nunca), âncora capture_start_utc gravada no ledger, colheita
> ok, varredura de órfãos no boot e terminate pós-fim implementados; job live não
> tem NENHUMA flag de post por construção. O que FALHOU foi a Etapa C contra LIVE
> da Twitch (não é código do vigia): bloco 0 fechou com 26s, depois 210s sem
> blocos (consumidor desistiu) e o bloco 1 saiu com dur=21387s — timestamps
> quebrados, quase certo por DESCONTINUIDADE do HLS ao vivo da Twitch (ads
> preroll/midroll com SCTE; o segmentador `-c copy` do ffmpeg não fecha segmento).
> A Etapa C foi validada em live do YouTube e simulação local; VOD da Twitch
> funciona (CloudFront sem descontinuidade). **Ticket pro Opus:** endurecer
> live_capture p/ Twitch live — candidatos: streamlink `--twitch-disable-ads`
> como resolvedor alternativo, `-fflags +genpts`/tratamento de descontinuidade no
> ffmpeg, ou re-encode leve dos blocos ao invés de `-c copy` só no caso Twitch
> live. Reproduzir: `python main.py https://twitch.tv/<canal_ao_vivo> --modo
> live-clips --session-id teste --content-filter gta`.

> **BUG DA ETAPA C EM TWITCH LIVE — RESOLVIDO (12/07/2026, sessão Fable, local):**
> Reproduzido 3× em live real (chapo_dizona, GTA PT): bloco 0 = 26.3s (era o preroll
> — o playlist trazia `twitch-stitched-ad` de 30.2s + `#EXT-X-DISCONTINUITY`),
> stall >180s e o bloco 1 saindo com dur=17972–18707s. Causa confirmada: o ad roda
> em linha de tempo própria (PTS ≈ 0) e o conteúdo carrega o PTS nativo da stream;
> na emenda ad→conteúdo o PTS salta a idade da live (~5h ≈ 18000s) e o segmentador
> `-c copy` trava e depois cospe o bloco com essa duração. Agravante: ad e conteúdo
> têm codec params diferentes (1080p30 Main 3Mbps vs 1080p60 High 6Mbps) no mesmo
> bitstream copiado.
>
> Candidatos testados na ordem combinada: **(1) `-fflags +genpts` REPROVADO** —
> falha idêntica à baseline (genpts gera PTS *faltantes*, não conserta salto).
> **(2) streamlink APROVADO** — 2 corridas limpas (6/6 blocos de 30.0s cravados)
> intercaladas com 3 baselines quebradas na mesma live. **(3) re-encode: não foi
> necessário.** Descoberta importante: o streamlink 8.x removeu
> `--twitch-disable-ads` porque filtrar ads virou comportamento padrão do plugin;
> a filtragem acontece no leitor HLS interno, então `--stream-url` NÃO serve — a
> integração é por pipe: `streamlink --stdout <url> 720p,720p60,best | ffmpeg -i
> pipe:0 -c copy -f segment ...`.
>
> Implementação (`live_capture.py`): pipe streamlink SOMENTE para live da Twitch
> (`_is_twitch_live_url` exclui `/videos/`); YouTube live, arquivo local e VOD
> seguem no caminho antigo intacto. Se o streamlink não estiver instalado, cai no
> HLS direto com aviso. Regressão: YouTube live (Al Jazeera) 3/3 blocos, simulação
> local 3/3, unitários da Etapa C 14/14, e vod-clips nem passa por live_capture.
> Nova dependência: `streamlink` no requirements.txt (Docker instala no build).
> Limitação conhecida: durante midroll o conteúdo NÃO existe pro viewer; um bloco
> que atravessa midroll pode inflar a duração pelo tamanho do intervalo (sem
> conserto possível no cliente). Pendências: validar streamlink de IP de
> datacenter na VPS (yt-dlp foi validado 10/07; mesmos endpoints usher/gql) e
> re-rodar o teste V5 ponta a ponta na VPS. Env nova opcional
> `BOTLIVE_TLS_NO_VERIFY=1` (ytdlp_config) só pra dev local com antivírus fazendo
> MITM de TLS (Python 3.13+ liga VERIFY_X509_STRICT e rejeita a CA do AVG);
> NUNCA usar na VPS.
| V6 | Dedup completo: `vigia_clip_index` + `--dedup-stream-id` no vod-clips | mesma live processada nos 2 modos; VOD NÃO repete cortes do live e complementa | ALTO |
| V7 | Endurecimento: auto-post c/ teto diário, retenção de disco, restart-safe, alertas de erro no `vigia_streams` | derrubar Supabase/Helix/container no meio e ver sobreviver | ALTO |

Partes que mais exigem raciocínio (priorizadas nesta sessão, já resolvidas no plano):
a arquitetura por subprocessos (§1), o elo stream_id live↔VOD e a conversão de
linhas do tempo (§3), o contrato de config (§4). As etapas V1–V3 são mecânicas;
V6 é a única com incerteza real de precisão (validar tolerância na prática).

## 6. Riscos e mitigação

1. **Quota do YouTube (o maior risco real, não a Twitch)**: 10.000 units/dia;
   upload = 1.600 units → ~6 uploads/dia. Hoje cada corte = 2 uploads (HD+vertical)
   → 3 cortes/dia ESGOTAM a quota. Vigia multi-canal estoura fácil. Mitigações:
   `max_posts_per_day` na config (teto duro), opção de postar SÓ o vertical
   (1 upload/corte), e pedir aumento de quota no Google Cloud (form de auditoria,
   leva semanas — iniciar cedo). Cortes acima do teto ficam renderizados no disco
   com publish.json, postáveis depois.
2. **Rate limit Twitch**: irrelevante no nosso volume (§2), mas tratar 429/5xx com
   backoff e nunca deixar o loop morrer por erro de API (ciclo falho = pula ciclo).
3. **Custo de rodar contínuo na VPS (4 vCPU)**: vigia idle ≈ 0; captura live
   (`-c copy`) é leve (rede+disco); o caro é render/whisper (~2,5min/corte, satura
   1-2 cores). `max_concurrent_renders=1` serializa; capturas ≤2. Pior cena:
   captura de 2 lives + 1 render simultâneos = ok em 4 vCPU. Disco: retenção da
   Etapa C já limpa blocos; cache de VOD scan pode crescer → limpeza pós-job no V7.
4. **Canal cai no meio / reconexão**: captura morre → ended_at → fluxo VOD cobre;
   novo stream_id = novo ciclo. Sem estado perdido.
5. **Helix fora do ar**: backoff, capturas em andamento continuam (não dependem da
   API), descoberta pausa, config em cache segue valendo.
6. **Supabase fora do ar**: config do cache local; `vigia_streams` sem escrita →
   modo degradado: NÃO iniciar streams novos (sem lock/idempotência não é seguro),
   só concluir os em andamento; fila_local.jsonl já é o fallback de registro.
7. **Restart do container**: idempotência via `vigia_streams` (jobs órfãos →
   failed, VOD-depois compensa). Restart policy pode ficar LIGADA pro vigia —
   diferente do serviço one-shot atual.
8. **GTA VI / mudança de categoria**: `discovery_game` é config; game_id resolvido
   por nome a cada boot.
9. **VOD indisponível (sub-only/desligado)**: detectado e marcado; canal continua
   elegível pro modo live.

## Fora de escopo (explícito)
- Dashboard em si (só o contrato de dados acima).
- Plugins Instagram/TikTok, compliance YouTube public (pendências antigas, separadas).
