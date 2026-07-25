-- BotLive Fases 4-6: eventos, variantes, ativos e fila de publicação.
-- Migração aditiva. Não altera nem remove tabelas legadas.

create table if not exists public.content_events (
    event_id uuid primary key default gen_random_uuid(),
    profile_id text not null references public.profiles(profile_id) on delete restrict,
    source_event_key text not null,
    source_ref text not null,
    timestamp_seconds double precision not null check (timestamp_seconds >= 0),
    event_type text not null default 'highlight',
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (profile_id, source_event_key)
);

create table if not exists public.editorial_variants (
    variant_id uuid primary key default gen_random_uuid(),
    event_id uuid not null references public.content_events(event_id) on delete cascade,
    profile_id text not null references public.profiles(profile_id) on delete restrict,
    strategy text not null,
    variant_signature text not null,
    editorial_metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (profile_id, event_id, variant_signature)
);

create table if not exists public.media_assets (
    asset_id uuid primary key default gen_random_uuid(),
    profile_id text not null references public.profiles(profile_id) on delete restrict,
    event_id uuid references public.content_events(event_id) on delete set null,
    variant_id uuid references public.editorial_variants(variant_id) on delete set null,
    path text not null,
    sha256 text not null,
    perceptual_hash text,
    audio_fingerprint text,
    duration double precision not null check (duration >= 0),
    width integer not null check (width >= 0),
    height integer not null check (height >= 0),
    aspect_ratio text not null,
    codec text,
    audio_codec text,
    filesize bigint not null check (filesize >= 0),
    validation_status text not null default 'pending'
        check (validation_status in ('pending', 'valid', 'invalid')),
    validation_errors jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    unique (profile_id, variant_id, sha256)
);

create table if not exists public.publication_jobs (
    job_id uuid primary key default gen_random_uuid(),
    profile_id text not null references public.profiles(profile_id) on delete restrict,
    event_id uuid references public.content_events(event_id) on delete set null,
    variant_id uuid references public.editorial_variants(variant_id) on delete set null,
    asset_id uuid not null references public.media_assets(asset_id) on delete restrict,
    destination_id uuid not null references public.profile_destinations(id) on delete restrict,
    platform text not null,
    account_id uuid references public.platform_accounts(id) on delete restrict,
    status text not null default 'pending'
        check (status in (
            'pending', 'validating', 'ready', 'uploading', 'processing',
            'published', 'retry_wait', 'rejected', 'cancelled', 'failed'
        )),
    publication_key text not null unique,
    title text,
    caption text,
    cover_path text,
    scheduled_at timestamptz,
    next_attempt_at timestamptz,
    attempts integer not null default 0 check (attempts >= 0),
    max_attempts integer not null default 3 check (max_attempts > 0),
    worker_id text,
    locked_at timestamptz,
    lock_expires_at timestamptz,
    external_id text,
    remote_status text,
    last_error text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    published_at timestamptz
);

create table if not exists public.publication_attempts (
    attempt_id bigint generated always as identity primary key,
    job_id uuid not null references public.publication_jobs(job_id) on delete cascade,
    attempt_number integer not null check (attempt_number > 0),
    worker_id text,
    status text not null,
    error_type text,
    error_message text,
    external_id text,
    remote_status text,
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    duration_ms integer,
    metadata jsonb not null default '{}'::jsonb,
    unique (job_id, attempt_number)
);

create index if not exists publication_jobs_eligible_idx
    on public.publication_jobs(status, next_attempt_at, scheduled_at, created_at);
create index if not exists publication_jobs_profile_idx
    on public.publication_jobs(profile_id, created_at desc);
create index if not exists publication_jobs_destination_idx
    on public.publication_jobs(destination_id, created_at desc);
create index if not exists publication_attempts_job_idx
    on public.publication_attempts(job_id, attempt_number);

drop trigger if exists publication_jobs_set_updated_at on public.publication_jobs;
create trigger publication_jobs_set_updated_at
before update on public.publication_jobs
for each row execute function public.set_multi_profile_updated_at();

-- Claim atômico: SKIP LOCKED permite vários workers sem pegar o mesmo job.
create or replace function public.claim_publication_job(
    p_worker_id text,
    p_lock_seconds integer default 300
)
returns setof public.publication_jobs
language plpgsql
security invoker
as $$
declare
    claimed_id uuid;
begin
    select job_id into claimed_id
    from public.publication_jobs
    where status in ('pending', 'ready', 'retry_wait', 'processing')
      and attempts < max_attempts
      and coalesce(scheduled_at, now()) <= now()
      and coalesce(next_attempt_at, now()) <= now()
      and (lock_expires_at is null or lock_expires_at <= now())
    order by coalesce(scheduled_at, created_at), created_at
    for update skip locked
    limit 1;

    if claimed_id is null then
        return;
    end if;

    return query
    update public.publication_jobs
    set worker_id = p_worker_id,
        locked_at = now(),
        lock_expires_at = now() + make_interval(secs => greatest(30, p_lock_seconds)),
        status = case when status = 'processing' then 'processing' else 'validating' end,
        attempts = attempts + 1,
        updated_at = now()
    where job_id = claimed_id
    returning *;
end;
$$;

create or replace view public.publication_metrics as
select
    profile_id,
    platform,
    account_id,
    status,
    count(*)::bigint as job_count,
    min(created_at) as first_created_at,
    max(updated_at) as last_updated_at
from public.publication_jobs
group by profile_id, platform, account_id, status;

-- Assim como a migration multi-perfil, RLS não é ativado automaticamente
-- enquanto o dashboard usar autenticação local e anon key. Ver docs/SECRETS.md.
