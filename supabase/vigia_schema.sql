-- Schema do Vigia (V2 do PLANO-VIGIA.md) — rodar no Supabase Studio > SQL Editor.
-- Idempotente: pode rodar de novo sem estragar nada.
-- REGRA DE OURO: max_posts_per_day existe desde o inicio e o default do vigia
-- e TUDO DESLIGADO (enabled=false) — ligar e decisao explicita no dashboard/Studio.

-- 1) Config unica (linha id=1). Dashboard futuro so faz UPDATE nesta linha.
create table if not exists vigia_config (
    id int primary key check (id = 1),
    enabled boolean not null default false,
    manual_channels_enabled boolean not null default true,
    discovery_enabled boolean not null default false,
    live_mode_enabled boolean not null default false,
    vod_mode_enabled boolean not null default true,
    discovery_game text not null default 'Grand Theft Auto V',
    discovery_language text not null default 'pt',
    discovery_min_viewers int not null default 100,
    discovery_max_channels int not null default 3,
    poll_interval_seconds int not null default 60,
    max_concurrent_captures int not null default 2,
    max_concurrent_renders int not null default 1,
    vod_delay_minutes int not null default 15,
    vod_max_attempts int not null default 6,
    dedup_window_seconds int not null default 60,
    max_cortes_live int not null default 3,
    max_cortes_vod int not null default 3,
    clip_duration_seconds int not null default 45,
    content_filter text not null default 'gta',
    target_height int not null default 720,
    post_youtube_enabled boolean not null default false,
    post_visibilidade text not null default 'unlisted'
        check (post_visibilidade in ('private', 'unlisted', 'public')),
    -- Teto DURO de uploads/dia no YouTube (quota: 10.000 units/dia; upload=1.600
    -- => ~6 uploads/dia; cada corte hoje = 2 uploads HD+vertical). O vigia NUNCA
    -- dispara job com post ligado se o orcamento do dia nao couber.
    max_posts_per_day int not null default 4 check (max_posts_per_day >= 0),
    -- Post do modo LIVE (cortes em tempo real): visibilidade e SEMPRE private
    -- (rascunho no Studio, publicacao manual) — fixa no codigo, sem coluna.
    -- Teto proprio: live e VOD tem orcamentos separados; a soma dos dois tetos
    -- deve caber nos ~6 uploads/dia da quota.
    post_live_enabled boolean not null default false,
    max_posts_per_day_live int not null default 2 check (max_posts_per_day_live >= 0),
    credito_streamer text,
    credito_canal text default '@GTA6brasilcortesoficial',
    updated_at timestamptz not null default now()
);

insert into vigia_config (id) values (1) on conflict (id) do nothing;

-- 2) Lista manual de canais (prioridade sobre descoberta).
create table if not exists vigia_channels (
    id bigint generated always as identity primary key,
    login text not null unique,
    enabled boolean not null default true,
    priority int not null default 100,
    added_by text not null default 'manual' check (added_by in ('manual', 'discovery')),
    last_seen_live timestamptz,
    notes text,
    created_at timestamptz not null default now()
);

-- 3) Ledger de execucao por transmissao. unique(stream_id) e o lock que impede
--    duas instancias do vigia (ou um restart) de processarem o mesmo stream.
create table if not exists vigia_streams (
    id bigint generated always as identity primary key,
    stream_id text not null unique,
    channel_login text not null,
    channel_user_id text,
    origin text not null default 'manual' check (origin in ('manual', 'discovery')),
    started_at timestamptz,
    detected_at timestamptz not null default now(),
    capture_start_utc timestamptz,
    ended_at timestamptz,
    live_job_status text not null default 'disabled' check (live_job_status in
        ('disabled', 'skipped_no_slot', 'running', 'done', 'failed')),
    vod_job_status text not null default 'pending' check (vod_job_status in
        ('disabled', 'pending', 'waiting_vod', 'running', 'done', 'failed',
         'vod_unavailable', 'deduped_all')),
    vod_url text,
    vod_attempts int not null default 0,
    uploads_done int not null default 0,
    uploads_done_live int not null default 0,
    error_message text,
    dry_run boolean not null default false,
    updated_at timestamptz not null default now()
);

create index if not exists vigia_streams_channel_idx on vigia_streams (channel_login);
create index if not exists vigia_streams_vod_status_idx on vigia_streams (vod_job_status);

-- 4) Indice de cortes para o dedup live x VOD (V6; criado ja para o contrato
--    ficar fechado — o vigia so passa a escrever aqui quando V6 entrar).
create table if not exists vigia_clip_index (
    id bigint generated always as identity primary key,
    stream_id text not null,
    mode text not null check (mode in ('live', 'vod')),
    ts_vod_estimated int not null,
    clip_start_vod int not null,
    clip_end_vod int not null,
    session_id text not null,
    corte_ref text,
    created_at timestamptz not null default now()
);

create index if not exists vigia_clip_index_stream_idx on vigia_clip_index (stream_id);

-- 5) Migracao 13/07/2026 — post PRIVATE no modo live com teto proprio.
--    Idempotente para instalacoes que rodaram o schema antes desta data.
alter table vigia_config
    add column if not exists post_live_enabled boolean not null default false;
alter table vigia_config
    add column if not exists max_posts_per_day_live int not null default 2
        check (max_posts_per_day_live >= 0);
alter table vigia_streams
    add column if not exists uploads_done_live int not null default 0;

-- 6) Migracao 13/07/2026 (noite) — Reels no Instagram no fluxo VOD.
--    Reel e SEMPRE publico (API sem rascunho); so posta quando a trava do
--    post VOD do YouTube liberar o job.
alter table vigia_config
    add column if not exists post_instagram_enabled boolean not null default false;
