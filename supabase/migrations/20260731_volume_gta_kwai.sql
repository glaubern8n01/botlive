-- Metas operacionais GTA/Kwai, estados manuais e metadados editáveis.
update public.profiles set settings = settings ||
  '{"daily_target":30,"daily_maximum":100,"render_concurrency":1,"analysis_concurrency":1,"download_concurrency":2,"prepare_only":true}'::jsonb,
  updated_at=now() where profile_id='kwai_cut_futebol';

update public.profiles set settings = settings ||
  '{"gta_daily_target":8,"gta_daily_maximum":12,"gta_render_concurrency":1,"schedule_hours":[8,10,12,14,16,18,20,22]}'::jsonb,
  updated_at=now() where profile_id in ('vigia','gta','gta_standard');

update public.vigia_config set max_posts_per_day=8,max_cortes_vod=greatest(max_cortes_vod,8),
  max_concurrent_renders=1,updated_at=now() where id=1;

alter table public.profile_destinations drop constraint if exists profile_destinations_publication_mode_check;
alter table public.profile_destinations add constraint profile_destinations_publication_mode_check check (
  publication_mode in ('disabled','manual','approval','prepare_only','automatic','upload_draft')
);

update public.profile_destinations set max_posts_per_day=8,minimum_interval_seconds=7200,
  allowed_hours='{8,10,12,14,16,18,20,22}',timezone='America/Sao_Paulo',
  max_pending_jobs=12,settings=settings||'{"daily_target":8,"daily_maximum":12,"render_concurrency":1}'::jsonb
where profile_id in ('gta6_cortes','gta6') and platform in ('youtube','instagram');

update public.profile_destinations set enabled=true,publication_mode='upload_draft',max_posts_per_day=8,
  minimum_interval_seconds=7200,allowed_hours='{8,10,12,14,16,18,20,22}',timezone='America/Sao_Paulo',
  max_pending_jobs=12,settings=settings||'{"mode":"upload_draft","rights_status":"authorized","direct_post":false,"shop":false}'::jsonb
where profile_id in ('gta6_cortes','gta6') and platform='tiktok_standard';

-- O rascunho confirmado pelo operador vira terminal para envio, mas não publicado.
update public.publication_jobs set status='draft_available',remote_status='SEND_TO_USER_INBOX',
  metadata=metadata||jsonb_build_object('manual_draft_confirmation',true,'draft_confirmed_at',now())
where platform='tiktok_standard' and external_id is not null
  and coalesce(metadata->>'mode',metadata->>'publish_mode')='upload_draft'
  and status in ('processing','ready','sent_to_user_inbox');

create or replace view public.gta_daily_metrics as
select current_date metric_date,
 count(distinct asset_id) filter(where created_at>=current_date) generated,
 count(*) filter(where platform='youtube' and status in ('published','published_manual') and created_at>=current_date) youtube_published,
 count(*) filter(where platform='instagram' and status in ('published','published_manual') and created_at>=current_date) instagram_published,
 count(*) filter(where platform='tiktok_standard' and status in ('draft_available','sent_to_user_inbox') and created_at>=current_date) tiktok_drafts,
 count(*) filter(where status='published_manual' and platform='tiktok_standard' and created_at>=current_date) tiktok_published_manual,
 count(*) filter(where status in ('failed','rejected') and created_at>=current_date) failures,
 min(scheduled_at) filter(where scheduled_at>now() and status in ('pending','ready')) next_scheduled_at
from public.publication_jobs where profile_id in ('gta6_cortes','gta6');

do $$ declare c record; begin
  for c in select conname from pg_constraint where conrelid='public.publication_jobs'::regclass
    and contype='c' and pg_get_constraintdef(oid) ilike '%status%' loop
    execute format('alter table public.publication_jobs drop constraint %I', c.conname);
  end loop;
end $$;
alter table public.publication_jobs add constraint publication_jobs_status_check check (status in (
  'pending','validating','ready','uploading','processing','draft_available','sent_to_user_inbox',
  'published','published_manual','retry_wait','rejected','cancelled','failed'
));

create or replace function public.mark_manual_publication(p_job_id uuid,p_external_id text,p_published_at timestamptz)
returns public.publication_jobs language plpgsql security invoker as $$
declare result public.publication_jobs;
begin
  update public.publication_jobs set status='published_manual',external_id=nullif(trim(p_external_id),''),
    remote_status='published_manual',published_at=coalesce(p_published_at,now()),worker_id=null,
    locked_at=null,lock_expires_at=null,updated_at=now(),metadata=metadata||jsonb_build_object(
      'publication_method','manual_mobile','operational_status','published_manual','manually_confirmed_at',now())
  where job_id=p_job_id and status in ('ready','draft_available','sent_to_user_inbox') returning * into result;
  if result.job_id is null then raise exception 'Somente itens prontos ou rascunhos podem ser marcados como publicados'; end if;
  return result;
end $$;

create or replace function public.update_publication_text(p_job_id uuid,p_description text,p_hashtags text,p_credits text,p_caption text)
returns public.publication_jobs language plpgsql security invoker as $$
declare result public.publication_jobs;
begin
  update public.publication_jobs set caption=p_caption,updated_at=now(),metadata=metadata||jsonb_build_object(
    'description',p_description,'hashtags',p_hashtags,'credits',p_credits,
    'text_approved',true,'text_edited_manually',true,'text_approved_at',now())
  where job_id=p_job_id and status in ('pending','validating','ready','draft_available','sent_to_user_inbox') returning * into result;
  if result.job_id is null then raise exception 'Texto não pode ser editado neste estado'; end if;
  return result;
end $$;

create or replace view public.kwai_cut_daily_metrics as
select p.profile_id,current_date metric_date,
 coalesce((p.settings->>'daily_minimum')::integer,30) daily_minimum,
 coalesce((p.settings->>'daily_target')::integer,30) daily_target,
 coalesce((p.settings->>'daily_maximum')::integer,100) daily_maximum,
 count(distinct a.asset_id) filter(where a.created_at>=current_date) generated,
 count(distinct a.asset_id) filter(where a.created_at>=current_date and a.validation_status='valid') approved,
 count(distinct a.asset_id) filter(where a.created_at>=current_date and a.validation_status='invalid') rejected,
 count(distinct j.job_id) filter(where j.created_at>=current_date and j.status in ('pending','validating','retry_wait')) queued,
 count(distinct j.job_id) filter(where j.created_at>=current_date and j.status='ready') ready,
 count(distinct j.job_id) filter(where j.published_at>=current_date and j.status in ('published','published_manual')) published
from public.profiles p left join public.media_assets a on a.profile_id=p.profile_id
left join public.publication_jobs j on j.profile_id=p.profile_id
where p.profile_id='kwai_cut_futebol' group by p.profile_id,p.settings;
