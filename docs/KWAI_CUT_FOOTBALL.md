# Kwai CUT Futebol

## Objetivo e segurança

O perfil `kwai_cut_futebol` acrescenta ao BotLive um fluxo de futebol real que termina em um pacote `prepare_only`. O BotLive legado não foi substituído: live, VOD, Vigia, downloader, filtros, YouTube, Instagram e o perfil `default` continuam nos mesmos caminhos.

O fluxo não automatiza login, CAPTCHA nem postagem. A API oficial só poderá ser ligada depois de autorização confirmada, com `KWAI_API_ENABLED=1`. Fontes públicas não são automaticamente consideradas permitidas: somente `authorized`, `licensed`, `campaign_allowed` e `owned` avançam sem revisão.

## Arquitetura

`FootballSource`/descoberta → `source_downloader` existente → filtro de futebol existente → `RealFootballClassifier` → `ContentEvent` → ViralScore/prioridade → variantes CUT → renderizadores atuais → gates de `MediaAsset` → fila persistente → `KwaiPublisher` em `prepare_only`.

A descoberta apenas entrega referências ao downloader existente. A migration não cria downloader, live watcher ou scanner paralelos.

## Perfil, regras e metas

O preset nasce inativo, com layout 9:16, alvo 1080×1920, H.264/AAC, meta mínima 30, alvo inicial 30 e teto 100. Os 15–60 segundos são provisórios no perfil e `duration_rule_confirmed=false`; não são uma alegação de regra oficial.

O planner ordena evento, confiança, contexto, qualidade e novidade. Cada evento pode gerar ação direta, jogada completa, reação, contexto e análise. As assinaturas usam mudança temporal/gancho real; mudanças cosméticas não criam variante. Se faltar material aprovado, o déficit é registrado.

As regras da campanha ficam em `kwai_cut_activities`: nome, período, duração, hashtags, termos, categoria, quantidade, legenda, capa, regras adicionais e confirmação. Uma atividade ativa é obrigatória para preparar o pacote.

## Futebol real

`RealFootballClassifier` retorna `real_match`, `real_highlights`, `real_news`, `real_interview`, `real_reaction`, `real_training`, `video_game`, `unrelated` ou `uncertain`. Termos negativos são armazenados no perfil e editáveis no dashboard. `video_game` e `uncertain` não seguem automaticamente.

## Prepare-only

O pacote é criado em:

`<BOTLIVE_OUTPUT_ROOT>/kwai_cut_futebol/YYYY-MM-DD/<variant_id>/`

Ele contém `video.mp4`, `cover.jpg` e `metadata.json`. O job persistente mantém chave idempotente. Nenhum upload é realizado.

## Dashboard e CLI

A rota `/kwai-cut` possui Visão geral, Fontes, Eventos, Vídeos, Regras, Fila, Conta, Métricas e Erros. Cards e listas consultam Supabase; na ausência dele a tela mostra erro/zero, sem inventar dados e sem expor secrets.

```text
python kwai_cut_cli.py status
python kwai_cut_cli.py process --profile kwai_cut_futebol --target 30 --simulate
python kwai_cut_cli.py process --profile kwai_cut_futebol --target 100 --simulate
python publication_worker.py --once --dry-run
```

## Feature flags

- `KWAI_CUT_DASHBOARD_ENABLED`
- `KWAI_CUT_FOOTBALL_ENABLED`
- `FOOTBALL_SOURCE_DISCOVERY_ENABLED`
- `FOOTBALL_REAL_CLASSIFIER_ENABLED`
- flags existentes `MULTI_PROFILE_ENABLED`, `PUBLICATION_QUEUE_ENABLED`, `KWAI_ENABLED`
- mantenha `KWAI_API_ENABLED=0` até autorização oficial

## Migration e rollback

Aplicar, depois das migrations de 25/07:

`supabase/migrations/20260730_kwai_cut_football.sql`

Ela é aditiva e não deve ser aplicada automaticamente na VPS. Rollback operacional: desligar as quatro flags novas e desativar o perfil. As tabelas permanecem para preservar dados; não há `DROP`, `TRUNCATE` nem remoção de coluna.

## Pendências externas

Regras oficiais de campanha/duração precisam ser confirmadas nos materiais da agência. OAuth/API e conta Kwai dependem de autorização oficial. Publicação real e aplicação da migration na VPS/Supabase ficam deliberadamente pendentes.
