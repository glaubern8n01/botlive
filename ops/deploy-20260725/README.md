# Deploy operacional — BotLive multi-profile (2026-07-25)

Branch: `feat/multi-profile-kwai` · HEAD `2037d7e5d8bce9e58afa80f93b4c101614380a34`.

Todas as migrations são **aditivas** e dependem da tabela legada `public.vigia_config`
(linha `id=1`). Aplicar **somente** no Supabase REAL do BotLive — nunca em outra base.

## Ordem de execução

1. **`00_preflight.sql`** — SOMENTE LEITURA. Rode e confira:
   - `vigia_config_existe` deve ser `public.vigia_config` (não nulo);
   - `vigia_config_id1` deve ser `1`;
   - as 11 colunas exigidas devem aparecer;
   - a lista de "tabelas novas já existentes" idealmente vem **vazia** (se vier
     preenchida, houve aplicação parcial anterior — pare e revise antes de seguir).
   Se `vigia_config` não existir ou `id=1` faltar → **base errada ou não semeada. PARE.**

2. **Migrations, nesta ordem** (arquivos canônicos do repo):
   1. `supabase/migrations/20260725_multi_profile.sql`
   2. `supabase/migrations/20260725_publication_pipeline.sql`
   3. `supabase/migrations/20260725_destination_policies.sql`
   4. `supabase/migrations/20260725_publication_dashboard.sql`

   - **SQL Editor do Supabase:** abra cada arquivo e execute um a um, na ordem.
   - **psql:** `psql "$DATABASE_URL" -f ops/deploy-20260725/run_all_psql.sql`
     (roda os 4 em ordem, dentro de transação; re-execução é segura — tudo é
     `if not exists` / `or replace`).

3. **`20_validate.sql`** — confere tabelas (10), colunas de política (6), views (2),
   RPCs (4), triggers, perfil `default` espelhado, contas seed e que a view segura
   **não** expõe `secret_ref`.

4. **`30_seed_test_profiles.sql`** — cria `teste_cut` e `teste_narrastars`
   (com `enabled=false`, inertes). Depois valide o **CRUD pelo dashboard** (`/perfis`).

## Rollback (não destrutivo)

- Migrations são aditivas: **não apague tabelas**. Para desligar tudo, zere as
  feature flags (ver `VPS_RUNBOOK.md`) e o caminho legado volta intacto.
- Reversão de código: `git revert` a partir do HEAD de referência
  `d0fa43331141c347faf5280a27254e88a93d5380`, do commit mais recente para o mais
  antigo. Nunca `reset --hard` em worktree com alterações do usuário.

## Segurança

- `platform_accounts` guarda só `secret_ref` (referência opaca) — nunca token/senha.
- RLS permanece **desligado** de propósito (dashboard legado usa anon key). Não
  expor o dashboard publicamente neste estado. Dívida registrada em `docs/SECRETS.md`.
