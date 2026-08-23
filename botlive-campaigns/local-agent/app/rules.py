"""Validacao automatica de candidatos.

O documento do projeto exige checar duracao, resolucao, audio, texto
obrigatorio, marcas, duplicidade e prazo. Cada regra vira um registro em
campaign_rule_checks com status, severidade, motivo e evidencia, para que a
revisao humana veja por que o corte passou ou travou.

Regra critica reprovada bloqueia a publicacao. Aviso nao bloqueia, mas fica
visivel na revisao.
"""

from __future__ import annotations

from datetime import datetime, timezone


# Piso de qualidade quando a campanha nao define o proprio minimo.
LARGURA_PADRAO = 720
ALTURA_PADRAO = 1280


def _agora():
    return datetime.now(timezone.utc)


def _check(key, status, severity, reason, evidence):
    return {
        "rule_key": key,
        "status": status,
        "severity": severity,
        "reason": reason,
        "evidence": evidence,
        "checked_at": _agora().isoformat(),
    }


def _duracao(campaign, candidate):
    duracao = float(candidate.get("source_end", 0)) - float(candidate.get("source_start", 0))
    minimo = campaign.get("min_duration")
    maximo = campaign.get("max_duration")
    ok = (minimo is None or duracao >= minimo) and (maximo is None or duracao <= maximo)
    return _check(
        "duration",
        "approved" if ok else "rejected",
        "critical",
        "Duracao dentro dos limites" if ok else "Duracao fora dos limites",
        {"seconds": duracao, "min": minimo, "max": maximo},
    )


def _proporcao(metadata):
    ratio = metadata.get("width", 0) / max(metadata.get("height", 1), 1)
    vertical = abs(ratio - 9 / 16) < 0.03
    return _check(
        "aspect_ratio",
        "approved" if vertical else "warning",
        "warning",
        "Proporcao 9:16" if vertical else "Saida ainda nao e 9:16",
        {"ratio": ratio},
    )


def _resolucao(campaign, metadata):
    """Resolucao minima. Campanha manda; sem regra propria, vale o piso 720x1280."""
    regras = campaign.get("rules") or {}
    exigida = "min_width" in regras or "min_height" in regras
    largura_min = int(regras.get("min_width", LARGURA_PADRAO))
    altura_min = int(regras.get("min_height", ALTURA_PADRAO))
    largura = int(metadata.get("width", 0))
    altura = int(metadata.get("height", 0))
    ok = largura >= largura_min and altura >= altura_min
    if ok:
        status, severity = "approved", "critical" if exigida else "warning"
    else:
        status = "rejected" if exigida else "warning"
        severity = "critical" if exigida else "warning"
    return _check(
        "resolution",
        status,
        severity,
        "Resolucao suficiente" if ok else "Resolucao abaixo do minimo",
        {"width": largura, "height": altura, "min_width": largura_min, "min_height": altura_min},
    )


def _audio(campaign, metadata):
    """Audio ausente so reprova quando a campanha exige audio explicitamente."""
    regras = campaign.get("rules") or {}
    exigido = bool(regras.get("require_audio"))
    tem_audio = bool(metadata.get("has_audio"))
    if tem_audio:
        return _check("audio", "approved", "critical" if exigido else "warning",
                      "Faixa de audio presente", {"has_audio": True})
    return _check(
        "audio",
        "rejected" if exigido else "warning",
        "critical" if exigido else "warning",
        "Campanha exige audio e o corte esta mudo" if exigido else "Corte sem faixa de audio",
        {"has_audio": False, "required": exigido},
    )


def _prazo(campaign, momento=None):
    """Prazo da campanha. Sem ends_at nao ha o que checar."""
    fim = campaign.get("ends_at")
    if not fim:
        return _check("deadline", "approved", "critical", "Campanha sem prazo definido", {})
    momento = momento or _agora()
    try:
        limite = datetime.fromisoformat(str(fim))
    except ValueError:
        return _check("deadline", "warning", "warning", "Prazo em formato invalido", {"ends_at": fim})
    if limite.tzinfo is None:
        limite = limite.replace(tzinfo=timezone.utc)
    dentro = momento <= limite
    return _check(
        "deadline",
        "approved" if dentro else "rejected",
        "critical",
        "Dentro do prazo da campanha" if dentro else "Prazo da campanha encerrado",
        {"ends_at": limite.isoformat(), "checked_at": momento.isoformat()},
    )


def _duplicidade(campaign, metadata):
    """Duplicidade e detectada fora daqui; aqui aplicamos a politica da campanha.

    metadata['duplicate_of'] traz o id do candidato ja existente, quando houver.
    """
    duplicado = metadata.get("duplicate_of")
    politica = (campaign.get("duplicate_policy") or "deny").lower()
    if not duplicado:
        return _check("duplicate", "approved", "critical", "Nenhuma duplicidade encontrada", {})
    if politica == "allow":
        return _check("duplicate", "warning", "warning", "Duplicidade permitida pela campanha",
                      {"duplicate_of": duplicado, "policy": politica})
    return _check(
        "duplicate",
        "rejected" if politica == "deny" else "warning",
        "critical" if politica == "deny" else "warning",
        "Corte duplicado",
        {"duplicate_of": duplicado, "policy": politica},
    )


def _texto(campaign, candidate):
    caption = (candidate.get("caption") or "").lower()
    regras = campaign.get("rules") or {}
    checks = []

    faltando = [x for x in campaign.get("hashtags", []) if x.lower() not in caption]
    checks.append(_check("hashtags", "approved" if not faltando else "rejected", "critical",
                         "Hashtags verificadas" if not faltando else "Hashtags obrigatorias ausentes",
                         {"missing": faltando}))

    mencoes = [x for x in campaign.get("mentions", []) if x.lower() not in caption]
    checks.append(_check("mentions", "approved" if not mencoes else "rejected", "critical",
                         "Mencoes verificadas" if not mencoes else "Mencoes obrigatorias ausentes",
                         {"missing": mencoes}))

    proibidas = [x for x in regras.get("prohibited_words", []) if x.lower() in caption]
    checks.append(_check("prohibited_words", "approved" if not proibidas else "rejected", "critical",
                         "Nenhuma palavra proibida" if not proibidas else "Palavra proibida detectada",
                         {"found": proibidas}))

    obrigatorias = [x for x in regras.get("required_words", []) if x.lower() not in caption]
    checks.append(_check("required_words", "approved" if not obrigatorias else "rejected", "critical",
                         "Palavras obrigatorias presentes" if not obrigatorias else "Palavra obrigatoria ausente",
                         {"missing": obrigatorias}))
    return checks


def _selo(campaign, metadata):
    """Selo dentro do corte. GabePeixe exige o lower embaixo do rosto durante
    todo o corte; Juninho exige a Kick NO CORTE, nao na legenda. Campanha que
    nao pede nada passa direto."""
    exigido = bool((campaign.get("rules") or {}).get("selo"))
    aplicado = bool((metadata.get("selo") or {}).get("aplicado"))
    if not exigido:
        return _check("selo", "approved", "warning", "Campanha nao exige selo", {})
    return _check(
        "selo",
        "approved" if aplicado else "rejected",
        "critical",
        "Selo obrigatorio aplicado no corte" if aplicado
        else "Campanha exige selo dentro do corte e ele nao foi aplicado",
        metadata.get("selo") or {},
    )


def evaluate(campaign, candidate, metadata, momento=None):
    """Roda todas as regras. metadata vem do render (largura, altura, audio) e
    do worker (authorized, duplicate_of)."""
    checks = [
        _duracao(campaign, candidate),
        _proporcao(metadata),
        _resolucao(campaign, metadata),
        _audio(campaign, metadata),
        _prazo(campaign, momento),
        _duplicidade(campaign, metadata),
        _selo(campaign, metadata),
    ]
    checks.extend(_texto(campaign, candidate))
    checks.append(
        _check(
            "authorized_source",
            "approved" if metadata.get("authorized") else "rejected",
            "critical",
            "Origem autorizada" if metadata.get("authorized") else "Autorizacao ausente",
            {"material_id": candidate.get("material_id")},
        )
    )
    checks.append(_check("human_review", "warning", "critical", "Revisao humana obrigatoria", {}))
    return checks


def summary(checks):
    if any(x["severity"] == "critical" and x["status"] == "rejected" for x in checks):
        return "blocked"
    if any(x["status"] == "warning" for x in checks):
        return "warning"
    return "approved"
