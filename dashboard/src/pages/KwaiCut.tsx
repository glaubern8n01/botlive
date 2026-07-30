import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, CheckCircle2, Copy, Download, HelpCircle, Plus, RefreshCw, Save, ShieldAlert, Smartphone } from 'lucide-react';
import { supabase } from '../lib/supabase';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Input } from '../components/ui/Input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/Table';

const PROFILE = 'kwai_cut_futebol';
const TABS = ['Visão geral', 'Publicar pelo celular', 'Fontes', 'Eventos', 'Vídeos', 'Regras', 'Fila', 'Conta', 'Métricas', 'Erros'] as const;
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
  confirmed_at?: string | null; notes?: string | null;
};
type EventRow = { event_id: string; event_type: string; source_ref: string; timestamp_seconds: number; metadata: Record<string, unknown>; created_at: string };
type JobRow = {
  job_id: string; asset_id: string; status: string; title: string | null; caption: string | null;
  cover_path: string | null; external_id: string | null; published_at: string | null;
  last_error: string | null; created_at: string; scheduled_at: string | null;
  metadata: Record<string, unknown>;
  media_assets: { asset_id: string; path: string; duration: number; width: number; height: number; validation_status: string } | null;
  content_events: { event_type: string; metadata: Record<string, unknown> } | null;
  editorial_variants: { variant_signature: string; editorial_metadata: Record<string, unknown> } | null;
};
type Account = {
  display_name: string | null; public_username: string | null; public_profile_url: string | null;
  creator_status: string | null; agency: string | null; contracted_at: string | null;
  contract_month: string | null; confirmed_niche: string | null; publication_mode: string | null;
  status: string;
};

const emptyMetrics: Metrics = { daily_minimum: 30, daily_target: 30, generated: 0, approved: 0, rejected: 0, queued: 0, ready: 0, published: 0 };
const emptyActivity: Activity = { name: '', min_duration_seconds: null, max_duration_seconds: null, required_hashtags: [], required_terms: [], category: 'football', minimum_quantity: null, caption_required: true, cover_required: true, additional_rules: '', confirmation_status: 'unconfirmed', active: true };

export function KwaiCut() {
  const [tab, setTab] = useState<Tab>('Visão geral');
  const [metrics, setMetrics] = useState<Metrics>(emptyMetrics);
  const [sources, setSources] = useState<Source[]>([]);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [activity, setActivity] = useState<Activity>(emptyActivity);
  const [account, setAccount] = useState<Account | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [sourceForm, setSourceForm] = useState({ name: '', source_type: 'youtube_channel', source_ref: '', usage_status: 'review_required', priority: 50 });

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    if (!supabase) { setError('Supabase não configurado. A página não inventa métricas.'); setLoading(false); return; }
    const [metricResult, sourceResult, eventResult, jobResult, activityResult, accountResult] = await Promise.all([
      supabase.from('kwai_cut_daily_metrics').select('*').eq('profile_id', PROFILE).maybeSingle(),
      supabase.from('football_sources').select('*').eq('profile_id', PROFILE).order('priority', { ascending: false }),
      supabase.from('content_events').select('*').eq('profile_id', PROFILE).order('created_at', { ascending: false }).limit(100),
      supabase.from('publication_jobs').select('job_id,asset_id,status,title,caption,cover_path,external_id,published_at,last_error,created_at,scheduled_at,metadata,media_assets(asset_id,path,duration,width,height,validation_status),content_events(event_type,metadata),editorial_variants(variant_signature,editorial_metadata)').eq('profile_id', PROFILE).order('created_at', { ascending: false }).limit(100),
      supabase.from('kwai_cut_activities').select('*').eq('profile_id', PROFILE).eq('active', true).maybeSingle(),
      supabase.from('platform_accounts_safe').select('display_name,public_username,public_profile_url,creator_status,agency,contracted_at,contract_month,confirmed_niche,publication_mode,status').eq('platform', 'kwai').eq('account_key', 'principal').maybeSingle(),
    ]);
    const firstError = [metricResult.error, sourceResult.error, eventResult.error, jobResult.error, activityResult.error, accountResult.error].find(Boolean);
    if (firstError) setError('Migration do Kwai CUT ainda não aplicada ou leitura indisponível.');
    if (metricResult.data) setMetrics(metricResult.data as Metrics);
    setSources((sourceResult.data || []) as Source[]);
    setEvents((eventResult.data || []) as EventRow[]);
    setJobs((jobResult.data || []).map((row) => ({
      ...row,
      media_assets: Array.isArray(row.media_assets) ? row.media_assets[0] || null : row.media_assets,
      content_events: Array.isArray(row.content_events) ? row.content_events[0] || null : row.content_events,
      editorial_variants: Array.isArray(row.editorial_variants) ? row.editorial_variants[0] || null : row.editorial_variants,
    })) as JobRow[]);
    if (activityResult.data) setActivity(activityResult.data as Activity);
    if (accountResult.data) setAccount(accountResult.data as Account);
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
  const markPublished = async (jobId: string, assetId: string, externalId: string, publishedAt: string) => {
    if (!supabase || busy) return false;
    setBusy(true); setError(null);
    const result = await supabase.rpc('mark_manual_publication', {
      p_job_id: jobId,
      p_external_id: externalId,
      p_published_at: new Date(publishedAt).toISOString(),
    });
    if (result.error) {
      setError(result.error.message || 'Não foi possível registrar a publicação manual.');
      setBusy(false);
      return false;
    }
    const cleanup = await fetch(`/api/assets/${assetId}/cleanup`, { method: 'POST' });
    if (!cleanup.ok) {
      setError('Publicação registrada, mas não foi possível liberar os arquivos da VPS. Tente novamente mais tarde.');
    }
    await load();
    setBusy(false);
    return true;
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
      {tab === 'Publicar pelo celular' && <ManualPublishing jobs={jobs} activity={activity} markPublished={markPublished} busy={busy} />}
      {tab === 'Fontes' && <Sources sources={sources} form={sourceForm} setForm={setSourceForm} add={addSource} toggle={toggleSource} busy={busy} />}
      {tab === 'Eventos' && <Events events={events} />}
      {tab === 'Vídeos' && <Jobs jobs={jobs} cancel={cancelJob} busy={busy} videos />}
      {tab === 'Regras' && <Rules activity={activity} setActivity={setActivity} save={saveActivity} busy={busy} />}
      {tab === 'Fila' && <Jobs jobs={jobs} cancel={cancelJob} busy={busy} />}
      {tab === 'Conta' && <AccountPanel account={account} />}
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

function AccountPanel({ account }: { account: Account | null }) {
  if (!account) return <Empty icon={<ShieldAlert />} title="Conta aguardando sincronização" text="Nenhuma credencial é exibida ou armazenada nesta tela." />;
  return <div className="grid gap-4 md:grid-cols-2">
    <Summary title="Conta CUT confirmada" lines={[
      account.display_name || 'Nome não informado',
      `@${account.public_username || 'usuário não informado'}`,
      account.creator_status || account.status,
      `Agência: ${account.agency || 'não informada'}`,
    ]} />
    <Summary title="Operação segura" lines={[
      `Contratação: ${account.contracted_at || 'não informada'} · mês ${account.contract_month || '—'}`,
      `Nicho: ${account.confirmed_niche || 'aguardando confirmação'}`,
      'Publicação manual pelo aplicativo',
      'API oficial desligada · prepare_only',
    ]} />
    {account.public_profile_url && <a className="text-sm text-orange-300 underline md:col-span-2" href={account.public_profile_url} target="_blank" rel="noreferrer">Abrir perfil público</a>}
  </div>;
}

function ManualPublishing({ jobs, activity, markPublished, busy }: {
  jobs: JobRow[];
  activity: Activity;
  markPublished: (jobId: string, assetId: string, externalId: string, publishedAt: string) => Promise<boolean>;
  busy: boolean;
}) {
  const readyJobs = jobs.filter((job) => job.status === 'ready' && job.media_assets?.validation_status === 'valid');
  return <div className="space-y-5">
    <details className="rounded-xl border border-orange-800 bg-orange-950/20 p-4">
      <summary className="flex cursor-pointer items-center gap-2 font-semibold"><HelpCircle className="h-5 w-5" />Como publicar</summary>
      <ol className="mt-4 list-decimal space-y-2 pl-6 text-sm text-zinc-300">
        <li>Baixe o vídeo.</li><li>Abra o aplicativo Kwai.</li><li>Toque no botão +.</li>
        <li>Escolha Álbum.</li><li>Selecione o vídeo baixado.</li><li>Escolha a capa.</li>
        <li>Cole a legenda e as hashtags.</li><li>Toque em Compartilhar.</li>
        <li>Volte ao dashboard e registre a publicação.</li>
      </ol>
    </details>
    <div className="flex items-center gap-2 text-sm text-zinc-400"><Smartphone className="h-5 w-5 text-orange-400" />Arquivos protegidos pelo mesmo acesso do dashboard. Nenhuma sessão do Kwai é usada.</div>
    {readyJobs.length ? <div className="grid gap-5 xl:grid-cols-2">
      {readyJobs.map((job, index) => <div key={job.job_id}><ManualVideoCard job={job} index={index} activity={activity} markPublished={markPublished} busy={busy} /></div>)}
    </div> : <Empty icon={<Smartphone />} title="Nenhum vídeo pronto" text="Os vídeos aparecerão aqui após geração e validação em prepare_only." />}
  </div>;
}

function ManualVideoCard({ job, index, activity, markPublished, busy }: {
  job: JobRow; index: number; activity: Activity;
  markPublished: (jobId: string, assetId: string, externalId: string, publishedAt: string) => Promise<boolean>;
  busy: boolean;
}) {
  const [externalId, setExternalId] = useState(job.external_id || '');
  const [publishedAt, setPublishedAt] = useState(job.published_at ? toLocalInput(job.published_at) : toLocalInput(new Date().toISOString()));
  const created = new Date(job.created_at);
  const date = `${created.getFullYear()}${String(created.getMonth() + 1).padStart(2, '0')}${String(created.getDate()).padStart(2, '0')}`;
  const slug = String(job.content_events?.event_type || 'lance').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'lance';
  const filename = `kwai-futebol-${slug}-${date}-${String(index + 1).padStart(3, '0')}.mp4`;
  const coverName = filename.replace(/\.mp4$/, '-capa.jpg');
  const videoUrl = `/api/assets/${job.asset_id}/video?name=${encodeURIComponent(filename)}`;
  const coverUrl = `/api/assets/${job.asset_id}/cover?name=${encodeURIComponent(coverName)}`;
  const hashtags = activity.required_hashtags.join(' ');
  const caption = job.caption || '';
  const allText = [job.title, caption, hashtags].filter(Boolean).join('\n');
  const published = job.status === 'published';
  const variant = job.editorial_variants?.variant_signature || 'CUT vertical';
  const event = job.content_events?.event_type || 'Evento de futebol';

  return <Card className={published ? 'border-emerald-800' : 'border-zinc-700'}>
    <div className="aspect-video overflow-hidden rounded-t-xl bg-black">
      <video className="h-full w-full object-contain" controls preload="metadata" poster={job.cover_path ? coverUrl : undefined}>
        <source src={videoUrl} type="video/mp4" />
      </video>
    </div>
    <CardHeader className="pb-3">
      <div className="flex items-start justify-between gap-3"><CardTitle className="leading-snug">{job.title || filename}</CardTitle><Badge variant={published ? 'success' : 'secondary'}>{published ? 'publicado' : 'pronto para postagem manual'}</Badge></div>
    </CardHeader>
    <CardContent className="space-y-4">
      <div className="grid grid-cols-2 gap-2 text-xs text-zinc-400">
        <span>Duração: <b className="text-zinc-200">{job.media_assets?.duration.toFixed(1)}s</b></span>
        <span>Formato: <b className="text-zinc-200">{job.media_assets?.width}×{job.media_assets?.height}</b></span>
        <span>Evento: <b className="text-zinc-200">{event}</b></span>
        <span>Variante: <b className="text-zinc-200">{variant}</b></span>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <a className="inline-flex h-9 items-center justify-center rounded-md bg-zinc-50 px-3 text-sm font-medium text-zinc-900" href={`${videoUrl}&download=1`} download={filename}><Download className="mr-2 h-4 w-4" />Baixar vídeo</a>
        <a className={`inline-flex h-9 items-center justify-center rounded-md border border-zinc-700 px-3 text-sm ${job.cover_path ? '' : 'pointer-events-none opacity-40'}`} href={`${coverUrl}&download=1`} download={coverName}><Download className="mr-2 h-4 w-4" />Baixar capa</a>
        <CopyButton label="Copiar legenda" value={caption} />
        <CopyButton label="Copiar hashtags" value={hashtags} />
        <div className="sm:col-span-2"><CopyButton label="Copiar tudo" value={allText} wide /></div>
      </div>
      <div className="rounded-lg border border-zinc-800 p-3">
        <p className="mb-3 text-sm font-semibold">Registrar publicação manual</p>
        <div className="space-y-2">
          <Input aria-label="URL ou ID da publicação" placeholder="URL ou ID da publicação" value={externalId} onChange={(event) => setExternalId(event.target.value)} disabled={published} />
          <Input aria-label="Horário da publicação" type="datetime-local" value={publishedAt} onChange={(event) => setPublishedAt(event.target.value)} disabled={published} />
          <Button className="w-full" disabled={busy || published || !externalId.trim() || !publishedAt} onClick={() => {
            if (window.confirm('Confirmar publicação? O MP4 e a capa serão removidos da VPS para liberar espaço. O registro permanecerá no histórico.')) {
              void markPublished(job.job_id, job.asset_id, externalId, publishedAt);
            }
          }}>
            <CheckCircle2 className="mr-2 h-4 w-4" />{published ? 'Publicação registrada' : 'Marcar como publicado'}
          </Button>
        </div>
      </div>
    </CardContent>
  </Card>;
}

function CopyButton({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };
  return <Button type="button" className={wide ? 'w-full' : ''} variant="outline" disabled={!value} onClick={copy}><Copy className="mr-2 h-4 w-4" />{copied ? 'Copiado' : label}</Button>;
}

function toLocalInput(value: string) {
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function Rules({ activity, setActivity, save, busy }: { activity: Activity; setActivity: (value: Activity) => void; save: (event: FormEvent) => void; busy: boolean }) {
  return <form onSubmit={save} className="grid gap-4 rounded-xl border border-zinc-800 p-5 md:grid-cols-2"><Label text="Nome da atividade"><Input value={activity.name} onChange={(e) => setActivity({ ...activity, name: e.target.value })} /></Label><Label text="Categoria"><Input value={activity.category} onChange={(e) => setActivity({ ...activity, category: e.target.value })} /></Label><Label text="Duração mínima"><Input type="number" value={activity.min_duration_seconds ?? ''} onChange={(e) => setActivity({ ...activity, min_duration_seconds: e.target.value ? Number(e.target.value) : null })} /></Label><Label text="Duração máxima"><Input type="number" value={activity.max_duration_seconds ?? ''} onChange={(e) => setActivity({ ...activity, max_duration_seconds: e.target.value ? Number(e.target.value) : null })} /></Label><Label text="Hashtags obrigatórias"><Input value={activity.required_hashtags.join(', ')} onChange={(e) => setActivity({ ...activity, required_hashtags: e.target.value.split(',').map((v) => v.trim()).filter(Boolean) })} /></Label><Label text="Termos obrigatórios"><Input value={activity.required_terms.join(', ')} onChange={(e) => setActivity({ ...activity, required_terms: e.target.value.split(',').map((v) => v.trim()).filter(Boolean) })} /></Label><Label text="Regras adicionais"><Input value={activity.additional_rules} onChange={(e) => setActivity({ ...activity, additional_rules: e.target.value })} /></Label><Label text="Confirmação"><Select value={activity.confirmation_status} set={(value) => setActivity({ ...activity, confirmation_status: value as Activity['confirmation_status'] })} options={['unconfirmed','confirmed']} /></Label><div className="md:col-span-2 flex justify-end"><Button disabled={busy || !activity.name.trim()}><Save className="mr-2 h-4 w-4" />Salvar regras</Button></div></form>;
}
function Select({ value, set, options }: { value: string; set: (value: string) => void; options: string[] }) { return <select value={value} onChange={(e) => set(e.target.value)} className="h-9 rounded-md border border-zinc-700 bg-zinc-950 px-3 text-sm">{options.map((option) => <option key={option}>{option}</option>)}</select>; }
function Label({ text, children }: { text: string; children: ReactNode }) { return <label className="space-y-1"><span className="text-sm">{text}</span>{children}</label>; }
function Empty({ icon, title, text }: { icon: ReactNode; title: string; text: string }) { return <div className="flex flex-col items-center py-16 text-center text-zinc-400">{icon}<h3 className="mt-3 font-semibold text-white">{title}</h3><p className="mt-1 max-w-lg">{text}</p></div>; }
