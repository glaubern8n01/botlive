// Espelho 1:1 do schema real em ../supabase/vigia_schema.sql.
// Se mudar o SQL, mudar aqui junto.

export type VigiaConfig = {
  id: number;
  enabled: boolean;
  manual_channels_enabled: boolean;
  discovery_enabled: boolean;
  live_mode_enabled: boolean;
  vod_mode_enabled: boolean;
  discovery_game: string;
  discovery_language: string;
  discovery_min_viewers: number;
  discovery_max_channels: number;
  poll_interval_seconds: number;
  max_concurrent_captures: number;
  max_concurrent_renders: number;
  vod_delay_minutes: number;
  vod_max_attempts: number;
  dedup_window_seconds: number;
  max_cortes_live: number;
  max_cortes_vod: number;
  clip_duration_seconds: number;
  content_filter: string;
  target_height: number;
  post_youtube_enabled: boolean;
  post_visibilidade: 'private' | 'unlisted' | 'public';
  max_posts_per_day: number;
  post_live_enabled: boolean;
  max_posts_per_day_live: number;
  post_instagram_enabled: boolean;
  credito_streamer: string | null;
  credito_canal: string | null;
  updated_at: string;
};

export type VigiaChannel = {
  id: number;
  login: string;
  enabled: boolean;
  priority: number;
  added_by: 'manual' | 'discovery';
  last_seen_live: string | null;
  notes: string | null;
  created_at: string;
};

export type LiveJobStatus = 'disabled' | 'skipped_no_slot' | 'running' | 'done' | 'failed';
export type VodJobStatus =
  | 'disabled'
  | 'pending'
  | 'waiting_vod'
  | 'running'
  | 'done'
  | 'failed'
  | 'vod_unavailable'
  | 'deduped_all';

export type VigiaStream = {
  id: number;
  stream_id: string;
  channel_login: string;
  channel_user_id: string | null;
  origin: 'manual' | 'discovery';
  started_at: string | null;
  detected_at: string;
  capture_start_utc: string | null;
  ended_at: string | null;
  live_job_status: LiveJobStatus;
  vod_job_status: VodJobStatus;
  vod_url: string | null;
  vod_attempts: number;
  uploads_done: number;
  uploads_done_live: number;
  error_message: string | null;
  dry_run: boolean;
  updated_at: string;
};

export type VigiaClipIndex = {
  id: number;
  stream_id: string;
  mode: 'live' | 'vod';
  ts_vod_estimated: number;
  clip_start_vod: number;
  clip_end_vod: number;
  session_id: string;
  corte_ref: string | null;
  created_at: string;
};

export type ProfileSource = {
  id: string;
  profile_id: string;
  source_type: string;
  source_ref: string;
  enabled: boolean;
  settings: Record<string, unknown>;
};

export type PlatformAccount = {
  id: string;
  platform: string;
  account_key: string;
  display_name: string | null;
  status: 'not_configured' | 'pending' | 'connected' | 'disconnected' | 'error';
};

export type ProfileDestination = {
  id: string;
  profile_id: string;
  platform: string;
  account_id: string | null;
  enabled: boolean;
  publication_mode: 'disabled' | 'manual' | 'approval' | 'automatic';
  max_posts_per_day: number | null;
  schedule: Record<string, unknown>;
  settings: Record<string, unknown>;
  platform_accounts: PlatformAccount | null;
};

export type ProfileRenderSettings = {
  profile_id: string;
  aspect_ratio: 'original' | '9:16';
  layout: 'original' | 'vertical-fit' | 'vertical-crop';
  min_duration_seconds: number;
  max_duration_seconds: number;
  target_height: number | null;
  captions_enabled: boolean;
  headline_enabled: boolean;
  brand: string | null;
  cta: string | null;
  settings: Record<string, unknown>;
};

export type Profile = {
  profile_id: string;
  name: string;
  description: string | null;
  niche: string | null;
  editorial_strategy: string;
  language: string;
  enabled: boolean;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  profile_sources: ProfileSource[];
  profile_destinations: ProfileDestination[];
  profile_render_settings: ProfileRenderSettings | null;
};
