-- Fluxo seguro de postagem manual pelo celular para o perfil Kwai CUT.
-- Não armazena senha, cookie, token ou sessão do navegador.

alter table public.kwai_cut_activities
    add column if not exists confirmed_at timestamptz,
    add column if not exists notes text;

create or replace view public.platform_accounts_safe as
select
    id,
    platform,
    account_key,
    display_name,
    status,
    (secret_ref is not null and length(trim(secret_ref)) > 0) as secret_configured,
    created_at,
    updated_at,
    metadata->>'public_username' as public_username,
    metadata->>'public_profile_url' as public_profile_url,
    metadata->>'creator_status' as creator_status,
    metadata->>'agency' as agency,
    metadata->>'contracted_at' as contracted_at,
    metadata->>'contract_month' as contract_month,
    metadata->>'confirmed_niche' as confirmed_niche,
    metadata->>'publication_mode' as publication_mode
from public.platform_accounts;

update public.platform_accounts
set
    display_name = 'Futebolrespiraofc',
    status = 'connected',
    metadata = metadata || jsonb_build_object(
        'public_username', 'futebolrespirafc',
        'public_profile_url', 'https://k.kwai.com/u/@futebolrespirafc/BCyK6msG',
        'creator_status', 'Criador Contratado',
        'agency', 'Edit-Vetra Digital',
        'contracted_at', '2026-07-28',
        'contract_month', 1,
        'confirmed_niche', 'futebol real',
        'publication_mode', 'manual_mobile',
        'api_enabled', false,
        'verification_source', 'capturas do aplicativo confirmadas pelo operador'
    ),
    updated_at = now()
where platform = 'kwai' and account_key = 'principal';

update public.profiles
set settings = settings || jsonb_build_object(
    'daily_minimum', 5,
    'daily_target', 5,
    'daily_maximum', 100,
    'prepare_only', true,
    'manual_mobile_publication', true,
    'account_confirmed', true,
    'pending_confirmations', jsonb_build_array(
        'regras exatas da atividade',
        'duração oficial',
        'hashtags',
        'critérios de vídeo válido',
        'método oficial de publicação automática'
    )
), updated_at = now()
where profile_id = 'kwai_cut_futebol';

update public.kwai_cut_activities
set
    name = 'Atividade CUT — aguardando confirmação',
    min_duration_seconds = null,
    max_duration_seconds = null,
    required_hashtags = '{}',
    required_terms = '{}',
    category = 'futebol real — confirmado pela agência',
    minimum_quantity = null,
    confirmation_status = 'unconfirmed',
    confirmed_at = null,
    notes = 'Conta e contratação confirmadas. Regras exatas, duração oficial, hashtags e critérios de vídeo válido aguardam confirmação.',
    active = true,
    updated_at = now()
where profile_id = 'kwai_cut_futebol' and active;

create unique index if not exists publication_jobs_platform_external_id_idx
    on public.publication_jobs(platform, external_id)
    where external_id is not null;

create or replace function public.mark_manual_publication(
    p_job_id uuid,
    p_external_id text,
    p_published_at timestamptz
)
returns public.publication_jobs
language plpgsql
security invoker
as $$
declare
    result public.publication_jobs;
    target_asset uuid;
begin
    if nullif(trim(p_external_id), '') is null then
        raise exception 'URL ou ID da publicação é obrigatório';
    end if;
    if p_published_at is null then
        raise exception 'Horário da publicação é obrigatório';
    end if;

    select asset_id into target_asset
    from public.publication_jobs
    where job_id = p_job_id and profile_id = 'kwai_cut_futebol'
    for update;

    if target_asset is null then
        raise exception 'Job não encontrado';
    end if;

    if exists (
        select 1 from public.publication_jobs
        where asset_id = target_asset
          and status = 'published'
          and job_id <> p_job_id
    ) then
        raise exception 'Este vídeo já foi registrado como publicado';
    end if;

    update public.publication_jobs
    set
        status = 'published',
        external_id = trim(p_external_id),
        remote_status = 'manual_confirmed',
        published_at = p_published_at,
        worker_id = null,
        locked_at = null,
        lock_expires_at = null,
        updated_at = now(),
        metadata = metadata || jsonb_build_object(
            'publication_method', 'manual_mobile',
            'manually_confirmed_at', now()
        )
    where job_id = p_job_id
      and profile_id = 'kwai_cut_futebol'
      and status = 'ready'
    returning * into result;

    if result.job_id is null then
        raise exception 'Somente vídeos prontos podem ser marcados como publicados';
    end if;
    return result;
end;
$$;
