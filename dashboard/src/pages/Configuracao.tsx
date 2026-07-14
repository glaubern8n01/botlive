import { useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '../components/ui/Card';
import { Switch } from '../components/ui/Switch';
import { Input } from '../components/ui/Input';
import { Button } from '../components/ui/Button';
import { VigiaConfig } from '../types';
import { ShieldAlert } from 'lucide-react';

// Toggles que ligam comportamento com efeito externo — pedem confirmação.
const CRITICAL_TOGGLES: (keyof VigiaConfig)[] = [
  'enabled',
  'post_youtube_enabled',
  'post_live_enabled',
  'post_instagram_enabled',
];

function NumberField({
  label,
  value,
  onChange,
  min = 0,
  hint,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  hint?: string;
}) {
  return (
    <div className="space-y-1">
      <label className="text-sm font-medium">{label}</label>
      <Input
        type="number"
        min={min}
        value={value}
        onChange={(e) => onChange(parseInt(e.target.value) || min)}
        className="w-32"
      />
      {hint && <p className="text-xs text-zinc-500">{hint}</p>}
    </div>
  );
}

function ToggleRow({
  title,
  description,
  checked,
  onChange,
}: {
  title: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <h4 className="font-medium">{title}</h4>
        <p className="text-sm text-zinc-400">{description}</p>
      </div>
      <Switch checked={checked} onCheckedChange={onChange} />
    </div>
  );
}

export function Configuracao() {
  const [config, setConfig] = useState<VigiaConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    async function fetchConfig() {
      if (!supabase) {
        setError('Supabase não configurado.');
        setLoading(false);
        return;
      }
      try {
        const { data, error } = await supabase.from('vigia_config').select('*').eq('id', 1).single();
        if (error) throw error;
        setConfig(data);
      } catch (err) {
        console.error(err);
        setError('Erro ao carregar configurações.');
      } finally {
        setLoading(false);
      }
    }
    fetchConfig();
  }, []);

  const handleChange = (field: keyof VigiaConfig, value: unknown) => {
    if (!config) return;
    if (CRITICAL_TOGGLES.includes(field) && value === true) {
      const nome =
        field === 'enabled'
          ? 'o VIGIA'
          : field === 'post_live_enabled'
            ? 'a POSTAGEM dos cortes de LIVE (private/rascunho) no YouTube'
            : field === 'post_instagram_enabled'
              ? 'a POSTAGEM de Reels no INSTAGRAM — Reel é sempre PÚBLICO, sem rascunho'
              : 'a POSTAGEM AUTOMÁTICA no YouTube';
      if (!window.confirm(`ATENÇÃO: você está prestes a ligar ${nome}. Confirma?`)) return;
    }
    setConfig({ ...config, [field]: value });
  };

  const handleSave = async () => {
    if (!config || !supabase) return;
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      // Envia só colunas conhecidas do schema (nunca o objeto inteiro cru).
      const { id, updated_at, ...fields } = config;
      const { error } = await supabase
        .from('vigia_config')
        .update({ ...fields, updated_at: new Date().toISOString() })
        .eq('id', 1);
      if (error) throw error;
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err) {
      console.error(err);
      setError('Erro ao salvar configurações.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="text-zinc-400">Carregando...</div>;
  if (error && !config) return <div className="text-red-500">{error}</div>;
  if (!config) return <div className="text-zinc-400">Sem dados.</div>;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Configuração Geral</h2>
        <p className="text-zinc-400">
          Linha única de <code>vigia_config</code>. O vigia relê a config a cada ciclo.
        </p>
      </div>

      <div className="grid gap-6">
        <Card className={config.enabled ? 'border-emerald-500/50' : 'border-red-900/50'}>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldAlert className="w-5 h-5" /> Master Switch
            </CardTitle>
            <CardDescription>
              Liga ou desliga o vigia por completo. Desligado, nenhuma outra configuração importa.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex items-center justify-between">
            <span className="font-medium text-lg">{config.enabled ? 'Vigia ATIVO' : 'Vigia INATIVO'}</span>
            <Switch checked={config.enabled} onCheckedChange={(c) => handleChange('enabled', c)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Descoberta de Lives</CardTitle>
            <CardDescription>Como o vigia encontra canais para processar.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <ToggleRow
              title="Lista manual"
              description="Usa os canais cadastrados na página Canais."
              checked={config.manual_channels_enabled}
              onChange={(c) => handleChange('manual_channels_enabled', c)}
            />
            <ToggleRow
              title="Descoberta aberta"
              description="Busca top canais da categoria por viewers na Twitch."
              checked={config.discovery_enabled}
              onChange={(c) => handleChange('discovery_enabled', c)}
            />
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-1">
                <label className="text-sm font-medium">Categoria (game)</label>
                <Input
                  value={config.discovery_game}
                  onChange={(e) => handleChange('discovery_game', e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium">Idioma</label>
                <Input
                  value={config.discovery_language}
                  onChange={(e) => handleChange('discovery_language', e.target.value)}
                  placeholder="pt (vazio = todos)"
                  className="w-32"
                />
              </div>
              <NumberField
                label="Mínimo de viewers"
                value={config.discovery_min_viewers}
                onChange={(v) => handleChange('discovery_min_viewers', v)}
              />
              <NumberField
                label="Máx. canais descobertos"
                value={config.discovery_max_channels}
                onChange={(v) => handleChange('discovery_max_channels', v)}
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Processamento</CardTitle>
            <CardDescription>Quando e como o robô corta os vídeos.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <ToggleRow
              title="Modo live"
              description="Captura contínua e cortes em tempo quase real durante a live."
              checked={config.live_mode_enabled}
              onChange={(c) => handleChange('live_mode_enabled', c)}
            />
            <ToggleRow
              title="Modo VOD"
              description="Reprocessa o VOD depois que a live termina."
              checked={config.vod_mode_enabled}
              onChange={(c) => handleChange('vod_mode_enabled', c)}
            />
            <div className="grid gap-4 md:grid-cols-3">
              <NumberField
                label="Cortes por live"
                value={config.max_cortes_live}
                onChange={(v) => handleChange('max_cortes_live', v)}
              />
              <NumberField
                label="Cortes por VOD"
                value={config.max_cortes_vod}
                onChange={(v) => handleChange('max_cortes_vod', v)}
              />
              <NumberField
                label="Duração do corte (s)"
                value={config.clip_duration_seconds}
                onChange={(v) => handleChange('clip_duration_seconds', v)}
                min={10}
              />
              <NumberField
                label="Delay do VOD (min)"
                value={config.vod_delay_minutes}
                onChange={(v) => handleChange('vod_delay_minutes', v)}
                hint="Espera após o fim da live"
              />
              <NumberField
                label="Capturas simultâneas"
                value={config.max_concurrent_captures}
                onChange={(v) => handleChange('max_concurrent_captures', v)}
                min={1}
              />
              <NumberField
                label="Renders simultâneos"
                value={config.max_concurrent_renders}
                onChange={(v) => handleChange('max_concurrent_renders', v)}
                min={1}
              />
              <NumberField
                label="Poll do vigia (s)"
                value={config.poll_interval_seconds}
                onChange={(v) => handleChange('poll_interval_seconds', v)}
                min={15}
              />
              <NumberField
                label="Altura alvo (px)"
                value={config.target_height}
                onChange={(v) => handleChange('target_height', v)}
                min={360}
              />
              <div className="space-y-1">
                <label className="text-sm font-medium">Filtro de conteúdo</label>
                <Input
                  value={config.content_filter}
                  onChange={(e) => handleChange('content_filter', e.target.value)}
                  className="w-32"
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Postagem e Limites</CardTitle>
            <CardDescription>Uploads para o YouTube — cuidado com a quota (upload = 1.600 units de 10.000/dia).</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <ToggleRow
              title="Postagem automática no YouTube (VOD)"
              description="Se ativo, posta os cortes do fluxo VOD. Se inativo, apenas gera e guarda no disco."
              checked={config.post_youtube_enabled}
              onChange={(c) => handleChange('post_youtube_enabled', c)}
            />
            <ToggleRow
              title="Postagem dos cortes de LIVE (private)"
              description="Cortes em tempo real sobem como PRIVATE (rascunho no Studio; você publica manualmente). Visibilidade fixa no código."
              checked={config.post_live_enabled ?? false}
              onChange={(c) => handleChange('post_live_enabled', c)}
            />
            <ToggleRow
              title="Reels no Instagram (gatilho: aprovação no YouTube)"
              description="Quando você muda um corte postado para PÚBLICO no Studio, o vigia posta o vertical 9:16 como Reel no ciclo seguinte. Nenhum Reel sai sem essa aprovação manual."
              checked={config.post_instagram_enabled ?? false}
              onChange={(c) => handleChange('post_instagram_enabled', c)}
            />
            <div className="grid gap-4 md:grid-cols-2">
              <NumberField
                label="Teto de uploads/dia (VOD)"
                value={config.max_posts_per_day}
                onChange={(v) => handleChange('max_posts_per_day', v)}
                hint="Teto DURO. Hoje cada corte = 2 uploads (HD + vertical)."
              />
              <NumberField
                label="Teto de uploads/dia (LIVE)"
                value={config.max_posts_per_day_live ?? 2}
                onChange={(v) => handleChange('max_posts_per_day_live', v)}
                hint="Orçamento separado do VOD. Soma dos dois tetos ≤ 6 (quota do YouTube)."
              />
              <div className="space-y-1">
                <label className="text-sm font-medium">Visibilidade</label>
                <select
                  value={config.post_visibilidade}
                  onChange={(e) => handleChange('post_visibilidade', e.target.value)}
                  className="flex h-9 w-40 rounded-md border border-zinc-800 bg-zinc-950 px-3 py-1 text-sm"
                >
                  <option value="private">private</option>
                  <option value="unlisted">unlisted</option>
                  <option value="public">public</option>
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium">Crédito do streamer</label>
                <Input
                  value={config.credito_streamer ?? ''}
                  onChange={(e) => handleChange('credito_streamer', e.target.value || null)}
                  placeholder="(vazio = usa o canal da live)"
                />
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium">Crédito do canal</label>
                <Input
                  value={config.credito_canal ?? ''}
                  onChange={(e) => handleChange('credito_canal', e.target.value || null)}
                />
              </div>
            </div>
          </CardContent>
          <CardFooter className="flex justify-end gap-4 border-t border-zinc-800 pt-6">
            {error && <span className="text-red-500 text-sm">{error}</span>}
            {success && <span className="text-emerald-500 text-sm">Salvo com sucesso!</span>}
            <Button onClick={handleSave} disabled={saving}>
              {saving ? 'Salvando...' : 'Salvar Configurações'}
            </Button>
          </CardFooter>
        </Card>
      </div>
    </div>
  );
}
