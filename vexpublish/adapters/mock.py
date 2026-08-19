"""Adapter de teste. Nunca sai da maquina.

Serve para exercitar fila, lock, retry e dry-run sem tocar em plataforma
nenhuma. Registra as chamadas para que o teste prove que publish nao roda
em dry-run.
"""

from __future__ import annotations

from ..core.errors import CodigoErro, VexPublishError
from .base import Adapter


class MockAdapter(Adapter):
    plataforma = "tiktok"
    compatibilidade = "NAO"

    def __init__(self, falhar_com: str | None = None, plataforma: str = "tiktok"):
        self.plataforma = plataforma
        self.falhar_com = falhar_com
        self.chamadas = []

    def login(self, conta, sessao):
        self.chamadas.append("login")
        return sessao

    def check_session(self, conta, sessao):
        self.chamadas.append("check_session")
        return "valid"

    def validate(self, job, conta):
        self.chamadas.append("validate")

    def prepare(self, job, conta):
        self.chamadas.append("prepare")
        return {"video_path": job["media_path"]}

    def publish(self, job, conta, payload):
        self.chamadas.append("publish")
        if self.falhar_com:
            raise VexPublishError(self.falhar_com, "falha simulada")
        return {"url": "https://exemplo.invalido/post/1", "external_id": "mock-1"}
