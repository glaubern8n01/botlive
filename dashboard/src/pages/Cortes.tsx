import { useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';
import { VigiaClipIndex } from '../types';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/Table';
import { Badge } from '../components/ui/Badge';
import { Info } from 'lucide-react';

function fmtSeconds(total: number): string {
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = Math.floor(total % 60);
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${m}:${String(s).padStart(2, '0')}`;
}

export function Cortes() {
  const [clips, setClips] = useState<VigiaClipIndex[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchClips();
  }, []);

  async function fetchClips() {
    if (!supabase) {
      setError('Supabase não configurado.');
      setLoading(false);
      return;
    }
    try {
      const { data, error } = await supabase
        .from('vigia_clip_index')
        .select('*')
        .order('created_at', { ascending: false })
        .limit(100);
      if (error) throw error;
      setClips(data || []);
    } catch (err) {
      console.error(err);
      setError('Erro ao carregar índice de cortes.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Índice de Cortes</h2>
        <p className="text-zinc-400">
          Registro de dedup live×VOD (<code>vigia_clip_index</code>): posição de cada corte na
          linha do tempo do VOD.
        </p>
      </div>

      <div className="flex items-start gap-3 bg-blue-500/10 border border-blue-500/30 text-blue-300 text-sm p-4 rounded-xl">
        <Info className="w-4 h-4 mt-0.5 shrink-0" />
        <p>
          Os arquivos dos cortes ficam no disco da VPS (com publish.json). Revisão e aprovação
          pelo painel exigem um backend de mídia — fase futura (pós-V7).
        </p>
      </div>

      {error && <div className="text-red-500">{error}</div>}

      <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Quando</TableHead>
              <TableHead>Stream</TableHead>
              <TableHead>Modo</TableHead>
              <TableHead>Janela no VOD</TableHead>
              <TableHead>Sessão</TableHead>
              <TableHead>Ref</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center py-8 text-zinc-400">Carregando...</TableCell>
              </TableRow>
            ) : clips.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center py-8 text-zinc-400">
                  Nenhum corte no índice (o vigia passa a escrever aqui quando o dedup V6 entrar).
                </TableCell>
              </TableRow>
            ) : (
              clips.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="text-zinc-400">{new Date(c.created_at).toLocaleString()}</TableCell>
                  <TableCell className="font-mono text-xs">{c.stream_id}</TableCell>
                  <TableCell>
                    <Badge variant={c.mode === 'live' ? 'success' : 'secondary'}>{c.mode}</Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {fmtSeconds(c.clip_start_vod)} – {fmtSeconds(c.clip_end_vod)}
                  </TableCell>
                  <TableCell className="text-zinc-400 max-w-48 truncate">{c.session_id}</TableCell>
                  <TableCell className="text-zinc-400 max-w-40 truncate">{c.corte_ref || '—'}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
