import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle } from 'lucide-react';
import { supabase } from '../lib/supabase';
import { Card, CardDescription, CardHeader, CardTitle } from '../components/ui/Card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/Table';

type MetricRow = { profile_id: string; platform: string; account_id: string | null; status: string; job_count: number };

export function Metricas() {
  const [rows, setRows] = useState<MetricRow[]>([]);
  const [validAssets, setValidAssets] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!supabase) { setError('Supabase não configurado.'); return; }
    const [metrics, assets] = await Promise.all([
      supabase.from('publication_metrics').select('*'),
      supabase.from('media_assets').select('*', { count: 'exact', head: true }).eq('validation_status', 'valid'),
    ]);
    if (metrics.error || assets.error) setError('As métricas de publicação ainda não foram aplicadas no Supabase.');
    else {
      setRows((metrics.data || []) as MetricRow[]);
      setValidAssets(assets.count || 0);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const total = (status: string) => rows.filter((row) => row.status === status).reduce((sum, row) => sum + Number(row.job_count), 0);
  const all = rows.reduce((sum, row) => sum + Number(row.job_count), 0);
  const published = total('published');
  const failed = total('failed');
  const grouped = useMemo(() => {
    const map = new Map<string, number>();
    rows.forEach((row) => map.set(`${row.profile_id}|${row.platform}`, (map.get(`${row.profile_id}|${row.platform}`) || 0) + Number(row.job_count)));
    return [...map.entries()].map(([key, count]) => { const [profile, platform] = key.split('|'); return { profile, platform, count }; });
  }, [rows]);

  return <div className="space-y-6">
    <div><h2 className="text-2xl font-bold">Métricas</h2><p className="text-zinc-400">Somente dados reais da fila e dos assets. Views, receita e engagement não são estimados.</p></div>
    {error && <div className="flex gap-2 text-red-400"><AlertCircle className="h-4 w-4" />{error}</div>}
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Metric title="Assets validados" value={validAssets} />
      <Metric title="Jobs pendentes" value={total('pending') + total('ready') + total('retry_wait')} />
      <Metric title="Publicados" value={published} />
      <Metric title="Falhas" value={failed} />
      <Metric title="Retries aguardando" value={total('retry_wait')} />
      <Metric title="Taxa de sucesso" value={all ? `${((published / Math.max(1, published + failed)) * 100).toFixed(1)}%` : '—'} />
      <Metric title="Em processamento" value={total('validating') + total('uploading') + total('processing')} />
      <Metric title="Jobs totais" value={all} />
    </div>
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50">
      <Table><TableHeader><TableRow><TableHead>Perfil</TableHead><TableHead>Plataforma</TableHead><TableHead>Jobs</TableHead></TableRow></TableHeader>
        <TableBody>{grouped.length === 0 ? <TableRow><TableCell colSpan={3} className="py-8 text-center text-zinc-500">Sem métricas disponíveis.</TableCell></TableRow> : grouped.map((item) => <TableRow key={`${item.profile}-${item.platform}`}><TableCell>{item.profile}</TableCell><TableCell className="capitalize">{item.platform}</TableCell><TableCell>{item.count}</TableCell></TableRow>)}</TableBody>
      </Table>
    </div>
  </div>;
}

function Metric({ title, value }: { title: string; value: number | string }) {
  return <Card><CardHeader><CardDescription>{title}</CardDescription><CardTitle className="text-3xl">{value}</CardTitle></CardHeader></Card>;
}
