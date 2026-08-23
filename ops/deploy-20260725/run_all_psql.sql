-- run_all_psql.sql — aplica as 4 migrations na ordem, em transação única.
-- Uso: psql "$DATABASE_URL" -f ops/deploy-20260725/run_all_psql.sql
-- Executar a partir da RAIZ do repo (caminhos \i são relativos ao cwd do psql).
-- Re-execução é segura: tudo é "if not exists" / "or replace".

\set ON_ERROR_STOP on
begin;

\echo '>> 1/4 multi_profile'
\i supabase/migrations/20260725_multi_profile.sql

\echo '>> 2/4 publication_pipeline'
\i supabase/migrations/20260725_publication_pipeline.sql

\echo '>> 3/4 destination_policies'
\i supabase/migrations/20260725_destination_policies.sql

\echo '>> 4/4 publication_dashboard'
\i supabase/migrations/20260725_publication_dashboard.sql

commit;
\echo '>> OK: 4 migrations aplicadas em transacao unica.'
