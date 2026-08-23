-- Lote v1 preservado como evidência de teste, mas removido da fila pronta.
with v1 as (
    select j.job_id, j.asset_id
    from public.publication_jobs j
    join public.editorial_variants v on v.variant_id = j.variant_id
    where j.profile_id = 'kwai_cut_futebol'
      and v.variant_signature like 'manual-mobile-v1:%'
      and j.status <> 'published'
)
update public.media_assets a
set validation_status = 'invalid',
    validation_errors = '["test_only","rejected_missing_audio_and_text"]'::jsonb
from v1
where a.asset_id = v1.asset_id;

update public.publication_jobs j
set status = 'rejected',
    last_error = 'test_only: áudio silencioso e textos não queimados no MP4',
    metadata = coalesce(j.metadata, '{}'::jsonb) || jsonb_build_object(
        'test_only', true,
        'invalidated_reason', 'rejected_missing_audio_and_text',
        'invalidated_at', now()
    )
from public.editorial_variants v
where j.variant_id = v.variant_id
  and j.profile_id = 'kwai_cut_futebol'
  and v.variant_signature like 'manual-mobile-v1:%'
  and j.status <> 'published';
