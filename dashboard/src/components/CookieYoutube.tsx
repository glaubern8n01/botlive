import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, Cookie, Loader2 } from 'lucide-react';

/**
 * Estado e troca do cookie do YouTube pelo painel.
 *
 * Antes o cookie era exportado do navegador e mandado por chat para alguem
 * copiar na VPS a mao. Ele vence sem avisar: numa rodada, 117 dos 120 canais
 * do Kwai CUT falharam na descoberta e so foi notado quando faltou video.
 *
 * Aqui o painel diz em quantos dias vence e aceita o arquivo colado. O arquivo
 * so e gravado se tiver cookie de login valido - trocar um que funciona por
 * lixo derrubaria a descoberta em silencio.
 */

type Estado = 'ok' | 'vencendo' | 'vencido' | 'ausente' | 'invalido';

type Leitura = {
  estado: Estado;
  motivo?: string;
  vence?: string;
  dias_que_faltam?: number;
  entradas?: number;
  atualizado_em?: string;
};

const CORES: Record<Estado, string> = {
  ok: 'border-emerald-800 bg-emerald-950/30 text-emerald-300',
  vencendo: 'border-amber-800 bg-amber-950/30 text-amber-300',
  vencido: 'border-red-900 bg-red-950/30 text-red-300',
  ausente: 'border-red-900 bg-red-950/30 text-red-300',
  invalido: 'border-red-900 bg-red-950/30 text-red-300',
};

function resumo(leitura: Leitura): string {
  if (leitura.estado === 'ok') return `Cookie válido, vence em ${leitura.dias_que_faltam} dias`;
  if (leitura.estado === 'vencendo') return `Vence em ${leitura.dias_que_faltam} dia(s) — troque logo`;
  if (leitura.estado === 'vencido') return 'Cookie vencido: a descoberta do Kwai CUT está falhando';
  if (leitura.estado === 'ausente') return 'Nenhum cookie instalado — o YouTube vai bloquear a VPS';
  return leitura.motivo || 'Arquivo inválido';
}

export default function CookieYoutube() {
  const [leitura, setLeitura] = useState<Leitura | null>(null);
  const [texto, setTexto] = useState('');
  const [aberto, setAberto] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState('');

  const carregar = useCallback(async () => {
    try {
      const resposta = await fetch('/api/cookies/youtube');
      setLeitura(await resposta.json());
    } catch {
      setErro('Não consegui ler o estado do cookie');
    }
  }, []);

  useEffect(() => { void carregar(); }, [carregar]);

  async function salvar() {
    setSalvando(true);
    setErro('');
    try {
      const resposta = await fetch('/api/cookies/youtube', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conteudo: texto }),
      });
      const corpo = await resposta.json();
      if (!resposta.ok) throw new Error(corpo?.error || 'Não deu para salvar');
      setLeitura(corpo);
      setTexto('');
      setAberto(false);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : 'Não deu para salvar');
    } finally {
      setSalvando(false);
    }
  }

  if (!leitura) return null;
  const precisaTrocar = leitura.estado !== 'ok';

  return (
    <div className={`rounded-lg border p-3 ${CORES[leitura.estado] || CORES.invalido}`}>
      <div className="flex flex-wrap items-center gap-2">
        {precisaTrocar ? <AlertCircle className="h-5 w-5 shrink-0" /> : <CheckCircle2 className="h-5 w-5 shrink-0" />}
        <Cookie className="h-4 w-4 shrink-0 opacity-60" />
        <span className="text-sm">Cookie do YouTube: {resumo(leitura)}</span>
        <button
          onClick={() => setAberto(!aberto)}
          className="ml-auto rounded border border-current px-2 py-1 text-xs hover:opacity-80"
        >
          {aberto ? 'Fechar' : precisaTrocar ? 'Colar cookie novo' : 'Trocar'}
        </button>
      </div>

      {aberto && (
        <div className="mt-3 space-y-2">
          <p className="text-xs opacity-80">
            Exporte com a extensão "Get cookies.txt" no youtube.com (formato Netscape) e cole aqui.
            Prefira uma conta secundária: quem tiver este arquivo entra na conta.
          </p>
          <textarea
            value={texto}
            onChange={(evento) => setTexto(evento.target.value)}
            rows={6}
            spellCheck={false}
            placeholder="# Netscape HTTP Cookie File..."
            className="w-full rounded border border-zinc-700 bg-zinc-900 p-2 font-mono text-xs text-zinc-200"
          />
          {erro && <div className="text-xs text-red-300">{erro}</div>}
          <button
            onClick={() => void salvar()}
            disabled={salvando || texto.trim().length < 50}
            className="flex items-center gap-2 rounded bg-orange-500 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
          >
            {salvando && <Loader2 className="h-4 w-4 animate-spin" />}
            Salvar cookie
          </button>
        </div>
      )}
    </div>
  );
}
