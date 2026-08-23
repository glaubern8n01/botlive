-- Kwai CUT: libera o status 'paused_resource_guard' em kwai_cut_producer_state.
--
-- O código em produção (kwai_cut_producer.py) grava esse status quando o guard
-- de recurso segura a produção (memória alta ou ffmpeg pesado já rodando). A
-- constraint original (20260731_kwai_daily_production.sql) só aceitava
-- idle/running/deficit/healthy/error, então TODO ciclo que batia no guard
-- morria com:
--   23514 new row for relation "kwai_cut_producer_state" violates check
--   constraint "kwai_cut_producer_state_status_check"
-- Com o relay ligado o ffmpeg está quase sempre ocupado, ou seja: o produtor
-- automático caía em praticamente todo ciclo de 15 min.

alter table public.kwai_cut_producer_state
    drop constraint if exists kwai_cut_producer_state_status_check;

alter table public.kwai_cut_producer_state
    add constraint kwai_cut_producer_state_status_check
    check (status in ('idle','running','deficit','healthy','error','paused_resource_guard'));
