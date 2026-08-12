from __future__ import annotations
from datetime import datetime,timezone
def evaluate(campaign,candidate,metadata):
 rules=campaign.get("rules") or {};checks=[]
 def add(key,status,severity,reason,evidence):checks.append({"rule_key":key,"status":status,"severity":severity,"reason":reason,"evidence":evidence,"checked_at":datetime.now(timezone.utc).isoformat()})
 duration=float(candidate.get("source_end",0))-float(candidate.get("source_start",0));minimum=campaign.get("min_duration");maximum=campaign.get("max_duration")
 ok=(minimum is None or duration>=minimum) and (maximum is None or duration<=maximum);add("duration","approved" if ok else "rejected","critical","Duração dentro dos limites" if ok else "Duração fora dos limites",{"seconds":duration,"min":minimum,"max":maximum})
 ratio=metadata.get("width",0)/max(metadata.get("height",1),1);vertical=abs(ratio-9/16)<.03;add("aspect_ratio","approved" if vertical else "warning","warning","Proporção 9:16" if vertical else "Saída ainda não é 9:16",{"ratio":ratio})
 caption=(candidate.get("caption") or "").lower();missing=[x for x in campaign.get("hashtags",[]) if x.lower() not in caption];add("hashtags","approved" if not missing else "rejected","critical","Hashtags verificadas" if not missing else "Hashtags obrigatórias ausentes",{"missing":missing})
 mentions=[x for x in campaign.get("mentions",[]) if x.lower() not in caption];add("mentions","approved" if not mentions else "rejected","critical","Menções verificadas" if not mentions else "Menções obrigatórias ausentes",{"missing":mentions})
 prohibited=[x for x in rules.get("prohibited_words",[]) if x.lower() in caption];add("prohibited_words","approved" if not prohibited else "rejected","critical","Nenhuma palavra proibida" if not prohibited else "Palavra proibida detectada",{"found":prohibited})
 required=[x for x in rules.get("required_words",[]) if x.lower() not in caption];add("required_words","approved" if not required else "rejected","critical","Palavras obrigatórias presentes" if not required else "Palavra obrigatória ausente",{"missing":required})
 add("authorized_source","approved" if metadata.get("authorized") else "rejected","critical","Origem autorizada" if metadata.get("authorized") else "Autorização ausente",{"material_id":candidate.get("material_id")})
 add("human_review","warning","critical","Revisão humana obrigatória",{})
 return checks
def summary(checks):
 if any(x["severity"]=="critical" and x["status"]=="rejected" for x in checks):return "blocked"
 if any(x["status"]=="warning" for x in checks):return "warning"
 return "approved"
