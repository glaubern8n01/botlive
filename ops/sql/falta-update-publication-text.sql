-- Kwai CUT: a unica RPC que o painel usa e que nunca foi criada no banco.
--
-- Sintoma: o botao "Salvar e aprovar texto" na aba "Publicar pelo celular"
-- falha silenciosamente. O backend chama update_publication_text e o PostgREST
-- responde PGRST202 (funcao inexistente). As outras tres RPCs do painel
-- (mark_manual_publication, review_football_source_prospect,
-- reevaluate_football_source_prospect) ja existem e funcionam.
--
-- Origem: supabase/migrations/20260731_volume_gta_kwai.sql, na branch
-- codex/kwai-multichannel-discovery. Rodar no SQL Editor do Supabase.

create or replace function public.update_publication_text(
  p_job_id uuid, p_description text, p_hashtags text, p_credits text, p_caption text
)
returns public.publication_jobs language plpgsql security invoker as $$
declare result public.publication_jobs;
begin
  update public.publication_jobs
     set caption = p_caption,
         updated_at = now(),
         metadata = metadata || jsonb_build_object(
           'description', p_description,
           'hashtags', p_hashtags,
           'credits', p_credits,
           'text_approved', true,
           'text_edited_manually', true,
           'text_approved_at', now())
   where job_id = p_job_id
     and status in ('pending','validating','ready','draft_available','sent_to_user_inbox')
   returning * into result;
  if result.job_id is null then
    raise exception 'Texto nao pode ser editado neste estado';
  end if;
  return result;
end $$;
