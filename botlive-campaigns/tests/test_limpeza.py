"""Faxina do material bruto capturado das fontes."""

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local-agent"))

from app import limpeza, store


class TestLimpeza(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.raiz = Path(self.pasta.name)
        patch = mock.patch.object(store, "DB_PATH", self.raiz / "campanhas.db")
        patch.start()
        self.addCleanup(patch.stop)
        store.migrate()
        self.campanha = store.insert("campaign_campaigns", {
            "platform": "viewx", "name": "Teste", "created_at": store.now(),
            "updated_at": store.now()})

    def _material(self, dias_atras=0, megas=300):
        arquivo = self.raiz / f"bruto-{dias_atras}-{megas}.mp4"
        arquivo.write_bytes(b"\0" * 1024)
        criado = (datetime.now(timezone.utc) - timedelta(days=dias_atras)).isoformat()
        return store.insert("campaign_materials", {
            "campaign_id": self.campanha["id"], "name": arquivo.name,
            "local_path": str(arquivo), "size_bytes": int(megas * 1e6),
            "sha256": arquivo.name, "status": "validated", "created_at": criado})

    def _corte(self, material):
        return store.insert("campaign_candidates", {
            "campaign_id": self.campanha["id"], "material_id": material["id"],
            "idempotency_key": f"k-{material['id']}", "created_at": store.now(),
            "updated_at": store.now()})

    def test_material_velho_perde_o_arquivo_mas_nao_a_linha(self):
        """A linha e a memoria de deduplicacao: sem ela o bot rebaixa o mesmo
        VOD amanha."""
        velho = self._material(dias_atras=5)
        limpeza.limpar(dias=3, teto_gb=999)
        self.assertFalse(Path(velho["local_path"]).exists())
        self.assertEqual("purged", store.get("campaign_materials", velho["id"])["status"])

    def test_material_novo_fica(self):
        novo = self._material(dias_atras=0)
        limpeza.limpar(dias=3, teto_gb=999)
        self.assertTrue(Path(novo["local_path"]).exists())

    def test_teto_de_espaco_leva_o_mais_velho_que_ja_virou_corte(self):
        antigo = self._material(dias_atras=2, megas=40_000)
        recente = self._material(dias_atras=1, megas=40_000)
        self._corte(antigo)
        self._corte(recente)
        resultado = limpeza.limpar(dias=30, teto_gb=50)
        self.assertFalse(Path(antigo["local_path"]).exists())
        self.assertTrue(Path(recente["local_path"]).exists())
        self.assertEqual(1, resultado["apagados"])

    def test_teto_nao_leva_material_que_ainda_nao_virou_corte(self):
        """Esse ainda tem trabalho pela frente - apagar seria jogar fora a
        gravacao antes de cortar."""
        pendente = self._material(dias_atras=2, megas=90_000)
        limpeza.limpar(dias=30, teto_gb=10)
        self.assertTrue(Path(pendente["local_path"]).exists())

    def test_rodar_duas_vezes_nao_reclama_de_arquivo_ausente(self):
        self._material(dias_atras=5)
        limpeza.limpar(dias=3, teto_gb=999)
        self.assertEqual(0, limpeza.limpar(dias=3, teto_gb=999)["apagados"])




class TestOrfaos(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.raiz = Path(self.pasta.name)
        patch = mock.patch.object(store, "DB_PATH", self.raiz / "campanhas.db")
        patch.start()
        self.addCleanup(patch.stop)
        store.migrate()
        self.midia = self.raiz / "midia"
        self.midia.mkdir()
        self.campanha = store.insert("campaign_campaigns", {
            "platform": "viewx", "name": "Teste", "created_at": store.now(),
            "updated_at": store.now()})

    def test_arquivo_sem_material_no_banco_e_apagado(self):
        """Foi assim que dois parciais de um VOD ocuparam 58 GB calados: sem
        linha no banco, as travas de idade e de teto nao os enxergam."""
        orfao = self.midia / "v2814440962.temp.mp4"
        orfao.write_bytes(b"\0" * 2048)
        resultado = limpeza.varrer_orfaos(self.midia)
        self.assertEqual(1, resultado["apagados"])
        self.assertFalse(orfao.exists())

    def test_arquivo_de_material_registrado_nao_e_tocado(self):
        arquivo = self.midia / "bom.mp4"
        arquivo.write_bytes(b"\0" * 512)
        store.insert("campaign_materials", {
            "campaign_id": self.campanha["id"], "name": "bom.mp4",
            "local_path": str(arquivo), "sha256": "abc", "created_at": store.now()})
        limpeza.varrer_orfaos(self.midia)
        self.assertTrue(arquivo.exists())

    def test_pasta_inexistente_nao_quebra(self):
        self.assertEqual(0, limpeza.varrer_orfaos(self.raiz / "nao-existe")["apagados"])


if __name__ == "__main__":
    unittest.main()
