-- 20_validate.sql — SOMENTE LEITURA. Rode DEPOIS das 4 migrations.

-- Tabelas novas (esperado: 10 linhas)
select table_name from information_schema.tables
where table_schema = 'public'
  and table_name in (
    'profiles','profile_sources','platform_accounts','profile_destinations',
    'profile_render_settings','content_events','editorial_variants','media_assets',
    'publication_jobs','publication_attempts')
order by table_name;

-- Colunas de política adicionadas por destination_policies (esperado: 6)
select column_name from information_schema.columns
where table_schema = 'public' and table_name = 'profile_destinations'
  and column_name in ('minimum_interval_seconds','allowed_hours','timezone',
    'max_pending_jobs','max_attempts','publisher_options')
order by column_name;

-- Views (esperado: 2)
select table_name from information_schema.views
where table_schema = 'public'
  and table_name in ('publication_metrics','platform_accounts_safe')
order by table_name;

-- RPCs (esperado: 4)
select routine_name from information_schema.routines
where routine_schema = 'public'
  and routine_name in ('claim_publication_job','cancel_publication_job',
    'retry_publication_job','set_multi_profile_updated_at')
order by routine_name;

-- Triggers de updated_at (esperado: 6 tabelas)
select event_object_table, trigger_name
from information_schema.triggers
where trigger_schema = 'public' and trigger_name like '%set_updated_at%'
order by event_object_table;

-- Constraints-chave presentes
select conname from pg_constraint
where conname in ('profiles_profile_id_format','profile_render_duration_range')
order by conname;

-- Perfil default espelhado do legado
select profile_id, name, enabled from public.profiles where profile_id = 'default';

-- Contas seed (youtube/instagram principal, status not_configured)
select platform, account_key, status from public.platform_accounts order by platform, account_key;

-- SEGURANÇA: a view segura NÃO pode expor secret_ref (esperado: 0 linhas)
select column_name from information_schema.columns
where table_schema = 'public' and table_name = 'platform_accounts_safe'
  and column_name = 'secret_ref';
