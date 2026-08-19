"""Fase 5: fontes autorizadas, biblioteca com dedup, plano de adaptacao e fila.

Nenhum teste renderiza video de verdade: o render usa o motor legado do
BotLive e e exercitado por mock, para que a suite continue rapida e nao
dependa de moviepy/ffmpeg instalados.
"""

import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local-agent"))
sys.path.insert(0, str(RAIZ))

os.environ["IMPORT_DATABASE_PATH"] = str(Path(tempfile.mkdtemp()) / "import.db")
os.environ["VEXPUBLISH_DATABASE_PATH"] = str(Path(tempfile.mkdtemp()) / "vexpublish.db")
os.environ.setdefault("IMPORT_ADMIN_TOKEN", "admin-import")
os.environ.setdefault("IMPORT_REVIEWER_TOKEN", "reviewer-import")

from importer import adapt, bridge, library, sources, store

from vexpublish.core import models as vexmodels
from vexpublish.core import store as vexstore

store.DB_PATH = Path(os.environ["IMPORT_DATABASE_PATH"])
vexstore.DB_PATH = Path(os.environ["VEXPUBLISH_DATABASE_PATH"])


def fonte_valida(**extra):
    base = {
        "name": f"Fonte {store.uid()[:8]}",
        "kind": "local_folder",
        "authorized": True,
        "authorization_source": "Contrato com o produtor",
        "license": "autorizacao-direta",
    }
    base.update(extra)
    return base


class Base(unittest.TestCase):
    def setUp(self):
        store.migrar()
        vexstore.migrar()
        with store.conectar() as db:
            for tabela in ("import_adaptations", "import_items", "import_sources", "import_audit"):
                db.execute(f"DELETE FROM {tabela}")
        self.pasta = Path(tempfile.mkdtemp())

    def _video(self, nome="a.mp4", conteudo=b"conteudo-de-video"):
        caminho = self.pasta / nome
        caminho.write_bytes(conteudo)
        return caminho


class FonteTests(Base):
    def test_fonte_sem_autorizacao_e_recusada(self):
        with self.assertRaises(store.ImportError_):
            sources.criar(**fonte_valida(authorized=False))

    def test_fonte_sem_quem_autorizou_e_recusada(self):
        with self.assertRaises(store.ImportError_):
            sources.criar(**fonte_valida(authorization_source="  "))

    def test_licenca_desconhecida_e_recusada(self):
        with self.assertRaises(store.ImportError_):
            sources.criar(**fonte_valida(license="pode-usar-acho"))

    def test_tipo_invalido_e_recusado(self):
        with self.assertRaises(store.ImportError_):
            sources.criar(**fonte_valida(kind="torrent"))

    def test_fonte_de_urls_exige_origem(self):
        with self.assertRaises(store.ImportError_):
            sources.criar(**fonte_valida(kind="url_list", location=""))

    def test_fonte_valida_entra_ativa(self):
        fonte = sources.criar(**fonte_valida())
        self.assertEqual(1, fonte["authorized"])
        self.assertEqual("active", fonte["status"])

    def test_fonte_arquivada_nao_importa(self):
        fonte = sources.criar(**fonte_valida())
        sources.arquivar(fonte["id"])
        with self.assertRaises(store.ImportError_):
            sources.exigir_ativa(fonte["id"])


class DownloadTests(Base):
    def test_download_exige_flag_do_ambiente(self):
        fonte = sources.criar(**fonte_valida(kind="url_list", location="https://exemplo.invalido/lista", allow_download=True))
        os.environ["IMPORT_ALLOW_DOWNLOAD"] = "false"
        with self.assertRaises(store.ImportError_) as erro:
            sources.exigir_download_permitido(fonte)
        self.assertIn("IMPORT_ALLOW_DOWNLOAD", str(erro.exception))

    def test_download_exige_permissao_da_fonte(self):
        fonte = sources.criar(**fonte_valida(kind="url_list", location="https://exemplo.invalido/lista", allow_download=False))
        os.environ["IMPORT_ALLOW_DOWNLOAD"] = "true"
        try:
            with self.assertRaises(store.ImportError_):
                sources.exigir_download_permitido(fonte)
        finally:
            os.environ["IMPORT_ALLOW_DOWNLOAD"] = "false"

    def test_download_liberado_com_os_dois_interruptores(self):
        fonte = sources.criar(**fonte_valida(kind="url_list", location="https://exemplo.invalido/lista", allow_download=True))
        os.environ["IMPORT_ALLOW_DOWNLOAD"] = "true"
        try:
            self.assertEqual(fonte["id"], sources.exigir_download_permitido(fonte)["id"])
        finally:
            os.environ["IMPORT_ALLOW_DOWNLOAD"] = "false"


class BibliotecaTests(Base):
    def setUp(self):
        super().setUp()
        self.fonte = sources.criar(**fonte_valida(location=str(self.pasta)))

    def test_mesmo_arquivo_nao_entra_duas_vezes(self):
        video = self._video()
        primeiro = library.registrar(self.fonte["id"], video)
        segundo = library.registrar(self.fonte["id"], video)
        self.assertEqual(primeiro["id"], segundo["id"])
        self.assertEqual(1, len(library.biblioteca()))

    def test_conteudo_igual_em_caminho_diferente_e_o_mesmo_item(self):
        primeiro = library.registrar(self.fonte["id"], self._video("a.mp4", b"igual"))
        segundo = library.registrar(self.fonte["id"], self._video("b.mp4", b"igual"))
        self.assertEqual(primeiro["id"], segundo["id"])

    def test_extensao_nao_suportada_e_recusada(self):
        with self.assertRaises(store.ImportError_):
            library.registrar(self.fonte["id"], self._video("a.exe"))

    def test_arquivo_vazio_e_recusado(self):
        with self.assertRaises(store.ImportError_):
            library.registrar(self.fonte["id"], self._video("vazio.mp4", b""))

    def test_arquivo_inexistente_e_recusado(self):
        with self.assertRaises(store.ImportError_):
            library.registrar(self.fonte["id"], self.pasta / "fantasma.mp4")

    def test_lote_conta_importados_repetidos_e_recusados(self):
        self._video("um.mp4", b"um")
        self._video("dois.mp4", b"dois")
        self._video("tres.txt", b"nao-e-video")
        primeiro = library.importar_pasta(self.fonte["id"])
        self.assertEqual(2, primeiro["importados"])
        self.assertEqual(0, primeiro["repetidos"])

        self._video("quatro.mp4", b"quatro")
        segundo = library.importar_pasta(self.fonte["id"])
        self.assertEqual(1, segundo["importados"])
        self.assertEqual(2, segundo["repetidos"])

    def test_lote_guarda_credito_da_autorizacao(self):
        item = library.registrar(self.fonte["id"], self._video())
        self.assertEqual("Contrato com o produtor", item["credit"])


class PlanoTests(Base):
    def setUp(self):
        super().setUp()
        self.fonte = sources.criar(**fonte_valida(location=str(self.pasta)))
        self.item = library.registrar(self.fonte["id"], self._video())

    def test_plano_padrao_e_vertical(self):
        plano = adapt.validar_plano({})
        self.assertEqual("vertical-fit", plano["layout"])
        self.assertTrue(plano["keep_credit"])

    def test_layout_invalido_e_recusado(self):
        with self.assertRaises(store.ImportError_):
            adapt.validar_plano({"layout": "quadrado"})

    def test_foco_fora_do_intervalo_e_recusado(self):
        with self.assertRaises(store.ImportError_):
            adapt.validar_plano({"layout": "vertical-crop", "focus_x": 3})

    def test_campo_desconhecido_e_recusado(self):
        with self.assertRaises(store.ImportError_):
            adapt.validar_plano({"blur_tudo": True})

    def test_remocao_de_autoria_e_recusada(self):
        for chave in ("remove_watermark", "remove_credits", "strip_attribution", "bypass_drm"):
            with self.subTest(chave=chave):
                with self.assertRaises(store.ImportError_) as erro:
                    adapt.validar_plano({chave: True})
                self.assertIn("nao remove autoria", str(erro.exception))

    def test_credito_nao_pode_ser_desligado(self):
        with self.assertRaises(store.ImportError_):
            adapt.validar_plano({"keep_credit": False})

    def test_intro_inexistente_e_recusada(self):
        with self.assertRaises(store.ImportError_):
            adapt.validar_plano({"intro_path": str(self.pasta / "nao-existe.mp4")})

    def test_planejar_e_idempotente(self):
        primeiro = adapt.planejar(self.item["id"], "canal-1", {"layout": "vertical-fit"})
        segundo = adapt.planejar(self.item["id"], "canal-1", {"layout": "vertical-fit"})
        self.assertEqual(primeiro["id"], segundo["id"])
        self.assertEqual("planned", primeiro["status"])

    def test_plano_diferente_gera_adaptacao_diferente(self):
        primeiro = adapt.planejar(self.item["id"], "canal-1", {"layout": "vertical-fit"})
        segundo = adapt.planejar(self.item["id"], "canal-1", {"layout": "vertical-crop"})
        self.assertNotEqual(primeiro["id"], segundo["id"])


class FilaTests(Base):
    def setUp(self):
        super().setUp()
        self.fonte = sources.criar(**fonte_valida(location=str(self.pasta)))
        self.item = library.registrar(self.fonte["id"], self._video())
        canal = vexmodels.Channel(name=f"Marca {store.uid()[:6]}", platforms=["tiktok"]).salvar()
        self.canal_id = canal["id"]
        self.adaptacao = adapt.planejar(self.item["id"], self.canal_id, {})
        self.saida = self.pasta / "adaptado.mp4"
        self.saida.write_bytes(b"video-adaptado")
        store.atualizar(
            "import_adaptations",
            self.adaptacao["id"],
            {"status": "rendered", "output_path": str(self.saida), "updated_at": store.agora()},
        )
        os.environ["IMPORT_ADAPT_PUBLISH_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("IMPORT_ADAPT_PUBLISH_ENABLED", None)

    def _conta(self, handle, status="active", platform="tiktok"):
        registro = vexmodels.Account(
            channel_id=self.canal_id, platform=platform, handle=handle, status=status
        ).salvar()
        return vexstore.obter("vexpublish_accounts", registro["id"])

    def test_modulo_desligado_nao_enfileira(self):
        os.environ["IMPORT_ADAPT_PUBLISH_ENABLED"] = "false"
        with self.assertRaises(store.ImportError_) as erro:
            bridge.enfileirar(self.adaptacao["id"])
        self.assertIn("IMPORT_ADAPT_PUBLISH_ENABLED", str(erro.exception))

    def test_adaptacao_nao_renderizada_nao_enfileira(self):
        outra = adapt.planejar(self.item["id"], self.canal_id, {"layout": "vertical-crop"})
        with self.assertRaises(store.ImportError_):
            bridge.enfileirar(outra["id"])

    def test_canal_sem_conta_ativa_recusa(self):
        self._conta("@inativa", status="inactive")
        with self.assertRaises(store.ImportError_) as erro:
            bridge.enfileirar(self.adaptacao["id"])
        self.assertIn("conta ativa", str(erro.exception))

    def test_fila_cria_um_job_por_conta_ativa(self):
        self._conta("@tiktok_um")
        self._conta("@yt_um", platform="youtube")
        resultado = bridge.enfileirar(self.adaptacao["id"])
        self.assertEqual(2, resultado["total"])
        self.assertTrue(all(x["status"] == "draft" for x in resultado["jobs"]))
        self.assertTrue(all(x["dry_run"] for x in resultado["jobs"]))

    def test_fila_pode_filtrar_plataforma(self):
        self._conta("@tiktok_dois")
        self._conta("@yt_dois", platform="youtube")
        resultado = bridge.enfileirar(self.adaptacao["id"], platform="youtube")
        self.assertEqual(1, resultado["total"])
        self.assertEqual("youtube", resultado["jobs"][0]["platform"])

    def test_enfileirar_duas_vezes_nao_duplica_job(self):
        self._conta("@tiktok_tres")
        primeiro = bridge.enfileirar(self.adaptacao["id"])
        segundo = bridge.enfileirar(self.adaptacao["id"])
        self.assertEqual(
            primeiro["jobs"][0]["publish_job_id"], segundo["jobs"][0]["publish_job_id"]
        )

    def test_arquivo_adaptado_ausente_recusa(self):
        self._conta("@tiktok_quatro")
        store.atualizar(
            "import_adaptations",
            self.adaptacao["id"],
            {"output_path": str(self.pasta / "sumiu.mp4"), "updated_at": store.agora()},
        )
        with self.assertRaises(store.ImportError_):
            bridge.enfileirar(self.adaptacao["id"])


class RenderTests(Base):
    def setUp(self):
        super().setUp()
        self.fonte = sources.criar(**fonte_valida(location=str(self.pasta)))
        self.item = library.registrar(self.fonte["id"], self._video())
        self.adaptacao = adapt.planejar(self.item["id"], "canal-x", {"title": "Titulo"})

    def test_render_usa_o_motor_do_botlive_e_valida_a_saida(self):
        class Validacao:
            valid, reason, width, height = True, "", 1080, 1920
            duration_seconds, has_audio = 12.0, True

        clipper = mock.Mock()
        clipper.validar_video_final.return_value = Validacao()
        overlay = mock.Mock()
        overlay.OverlayConfig.return_value = mock.Mock(enabled=True)

        def render_falso(entrada, saida, output_layout, focus_x):
            Path(saida).write_bytes(b"render")

        clipper.renderizar_layout.side_effect = render_falso

        with mock.patch.object(adapt, "_legado", side_effect=lambda nome: clipper if nome == "clipper" else overlay):
            resultado = adapt.executar(self.adaptacao["id"])

        self.assertEqual("rendered", resultado["status"])
        self.assertEqual(1080, resultado["width"])
        self.assertTrue(clipper.renderizar_layout.called)
        self.assertTrue(overlay.aplicar_overlay_no_video.called)

    def test_saida_invalida_marca_falha_sem_apagar_o_original(self):
        class Validacao:
            valid, reason = False, "video preto"
            width = height = 0
            duration_seconds, has_audio = 0.0, False

        clipper = mock.Mock()
        clipper.validar_video_final.return_value = Validacao()
        clipper.renderizar_layout.side_effect = lambda entrada, saida, output_layout, focus_x: Path(saida).write_bytes(b"x")

        with mock.patch.object(adapt, "_legado", side_effect=lambda nome: clipper if nome == "clipper" else mock.Mock()):
            with self.assertRaises(store.ImportError_):
                adapt.executar(self.adaptacao["id"])

        self.assertEqual("failed", store.obter("import_adaptations", self.adaptacao["id"])["status"])
        self.assertTrue(Path(self.item["local_path"]).is_file())


if __name__ == "__main__":
    unittest.main()


class ExtrasTests(Base):
    """Capa e narracao: funcao desta operacao, nao do pipeline de cortes."""

    def setUp(self):
        super().setUp()
        self.fonte = sources.criar(**fonte_valida(location=str(self.pasta)))
        self.item = library.registrar(self.fonte["id"], self._video())

    def test_capa_entra_no_plano_por_padrao_e_narracao_nao(self):
        plano = adapt.validar_plano({})
        self.assertTrue(plano["capa"])
        self.assertFalse(plano["narracao"])

    def test_da_pra_ligar_narracao(self):
        self.assertTrue(adapt.validar_plano({"narracao": True})["narracao"])

    def test_plano_sem_extras_nao_gera_arquivo(self):
        extras = adapt._gerar_extras({"capa": False, "narracao": False},
                                     self.pasta / "x.mp4", "ad-1")
        self.assertEqual("", extras["cover_path"])
        self.assertEqual("", extras["narration_path"])

    def test_capa_e_gerada_a_partir_do_plano(self):
        alvo = self.pasta / "adaptado.mp4"
        alvo.write_bytes(b"video")
        extras = adapt._gerar_extras(
            {"capa": True, "narracao": False, "layout": "vertical-fit",
             "title": "Achadinho do dia", "brand": "Loja", "cta": "Link na bio"},
            alvo, "ad-2",
        )
        self.assertTrue(extras["cover_path"], extras["extras_error"])
        self.assertTrue(Path(extras["cover_path"]).is_file())

    def test_falha_de_extra_nao_derruba_a_adaptacao(self):
        """Sem texto para narrar, registra o motivo e segue."""
        alvo = self.pasta / "adaptado2.mp4"
        alvo.write_bytes(b"video")
        extras = adapt._gerar_extras(
            {"capa": False, "narracao": True, "layout": "vertical-fit",
             "title": "", "description": ""},
            alvo, "ad-3",
        )
        self.assertEqual("", extras["narration_path"])
        self.assertIn("sem texto", extras["extras_error"])


class DownloaderTests(Base):
    """O executor de download que faltava. Continua preso as duas travas."""

    def test_fonte_sem_permissao_de_download_e_recusada(self):
        from importer import downloader

        fonte = sources.criar(**fonte_valida(kind="url_list",
                                             location="https://exemplo.invalido/perfil",
                                             allow_download=False))
        os.environ["IMPORT_ALLOW_DOWNLOAD"] = "true"
        try:
            with self.assertRaises(store.ImportError_):
                downloader.baixar(fonte["id"])
        finally:
            os.environ["IMPORT_ALLOW_DOWNLOAD"] = "false"

    def test_ambiente_desligado_recusa_mesmo_com_fonte_liberada(self):
        from importer import downloader

        fonte = sources.criar(**fonte_valida(kind="url_list",
                                             location="https://exemplo.invalido/perfil",
                                             allow_download=True))
        os.environ["IMPORT_ALLOW_DOWNLOAD"] = "false"
        with self.assertRaises(store.ImportError_) as erro:
            downloader.baixar(fonte["id"])
        self.assertIn("IMPORT_ALLOW_DOWNLOAD", str(erro.exception))

    def test_fonte_arquivada_nao_baixa(self):
        from importer import downloader

        fonte = sources.criar(**fonte_valida(kind="url_list",
                                             location="https://exemplo.invalido/x",
                                             allow_download=True))
        sources.arquivar(fonte["id"])
        os.environ["IMPORT_ALLOW_DOWNLOAD"] = "true"
        try:
            with self.assertRaises(store.ImportError_):
                downloader.baixar(fonte["id"])
        finally:
            os.environ["IMPORT_ALLOW_DOWNLOAD"] = "false"


class VariacaoTests(Base):
    """Cada conta recebe uma edicao diferente, de forma reproduzivel."""

    def test_gera_variacoes_todas_distintas(self):
        from importer import variacao

        vs = variacao.gerar("item-1", 5)
        self.assertEqual(5, len(vs))
        self.assertTrue(variacao.distintas(vs), [variacao.assinatura(v) for v in vs])

    def test_mesma_semente_devolve_o_mesmo_plano(self):
        from importer import variacao

        a = variacao.gerar("item-2", 4)
        b = variacao.gerar("item-2", 4)
        self.assertEqual([variacao.assinatura(x) for x in a],
                         [variacao.assinatura(x) for x in b])

    def test_itens_diferentes_geram_edicoes_diferentes(self):
        from importer import variacao

        a = {variacao.assinatura(x) for x in variacao.gerar("item-3", 4)}
        b = {variacao.assinatura(x) for x in variacao.gerar("item-4", 4)}
        self.assertNotEqual(a, b)

    def test_quantidade_alem_do_possivel_e_recusada(self):
        from importer import variacao

        with self.assertRaises(store.ImportError_) as erro:
            variacao.gerar("item-5", 999)
        self.assertIn("se repetem", str(erro.exception))

    def test_variacao_entra_no_plano_sem_apagar_o_resto(self):
        from importer import variacao

        v = variacao.gerar("item-6", 1)[0]
        plano = v.como_plano({"title": "Achadinho", "brand": "Loja", "cta": "Link"})
        self.assertIn("Achadinho", plano["title"])
        self.assertEqual("Loja", plano["brand"])
        self.assertEqual("Link", plano["cta"])
        self.assertIn(plano["layout"], variacao.LAYOUTS)

    def test_sufixo_por_conta_muda_o_titulo(self):
        from importer import variacao

        vs = variacao.gerar("item-7", 2, sufixos=["@conta_a", "@conta_b"])
        t1 = vs[0].como_plano({"title": "Oferta"})["title"]
        t2 = vs[1].como_plano({"title": "Oferta"})["title"]
        self.assertNotEqual(t1, t2)
