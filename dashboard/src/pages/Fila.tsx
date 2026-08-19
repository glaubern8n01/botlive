import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, Ban, ChevronDown, ChevronRight, ExternalLink, RefreshCw } from 'lucide-react';
import { supabase } from '../lib/supabase';
import { PublicationAttempt, PublicationJob, PublicationJobStatus } from '../types';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/Table';

const STATUSES: PublicationJobStatus[] = ['pending', 'validating', 'ready', 'uploading', 'processing', 'published', 'retry_wait', 'rejected', 'cancelled', 'failed'];

function one<T>(value: T | T[] | null): T | null {
  return Array.isArray(value) ? value[0] || null : value;
}

export function Fila() {
  const [jobs, setJobs] = useState<PublicationJob[]>([]);
  const [attempts, setAttempts] = useState<Record<string, PublicationAttempt[]>>({});
  const [expanded, setExpanded] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [profile, setProfile] = useState('');
  const [platform, setPlatform] = useState('');
  const [account, setAccount] = useState('');
  const [status, setStatus] = useState('');
  const [date, setDate] = useState('');

  const load = useCallback(async () => {
    if (!supabase) { setError('Supabase não configurado.'); return; }
    const result = await supabase.from('publication_jobs').select(`
      *, media_assets(path,width,height,duration,validation_status),
      platform_accounts(account_key,display_name)
    `).order('created_at', { ascending: false }).limit(500);
    if (result.error) setError('A fila ainda não foi aplicada no Supabase.');
    else setJobs((result.data || []).map((row) => ({
      ...row,
      media_assets: one(row.media_assets),
      platform_accounts: one(row.platform_accounts),
    })) as PublicationJob[]);
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => jobs.filter((job) =>
    (!profile || job.profile_id === profile) &&
    (!platform || job.platform === platform) &&
    (!account || job.account_id === account) &&
    (!status || job.status === status) &&
    (!date || job.created_at.startsWith(date))
  ), [jobs, profile, platform, account, status, date]);

  const toggleDetails = async (job: PublicationJob) => {
    if (expanded === job.job_id) { setExpanded(null); return; }
    setExpanded(job.job_id);
    if (!attempts[job.job_id] && supabase) {
      const result = await supabase.from('publication_attempts').select('*').eq('job_id', job.job_id).order('attempt_number');
      if (!result.error) setAttempts((current) => ({ ...current, [job.job_id]: (result.data || []) as PublicationAttempt[] }));
    }
  };

  const action = async (job: PublicationJob, kind: 'cancel' | 'retry') => {
    if (!supabase || busy) return;
    setBusy(job.job_id);
    const functionName = kind === 'cancel' ? 'cancel_publication_job' : 'retry_publication_job';
    const result = await supabase.rpc(functionName, { p_job_id: job.job_id });
    if (result.error) setError(`Não foi possível ${kind === 'cancel' ? 'cancelar' : 'reprocessar'} o job.`);
    await load();
    setBusy(null);
  };

  const profiles = Array.from(new Set<string>(jobs.map((job) => String(job.profile_id))));
  const platforms = Array.from(new Set<string>(jobs.map((job) => String(job.platform))));
  const accounts = [...new Set(jobs.map((job) => job.account_id).filter(Boolean))] as string[];

  return (
    <div className="space-y-6">
      <div><h2 className="text-2xl font-bold">Fila</h2><p className="text-zinc-400">Jobs persistentes, tentativas, locks e processamento por destino.</p></div>
      {error && <div className="flex gap-2 text-red-400"><AlertCircle className="h-4 w-4" />{error}</div>}
      <div className="grid gap-3 rounded-xl border border-zinc-800 bg-zinc-900/50 p-4 md:grid-cols-5">
        <Filter value={profile} onChange={setProfile} label="Perfil" options={profiles} />
        <Filter value={platform} onChange={setPlatform} label="Plataforma" options={platforms} />
        <Filter value={account} onChange={setAccount} label="Conta" options={accounts} />
        <Filter value={status} onChange={setStatus} label="Status" options={STATUSES} />
        <label className="text-sm">Data<Input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label>
      </div>
      <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/50">
        <Table>
          <TableHeader><TableRow>
            <TableHead>Job / Perfil</TableHead><TableHead>Evento / Variante</TableHead><TableHead>Asset</TableHead>
            <TableHead>Destino</TableHead><TableHead>Status</TableHead><TableHead>Agendamento</TableHead>
            <TableHead>Tentativas</TableHead><TableHead>Erro</TableHead><TableHead className="text-right">Ações</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {filtered.length === 0 ? <TableRow><TableCell colSpan={9} className="py-10 text-center text-zinc-500">Nenhum job encontrado.</TableCell></TableRow>
              : filtered.map((job) => <Fragment key={job.job_id}>
                <TableRow key={job.job_id}>
                  <TableCell><button onClick={() => toggleDetails(job)} className="mr-2">{expanded === job.job_id ? <ChevronDown className="inline h-4 w-4" /> : <ChevronRight className="inline h-4 w-4" />}</button><code className="text-xs">{job.job_id.slice(0, 8)}</code><div className="text-xs text-zinc-500">{job.profile_id}</div></TableCell>
                  <TableCell><div className="text-xs">{job.event_id?.slice(0, 8) || '—'}</div><div className="text-xs text-zinc-500">{job.variant_id?.slice(0, 8) || '—'}</div></TableCell>
                  <TableCell><div className="max-w-36 truncate">{job.media_assets?.path || job.asset_id.slice(0, 8)}</div><div className="text-xs text-zinc-500">{job.media_assets ? `${job.media_assets.width}×${job.media_assets.height} · ${job.media_assets.duration.toFixed(1)}s` : '—'}</div></TableCell>
                  <TableCell><span className="capitalize">{job.platform}</span><div className="text-xs text-zinc-500">{job.platform_accounts?.display_name || job.platform_accounts?.account_key || job.account_id?.slice(0, 8) || '—'}</div></TableCell>
                  <TableCell><Badge variant={job.status === 'published' ? 'success' : job.status === 'failed' ? 'destructive' : 'secondary'}>{job.status}</Badge></TableCell>
                  <TableCell className="text-xs">{job.scheduled_at ? new Date(job.scheduled_at).toLocaleString() : 'Imediato'}<div className="text-zinc-500">{new Date(job.created_at).toLocaleString()}</div></TableCell>
                  <TableCell>{job.attempts}/{job.max_attempts}</TableCell>
                  <TableCell className="max-w-40 truncate text-xs text-red-400" title={job.last_error || ''}>{job.last_error || '—'}</TableCell>
                  <TableCell className="text-right">
                    {['pending', 'ready', 'retry_wait'].includes(job.status) && <Button variant="ghost" size="icon" disabled={busy === job.job_id} title="Cancelar job pendente" onClick={() => action(job, 'cancel')}><Ban className="h-4 w-4" /></Button>}
                    {job.status === 'failed' && <Button variant="ghost" size="icon" disabled={busy === job.job_id} title="Reprocessar job falho" onClick={() => action(job, 'retry')}><RefreshCw className="h-4 w-4" /></Button>}
                    {job.media_assets?.path && <Button variant="ghost" size="icon" title="Caminho do asset" onClick={() => navigator.clipboard.writeText(job.media_assets!.path)}><ExternalLink className="h-4 w-4" /></Button>}
                  </TableCell>
                </TableRow>
                {expanded === job.job_id && <TableRow key={`${job.job_id}-details`}><TableCell colSpan={9} className="bg-zinc-950/60">
                  <div className="grid gap-4 md:grid-cols-4">
                    <Detail title="Job" lines={[`Criado: ${new Date(job.created_at).toLocaleString()}`, `Atualizado: ${new Date(job.updated_at).toLocaleString()}`, `Worker: ${job.worker_id || '—'}`]} />
                    <Detail title="Publicação" lines={[`External ID: ${job.external_id || '—'}`, `Remote: ${job.remote_status || '—'}`, `Publicado: ${job.published_at ? new Date(job.published_at).toLocaleString() : '—'}`]} />
                    <Detail title="Asset" lines={[job.media_assets?.path || '—', `Validação: ${job.media_assets?.validation_status || '—'}`]} />
                    <Detail title="Timeline / Tentativas" lines={(attempts[job.job_id] || []).map((attempt) => `#${attempt.attempt_number} ${attempt.status}${attempt.error_type ? ` · ${attempt.error_type}` : ''}`)} />
                  </div>
                </TableCell></TableRow>}
              </Fragment>)}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function Filter({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: string[] }) {
  return <label className="text-sm">{label}<select value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-zinc-700 bg-zinc-950 px-2"><option value="">Todos</option>{options.map((option) => <option key={option} value={option}>{option}</option>)}</select></label>;
}

function Detail({ title, lines }: { title: string; lines: string[] }) {
  return <div><h4 className="mb-2 font-medium">{title}</h4>{lines.length ? lines.map((line, index) => <div key={index} className="break-all text-xs text-zinc-400">{line}</div>) : <div className="text-xs text-zinc-500">Sem registros.</div>}</div>;
}
