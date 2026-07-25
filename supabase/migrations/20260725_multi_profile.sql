-- BotLive Fase 2: configuração multi-perfil.
-- Migração estritamente aditiva: vigia_config e todas as tabelas legadas
-- continuam intactas e seguem sendo a fonte do Vigia nesta fase.

create table if not exists public.profiles (
    profile_id text primary key,
    name text not null,
    description text,
    niche text,
    editorial_strategy text not null default 'default',
    language text not null default 'pt-BR',
    enabled boolean not null default false,
    settings jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint profiles_profile_id_format
        check (profile_id ~ '^[a-z0-9][a-z0-9_-]{1,62}$')
);

create table if not exists public.profile_sources (
    id uuid primary key default gen_random_uuid(),
    profile_id text not null references public.profiles(profile_id) on delete cascade,
    source_type text not null,
    source_ref text not null,
    enabled boolean not null default true,
    settings jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (profile_id, source_type, source_ref)
);

create table if not exists public.platform_accounts (
    id uuid primary key default gen_random_uuid(),
    platform text not null,
    account_key text not null,
    display_name text,
    status text not null default 'not_configured'
        check (status in ('not_configured', 'pending', 'connected', 'disconnected', 'error')),
    secret_ref text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (platform, account_key)
);

comment on column public.platform_accounts.secret_ref is
    'Referência opaca para env/secret manager; nunca armazenar token, senha ou client secret.';

create table if not exists public.profile_destinations (
    id uuid primary key default gen_random_uuid(),
    profile_id text not null references public.profiles(profile_id) on delete cascade,
    platform text not null,
    account_id uuid references public.platform_accounts(id) on delete restrict,
    enabled boolean not null default false,
    publication_mode text not null default 'disabled'
        check (publication_mode in ('disabled', 'manual', 'approval', 'automatic')),
    max_posts_per_day integer check (max_posts_per_day is null or max_posts_per_day >= 0),
    schedule jsonb not null default '{}'::jsonb,
    settings jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (profile_id, platform, account_id)
);

create table if not exists public.profile_render_settings (
    profile_id text primary key references public.profiles(profile_id) on delete cascade,
    aspect_ratio text not null default '9:16'
        check (aspect_ratio in ('original', '9:16')),
    layout text not null default 'vertical-fit'
        check (layout in ('original', 'vertical-fit', 'vertical-crop')),
    min_duration_seconds integer not null default 5 check (min_duration_seconds >= 0),
    max_duration_seconds integer not null default 60 check (max_duration_seconds > 0),
    target_height integer check (target_height is null or target_height > 0),
    captions_enabled boolean not null default true,
    headline_enabled boolean not null default true,
    brand text,
    cta text,
    settings jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now(),
    constraint profile_render_duration_range
        check (min_duration_seconds <= max_duration_seconds)
);

create index if not exists profile_sources_profile_idx
    on public.profile_sources(profile_id);
create index if not exists profile_destinations_profile_idx
    on public.profile_destinations(profile_id);
create index if not exists profile_destinations_account_idx
    on public.profile_destinations(account_id);

-- Espelha o singleton atual como perfil default. Reexecução é segura e não
-- sobrescreve edições feitas na nova tela.
insert into public.profiles (
    profile_id, name, description, niche, editorial_strategy, language, enabled, settings
)
select
    'default',
    'Default',
    'Perfil de compatibilidade com vigia_config',
    nullif(content_filter, 'none'),
    'default',
    coalesce(nullif(discovery_language, ''), 'pt'),
    enabled,
    jsonb_build_object('legacy_config_id', id)
from public.vigia_config
where id = 1
on conflict (profile_id) do nothing;

insert into public.profile_sources (profile_id, source_type, source_ref, enabled)
select 'default', 'legacy_vigia_channels', 'vigia_channels', manual_channels_enabled
from public.vigia_config
where id = 1
on conflict (profile_id, source_type, source_ref) do nothing;

insert into public.platform_accounts (platform, account_key, display_name, status)
values
    ('youtube', 'principal', 'Principal', 'not_configured'),
    ('instagram', 'principal', 'Principal', 'not_configured')
on conflict (platform, account_key) do nothing;

insert into public.profile_destinations (
    profile_id, platform, account_id, enabled, publication_mode, max_posts_per_day, settings
)
select
    'default',
    'youtube',
    account.id,
    config.post_youtube_enabled,
    case when config.post_youtube_enabled then 'automatic' else 'disabled' end,
    config.max_posts_per_day,
    jsonb_build_object('visibility', config.post_visibilidade)
from public.vigia_config config
join public.platform_accounts account
  on account.platform = 'youtube' and account.account_key = 'principal'
where config.id = 1
on conflict (profile_id, platform, account_id) do nothing;

insert into public.profile_destinations (
    profile_id, platform, account_id, enabled, publication_mode
)
select
    'default',
    'instagram',
    account.id,
    config.post_instagram_enabled,
    case when config.post_instagram_enabled then 'approval' else 'disabled' end
from public.vigia_config config
join public.platform_accounts account
  on account.platform = 'instagram' and account.account_key = 'principal'
where config.id = 1
on conflict (profile_id, platform, account_id) do nothing;

insert into public.profile_render_settings (
    profile_id, aspect_ratio, layout, min_duration_seconds, max_duration_seconds,
    target_height, captions_enabled, headline_enabled, brand
)
select
    'default',
    '9:16',
    'vertical-fit',
    5,
    greatest(5, clip_duration_seconds),
    target_height,
    true,
    true,
    credito_canal
from public.vigia_config
where id = 1
on conflict (profile_id) do nothing;

-- Mantém updated_at consistente sem acoplar ao trigger legado.
create or replace function public.set_multi_profile_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at
before update on public.profiles
for each row execute function public.set_multi_profile_updated_at();

drop trigger if exists profile_sources_set_updated_at on public.profile_sources;
create trigger profile_sources_set_updated_at
before update on public.profile_sources
for each row execute function public.set_multi_profile_updated_at();

drop trigger if exists platform_accounts_set_updated_at on public.platform_accounts;
create trigger platform_accounts_set_updated_at
before update on public.platform_accounts
for each row execute function public.set_multi_profile_updated_at();

drop trigger if exists profile_destinations_set_updated_at on public.profile_destinations;
create trigger profile_destinations_set_updated_at
before update on public.profile_destinations
for each row execute function public.set_multi_profile_updated_at();

drop trigger if exists profile_render_settings_set_updated_at on public.profile_render_settings;
create trigger profile_render_settings_set_updated_at
before update on public.profile_render_settings
for each row execute function public.set_multi_profile_updated_at();

-- RLS não é ativado automaticamente porque o dashboard legado usa a anon key
-- sem sessão Supabase Auth. Ativá-lo aqui quebraria a compatibilidade atual.
-- Antes de expor o dashboard publicamente, migrar AuthWrapper para Supabase
-- Auth e então habilitar políticas por usuário/organização.
