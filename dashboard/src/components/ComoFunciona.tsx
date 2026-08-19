// Explicador do caminho que o vídeo percorre dentro de cada módulo.
//
// As telas mostravam formulários sem dizer onde aquilo desemboca. Quem abre
// precisa enxergar: de onde sai, por onde passa, quem aprova e onde termina.
const passoBase = "flex-1 min-w-[130px] rounded-xl border p-3";

type Passo = {
    titulo: string;
    detalhe: string;
    estado?: "feito" | "humano" | "travado";
};

type Props = {
    titulo?: string;
    passos: Passo[];
    aviso?: string;
};

const CORES = {
    feito: "border-zinc-800 bg-zinc-900/60",
    humano: "border-amber-800/60 bg-amber-950/20",
    travado: "border-emerald-800/60 bg-emerald-950/20",
};

export function ComoFunciona({ titulo = "Como o vídeo caminha", passos, aviso }: Props) {
    return <section className="rounded-2xl border border-zinc-800 bg-zinc-900/75 p-4">
        <h2 className="text-lg font-bold">{titulo}</h2>
        <div className="mt-3 flex flex-wrap items-stretch gap-2">
            {passos.map((p, i) => <div key={p.titulo} className="flex flex-1 items-stretch gap-2">
                <article className={`${passoBase} ${CORES[p.estado || "feito"]}`}>
                    <p className="text-xs font-bold uppercase tracking-wide text-zinc-500">passo {i + 1}</p>
                    <p className="font-bold">{p.titulo}</p>
                    <p className="text-sm text-zinc-400">{p.detalhe}</p>
                    {p.estado === "humano" && <p className="mt-1 text-xs text-amber-400">depende de você</p>}
                    {p.estado === "travado" && <p className="mt-1 text-xs text-emerald-400">trava de segurança</p>}
                </article>
                {i < passos.length - 1 && <span className="self-center text-zinc-600">→</span>}
            </div>)}
        </div>
        {aviso && <p className="mt-3 rounded-xl border border-zinc-800 bg-zinc-950/60 p-3 text-sm text-zinc-300">{aviso}</p>}
    </section>;
}

// Estado vazio que ensina, em vez de só dizer "nenhum item".
export function Vazio({ oQueE, comoComecar }: { oQueE: string; comoComecar: string }) {
    return <div className="rounded-xl border border-dashed border-zinc-700 p-6 text-center">
        <p className="text-zinc-300">{oQueE}</p>
        <p className="mt-2 text-sm text-zinc-500">{comoComecar}</p>
    </div>;
}
