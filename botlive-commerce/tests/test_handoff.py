"""Fase 8: entrega ao Live Pilot por contrato, sem alterar a extensao."""

import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(RAIZ))

os.environ.setdefault("COMMERCE_DATABASE_PATH", str(Path(tempfile.mkdtemp()) / "handoff.db"))

from commerce import creatives, handoff, livepilot, products, store

store.DB_PATH = Path(os.environ["COMMERCE_DATABASE_PATH"])


class HandoffTests(unittest.TestCase):
    def setUp(self):
        store.migrar()
        with store.conectar() as db:
            for tabela in ("commerce_packages", "commerce_creatives", "commerce_assets",
                           "commerce_claims", "commerce_evidence", "commerce_products"):
                db.execute(f"DELETE FROM {tabela}")
        os.environ["COMMERCE_DRY_RUN"] = "true"
        self.pasta = Path(tempfile.mkdtemp())
        self.produto = products.criar_produto(
            "tiktok-shop", "Fone X", price=199.9, affiliate_url="https://loja.invalido/1"
        )
        evidencia = products.registrar_evidencia(
            self.produto["id"], "especificacao", "Bateria de 20h", "Site oficial", reliability="alta"
        )
        sustentado = products.propor_claim(self.produto["id"], "Dura 20 horas")
        products.sustentar_claim(sustentado["id"], [evidencia["id"]])
        bloqueado = products.propor_claim(self.produto["id"], "Cura insonia")
        products.bloquear_claim(bloqueado["id"], "Saude sem laudo")

        video = self.pasta / "demo.mp4"
        video.write_bytes(b"video")
        asset = creatives.registrar_asset(
            self.produto["id"], "video", str(video), rights="Cedido pelo fornecedor"
        )
        imagem = self.pasta / "hero.png"
        imagem.write_bytes(b"img")
        creatives.registrar_asset(
            self.produto["id"], "imagem", str(imagem), rights="Cedido pelo fornecedor"
        )
        criativo = creatives.criar(
            self.produto["id"], "LIVE_SCENE", hook="Olha", script="Dura 20 horas",
            cta="Link na bio", claim_ids=[sustentado["id"]], asset_ids=[asset["id"]],
        )
        creatives.aprovar(criativo["id"])
        self.pacote = livepilot.exportar(self.produto["id"])

    def tearDown(self):
        os.environ.pop("COMMERCE_DRY_RUN", None)

    def test_claim_sustentado_vira_resposta_aprovada(self):
        plano = handoff.traduzir(livepilot.carregar(self.pacote["package_id"]))
        produto = plano["chamadas"][0]["corpo"]
        self.assertEqual(["Dura 20 horas"], produto["approved_answers"])

    def test_claim_bloqueado_vira_alegacao_proibida(self):
        plano = handoff.traduzir(livepilot.carregar(self.pacote["package_id"]))
        produto = plano["chamadas"][0]["corpo"]
        self.assertIn("Cura insonia", produto["prohibited_claims"])
        self.assertNotIn("Cura insonia", produto["approved_answers"])

    def test_cta_vira_bloco_de_roteiro(self):
        plano = handoff.traduzir(livepilot.carregar(self.pacote["package_id"]))
        scripts = [x for x in plano["chamadas"] if x["rota"].endswith("/scripts")]
        self.assertEqual(1, len(scripts))
        self.assertEqual("cta", scripts[0]["corpo"]["kind"])
        self.assertEqual("Link na bio", scripts[0]["corpo"]["text"])

    def test_video_vira_media_do_live_pilot(self):
        plano = handoff.traduzir(livepilot.carregar(self.pacote["package_id"]))
        media = [x for x in plano["chamadas"] if x["rota"].endswith("/media")]
        self.assertEqual(1, len(media))
        self.assertEqual("video", media[0]["corpo"]["kind"])
        self.assertTrue(media[0]["corpo"]["authorized"])

    def test_imagem_nao_e_descartada_em_silencio(self):
        plano = handoff.traduzir(livepilot.carregar(self.pacote["package_id"]))
        self.assertIn("images", plano["nao_entregue"])
        self.assertEqual(1, plano["nao_entregue"]["images"]["quantidade"])
        self.assertTrue(plano["extensao_precisa_mudar"])

    def test_proveniencia_vai_junto_nas_notas(self):
        plano = handoff.traduzir(livepilot.carregar(self.pacote["package_id"]))
        notas = plano["chamadas"][0]["corpo"]["notes"]
        self.assertIn("Confianca", notas)
        self.assertIn("evidencia", notas)

    def test_dry_run_nao_faz_requisicao(self):
        with mock.patch.object(handoff, "_post", side_effect=AssertionError("nao pode enviar")):
            resultado = handoff.entregar(self.pacote["package_id"])
        self.assertTrue(resultado["dry_run"])
        self.assertFalse(resultado["enviado"])
        self.assertGreater(resultado["chamadas_previstas"], 0)

    def test_dry_run_e_o_padrao_do_ambiente(self):
        os.environ.pop("COMMERCE_DRY_RUN", None)
        self.assertTrue(handoff.dry_run_padrao())

    def test_envio_real_exige_token_do_live_pilot(self):
        os.environ["COMMERCE_DRY_RUN"] = "false"
        os.environ.pop("SHOP_LIVE_LOCAL_TOKEN", None)
        with self.assertRaises(store.CommerceError) as erro:
            handoff.entregar(self.pacote["package_id"], dry_run=False)
        self.assertIn("SHOP_LIVE_LOCAL_TOKEN", str(erro.exception))

    def test_envio_real_usa_as_rotas_publicas_na_ordem(self):
        os.environ["SHOP_LIVE_LOCAL_TOKEN"] = "token-local"
        chamadas = []

        def falso_post(rota, corpo):
            chamadas.append((rota, corpo))
            return {"id": f"id-{len(chamadas)}"}

        try:
            with mock.patch.object(handoff, "_post", side_effect=falso_post):
                resultado = handoff.entregar(self.pacote["package_id"], dry_run=False)
        finally:
            os.environ.pop("SHOP_LIVE_LOCAL_TOKEN", None)

        self.assertTrue(resultado["enviado"])
        self.assertEqual("/shop-live/v1/products", chamadas[0][0])
        # Tudo que vem depois recebe o id devolvido pelo Live Pilot.
        self.assertTrue(all(x[1]["product_id"] == "id-1" for x in chamadas[1:]))
        self.assertEqual("id-1", resultado["criados"]["produto"])

    def test_pacote_adulterado_nao_e_entregue(self):
        store.atualizar("commerce_packages", self.pacote["package_id"], {"checksum": "mentira"})
        with self.assertRaises(store.CommerceError):
            handoff.entregar(self.pacote["package_id"])

    def test_pacote_inexistente_e_recusado(self):
        with self.assertRaises(store.CommerceError):
            handoff.entregar("pacote-fantasma")

    def test_relatorio_declara_extensao_intocada(self):
        relatorio = handoff.relatorio_de_compatibilidade()
        self.assertFalse(relatorio["extensao_alterada"])
        self.assertIn("talking_points", relatorio["cobre"])
        self.assertIn("images", relatorio["nao_cobre"])
        self.assertEqual(2, len(relatorio["mudanca_necessaria_na_extensao"]))

    def test_nenhum_import_do_live_pilot(self):
        """O acoplamento tem que ser HTTP: nada de importar ou abrir o banco dele."""
        import ast

        fonte = Path(__file__).resolve().parents[1] / "commerce" / "handoff.py"
        arvore = ast.parse(fonte.read_text(encoding="utf-8"))

        importados = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                importados.update(alias.name for alias in no.names)
            elif isinstance(no, ast.ImportFrom):
                importados.add(no.module or "")
        for proibido in ("app", "sqlite3", "sqlalchemy"):
            self.assertNotIn(proibido, importados)
        self.assertTrue(any(x.startswith("urllib") for x in importados))

        # Nenhuma string do codigo (fora de docstring/comentario) aponta para o banco.
        literais = [
            no.value for no in ast.walk(arvore)
            if isinstance(no, ast.Constant) and isinstance(no.value, str)
            and not isinstance(getattr(no, "parent", None), ast.Expr)
        ]
        executaveis = [x for x in literais if "\n" not in x]
        self.assertFalse([x for x in executaveis if "shop-live.db" in x])


if __name__ == "__main__":
    unittest.main()
