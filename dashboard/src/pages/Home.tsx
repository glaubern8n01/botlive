import { useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Activity, ShieldAlert, CheckCircle2, Radio } from 'lucide-react';
import { VigiaConfig } from '../types';

type Stats = {
  activeChannels: number;
  livesToday: number;
  capturesRunning: number;
  uploadsToday: number;
};

export function Home() {
  const [config, setConfig] = useState<VigiaConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<Stats>({
    activeChannels: 0,
    livesToday: 0,
    capturesRunning: 0,
    uploadsToday: 0,
  });

  useEffect(() => {
    async function fetchData() {
      if (!supabase) {
        setError('Supabase não configurado (VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY).');
        setLoading(false);
        return;
      }

      try {
        const { data: configData, error: configError } = await supabase
          .from('vigia_config')
          .select('*')
          .eq('id', 1)
          .single();
        if (configError) throw configError;
        setConfig(configData);

        const { count: channelsCount, error: channelsError } = await supabase
          .from('vigia_channels')
          .select('*', { count: 'exact', head: true })
          .eq('enabled', true);
        if (channelsError) throw channelsError;

        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const todayIso = today.toISOString();

        const { count: livesCount, error: livesError } = await supabase
          .from('vigia_streams')
          .select('*', { count: 'exact', head: true })
          .gte('detected_at', todayIso);
        if (livesError) throw livesError;

        const { count: runningCount, error: runningError } = await supabase
          .from('vigia_streams')
          .select('*', { count: 'exact', head: true })
          .eq('live_job_status', 'running');
        if (runningError) throw runningError;

        // Estimativa: uploads_done acumula por transmissão; somamos as
        // transmissões tocadas hoje. Não é contador diário exato.
        const { data: uploadsRows, error: uploadsError } = await supabase
          .from('vigia_streams')
          .select('uploads_done')
          .gte('updated_at', todayIso);
        if (uploadsError) throw uploadsError;
        const uploadsToday = (uploadsRows || []).reduce(
          (acc, row) => acc + (row.uploads_done || 0),
          0,
        );

        setStats({
          activeChannels: channelsCount || 0,
          livesToday: livesCount || 0,
          capturesRunning: runningCount || 0,
          uploadsToday,
        });
      } catch (err) {
        console.error(err);
        setError('Erro ao carregar dados do painel.');
      } finally {
        setLoading(false);
      }
    }

    fetchData();
  }, []);

  if (loading) return <div className="text-zinc-400">Carregando painel...</div>;
  if (error) return <div className="text-red-500">{error}</div>;
  if (!config) return <div className="text-zinc-400">Nenhuma configuração encontrada.</div>;

  const isSystemActive = config.enabled;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Painel de Controle</h2>
        <p className="text-zinc-400">Visão geral do vigia automático de cortes.</p>
      </div>

      <Card className={`border-l-4 ${isSystemActive ? 'border-l-emerald-500 bg-emerald-500/10' : 'border-l-zinc-600 bg-zinc-900'}`}>
        <CardContent className="p-6 flex items-center justify-between">
          <div className="flex items-center gap-4">
            {isSystemActive ? (
              <Activity className="w-8 h-8 text-emerald-500" />
            ) : (
              <ShieldAlert className="w-8 h-8 text-zinc-500" />
            )}
            <div>
              <h3 className="text-lg font-semibold flex items-center gap-2">
                Status do Vigia
                {isSystemActive ? (
                  <Badge variant="success">LIGADO</Badge>
                ) : (
                  <Badge variant="secondary">DESLIGADO</Badge>
                )}
              </h3>
              <p className="text-sm text-zinc-400 mt-1">
                {isSystemActive
                  ? 'O vigia está monitorando canais e disparando jobs.'
                  : 'O vigia está desativado. Nenhuma ação será tomada.'}
              </p>
            </div>
          </div>
          {stats.capturesRunning > 0 && (
            <div className="flex items-center gap-2 text-red-400">
              <Radio className="w-5 h-5 animate-pulse" />
              <span className="font-semibold">{stats.capturesRunning} captura(s) ao vivo</span>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-zinc-400">Postagem no YouTube</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold flex items-center gap-2">
              {config.post_youtube_enabled ? (
                <span className="text-emerald-500 flex items-center gap-2">
                  Ativa <CheckCircle2 className="w-5 h-5" />
                </span>
              ) : (
                <span className="text-amber-500">Pausada</span>
              )}
            </div>
            <p className="text-xs text-zinc-500 mt-1">
              Teto diário: {config.max_posts_per_day} uploads ({config.post_visibilidade})
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-zinc-400">Canais Ativos</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.activeChannels}</div>
            <p className="text-xs text-zinc-500 mt-1">
              {config.manual_channels_enabled ? 'Lista manual ativa' : 'Lista manual inativa'}
              {config.discovery_enabled ? ' · descoberta aberta ativa' : ''}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-zinc-400">Lives Hoje</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.livesToday}</div>
            <p className="text-xs text-zinc-500 mt-1">Transmissões detectadas desde 00:00</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-zinc-400">Uploads Hoje (estimativa)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {stats.uploadsToday}{' '}
              <span className="text-zinc-500 text-sm font-normal">/ {config.max_posts_per_day}</span>
            </div>
            <div className="w-full bg-zinc-800 rounded-full h-1.5 mt-3">
              <div
                className={`h-1.5 rounded-full ${stats.uploadsToday >= config.max_posts_per_day ? 'bg-red-500' : 'bg-blue-500'}`}
                style={{
                  width: `${Math.min(100, (stats.uploadsToday / Math.max(1, config.max_posts_per_day)) * 100)}%`,
                }}
              ></div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
