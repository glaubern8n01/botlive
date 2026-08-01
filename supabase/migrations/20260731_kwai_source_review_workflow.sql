-- Kwai CUT: fluxo de revisão, autorização e auditoria de fontes.
-- Migração ADITIVA e idempotente (re-execução segura). Não remove colunas nem dados.

-- 1. Amplia usage_status das fontes com 'approved' e adiciona validade da autorização.
alter table public.football_sources drop constraint if exists football_sources_usage_status_check;
alter table public.football_sources add constraint football_sources_usage_status_check
  check (usage_status in ('authorized','licensed','campaign_allowed','approved','owned','review_required','blocked'));
alter table public.football_sources add column if not exists authorization_expires_at timestamptz;

-- 2. Campos de revisão/autorização nas fontes candidatas.
alter table public.football_source_prospects
  add column if not exists owner_name text,
  add column if not exists authorization_reason text,
  add column if not exists license_or_cut_task text,
  add column if not exists evidence_url text,
  add column if not exists review_notes text,
  add column if not exists reviewed_at timestamptz,
  add column if not exists reviewed_by text,
  add column if not exists blocked_reason text,
  add column if not exists blocked_at timestamptz,
  add column if not exists authorization_expires_at timestamptz,
  add column if not exists previous_review_state text,
  add column if not exists approved_source_id uuid references public.football_sources(source_id);

-- 3. Renomeia status legados e amplia o check de review_status.
alter table public.football_source_prospects drop constraint if exists football_source_prospects_review_status_check;
update public.football_source_prospects set review_status = 'review_required' where review_status = 'pending_review';
update public.football_source_prospects set review_status = 'blocked' where review_status = 'rejected';
alter table public.football_source_prospects add constraint football_source_prospects_review_status_check
  check (review_status in ('discovered','review_required','approved','campaign_allowed','licensed','authorized','blocked'));
alter table public.football_source_prospects alter column review_status set default 'review_required';

-- 4. Auditoria de revisões (preserva toda decisão anterior).
create table if not exists public.football_source_review_history (
  history_id uuid primary key default gen_random_uuid(),
  prospect_id uuid not null references public.football_source_prospects(prospect_id) on delete cascade,
  profile_id text not null,
  from_status text,
  to_status text not null,
  action text not null check (action in ('approve','block','reevaluate')),
  reviewed_by text not null default 'dashboard',
  reason text,
  evidence_url text,
  notes text,
  created_at timestamptz not null default now()
);
create index if not exists football_source_review_history_idx
  on public.football_source_review_history(prospect_id, created_at desc);

-- 5. RPC de aprovação/bloqueio, com validação de transição e auditoria.
create or replace function public.review_football_source_prospect(
  p_prospect_id uuid, p_status text, p_owner_name text, p_authorization_reason text,
  p_license_or_cut_task text, p_evidence_url text, p_review_notes text default null,
  p_reviewed_by text default 'dashboard', p_authorization_expires_at timestamptz default null,
  p_blocked_reason text default null
) returns uuid language plpgsql security definer set search_path = public as $$
declare p public.football_source_prospects; new_source_id uuid;
begin
  if p_status not in ('approved','campaign_allowed','licensed','authorized','blocked') then
    raise exception 'invalid review status';
  end if;
  select * into p from public.football_source_prospects
    where prospect_id = p_prospect_id and profile_id = 'kwai_cut_futebol' for update;
  if not found then raise exception 'prospect not found'; end if;

  if p_status = 'blocked' then
    if nullif(trim(p_blocked_reason),'') is null then
      raise exception 'blocked_reason is required';
    end if;
    -- Bloqueio retira imediatamente a fonte ligada da produção.
    if p.approved_source_id is not null then
      update public.football_sources set usage_status = 'blocked', enabled = false, updated_at = now()
        where source_id = p.approved_source_id;
    end if;
  else
    -- Concessão exige evidência; fonte bloqueada precisa ser reavaliada antes.
    if p.review_status = 'blocked' then
      raise exception 'source is blocked; reevaluate before approving';
    end if;
    if nullif(trim(p_owner_name),'') is null or nullif(trim(p_authorization_reason),'') is null
        or nullif(trim(p_license_or_cut_task),'') is null or nullif(trim(p_evidence_url),'') is null then
      raise exception 'owner, authorization reason, license/CUT task and evidence are required';
    end if;
    insert into public.football_sources(profile_id,name,source_type,source_ref,usage_status,enabled,priority,
        allowed_live,allowed_vod,allowed_highlights,authorization_expires_at,settings)
    values (p.profile_id, coalesce(nullif(p.title,''), p.source_url),
      case when p.source_type in ('youtube_channel','youtube_playlist','youtube_search','youtube_live','direct_video','local_file','watched_folder','authorized_feed')
           then p.source_type else 'direct_video' end,
      p.source_url, p_status, true, 70,
      p.source_type in ('youtube_live','youtube_channel'), true, true, p_authorization_expires_at,
      jsonb_build_object('owner_name',p_owner_name,'authorization_reason',p_authorization_reason,
        'license_or_cut_task',p_license_or_cut_task,'evidence_url',p_evidence_url,
        'review_notes',p_review_notes,'prospect_id',p.prospect_id))
    on conflict (profile_id, source_type, source_ref) do update
      set usage_status = excluded.usage_status, enabled = true, priority = excluded.priority,
          authorization_expires_at = excluded.authorization_expires_at, settings = excluded.settings, updated_at = now()
    returning source_id into new_source_id;
  end if;

  update public.football_source_prospects set
    review_status = p_status,
    previous_review_state = p.review_status,
    owner_name = coalesce(nullif(trim(p_owner_name),''), p.owner_name),
    authorization_reason = coalesce(nullif(trim(p_authorization_reason),''), p.authorization_reason),
    license_or_cut_task = coalesce(nullif(trim(p_license_or_cut_task),''), p.license_or_cut_task),
    evidence_url = coalesce(nullif(trim(p_evidence_url),''), p.evidence_url),
    review_notes = nullif(trim(p_review_notes),''),
    authorization_expires_at = case when p_status = 'blocked' then p.authorization_expires_at else p_authorization_expires_at end,
    blocked_reason = case when p_status = 'blocked' then nullif(trim(p_blocked_reason),'') else null end,
    blocked_at = case when p_status = 'blocked' then now() else null end,
    reviewed_at = now(), reviewed_by = p_reviewed_by,
    approved_source_id = coalesce(new_source_id, p.approved_source_id),
    updated_at = now()
  where prospect_id = p_prospect_id;

  insert into public.football_source_review_history(prospect_id,profile_id,from_status,to_status,action,reviewed_by,reason,evidence_url,notes)
  values (p_prospect_id, p.profile_id, p.review_status, p_status,
    case when p_status = 'blocked' then 'block' else 'approve' end, p_reviewed_by,
    case when p_status = 'blocked' then p_blocked_reason else p_authorization_reason end,
    nullif(trim(p_evidence_url),''), p_review_notes);

  return new_source_id;
end $$;

-- 6. RPC de reavaliação: só a partir de blocked, review_required ou autorização vencida.
create or replace function public.reevaluate_football_source_prospect(
  p_prospect_id uuid, p_reviewed_by text default 'dashboard', p_reason text default null, p_notes text default null
) returns void language plpgsql security definer set search_path = public as $$
declare p public.football_source_prospects;
begin
  select * into p from public.football_source_prospects
    where prospect_id = p_prospect_id and profile_id = 'kwai_cut_futebol' for update;
  if not found then raise exception 'prospect not found'; end if;
  if p.review_status not in ('blocked','review_required')
      and not (p.authorization_expires_at is not null and p.authorization_expires_at <= now()) then
    raise exception 'source is not blocked, pending or expired';
  end if;
  if nullif(trim(p_reason),'') is null then raise exception 'reason is required'; end if;
  -- Preserva a decisão anterior e tira a fonte de produção até nova aprovação.
  if p.approved_source_id is not null then
    update public.football_sources set enabled = false, updated_at = now() where source_id = p.approved_source_id;
  end if;
  update public.football_source_prospects set
    review_status = 'review_required', previous_review_state = p.review_status,
    blocked_reason = null, blocked_at = null,
    review_notes = coalesce(nullif(trim(p_notes),''), p.review_notes),
    reviewed_at = now(), reviewed_by = p_reviewed_by, updated_at = now()
  where prospect_id = p_prospect_id;
  insert into public.football_source_review_history(prospect_id,profile_id,from_status,to_status,action,reviewed_by,reason,notes)
  values (p_prospect_id, p.profile_id, p.review_status, 'review_required', 'reevaluate', p_reviewed_by, p_reason, p_notes);
end $$;
