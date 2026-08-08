import { useState } from "react";
import type { ReactNode } from "react";
import { AlertTriangle, Camera, Mic, Pause, Play, Radio, ShoppingBag, Users, Wifi } from "lucide-react";

const products = ["Kit demonstrativo A", "Produto B", "Produto C"];
const script = ["Apresente o produto com suas próprias palavras e mostre o item na câmera.", "Demonstre a característica principal sem prometer resultado não cadastrado.", "Convide o público a perguntar sobre prazo e funcionamento."];
const comments = ["Tem garantia?", "Qual é o prazo de entrega?", "O desconto vale hoje?"];

export function ShopLive() {
  const [running, setRunning] = useState(false), [step, setStep] = useState(0), [product, setProduct] = useState(0);
  return <div className="space-y-5" data-testid="shop-live">
    <header className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-widest text-emerald-400">Módulo isolado · seed 42</p><h2 className="text-2xl font-bold">Shop LIVE Copiloto</h2></div><div className="flex gap-2"><span className="rounded-full border border-amber-500/40 px-3 py-2 text-xs text-amber-300">Simulação · sem ação externa</span><button onClick={() => setRunning(!running)} className={`flex items-center gap-2 rounded-lg px-4 py-2 font-semibold text-zinc-950 ${running ? "bg-amber-500" : "bg-emerald-500"}`}>{running ? <Pause size={16}/> : <Play size={16}/>} {running ? "Pausar" : "Iniciar simulação"}</button></div></header>
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><Health icon={Mic} label="Áudio" value="Ativo · -18 dB"/><Health icon={Camera} label="Vídeo" value="1080×1920 · 30 FPS"/><Health icon={Wifi} label="Conexão" value="Estável · 42 ms"/><Health icon={AlertTriangle} label="Conformidade" value="1 atenção" warning/></section>
    <section className="grid gap-4 xl:grid-cols-3">
      <Panel title="Preview local" icon={Radio}><div className="relative mx-auto aspect-[9/16] max-h-96 rounded-xl border border-zinc-700 bg-gradient-to-b from-zinc-800 to-zinc-950"><div className="absolute inset-0 grid place-items-center text-center text-zinc-500"><span><Camera className="mx-auto mb-2"/>Preview requer permissão local<br/>Nenhuma gravação ativa</span></div><b className="absolute left-3 top-3 rounded bg-red-500 px-2 py-1 text-xs">SIMULADO</b></div><div className="mt-3 grid grid-cols-2 gap-2"><Metric icon={Users} value="164 audiência"/><Metric icon={ShoppingBag} value="dados indisponíveis"/></div></Panel>
      <Panel title="Teleprompter" icon={Radio}><p className="text-sm text-zinc-500">Bloco {step + 1} de {script.length}</p><div className="my-4 flex min-h-52 items-center rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-6 text-xl font-medium">{script[step]}</div><button onClick={() => setStep(Math.min(step + 1, script.length - 1))} className="rounded-lg bg-zinc-100 px-4 py-2 text-zinc-950">Usado · avançar</button><div className="mt-5 rounded-xl border border-zinc-800 p-4"><small className="text-zinc-500">PRODUTO ATUAL</small><p className="font-semibold">{products[product]}</p><button onClick={() => setProduct((product + 1) % products.length)} className="mt-2 text-emerald-400">Próximo produto →</button></div></Panel>
      <Panel title="Comentários priorizados" icon={Users}><div className="space-y-3">{comments.map((text, i) => <article key={text} className="rounded-xl border border-zinc-800 p-3"><small className="text-emerald-400">prioridade {96 - i * 5}</small><p className="my-2 font-medium">{text}</p><p className="rounded bg-zinc-800 p-2 text-xs">Confirme esta informação antes de responder.</p></article>)}</div></Panel>
    </section>
  </div>;
}
function Panel({title, icon: Icon, children}: {title:string; icon:typeof Radio; children:ReactNode}) { return <div className="rounded-2xl border border-zinc-800 bg-zinc-900/70 p-4"><h3 className="mb-4 flex gap-2 font-semibold"><Icon size={18} className="text-emerald-400"/>{title}</h3>{children}</div> }
function Health({icon:Icon,label,value,warning=false}:{icon:typeof Mic;label:string;value:string;warning?:boolean}) { return <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 p-4"><p className="flex gap-2 text-sm text-zinc-400"><Icon size={16}/>{label}</p><b className={warning ? "text-amber-400" : "text-emerald-400"}>{value}</b></div> }
function Metric({icon:Icon,value}:{icon:typeof Users;value:string}) { return <div className="rounded-lg bg-zinc-800 p-3 text-sm"><Icon size={14}/>{value}</div> }
