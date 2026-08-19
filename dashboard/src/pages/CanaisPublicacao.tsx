// Aba multi-canais do VexPublish.
// NOME PROVISORIO: "Canais de publicação". A aba /canais existente continua
// sendo a lista de canais Twitch de origem (vigia_channels) — são coisas
// diferentes e o nome final ainda não foi decidido.
import { FormEvent, useEffect, useState } from "react";

type Tab = "canais" | "contas" | "comparacao" | "fila";
type Row = Record<string, any>;

const API = import.meta.env.VITE_VEXPUBLISH_API_URL || "http://127.0.0.1:8785";
const tabs: [Tab, string][] = [["canais", "Canais"], ["contas", "Contas e limites"], ["comparacao", "Comparação"], ["fila", "Fila e saúde"]];
const panel = "rounded-2xl border border-zinc-800 bg-zinc-900/75 p-4";
const input = "min-h-11 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2";
const button = "min-h-11 rounded-lg bg-cyan-500 px-4 font-bold text-zinc-950 disabled:opacity-40";
const secondary = "min-h-10 rounded-lg border border-zinc-700 px-3 py-2";
const PLATAFORMAS = ["tiktok", "instagram", "youtube", "kwai"];

export function CanaisPublicacao() {
    const [tab, setTab] = useState<Tab>("canais");
    const [token, setToken] = useState(() => sessionStorage.getItem("vexpublish_token") || "");
    const [draft, setDraft] = useState("");
    const [canais, setCanais] = useState<Row[]>([]);
    const [contas, setContas] = useState<Row[]>([]);
    const [comparacao, setComparacao] = useState<Row | null>(null);
    const [fila, setFila] = useState<Row | null>(null);
    const [saude, setSaude] = useState<Row | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");

    async function request(path: string, init: RequestInit = {}) {
        const r = await fetch(API + path, { ...init, headers: { "Content-Type": "application/json", "X-VexPublish-Token": token } });
        if (!r.ok) throw new Error((await r.text()) || `Erro ${r.status}`);
        return r.json();
    }

    async function run(work: () => Promise<void>) {
        setLoading(true); setError("");
        try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "Falha inesperada"); } finally { setLoading(false); }
    }

    async function refresh() {
        setSaude(await (await fetch(API + "/vexpublish/v1/health")).json());
        if (tab === "canais" || tab === "contas") setCanais((await request("/vexpublish/v1/channels")).items || []);
        if (tab === "contas") setContas((await request("/vexpublish/v1/accounts")).items || []);
        if (tab === "comparacao") setComparacao(await request("/vexpublish/v1/compare"));
        if (tab === "fila") setFila(await request("/vexpublish/v1/queue"));
    }

    useEffect(() => { if (token) void run(refresh); }, [token, tab]);

    function login(e: FormEvent) {
        e.preventDefault(); sessionStorage.setItem("vexpublish_token", draft); setToken(draft);
    }

    if (!token) return <form onSubmit={login} className={`${panel} mx-auto max-w-md space-y-3`}>
        <h1 className="text-2xl font-bold">Canais de publicação</h1>
        <p className="text-sm text-zinc-400">Agente local do VexPublish. Nada é publicado por esta tela.</p>
        <input className={`${input} w-full`} type="password" placeholder="Token local" value={draft} onChange={e => setDraft(e.target.value)} required />
        <button className={`${button} w-full`}>Conectar</button>
    </form>;

    return <main className="space-y-4" data-testid="vexpublish-module" aria-busy={loading}>
        <header className={panel}>
            <div className="flex flex-wrap justify-between gap-3">
                <div>
                    <p className="text-xs font-bold uppercase tracking-widest text-cyan-400">Nome provisório · multi-canais</p>
                    <h1 className="text-2xl font-bold">Canais de publicação</h1>
                    <p className="text-sm text-zinc-400">Marca, nicho, contas e limites. Não confundir com a aba “Canais”, que lista os canais Twitch vigiados.</p>
                </div>
                <button className={secondary} onClick={() => { sessionStorage.removeItem("vexpublish_token"); setToken(""); }}>Desconectar</button>
            </div>
            {saude && <p className="mt-3 text-sm text-zinc-400">
                Publicação: <strong className={saude.enabled ? "text-amber-400" : "text-emerald-400"}>{saude.enabled ? "módulo ligado" : "módulo desligado"}</strong>
                {" · "}dry-run <strong className={saude.dry_run ? "text-emerald-400" : "text-amber-400"}>{saude.dry_run ? "ligado" : "desligado"}</strong>
                {" · "}aprovação obrigatória <strong>{saude.require_approval ? "sim" : "não"}</strong>
                {" · "}nenhum adapter validado
            </p>}
            <nav className="mt-4 flex gap-2 overflow-x-auto" aria-label="Áreas de canais">
                {tabs.map(([id, label]) => <button key={id} onClick={() => setTab(id)} className={tab === id ? button : secondary} aria-current={tab === id ? "page" : undefined}>{label}</button>)}
            </nav>
        </header>
        {loading && <p role="status">Carregando…</p>}
        {error && <div role="alert" className="rounded-lg border border-red-700 bg-red-950/40 p-3">{error}</div>}
        {tab === "canais" && <Canais rows={canais} request={request} run={run} refresh={refresh} />}
        {tab === "contas" && <Contas rows={contas} canais={canais} request={request} run={run} refresh={refresh} />}
        {tab === "comparacao" && <Comparacao dados={comparacao} />}
        {tab === "fila" && <Fila dados={fila} />}
    </main>;
}

type Acoes = { request: (p: string, i?: RequestInit) => Promise<any>; run: (w: () => Promise<void>) => Promise<void>; refresh: () => Promise<void> };

function Canais({ rows, request, run, refresh }: Acoes & { rows: Row[] }) {
    const vazio = { name: "", niche: "", voice: "", platforms: [] as string[], notes: "" };
    const [form, setForm] = useState(vazio);
    async function save(e: FormEvent) {
        e.preventDefault();
        await run(async () => { await request("/vexpublish/v1/channels", { method: "POST", body: JSON.stringify({ ...form, identity: {}, calendar: {}, content_rules: {}, preferred_providers: [] }) }); setForm(vazio); await refresh(); });
    }
    return <section className={`${panel} space-y-4`}>
        <h2 className="text-lg font-bold">Canais</h2>
        <form onSubmit={save} className="grid gap-2 md:grid-cols-4">
            <input className={input} placeholder="Nome da marca" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} required />
            <input className={input} placeholder="Nicho" value={form.niche} onChange={e => setForm({ ...form, niche: e.target.value })} />
            <input className={input} placeholder="Voz / tom" value={form.voice} onChange={e => setForm({ ...form, voice: e.target.value })} />
            <fieldset className="flex flex-wrap items-center gap-3 md:col-span-2">
                <legend className="sr-only">Plataformas do canal</legend>
                {PLATAFORMAS.map(x => <label key={x} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={form.platforms.includes(x)} onChange={e => setForm({ ...form, platforms: e.target.checked ? [...form.platforms, x] : form.platforms.filter(p => p !== x) })} />
                    {x}
                </label>)}
            </fieldset>
            <button className={button}>Criar canal</button>
        </form>
        {!rows.length && <p className="rounded-xl border border-dashed border-zinc-700 p-6 text-center text-zinc-400">Nenhum canal cadastrado.</p>}
        <div className="grid gap-3 md:grid-cols-2">
            {rows.map(x => <article key={x.id} className="rounded-xl border border-zinc-800 p-3">
                <div className="flex justify-between"><strong>{x.name}</strong><span className={x.status === "active" ? "text-emerald-400" : "text-zinc-400"}>{x.status}</span></div>
                <p className="text-sm text-zinc-400">{x.slug} · {x.niche || "sem nicho"} · {JSON.parse(x.platforms || "[]").join(", ") || "sem plataforma"}</p>
                <button className="mt-2 underline" onClick={() => run(async () => { await request(`/vexpublish/v1/channels/${x.id}/status?ativo=${x.status !== "active"}`, { method: "POST" }); await refresh(); })}>
                    {x.status === "active" ? "Pausar" : "Ativar"}
                </button>
            </article>)}
        </div>
    </section>;
}

function Contas({ rows, canais, request, run, refresh }: Acoes & { rows: Row[]; canais: Row[] }) {
    const vazio = { channel_id: "", platform: "tiktok", handle: "", max_posts_per_day: 0, minimum_interval_minutes: 0, allowed_hours: [] as number[], timezone: "America/Sao_Paulo", label: "" };
    const [form, setForm] = useState(vazio);
    async function save(e: FormEvent) {
        e.preventDefault();
        await run(async () => { await request("/vexpublish/v1/accounts", { method: "POST", body: JSON.stringify(form) }); setForm({ ...vazio, channel_id: form.channel_id }); await refresh(); });
    }
    return <section className={`${panel} space-y-4`}>
        <h2 className="text-lg font-bold">Contas e limites</h2>
        <p className="text-sm text-zinc-400">Limite 0 significa sem teto configurado — nenhum número fica fixo no código.</p>
        <form onSubmit={save} className="grid gap-2 md:grid-cols-5">
            <select className={input} value={form.channel_id} onChange={e => setForm({ ...form, channel_id: e.target.value })} required>
                <option value="">Canal</option>{canais.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
            <select className={input} value={form.platform} onChange={e => setForm({ ...form, platform: e.target.value })}>
                {PLATAFORMAS.map(x => <option key={x} value={x}>{x}</option>)}
            </select>
            <input className={input} placeholder="@perfil" value={form.handle} onChange={e => setForm({ ...form, handle: e.target.value })} required />
            <input className={input} type="number" min="0" placeholder="Posts por dia" value={form.max_posts_per_day} onChange={e => setForm({ ...form, max_posts_per_day: Number(e.target.value) })} />
            <input className={input} type="number" min="0" placeholder="Intervalo (min)" value={form.minimum_interval_minutes} onChange={e => setForm({ ...form, minimum_interval_minutes: Number(e.target.value) })} />
            <button className={button}>Vincular conta</button>
        </form>
        {!rows.length && <p className="rounded-xl border border-dashed border-zinc-700 p-6 text-center text-zinc-400">Nenhuma conta vinculada.</p>}
        <div className="grid gap-3 md:grid-cols-2">
            {rows.map(x => <article key={x.id} className="rounded-xl border border-zinc-800 p-3">
                <div className="flex justify-between"><strong>{x.platform} · {x.handle}</strong><span className={x.status === "active" ? "text-emerald-400" : "text-zinc-400"}>{x.status}</span></div>
                <p className="text-sm text-zinc-400">
                    {x.max_posts_per_day ? `${x.max_posts_per_day}/dia` : "sem teto"} · intervalo {x.minimum_interval_minutes || 0} min · janela {JSON.parse(x.allowed_hours || "[]").join(", ") || "livre"}
                </p>
                <button className="mt-2 underline" onClick={() => run(async () => { await request(`/vexpublish/v1/accounts/${x.id}/status?ativa=${x.status !== "active"}`, { method: "POST" }); await refresh(); })}>
                    {x.status === "active" ? "Pausar conta" : "Ativar conta"}
                </button>
            </article>)}
        </div>
    </section>;
}

function Comparacao({ dados }: { dados: Row | null }) {
    if (!dados) return <section className={panel}><p>Sem dados de comparação.</p></section>;
    return <section className={`${panel} space-y-3`}>
        <h2 className="text-lg font-bold">Comparação entre canais · últimos {dados.janela_dias} dias</h2>
        <p className="text-sm text-zinc-400">{dados.totais.canais} canais · {dados.totais.publicados} publicações · {dados.totais.falhas} falhas · {dados.totais.views} views · R$ {Number(dados.totais.receita).toFixed(2)}</p>
        <div className="overflow-x-auto">
            <table className="w-full text-sm">
                <thead className="text-left text-zinc-400"><tr><th className="py-2">Canal</th><th>Publicados</th><th>Freq/dia</th><th>Falhas</th><th>Sucesso</th><th>Views</th><th>Retenção</th><th>Receita</th></tr></thead>
                <tbody>
                    {dados.canais.map((x: Row) => <tr key={x.channel_id} className="border-t border-zinc-800">
                        <td className="py-2"><strong>{x.name}</strong><br /><span className="text-zinc-500">{x.niche || "sem nicho"}</span></td>
                        <td>{x.publicados}</td><td>{x.frequencia_por_dia}</td><td>{x.falhas}</td>
                        <td>{x.taxa_sucesso === null ? "—" : `${Math.round(x.taxa_sucesso * 100)}%`}</td>
                        <td>{x.sem_metricas ? "—" : x.views}</td>
                        <td>{x.sem_metricas ? "—" : `${Math.round(x.retencao_media * 100)}%`}</td>
                        <td>{x.sem_metricas ? "—" : `R$ ${Number(x.receita).toFixed(2)}`}</td>
                    </tr>)}
                </tbody>
            </table>
        </div>
        {!!dados.canais_sem_metricas.length && <p className="text-sm text-amber-400">Sem métrica registrada: {dados.canais_sem_metricas.join(", ")}. Traço significa dado ausente, não zero.</p>}
    </section>;
}

function Fila({ dados }: { dados: Row | null }) {
    if (!dados) return <section className={panel}><p>Sem dados de fila.</p></section>;
    return <section className={`${panel} space-y-3`}>
        <h2 className="text-lg font-bold">Fila e saúde</h2>
        <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-xl border border-zinc-800 p-3">
                <h3 className="font-bold">Jobs por status</h3>
                {Object.entries(dados.por_status || {}).map(([k, v]) => <p key={k} className="text-sm">{k}: <strong>{String(v)}</strong></p>)}
                {!Object.keys(dados.por_status || {}).length && <p className="text-sm text-zinc-400">Nenhum job.</p>}
            </div>
            <div className="rounded-xl border border-zinc-800 p-3">
                <h3 className="font-bold">Contas por plataforma</h3>
                {Object.entries(dados.contas || {}).map(([k, v]) => <p key={k} className="text-sm">{k}: {Object.entries(v as Row).map(([s, n]) => `${s} ${n}`).join(" · ") || "nenhuma"}</p>)}
            </div>
            <div className="rounded-xl border border-zinc-800 p-3">
                <h3 className="font-bold">Adapters</h3>
                {Object.entries(dados.adapters || {}).map(([k, v]) => <p key={k} className="text-sm">{k}: <span className="text-amber-400">{String(v)}</span></p>)}
            </div>
        </div>
    </section>;
}
