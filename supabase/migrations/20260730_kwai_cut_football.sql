-- Kwai CUT Futebol. Migração aditiva; não altera tabelas ou fluxos legados.

create table if not exists public.football_sources (
    source_id uuid primary key default gen_random_uuid(),
    profile_id text not null references public.profiles(profile_id) on delete restrict,
    name text not null,
    source_type text not null check (source_type in (
        'youtube_channel','youtube_playlist','youtube_search','youtube_live',
        'direct_video','local_file','watched_folder','authorized_feed'
    )),
    source_ref text not null,
    usage_status text not null default 'review_required' check (usage_status in (
        'authorized','licensed','campaign_allowed','owned','review_required','blocked'
    )),
    enabled boolean not null default true,
    priority integer not null default 50 check (priority between 0 and 100),
    check_frequency_minutes integer not null default 30 check (check_frequency_minutes > 0),
    allowed_live boolean not null default false,
    allowed_vod boolean not null default true,
    allowed_highlights boolean not null default true,
    allowed_news boolean not null default false,
    max_cuts integer not null default 10 check (max_cuts >= 0),
    last_checked_at timestamptz,
    last_video_ref text,
    status text not null default 'idle',
    last_error text,
    metrics jsonb not null default '{}'::jsonb,
    settings jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(profile_id, source_type, source_ref)
);

create table if not exists public.kwai_cut_activities (
    activity_id uuid primary key default gen_random_uuid(),
    profile_id text not null references public.profiles(profile_id) on delete restrict,
    name text not null,
    starts_at timestamptz,
    ends_at timestamptz,
    min_duration_seconds integer check (min_duration_seconds is null or min_duration_seconds >= 0),
    max_duration_seconds integer check (max_duration_seconds is null or max_duration_seconds > 0),
    required_hashtags text[] not null default '{}',
    required_terms text[] not null default '{}',
    category text,
    minimum_quantity integer check (minimum_quantity is null or minimum_quantity >= 0),
    caption_required boolean not null default true,
    cover_required boolean not null default true,
    additional_rules text,
    confirmation_status text not null default 'unconfirmed'
        check (confirmation_status in ('confirmed','unconfirmed')),
    active boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint kwai_cut_activity_duration check (
        min_duration_seconds is null or max_duration_seconds is null
        or min_duration_seconds <= max_duration_seconds
    )
);

create index if not exists football_sources_profile_idx
    on public.football_sources(profile_id, enabled, priority desc);
create unique index if not exists kwai_cut_one_active_activity_idx
    on public.kwai_cut_activities(profile_id) where active;

insert into public.profiles (
    profile_id,name,description,niche,editorial_strategy,language,enabled,settings
) values (
    'kwai_cut_futebol','Kwai CUT Futebol',
    'Perfil aditivo prepare_only para futebol real','football','cut','pt-BR',false,
    '{"daily_minimum":30,"daily_target":30,"daily_maximum":100,"duration_rule_confirmed":false,"prepare_only":true,"classification_threshold":0.75,"negative_terms":["EA FC","FC 26","FIFA gameplay","eFootball","PES","Football Manager","Ultimate Team","modo carreira","gameplay","simulação","mobile game","videogame"]}'::jsonb
) on conflict(profile_id) do nothing;

insert into public.platform_accounts(platform,account_key,display_name,status,metadata)
values ('kwai','principal','Kwai CUT','not_configured','{"mode":"prepare_only"}'::jsonb)
on conflict(platform,account_key) do nothing;

insert into public.profile_render_settings (
    profile_id,aspect_ratio,layout,min_duration_seconds,max_duration_seconds,
    target_height,captions_enabled,headline_enabled,settings
) values (
    'kwai_cut_futebol','9:16','vertical-fit',15,60,1920,true,true,
    '{"width":1080,"video_codec":"h264","audio_codec":"aac","requires_confirmation":true}'::jsonb
) on conflict(profile_id) do nothing;

insert into public.profile_destinations (
    profile_id,platform,account_id,enabled,publication_mode,max_posts_per_day,settings
)
select 'kwai_cut_futebol','kwai',id,true,'approval',100,'{"mode":"prepare_only"}'::jsonb
from public.platform_accounts where platform='kwai' and account_key='principal'
on conflict(profile_id,platform,account_id) do nothing;

drop trigger if exists football_sources_set_updated_at on public.football_sources;
create trigger football_sources_set_updated_at before update on public.football_sources
for each row execute function public.set_multi_profile_updated_at();
drop trigger if exists kwai_cut_activities_set_updated_at on public.kwai_cut_activities;
create trigger kwai_cut_activities_set_updated_at before update on public.kwai_cut_activities
for each row execute function public.set_multi_profile_updated_at();

create or replace view public.kwai_cut_daily_metrics as
select
    p.profile_id,
    current_date as metric_date,
    coalesce((p.settings->>'daily_minimum')::integer,30) as daily_minimum,
    coalesce((p.settings->>'daily_target')::integer,30) as daily_target,
    count(distinct a.asset_id) filter (where a.created_at >= current_date)::bigint as generated,
    count(distinct a.asset_id) filter (where a.created_at >= current_date and a.validation_status='valid')::bigint as approved,
    count(distinct a.asset_id) filter (where a.created_at >= current_date and a.validation_status='invalid')::bigint as rejected,
    count(distinct j.job_id) filter (where j.created_at >= current_date and j.status in ('pending','validating','retry_wait'))::bigint as queued,
    count(distinct j.job_id) filter (where j.created_at >= current_date and j.status='ready')::bigint as ready,
    count(distinct j.job_id) filter (where j.created_at >= current_date and j.status='published')::bigint as published
from public.profiles p
left join public.media_assets a on a.profile_id=p.profile_id
left join public.publication_jobs j on j.profile_id=p.profile_id
where p.profile_id='kwai_cut_futebol'
group by p.profile_id,p.settings;

-- Rollback seguro: desative o perfil/flags. As tabelas são mantidas para não perder dados.
