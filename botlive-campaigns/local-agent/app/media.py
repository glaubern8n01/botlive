from __future__ import annotations
import hashlib,json,mimetypes,os,shutil,subprocess
from pathlib import Path
from uuid import uuid4
from fastapi import UploadFile
from .store import ROOT

ALLOWED={".mp4":{"video/mp4","application/mp4"},".mov":{"video/quicktime"},".webm":{"video/webm"},".mkv":{"video/x-matroska","application/octet-stream"}}
CODECS={"h264","hevc","vp8","vp9","av1","mpeg4"}
def media_root():
 root=Path(os.getenv("CAMPAIGNS_MEDIA_ROOT",ROOT/"data"/"media")).resolve();root.mkdir(parents=True,exist_ok=True);return root
def quarantine_root():
 root=media_root()/"quarantine";root.mkdir(exist_ok=True);return root
def accepted_root():
 root=media_root()/"accepted";root.mkdir(exist_ok=True);return root
def safe_path(root:Path,name:str):
 if Path(name).name!=name:raise ValueError("Nome interno inválido")
 target=(root/name).resolve()
 if target.parent!=root.resolve():raise ValueError("Caminho fora do armazenamento")
 return target
def signature(ext,data):
 if ext in {".mp4",".mov"}:return len(data)>12 and data[4:8]==b"ftyp"
 if ext==".webm" or ext==".mkv":return data.startswith(b"\x1a\x45\xdf\xa3")
 return False
def detected_mime(ext):return {".mp4":"video/mp4",".mov":"video/quicktime",".webm":"video/webm",".mkv":"video/x-matroska"}[ext]
def sha256(path):
 h=hashlib.sha256()
 with Path(path).open("rb") as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b""):h.update(chunk)
 return h.hexdigest()
async def validate_upload(upload:UploadFile):
 original=Path(upload.filename or "");ext=original.suffix.lower()
 if ext not in ALLOWED:raise ValueError("Formato não permitido")
 declared=(upload.content_type or mimetypes.guess_type(original.name)[0] or "").lower()
 if declared not in ALLOWED[ext]:raise ValueError("MIME declarado incompatível")
 max_bytes=int(os.getenv("CAMPAIGNS_MAX_UPLOAD_BYTES",str(500*1024*1024)));name=f"{uuid4().hex}{ext}";quarantine=safe_path(quarantine_root(),name);size=0;header=b""
 try:
  with quarantine.open("xb") as output:
   while chunk:=await upload.read(1024*1024):
    size+=len(chunk)
    if size>max_bytes:raise ValueError("Arquivo excede o limite")
    if len(header)<64:header=(header+chunk)[:64]
    output.write(chunk)
  if not size:raise ValueError("Arquivo vazio")
  if not signature(ext,header):raise ValueError("Extensão disfarçada ou assinatura inválida")
  metadata=probe(quarantine);digest=sha256(quarantine);target=safe_path(accepted_root(),name);shutil.move(str(quarantine),target)
  return {"stored_name":name,"path":target,"size":size,"sha256":digest,"declared_mime":declared,"detected_mime":detected_mime(ext),"metadata":metadata}
 except Exception:quarantine.unlink(missing_ok=True);raise
def probe(path):
 command=[os.getenv("CAMPAIGNS_FFPROBE","ffprobe"),"-v","error","-show_streams","-show_format","-of","json",str(path)]
 try:parsed=json.loads(subprocess.run(command,capture_output=True,text=True,check=True,timeout=int(os.getenv("CAMPAIGNS_FFPROBE_TIMEOUT","20"))).stdout)
 except subprocess.TimeoutExpired as exc:raise ValueError("ffprobe excedeu o tempo limite") from exc
 except (OSError,subprocess.CalledProcessError,json.JSONDecodeError) as exc:raise ValueError("Vídeo corrompido ou ffprobe indisponível") from exc
 streams=parsed.get("streams",[]);video=next((x for x in streams if x.get("codec_type")=="video"),None);audio=next((x for x in streams if x.get("codec_type")=="audio"),None);fmt=parsed.get("format",{})
 if not video:raise ValueError("Stream de vídeo ausente")
 duration=float(fmt.get("duration") or video.get("duration") or 0)
 if not 0<duration<=int(os.getenv("CAMPAIGNS_MAX_DURATION_SECONDS","43200")):raise ValueError("Duração inválida")
 codec=str(video.get("codec_name") or "")
 if codec not in CODECS:raise ValueError("Codec de vídeo não permitido")
 width,height=int(video.get("width") or 0),int(video.get("height") or 0)
 if width<16 or height<16:raise ValueError("Resolução inválida")
 rate=str(video.get("avg_frame_rate") or "0/1");a,b=(rate.split("/")+["1"])[:2];fps=float(a)/max(float(b),1)
 return {"duration_seconds":round(duration,3),"width":width,"height":height,"fps":round(fps,3),"video_codec":codec,"audio_codec":audio.get("codec_name") if audio else None,"has_audio":bool(audio),"bit_rate":int(fmt.get("bit_rate") or 0),"format_name":fmt.get("format_name") or ""}
