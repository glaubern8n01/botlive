from __future__ import annotations
import hashlib,hmac,os,time
from collections import defaultdict,deque
from fastapi import Header,HTTPException,Request
ROLES={"admin":{"*"},"operator":{"read","write","upload","jobs","export"},"reviewer":{"read","review"}}
BUCKETS=defaultdict(deque)
def configured():
 return {role:os.getenv(f"CAMPAIGNS_{role.upper()}_TOKEN",os.getenv("CAMPAIGNS_LOCAL_TOKEN","") if role=="admin" else "") for role in ROLES}
def identity(candidate):
 for role,token in configured().items():
  if token and candidate and hmac.compare_digest(token,candidate):return {"actor":role,"role":role}
 raise HTTPException(401,"Token inválido")
def require(action):
 def dependency(x_campaigns_token:str|None=Header(default=None)):
  if os.getenv("CAMPAIGNS_ENABLED","false").lower()!="true":raise HTTPException(404,"Módulo desativado")
  user=identity(x_campaigns_token);allowed=ROLES[user["role"]]
  if "*" not in allowed and action not in allowed:raise HTTPException(403,"Permissão insuficiente")
  return user
 return dependency
def rate_limit(request:Request,scope="default",limit=60,window=60):
 key=(scope,request.client.host if request.client else "local");now=time.monotonic();bucket=BUCKETS[key]
 while bucket and bucket[0]<now-window:bucket.popleft()
 if len(bucket)>=limit:raise HTTPException(429,"Limite de requisições excedido")
 bucket.append(now)
def token_hash(value):return hashlib.sha256(value.encode()).hexdigest()
