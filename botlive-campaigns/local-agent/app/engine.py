from __future__ import annotations
import importlib.util,os,sys
from pathlib import Path
from .media import sha256
from .store import REPO_ROOT
ALGORITHM_VERSION="botlive-highlight-v1"
def _load(name):
 if str(REPO_ROOT) not in sys.path:sys.path.insert(0,str(REPO_ROOT))
 path=REPO_ROOT/f"{name}.py";spec=importlib.util.spec_from_file_location(f"campaign_legacy_{name}",path);module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);return module
def detect(path,max_candidates=8,min_gap_seconds=45,min_score=0):
 detector=_load("highlight_detector");items=detector.detectar_melhores_momentos(path,max_cortes=max_candidates,min_gap_seconds=min_gap_seconds,min_score=min_score)
 return [{"timestamp":x.timestamp_seconds,"score":x.score,"reason":x.reason,"audio_score":x.audio_score,"motion_score":x.motion_score,"brightness_score":x.brightness_score} for x in items]
def render(path,output,start,end,layout="vertical-crop",caption="",hook="",brand="",cta=""):
 clipper=_load("clipper");output=Path(output);output.parent.mkdir(parents=True,exist_ok=True);duration=max(6,float(end)-float(start));peak=int(float(start)+duration/2)
 import runtime_paths
 previous=runtime_paths.get_output_root();runtime_paths.set_output_root(output.parent.parent)
 overlay=None
 if any([caption,hook,brand,cta]):
  overlay_module=_load("overlay_editor");overlay=overlay_module.OverlayConfig(title=hook or None,description=caption or None,brand=brand or None,cta=cta or None)
 try:result=clipper.criar_corte_vertical_de_arquivo(Path(path),peak_timestamp=peak,clip_id=output.stem,seconds_before=int(duration/2),seconds_after=int(duration-duration/2),output_layout=layout,overlay_config=overlay)
 finally:runtime_paths.set_output_root(previous)
 result=Path(result)
 if result.resolve()!=output.resolve():
  output.unlink(missing_ok=True);result.replace(output);result=output
 validation=clipper.validar_video_final(result,require_audio=False)
 if not validation.valid:raise ValueError(f"Saída inválida: {validation.reason}")
 subtitle=output.with_suffix(".srt")
 subtitle.write_text(f"1\n00:00:00,000 --> 00:00:{int(validation.duration_seconds):02d},000\n{caption or hook or 'Corte BotLive'}\n",encoding="utf-8")
 return {"path":str(result),"subtitle_path":str(subtitle),"sha256":sha256(result),"duration_seconds":validation.duration_seconds,"width":validation.width,"height":validation.height,"has_audio":validation.has_audio}
