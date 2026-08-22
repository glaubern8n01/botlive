// Tela de entrada dos agentes locais.
//
// A versao anterior pedia "Token local" e mais nada — quem abria nao tinha
// como saber o que era aquilo, de onde tirar, nem o que a tela fazia. Aqui
// a tela explica o que e o modulo, o que ele NAO faz, e mostra o comando
// exato que revela o token.
import { FormEvent, useState } from "react";

const panel = "rounded-2xl border border-zinc-800 bg-zinc-900/75 p-5";
const input = "min-h-11 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2";
const button = "min-h-11 rounded-lg bg-cyan-500 px-4 font-bold text-zinc-950 disabled:opacity-40";

type Props = {
    titulo: string;
    resumo: string;
    faz: string[];
    naoFaz: string;
    chaveSessao: string;
    aoEntrar: (token: string) => void;
};

const COMANDO = "ssh root@69.62.96.161 cat /root/agents-tokens.txt";

export function AgenteLogin({ titulo, resumo, faz, naoFaz, chaveSessao, aoEntrar }: Props) {
    const [draft, setDraft] = useState("");
    const [copiado, setCopiado] = useState(false);

    function entrar(e: FormEvent) {
        e.preventDefault();
        sessionStorage.setItem(chaveSessao, draft);
        aoEntrar(draft);
    }

    return <main className="mx-auto max-w-2xl space-y-4">
        <section className={`${panel} space-y-3`}>
            <h1 className="text-2xl font-bold">{titulo}</h1>
            <p className="text-zinc-300">{resumo}</p>

            <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-3">
                <h2 className="text-sm font-bold uppercase tracking-wide text-cyan-400">O que dá pra fazer aqui</h2>
                <ul className="mt-2 space-y-1 text-sm text-zinc-300">
                    {faz.map(x => <li key={x}>• {x}</li>)}
                </ul>
            </div>

            <p className="rounded-xl border border-emerald-800/60 bg-emerald-950/30 p-3 text-sm text-emerald-200">
                <strong>Nada é publicado por esta tela.</strong> {naoFaz}
            </p>
        </section>

        <form onSubmit={entrar} className={`${panel} space-y-3`}>
            <h2 className="text-lg font-bold">Entrar</h2>
            <p className="text-sm text-zinc-400">
                Esta tela é protegida por uma senha própria, criada só para os módulos novos.
                Ela <strong>não</strong> é a senha do painel, nem do YouTube, do Instagram, do TikTok ou do Kwai —
                e nada do que já funcionava depende dela.
            </p>

            <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-3">
                <p className="text-sm text-zinc-400">Para descobrir a senha, rode no seu computador:</p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                    <code className="flex-1 break-all rounded-lg bg-black/50 p-2 text-xs text-cyan-300">{COMANDO}</code>
                    <button
                        type="button"
                        className="min-h-10 rounded-lg border border-zinc-700 px-3 text-sm"
                        onClick={() => {
                            void navigator.clipboard?.writeText(COMANDO);
                            setCopiado(true);
                            setTimeout(() => setCopiado(false), 2000);
                        }}
                    >{copiado ? "copiado" : "copiar"}</button>
                </div>
                <p className="mt-2 text-xs text-zinc-500">
                    A saída traz uma linha por módulo. Use a que começa com o nome deste aqui.
                </p>
            </div>

            <input
                className={`${input} w-full`}
                type="password"
                placeholder="Cole a senha aqui"
                value={draft}
                onChange={e => setDraft(e.target.value)}
                required
            />
            <button className={`${button} w-full`}>Entrar</button>
        </form>
    </main>;
}
