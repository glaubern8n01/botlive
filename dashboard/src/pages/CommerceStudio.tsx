// Commerce Studio — TikTok Shop e Shopee.
// Não publica: gera LiveAssetPackage para o Live Pilot e PublishJob em draft.
import { FormEvent, useEffect, useState } from "react";
import { AgenteLogin } from "../components/AgenteLogin";
import { ComoFunciona } from "../components/ComoFunciona";

type Tab = "produtos" | "provas" | "criativos" | "pacotes";
type Row = Record<string, any>;

const API = import.meta.env.VITE_COMMERCE_API_URL || "http://127.0.0.1:8805";
const tabs: [Tab, string][] = [["produtos", "Produtos"], ["provas", "Evidências e claims"], ["criativos", "Criativos"], ["pacotes", "Pacotes Live Pilot"]];
const panel = "rounded-2xl border border-zinc-800 bg-zinc-900/75 p-4";
const input = "min-h-11 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2";
const button = "min-h-11 rounded-lg bg-cyan-500 px-4 font-bold text-zinc-950 disabled:opacity-40";
const secondary = "min-h-10 rounded-lg border border-zinc-700 px-3 py-2";
const ORIGENS = ["manual", "importado", "catalogo-oficial", "api-afiliado"];
const EVIDENCIAS = ["especificacao", "pagina-oficial", "laudo", "review", "teste-proprio"];

export function CommerceStudio() {
    const [tab, setTab] = useState<Tab>("produtos");
    const [token, setToken] = useState(() => sessionStorage.getItem("commerce_token") || "");
    const [draft, setDraft] = useState("");
    const [produtos, setProdutos] = useState<Row[]>([]);
    const [selecionado, setSelecionado] = useState<Row | null>(null);
    const [criativos, setCriativos] = useState<Row[]>([]);
    const [tipos, setTipos] = useState<string[]>([]);
    const [pacotes, setPacotes] = useState<Row[]>([]);
    const [saude, setSaude] = useState<Row | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");

    async function request(path: string, init: RequestInit = {}) {
        const r = await fetch(API + path, { ...init, headers: { "Content-Type": "application/json", "X-Commerce-Token": token } });
        if (!r.ok) throw new Error((await r.text()) || `Erro ${r.status}`);
        return r.json();
    }

    async function run(work: () => Promise<void>) {
        setLoading(true); setError(""); setNotice("");
        try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "Falha inesperada"); } finally { setLoading(false); }
    }

    async function refresh() {
        setSaude(await (await fetch(API + "/commerce/v1/health")).json());
        setProdutos((await request("/commerce/v1/products")).items || []);
        if (selecionado) setSelecionado(await request(`/commerce/v1/products/${selecionado.id}`));
        if (tab === "criativos") {
            setTipos((await request("/commerce/v1/creative-kinds")).items || []);
            setCriativos((await request("/commerce/v1/creatives")).items || []);
        }
        if (tab === "pacotes" && selecionado) setPacotes((await request(`/commerce/v1/products/${selecionado.id}/live-package`)).items || []);
    }

    useEffect(() => { if (token) void run(refresh); }, [token, tab]);

    if (!token) return <AgenteLogin
        titulo="Commerce Studio"
        resumo="Monta os vídeos de venda de produto (TikTok Shop e Shopee): o que pode ser dito sobre o produto, os criativos e o pacote que a live consome."
        faz={[
            "Cadastrar produto com link de afiliado e as provas do que ele faz",
            "Marcar quais frases podem ser ditas — só as que têm prova",
            "Criar os vídeos de venda e passar pelo controle de qualidade",
            "Exportar o pacote pronto para a extensão de LIVE",
        ]}
        naoFaz="Nenhuma frase de venda passa sem prova registrada, e a extensão de LIVE não é alterada — ela só recebe o pacote."
        chaveSessao="commerce_token"
        aoEntrar={setToken}
    />;

    return <main className="space-y-4" aria-busy={loading} data-testid="commerce-module">
        <header className={panel}>
            <div className="flex flex-wrap justify-between gap-3">
                <div>
                    <p className="text-xs font-bold uppercase tracking-widest text-cyan-400">Feature flag · separado do Live Pilot</p>
                    <h1 className="text-2xl font-bold">Commerce Studio</h1>
                    <p className="text-sm text-zinc-400">TikTok Shop e Shopee. A extensão de LIVE não é alterada — ela só consome o pacote exportado.</p>
                </div>
                <button className={secondary} onClick={() => { sessionStorage.removeItem("commerce_token"); setToken(""); }}>Desconectar</button>
            </div>
            {saude && <p className="mt-3 text-sm text-zinc-400">
                dry-run <strong className={saude.dry_run ? "text-emerald-400" : "text-amber-400"}>{saude.dry_run ? "ligado" : "desligado"}</strong>
                {" · "}auto-publish <strong className={saude.auto_publish ? "text-amber-400" : "text-emerald-400"}>{saude.auto_publish ? "ligado" : "desligado"}</strong>
                {" · "}Live Pilot alterado: <strong>não</strong>
            </p>}
            <nav className="mt-4 flex gap-2 overflow-x-auto" aria-label="Áreas do Commerce Studio">
                {tabs.map(([id, label]) => <button key={id} onClick={() => setTab(id)} className={tab === id ? button : secondary} aria-current={tab === id ? "page" : undefined}>{label}</button>)}
            </nav>
            {selecionado && <p className="mt-3 text-sm">Produto ativo: <strong>{selecionado.title}</strong> · confiança <strong>{Number(selecionado.confidence).toFixed(2)}</strong> (teto {selecionado.confidence_teto})</p>}
        </header>
        <ComoFunciona
            passos={[
                { titulo: "Produto", detalhe: "link, preço e de onde veio a informação" },
                { titulo: "Provas", detalhe: "o que sustenta cada frase", estado: "humano" },
                { titulo: "Criativo", detalhe: "gancho, roteiro e CTA" },
                { titulo: "Controle", detalhe: "reprova frase sem prova", estado: "travado" },
                { titulo: "Pacote / Fila", detalhe: "vai pra LIVE ou pra publicação" },
            ]}
            aviso="A regra central: frase sem prova registrada não vira fala na live nem legenda de vídeo. O controle lê o roteiro inteiro, não só o que você marcou."
        />
        {loading && <p role="status">Carregando…</p>}
        {error && <div role="alert" className="rounded-lg border border-red-700 bg-red-950/40 p-3">{error}</div>}
        {notice && <div role="status" className="rounded-lg border border-emerald-700 bg-emerald-950/40 p-3">{notice}</div>}

        {tab === "produtos" && <Produtos rows={produtos} request={request} run={run} refresh={refresh} escolher={async (x: Row) => run(async () => setSelecionado(await request(`/commerce/v1/products/${x.id}`)))} />}
        {tab === "provas" && <Provas produto={selecionado} request={request} run={run} refresh={refresh} />}
        {tab === "criativos" && <Criativos rows={criativos} tipos={tipos} produto={selecionado} request={request} run={run} refresh={refresh} aviso={setNotice} />}
        {tab === "pacotes" && <Pacotes rows={pacotes} produto={selecionado} request={request} run={run} refresh={refresh} aviso={setNotice} />}
    </main>;
}

type Acoes = { request: (p: string, i?: RequestInit) => Promise<any>; run: (w: () => Promise<void>) => Promise<void>; refresh: () => Promise<void> };

function Produtos({ rows, request, run, refresh, escolher }: Acoes & { rows: Row[]; escolher: (x: Row) => void }) {
    const vazio = { platform: "tiktok-shop", title: "", source: "manual", brand: "", affiliate_url: "", price: 0, target_audience: "", notes: "", features: [] as string[] };
    const [form, setForm] = useState(vazio);
    return <section className={`${panel} space-y-4`}>
        <h2 className="text-lg font-bold">Produtos</h2>
        <p className="text-sm text-zinc-400">Confiança não é digitada: ela é derivada da evidência que você anexar. Cadastro manual tem teto 0,3.</p>
        <form onSubmit={(e) => { e.preventDefault(); void run(async () => { await request("/commerce/v1/products", { method: "POST", body: JSON.stringify(form) }); setForm(vazio); await refresh(); }); }} className="grid gap-2 md:grid-cols-3">
            <select className={input} value={form.platform} onChange={e => setForm({ ...form, platform: e.target.value })}>
                <option value="tiktok-shop">TikTok Shop</option><option value="shopee">Shopee</option>
            </select>
            <input className={input} placeholder="Título do produto" value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} required />
            <select className={input} value={form.source} onChange={e => setForm({ ...form, source: e.target.value })}>
                {ORIGENS.map(x => <option key={x} value={x}>{x}</option>)}
            </select>
            <input className={input} placeholder="Marca" value={form.brand} onChange={e => setForm({ ...form, brand: e.target.value })} />
            <input className={input} type="url" placeholder="Link de afiliado" value={form.affiliate_url} onChange={e => setForm({ ...form, affiliate_url: e.target.value })} />
            <input className={input} type="number" min="0" step="0.01" placeholder="Preço" value={form.price} onChange={e => setForm({ ...form, price: Number(e.target.value) })} />
            <button className={button}>Cadastrar produto</button>
        </form>
        {!rows.length && <p className="rounded-xl border border-dashed border-zinc-700 p-6 text-center text-zinc-400">Nenhum produto cadastrado.</p>}
        <div className="grid gap-3 md:grid-cols-2">
            {rows.map(x => <article key={x.id} className="rounded-xl border border-zinc-800 p-3">
                <div className="flex justify-between"><strong>{x.title}</strong><span className="text-cyan-400">{x.platform}</span></div>
                <p className="text-sm text-zinc-400">origem {x.source} · confiança {Number(x.confidence).toFixed(2)} · R$ {Number(x.price).toFixed(2)}</p>
                <button className="mt-2 underline" onClick={() => escolher(x)}>Selecionar</button>
            </article>)}
        </div>
    </section>;
}

function Provas({ produto, request, run, refresh }: Acoes & { produto: Row | null }) {
    const [evidencia, setEvidencia] = useState({ kind: "especificacao", statement: "", source_label: "", source_url: "", reliability: "media" });
    const [claim, setClaim] = useState("");
    const [selecao, setSelecao] = useState<string[]>([]);
    if (!produto) return <section className={panel}><p className="text-zinc-400">Selecione um produto na aba Produtos.</p></section>;
    return <section className={`${panel} space-y-4`}>
        <h2 className="text-lg font-bold">Evidências e claims — {produto.title}</h2>
        <form onSubmit={(e) => { e.preventDefault(); void run(async () => { await request(`/commerce/v1/products/${produto.id}/evidence`, { method: "POST", body: JSON.stringify(evidencia) }); setEvidencia({ ...evidencia, statement: "", source_label: "" }); await refresh(); }); }} className="grid gap-2 md:grid-cols-4">
            <select className={input} value={evidencia.kind} onChange={e => setEvidencia({ ...evidencia, kind: e.target.value })}>
                {EVIDENCIAS.map(x => <option key={x} value={x}>{x}</option>)}
            </select>
            <input className={input} placeholder="O que a evidência sustenta" value={evidencia.statement} onChange={e => setEvidencia({ ...evidencia, statement: e.target.value })} required />
            <input className={input} placeholder="Origem (obrigatória)" value={evidencia.source_label} onChange={e => setEvidencia({ ...evidencia, source_label: e.target.value })} required />
            <button className={button}>Registrar evidência</button>
        </form>
        <div className="grid gap-2">
            {(produto.evidencias || []).map((x: Row) => <label key={x.id} className="flex items-center gap-2 rounded-lg border border-zinc-800 p-2 text-sm">
                <input type="checkbox" checked={selecao.includes(x.id)} onChange={e => setSelecao(e.target.checked ? [...selecao, x.id] : selecao.filter(i => i !== x.id))} />
                <span><strong>{x.statement}</strong> — {x.source_label} ({x.reliability})</span>
            </label>)}
        </div>
        <form onSubmit={(e) => { e.preventDefault(); void run(async () => { await request(`/commerce/v1/products/${produto.id}/claims`, { method: "POST", body: JSON.stringify({ text: claim }) }); setClaim(""); await refresh(); }); }} className="flex flex-wrap gap-2">
            <input className={`${input} flex-1`} placeholder="Novo claim" value={claim} onChange={e => setClaim(e.target.value)} required />
            <button className={button}>Propor claim</button>
        </form>
        <div className="grid gap-3 md:grid-cols-3">
            <Coluna titulo="Sustentados" cor="text-emerald-400" itens={produto.claims_allowed || []} />
            <Coluna titulo="Propostos (sem evidência)" cor="text-amber-400" itens={produto.claims_propostos || []} />
            <Coluna titulo="Bloqueados" cor="text-red-400" itens={produto.claims_blocked || []} />
        </div>
        <p className="text-xs text-zinc-500">Marque as evidências acima e sustente o claim pela API — claim sem evidência nunca vira ponto de fala no Live Pilot.</p>
    </section>;
}

function Coluna({ titulo, cor, itens }: { titulo: string; cor: string; itens: string[] }) {
    return <div className="rounded-xl border border-zinc-800 p-3">
        <h3 className={`font-bold ${cor}`}>{titulo}</h3>
        {!itens.length && <p className="text-sm text-zinc-500">—</p>}
        {itens.map(x => <p key={x} className="text-sm">{x}</p>)}
    </div>;
}

function Criativos({ rows, tipos, produto, request, run, refresh, aviso }: Acoes & { rows: Row[]; tipos: string[]; produto: Row | null; aviso: (x: string) => void }) {
    const vazio = { kind: "PRODUCT_HERO", hook: "", script: "", cta: "", objective: "" };
    const [form, setForm] = useState(vazio);
    return <section className={`${panel} space-y-4`}>
        <h2 className="text-lg font-bold">Criativos</h2>
        {!produto && <p className="text-zinc-400">Selecione um produto para criar.</p>}
        {produto && <form onSubmit={(e) => { e.preventDefault(); void run(async () => { await request("/commerce/v1/creatives", { method: "POST", body: JSON.stringify({ ...form, product_id: produto.id }) }); setForm(vazio); await refresh(); }); }} className="grid gap-2 md:grid-cols-3">
            <select className={input} value={form.kind} onChange={e => setForm({ ...form, kind: e.target.value })}>
                {tipos.map(x => <option key={x} value={x}>{x}</option>)}
            </select>
            <input className={input} placeholder="Gancho" value={form.hook} onChange={e => setForm({ ...form, hook: e.target.value })} />
            <input className={input} placeholder="CTA" value={form.cta} onChange={e => setForm({ ...form, cta: e.target.value })} />
            <textarea className={`${input} md:col-span-2`} placeholder="Roteiro" value={form.script} onChange={e => setForm({ ...form, script: e.target.value })} />
            <button className={button}>Criar criativo</button>
        </form>}
        {!rows.length && <p className="rounded-xl border border-dashed border-zinc-700 p-6 text-center text-zinc-400">Nenhum criativo.</p>}
        <div className="grid gap-3 md:grid-cols-2">
            {rows.map(x => {
                const qa = JSON.parse(x.qa || "{}");
                return <article key={x.id} className="rounded-xl border border-zinc-800 p-3">
                    <div className="flex justify-between"><strong>{x.kind}</strong><span className={x.status === "approved" ? "text-emerald-400" : x.status === "qa_failed" ? "text-red-400" : "text-zinc-400"}>{x.status}</span></div>
                    <p className="text-sm text-zinc-400">{x.hook || "sem gancho"}</p>
                    {qa.problemas?.length ? <ul className="mt-1 text-xs text-red-300">{qa.problemas.map((p: Row, i: number) => <li key={i}>{p.regra}{p.itens?.length ? `: ${p.itens.join(", ")}` : ""}</li>)}</ul> : null}
                    <div className="mt-2 flex flex-wrap gap-3">
                        <button className="underline" onClick={() => run(async () => { const out = await request(`/commerce/v1/creatives/${x.id}/qa`, { method: "POST" }); aviso(out.ok ? "QA limpo" : `QA reprovou: ${out.problemas.map((p: Row) => p.regra).join(", ")}`); await refresh(); })}>Rodar QA</button>
                        {x.status !== "approved" && <button className="underline" onClick={() => run(async () => { await request(`/commerce/v1/creatives/${x.id}/approve`, { method: "POST" }); await refresh(); })}>Aprovar</button>}
                    </div>
                </article>;
            })}
        </div>
    </section>;
}

function Pacotes({ rows, produto, request, run, refresh, aviso }: Acoes & { rows: Row[]; produto: Row | null; aviso: (x: string) => void }) {
    if (!produto) return <section className={panel}><p className="text-zinc-400">Selecione um produto.</p></section>;
    return <section className={`${panel} space-y-4`}>
        <h2 className="text-lg font-bold">Pacotes para o Live Pilot — {produto.title}</h2>
        <p className="text-sm text-zinc-400">Só claims sustentados viram pontos de fala. Cada exportação cria uma versão nova; nenhuma é sobrescrita.</p>
        <button className={button} onClick={() => run(async () => { const out = await request(`/commerce/v1/products/${produto.id}/live-package`, { method: "POST" }); aviso(`Pacote v${out.version} com ${out.talking_points} ponto(s) de fala`); await refresh(); })}>Exportar pacote</button>
        {!rows.length && <p className="rounded-xl border border-dashed border-zinc-700 p-6 text-center text-zinc-400">Nenhum pacote exportado.</p>}
        <div className="grid gap-3 md:grid-cols-2">
            {rows.map(x => <article key={x.id} className="rounded-xl border border-zinc-800 p-3">
                <div className="flex justify-between"><strong>versão {x.version}</strong><span className="text-zinc-400">{new Date(x.created_at).toLocaleString()}</span></div>
                <code className="text-xs">checksum {String(x.checksum).slice(0, 16)}…</code>
            </article>)}
        </div>
    </section>;
}
