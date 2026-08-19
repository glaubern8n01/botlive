"""Fase 7: proveniencia, claims sustentados, QA de criativo e LiveAssetPackage."""

import json, os, sys, tempfile, unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(RAIZ))

os.environ["COMMERCE_DATABASE_PATH"] = str(Path(tempfile.mkdtemp()) / "commerce.db")
os.environ.setdefault("VEXPUBLISH_DATABASE_PATH", str(Path(tempfile.mkdtemp()) / "vex-commerce.db"))

from commerce import bridge, creatives, livepilot, products, store

from vexpublish.core import models as vexmodels
from vexpublish.core import store as vexstore

store.DB_PATH = Path(os.environ["COMMERCE_DATABASE_PATH"])
vexstore.DB_PATH = Path(os.environ["VEXPUBLISH_DATABASE_PATH"])


class Base(unittest.TestCase):
    def setUp(self):
        store.migrar()
        vexstore.migrar()
        with store.conectar() as db:
            for tabela in ("commerce_packages", "commerce_creatives", "commerce_assets",
                           "commerce_claims", "commerce_evidence", "commerce_products"):
                db.execute(f"DELETE FROM {tabela}")
        self.pasta = Path(tempfile.mkdtemp())
        self.produto = products.criar_produto(
            "tiktok-shop", "Fone sem fio X", affiliate_url="https://loja.invalido/p/1"
        )

    def _evidencia(self, statement="Bateria de 20h", reliability="alta"):
        return products.registrar_evidencia(
            self.produto["id"], "especificacao", statement, "Página oficial do fabricante",
            reliability=reliability,
        )

    def _asset(self, kind="video"):
        arquivo = self.pasta / f"{kind}.mp4"
        arquivo.write_bytes(b"asset")
        return creatives.registrar_asset(
            self.produto["id"], kind, str(arquivo), rights="Cedido pelo fornecedor"
        )


class ProdutoTests(Base):
    def test_produto_manual_nao_nasce_confiavel(self):
        self.assertEqual(products.CONFIANCA_INICIAL, self.produto["confidence"])
        self.assertEqual("manual", self.produto["source"])

    def test_confianca_manual_nunca_chega_a_um(self):
        for indice in range(8):
            self._evidencia(f"Fato {indice}", "alta")
        ficha = products.ficha(self.produto["id"])
        self.assertLessEqual(ficha["confidence"], products.TETO_POR_ORIGEM["manual"])
        self.assertLess(ficha["confidence"], 1.0)

    def test_origem_oficial_tem_teto_maior_que_manual(self):
        self.assertGreater(
            products.TETO_POR_ORIGEM["catalogo-oficial"], products.TETO_POR_ORIGEM["manual"]
        )

    def test_evidencia_sobe_a_confianca(self):
        antes = products.ficha(self.produto["id"])["confidence"]
        self._evidencia()
        self.assertGreater(products.ficha(self.produto["id"])["confidence"], antes)

    def test_evidencia_sem_origem_e_recusada(self):
        with self.assertRaises(store.CommerceError):
            products.registrar_evidencia(self.produto["id"], "especificacao", "Algo", "  ")

    def test_plataforma_invalida_e_recusada(self):
        with self.assertRaises(store.CommerceError):
            products.criar_produto("mercado-livre", "Produto")

    def test_ficha_traz_proveniencia_junto(self):
        self._evidencia()
        ficha = products.ficha(self.produto["id"])
        self.assertEqual(1, len(ficha["evidencias"]))
        self.assertIn("confidence_teto", ficha)


class ClaimTests(Base):
    def test_claim_sem_evidencia_nao_e_sustentado(self):
        claim = products.propor_claim(self.produto["id"], "Dura 20 horas")
        self.assertEqual("proposed", claim["state"])
        with self.assertRaises(store.CommerceError) as erro:
            products.sustentar_claim(claim["id"], [])
        self.assertIn("sem suporte documentado", str(erro.exception))

    def test_claim_com_evidencia_e_sustentado(self):
        evidencia = self._evidencia()
        claim = products.propor_claim(self.produto["id"], "Dura 20 horas")
        sustentado = products.sustentar_claim(claim["id"], [evidencia["id"]])
        self.assertEqual("supported", sustentado["state"])
        self.assertIn("Dura 20 horas", products.claims_permitidos(self.produto["id"]))

    def test_evidencia_de_outro_produto_e_recusada(self):
        outro = products.criar_produto("shopee", "Outro produto")
        alheia = products.registrar_evidencia(outro["id"], "review", "Bom", "Site")
        claim = products.propor_claim(self.produto["id"], "Dura 20 horas")
        with self.assertRaises(store.CommerceError):
            products.sustentar_claim(claim["id"], [alheia["id"]])

    def test_claim_bloqueado_nao_pode_ser_sustentado(self):
        evidencia = self._evidencia()
        claim = products.propor_claim(self.produto["id"], "Cura insonia")
        products.bloquear_claim(claim["id"], "Alegacao de saude sem laudo")
        with self.assertRaises(store.CommerceError):
            products.sustentar_claim(claim["id"], [evidencia["id"]])

    def test_bloqueio_exige_motivo(self):
        claim = products.propor_claim(self.produto["id"], "Cura tudo")
        with self.assertRaises(store.CommerceError):
            products.bloquear_claim(claim["id"], "")

    def test_claim_repetido_nao_duplica(self):
        primeiro = products.propor_claim(self.produto["id"], "Leve")
        segundo = products.propor_claim(self.produto["id"], "Leve")
        self.assertEqual(primeiro["id"], segundo["id"])


class CriativoTests(Base):
    def test_tipo_invalido_e_recusado(self):
        with self.assertRaises(store.CommerceError):
            creatives.criar(self.produto["id"], "VIDEO_QUALQUER")

    def test_os_doze_tipos_do_documento_existem(self):
        self.assertEqual(12, len(creatives.TIPOS))
        for esperado in ("UGC_SELFIE", "PRODUCT_HERO", "LIVE_SCENE", "THUMBNAIL"):
            self.assertIn(esperado, creatives.TIPOS)

    def test_criativo_identico_nao_duplica(self):
        primeiro = creatives.criar(self.produto["id"], "DEMO", hook="Olha isso", script="texto")
        segundo = creatives.criar(self.produto["id"], "DEMO", hook="Olha isso", script="texto")
        self.assertEqual(primeiro["id"], segundo["id"])

    def test_qa_reprova_claim_sem_evidencia_no_roteiro(self):
        products.propor_claim(self.produto["id"], "Dura 20 horas")
        asset = self._asset()
        criativo = creatives.criar(
            self.produto["id"], "DEMO", hook="Olha", script="Dura 20 horas de verdade",
            cta="Compra aqui", asset_ids=[asset["id"]],
        )
        resultado = creatives.rodar_qa(criativo["id"])
        self.assertFalse(resultado["ok"])
        self.assertIn("claim_sem_evidencia", [x["regra"] for x in resultado["problemas"]])

    def test_qa_reprova_claim_bloqueado_no_roteiro(self):
        claim = products.propor_claim(self.produto["id"], "Cura insonia")
        products.bloquear_claim(claim["id"], "Saude sem laudo")
        asset = self._asset()
        criativo = creatives.criar(
            self.produto["id"], "DEMO", hook="Olha", script="Ele cura insonia",
            cta="Compra", asset_ids=[asset["id"]],
        )
        resultado = creatives.rodar_qa(criativo["id"])
        self.assertIn("claim_bloqueado", [x["regra"] for x in resultado["problemas"]])

    def test_qa_reprova_sem_asset_e_sem_cta(self):
        criativo = creatives.criar(self.produto["id"], "DEMO", hook="Oi", script="texto")
        regras = [x["regra"] for x in creatives.rodar_qa(criativo["id"])["problemas"]]
        self.assertIn("sem_asset", regras)
        self.assertIn("sem_cta", regras)

    def test_aprovacao_e_bloqueada_por_qa_sujo(self):
        criativo = creatives.criar(self.produto["id"], "DEMO", hook="Oi", script="texto")
        with self.assertRaises(store.CommerceError):
            creatives.aprovar(criativo["id"])
        self.assertEqual("qa_failed", store.obter("commerce_creatives", criativo["id"])["status"])

    def test_criativo_limpo_e_aprovado(self):
        evidencia = self._evidencia()
        claim = products.propor_claim(self.produto["id"], "Dura 20 horas")
        products.sustentar_claim(claim["id"], [evidencia["id"]])
        asset = self._asset()
        criativo = creatives.criar(
            self.produto["id"], "PRODUCT_HERO", hook="Olha", script="Dura 20 horas",
            cta="Link na bio", claim_ids=[claim["id"]], asset_ids=[asset["id"]],
        )
        self.assertEqual("approved", creatives.aprovar(criativo["id"])["status"])

    def test_asset_sem_direito_e_recusado(self):
        with self.assertRaises(store.CommerceError):
            creatives.registrar_asset(self.produto["id"], "imagem", "x.png", rights="  ")


class PacoteTests(Base):
    def _criativo_aprovado(self, cta="Link na bio"):
        evidencia = self._evidencia()
        claim = products.propor_claim(self.produto["id"], "Dura 20 horas")
        products.sustentar_claim(claim["id"], [evidencia["id"]])
        asset = self._asset()
        self._asset("imagem")
        criativo = creatives.criar(
            self.produto["id"], "LIVE_SCENE", hook="Olha", script="Dura 20 horas",
            cta=cta, claim_ids=[claim["id"]], asset_ids=[asset["id"]],
        )
        creatives.aprovar(criativo["id"])
        return criativo

    def test_pacote_exige_claim_sustentado(self):
        with self.assertRaises(store.CommerceError) as erro:
            livepilot.montar(self.produto["id"])
        self.assertIn("claim sustentado", str(erro.exception))

    def test_pacote_exige_criativo_aprovado(self):
        evidencia = self._evidencia()
        claim = products.propor_claim(self.produto["id"], "Dura 20 horas")
        products.sustentar_claim(claim["id"], [evidencia["id"]])
        with self.assertRaises(store.CommerceError):
            livepilot.montar(self.produto["id"])

    def test_pacote_segue_o_contrato_do_documento(self):
        self._criativo_aprovado()
        pacote = livepilot.montar(self.produto["id"])
        for campo in livepilot.CAMPOS:
            self.assertIn(campo, pacote)

    def test_talking_points_so_saem_de_claim_sustentado(self):
        self._criativo_aprovado()
        bloqueado = products.propor_claim(self.produto["id"], "Cura insonia")
        products.bloquear_claim(bloqueado["id"], "Saude sem laudo")
        products.propor_claim(self.produto["id"], "Melhor do mundo")

        pacote = livepilot.montar(self.produto["id"])
        self.assertEqual(["Dura 20 horas"], pacote["talking_points"])
        self.assertNotIn("Cura insonia", pacote["talking_points"])
        self.assertNotIn("Melhor do mundo", pacote["talking_points"])
        self.assertIn("Cura insonia", pacote["metadata"]["claims_blocked"])

    def test_exportar_versiona_sem_sobrescrever(self):
        self._criativo_aprovado()
        primeiro = livepilot.exportar(self.produto["id"])
        segundo = livepilot.exportar(self.produto["id"])
        self.assertEqual(1, primeiro["version"])
        self.assertEqual(2, segundo["version"])
        self.assertEqual(2, len(livepilot.historico(self.produto["id"])))

    def test_exportar_grava_arquivo_para_a_extensao(self):
        self._criativo_aprovado()
        destino = self.pasta / "pacote.json"
        resultado = livepilot.exportar(self.produto["id"], destino)
        conteudo = json.loads(destino.read_text(encoding="utf-8"))
        self.assertEqual(self.produto["id"], conteudo["product_id"])
        self.assertEqual(resultado["version"], conteudo["metadata"]["pacote_versao"])

    def test_pacote_adulterado_e_detectado(self):
        self._criativo_aprovado()
        exportado = livepilot.exportar(self.produto["id"])
        store.atualizar(
            "commerce_packages", exportado["package_id"], {"checksum": "mentira"}
        )
        with self.assertRaises(store.CommerceError):
            livepilot.carregar(exportado["package_id"])


class FilaTests(Base):
    def setUp(self):
        super().setUp()
        os.environ["COMMERCE_ENABLED"] = "true"
        canal = vexmodels.Channel(name=f"Loja {store.uid()[:6]}", platforms=["tiktok"]).salvar()
        self.canal_id = canal["id"]
        registro = vexmodels.Account(
            channel_id=self.canal_id, platform="tiktok",
            handle=f"@loja{store.uid()[:6]}", status="active",
        ).salvar()
        self.conta = vexstore.obter("vexpublish_accounts", registro["id"])

    def tearDown(self):
        for chave in ("COMMERCE_ENABLED", "COMMERCE_AUTO_PUBLISH"):
            os.environ.pop(chave, None)

    def _pronto(self):
        evidencia = self._evidencia()
        claim = products.propor_claim(self.produto["id"], "Dura 20 horas")
        products.sustentar_claim(claim["id"], [evidencia["id"]])
        asset = self._asset()
        criativo = creatives.criar(
            self.produto["id"], "DEMO", hook="Olha", script="Dura 20 horas",
            cta="Link na bio", claim_ids=[claim["id"]], asset_ids=[asset["id"]],
        )
        creatives.aprovar(criativo["id"])
        saida = self.pasta / "criativo.mp4"
        saida.write_bytes(b"video")
        store.atualizar("commerce_creatives", criativo["id"], {"output_path": str(saida)})
        return criativo

    def test_flags_nascem_seguras(self):
        estado = bridge.flags()
        self.assertFalse(estado["auto_publish"])
        self.assertTrue(estado["require_approval"])
        self.assertTrue(estado["dry_run"])

    def test_modulo_desligado_nao_enfileira(self):
        criativo = self._pronto()
        os.environ["COMMERCE_ENABLED"] = "false"
        with self.assertRaises(store.CommerceError):
            bridge.enfileirar(criativo["id"], self.canal_id)

    def test_auto_publish_ligado_e_recusado(self):
        criativo = self._pronto()
        os.environ["COMMERCE_AUTO_PUBLISH"] = "true"
        with self.assertRaises(store.CommerceError) as erro:
            bridge.enfileirar(criativo["id"], self.canal_id)
        self.assertIn("COMMERCE_AUTO_PUBLISH", str(erro.exception))

    def test_criativo_sem_aprovacao_nao_passa_na_checagem(self):
        criativo = creatives.criar(self.produto["id"], "DEMO", hook="Oi", script="texto")
        relatorio = bridge.checar_antes_de_publicar(criativo["id"])
        self.assertFalse(relatorio["ok"])
        self.assertIn("criativo sem aprovacao humana", relatorio["problemas"])

    def test_produto_sem_link_e_bloqueado(self):
        criativo = self._pronto()
        store.atualizar("commerce_products", self.produto["id"], {"affiliate_url": ""})
        relatorio = bridge.checar_antes_de_publicar(criativo["id"])
        self.assertIn("produto sem link", relatorio["problemas"])

    def test_fila_cria_job_em_draft_e_dry_run(self):
        criativo = self._pronto()
        resultado = bridge.enfileirar(criativo["id"], self.canal_id)
        self.assertEqual(1, resultado["total"])
        self.assertEqual("draft", resultado["jobs"][0]["status"])
        self.assertTrue(resultado["jobs"][0]["dry_run"])
        self.assertEqual("queued", store.obter("commerce_creatives", criativo["id"])["status"])

    def test_legenda_leva_o_link_do_produto(self):
        criativo = self._pronto()
        resultado = bridge.enfileirar(criativo["id"], self.canal_id)
        job = vexstore.obter("vexpublish_jobs", resultado["jobs"][0]["publish_job_id"])
        self.assertIn("https://loja.invalido/p/1", job["caption"])

    def test_canal_inexistente_e_recusado(self):
        criativo = self._pronto()
        with self.assertRaises(store.CommerceError):
            bridge.enfileirar(criativo["id"], "canal-fantasma")


if __name__ == "__main__":
    unittest.main()
