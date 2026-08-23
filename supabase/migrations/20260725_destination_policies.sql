-- Políticas independentes por perfil/destino.
alter table public.profile_destinations
    add column if not exists minimum_interval_seconds integer not null default 0
        check (minimum_interval_seconds >= 0),
    add column if not exists allowed_hours jsonb not null default '[]'::jsonb,
    add column if not exists timezone text not null default 'UTC',
    add column if not exists max_pending_jobs integer
        check (max_pending_jobs is null or max_pending_jobs >= 0),
    add column if not exists max_attempts integer not null default 3
        check (max_attempts > 0),
    add column if not exists publisher_options jsonb not null default '{}'::jsonb;
