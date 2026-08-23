-- Produção diária Kwai CUT: aditiva, prepare_only e sem API externa.

update public.profiles
set settings = settings || '{"daily_minimum":30,"daily_target":30,"daily_maximum":100,"published_media_retention_days":30,"rejected_media_retention_days":7,"temporary_files_retention_hours":24,"prepare_only":true}'::jsonb,
    enabled = true,
    updated_at = now()
where profile_id = 'kwai_cut_futebol';

update public.profile_destinations
set enabled = true, publication_mode = 'prepare_only',
    settings = settings || '{"mode":"prepare_only","api_enabled":false}'::jsonb
where profile_id = 'kwai_cut_futebol' and platform = 'kwai';

create table if not exists public.kwai_cut_producer_state (
    profile_id text primary key references public.profiles(profile_id) on delete restrict,
    worker_id text,
    lease_expires_at timestamptz,
    last_started_at timestamptz,
    last_finished_at timestamptz,
    next_run_at timestamptz,
    target integer not null default 30 check (target between 1 and 100),
    approved_today integer not null default 0,
    deficit integer not null default 30,
    eligible_sources integer not null default 0,
    status text not null default 'idle' check (status in ('idle','running','deficit','healthy','error')),
    last_error text,
    disk_usage_bytes bigint not null default 0,
    updated_at timestamptz not null default now()
);

insert into public.kwai_cut_producer_state(profile_id)
values ('kwai_cut_futebol') on conflict (profile_id) do nothing;

create or replace function public.mark_manual_publication(
    p_job_id uuid, p_external_id text, p_published_at timestamptz
)
returns public.publication_jobs language plpgsql security invoker as $$
declare result public.publication_jobs; target_asset uuid;
begin
    if nullif(trim(p_external_id), '') is null then raise exception 'URL ou ID da publicação é obrigatório'; end if;
    if p_published_at is null then raise exception 'Horário da publicação é obrigatório'; end if;
    select asset_id into target_asset from public.publication_jobs
      where job_id=p_job_id and profile_id='kwai_cut_futebol' for update;
    if target_asset is null then raise exception 'Job não encontrado'; end if;
    if exists(select 1 from public.publication_jobs where asset_id=target_asset and status='published' and job_id<>p_job_id)
      then raise exception 'Este vídeo já foi registrado como publicado'; end if;
    update public.publication_jobs set status='published', external_id=trim(p_external_id),
      remote_status='published_manual', published_at=p_published_at, worker_id=null,
      locked_at=null, lock_expires_at=null, updated_at=now(),
      metadata=metadata || jsonb_build_object(
        'publication_method','manual_mobile','operational_status','published_manual',
        'manually_confirmed_at',now(),'media_delete_after',now()+interval '30 days'
      )
    where job_id=p_job_id and profile_id='kwai_cut_futebol' and status='ready'
    returning * into result;
    if result.job_id is null then raise exception 'Somente vídeos prontos podem ser marcados como publicados'; end if;
    return result;
end; $$;

create or replace view public.kwai_cut_daily_metrics as
select p.profile_id, current_date metric_date,
  coalesce((p.settings->>'daily_minimum')::integer,30) daily_minimum,
  coalesce((p.settings->>'daily_target')::integer,30) daily_target,
  count(distinct a.asset_id) filter(where a.created_at>=current_date) generated,
  count(distinct a.asset_id) filter(where a.created_at>=current_date and a.validation_status='valid') approved,
  count(distinct a.asset_id) filter(where a.created_at>=current_date and a.validation_status='invalid') rejected,
  count(distinct j.job_id) filter(where j.created_at>=current_date and j.status in ('pending','validating','retry_wait')) queued,
  count(distinct j.job_id) filter(where j.created_at>=current_date and j.status='ready') ready,
  count(distinct j.job_id) filter(where j.published_at>=current_date and j.status='published') published
from public.profiles p left join public.media_assets a on a.profile_id=p.profile_id
left join public.publication_jobs j on j.profile_id=p.profile_id
where p.profile_id='kwai_cut_futebol' group by p.profile_id,p.settings;
