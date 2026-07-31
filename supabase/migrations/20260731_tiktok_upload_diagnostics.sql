create table if not exists public.tiktok_standard_uploads (
    upload_id uuid primary key default gen_random_uuid(),
    account_id uuid not null references public.platform_accounts(id) on delete restrict,
    publication_key text not null unique,
    publish_id text not null unique,
    asset_path text not null,
    asset_sha256 text not null,
    video_size bigint not null check (video_size > 0),
    chunk_size bigint not null check (chunk_size > 0),
    total_chunk_count integer not null check (total_chunk_count between 1 and 1000),
    bytes_sent bigint not null default 0,
    upload_host text,
    status text not null,
    remote_status text,
    upload_started_at timestamptz not null,
    updated_at timestamptz not null default now()
);
alter table public.tiktok_standard_uploads enable row level security;
