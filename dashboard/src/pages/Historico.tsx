import { useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';
import { VigiaStream, LiveJobStatus, VodJobStatus } from '../types';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/Table';
import { Badge } from '../components/ui/Badge';
import { Input } from '../components/ui/Input';

function liveBadge(status: LiveJobStatus) {
  switch (status) {
    case 'running':
      return <Badge className="bg-red-500/20 text-red-400 border-transparent">AO VIVO</Badge>;
    case 'done':
      return <Badge variant="success">done</Badge>;
    case 'failed':
      return <Badge variant="destructive">failed</Badge>;
    case 'skipped_no_slot':
      return <Badge variant="outline">sem vaga</Badge>;
    default:
      return <Badge variant="secondary">{status}</Badge>;
  }
}

function vodBadge(status: VodJobStatus) {
  switch (status) {
    case 'running':
      return <Badge className="bg-blue-500/20 text-blue-400 border-transparent">running</Badge>;
    case 'done':
      return <Badge variant="success">done</Badge>;
    case 'failed':
      return <Badge variant="destructive">failed</Badge>;
    case 'waiting_vod':
      return <Badge className="bg-amber-500/20 text-amber-400 border-transparent">aguardando VOD</Badge>;
    case 'vod_unavailable':
      return <Badge variant="outline">VOD indisponível</Badge>;
    case 'deduped_all':
      return <Badge variant="outline">tudo deduplicado</Badge>;
    default:
      return <Badge variant="secondary">{status}</Badge>;
  }
}

export function Historico() {
  const [streams, setStreams] = useState<VigiaStream[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterChannel, setFilterChannel] = useState('');

  useEffect(() => {
    fetchStreams();
  }, []);

  async function fetchStreams() {
    if (!supabase) {
      setError('Supabase não configurado.');
      setLoading(false);
      return;
    }
    try {
      const { data, error } = await supabase
        .from('vigia_streams')
        .select('*')
        .order('detected_at', { ascending: false })
        .limit(100);
      if (error) throw error;
      setStreams(data || []);
    } catch (err) {
      console.error(err);
      setError('Erro ao carregar histórico.');
    } finally {
      setLoading(false);
    }
  }

  const filtered = streams.filter((s) =>
    s.channel_login.toLowerCase().includes(filterChannel.toLowerCase()),
  );

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Histórico de Transmissões</h2>
        <p className="text-zinc-400">
          Ledger do vigia (<code>vigia_streams</code>) — uma linha por transmissão detectada.
        </p>
      </div>

      {error && <div className="text-red-500">{error}</div>}

      <div className="flex items-center gap-4">
        <Input
          placeholder="Filtrar por canal..."
          value={filterChannel}
          onChange={(e) => setFilterChannel(e.target.value)}
          className="max-w-xs"
        />
      </div>

      <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Canal</TableHead>
              <TableHead>Origem</TableHead>
              <TableHead>Job Live</TableHead>
              <TableHead>Job VOD</TableHead>
              <TableHead>Uploads</TableHead>
              <TableHead>Detectada em</TableHead>
              <TableHead>Fim da live</TableHead>
              <TableHead>Erro</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={8} className="text-center py-8 text-zinc-400">Carregando histórico...</TableCell>
              </TableRow>
            ) : filtered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="text-center py-8 text-zinc-400">Nenhum registro encontrado.</TableCell>
              </TableRow>
            ) : (
              filtered.map((s) => (
                <TableRow key={s.stream_id}>
                  <TableCell className="font-medium">
                    {s.channel_login}
                    {s.dry_run && (
                      <Badge variant="outline" className="ml-2 text-zinc-500">dry</Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant={s.origin === 'manual' ? 'outline' : 'secondary'}>{s.origin}</Badge>
                  </TableCell>
                  <TableCell>{liveBadge(s.live_job_status)}</TableCell>
                  <TableCell>{vodBadge(s.vod_job_status)}</TableCell>
                  <TableCell>{s.uploads_done}</TableCell>
                  <TableCell className="text-zinc-400">{new Date(s.detected_at).toLocaleString()}</TableCell>
                  <TableCell className="text-zinc-400">
                    {s.ended_at ? new Date(s.ended_at).toLocaleString() : '—'}
                  </TableCell>
                  <TableCell className="text-red-400 max-w-56 truncate" title={s.error_message || ''}>
                    {s.error_message || '—'}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
