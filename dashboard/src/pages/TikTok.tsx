import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, CheckCircle2, Copy, RefreshCw, Save, ShieldCheck } from 'lucide-react';
import { supabase } from '../lib/supabase';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';

const PROFILE_IDS = ['gta6_cortes', 'gta6'];
const TABS = ['Visão geral', 'Conta', 'Vídeos', 'Fila', 'API', 'Configuração', 'Métricas', 'Erros'] as const;
type Tab = typeof TABS[number];

type Connection = {
  nickname: string | null;
  granted_scopes: string[];
  token_expires_at: string | null;
  review_status: string;
  connection_status: string;
  creator_info: Record<string, unknown>;
  secret_configured: boolean;
};
type Account = { display_name: string | null; account_key: string; status: string; secret_configured: boolean };
type Job = {
  job_id: string; status: string; title: string | null; caption: string | null;
  external_id: string | null; remote_status: string | null; last_error: string | null;
  created_at: string; published_at: string | null; metadata: Record<string, unknown>;
};
type GtaMetrics = { generated: number; youtube_published: number; instagram_published: number; tiktok_drafts: number; tiktok_published_manual: number; failures: number; next_scheduled_at: string | null };

export function TikTok() {
  const [tab, setTab] = useState<Tab>('Visão geral');
  const [account, setAccount] = useState<Account | null>(null);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [metrics, setMetrics] = useState<GtaMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const authBase = import.meta.env.VITE_TIKTOK_AUTH_BASE_URL || '';
  const apiEnabled = import.meta.env.VITE_TIKTOK_STANDARD_API_ENABLED === '1';
  const draftEnabled = apiEnabled && import.meta.env.VITE_TIKTOK_STANDARD_UPLOAD_DRAFT_ENABLED === '1';
  const directEnabled = apiEnabled && import.meta.env.VITE_TIKTOK_STANDARD_DIRECT_POST_ENABLED === '1'
    && connection?.review_status === 'approved';

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    if (!supabase) { setError('Supabase não configurado; nenhum dado foi inventado.'); setLoading(false); return; }
    const [accountResult, connectionResult, jobsResult, metricsResult] = await Promise.all([
      supabase.from('platform_accounts_safe').select('display_name,account_key,status,secret_configured')
        .eq('platform', 'tiktok_standard').eq('account_key', 'gta6brasilcortes').maybeSingle(),
      supabase.from('tiktok_standard_connections_safe').select('*').maybeSingle(),
      supabase.from('publication_jobs').select('job_id,status,title,caption,external_id,remote_status,last_error,created_at,published_at,metadata')
        .eq('platform', 'tiktok_standard').in('profile_id', PROFILE_IDS).order('created_at', { ascending: false }).limit(100),
      supabase.from('gta_daily_metrics').select('*').maybeSingle(),
    ]);
    if (accountResult.error || connectionResult.error || jobsResult.error) {
      setError('A migration TikTok Standard ainda não foi aplicada ou a leitura está indisponível.');
    }
    setAccount(accountResult.data as Account | null);
    setConnection(connectionResult.data as Connection | null);
    setJobs((jobsResult.data || []) as Job[]);
    setMetrics(metricsResult.data as GtaMetrics | null);
    setLoading(false);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const prepared = jobs.filter((job) => ['pending', 'ready'].includes(job.status)).length;
  const drafts = jobs.filter((job) => ['draft_available','sent_to_user_inbox'].includes(job.status)).length;
  const published = jobs.filter((job) => ['published','published_manual'].includes(job.status)).length;
  const failures = jobs.filter((job) => job.last_error || ['failed', 'rejected'].includes(job.status));
  const lastPublished = jobs.find((job) => job.published_at)?.published_at;
  const scoped = useMemo(() => new Set(connection?.granted_scopes || []), [connection]);

  return <div className="space-y-6">
    <div className="flex items-start justify-between gap-4">
      <div><h2 className="text-2xl font-bold">TikTok normal — GTA6 Brasil Cortes</h2>
        <p className="text-zinc-400">Destino independente · prepare_only · TikTok Shop desligado</p></div>
      <Button variant="outline" onClick={() => void load()} disabled={loading}><RefreshCw className="mr-2 h-4 w-4" />Atualizar</Button>
    </div>
    {error && <div className="flex gap-2 rounded-lg border border-amber-800 bg-amber-950/30 p-3 text-amber-300">
      <AlertCircle className="h-5 w-5 shrink-0" />{error}</div>}
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Metric title="Conta" value={connection?.connection_status || account?.status || 'não configurada'} />
      <Metric title="@handle" value={`@${connection?.nickname || account?.account_key || 'gta6brasilcortes'}`} />
      <Metric title="Modo" value="prepare_only" />
      <Metric title="App review" value={connection?.review_status || 'não configurado'} />
      <Metric title="Token válido" value={tokenValid(connection) ? 'sim' : 'não'} />
      <Metric title="Vídeos preparados" value={String(prepared)} />
      <Metric title="Rascunhos enviados" value={String(drafts)} />
      <Metric title="Publicados" value={String(published)} />
      <Metric title="Falhas" value={String(failures.length)} />
      <Metric title="Meta GTA" value="8 / dia · máx. 12" />
      <Metric title="Última publicação" value={lastPublished ? new Date(lastPublished).toLocaleString() : 'nenhuma'} />
    </div>
    <div className="flex gap-1 overflow-x-auto border-b border-zinc-800">{TABS.map((item) =>
      <button key={item} onClick={() => setTab(item)} className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm ${
        tab === item ? 'border-cyan-400 text-white' : 'border-transparent text-zinc-400'}`}>{item}</button>)}</div>
    {loading ? <div className="py-16 text-center text-zinc-500">Carregando dados reais...</div> :
      <section className="space-y-4">
        {tab === 'Visão geral' && <div className="grid gap-4 md:grid-cols-3">
          <Panel title="Segurança" lines={['Master limpo, sem marca de plataforma', 'Falha não bloqueia YouTube ou Instagram', 'Nenhuma chamada em prepare_only']} />
          <Panel title="Separação" lines={['platform: tiktok_standard', 'Destino: tiktok_standard_gta6', 'TikTok Shop sem conta, token ou jobs']} />
          <Panel title="Direitos" lines={['owned/authorized/licensed podem avançar', 'review_required exige aprovação', 'blocked nunca avança']} />
        </div>}
        {tab === 'Conta' && <Card><CardHeader><CardTitle>Conexão oficial Login Kit</CardTitle></CardHeader><CardContent className="space-y-3">
          <p>Conta: <b>{connection?.nickname ? `@${connection.nickname}` : '@gta6brasilcortes (aguardando OAuth)'}</b></p>
          <p>Escopos concedidos: {connection?.granted_scopes?.join(', ') || 'nenhum'}</p>
          <div className="flex flex-wrap gap-2">
            {authBase && <a className="inline-flex h-9 items-center rounded-md bg-white px-4 text-sm font-medium text-zinc-900"
              href={`${authBase}/tiktok/connect`}>Conectar TikTok</a>}
            <Button variant="outline" disabled={!connection}>Reconectar</Button>
            {authBase && connection && <a className="inline-flex h-9 items-center rounded-md border border-zinc-800 px-4 text-sm"
              href={`${authBase}/tiktok/disconnect`}>Desconectar</a>}
            <Button variant="outline" disabled={!connection}>Testar conexão</Button>
          </div>
        </CardContent></Card>}
        {tab === 'Vídeos' && <Jobs jobs={jobs} empty="Nenhuma variante TikTok preparada." refresh={load} />}
        {tab === 'Fila' && <Jobs jobs={jobs.filter((job) => !['published','published_manual'].includes(job.status))} empty="Fila vazia." refresh={load} />}
        {tab === 'Erros' && <Jobs jobs={failures} empty="Nenhum erro registrado." refresh={load} />}
        {tab === 'API' && <Card><CardHeader><CardTitle>Produtos e escopos</CardTitle></CardHeader><CardContent className="space-y-3">
          <Scope name="user.info.basic" available={scoped.has('user.info.basic')} />
          <Scope name="video.upload" available={scoped.has('video.upload')} />
          <Scope name="video.publish" available={scoped.has('video.publish')} />
          <p className="text-sm text-zinc-400">API geral: {apiEnabled ? 'habilitada' : 'desligada'} ·
            upload draft: {draftEnabled ? 'habilitado' : 'desligado'} · direct post: {directEnabled ? 'habilitado' : 'desligado'}</p>
        </CardContent></Card>}
        {tab === 'Configuração' && <Panel title="Flags efetivas" lines={[
          'TIKTOK_STANDARD_ENABLED=1', `TIKTOK_STANDARD_API_ENABLED=${apiEnabled ? 1 : 0}`,
          `TIKTOK_STANDARD_UPLOAD_DRAFT_ENABLED=${draftEnabled ? 1 : 0}`,
          `TIKTOK_STANDARD_DIRECT_POST_ENABLED=${directEnabled ? 1 : 0}`,
          'TIKTOK_SHOP_ENABLED=0', 'TIKTOK_SHOP_API_ENABLED=0',
        ]} />}
        {tab === 'Métricas' && <Panel title="Métricas reais" lines={[
          `${metrics?.generated ?? 0} gerados hoje`, `${metrics?.youtube_published ?? 0} YouTube publicados`,
          `${metrics?.instagram_published ?? 0} Instagram publicados`, `${metrics?.tiktok_drafts ?? drafts} rascunhos TikTok`,
          `${metrics?.tiktok_published_manual ?? 0} TikTok publicados manualmente`, `${metrics?.failures ?? failures.length} falhas`,
          `Próximo horário: ${metrics?.next_scheduled_at ? new Date(metrics.next_scheduled_at).toLocaleString() : 'aguardando job'}`,
        ]} />}
      </section>}
  </div>;
}

function tokenValid(connection: Connection | null) {
  return Boolean(connection?.token_expires_at && new Date(connection.token_expires_at).getTime() > Date.now());
}
function Metric({ title, value }: { title: string; value: string }) {
  return <Card><CardHeader><CardTitle className="text-sm text-zinc-400">{title}</CardTitle></CardHeader>
    <CardContent className="text-lg font-bold break-words">{value}</CardContent></Card>;
}
function Panel({ title, lines }: { title: string; lines: string[] }) {
  return <Card><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent>{lines.map((line) =>
    <div key={line} className="mb-2 flex gap-2 text-sm text-zinc-300"><ShieldCheck className="h-4 w-4 shrink-0 text-emerald-500" />{line}</div>)}</CardContent></Card>;
}
function Scope({ name, available }: { name: string; available: boolean }) {
  return <div className="flex items-center justify-between rounded-lg border border-zinc-800 p-3"><code>{name}</code>
    <Badge variant={available ? 'success' : 'secondary'}>{available ? 'concedido' : 'não configurado'}</Badge></div>;
}
function Jobs({ jobs, empty, refresh }: { jobs: Job[]; empty: string; refresh: () => Promise<void> }) {
  if (!jobs.length) return <p className="py-12 text-center text-zinc-500">{empty}</p>;
  return <div className="space-y-3">{jobs.map((job) => <TikTokJob key={job.job_id} job={job} refresh={refresh} />)}</div>;
}

function TikTokJob({ job, refresh }: { job: Job; refresh: () => Promise<void> }) {
  const [description, setDescription] = useState(String(job.metadata?.description || job.caption || ''));
  const [hashtags, setHashtags] = useState(String(job.metadata?.hashtags || ''));
  const [credits, setCredits] = useState(String(job.metadata?.credits || ''));
  const [externalId, setExternalId] = useState('');
  const editable = ['pending','ready','draft_available','sent_to_user_inbox'].includes(job.status);
  const text = [description, credits, hashtags].filter(Boolean).join('\n\n');
  return <Card><CardContent className="space-y-3 pt-6">
    <div className="flex items-start justify-between gap-3"><div><b>{job.title || job.job_id.slice(0, 8)}</b><p className="text-xs text-zinc-500">{text.length} caracteres</p></div><Badge>{job.remote_status || job.status}</Badge></div>
    <textarea className="min-h-20 w-full rounded-md border border-zinc-700 bg-zinc-950 p-2 text-sm" value={description} onChange={(e) => setDescription(e.target.value)} disabled={!editable} />
    <textarea className="min-h-14 w-full rounded-md border border-zinc-700 bg-zinc-950 p-2 text-sm" value={hashtags} onChange={(e) => setHashtags(e.target.value)} disabled={!editable} />
    <div className="flex flex-wrap gap-2">
      <Button variant="outline" onClick={() => void navigator.clipboard.writeText(description)} disabled={!description}><Copy className="mr-2 h-4 w-4" />Copiar descrição</Button>
      <Button variant="outline" onClick={() => void navigator.clipboard.writeText(hashtags)} disabled={!hashtags}><Copy className="mr-2 h-4 w-4" />Copiar hashtags</Button>
      <Button variant="outline" onClick={() => void navigator.clipboard.writeText(text)} disabled={!text}><Copy className="mr-2 h-4 w-4" />Copiar tudo</Button>
      <Button variant="outline" disabled={!editable || !supabase} onClick={async () => { if (!supabase) return; await supabase.rpc('update_publication_text',{p_job_id:job.job_id,p_description:description,p_hashtags:hashtags,p_credits:credits,p_caption:text}); await refresh(); }}><Save className="mr-2 h-4 w-4" />Salvar texto</Button>
    </div>
    {['draft_available','sent_to_user_inbox'].includes(job.status) && <div className="flex flex-col gap-2 sm:flex-row"><input className="h-9 flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 text-sm" placeholder="URL ou ID opcional" value={externalId} onChange={(e) => setExternalId(e.target.value)} /><Button onClick={async () => { if (!supabase) return; await supabase.rpc('mark_manual_publication',{p_job_id:job.job_id,p_external_id:externalId,p_published_at:new Date().toISOString()}); await refresh(); }}><CheckCircle2 className="mr-2 h-4 w-4" />Marcar como publicado no TikTok</Button></div>}
    {job.last_error && <p className="text-sm text-red-400">{job.last_error}</p>}
  </CardContent></Card>;
}
