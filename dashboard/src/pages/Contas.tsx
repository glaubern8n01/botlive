import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, KeyRound } from 'lucide-react';
import { supabase } from '../lib/supabase';
import { SafePlatformAccount } from '../types';
import { Badge } from '../components/ui/Badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/Card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/Table';

const STATUS_LABEL: Record<string, string> = {
  not_configured: 'Não configurado',
  pending: 'Autorização pendente',
  connected: 'Conectado',
  disconnected: 'Desconectado',
  error: 'Erro de autorização',
};

export function Contas() {
  const [accounts, setAccounts] = useState<SafePlatformAccount[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!supabase) {
      setError('Supabase não configurado.');
      setLoading(false);
      return;
    }
    const result = await supabase.from('platform_accounts_safe').select('*').order('platform').order('account_key');
    if (result.error) setError('A view segura de contas ainda não foi aplicada no Supabase.');
    else setAccounts((result.data || []) as SafePlatformAccount[]);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Contas e destinos</h2>
        <p className="text-zinc-400">Referências públicas de contas. Secrets e tokens nunca são carregados nesta tela.</p>
      </div>
      {error && <div className="flex gap-2 text-red-400"><AlertCircle className="h-4 w-4" />{error}</div>}
      <Card>
        <CardHeader>
          <CardTitle>Publishers configurados</CardTitle>
          <CardDescription>YouTube e Instagram mantêm compatibilidade; Kwai aceita dry-run, prepare-only ou API autorizada.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader><TableRow>
              <TableHead>Plataforma</TableHead><TableHead>Conta</TableHead><TableHead>Account ID</TableHead>
              <TableHead>Status</TableHead><TableHead>Secret configurado?</TableHead><TableHead>Publisher</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {loading ? <TableRow><TableCell colSpan={6} className="py-8 text-center">Carregando...</TableCell></TableRow>
                : accounts.length === 0 ? <TableRow><TableCell colSpan={6} className="py-8 text-center text-zinc-500">Nenhuma conta cadastrada.</TableCell></TableRow>
                : accounts.map((account) => <TableRow key={account.id}>
                  <TableCell className="capitalize font-medium">{account.platform}</TableCell>
                  <TableCell>{account.display_name || account.account_key}</TableCell>
                  <TableCell><code className="text-xs text-zinc-500">{account.id}</code></TableCell>
                  <TableCell><Badge variant={account.status === 'connected' ? 'success' : 'secondary'}>{STATUS_LABEL[account.status] || account.status}</Badge></TableCell>
                  <TableCell>
                    <span className={account.secret_configured ? 'text-emerald-400' : 'text-zinc-500'}>
                      {account.secret_configured ? <CheckCircle2 className="mr-1 inline h-4 w-4" /> : <KeyRound className="mr-1 inline h-4 w-4" />}
                      {account.secret_configured ? 'Sim' : 'Não'}
                    </span>
                  </TableCell>
                  <TableCell>{account.platform === 'kwai' ? 'KwaiPublisher' : `${account.platform[0].toUpperCase()}${account.platform.slice(1)}Publisher`}</TableCell>
                </TableRow>)}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
