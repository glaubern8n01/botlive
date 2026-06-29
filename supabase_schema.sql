create table if not exists public.dark_gta_clips (
  id uuid primary key default gen_random_uuid(),
  live_url text not null,
  peak_timestamp integer not null,
  keywords text[] not null default '{}',
  messages_per_minute integer,
  status text not null default 'pendente',
  output_path text,
  error_message text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint dark_gta_clips_status_check
    check (status in ('pendente', 'processando', 'concluido', 'erro'))
);

create index if not exists dark_gta_clips_status_idx
  on public.dark_gta_clips (status);

create index if not exists dark_gta_clips_created_at_idx
  on public.dark_gta_clips (created_at desc);

create or replace function public.set_dark_gta_clips_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists dark_gta_clips_set_updated_at on public.dark_gta_clips;

create trigger dark_gta_clips_set_updated_at
before update on public.dark_gta_clips
for each row
execute function public.set_dark_gta_clips_updated_at();
