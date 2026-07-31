-- TikTok Standard para GTA: aditiva, segura e separada do futuro TikTok Shop.
-- Não armazena access_token, refresh_token ou client_secret.

alter table public.profile_destinations
    drop constraint if exists profile_destinations_publication_mode_check;
alter table public.profile_destinations
    add constraint profile_destinations_publication_mode_check
    check (publication_mode in (
        'disabled', 'prepare_only', 'manual', 'automatic', 'upload_draft', 'direct_post'
    ));

create table if not exists public.tiktok_standard_connections (
    connection_id uuid primary key default gen_random_uuid(),
    account_id uuid not null unique references public.platform_accounts(id) on delete restrict,
    open_id text,
    nickname text,
    secret_ref text not null,
    granted_scopes text[] not null default '{}',
    token_expires_at timestamptz,
    refresh_expires_at timestamptz,
    review_status text not null default 'not_configured'
        check (review_status in ('not_configured','draft','pending','approved','denied')),
    connection_status text not null default 'disconnected'
        check (connection_status in ('disconnected','connected','expired','revoked','error')),
    creator_info jsonb not null default '{}'::jsonb,
    connected_at timestamptz,
    disconnected_at timestamptz,
    updated_at timestamptz not null default now(),
    constraint tiktok_standard_secret_namespace
        check (secret_ref like 'tiktok-encrypted:%')
);

create table if not exists public.tiktok_standard_audit (
    audit_id bigint generated always as identity primary key,
    account_id uuid references public.platform_accounts(id) on delete restrict,
    job_id uuid references public.publication_jobs(job_id) on delete set null,
    action text not null,
    result text not null,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists public.tiktok_standard_metrics (
    metric_id bigint generated always as identity primary key,
    account_id uuid not null references public.platform_accounts(id) on delete restrict,
    job_id uuid references public.publication_jobs(job_id) on delete cascade,
    publish_id text,
    metric_name text not null,
    metric_value numeric,
    measured_at timestamptz not null default now()
);

comment on table public.tiktok_standard_connections is
    'Metadados não secretos; tokens ficam somente no armazenamento criptografado do backend.';

insert into public.platform_accounts(platform, account_key, display_name, status, secret_ref, metadata)
values (
    'tiktok_standard', 'gta6brasilcortes', 'GTA6 Brasil Cortes',
    'not_configured', 'tiktok-encrypted:gta6brasilcortes',
    '{"destination_key":"tiktok_standard_gta6","shop":false}'::jsonb
)
on conflict (platform, account_key) do update
set display_name = excluded.display_name,
    metadata = public.platform_accounts.metadata || excluded.metadata;

insert into public.profile_destinations(
    profile_id, platform, account_id, enabled, publication_mode,
    max_pending_jobs, max_attempts, settings
)
select
    profile.profile_id, 'tiktok_standard', account.id, true, 'prepare_only',
    3, 3,
    '{"destination_key":"tiktok_standard_gta6","content_profile":"gta6_cortes","mode":"prepare_only","rights_status":"review_required"}'::jsonb
from public.profiles profile
join public.platform_accounts account
  on account.platform='tiktok_standard' and account.account_key='gta6brasilcortes'
where profile.profile_id in ('gta6_cortes', 'gta6')
order by case when profile.profile_id='gta6_cortes' then 0 else 1 end
limit 1
on conflict (profile_id, platform, account_id) do update
set settings = public.profile_destinations.settings || excluded.settings;

create or replace view public.tiktok_standard_connections_safe as
select
    connection_id, account_id, nickname, granted_scopes, token_expires_at,
    refresh_expires_at, review_status, connection_status, creator_info,
    connected_at, disconnected_at, updated_at,
    (secret_ref is not null) as secret_configured
from public.tiktok_standard_connections;

-- Não há conta, destino, token, job ou métrica tiktok_shop nesta migration.
