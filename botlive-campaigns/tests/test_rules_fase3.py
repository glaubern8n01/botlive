"""Fase 3: as sete validacoes automaticas exigidas pelo documento.

duracao, resolucao, audio, texto obrigatorio, marcas, duplicidade e prazo.
"""

import os, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local-agent"))
os.environ.setdefault("CAMPAIGNS_DATABASE_PATH", str(Path(tempfile.mkdtemp()) / "rules.db"))

from app import store
from app.rules import evaluate, summary
from app.worker import duplicado

VERTICAL = {"width": 1080, "height": 1920, "has_audio": True, "authorized": True}


def campanha(**extra):
    base = {
        "min_duration": 10,
        "max_duration": 60,
        "hashtags": [],
        "mentions": [],
        "rules": {},
        "duplicate_policy": "deny",
    }
    base.update(extra)
    return base


def candidato(**extra):
    base = {"source_start": 0, "source_end": 30, "caption": "", "material_id": "m"}
    base.update(extra)
    return base


def achar(checks, chave):
    return next(x for x in checks if x["rule_key"] == chave)


class RegrasTests(unittest.TestCase):
    def test_cobre_as_sete_validacoes(self):
        checks = evaluate(campanha(), candidato(), VERTICAL)
        chaves = {x["rule_key"] for x in checks}
        for exigida in ("duration", "resolution", "audio", "required_words", "hashtags",
                        "mentions", "duplicate", "deadline"):
            self.assertIn(exigida, chaves)

    def test_corte_limpo_passa_com_aviso_de_revisao(self):
        checks = evaluate(campanha(), candidato(), VERTICAL)
        self.assertEqual("warning", summary(checks))
        self.assertEqual("warning", achar(checks, "human_review")["status"])

    def test_resolucao_abaixo_do_piso_vira_aviso(self):
        checks = evaluate(campanha(), candidato(), {**VERTICAL, "width": 360, "height": 640})
        self.assertEqual("warning", achar(checks, "resolution")["status"])
        self.assertNotEqual("blocked", summary(checks))

    def test_resolucao_abaixo_do_minimo_da_campanha_bloqueia(self):
        alvo = campanha(rules={"min_width": 1080, "min_height": 1920})
        checks = evaluate(alvo, candidato(), {**VERTICAL, "width": 720, "height": 1280})
        self.assertEqual("rejected", achar(checks, "resolution")["status"])
        self.assertEqual("blocked", summary(checks))

    def test_audio_ausente_bloqueia_quando_a_campanha_exige(self):
        alvo = campanha(rules={"require_audio": True})
        checks = evaluate(alvo, candidato(), {**VERTICAL, "has_audio": False})
        self.assertEqual("rejected", achar(checks, "audio")["status"])
        self.assertEqual("blocked", summary(checks))

    def test_audio_ausente_e_so_aviso_sem_exigencia(self):
        checks = evaluate(campanha(), candidato(), {**VERTICAL, "has_audio": False})
        self.assertEqual("warning", achar(checks, "audio")["status"])
        self.assertNotEqual("blocked", summary(checks))

    def test_prazo_encerrado_bloqueia(self):
        ontem = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        checks = evaluate(campanha(ends_at=ontem), candidato(), VERTICAL)
        self.assertEqual("rejected", achar(checks, "deadline")["status"])
        self.assertEqual("blocked", summary(checks))

    def test_prazo_futuro_passa(self):
        amanha = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        checks = evaluate(campanha(ends_at=amanha), candidato(), VERTICAL)
        self.assertEqual("approved", achar(checks, "deadline")["status"])

    def test_prazo_ausente_nao_bloqueia(self):
        self.assertEqual("approved", achar(evaluate(campanha(), candidato(), VERTICAL), "deadline")["status"])

    def test_duplicidade_bloqueia_com_politica_deny(self):
        checks = evaluate(campanha(), candidato(), {**VERTICAL, "duplicate_of": "outro-id"})
        self.assertEqual("rejected", achar(checks, "duplicate")["status"])
        self.assertEqual("blocked", summary(checks))

    def test_duplicidade_permitida_vira_aviso(self):
        alvo = campanha(duplicate_policy="allow")
        checks = evaluate(alvo, candidato(), {**VERTICAL, "duplicate_of": "outro-id"})
        self.assertEqual("warning", achar(checks, "duplicate")["status"])
        self.assertNotEqual("blocked", summary(checks))

    def test_origem_nao_autorizada_bloqueia(self):
        checks = evaluate(campanha(), candidato(), {**VERTICAL, "authorized": False})
        self.assertEqual("blocked", summary(checks))


class DuplicidadeTests(unittest.TestCase):
    def setUp(self):
        store.migrate()
        with store.connect() as db:
            for tabela in ("campaign_candidates", "campaign_materials", "campaign_campaigns"):
                db.execute(f"DELETE FROM {tabela}")
        stamp = store.now()
        self.campanha = store.insert(
            "campaign_campaigns",
            {"platform": "manual", "name": "Dup", "created_at": stamp, "updated_at": stamp},
        )
        self.material = store.insert(
            "campaign_materials",
            {
                "campaign_id": self.campanha["id"],
                "name": "origem.mp4",
                "sha256": "sha-material",
                "authorized": 1,
                "status": "validated",
                "created_at": stamp,
            },
        )

    def _candidato(self, chave, inicio, fim, sha=""):
        stamp = store.now()
        return store.insert(
            "campaign_candidates",
            {
                "campaign_id": self.campanha["id"],
                "material_id": self.material["id"],
                "source_start": inicio,
                "source_end": fim,
                "output_sha256": sha,
                "status": "review",
                "idempotency_key": chave,
                "created_at": stamp,
                "updated_at": stamp,
            },
        )

    def test_arquivo_identico_e_duplicado(self):
        self._candidato("a", 0, 30, "sha-igual")
        novo = self._candidato("b", 500, 530, "sha-igual")
        self.assertIsNotNone(duplicado(novo, "sha-igual"))

    def test_trecho_sobreposto_e_duplicado(self):
        self._candidato("c", 100, 130, "sha-1")
        novo = self._candidato("d", 110, 140, "sha-2")
        self.assertIsNotNone(duplicado(novo, "sha-2"))

    def test_trecho_distante_nao_e_duplicado(self):
        self._candidato("e", 0, 30, "sha-3")
        novo = self._candidato("f", 600, 630, "sha-4")
        self.assertIsNone(duplicado(novo, "sha-4"))

    def test_candidato_rejeitado_nao_conta_como_duplicidade(self):
        anterior = self._candidato("g", 200, 230, "sha-5")
        store.update("campaign_candidates", anterior["id"], {"status": "rejected"})
        novo = self._candidato("h", 205, 235, "sha-6")
        self.assertIsNone(duplicado(novo, "sha-6"))


if __name__ == "__main__":
    unittest.main()
