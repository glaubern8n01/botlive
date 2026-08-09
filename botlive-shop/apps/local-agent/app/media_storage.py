from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import wave
import math
from pathlib import Path
from uuid import uuid4
from fastapi import UploadFile
from .paths import MEDIA_ROOT

ALLOWED = {
    ".mp4": {"video/mp4", "application/mp4"},
    ".webm": {"video/webm", "audio/webm"},
    ".mp3": {"audio/mpeg", "audio/mp3"},
    ".wav": {"audio/wav", "audio/x-wav", "audio/wave"},
    ".m4a": {"audio/mp4", "audio/x-m4a", "video/mp4"},
}

def storage_root() -> Path:
    root = MEDIA_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root

def safe_path(stored_name: str) -> Path:
    if Path(stored_name).name != stored_name: raise ValueError("Nome interno inválido")
    root=storage_root(); target=(root/stored_name).resolve()
    if target.parent != root: raise ValueError("Caminho fora do armazenamento")
    return target

def validate_header(extension: str, data: bytes) -> None:
    valid = {
        ".mp4": len(data)>12 and data[4:8]==b"ftyp",
        ".m4a": len(data)>12 and data[4:8]==b"ftyp",
        ".webm": data.startswith(b"\x1a\x45\xdf\xa3"),
        ".mp3": data.startswith(b"ID3") or (len(data)>1 and data[0]==0xFF and data[1]&0xE0==0xE0),
        ".wav": len(data)>12 and data[:4]==b"RIFF" and data[8:12]==b"WAVE",
    }
    if not valid.get(extension,False): raise ValueError("Conteúdo não corresponde ao formato informado")

async def store_upload(upload: UploadFile) -> tuple[str,Path,int,str,str]:
    original=Path(upload.filename or "")
    extension=original.suffix.lower()
    if extension not in ALLOWED: raise ValueError("Formato não permitido")
    mime=(upload.content_type or mimetypes.guess_type(original.name)[0] or "").lower()
    if mime not in ALLOWED[extension]: raise ValueError("MIME não permitido para a extensão")
    max_bytes=int(os.getenv("SHOP_LIVE_MEDIA_MAX_BYTES",str(100*1024*1024)))
    total_limit=int(os.getenv("SHOP_LIVE_MEDIA_TOTAL_MAX_BYTES",str(10*1024*1024*1024)))
    existing=sum(path.stat().st_size for path in storage_root().iterdir() if path.is_file())
    stored_name=f"{uuid4().hex}{extension}"; target=safe_path(stored_name); size=0; header=b""
    try:
        with target.open("xb") as output:
            while chunk:=await upload.read(1024*1024):
                size+=len(chunk)
                if size>max_bytes: raise ValueError("Arquivo excede o tamanho máximo")
                if existing+size>total_limit: raise ValueError("Armazenamento local atingiu o limite configurado")
                if len(header)<64: header=(header+chunk)[:64]
                output.write(chunk)
        if not size: raise ValueError("Arquivo vazio")
        validate_header(extension,header)
        try: target.chmod(0o600)
        except OSError: pass
        return stored_name,target,size,mime,extension.lstrip(".")
    except Exception:
        target.unlink(missing_ok=True)
        raise

def inspect_media(path: Path, extension: str) -> dict:
    result={"duration_seconds":0.0,"width":None,"height":None,"format_name":extension}
    try:
        command=[os.getenv("SHOP_LIVE_FFPROBE","ffprobe"),"-v","error","-show_entries","format=duration,format_name:stream=codec_type,width,height","-of","json",str(path)]
        parsed=json.loads(subprocess.run(command,capture_output=True,text=True,check=True,timeout=15).stdout)
        fmt=parsed.get("format",{}); result["duration_seconds"]=round(float(fmt.get("duration") or 0),3); result["format_name"]=fmt.get("format_name") or extension
        streams=parsed.get("streams",[])
        compatible=[row for row in streams if row.get("codec_type") in {"audio","video"}]
        if not compatible: raise ValueError("ffprobe não reconheceu fluxo compatível")
        if not math.isfinite(result["duration_seconds"]) or result["duration_seconds"] <= 0: raise ValueError("Duração de mídia inválida")
        video=next((row for row in streams if row.get("codec_type")=="video"),None)
        if video: result["width"],result["height"]=video.get("width"),video.get("height")
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError, KeyError, TypeError, ValueError) as error:
        if extension=="wav":
            try:
                with wave.open(str(path),"rb") as wav: result["duration_seconds"]=round(wav.getnframes()/wav.getframerate(),3)
            except (wave.Error, OSError, ZeroDivisionError) as wav_error:
                raise ValueError("Arquivo não contém mídia reproduzível") from wav_error
            if result["duration_seconds"] <= 0: raise ValueError("Duração de mídia inválida")
        else:
            raise ValueError("Arquivo não contém mídia reproduzível") from error
    return result
