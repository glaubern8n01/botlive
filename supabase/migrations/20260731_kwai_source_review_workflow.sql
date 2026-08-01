alter table public.football_source_prospects
  add column if not exists owner_name text,
  add column if not exists authorization_reason text,
  add column if not exists license_or_cut_task text,
  add column if not exists evidence_url text,
  add column if not exists review_notes text,
  add column if not exists reviewed_at timestamptz,
  add column if not exists reviewed_by text,
  add column if not exists approved_source_id uuid references public.football_sources(source_id);

alter table public.football_source_prospects drop constraint if exists football_source_prospects_review_status_check;
update public.football_source_prospects set review_status = 'review_required' where review_status = 'pending_review';
update public.football_source_prospects set review_status = 'blocked' where review_status = 'rejected';
alter table public.football_source_prospects add constraint football_source_prospects_review_status_check
  check (review_status in ('discovered','review_required','approved','campaign_allowed','licensed','authorized','blocked'));
alter table public.football_source_prospects alter column review_status set default 'review_required';

create or replace function public.review_football_source_prospect(
  p_prospect_id uuid, p_status text, p_owner_name text, p_authorization_reason text,
  p_license_or_cut_task text, p_evidence_url text, p_review_notes text default null,
  p_reviewed_by text default 'dashboard'
) returns uuid language plpgsql security definer set search_path = public as $$
declare p public.football_source_prospects; new_source_id uuid;
begin
  if p_status not in ('approved','campaign_allowed','licensed','authorized','blocked') then
    raise exception 'invalid review status';
  end if;
  select * into p from public.football_source_prospects where prospect_id = p_prospect_id and profile_id = 'kwai_cut_futebol' for update;
  if not found then raise exception 'prospect not found'; end if;
  if p_status <> 'blocked' and (nullif(trim(p_owner_name),'') is null or nullif(trim(p_authorization_reason),'') is null
      or nullif(trim(p_license_or_cut_task),'') is null or nullif(trim(p_evidence_url),'') is null) then
    raise exception 'owner, authorization reason, license/CUT task and evidence are required';
  end if;
  if p_status <> 'blocked' then
    insert into public.football_sources(profile_id,name,source_type,source_ref,usage_status,enabled,priority,allowed_live,allowed_vod,allowed_highlights,settings)
    values (p.profile_id, coalesce(nullif(p.title,''),p.source_url),
      case when p.source_type in ('youtube_channel','youtube_playlist','youtube_search','youtube_live','direct_video','local_file','watched_folder','authorized_feed') then p.source_type else 'direct_video' end,
      p.source_url, p_status, true, 70, p.source_type in ('youtube_live','youtube_channel'), true, true,
      jsonb_build_object('owner_name',p_owner_name,'authorization_reason',p_authorization_reason,'license_or_cut_task',p_license_or_cut_task,'evidence_url',p_evidence_url,'review_notes',p_review_notes,'prospect_id',p.prospect_id))
    returning source_id into new_source_id;
  end if;
  update public.football_source_prospects set review_status=p_status, owner_name=nullif(trim(p_owner_name),''),
    authorization_reason=nullif(trim(p_authorization_reason),''), license_or_cut_task=nullif(trim(p_license_or_cut_task),''),
    evidence_url=nullif(trim(p_evidence_url),''), review_notes=nullif(trim(p_review_notes),''), reviewed_at=now(),
    reviewed_by=p_reviewed_by, approved_source_id=new_source_id, updated_at=now() where prospect_id=p_prospect_id;
  return new_source_id;
end $$;
