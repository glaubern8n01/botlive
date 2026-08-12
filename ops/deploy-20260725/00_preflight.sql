-- 00_preflight.sql — SOMENTE LEITURA. Rode e confira ANTES de aplicar qualquer migration.
-- Confirma que este é o Supabase REAL do BotLive e que nada foi aplicado parcialmente.

-- 1) A tabela legada exigida existe? (as migrations espelham o perfil default dela)
select to_regclass('public.vigia_config') as vigia_config_existe;

-- 2) A linha singleton id=1 existe?
select count(*) as vigia_config_id1 from public.vigia_config where id = 1;

-- 3) As 11 colunas de vigia_config exigidas pela migration multi_profile existem?
select column_name
from information_schema.columns
where table_schema = 'public' and table_name = 'vigia_config'
  and column_name in (
    'content_filter','discovery_language','enabled','manual_channels_enabled',
    'post_youtube_enabled','max_posts_per_day','post_visibilidade',
    'post_instagram_enabled','clip_duration_seconds','target_height','credito_canal'
  )
order by column_name;

-- 4) Alguma tabela NOVA já existe? (detecta aplicação parcial anterior — idealmente vazio)
select table_name
from information_schema.tables
where table_schema = 'public'
  and table_name in (
    'profiles','profile_sources','platform_accounts','profile_destinations',
    'profile_render_settings','content_events','editorial_variants','media_assets',
    'publication_jobs','publication_attempts'
  )
order by table_name;

-- 5) Views/RPCs novas já existem? (idealmente vazio)
select routine_name from information_schema.routines
where routine_schema = 'public'
  and routine_name in ('claim_publication_job','cancel_publication_job',
    'retry_publication_job','set_multi_profile_updated_at')
order by routine_name;

select table_name from information_schema.views
where table_schema = 'public'
  and table_name in ('publication_metrics','platform_accounts_safe')
order by table_name;
