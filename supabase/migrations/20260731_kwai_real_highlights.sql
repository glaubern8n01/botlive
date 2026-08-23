-- Pipeline real e auditável do Kwai CUT. Não publica automaticamente.
alter table public.football_discovered_videos
  add column if not exists source_sha256 text,
  add column if not exists media_asset_id uuid references public.media_assets(asset_id) on delete set null,
  add column if not exists publication_job_id uuid references public.publication_jobs(job_id) on delete set null;

create unique index if not exists football_discovered_source_sha_unique
  on public.football_discovered_videos(profile_id, source_sha256)
  where source_sha256 is not null and status not in ('rejected','error');

create unique index if not exists kwai_media_sha_unique
  on public.media_assets(profile_id, sha256)
  where profile_id='kwai_cut_futebol';

with ranked as (
  select asset_id, path,
         row_number() over(partition by profile_id, path order by created_at, asset_id) as duplicate_rank
  from public.media_assets
  where profile_id='kwai_cut_futebol'
)
update public.media_assets asset
set validation_status='invalid',
    validation_errors=coalesce(asset.validation_errors, '[]'::jsonb) || '["duplicate_media_path"]'::jsonb,
    path=asset.path || '#duplicate-record:' || asset.asset_id::text
from ranked
where asset.asset_id=ranked.asset_id and ranked.duplicate_rank>1;

create unique index if not exists kwai_media_path_unique
  on public.media_assets(profile_id, path)
  where profile_id='kwai_cut_futebol';

create index if not exists kwai_media_visual_idx
  on public.media_assets(profile_id, perceptual_hash)
  where profile_id='kwai_cut_futebol' and perceptual_hash is not null;

create index if not exists kwai_media_audio_idx
  on public.media_assets(profile_id, audio_fingerprint)
  where profile_id='kwai_cut_futebol' and audio_fingerprint is not null;

-- Os lotes históricos genéricos ficam auditáveis, mas saem da fila de revisão.
update public.publication_jobs
set status='rejected', last_error='generic_historical_content_forbidden_by_kwai_spec',
    metadata=metadata || '{"invalidated_reason":"generic_historical_content","superseded":true}'::jsonb
where profile_id='kwai_cut_futebol'
  and status in ('pending','ready','retry_wait')
  and coalesce(metadata->>'version','') in ('2','3','4');

alter table public.football_source_checks
  add column if not exists discard_reasons jsonb not null default '{}'::jsonb;
alter table public.football_source_checks drop constraint if exists football_source_checks_status_check;
alter table public.football_source_checks add constraint football_source_checks_status_check
  check (status in ('ok','error','skipped'));
