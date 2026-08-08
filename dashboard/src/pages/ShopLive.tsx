import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { AlertTriangle, Camera, Mic, Pause, Play, Radio, ShoppingBag, Users, Wifi } from "lucide-react";

type LiveEvent = { type: string; sequence?: number; payload: Record<string, unknown> };
type Comment = { id: string; author: string; text: string; intent: string; priority: number };
const API = import.meta.env.VITE_SHOP_LIVE_API_URL || "http://127.0.0.1:8765";
const WS = API.replace(/^http/, "ws") + "/shop-live/v1/events";

export function ShopLive() {
  const socket = useRef<WebSocket | null>(null);
  const [connection, setConnection] = useState<"conectando"|"pronto"|"executando"|"offline">("conectando");
  const [viewers, setViewers] = useState<number | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [orders, setOrders] = useState(0);
  const [revenue, setRevenue] = useState(0);
  const [audio, setAudio] = useState("aguardando sinal");
  const [video, setVideo] = useState("aguardando sinal");
  const [network, setNetwork] = useState("conectando ao agente");
  const [alerts, setAlerts] = useState<LiveEvent[]>([]);
  const [events, setEvents] = useState<LiveEvent[]>([]);

  useEffect(() => {
    const ws = new WebSocket(WS); socket.current = ws;
    ws.onopen = () => { setConnection("pronto"); setNetwork("agente conectado"); };
    ws.onclose = () => { setConnection("offline"); setNetwork("agente indisponível"); };
    ws.onerror = () => setConnection("offline");
    ws.onmessage = message => {
      const event = JSON.parse(message.data) as LiveEvent;
      setEvents(old => [event, ...old].slice(0, 60));
      if (event.type === "simulation.ready") setConnection("pronto");
      if (event.type === "session.started") setConnection("executando");
      if (event.type === "session.ended") setConnection("pronto");
      if (event.type === "viewer.count_changed") setViewers(Number(event.payload.count));
      if (event.type === "comment.received") setComments(old => [event.payload as unknown as Comment, ...old].sort((a,b) => b.priority-a.priority).slice(0,8));
      if (event.type === "order.detected") { setOrders(old => old + Number(event.payload.quantity)); setRevenue(old => old + Number(event.payload.amount)); }
      if (event.type === "audio.level") setAudio(`${event.payload.db} dB · ativo`);
      if (event.type === "audio.muted") setAudio("microfone mutado");
      if (event.type === "video.freeze_seconds") setVideo(`congelada há ${event.payload.value}s`);
      if (event.type === "connection.packet_loss") setNetwork(`degradada · ${Math.round(Number(event.payload.value)*100)}% perda`);
      if (event.type === "connection.recovered") setNetwork(`${event.payload.latency_ms} ms · recuperada`);
      if (event.type === "compliance.warning_received") setAlerts(old => [event, ...old].slice(0,8));
    };
    return () => ws.close();
  }, []);

  const running = connection === "executando";
  const latest = useMemo(() => events[0]?.type ?? "nenhum evento", [events]);
  function start() { if (socket.current?.readyState === WebSocket.OPEN) { setViewers(null); setComments([]); setOrders(0); setRevenue(0); setAlerts([]); socket.current.send(JSON.stringify({speed: 2})); } }

  return <div className="space-y-5" data-testid="shop-live">
    <header className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-widest text-emerald-400">FastAPI + WebSocket · simulação seed 42</p><h2 className="text-2xl font-bold">Shop LIVE Copiloto</h2></div><button disabled={connection !== "pronto"} onClick={start} className="flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 font-semibold text-zinc-950 disabled:opacity-40">{running ? <Pause size={16}/> : <Play size={16}/>} {running ? "Simulação em curso" : "Iniciar cenário"}</button></header>
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><Health icon={Mic} label="Áudio" value={audio} warning={audio.includes("mutado")}/><Health icon={Camera} label="Vídeo" value={video} warning={video.includes("congelada")}/><Health icon={Wifi} label="Conexão" value={network} warning={connection === "offline" || network.includes("degradada")}/><Health icon={AlertTriangle} label="Conformidade" value={alerts.length ? `${alerts.length} alerta(s)` : "sem alerta recebido"} warning={alerts.length > 0}/></section>
    <section className="grid gap-4 xl:grid-cols-3">
      <Panel title="Operação ao vivo" icon={Radio}><div className="grid grid-cols-2 gap-3"><Metric icon={Users} value={viewers === null ? "aguardando" : `${viewers} audiência`}/><Metric icon={ShoppingBag} value={`${orders} pedidos · R$ ${revenue.toFixed(2)}`}/></div><p className="mt-4 text-sm text-zinc-400">Estado: {connection}</p><p className="mt-1 text-sm text-zinc-500">Último evento: {latest}</p><div className="mt-4 max-h-64 space-y-2 overflow-auto">{alerts.map((a,i)=><div key={i} className="rounded border border-amber-500/30 bg-amber-500/10 p-3 text-sm"><b className="text-amber-300">{String(a.payload.rule)}</b><p>{String(a.payload.problem)}</p><small>{String(a.payload.correction)}</small></div>)}</div></Panel>
      <Panel title="Comentários priorizados" icon={Users}>{comments.length === 0 ? <p className="text-zinc-500">Aguardando eventos do simulador.</p> : <div className="space-y-3">{comments.map(c=><article key={c.id} className="rounded-xl border border-zinc-800 p-3"><small className="text-emerald-400">{c.intent} · prioridade {c.priority}</small><p className="my-2 font-medium">{c.text}</p><p className="rounded bg-zinc-800 p-2 text-xs">Confirme esta informação antes de responder.</p></article>)}</div>}</Panel>
      <Panel title="Eventos persistidos" icon={ShoppingBag}><div className="max-h-96 space-y-2 overflow-auto">{events.map((event,i)=><div key={`${event.sequence}-${i}`} className="flex justify-between rounded bg-zinc-950/60 p-2 text-xs"><span>{event.type}</span><span className="text-zinc-500">#{event.sequence ?? "—"}</span></div>)}</div></Panel>
    </section>
  </div>;
}
function Panel({title,icon:Icon,children}:{title:string;icon:typeof Radio;children:ReactNode}) { return <div className="rounded-2xl border border-zinc-800 bg-zinc-900/70 p-4"><h3 className="mb-4 flex gap-2 font-semibold"><Icon size={18} className="text-emerald-400"/>{title}</h3>{children}</div> }
function Health({icon:Icon,label,value,warning=false}:{icon:typeof Mic;label:string;value:string;warning?:boolean}) { return <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 p-4"><p className="flex gap-2 text-sm text-zinc-400"><Icon size={16}/>{label}</p><b className={warning ? "text-amber-400" : "text-emerald-400"}>{value}</b></div> }
function Metric({icon:Icon,value}:{icon:typeof Users;value:string}) { return <div className="rounded-lg bg-zinc-800 p-3 text-sm"><Icon size={14}/>{value}</div> }
