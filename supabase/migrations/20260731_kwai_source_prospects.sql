create table if not exists public.football_source_prospects (
  prospect_id uuid primary key default gen_random_uuid(),
  profile_id text not null references public.profiles(profile_id) on delete cascade,
  prospect_key text not null,
  source_url text not null,
  title text not null,
  source_type text not null default 'youtube_video',
  discovered_by text not null default 'automatic_search',
  search_query text,
  review_status text not null default 'pending_review' check (review_status in ('pending_review','approved','rejected')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(profile_id, prospect_key)
);
create index if not exists football_source_prospects_review_idx
  on public.football_source_prospects(profile_id, review_status, created_at desc);
