from dataclasses import asdict
from enum import Enum

class Severity(str, Enum):
    HIGH = "alto"
    CRITICAL = "critico"

def evaluate_signal(kind: str, value) -> list[dict]:
    alert = None
    if kind == "audio.silence_seconds" and float(value) >= 12:
        alert = ("LIVE_AUDIO_001", Severity.HIGH, "Silêncio prolongado.", "Confirme o microfone e retome a fala humana.", False)
    elif kind == "audio.muted" and value is True:
        alert = ("LIVE_AUDIO_002", Severity.CRITICAL, "Microfone desativado.", "Pause e reative o dispositivo.", True)
    elif kind == "video.freeze_seconds" and float(value) >= 8:
        alert = ("LIVE_VIDEO_001", Severity.CRITICAL, "Imagem congelada.", "Pause e reconecte a câmera.", True)
    elif kind == "connection.packet_loss" and float(value) >= .15:
        alert = ("LIVE_NET_001", Severity.HIGH, "Conexão degradada.", "Verifique uma conexão estável.", False)
    elif kind == "script.prohibited_claim" and value is True:
        alert = ("LIVE_CLAIM_001", Severity.CRITICAL, "Alegação proibida.", "Use apenas texto aprovado.", True)
    if not alert: return []
    rule, severity, problem, correction, pause = alert
    return [{"rule": rule, "severity": severity.value, "problem": problem, "correction": correction, "pause_required": pause}]
