-- 30_seed_test_profiles.sql — cria perfis reais de teste, INERTES (enabled=false).
-- Rode DEPOIS das migrations. Depois valide o CRUD pelo dashboard (/perfis).
-- Idempotente: on conflict do nothing.

begin;

insert into public.profiles
  (profile_id, name, description, niche, editorial_strategy, language, enabled, settings)
values
  ('teste_cut', 'Teste CUT', 'Perfil de teste da estrategia CUT',
   'teste', 'cut', 'pt-BR', false, '{}'::jsonb),
  ('teste_narrastars', 'Teste Narrastars', 'Perfil de teste da estrategia Narrastars',
   'teste', 'narrastars', 'pt-BR', false, '{}'::jsonb)
on conflict (profile_id) do nothing;

-- Política de render padrão para cada perfil (permite abrir/editar no dashboard)
insert into public.profile_render_settings (profile_id)
values ('teste_cut'), ('teste_narrastars')
on conflict (profile_id) do nothing;

commit;

-- Conferência
select profile_id, name, editorial_strategy, enabled
from public.profiles
where profile_id in ('teste_cut', 'teste_narrastars')
order by profile_id;
