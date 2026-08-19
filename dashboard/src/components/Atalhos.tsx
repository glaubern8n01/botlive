// Direcionamento para as plataformas de verdade.
//
// O painel mostra o que o bot fez, mas conferir o resultado exigia sair e
// procurar o site na mão. Aqui cada plataforma tem o link direto para o lugar
// onde o vídeo realmente aparece.
const CARTAO = "flex items-center gap-3 rounded-xl border border-zinc-800 bg-zinc-950/60 p-3 transition hover:border-cyan-700 hover:bg-zinc-900";

type Destino = {
    nome: string;
    onde: string;
    url: string;
    icone: string;
};

export const PLATAFORMAS: Destino[] = [
    {
        nome: "YouTube",
        onde: "Studio do canal — vê os cortes postados, views e comentários",
        url: "https://studio.youtube.com/channel/UCv8ZMRZVXjyZUqCLUgnCETw/videos/upload",
        icone: "▶",
    },
    {
        nome: "Instagram",
        onde: "Perfil @gta6brasilcortes — confere os Reels publicados",
        url: "https://www.instagram.com/gta6brasilcortes/reels/",
        icone: "◎",
    },
    {
        nome: "TikTok",
        onde: "Caixa de rascunhos — os cortes chegam aqui antes de postar",
        url: "https://www.tiktok.com/tiktokstudio/content",
        icone: "♪",
    },
    {
        nome: "Kwai",
        onde: "Painel de criador do Kwai",
        url: "https://www.kwai.com/",
        icone: "K",
    },
];

export const OPERACAO: Destino[] = [
    {
        nome: "EasyPanel",
        onde: "Serviços da VPS: ligar, parar, ver logs",
        url: "https://easypanel.gmspeed.com/projects/botlive",
        icone: "⚙",
    },
    {
        nome: "Supabase",
        onde: "Banco: canais vigiados, cortes e histórico",
        url: "https://supabase.com/dashboard",
        icone: "▤",
    },
];

function Cartao({ d }: { d: Destino }) {
    return <a className={CARTAO} href={d.url} target="_blank" rel="noreferrer">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-zinc-800 text-lg">{d.icone}</span>
        <span className="min-w-0">
            <span className="block font-bold">{d.nome}</span>
            <span className="block text-sm text-zinc-400">{d.onde}</span>
        </span>
        <span className="ml-auto shrink-0 text-zinc-600">↗</span>
    </a>;
}

export function Atalhos({ titulo = "Ir direto para a plataforma", destinos = PLATAFORMAS }: { titulo?: string; destinos?: Destino[] }) {
    return <section className="rounded-2xl border border-zinc-800 bg-zinc-900/75 p-4">
        <h2 className="text-lg font-bold">{titulo}</h2>
        <p className="text-sm text-zinc-400">Abre em uma aba nova, direto no lugar onde o conteúdo aparece.</p>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
            {destinos.map(d => <div key={d.nome}><Cartao d={d} /></div>)}
        </div>
    </section>;
}
