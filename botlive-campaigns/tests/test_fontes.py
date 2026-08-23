"""A ponte entre a live do influenciador e o corte da campanha.

Nenhum teste baixa vídeo: o yt-dlp é substituído por mock. O que se verifica é
a regra — autorização declarada, VOD não baixado duas vezes, fonte desligada
não busca — e o encaixe no pipeline que já existia.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local-agent"))
os.environ.setdefault("CAMPAIGNS_DATABASE_PATH", str(Path(tempfile.mkdtemp()) / "fontes.db"))

from app import fontes, store


class FonteDaCampanhaTests(unittest.TestCase):
    def setUp(self):
        store.migrate()
        with store.connect() as db:
            for tabela in ("campaign_sources", "campaign_materials", "campaign_jobs",
                           "campaign_candidates", "campaign_campaigns"):
                db.execute(f"DELETE FROM {tabela}")
        stamp = store.now()
        self.campanha = store.insert("campaign_campaigns", {
            "platform": "viewx", "name": "Campeonato do influenciador",
            "status": "active", "created_at": stamp, "updated_at": stamp,
        })
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["CAMPAIGNS_MEDIA_ROOT"] = str(self.tmp)

    def _fonte(self, **extra):
        dados = {
            "campaign_id": self.campanha["id"], "network": "twitch",
            "url": "https://twitch.tv/influenciador", "influencer": "Influenciador",
            "authorization_source": "campanha autoriza cortes do canal",
        }
        dados.update(extra)
        return fontes.registrar(**dados)

    def test_fonte_sem_autorizacao_declarada_e_recusada(self):
        with self.assertRaises(ValueError) as erro:
            self._fonte(authorization_source="   ")
        self.assertIn("autorizacao", str(erro.exception))

    def test_rede_desconhecida_e_recusada(self):
        with self.assertRaises(ValueError):
            self._fonte(network="orkut")

    def test_url_precisa_ser_http(self):
        with self.assertRaises(ValueError):
            self._fonte(url="twitch.tv/sem-esquema")

    def test_mesma_fonte_nao_entra_duas_vezes(self):
        primeira = self._fonte()
        segunda = self._fonte()
        self.assertEqual(primeira["id"], segunda["id"])

    def test_captura_registra_material_autorizado_e_com_origem(self):
        fonte = self._fonte()
        arquivo = self.tmp / self.campanha["id"] / "vod123.mp4"

        def falso_run(comando, **kwargs):
            if "--flat-playlist" in comando:
                linha = json.dumps({"id": "vod123", "title": "Live de ontem",
                                    "url": "https://twitch.tv/videos/123", "duration": 3600})
                return mock.Mock(returncode=0, stdout=linha, stderr="")
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_bytes(b"video da live")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(fontes, "comando_ytdlp", return_value=["yt-dlp"]), \
             mock.patch("subprocess.run", side_effect=falso_run):
            resultado = fontes.buscar(fonte["id"])

        self.assertEqual(1, len(resultado["materiais"]))
        material = resultado["materiais"][0]
        self.assertEqual(1, material["authorized"])
        self.assertEqual("campanha autoriza cortes do canal", material["authorization_source"])
        self.assertEqual("validated", material["status"])
        self.assertIn("vod123", material["metadata"])

    def test_mesmo_vod_nao_e_baixado_duas_vezes(self):
        fonte = self._fonte()
        arquivo = self.tmp / self.campanha["id"] / "vod123.mp4"

        def falso_run(comando, **kwargs):
            if "--flat-playlist" in comando:
                return mock.Mock(returncode=0, stdout=json.dumps(
                    {"id": "vod123", "title": "Live", "url": "https://twitch.tv/videos/123"}), stderr="")
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_bytes(b"video")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(fontes, "comando_ytdlp", return_value=["yt-dlp"]), \
             mock.patch("subprocess.run", side_effect=falso_run):
            fontes.buscar(fonte["id"])
            segunda = fontes.buscar(fonte["id"])

        self.assertEqual([], segunda["materiais"])
        self.assertIn("nada novo", segunda["motivo"])

    def test_fonte_desligada_nao_busca(self):
        fonte = self._fonte()
        fontes.alternar(fonte["id"], False)
        with mock.patch("subprocess.run", side_effect=AssertionError("não deveria baixar")):
            resultado = fontes.buscar(fonte["id"])
        self.assertEqual("fonte desativada", resultado["motivo"])

    def test_campanha_arquivada_nao_busca(self):
        fonte = self._fonte()
        store.update("campaign_campaigns", self.campanha["id"], {"status": "archived"})
        with mock.patch("subprocess.run", side_effect=AssertionError("não deveria baixar")):
            resultado = fontes.buscar(fonte["id"])
        self.assertEqual("campanha arquivada", resultado["motivo"])

    def test_falha_ao_listar_fica_registrada_e_nao_levanta(self):
        fonte = self._fonte()
        with mock.patch.object(fontes, "listar_disponiveis", side_effect=RuntimeError("canal fora do ar")):
            resultado = fontes.buscar(fonte["id"])
        self.assertEqual([], resultado["materiais"])
        atual = store.get("campaign_sources", fonte["id"])
        self.assertIn("canal fora do ar", atual["last_error"])

    def test_fila_de_checagem_pega_a_mais_antiga_primeiro(self):
        primeira = self._fonte(url="https://twitch.tv/um")
        segunda = self._fonte(url="https://twitch.tv/dois")
        store.update("campaign_sources", primeira["id"], {"last_checked_at": "2026-08-23T10:00:00+00:00"})
        store.update("campaign_sources", segunda["id"], {"last_checked_at": None})
        fila = fontes.fontes_para_checar()
        self.assertEqual(segunda["id"], fila[0]["id"])

    def test_job_capturar_enfileira_a_deteccao(self):
        """O encaixe no pipeline: material capturado já entra para ser cortado."""
        from app import worker
        from app.queue import enqueue

        fonte = self._fonte()
        material = store.insert("campaign_materials", {
            "campaign_id": self.campanha["id"], "name": "Live", "local_path": "/tmp/x.mp4",
            "sha256": "abc", "authorized": 1, "authorization_source": "campanha",
            "status": "validated", "created_at": store.now(),
        })
        job = enqueue("capturar", fonte["id"], {"limite": 1}, "capturar:teste")
        with mock.patch.object(worker.fontes if hasattr(worker, "fontes") else fontes,
                               "buscar", return_value={"materiais": [material], "motivo": ""}), \
             mock.patch("app.fontes.buscar", return_value={"materiais": [material], "motivo": ""}):
            resultado = worker.process(job, "worker-teste")
        self.assertEqual(1, resultado["deteccoes_enfileiradas"])
        detects = store.rows("campaign_jobs", 10, 0, "kind=?", ("detect",))
        self.assertEqual(1, len(detects))
        self.assertEqual(material["id"], detects[0]["entity_id"])
