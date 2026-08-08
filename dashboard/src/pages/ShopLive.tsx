import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { AlertTriangle, Camera, Mic, Pause, Play, Radio, RotateCcw, ShoppingBag, Square, Users, Wifi } from "lucide-react";

type LiveEvent = { type: string; sequence?: number; payload: Record<string, unknown> };
type AuditEvent = { id:string; type:string; result:string; created_at:string; payload:Record<string,unknown> };
type Comment = { id:string; author:string; text:string; intent:string; priority:number };
type State = "conectando"|"pronto"|"executando"|"pausada"|"offline";
const API = import.meta.env.VITE_SHOP_LIVE_API_URL || "http://127.0.0.1:8765";

export function ShopLive() {
  const socket = useRef<WebSocket | null>(null);
  const [token, setToken] = useState(() => sessionStorage.getItem("shop_live_token") || "");
  const [draftToken, setDraftToken] = useState("");
  const [connection, setConnection] = useState<State>("conectando");
  const [viewers, setViewers] = useState<number|null>(null), [comments,setComments] = useState<Comment[]>([]);
  const [orders,setOrders] = useState(0), [revenue,setRevenue] = useState(0);
  const [audio,setAudio] = useState("aguardando sinal"), [video,setVideo] = useState("aguardando sinal"), [network,setNetwork] = useState("conectando ao agente");
  const [alerts,setAlerts] = useState<LiveEvent[]>([]), [transient,setTransient] = useState<LiveEvent[]>([]), [persisted,setPersisted] = useState<AuditEvent[]>([]);

  async function refreshAudit(activeToken = token) {
    if (!activeToken) return;
    const response = await fetch(`${API}/shop-live/v1/audit?limit=40&offset=0`, {headers:{"X-Shop-Live-Token":activeToken}});
    if (response.ok) setPersisted((await response.json()).items);
    if (response.status === 401) { sessionStorage.removeItem("shop_live_token"); setToken(""); }
  }

  useEffect(() => {
    if (!token) return;
    const ws = new WebSocket(`${API.replace(/^http/, "ws")}/shop-live/v1/events?token=${encodeURIComponent(token)}`); socket.current = ws;
    ws.onopen = () => { setConnection("conectando"); setNetwork("autenticando agente"); };
    ws.onclose = () => { setConnection("offline"); setNetwork("agente indisponível"); };
    ws.onerror = () => setConnection("offline");
    ws.onmessage = message => {
      const event = JSON.parse(message.data) as LiveEvent; setTransient(old => [event,...old].slice(0,60));
      if (["simulation.ready","simulation.stopped","simulation.completed"].includes(event.type)) setConnection("pronto");
      if (["simulation.started","simulation.resumed"].includes(event.type)) setConnection("executando");
      if (event.type === "simulation.paused") setConnection("pausada");
      if (event.type === "viewer.count_changed") setViewers(Number(event.payload.count));
      if (event.type === "comment.received") setComments(old => [event.payload as unknown as Comment,...old].sort((a,b)=>b.priority-a.priority).slice(0,8));
      if (event.type === "order.detected") { setOrders(old=>old+Number(event.payload.quantity)); setRevenue(old=>old+Number(event.payload.amount)); }
      if (event.type === "audio.level") setAudio(`${event.payload.db} dB · ativo`);
      if (event.type === "audio.muted") setAudio("microfone mutado");
      if (event.type === "video.freeze_seconds") setVideo(`congelada há ${event.payload.value}s`);
      if (event.type === "connection.packet_loss") setNetwork(`degradada · ${Math.round(Number(event.payload.value)*100)}% perda`);
      if (event.type === "connection.recovered") setNetwork(`${event.payload.latency_ms} ms · recuperada`);
      if (event.type === "compliance.warning_received") setAlerts(old => [event,...old].slice(0,8));
    };
    void refreshAudit(token); const timer = window.setInterval(() => void refreshAudit(token), 1000);
    return () => { window.clearInterval(timer); ws.close(); };
  }, [token]);

  const latest = useMemo(()=>transient[0]?.type ?? "nenhum evento temporário",[transient]);
  function command(action:"start"|"pause"|"resume"|"stop") {
    if (socket.current?.readyState !== WebSocket.OPEN) return;
    if (action === "start") { setViewers(null);setComments([]);setOrders(0);setRevenue(0);setAlerts([]); }
    socket.current.send(JSON.stringify({action,speed:2}));
  }
  function authenticate(event:FormEvent) { event.preventDefault(); const clean=draftToken.trim(); if(clean){sessionStorage.setItem("shop_live_token",clean);setToken(clean);} }

  if (!token) return <form onSubmit={authenticate} className="mx-auto max-w-md rounded-2xl border border-zinc-800 bg-zinc-900 p-6"><h2 className="text-xl font-bold">Autenticação local do Shop LIVE</h2><p className="my-3 text-sm text-zinc-400">Informe o token configurado no agente local. Ele ficará apenas nesta aba.</p><input type="password" value={draftToken} onChange={e=>setDraftToken(e.target.value)} className="w-full rounded-lg border border-zinc-700 bg-zinc-950 p-3" autoComplete="off"/><button className="mt-3 rounded-lg bg-emerald-500 px-4 py-2 font-semibold text-zinc-950">Conectar</button></form>;

  const actionDisabled = connection === "conectando" || connection === "offline";
  return <div className="space-y-5" data-testid="shop-live">
    <header className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-widest text-emerald-400">FastAPI + WebSocket · seed 42</p><h2 className="text-2xl font-bold">Shop LIVE Copiloto</h2></div><div className="flex gap-2">{connection === "pronto" && <Action onClick={()=>command("start")} icon={Play} label="Iniciar cenário"/>}{connection === "executando" && <><Action onClick={()=>command("pause")} icon={Pause} label="Pausar"/><Action onClick={()=>command("stop")} icon={Square} label="Encerrar" danger/></>}{connection === "pausada" && <><Action onClick={()=>command("resume")} icon={RotateCcw} label="Continuar"/><Action onClick={()=>command("stop")} icon={Square} label="Encerrar" danger/></>}{actionDisabled && <Action disabled icon={Wifi} label={connection === "offline" ? "Agente offline" : "Conectando"}/>}</div></header>
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><Health icon={Mic} label="Áudio" value={audio} warning={audio.includes("mutado")}/><Health icon={Camera} label="Vídeo" value={video} warning={video.includes("congelada")}/><Health icon={Wifi} label="Conexão" value={network} warning={connection==="offline"||network.includes("degradada")}/><Health icon={AlertTriangle} label="Conformidade" value={alerts.length?`${alerts.length} alerta(s)`:"sem alerta recebido"} warning={alerts.length>0}/></section>
    <section className="grid gap-4 xl:grid-cols-3"><Panel title="Operação ao vivo" icon={Radio}><div className="grid grid-cols-2 gap-3"><Metric icon={Users} value={viewers===null?"aguardando":`${viewers} audiência`}/><Metric icon={ShoppingBag} value={`${orders} pedidos · R$ ${revenue.toFixed(2)}`}/></div><p className="mt-4 text-sm">Estado: {connection}</p><p className="text-sm text-zinc-500">Último temporário: {latest}</p>{alerts.map((a,i)=><div key={i} className="mt-2 rounded border border-amber-500/30 p-2 text-sm"><b>{String(a.payload.rule)}</b> · {String(a.payload.problem)}</div>)}</Panel><Panel title="Comentários priorizados" icon={Users}>{comments.length?comments.map(c=><article key={c.id} className="mb-2 rounded-xl border border-zinc-800 p-3"><small className="text-emerald-400">{c.intent} · {c.priority}</small><p>{c.text}</p></article>):<p className="text-zinc-500">Aguardando eventos temporários.</p>}</Panel><Panel title="Eventos persistidos · auditoria" icon={ShoppingBag}><div className="max-h-96 space-y-2 overflow-auto">{persisted.map(event=><div key={event.id} className="rounded bg-zinc-950/60 p-2 text-xs"><div className="flex justify-between"><span>{event.type}</span><span className="text-zinc-500">persistido</span></div><time className="text-zinc-600">{new Date(event.created_at).toLocaleTimeString("pt-BR")}</time></div>)}</div></Panel></section>
  </div>;
}
function Action({onClick,icon:Icon,label,disabled=false,danger=false}:{onClick?:()=>void;icon:typeof Play;label:string;disabled?:boolean;danger?:boolean}){return <button disabled={disabled} onClick={onClick} className={`flex items-center gap-2 rounded-lg px-4 py-2 font-semibold text-zinc-950 disabled:bg-zinc-700 disabled:text-zinc-400 ${danger?"bg-red-400":"bg-emerald-500"}`}><Icon size={16}/>{label}</button>}
function Panel({title,icon:Icon,children}:{title:string;icon:typeof Radio;children:ReactNode}){return <div className="rounded-2xl border border-zinc-800 bg-zinc-900/70 p-4"><h3 className="mb-4 flex gap-2 font-semibold"><Icon size={18} className="text-emerald-400"/>{title}</h3>{children}</div>}
function Health({icon:Icon,label,value,warning=false}:{icon:typeof Mic;label:string;value:string;warning?:boolean}){return <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 p-4"><p className="flex gap-2 text-sm text-zinc-400"><Icon size={16}/>{label}</p><b className={warning?"text-amber-400":"text-emerald-400"}>{value}</b></div>}
function Metric({icon:Icon,value}:{icon:typeof Users;value:string}){return <div className="rounded-lg bg-zinc-800 p-3 text-sm"><Icon size={14}/>{value}</div>}
