create table if not exists public.football_source_checks (
  check_id uuid primary key default gen_random_uuid(),
  profile_id text not null references public.profiles(profile_id) on delete cascade,
  source_id uuid not null references public.football_sources(source_id) on delete cascade,
  status text not null check (status in ('ok','error')),
  checked_at timestamptz not null default now(),
  found_count integer not null default 0,
  new_count integer not null default 0,
  duplicate_count integer not null default 0,
  discarded_count integer not null default 0,
  live_count integer not null default 0,
  error text
);

create index if not exists football_source_checks_source_checked_idx
  on public.football_source_checks(profile_id, source_id, checked_at desc);

create table if not exists public.football_discovered_videos (
  discovered_id uuid primary key default gen_random_uuid(),
  profile_id text not null references public.profiles(profile_id) on delete cascade,
  source_id uuid not null references public.football_sources(source_id) on delete cascade,
  discovery_key text not null,
  external_id text,
  source_url text not null,
  source_name text not null,
  title text not null,
  duration numeric,
  source_published_at text,
  status text not null default 'found' check (status in (
    'found','waiting_processing','processing','cut_identified','rendering',
    'ready_review','approved','rejected','error'
  )),
  discard_reason text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(profile_id, discovery_key)
);

create unique index if not exists football_discovered_external_unique
  on public.football_discovered_videos(profile_id, source_id, external_id)
  where external_id is not null;
