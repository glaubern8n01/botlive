import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, CheckCircle2, Plus, RefreshCw, Save, ShieldAlert } from 'lucide-react';
import { supabase } from '../lib/supabase';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Input } from '../components/ui/Input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/Table';

const PROFILE = 'kwai_cut_futebol';
const TABS = ['Visão geral', 'Fontes', 'Eventos', 'Vídeos', 'Regras', 'Fila', 'Conta', 'Métricas', 'Erros'] as const;
type Tab = typeof TABS[number];

type Metrics = {
  daily_minimum: number; daily_target: number; generated: number; approved: number;
  rejected: number; queued: number; ready: number; published: number;
};
type Source = {
  source_id: string; name: string; source_type: string; source_ref: string;
  usage_status: string; enabled: boolean; priority: number; status: string;
  last_checked_at: string | null; last_error: string | null; metrics: Record<string, number>;
};
type Activity = {
  activity_id?: string; name: string; min_duration_seconds: number | null;
  max_duration_seconds: number | null; required_hashtags: string[];
  required_terms: string[]; category: string; minimum_quantity: number | null;
  caption_required: boolean; cover_required: boolean; additional_rules: string;
  confirmation_status: 'confirmed' | 'unconfirmed'; active: boolean;
};
type EventRow = { event_id: string; event_type: string; source_ref: string; timestamp_seconds: number; metadata: Record<string, unknown>; created_at: string };
type JobRow = { job_id: string; status: string; title: string | null; caption: string | null; last_error: string | null; created_at: string; scheduled_at: string | null; media_assets: { path: string; duration: number; width: number; height: number; validation_status: string } | null };

const emptyMetrics: Metrics = { daily_minimum: 30, daily_target: 30, generated: 0, approved: 0, rejected: 0, queued: 0, ready: 0, published: 0 };
const emptyActivity: Activity = { name: '', min_duration_seconds: null, max_duration_seconds: null, required_hashtags: [], required_terms: [], category: 'football', minimum_quantity: null, caption_required: true, cover_required: true, additional_rules: '', confirmation_status: 'unconfirmed', active: true };

export function KwaiCut() {
  const [tab, setTab] = useState<Tab>('Visão geral');
  const [metrics, setMetrics] = useState<Metrics>(emptyMetrics);
  const [sources, setSources] = useState<Source[]>([]);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [activity, setActivity] = useState<Activity>(emptyActivity);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [sourceForm, setSourceForm] = useState({ name: '', source_type: 'youtube_channel', source_ref: '', usage_status: 'review_required', priority: 50 });

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    if (!supabase) { setError('Supabase não configurado. A página não inventa métricas.'); setLoading(false); return; }
    const [metricResult, sourceResult, eventResult, jobResult, activityResult] = await Promise.all([
      supabase.from('kwai_cut_daily_metrics').select('*').eq('profile_id', PROFILE).maybeSingle(),
      supabase.from('football_sources').select('*').eq('profile_id', PROFILE).order('priority', { ascending: false }),
      supabase.from('content_events').select('*').eq('profile_id', PROFILE).order('created_at', { ascending: false }).limit(100),
      supabase.from('publication_jobs').select('job_id,status,title,caption,last_error,created_at,scheduled_at,media_assets(path,duration,width,height,validation_status)').eq('profile_id', PROFILE).order('created_at', { ascending: false }).limit(100),
      supabase.from('kwai_cut_activities').select('*').eq('profile_id', PROFILE).eq('active', true).maybeSingle(),
    ]);
    const firstError = [metricResult.error, sourceResult.error, eventResult.error, jobResult.error, activityResult.error].find(Boolean);
    if (firstError) setError('Migration do Kwai CUT ainda não aplicada ou leitura indisponível.');
    if (metricResult.data) setMetrics(metricResult.data as Metrics);
    setSources((sourceResult.data || []) as Source[]);
    setEvents((eventResult.data || []) as EventRow[]);
    setJobs((jobResult.data || []).map((row) => ({ ...row, media_assets: Array.isArray(row.media_assets) ? row.media_assets[0] || null : row.media_assets })) as JobRow[]);
    if (activityResult.data) setActivity(activityResult.data as Activity);
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);

  const deficit = Math.max(0, metrics.daily_target - metrics.approved);
  const lastProcessing = jobs[0]?.created_at;
  const failures = useMemo(() => jobs.filter((job) => job.last_error || ['failed', 'rejected'].includes(job.status)), [jobs]);
  const nextRun = jobs.map((job) => job.scheduled_at).filter((value): value is string => Boolean(value)).sort()[0];

  const addSource = async (event: FormEvent) => {
    event.preventDefault();
    if (!supabase || busy || !sourceForm.name.trim() || !sourceForm.source_ref.trim()) return;
    setBusy(true);
    const result = await supabase.from('football_sources').insert({ ...sourceForm, profile_id: PROFILE, enabled: true });
    if (result.error) setError('Não foi possível cadastrar a fonte.');
    else { setSourceForm({ ...sourceForm, name: '', source_ref: '' }); await load(); }
    setBusy(false);
  };
  const toggleSource = async (source: Source) => {
    if (!supabase || busy) return; setBusy(true);
    const result = await supabase.from('football_sources').update({ enabled: !source.enabled }).eq('source_id', source.source_id);
    if (result.error) setError('Não foi possível atualizar a fonte.'); else await load();
    setBusy(false);
  };
  const saveActivity = async (event: FormEvent) => {
    event.preventDefault(); if (!supabase || busy || !activity.name.trim()) return; setBusy(true);
    const payload = { ...activity, profile_id: PROFILE };
    const result = activity.activity_id
      ? await supabase.from('kwai_cut_activities').update(payload).eq('activity_id', activity.activity_id)
      : await supabase.from('kwai_cut_activities').insert(payload);
    if (result.error) setError('Não foi possível salvar as regras.'); else await load();
    setBusy(false);
  };
  const cancelJob = async (jobId: string) => {
    if (!supabase || busy) return; setBusy(true);
    const result = await supabase.rpc('cancel_publication_job', { p_job_id: jobId });
    if (result.error) setError('Não foi possível cancelar o job.'); else await load();
    setBusy(false);
  };

  return <div className="space-y-6">
    <div className="flex items-start justify-between gap-4">
      <div><h2 className="text-2xl font-bold">Kwai CUT</h2><p className="text-zinc-400">Futebol real · prepare_only · nenhuma postagem externa automática</p></div>
      <Button variant="outline" onClick={load} disabled={loading}><RefreshCw className="mr-2 h-4 w-4" />Atualizar</Button>
    </div>
    {error && <div className="flex gap-2 rounded-lg border border-amber-800 bg-amber-950/30 p-3 text-amber-300"><AlertCircle className="h-5 w-5 shrink-0" />{error}</div>}
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <Metric title="Meta mínima" value={metrics.daily_minimum} />
      <Metric title="Meta desejada" value={metrics.daily_target} />
      <Metric title="Gerados hoje" value={metrics.generated} />
      <Metric title="Aprovados" value={metrics.approved} good />
      <Metric title="Na fila" value={metrics.queued} />
      <Metric title="Prontos para postar" value={metrics.ready} good />
      <Metric title="Publicados" value={metrics.published} />
      <Metric title="Rejeitados" value={metrics.rejected} warn />
      <Metric title="Déficit da meta" value={deficit} warn={deficit > 0} />
      <Card><CardHeader><CardTitle className="text-sm text-zinc-400">Último processamento</CardTitle></CardHeader><CardContent className="text-sm font-semibold">{lastProcessing ? new Date(lastProcessing).toLocaleString() : 'Sem dado real'}</CardContent></Card>
      <Card><CardHeader><CardTitle className="text-sm text-zinc-400">Próxima execução</CardTitle></CardHeader><CardContent className="text-sm font-semibold">{nextRun ? new Date(nextRun).toLocaleString() : 'Não agendada'}</CardContent></Card>
    </div>
    <div className="flex gap-1 overflow-x-auto border-b border-zinc-800">{TABS.map((item) => <button key={item} onClick={() => setTab(item)} className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm ${tab === item ? 'border-orange-400 text-white' : 'border-transparent text-zinc-400'}`}>{item}</button>)}</div>
    {loading ? <div className="py-16 text-center text-zinc-500">Carregando dados reais...</div> : <>
      {tab === 'Visão geral' && <Overview metrics={metrics} sources={sources} events={events} jobs={jobs} deficit={deficit} />}
      {tab === 'Fontes' && <Sources sources={sources} form={sourceForm} setForm={setSourceForm} add={addSource} toggle={toggleSource} busy={busy} />}
      {tab === 'Eventos' && <Events events={events} />}
      {tab === 'Vídeos' && <Jobs jobs={jobs} cancel={cancelJob} busy={busy} videos />}
      {tab === 'Regras' && <Rules activity={activity} setActivity={setActivity} save={saveActivity} busy={busy} />}
      {tab === 'Fila' && <Jobs jobs={jobs} cancel={cancelJob} busy={busy} />}
      {tab === 'Conta' && <Empty icon={<ShieldAlert />} title="Modo prepare_only" text="A conta e a API oficial permanecem pendentes. Credenciais nunca são exibidas nesta tela." />}
      {tab === 'Métricas' && <Overview metrics={metrics} sources={sources} events={events} jobs={jobs} deficit={deficit} />}
      {tab === 'Erros' && <Jobs jobs={failures} cancel={cancelJob} busy={busy} />}
    </>}
  </div>;
}

function Metric({ title, value, good, warn }: { title: string; value: number; good?: boolean; warn?: boolean }) {
  return <Card><CardHeader><CardTitle className="text-sm text-zinc-400">{title}</CardTitle></CardHeader><CardContent className={`text-3xl font-bold ${good ? 'text-emerald-400' : warn ? 'text-amber-400' : ''}`}>{value}</CardContent></Card>;
}
function Overview({ metrics, sources, events, jobs, deficit }: { metrics: Metrics; sources: Source[]; events: EventRow[]; jobs: JobRow[]; deficit: number }) {
  return <div className="grid gap-4 md:grid-cols-3"><Summary title="Operação" lines={[`${sources.filter((s) => s.enabled).length} fontes ativas`, `${events.length} eventos recentes`, `${jobs.length} jobs recentes`]} /><Summary title="Qualidade" lines={[`${metrics.approved} aprovados`, `${metrics.rejected} rejeitados`, `Déficit registrado: ${deficit}`]} /><Summary title="Segurança" lines={['Somente fontes autorizadas', 'Futebol de videogame bloqueado', 'API Kwai desligada']} /></div>;
}
function Summary({ title, lines }: { title: string; lines: string[] }) { return <Card><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent>{lines.map((line) => <div key={line} className="mb-2 flex items-center gap-2 text-sm text-zinc-300"><CheckCircle2 className="h-4 w-4 text-emerald-500" />{line}</div>)}</CardContent></Card>; }
function Sources({ sources, form, setForm, add, toggle, busy }: { sources: Source[]; form: { name: string; source_type: string; source_ref: string; usage_status: string; priority: number }; setForm: (value: typeof form) => void; add: (event: FormEvent) => void; toggle: (source: Source) => void; busy: boolean }) {
  return <div className="space-y-4"><form onSubmit={add} className="grid gap-3 rounded-xl border border-zinc-800 p-4 md:grid-cols-5"><Input placeholder="Nome" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /><Input placeholder="URL ou referência" value={form.source_ref} onChange={(e) => setForm({ ...form, source_ref: e.target.value })} /><Select value={form.source_type} set={(source_type) => setForm({ ...form, source_type })} options={['youtube_channel','youtube_playlist','youtube_search','youtube_live','direct_video','local_file','watched_folder','authorized_feed']} /><Select value={form.usage_status} set={(usage_status) => setForm({ ...form, usage_status })} options={['review_required','authorized','licensed','campaign_allowed','owned','blocked']} /><Button disabled={busy}><Plus className="mr-2 h-4 w-4" />Adicionar</Button></form><Table><TableHeader><TableRow><TableHead>Fonte</TableHead><TableHead>Tipo</TableHead><TableHead>Direitos</TableHead><TableHead>Status</TableHead><TableHead>Última verificação</TableHead><TableHead>Ação</TableHead></TableRow></TableHeader><TableBody>{sources.length ? sources.map((source) => <TableRow key={source.source_id}><TableCell><b>{source.name}</b><div className="max-w-64 truncate text-xs text-zinc-500">{source.source_ref}</div></TableCell><TableCell>{source.source_type}</TableCell><TableCell><Badge variant={['authorized','licensed','campaign_allowed','owned'].includes(source.usage_status) ? 'success' : 'secondary'}>{source.usage_status}</Badge></TableCell><TableCell>{source.status}</TableCell><TableCell>{source.last_checked_at ? new Date(source.last_checked_at).toLocaleString() : 'Nunca'}</TableCell><TableCell><Button variant="outline" disabled={busy} onClick={() => toggle(source)}>{source.enabled ? 'Desativar' : 'Ativar'}</Button></TableCell></TableRow>) : <TableRow><TableCell colSpan={6} className="py-10 text-center text-zinc-500">Nenhuma fonte cadastrada.</TableCell></TableRow>}</TableBody></Table></div>;
}
function Events({ events }: { events: EventRow[] }) { return <Table><TableHeader><TableRow><TableHead>Evento</TableHead><TableHead>Fonte</TableHead><TableHead>Timestamp</TableHead><TableHead>Confiança</TableHead><TableHead>Prioridade / Viral</TableHead></TableRow></TableHeader><TableBody>{events.length ? events.map((event) => <TableRow key={event.event_id}><TableCell>{event.event_type}</TableCell><TableCell className="max-w-64 truncate">{event.source_ref}</TableCell><TableCell>{event.timestamp_seconds.toFixed(1)}s</TableCell><TableCell>{String(event.metadata.confidence ?? '—')}</TableCell><TableCell>{String(event.metadata.viral_score ?? event.metadata.priority_score ?? '—')}</TableCell></TableRow>) : <TableRow><TableCell colSpan={5} className="py-10 text-center text-zinc-500">Nenhum evento encontrado.</TableCell></TableRow>}</TableBody></Table>; }
function Jobs({ jobs, cancel, busy, videos }: { jobs: JobRow[]; cancel: (id: string) => void; busy: boolean; videos?: boolean }) { return <Table><TableHeader><TableRow><TableHead>{videos ? 'Vídeo' : 'Job'}</TableHead><TableHead>Status</TableHead><TableHead>Asset</TableHead><TableHead>Validação</TableHead><TableHead>Erro</TableHead><TableHead>Ação</TableHead></TableRow></TableHeader><TableBody>{jobs.length ? jobs.map((job) => <TableRow key={job.job_id}><TableCell>{job.title || job.job_id.slice(0,8)}<div className="text-xs text-zinc-500">{job.caption || 'Sem caption'}</div></TableCell><TableCell><Badge>{job.status}</Badge></TableCell><TableCell className="max-w-72 truncate">{job.media_assets?.path || '—'}<div className="text-xs text-zinc-500">{job.media_assets ? `${job.media_assets.width}×${job.media_assets.height} · ${job.media_assets.duration}s` : ''}</div></TableCell><TableCell>{job.media_assets?.validation_status || '—'}</TableCell><TableCell className="max-w-48 truncate text-red-400">{job.last_error || '—'}</TableCell><TableCell>{['pending','ready','retry_wait'].includes(job.status) && <Button variant="outline" disabled={busy} onClick={() => cancel(job.job_id)}>Cancelar</Button>}</TableCell></TableRow>) : <TableRow><TableCell colSpan={6} className="py-10 text-center text-zinc-500">Nenhum registro real.</TableCell></TableRow>}</TableBody></Table>; }
function Rules({ activity, setActivity, save, busy }: { activity: Activity; setActivity: (value: Activity) => void; save: (event: FormEvent) => void; busy: boolean }) {
  return <form onSubmit={save} className="grid gap-4 rounded-xl border border-zinc-800 p-5 md:grid-cols-2"><Label text="Nome da atividade"><Input value={activity.name} onChange={(e) => setActivity({ ...activity, name: e.target.value })} /></Label><Label text="Categoria"><Input value={activity.category} onChange={(e) => setActivity({ ...activity, category: e.target.value })} /></Label><Label text="Duração mínima"><Input type="number" value={activity.min_duration_seconds ?? ''} onChange={(e) => setActivity({ ...activity, min_duration_seconds: e.target.value ? Number(e.target.value) : null })} /></Label><Label text="Duração máxima"><Input type="number" value={activity.max_duration_seconds ?? ''} onChange={(e) => setActivity({ ...activity, max_duration_seconds: e.target.value ? Number(e.target.value) : null })} /></Label><Label text="Hashtags obrigatórias"><Input value={activity.required_hashtags.join(', ')} onChange={(e) => setActivity({ ...activity, required_hashtags: e.target.value.split(',').map((v) => v.trim()).filter(Boolean) })} /></Label><Label text="Termos obrigatórios"><Input value={activity.required_terms.join(', ')} onChange={(e) => setActivity({ ...activity, required_terms: e.target.value.split(',').map((v) => v.trim()).filter(Boolean) })} /></Label><Label text="Regras adicionais"><Input value={activity.additional_rules} onChange={(e) => setActivity({ ...activity, additional_rules: e.target.value })} /></Label><Label text="Confirmação"><Select value={activity.confirmation_status} set={(value) => setActivity({ ...activity, confirmation_status: value as Activity['confirmation_status'] })} options={['unconfirmed','confirmed']} /></Label><div className="md:col-span-2 flex justify-end"><Button disabled={busy || !activity.name.trim()}><Save className="mr-2 h-4 w-4" />Salvar regras</Button></div></form>;
}
function Select({ value, set, options }: { value: string; set: (value: string) => void; options: string[] }) { return <select value={value} onChange={(e) => set(e.target.value)} className="h-9 rounded-md border border-zinc-700 bg-zinc-950 px-3 text-sm">{options.map((option) => <option key={option}>{option}</option>)}</select>; }
function Label({ text, children }: { text: string; children: ReactNode }) { return <label className="space-y-1"><span className="text-sm">{text}</span>{children}</label>; }
function Empty({ icon, title, text }: { icon: ReactNode; title: string; text: string }) { return <div className="flex flex-col items-center py-16 text-center text-zinc-400">{icon}<h3 className="mt-3 font-semibold text-white">{title}</h3><p className="mt-1 max-w-lg">{text}</p></div>; }
