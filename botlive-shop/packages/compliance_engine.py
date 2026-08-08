from dataclasses import dataclass
from enum import Enum

class Severity(str, Enum):
    INFO = "informativo"
    WARNING = "atencao"
    HIGH = "alto"
    CRITICAL = "critico"

@dataclass(frozen=True)
class Signal:
    kind: str
    value: float | str | bool

@dataclass(frozen=True)
class Alert:
    rule: str
    severity: Severity
    problem: str
    correction: str
    pause_required: bool = False

def evaluate(signals: list[Signal]) -> list[Alert]:
    alerts = []
    for signal in signals:
        if signal.kind == "audio.silence_seconds" and float(signal.value) >= 12:
            alerts.append(Alert("LIVE_AUDIO_001", Severity.HIGH, "Silêncio prolongado.", "Confirme o microfone e retome a fala humana."))
        elif signal.kind == "audio.muted" and signal.value is True:
            alerts.append(Alert("LIVE_AUDIO_002", Severity.CRITICAL, "Microfone desativado.", "Pause e reative o dispositivo.", True))
        elif signal.kind == "video.freeze_seconds" and float(signal.value) >= 8:
            alerts.append(Alert("LIVE_VIDEO_001", Severity.CRITICAL, "Imagem congelada.", "Pause e reconecte a câmera.", True))
        elif signal.kind == "connection.packet_loss" and float(signal.value) >= .15:
            alerts.append(Alert("LIVE_NET_001", Severity.HIGH, "Conexão degradada.", "Verifique uma conexão estável."))
        elif signal.kind == "script.prohibited_claim" and signal.value is True:
            alerts.append(Alert("LIVE_CLAIM_001", Severity.CRITICAL, "Alegação proibida.", "Use apenas texto aprovado.", True))
    return alerts
