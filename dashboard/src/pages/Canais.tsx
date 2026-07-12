import React, { useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';
import { VigiaChannel } from '../types';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/Table';
import { Badge } from '../components/ui/Badge';
import { Trash2, Plus } from 'lucide-react';

export function Canais() {
  const [channels, setChannels] = useState<VigiaChannel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newLogin, setNewLogin] = useState('');
  const [newPriority, setNewPriority] = useState<number>(100);
  const [newNotes, setNewNotes] = useState('');
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    fetchChannels();
  }, []);

  async function fetchChannels() {
    if (!supabase) {
      setError('Supabase não configurado.');
      setLoading(false);
      return;
    }
    try {
      const { data, error } = await supabase
        .from('vigia_channels')
        .select('*')
        .order('priority', { ascending: true })
        .order('login', { ascending: true });
      if (error) throw error;
      setChannels(data || []);
    } catch (err) {
      console.error(err);
      setError('Erro ao carregar canais.');
    } finally {
      setLoading(false);
    }
  }

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newLogin.trim() || !supabase) return;
    setAdding(true);
    try {
      const { error } = await supabase.from('vigia_channels').insert({
        login: newLogin.trim().toLowerCase(),
        priority: newPriority,
        enabled: true,
        added_by: 'manual',
        notes: newNotes.trim() || null,
      });
      if (error) throw error;
      setNewLogin('');
      setNewPriority(100);
      setNewNotes('');
      fetchChannels();
    } catch (err) {
      console.error(err);
      alert('Erro ao adicionar canal (login já existe?).');
    } finally {
      setAdding(false);
    }
  };

  const toggleEnabled = async (channel: VigiaChannel) => {
    if (!supabase) return;
    try {
      await supabase
        .from('vigia_channels')
        .update({ enabled: !channel.enabled })
        .eq('id', channel.id);
      fetchChannels();
    } catch (err) {
      console.error(err);
    }
  };

  const handleDelete = async (channel: VigiaChannel) => {
    if (!supabase) return;
    if (!window.confirm(`Remover ${channel.login} da lista manual?`)) return;
    try {
      await supabase.from('vigia_channels').delete().eq('id', channel.id);
      fetchChannels();
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Canais Cadastrados</h2>
        <p className="text-zinc-400">
          Lista manual de canais da Twitch (prioridade menor = processado primeiro).
        </p>
      </div>

      {error && <div className="text-red-500">{error}</div>}

      <div className="bg-zinc-900/50 border border-zinc-800 p-4 rounded-xl">
        <form onSubmit={handleAdd} className="flex flex-wrap gap-4 items-end">
          <div className="space-y-1 flex-1 min-w-40">
            <label className="text-sm font-medium">Login do canal (Twitch)</label>
            <Input value={newLogin} onChange={(e) => setNewLogin(e.target.value)} placeholder="ex: gaules" />
          </div>
          <div className="space-y-1 w-28">
            <label className="text-sm font-medium">Prioridade</label>
            <Input
              type="number"
              value={newPriority}
              onChange={(e) => setNewPriority(parseInt(e.target.value) || 100)}
              min={1}
            />
          </div>
          <div className="space-y-1 flex-1 min-w-40">
            <label className="text-sm font-medium">Notas (opcional)</label>
            <Input value={newNotes} onChange={(e) => setNewNotes(e.target.value)} placeholder="ex: RP, horário da noite" />
          </div>
          <Button type="submit" disabled={adding || !newLogin.trim()}>
            <Plus className="w-4 h-4 mr-2" />
            Adicionar
          </Button>
        </form>
      </div>

      <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Canal</TableHead>
              <TableHead>Prioridade</TableHead>
              <TableHead>Origem</TableHead>
              <TableHead>Última live vista</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Notas</TableHead>
              <TableHead className="text-right">Ações</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-8 text-zinc-400">Carregando...</TableCell>
              </TableRow>
            ) : channels.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-8 text-zinc-400">Nenhum canal cadastrado.</TableCell>
              </TableRow>
            ) : (
              channels.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="font-medium">
                    <a
                      href={`https://twitch.tv/${c.login}`}
                      target="_blank"
                      rel="noreferrer"
                      className="hover:underline"
                    >
                      {c.login}
                    </a>
                  </TableCell>
                  <TableCell>{c.priority}</TableCell>
                  <TableCell>
                    <Badge variant={c.added_by === 'manual' ? 'outline' : 'secondary'}>{c.added_by}</Badge>
                  </TableCell>
                  <TableCell className="text-zinc-400">
                    {c.last_seen_live ? new Date(c.last_seen_live).toLocaleString() : '—'}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={c.enabled ? 'success' : 'secondary'}
                      className="cursor-pointer"
                      onClick={() => toggleEnabled(c)}
                    >
                      {c.enabled ? 'Ativo' : 'Inativo'}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-zinc-400 max-w-48 truncate">{c.notes || '—'}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handleDelete(c)}
                      className="text-red-400 hover:text-red-300"
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
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
