// Aba Importar / Adaptar / Publicar.
// Nada aqui publica: a saída é PublishJob em draft no VexPublish.
import { FormEvent, useEffect, useState } from "react";
import { AgenteLogin } from "../components/AgenteLogin";
import { ComoFunciona } from "../components/ComoFunciona";

type Tab = "fontes" | "biblioteca" | "adaptacao" | "auditoria";
type Row = Record<string, any>;

const API = import.meta.env.VITE_IMPORT_API_URL || "http://127.0.0.1:8795";
const tabs: [Tab, string][] = [["fontes", "Fontes autorizadas"], ["biblioteca", "Biblioteca"], ["adaptacao", "Adaptação e fila"], ["auditoria", "Auditoria"]];
const panel = "rounded-2xl border border-zinc-800 bg-zinc-900/75 p-4";
const input = "min-h-11 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2";
const button = "min-h-11 rounded-lg bg-cyan-500 px-4 font-bold text-zinc-950 disabled:opacity-40";
const secondary = "min-h-10 rounded-lg border border-zinc-700 px-3 py-2";
const LICENCAS = ["propria", "cc-by", "cc-by-sa", "cc0", "dominio-publico", "autorizacao-direta", "campanha"];
const LAYOUTS = ["vertical-fit", "vertical-crop", "original"];

export function ImportarAdaptar() {
    const [tab, setTab] = useState<Tab>("fontes");
    const [token, setToken] = useState(() => sessionStorage.getItem("import_token") || "");
    const [draft, setDraft] = useState("");
    const [fontes, setFontes] = useState<Row[]>([]);
    const [itens, setItens] = useState<Row[]>([]);
    const [adaptacoes, setAdaptacoes] = useState<Row[]>([]);
    const [auditoria, setAuditoria] = useState<Row[]>([]);
    const [saude, setSaude] = useState<Row | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");

    async function request(path: string, init: RequestInit = {}) {
        const r = await fetch(API + path, { ...init, headers: { "Content-Type": "application/json", "X-Import-Token": token } });
        if (!r.ok) throw new Error((await r.text()) || `Erro ${r.status}`);
        return r.json();
    }

    async function run(work: () => Promise<void>) {
        setLoading(true); setError(""); setNotice("");
        try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "Falha inesperada"); } finally { setLoading(false); }
    }

    async function refresh() {
        setSaude(await (await fetch(API + "/import/v1/health")).json());
        if (tab === "fontes" || tab === "biblioteca" || tab === "adaptacao") setFontes((await request("/import/v1/sources")).items || []);
        if (tab === "biblioteca" || tab === "adaptacao") setItens((await request("/import/v1/items")).items || []);
        if (tab === "adaptacao") setAdaptacoes((await request("/import/v1/adaptations")).items || []);
        if (tab === "auditoria") setAuditoria((await request("/import/v1/audit")).items || []);
    }

    useEffect(() => { if (token) void run(refresh); }, [token, tab]);

    if (!token) return <AgenteLogin
        titulo="Importar / Adaptar"
        resumo="Traz vídeos que você tem direito de usar, adapta pro formato do canal (9:16, tarja, título, marca) e manda pra fila de publicação."
        faz={[
            "Cadastrar de onde o material vem e quem autorizou o uso",
            "Importar uma pasta inteira de uma vez, sem repetir arquivo",
            "Transformar em vertical com título, marca e CTA",
            "Mandar o resultado pra fila do canal escolhido",
        ]}
        naoFaz="Ele não remove marca d'água nem crédito de ninguém — o plano de adaptação recusa esse tipo de opção. E o download automático vem desligado."
        chaveSessao="import_token"
        aoEntrar={setToken}
    />;

    return <main className="space-y-4" aria-busy={loading} data-testid="import-module">
        <header className={panel}>
            <div className="flex flex-wrap justify-between gap-3">
                <div>
                    <p className="text-xs font-bold uppercase tracking-widest text-cyan-400">Feature flag · operação isolada</p>
                    <h1 className="text-2xl font-bold">Importar / Adaptar / Publicar</h1>
                    <p className="text-sm text-zinc-400">Material próprio, licenciado ou autorizado. A adaptação preserva o crédito da origem.</p>
                </div>
                <button className={secondary} onClick={() => { sessionStorage.removeItem("import_token"); setToken(""); }}>Desconectar</button>
            </div>
            {saude && <p className="mt-3 text-sm text-zinc-400">
                Download automático: <strong className={saude.download_liberado ? "text-amber-400" : "text-emerald-400"}>{saude.download_liberado ? "liberado" : "desligado"}</strong>
                {" · "}saída: <strong>{saude.saida}</strong>
            </p>}
            <nav className="mt-4 flex gap-2 overflow-x-auto" aria-label="Áreas de importação">
                {tabs.map(([id, label]) => <button key={id} onClick={() => setTab(id)} className={tab === id ? button : secondary} aria-current={tab === id ? "page" : undefined}>{label}</button>)}
            </nav>
        </header>
        <ComoFunciona
            passos={[
                { titulo: "Fonte", detalhe: "de onde vem e quem autorizou", estado: "humano" },
                { titulo: "Biblioteca", detalhe: "importa em lote, sem repetir" },
                { titulo: "Adaptação", detalhe: "vertical, tarja, marca, CTA" },
                { titulo: "Fila do canal", detalhe: "vira job de publicação" },
                { titulo: "Aprovação", detalhe: "você libera antes de sair", estado: "travado" },
            ]}
            aviso="O crédito da origem é sempre mantido. Arquivo repetido é detectado pelo conteúdo, não pelo nome — o mesmo vídeo com outro nome não entra duas vezes."
        />
        {loading && <p role="status">Carregando…</p>}
        {error && <div role="alert" className="rounded-lg border border-red-700 bg-red-950/40 p-3">{error}</div>}
        {notice && <div role="status" className="rounded-lg border border-emerald-700 bg-emerald-950/40 p-3">{notice}</div>}
        {tab === "fontes" && <Fontes rows={fontes} request={request} run={run} refresh={refresh} />}
        {tab === "biblioteca" && <Biblioteca rows={itens} fontes={fontes} request={request} run={run} refresh={refresh} aviso={setNotice} />}
        {tab === "adaptacao" && <Adaptacao rows={adaptacoes} itens={itens} request={request} run={run} refresh={refresh} aviso={setNotice} />}
        {tab === "auditoria" && <Auditoria rows={auditoria} />}
    </main>;
}

type Acoes = { request: (p: string, i?: RequestInit) => Promise<any>; run: (w: () => Promise<void>) => Promise<void>; refresh: () => Promise<void> };

function Fontes({ rows, request, run, refresh }: Acoes & { rows: Row[] }) {
    const vazio = { name: "", kind: "local_folder", location: "", authorized: false, authorization_source: "", license: "autorizacao-direta", rights_notes: "", allow_download: false };
    const [form, setForm] = useState(vazio);
    return <section className={`${panel} space-y-4`}>
        <h2 className="text-lg font-bold">Fontes autorizadas</h2>
        <p className="text-sm text-zinc-400">Sem marcar a autorização e dizer quem autorizou, a fonte não entra.</p>
        <form onSubmit={(e) => { e.preventDefault(); void run(async () => { await request("/import/v1/sources", { method: "POST", body: JSON.stringify(form) }); setForm(vazio); await refresh(); }); }} className="grid gap-2 md:grid-cols-3">
            <input className={input} placeholder="Nome da fonte" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} required />
            <select className={input} value={form.kind} onChange={e => setForm({ ...form, kind: e.target.value })}>
                <option value="local_folder">Pasta local</option><option value="upload">Upload</option><option value="url_list">Lista de URLs</option>
            </select>
            <input className={input} placeholder="Pasta ou lista de origem" value={form.location} onChange={e => setForm({ ...form, location: e.target.value })} />
            <input className={input} placeholder="Quem autorizou" value={form.authorization_source} onChange={e => setForm({ ...form, authorization_source: e.target.value })} required />
            <select className={input} value={form.license} onChange={e => setForm({ ...form, license: e.target.value })}>
                {LICENCAS.map(x => <option key={x} value={x}>{x}</option>)}
            </select>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.authorized} onChange={e => setForm({ ...form, authorized: e.target.checked })} />Confirmo que o uso é autorizado</label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.allow_download} onChange={e => setForm({ ...form, allow_download: e.target.checked })} />Permitir download automático</label>
            <button className={button}>Cadastrar fonte</button>
        </form>
        {!rows.length && <p className="rounded-xl border border-dashed border-zinc-700 p-6 text-center text-zinc-400">Nenhuma fonte cadastrada.</p>}
        <div className="grid gap-3 md:grid-cols-2">
            {rows.map(x => <article key={x.id} className="rounded-xl border border-zinc-800 p-3">
                <div className="flex justify-between"><strong>{x.name}</strong><span className={x.status === "active" ? "text-emerald-400" : "text-zinc-500"}>{x.status}</span></div>
                <p className="text-sm text-zinc-400">{x.kind} · licença {x.license} · {x.allow_download ? "download permitido" : "sem download"}</p>
                <p className="text-xs text-zinc-500">Autorizado por: {x.authorization_source}</p>
                {x.status === "active" && <button className="mt-2 underline" onClick={() => run(async () => { await request(`/import/v1/sources/${x.id}/archive`, { method: "POST" }); await refresh(); })}>Arquivar</button>}
            </article>)}
        </div>
    </section>;
}

function Biblioteca({ rows, fontes, request, run, refresh, aviso }: Acoes & { rows: Row[]; fontes: Row[]; aviso: (x: string) => void }) {
    const [source, setSource] = useState("");
    const [folder, setFolder] = useState("");
    return <section className={`${panel} space-y-4`}>
        <h2 className="text-lg font-bold">Biblioteca</h2>
        <p className="text-sm text-zinc-400">Deduplicação por SHA-256: o mesmo conteúdo não entra duas vezes, mesmo com outro nome de arquivo.</p>
        <form onSubmit={(e) => { e.preventDefault(); void run(async () => { const out = await request("/import/v1/batch", { method: "POST", body: JSON.stringify({ source_id: source, folder: folder || null }) }); aviso(`${out.importados} importados · ${out.repetidos} repetidos · ${out.recusados.length} recusados`); await refresh(); }); }} className="grid gap-2 md:grid-cols-3">
            <select className={input} value={source} onChange={e => setSource(e.target.value)} required>
                <option value="">Fonte</option>{fontes.filter(x => x.status === "active").map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
            <input className={input} placeholder="Pasta (vazio = a da fonte)" value={folder} onChange={e => setFolder(e.target.value)} />
            <button className={button}>Importar em lote</button>
        </form>
        {!rows.length && <p className="rounded-xl border border-dashed border-zinc-700 p-6 text-center text-zinc-400">Biblioteca vazia.</p>}
        <div className="grid gap-3 md:grid-cols-2">
            {rows.map(x => <article key={x.id} className="rounded-xl border border-zinc-800 p-3">
                <strong>{x.name}</strong>
                <p className="text-sm text-zinc-400">{x.width || "?"}×{x.height || "?"} · {Number(x.duration_seconds || 0).toFixed(1)}s · {(x.size_bytes / 1048576).toFixed(1)} MB · {x.has_audio ? "com áudio" : "sem áudio"}</p>
                <p className="text-xs text-zinc-500">Crédito: {x.credit || "—"}</p>
                <code className="text-xs">SHA-256 {String(x.sha256).slice(0, 16)}…</code>
            </article>)}
        </div>
    </section>;
}

function Adaptacao({ rows, itens, request, run, refresh, aviso }: Acoes & { rows: Row[]; itens: Row[]; aviso: (x: string) => void }) {
    const vazio = { item_id: "", channel_id: "", plan: { layout: "vertical-fit", title: "", description: "", brand: "", cta: "" } };
    const [form, setForm] = useState<any>(vazio);
    return <section className={`${panel} space-y-4`}>
        <h2 className="text-lg font-bold">Adaptação e fila por canal</h2>
        <p className="text-sm text-zinc-400">O crédito da origem é mantido — o plano não aceita opção de remover autoria ou proteção.</p>
        <form onSubmit={(e) => { e.preventDefault(); void run(async () => { await request("/import/v1/adaptations", { method: "POST", body: JSON.stringify(form) }); setForm(vazio); await refresh(); }); }} className="grid gap-2 md:grid-cols-3">
            <select className={input} value={form.item_id} onChange={e => setForm({ ...form, item_id: e.target.value })} required>
                <option value="">Item da biblioteca</option>{itens.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
            <input className={input} placeholder="ID do canal no VexPublish" value={form.channel_id} onChange={e => setForm({ ...form, channel_id: e.target.value })} required />
            <select className={input} value={form.plan.layout} onChange={e => setForm({ ...form, plan: { ...form.plan, layout: e.target.value } })}>
                {LAYOUTS.map(x => <option key={x} value={x}>{x}</option>)}
            </select>
            <input className={input} placeholder="Título / tarja" value={form.plan.title} onChange={e => setForm({ ...form, plan: { ...form.plan, title: e.target.value } })} />
            <input className={input} placeholder="Identidade / marca" value={form.plan.brand} onChange={e => setForm({ ...form, plan: { ...form.plan, brand: e.target.value } })} />
            <input className={input} placeholder="CTA" value={form.plan.cta} onChange={e => setForm({ ...form, plan: { ...form.plan, cta: e.target.value } })} />
            <button className={button}>Planejar adaptação</button>
        </form>
        {!rows.length && <p className="rounded-xl border border-dashed border-zinc-700 p-6 text-center text-zinc-400">Nenhuma adaptação planejada.</p>}
        <div className="grid gap-3 md:grid-cols-2">
            {rows.map(x => <article key={x.id} className="rounded-xl border border-zinc-800 p-3">
                <div className="flex justify-between"><strong>{JSON.parse(x.plan || "{}").layout}</strong><span>{x.status}</span></div>
                <p className="text-sm text-zinc-400">{x.width || "?"}×{x.height || "?"} · canal {x.channel_id || "—"}</p>
                {x.error && <p className="text-xs text-red-300">{x.error}</p>}
                <div className="mt-2 flex flex-wrap gap-3">
                    {x.status === "planned" && <button className="underline" onClick={() => run(async () => { await request(`/import/v1/adaptations/${x.id}/render`, { method: "POST" }); await refresh(); })}>Renderizar</button>}
                    {["rendered", "queued"].includes(x.status) && <button className="underline" onClick={() => run(async () => { const out = await request(`/import/v1/adaptations/${x.id}/queue`, { method: "POST", body: JSON.stringify({ caption: "" }) }); aviso(`${out.total} job(s) em draft no VexPublish, aguardando aprovação`); await refresh(); })}>Enviar para a fila do canal</button>}
                </div>
            </article>)}
        </div>
    </section>;
}

function Auditoria({ rows }: { rows: Row[] }) {
    return <section className={`${panel} space-y-3`}>
        <h2 className="text-lg font-bold">Auditoria</h2>
        {!rows.length && <p className="text-zinc-400">Nenhum evento.</p>}
        {rows.map(x => <article key={x.id} className="rounded-xl border border-zinc-800 p-3">
            <div className="flex justify-between"><strong>{x.action}</strong><span className={x.result === "ok" ? "text-emerald-400" : "text-amber-400"}>{x.result}</span></div>
            <p className="text-sm text-zinc-400">{x.actor} ({x.role}) · {new Date(x.created_at).toLocaleString()}</p>
            <p className="text-xs text-zinc-500">{x.entity_type} {x.entity_id || ""}</p>
        </article>)}
    </section>;
}
