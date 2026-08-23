from __future__ import annotations
import json,os,socket,time,traceback
from datetime import datetime,timedelta,timezone
from pathlib import Path
from . import engine
from .queue import claim,enqueue,heartbeat,recover_orphans,transition
from .rules import evaluate,summary
from .store import ROOT,audit,connect,get,insert,now,uid,update

def duplicado(candidate,output_sha256):
    """Procura outro candidato que ja represente o mesmo corte.

    Duas formas contam como duplicidade: arquivo final identico (mesmo sha256)
    ou trecho sobreposto em mais de 50% do mesmo material de origem.
    """
    inicio=float(candidate.get("source_start") or 0)
    fim=float(candidate.get("source_end") or 0)
    duracao=max(fim-inicio,0.001)
    with connect() as db:
        if output_sha256:
            igual=db.execute("SELECT id FROM campaign_candidates WHERE campaign_id=? AND output_sha256=? AND id<>? LIMIT 1",(candidate["campaign_id"],output_sha256,candidate["id"])).fetchone()
            if igual:return igual["id"]
        vizinhos=db.execute("SELECT id,source_start,source_end FROM campaign_candidates WHERE campaign_id=? AND material_id=? AND id<>? AND status<>'rejected'",(candidate["campaign_id"],candidate["material_id"],candidate["id"])).fetchall()
    for vizinho in vizinhos:
        sobreposicao=min(fim,float(vizinho["source_end"] or 0))-max(inicio,float(vizinho["source_start"] or 0))
        if sobreposicao/duracao>0.5:return vizinho["id"]
    return None

def process(job,worker_id):
 payload=json.loads(job["payload"]);transition(job["id"],"running",heartbeat_at=now());heartbeat(job["id"],worker_id,.05)
 if job["kind"]=="detect":
  material=get("campaign_materials",job["entity_id"]);campaign=get("campaign_campaigns",material["campaign_id"]);duration=payload.get("clip_duration",45)
  # modo "fala": escolhe pelo que foi dito, nao por movimento. E o que serve
  # para podcast, entrevista e reaction - a maior parte das campanhas. Sem fala
  # reconhecida, cai para o detector de movimento em vez de nao gerar nada.
  # Campanha e podcast, musica e entrevista: o momento bom e uma frase, nao um
  # pico de movimento. Por isso o padrao aqui e "fala".
  modo=payload.get("modo",os.getenv("CAMPAIGNS_DETECT_MODO","fala"));items=[]
  if modo=="fala":
   from . import fala
   items=fala.detectar(material["local_path"],payload.get("max_candidates",8),payload.get("min_gap_seconds",45),payload.get("janela_min",15),payload.get("janela_max",60),payload.get("min_score",0))
   if not items:audit("detect.sem_fala","material",material["id"],{"caindo_para":"movimento"})
  if not items:
   # O detector de movimento depende do motor legado (moviepy). Se ele nao
   # estiver na imagem, isso vira aviso e nao falha do job - o material fica
   # registrado esperando, em vez de sumir na fila de erro.
   try:items=engine.detect(material["local_path"],payload.get("max_candidates",8),payload.get("min_gap_seconds",45),payload.get("min_score",0))
   except Exception as exc:
    audit("detect.movimento_indisponivel","material",material["id"],{"erro":str(exc)[:200]},result="failed");return {"candidates":0,"motivo":f"sem deteccao possivel: {exc}"[:200]}
  for index,item in enumerate(items):
   # A janela por fala ja vem com inicio e fim reais; a por movimento so tem o
   # pico, e ai a duracao e centrada nele.
   start=item.get("inicio") if item.get("inicio") is not None else max(0,item["timestamp"]-duration/2)
   end=item.get("fim") if item.get("fim") is not None else start+duration
   key=f"{material['id']}:{round(start,2)}:{round(end-start,2)}:{payload.get('layout','vertical-fit')}"
   candidate=insert("campaign_candidates",{"campaign_id":campaign["id"],"material_id":material["id"],"source_start":start,"source_end":end,"score":item["score"],"algorithm_version":(__import__("app.fala",fromlist=["ALGORITMO"]).ALGORITMO if item.get("inicio") is not None else engine.ALGORITHM_VERSION),"parameters":json.dumps(payload),"version":1,"caption":" ".join(json.loads(campaign["hashtags"]) + json.loads(campaign["mentions"])),"hook":"","layout":payload.get("layout","vertical-fit"),"status":"detected","checklist_status":"pending","idempotency_key":key,"created_at":now(),"updated_at":now()});heartbeat(job["id"],worker_id,.1+.8*(index+1)/max(len(items),1));audit("candidate.detected","candidate",candidate["id"],item)
  return {"candidates":len(items)}
 if job["kind"]=="render":
  candidate=get("campaign_candidates",job["entity_id"]);material=get("campaign_materials",candidate["material_id"]);campaign=get("campaign_campaigns",candidate["campaign_id"]);out=ROOT/"data"/"outputs"/campaign["id"]/f"{candidate['id']}.mp4";mentions=json.loads(campaign["mentions"]);rules=json.loads(campaign["rules"]);result=engine.render(material["local_path"],out,candidate["source_start"],candidate["source_end"],candidate["layout"],candidate["caption"],candidate["hook"]," ".join(mentions),rules.get("cta", ""));update("campaign_candidates",candidate["id"],{"output_path":result["path"],"output_sha256":result["sha256"],"status":"review","updated_at":now()});candidate=get("campaign_candidates",candidate["id"]);campaign["rules"]=rules;campaign["hashtags"]=json.loads(campaign["hashtags"]);campaign["mentions"]=mentions;checks=evaluate(campaign,candidate,{**result,"authorized":bool(material["authorized"]),"duplicate_of":duplicado(candidate,result["sha256"])});state=summary(checks)
  with connect() as db:
   for check in checks:db.execute("INSERT OR REPLACE INTO campaign_rule_checks(id,candidate_id,rule_key,status,severity,reason,evidence,checked_at) VALUES(?,?,?,?,?,?,?,?)",(uid(),candidate["id"],check["rule_key"],check["status"],check["severity"],check["reason"],json.dumps(check["evidence"]),check["checked_at"]))
  update("campaign_candidates",candidate["id"],{"checklist_status":state,"updated_at":now()});return result
 if job["kind"]=="capturar":
  # A ponte: busca o que ha de novo na fonte do influenciador, registra como
  # material autorizado da campanha e ja enfileira a deteccao. Sem isto,
  # alguem tinha que baixar a live e subir o arquivo a mao todo dia.
  from . import fontes
  resultado=fontes.buscar(job["entity_id"],payload.get("limite",1));detectados=0
  for material in resultado["materiais"]:
   chave=f"detect:{material['id']}"
   enqueue("detect",material["id"],{"max_candidates":payload.get("max_candidates",8),"clip_duration":payload.get("clip_duration",45),"min_gap_seconds":payload.get("min_gap_seconds",45),"layout":payload.get("layout","vertical-fit")},chave);detectados+=1
  heartbeat(job["id"],worker_id,.9);return {"materiais":len(resultado["materiais"]),"deteccoes_enfileiradas":detectados,"motivo":resultado["motivo"]}
 raise ValueError("Tipo de job desconhecido")

def run_once(worker_id=None):
 worker_id=worker_id or f"{socket.gethostname()}-{os.getpid()}";recover_orphans();job=claim(worker_id)
 if not job:return False
 try:result=process(job,worker_id);transition(job["id"],"completed",progress=1,error="");audit("job.completed","job",job["id"],result);return True
 except Exception as exc:
  attempts=int(job["attempts"]);maximum=int(job["max_attempts"]);status="retry_wait" if attempts<maximum else "failed";run_after=(datetime.now(timezone.utc)+timedelta(seconds=min(300,2**attempts))).isoformat();transition(job["id"],status,error=str(exc)[:1000],run_after=run_after,worker_id=None);audit("job.failed","job",job["id"],{"error":str(exc),"retry":status=="retry_wait"},result="failed");return True
def agendar_fontes():
 """Enfileira a checagem das fontes que estao ha mais tempo sem olhar.

 A chave de idempotencia carrega a hora: uma fonte e checada no maximo uma vez
 por hora, e reiniciar o worker nao refaz o trabalho da hora corrente.
 """
 from . import fontes
 agendados=0
 for fonte in fontes.fontes_para_checar(limite=5):
  hora=datetime.now(timezone.utc).strftime("%Y%m%d%H")
  if enqueue("capturar",fonte["id"],{"limite":1},f"capturar:{fonte['id']}:{hora}")["status"]=="queued":agendados+=1
 return agendados
def main():
 if os.getenv("CAMPAIGNS_ENABLED","false").lower()!="true":raise SystemExit("Campanhas desativadas")
 ultima_varredura=0.0
 while True:
  if os.getenv("CAMPAIGNS_PAUSED","false").lower()=="true":time.sleep(2);continue
  # A cada 10 minutos olha se ha fonte para checar; no resto do tempo o worker
  # so consome a fila.
  if time.monotonic()-ultima_varredura>600:
   try:agendar_fontes()
   except Exception as exc:print(f"[campanhas] varredura de fontes falhou: {exc}")
   ultima_varredura=time.monotonic()
  if not run_once():time.sleep(2)
if __name__=="__main__":main()
