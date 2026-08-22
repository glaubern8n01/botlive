// Produção em Massa — baixar em lote, editar em lote, exportar e postar.
// Módulo isolado: com VITE_MASS_ENABLED=false esta aba nem entra no bundle.
import { FormEvent, useEffect, useState } from "react";
import { AgenteLogin } from "../components/AgenteLogin";
import { ComoFunciona } from "../components/ComoFunciona";

type Tab = "download" | "editor" | "postador" | "historico" | "ajuda";
type Row = Record<string, any>;

// ?? e nao ||: no build do app Windows a variavel vem vazia de proposito,
// porque la a API serve o proprio painel (mesma origem, caminho relativo).
const API = import.meta.env.VITE_MASS_API_URL ?? "http://127.0.0.1:8825";
const tabs: [Tab, string][] = [
    ["download", "Download"], ["editor", "Editor"], ["postador", "Postador"],
    ["historico", "Histórico"], ["ajuda", "Ajuda"],
];
const panel = "rounded-2xl border border-zinc-800 bg-zinc-900/75 p-4";
const input = "min-h-11 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2";
const button = "min-h-11 rounded-lg bg-cyan-500 px-4 font-bold text-zinc-950 disabled:opacity-40";
const secondary = "min-h-10 rounded-lg border border-zinc-700 px-3 py-2";

const COR_STATUS: Record<string, string> = {
    completed: "text-emerald-400", running: "text-cyan-400", queued: "text-zinc-400",
    failed: "text-red-400", cancelled: "text-zinc-500", paused: "text-amber-400",
    manual_action_required: "text-amber-400",
};

export function ProducaoEmMassa() {
    const [tab, setTab] = useState<Tab>("download");
    // No app Windows o token e a senha do painel sao o mesmo valor, injetado na
    // hora de servir a pagina - evita digitar a mesma senha duas vezes. No painel
    // da VPS a variavel nao existe e o login por token continua igual.
    const [token, setToken] = useState(() => sessionStorage.getItem("mass_token")
        || (window as unknown as { __BOTLIVE_TOKEN__?: string }).__BOTLIVE_TOKEN__
        || "");
    const [projetos, setProjetos] = useState<Row[]>([]);
    const [projeto, setProjeto] = useState<string>("");
    const [saude, setSaude] = useState<Row | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");

    async function request(path: string, init: RequestInit = {}) {
        const r = await fetch(API + path, {
            ...init,
            headers: { "Content-Type": "application/json", "X-Mass-Token": token },
        });
        if (!r.ok) throw new Error((await r.text()) || `Erro ${r.status}`);
        return r.json();
    }

    async function run(work: () => Promise<void>) {
        setLoading(true); setError(""); setNotice("");
        try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "Falha inesperada"); } finally { setLoading(false); }
    }

    async function carregarProjetos() {
        setSaude(await (await fetch(API + "/mass/v1/health")).json());
        const lista = (await request("/mass/v1/projetos")).items || [];
        setProjetos(lista);
        if (!projeto && lista.length) setProjeto(lista[lista.length - 1].id);
    }

    useEffect(() => { if (token) void run(carregarProjetos); }, [token]);

    if (!token) return <AgenteLogin
        titulo="Produção em Massa"
        resumo="Baixa vários vídeos de uma vez, aplica a mesma edição em todos, gera o ZIP e manda pra fila de postagem. Tudo processado no seu computador."
        faz={[
            "Colar dezenas de links (ou importar um .txt) e baixar tudo",
            "Aplicar logo, mockup, CTA e formato 9:16 no lote inteiro",
            "Gerar prévia de 3s antes de processar 100 vídeos",
            "Exportar em ZIP e enfileirar pra postagem",
        ]}
        naoFaz="Os originais nunca são sobrescritos, e a postagem nasce em dry-run: monta tudo e para antes de confirmar."
        chaveSessao="mass_token"
        aoEntrar={setToken}
    />;

    const comum = { request, run, projeto, aviso: setNotice };

    return <main className="space-y-4" aria-busy={loading} data-testid="massa-module">
        <header className={panel}>
            <div className="flex flex-wrap justify-between gap-3">
                <div>
                    <p className="text-xs font-bold uppercase tracking-widest text-cyan-400">Feature flag · módulo isolado</p>
                    <h1 className="text-2xl font-bold">Produção em Massa</h1>
                    <p className="text-sm text-zinc-400">Baixar → Editar → Exportar → Postar. FFmpeg e yt-dlp rodando local, sem nuvem.</p>
                </div>
                <button className={secondary} onClick={() => { sessionStorage.removeItem("mass_token"); setToken(""); }}>Desconectar</button>
            </div>
            {saude && <p className="mt-3 text-sm text-zinc-400">
                Postador: <strong>{saude.postador?.modo === "api" ? "API oficial" : "navegador local"}</strong>
                {" · "}dry-run <strong className={saude.postador?.dry_run ? "text-emerald-400" : "text-amber-400"}>{saude.postador?.dry_run ? "ligado" : "desligado"}</strong>
                {" · "}editor com <strong>{saude.workers_editor}</strong> por rodada
                {" · "}{saude.processamento}
            </p>}
            <ProjetoSeletor projetos={projetos} projeto={projeto} setProjeto={setProjeto}
                request={request} run={run} recarregar={carregarProjetos} />
            <nav className="mt-4 flex gap-2 overflow-x-auto" aria-label="Etapas da produção">
                {tabs.map(([id, label]) => <button key={id} onClick={() => setTab(id)}
                    className={tab === id ? button : secondary} aria-current={tab === id ? "page" : undefined}>{label}</button>)}
            </nav>
        </header>

        <ComoFunciona
            passos={[
                { titulo: "Baixar", detalhe: "cole os links ou o perfil" },
                { titulo: "Editar", detalhe: "um template para o lote todo" },
                { titulo: "Exportar", detalhe: "ZIP, originais preservados", estado: "travado" },
                { titulo: "Postar", detalhe: "fila com intervalo", estado: "humano" },
            ]}
            aviso="Cada projeto tem pastas próprias: downloads/, editados/ e exports/. A edição nunca escreve por cima do que foi baixado — lote mal configurado se refaz sem perder a fonte."
        />

        {loading && <p role="status">Carregando…</p>}
        {error && <div role="alert" className="rounded-lg border border-red-700 bg-red-950/40 p-3">{error}</div>}
        {notice && <div role="status" className="rounded-lg border border-emerald-700 bg-emerald-950/40 p-3">{notice}</div>}

        {!projeto && tab !== "ajuda" && <div className={panel}><p className="text-zinc-400">Crie ou escolha um projeto acima para começar.</p></div>}
        {projeto && tab === "download" && <Download {...comum} />}
        {projeto && tab === "editor" && <Editor {...comum} />}
        {projeto && tab === "postador" && <Postador {...comum} saude={saude} />}
        {projeto && tab === "historico" && <Historico {...comum} />}
        {tab === "ajuda" && <Ajuda request={request} run={run} />}
    </main>;
}

type Comum = {
    request: (p: string, i?: RequestInit) => Promise<any>;
    run: (w: () => Promise<void>) => Promise<void>;
    projeto: string;
    aviso: (x: string) => void;
};

function ProjetoSeletor({ projetos, projeto, setProjeto, request, run, recarregar }: any) {
    const [nome, setNome] = useState("");
    return <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="text-sm text-zinc-400">Projeto:</span>
        <select className={input} value={projeto} onChange={e => setProjeto(e.target.value)}>
            <option value="">— escolha —</option>
            {projetos.map((p: Row) => <option key={p.id} value={p.id}>{p.nome}</option>)}
        </select>
        <input className={input} placeholder="Nome do novo projeto" value={nome} onChange={e => setNome(e.target.value)} />
        <button className={secondary} onClick={() => run(async () => {
            if (!nome.trim()) return;
            await request("/mass/v1/projetos", { method: "POST", body: JSON.stringify({ nome }) });
            setNome(""); await recarregar();
        })}>Criar projeto</button>
    </div>;
}

function Fila({ dados, onStatus }: { dados: Row | null; onStatus: (id: string, s: string) => void }) {
    if (!dados?.itens?.length) return <p className="rounded-xl border border-dashed border-zinc-700 p-6 text-center text-zinc-400">Fila vazia.</p>;
    const resumo: Row = dados.resumo || {};
    return <div className="space-y-2">
        <p className="text-sm text-zinc-400">
            {Object.entries(resumo).map(([k, v]) => <span key={k} className="mr-3">{k}: <strong className={COR_STATUS[k] || ""}>{String(v)}</strong></span>)}
        </p>
        <div className="max-h-96 overflow-y-auto rounded-xl border border-zinc-800">
            {dados.itens.map((x: Row) => <div key={x.id} className="flex items-center gap-3 border-b border-zinc-800 p-2 text-sm last:border-0">
                <span className={`w-40 shrink-0 font-bold ${COR_STATUS[x.status] || ""}`}>{x.status}</span>
                <span className="min-w-0 flex-1 truncate text-zinc-300">{x.titulo || x.url || x.saida || x.arquivo || x.entrada}</span>
                {x.erro && <span className="max-w-xs truncate text-xs text-red-300" title={x.erro}>{x.erro}</span>}
                {["queued", "paused", "failed"].includes(x.status) &&
                    <button className="shrink-0 text-xs underline" onClick={() => onStatus(x.id, x.status === "queued" ? "paused" : "queued")}>
                        {x.status === "queued" ? "pausar" : "retentar"}
                    </button>}
            </div>)}
        </div>
    </div>;
}

function Download({ request, run, projeto, aviso }: Comum) {
    const [texto, setTexto] = useState("");
    const [arquivo, setArquivo] = useState("");
    const [deteccao, setDeteccao] = useState<Row | null>(null);
    const [fila, setFila] = useState<Row | null>(null);
    const [perfil, setPerfil] = useState("");

    async function carregar() { setFila(await request(`/mass/v1/projetos/${projeto}/downloads`)); }
    useEffect(() => { if (projeto) void run(carregar); }, [projeto]);

    return <section className="space-y-4">
        <div className={`${panel} space-y-3`}>
            <h2 className="text-lg font-bold">1. De onde vêm os vídeos</h2>
            <textarea className={`${input} h-28 w-full font-mono text-xs`} placeholder={"Cole os links, um por linha:\nhttps://...\nhttps://..."} value={texto} onChange={e => setTexto(e.target.value)} />
            <div className="flex flex-wrap gap-2">
                <input className={`${input} flex-1`} placeholder="ou caminho de um links.txt" value={arquivo} onChange={e => setArquivo(e.target.value)} />
                <button className={secondary} onClick={() => run(async () => {
                    const r = await request("/mass/v1/links/detectar", { method: "POST", body: JSON.stringify({ texto, arquivo }) });
                    setDeteccao(r);
                })}>Detectar links</button>
                <button className={secondary} onClick={() => run(async () => {
                    const t = await navigator.clipboard.readText();
                    setTexto(t);
                    setDeteccao(await request("/mass/v1/links/detectar", { method: "POST", body: JSON.stringify({ texto: t }) }));
                })}>Colar da área de transferência</button>
            </div>

            {deteccao && <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-3">
                <p className="text-lg font-bold text-cyan-400">{deteccao.total} links detectados</p>
                <p className="text-sm text-zinc-400">
                    {Object.entries(deteccao.por_plataforma || {}).map(([k, v]) => `${k}: ${v}`).join(" · ")}
                </p>
                {(deteccao.avisos || []).map((a: string) => <p key={a} className="mt-1 text-xs text-amber-400">{a}</p>)}
                <button className={`${button} mt-3`} disabled={!deteccao.total} onClick={() => run(async () => {
                    const r = await request(`/mass/v1/projetos/${projeto}/downloads`, {
                        method: "POST", body: JSON.stringify({ urls: (deteccao.itens || []).map((i: Row) => i.url) }),
                    });
                    aviso(`${r.enfileirados} na fila · ${r.repetidos} já estavam`);
                    await carregar();
                })}>Adicionar {deteccao.total} à fila</button>
            </div>}
        </div>

        <div className={`${panel} space-y-3`}>
            <h2 className="text-lg font-bold">Ou listar um perfil inteiro</h2>
            <div className="flex flex-wrap gap-2">
                <input className={`${input} flex-1`} placeholder="https://instagram.com/perfil" value={perfil} onChange={e => setPerfil(e.target.value)} />
                <button className={secondary} onClick={() => run(async () => {
                    const r = await request("/mass/v1/perfil/listar", { method: "POST", body: JSON.stringify({ url: perfil, limite: 0 }) });
                    setDeteccao({ total: r.total, por_plataforma: { [r.plataforma]: r.total }, itens: r.itens, avisos: [] });
                    aviso(`${r.total} vídeos encontrados no perfil`);
                })}>Listar vídeos</button>
            </div>
            <p className="text-xs text-zinc-500">Só lista, não baixa. Confira o tamanho antes de mandar baixar tudo.</p>
        </div>

        <div className={`${panel} space-y-3`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-lg font-bold">Fila de download</h2>
                <div className="flex gap-2">
                    <button className={secondary} onClick={() => run(carregar)}>Atualizar</button>
                    <button className={button} onClick={() => run(async () => {
                        const r = await request(`/mass/v1/projetos/${projeto}/downloads/rodar`, { method: "POST", body: JSON.stringify({ maximo: 5 }) });
                        aviso(`${r.processados} processados`); await carregar();
                    })}>Baixar próximos 5</button>
                </div>
            </div>
            <Fila dados={fila} onStatus={(id, s) => run(async () => {
                await request(`/mass/v1/downloads/${id}/status?status=${s}`, { method: "POST" }); await carregar();
            })} />
        </div>
    </section>;
}

function Editor({ request, run, projeto, aviso }: Comum) {
    const vazio = { nome: "", formato: "9:16", modo_horizontal: "blur", logo_path: "", mockup_path: "", cta_texto: "", audio: "manter", velocidade: 1.0, cortar_inicio: 0, cortar_fim: 0 };
    const [form, setForm] = useState<any>(vazio);
    const [lista, setLista] = useState<Row[]>([]);
    const [escolhido, setEscolhido] = useState("");
    const [fila, setFila] = useState<Row | null>(null);
    const [amostra, setAmostra] = useState("");
    const [pasta, setPasta] = useState("");
    const [recursivo, setRecursivo] = useState(false);
    const [naPasta, setNaPasta] = useState<Row | null>(null);

    async function carregar() {
        setLista((await request("/mass/v1/templates")).items || []);
        setFila(await request(`/mass/v1/projetos/${projeto}/edicoes`));
    }
    useEffect(() => { if (projeto) void run(carregar); }, [projeto]);

    return <section className="space-y-4">
        <div className={`${panel} space-y-3`}>
            <h2 className="text-lg font-bold">2. Template — vale pro lote inteiro</h2>
            <form onSubmit={(e: FormEvent) => { e.preventDefault(); void run(async () => {
                await request("/mass/v1/templates", { method: "POST", body: JSON.stringify(form) });
                setForm(vazio); await carregar(); aviso("Template salvo");
            }); }} className="grid gap-2 md:grid-cols-3">
                <input className={input} placeholder="Nome do template" value={form.nome} onChange={e => setForm({ ...form, nome: e.target.value })} required />
                <select className={input} value={form.formato} onChange={e => setForm({ ...form, formato: e.target.value })}>
                    {["9:16", "4:5", "1:1", "16:9"].map(x => <option key={x} value={x}>{x}</option>)}
                </select>
                <select className={input} value={form.modo_horizontal} onChange={e => setForm({ ...form, modo_horizontal: e.target.value })}>
                    <option value="blur">horizontal: fundo borrado</option>
                    <option value="crop">horizontal: cortar</option>
                    <option value="fit">horizontal: barra preta</option>
                </select>
                <input className={input} placeholder="Caminho da logo (.png)" value={form.logo_path} onChange={e => setForm({ ...form, logo_path: e.target.value })} />
                <input className={input} placeholder="Mockup (.png, .webp ou .webm/.mov com transparência)" value={form.mockup_path} onChange={e => setForm({ ...form, mockup_path: e.target.value })} />
                <input className={input} placeholder="CTA (ex: COMPRE AGORA)" value={form.cta_texto} onChange={e => setForm({ ...form, cta_texto: e.target.value })} />
                <select className={input} value={form.audio} onChange={e => setForm({ ...form, audio: e.target.value })}>
                    <option value="manter">áudio: manter</option>
                    <option value="remover">áudio: remover</option>
                    <option value="normalizar">áudio: normalizar</option>
                </select>
                <input className={input} type="number" step="0.05" min="0.5" max="2" placeholder="velocidade" value={form.velocidade} onChange={e => setForm({ ...form, velocidade: Number(e.target.value) })} />
                <button className={button}>Salvar template</button>
            </form>
            <p className="text-xs text-zinc-500">Velocidade fora de 0.5–2.0 e logo acima de 40% da largura são recusadas — quebram o áudio ou cobrem o vídeo.</p>
            <p className="text-xs text-zinc-500">O mockup pode ser vídeo com transparência (.webm/.mov): ele entra em loop e termina junto com o vídeo de base.</p>
        </div>

        <div className={`${panel} space-y-3`}>
            <h2 className="text-lg font-bold">Processar o lote</h2>
            <div className="flex flex-wrap gap-2">
                <select className={input} value={escolhido} onChange={e => setEscolhido(e.target.value)}>
                    <option value="">— escolha o template —</option>
                    {lista.map(t => <option key={t.id} value={t.id}>{t.nome} ({t.formato})</option>)}
                </select>
                <button className={secondary} disabled={!escolhido} onClick={() => run(async () => {
                    const r = await request(`/mass/v1/projetos/${projeto}/edicoes`, {
                        method: "POST", body: JSON.stringify({ template_id: escolhido, usar_baixados: true }),
                    });
                    aviso(`${r.enfileirados} vídeos na fila de edição`); await carregar();
                })}>Adicionar baixados ao editor</button>
                <button className={button} disabled={!escolhido} onClick={() => run(async () => {
                    const r = await request(`/mass/v1/projetos/${projeto}/edicoes/rodar`, { method: "POST", body: JSON.stringify({ maximo: 3 }) });
                    aviso(`${r.processados} processados`); await carregar();
                })}>Editar próximos 3</button>
            </div>

            <div className="space-y-2 border-t border-zinc-800 pt-3">
                <p className="text-sm font-bold">Ou editar uma pasta que você já tem</p>
                <div className="flex flex-wrap gap-2">
                    <input className={`${input} flex-1`} placeholder="C:\BotLive\Downloads\Projeto01" value={pasta} onChange={e => setPasta(e.target.value)} />
                    <label className="flex items-center gap-2 text-sm text-zinc-400">
                        <input type="checkbox" checked={recursivo} onChange={e => setRecursivo(e.target.checked)} />
                        subpastas
                    </label>
                    <button className={secondary} disabled={!pasta} onClick={() => run(async () => {
                        const r = await request("/mass/v1/pasta/listar", { method: "POST", body: JSON.stringify({ caminho: pasta, recursivo }) });
                        setNaPasta(r); aviso(`${r.total} vídeos na pasta`);
                    })}>Conferir pasta</button>
                    <button className={button} disabled={!escolhido || !pasta} onClick={() => run(async () => {
                        const r = await request(`/mass/v1/projetos/${projeto}/edicoes`, {
                            method: "POST", body: JSON.stringify({ template_id: escolhido, pasta, recursivo }),
                        });
                        aviso(`${r.enfileirados} de ${r.encontrados} vídeos na fila`); await carregar();
                    })}>Adicionar pasta ao editor</button>
                </div>
                {naPasta && <p className="text-xs text-zinc-500">{naPasta.total} arquivo(s): {(naPasta.itens || []).slice(0, 4).map((x: string) => x.split(/[\/]/).pop()).join(", ")}{naPasta.total > 4 ? "…" : ""}</p>}
                <p className="text-xs text-zinc-500">Os originais não são tocados — a saída vai para <code>editados/</code> do projeto.</p>
            </div>

            <div className="flex flex-wrap gap-2 border-t border-zinc-800 pt-3">
                <input className={`${input} flex-1`} placeholder="Caminho de um vídeo para prévia de 3s" value={amostra} onChange={e => setAmostra(e.target.value)} />
                <button className={secondary} disabled={!escolhido || !amostra} onClick={() => run(async () => {
                    const r = await request("/mass/v1/previa", { method: "POST", body: JSON.stringify({ entrada: amostra, template_id: escolhido, segundos: 3 }) });
                    aviso(`Prévia gerada: ${r.arquivo}`);
                })}>Gerar prévia</button>
            </div>
            <p className="text-xs text-zinc-500">Confira a prévia antes de processar 100 vídeos — é 3 segundos em vez de horas.</p>

            {fila && <p className="text-sm">Progresso: <strong className="text-cyan-400">{Math.round((fila.progresso || 0) * 100)}%</strong></p>}
            <Fila dados={fila} onStatus={(id, s) => run(async () => {
                await request(`/mass/v1/edicoes/${id}/status?status=${s}`, { method: "POST" }); await carregar();
            })} />
        </div>
    </section>;
}

function Postador({ request, run, projeto, aviso, saude }: Comum & { saude: Row | null }) {
    const [descricao, setDescricao] = useState("");
    const [hashtags, setHashtags] = useState("");
    const [fila, setFila] = useState<Row | null>(null);
    const [exportacao, setExportacao] = useState<Row | null>(null);

    async function carregar() {
        setFila(await request(`/mass/v1/projetos/${projeto}/publicacoes`));
        setExportacao(await request(`/mass/v1/projetos/${projeto}/export`));
    }
    useEffect(() => { if (projeto) void run(carregar); }, [projeto]);

    const local = saude?.postador?.modo === "local";

    return <section className="space-y-4">
        <div className={`${panel} space-y-3`}>
            <h2 className="text-lg font-bold">3. Exportar</h2>
            {exportacao && <p className="text-sm text-zinc-400">
                {exportacao.prontos} prontos · {exportacao.tamanho_mb} MB · {exportacao.zips?.length || 0} ZIP(s)
            </p>}
            <div className="flex flex-wrap gap-2">
                <button className={secondary} onClick={() => run(async () => {
                    const r = await request(`/mass/v1/projetos/${projeto}/export/zip`, { method: "POST" });
                    aviso(`ZIP com ${r.arquivos} vídeos (${r.tamanho_mb} MB)`); await carregar();
                })}>Gerar ZIP</button>
            </div>
            {exportacao && <p className="text-xs text-zinc-500">Pasta: {exportacao.pasta_exports}</p>}
        </div>

        <div className={`${panel} space-y-3`}>
            <h2 className="text-lg font-bold">4. Postar</h2>
            {local && <p className="rounded-xl border border-amber-800/60 bg-amber-950/30 p-3 text-sm text-amber-200">
                <strong>Modo navegador local.</strong> Automatizar o app do Instagram vai contra os termos dele e pode custar a conta.
                O modo API oficial não tem esse risco.
            </p>}
            {local && <Sessao request={request} run={run} aviso={aviso} />}
            {saude?.ensaio_no_navegador && <p className="text-xs text-cyan-400">
                Ensaio no navegador ligado: o dry-run abre a tela, carrega o vídeo e para antes de Compartilhar.
            </p>}
            <textarea className={`${input} h-20 w-full`} placeholder="Descrição para todos" value={descricao} onChange={e => setDescricao(e.target.value)} />
            <input className={`${input} w-full`} placeholder="hashtags separadas por espaço" value={hashtags} onChange={e => setHashtags(e.target.value)} />
            <div className="flex flex-wrap gap-2">
                <button className={secondary} onClick={() => run(async () => {
                    const r = await request(`/mass/v1/projetos/${projeto}/publicacoes`, {
                        method: "POST", body: JSON.stringify({
                            usar_editados: true, descricao,
                            hashtags: hashtags.split(/\s+/).filter(Boolean),
                        }),
                    });
                    aviso(`${r.enfileirados} na fila · ${r.repetidos} já estavam`); await carregar();
                })}>Enfileirar editados</button>
                <button className={button} onClick={() => run(async () => {
                    const r = await request(`/mass/v1/projetos/${projeto}/publicacoes/rodar`, { method: "POST", body: JSON.stringify({ maximo: 1 }) });
                    aviso(`${r.processados} processado(s)`); await carregar();
                })}>Rodar fila (1)</button>
            </div>
            <Fila dados={fila} onStatus={(id, s) => run(async () => {
                await request(`/mass/v1/publicacoes/${id}/status?status=${s}`, { method: "POST" }); await carregar();
            })} />
        </div>
    </section>;
}

function Sessao({ request, run, aviso }: { request: any; run: any; aviso: (x: string) => void }) {
    const [conta, setConta] = useState("principal");
    const [estado, setEstado] = useState<Row | null>(null);

    async function checar() { setEstado(await request(`/mass/v1/sessao/${conta}`)); }
    useEffect(() => { void run(checar); }, [conta]);

    return <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-3 space-y-2">
        <p className="text-sm">
            Instagram: <strong className={estado?.salva ? "text-emerald-400" : "text-amber-400"}>
                {estado?.salva ? "● conectado" : "○ sem sessão salva"}
            </strong>
        </p>
        <div className="flex flex-wrap gap-2">
            <input className={input} value={conta} onChange={e => setConta(e.target.value)} placeholder="conta" />
            <button className={secondary} onClick={() => run(async () => {
                await request(`/mass/v1/sessao/${conta}/login`, { method: "POST" });
                aviso("Sessão salva"); await checar();
            })}>Abrir Instagram para login</button>
            <button className={secondary} onClick={() => run(checar)}>Conferir</button>
        </div>
        <p className="text-xs text-zinc-500">
            O navegador abre e <strong>você</strong> faz o login à mão — o BotLive não digita senha, não resolve captcha e não toca no 2FA.
            Se o Instagram pedir confirmação no meio da postagem, o item para como <em>ação manual necessária</em>.
        </p>
    </div>;
}

function Historico({ request, run, projeto }: Comum) {
    const [dados, setDados] = useState<Row | null>(null);
    useEffect(() => { if (projeto) void run(async () => setDados(await request(`/mass/v1/projetos/${projeto}/historico`))); }, [projeto]);
    if (!dados) return <div className={panel}><p className="text-zinc-400">Sem dados.</p></div>;
    return <section className={`${panel} space-y-3`}>
        <h2 className="text-lg font-bold">{dados.projeto}</h2>
        <div className="grid gap-3 md:grid-cols-4">
            {[["Baixados", dados.totais.baixados], ["Editados", dados.totais.editados],
              ["Publicados", dados.totais.publicados], ["Falhas", dados.totais.falhas]].map(([r, v]) =>
                <div key={String(r)} className="rounded-xl border border-zinc-800 p-3">
                    <p className="text-sm text-zinc-400">{r}</p>
                    <p className={`text-2xl font-bold ${r === "Falhas" && Number(v) > 0 ? "text-red-400" : ""}`}>{String(v)}</p>
                </div>)}
        </div>
        <p className="text-xs text-zinc-500">Pasta: {dados.pasta} · criado em {new Date(dados.criado_em).toLocaleString()}</p>
    </section>;
}

function Ajuda({ request, run }: { request: any; run: any }) {
    const [topicos, setTopicos] = useState<Row[]>([]);
    useEffect(() => { void run(async () => setTopicos((await request("/mass/v1/ajuda")).topicos || [])); }, []);
    return <section className={`${panel} space-y-3`}>
        <h2 className="text-lg font-bold">Ajuda</h2>
        <div className="grid gap-3 md:grid-cols-2">
            {topicos.map(t => <article key={t.titulo} className="rounded-xl border border-zinc-800 p-3">
                <h3 className="font-bold">{t.titulo}</h3>
                <ol className="mt-2 space-y-1 text-sm text-zinc-400">
                    {(t.passos || []).map((p: string, i: number) => <li key={i}>{i + 1}. {p}</li>)}
                </ol>
            </article>)}
        </div>
    </section>;
}
