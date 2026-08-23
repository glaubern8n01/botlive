-- Views e ações seguras para o dashboard de publicação.
-- Nunca expõe secret_ref nem qualquer credencial.

create or replace view public.platform_accounts_safe as
select
    id,
    platform,
    account_key,
    display_name,
    status,
    (secret_ref is not null and length(trim(secret_ref)) > 0) as secret_configured,
    created_at,
    updated_at
from public.platform_accounts;

create or replace function public.cancel_publication_job(p_job_id uuid)
returns public.publication_jobs
language plpgsql
security invoker
as $$
declare
    result public.publication_jobs;
begin
    update public.publication_jobs
    set status = 'cancelled',
        worker_id = null,
        locked_at = null,
        lock_expires_at = null,
        updated_at = now()
    where job_id = p_job_id
      and status in ('pending', 'ready', 'retry_wait')
    returning * into result;
    return result;
end;
$$;

create or replace function public.retry_publication_job(p_job_id uuid)
returns public.publication_jobs
language plpgsql
security invoker
as $$
declare
    result public.publication_jobs;
begin
    update public.publication_jobs
    set status = 'pending',
        attempts = 0,
        next_attempt_at = null,
        worker_id = null,
        locked_at = null,
        lock_expires_at = null,
        last_error = null,
        updated_at = now()
    where job_id = p_job_id
      and status = 'failed'
    returning * into result;
    return result;
end;
$$;
