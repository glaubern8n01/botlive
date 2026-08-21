"""Producao em Massa: fila, templates, comando do FFmpeg, ZIP e dry-run.

Os testes que envolvem FFmpeg/yt-dlp verificam o COMANDO montado, nao a
execucao: assim a suite roda rapido e nao depende de rede. O render real e
exercitado no teste ponta a ponta, quando ffmpeg existe.
"""

import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MASS_DATABASE_PATH"] = str(Path(tempfile.mkdtemp()) / "massa.db")
os.environ["MASS_PROJECTS_DIR"] = str(Path(tempfile.mkdtemp()) / "projetos")

from massa import baixar, editor, exportar, fontes, postador, projetos, store, templates

store.DB_PATH = Path(os.environ["MASS_DATABASE_PATH"])


class Base(unittest.TestCase):
    def setUp(self):
        store.migrar()
        with store.conectar() as db:
            for t in ("mass_publicacoes", "mass_edicoes", "mass_downloads",
                      "mass_templates", "mass_projetos", "mass_audit"):
                db.execute(f"DELETE FROM {t}")
        os.environ["MASS_CONTENT_STUDIO_ENABLED"] = "true"
        for chave in ("MASS_PUBLISH_ENABLED", "MASS_PUBLISHER_MODE",
                      "LOCAL_PUBLISHER_DRY_RUN", "MASS_PUBLISH_INTERVALO"):
            os.environ.pop(chave, None)
        self.tmp = Path(tempfile.mkdtemp())
        self.projeto = projetos.criar(f"Lote {store.uid()[:6]}")

    def _video(self, nome="v.mp4"):
        caminho = self.tmp / nome
        caminho.write_bytes(b"conteudo-de-video")
        return caminho

    def _template(self, **campos):
        return templates.criar(f"tpl-{store.uid()[:6]}", **campos)


class FlagTests(Base):
    def test_modulo_nasce_desligado(self):
        os.environ.pop("MASS_CONTENT_STUDIO_ENABLED", None)
        self.assertFalse(store.modulo_ligado())
        with self.assertRaises(store.MassaError) as erro:
            store.exigir_modulo()
        self.assertIn("MASS_CONTENT_STUDIO_ENABLED", str(erro.exception))


class FonteTests(Base):
    def test_detecta_plataforma_por_url(self):
        self.assertEqual("instagram", fontes.detectar("https://instagram.com/reel/x").nome)
        self.assertEqual("tiktok", fontes.detectar("https://www.tiktok.com/@a/video/1").nome)
        self.assertEqual("youtube", fontes.detectar("https://youtu.be/abc").nome)
        self.assertEqual("generico", fontes.detectar("https://site.com/v.mp4").nome)

    def test_extrai_urls_de_texto_colado(self):
        texto = """olha esses:
        https://instagram.com/reel/1
        https://instagram.com/reel/2 e https://youtu.be/3
        lixo aqui"""
        urls = fontes.extrair_urls(texto)
        self.assertEqual(3, len(urls))

    def test_url_repetida_entra_uma_vez(self):
        urls = fontes.extrair_urls("https://a.com/1 https://a.com/1")
        self.assertEqual(1, len(urls))

    def test_pontuacao_no_fim_da_url_e_removida(self):
        self.assertEqual(["https://a.com/1"], fontes.extrair_urls("veja https://a.com/1."))

    def test_classificacao_conta_por_plataforma(self):
        r = fontes.classificar(["https://instagram.com/reel/1",
                                "https://instagram.com/reel/2",
                                "https://youtu.be/3"])
        self.assertEqual(3, r["total"])
        self.assertEqual(2, r["por_plataforma"]["instagram"])
        self.assertTrue(any("instagram" in a for a in r["avisos"]))

    def test_le_arquivo_txt(self):
        arquivo = self.tmp / "links.txt"
        arquivo.write_text("https://a.com/1\nhttps://a.com/2\n", encoding="utf-8")
        self.assertEqual(2, len(fontes.ler_arquivo(str(arquivo))))

    def test_arquivo_inexistente_da_erro_claro(self):
        with self.assertRaises(store.MassaError):
            fontes.ler_arquivo(str(self.tmp / "nao-existe.txt"))


class ProjetoTests(Base):
    def test_projeto_cria_as_tres_pastas(self):
        for sub in projetos.SUBPASTAS:
            self.assertTrue(Path(self.projeto["pasta"], sub).is_dir(), sub)

    def test_projeto_sem_nome_e_recusado(self):
        with self.assertRaises(store.MassaError):
            projetos.criar("   ")

    def test_historico_resume_o_lote(self):
        h = projetos.historico(self.projeto["id"])
        self.assertEqual(0, h["totais"]["baixados"])
        self.assertIn("pasta", h)


class DownloadTests(Base):
    def test_enfileira_sem_repetir(self):
        urls = ["https://a.com/1", "https://a.com/2"]
        primeiro = baixar.enfileirar(self.projeto["id"], urls)
        segundo = baixar.enfileirar(self.projeto["id"], urls)
        self.assertEqual(2, primeiro["enfileirados"])
        self.assertEqual(0, segundo["enfileirados"])
        self.assertEqual(2, segundo["repetidos"])

    def test_fila_mostra_resumo_por_status(self):
        baixar.enfileirar(self.projeto["id"], ["https://a.com/1"])
        self.assertEqual(1, baixar.fila(self.projeto["id"])["resumo"]["queued"])

    def test_cancelar_e_retentar(self):
        ids = baixar.enfileirar(self.projeto["id"], ["https://a.com/1"])["ids"]
        self.assertEqual("cancelled", baixar.mudar_status(ids[0], "cancelled")["status"])
        item = baixar.mudar_status(ids[0], "queued")
        self.assertEqual("queued", item["status"])
        self.assertEqual("", item["erro"])

    def test_status_invalido_e_recusado(self):
        ids = baixar.enfileirar(self.projeto["id"], ["https://a.com/1"])["ids"]
        with self.assertRaises(store.MassaError):
            baixar.mudar_status(ids[0], "voando")

    def test_falha_do_ytdlp_marca_item_sem_derrubar_lote(self):
        ids = baixar.enfileirar(self.projeto["id"], ["https://a.com/1", "https://a.com/2"])["ids"]

        class Falha:
            returncode = 1
            stdout = ""
            stderr = "ERROR: video indisponivel"

        with mock.patch.object(baixar.subprocess, "run", return_value=Falha()):
            resultado = baixar.rodar_fila(self.projeto["id"], 2)
        self.assertEqual(2, resultado["processados"])
        self.assertTrue(all(x["status"] == "failed" for x in resultado["itens"]))
        self.assertEqual(2, resultado["fila"]["failed"])

    def test_yt_dlp_resolvido_como_modulo_quando_falta_no_path(self):
        with mock.patch.object(baixar.shutil, "which", return_value=None):
            comando = baixar.comando_base()
        self.assertIn("-m", comando)
        self.assertIn("yt_dlp", comando)


class TemplateTests(Base):
    def test_template_tem_padroes_sensatos(self):
        t = self._template()
        self.assertEqual("9:16", t["formato"])
        self.assertEqual("blur", t["modo_horizontal"])
        self.assertEqual(1.0, t["velocidade"])

    def test_formato_invalido_e_recusado(self):
        with self.assertRaises(store.MassaError):
            self._template(formato="3:7")

    def test_velocidade_absurda_e_recusada(self):
        with self.assertRaises(store.MassaError) as erro:
            self._template(velocidade=5.0)
        self.assertIn("audio quebra", str(erro.exception))

    def test_logo_gigante_e_recusada(self):
        with self.assertRaises(store.MassaError) as erro:
            self._template(logo_escala=0.9)
        self.assertIn("cobre o video", str(erro.exception))

    def test_arquivo_de_logo_inexistente_e_recusado(self):
        with self.assertRaises(store.MassaError):
            self._template(logo_path=str(self.tmp / "nao-existe.png"))

    def test_dimensoes_por_formato(self):
        self.assertEqual((1080, 1920), templates.dimensoes(self._template(formato="9:16")))
        self.assertEqual((1080, 1080), templates.dimensoes(self._template(formato="1:1")))


class ComandoFFmpegTests(Base):
    def test_blur_usa_grafo_com_rotulos(self):
        t = self._template(modo_horizontal="blur")
        cmd = editor.montar_comando(Path("e.mp4"), Path("s.mp4"), t)
        grafo = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("split=2[bgsrc][fgsrc]", grafo)
        self.assertIn("boxblur", grafo)
        self.assertIn("[bg][fg]overlay", grafo)

    def test_crop_e_fit_produzem_filtros_diferentes(self):
        crop = editor.montar_comando(Path("e.mp4"), Path("s.mp4"),
                                     self._template(modo_horizontal="crop"))
        fit = editor.montar_comando(Path("e.mp4"), Path("s.mp4"),
                                    self._template(modo_horizontal="fit"))
        self.assertIn("crop=1080:1920", crop[crop.index("-filter_complex") + 1])
        self.assertIn("pad=1080:1920", fit[fit.index("-filter_complex") + 1])

    def test_cta_entra_como_drawtext_escapado(self):
        t = self._template(cta_texto="50% OFF: hoje")
        grafo = editor.montar_comando(Path("e.mp4"), Path("s.mp4"), t)
        grafo = grafo[grafo.index("-filter_complex") + 1]
        self.assertIn("drawtext", grafo)
        self.assertIn(r"OFF\:", grafo)

    def test_audio_removido_usa_an(self):
        cmd = editor.montar_comando(Path("e.mp4"), Path("s.mp4"),
                                    self._template(audio="remover"))
        self.assertIn("-an", cmd)

    def test_normalizar_audio_entra_no_filtro(self):
        cmd = editor.montar_comando(Path("e.mp4"), Path("s.mp4"),
                                    self._template(audio="normalizar"))
        self.assertIn("loudnorm", cmd[cmd.index("-af") + 1])

    def test_velocidade_ajusta_video_e_audio(self):
        cmd = editor.montar_comando(Path("e.mp4"), Path("s.mp4"),
                                    self._template(velocidade=1.1))
        self.assertIn("setpts", cmd[cmd.index("-filter_complex") + 1])
        self.assertIn("atempo=1.1", cmd[cmd.index("-af") + 1])

    def test_corte_de_inicio_usa_ss(self):
        cmd = editor.montar_comando(Path("e.mp4"), Path("s.mp4"),
                                    self._template(cortar_inicio=2.0))
        self.assertEqual("2.0", cmd[cmd.index("-ss") + 1])

    def test_corte_de_fim_precisa_da_duracao(self):
        t = self._template(cortar_fim=3.0)
        sem = editor.montar_comando(Path("e.mp4"), Path("s.mp4"), t, duracao=0)
        self.assertNotIn("-t", sem)
        com = editor.montar_comando(Path("e.mp4"), Path("s.mp4"), t, duracao=30)
        self.assertAlmostEqual(27.0, float(com[com.index("-t") + 1]), places=1)

    def test_corte_maior_que_o_video_e_recusado(self):
        t = self._template(cortar_inicio=5, cortar_fim=10)
        with self.assertRaises(store.MassaError) as erro:
            editor.montar_comando(Path("e.mp4"), Path("s.mp4"), t, duracao=12)
        self.assertIn("maiores que o video", str(erro.exception))

    def test_logo_e_mockup_entram_como_entradas_extras(self):
        logo = self.tmp / "logo.png"; logo.write_bytes(b"png")
        mockup = self.tmp / "mock.png"; mockup.write_bytes(b"png")
        t = self._template(logo_path=str(logo), mockup_path=str(mockup))
        cmd = editor.montar_comando(Path("e.mp4"), Path("s.mp4"), t)
        self.assertEqual(3, cmd.count("-i"))
        grafo = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("[logo]overlay", grafo)
        self.assertIn("[mock]overlay", grafo)

    def test_previa_limita_a_duracao(self):
        cmd = editor.montar_comando(Path("e.mp4"), Path("s.mp4"),
                                    self._template(), amostra_segundos=3)
        self.assertEqual("3", cmd[cmd.index("-t") + 1])


class EdicaoTests(Base):
    def test_saida_nunca_sobrescreve_o_original(self):
        entrada = self._video()
        t = self._template()
        ids = editor.enfileirar(self.projeto["id"], t["id"], [str(entrada)])["ids"]

        class Ok:
            returncode = 0
            stdout = stderr = ""

        def falso_run(cmd, **kw):
            # So o ffmpeg escreve saida; o ffprobe recebe a ENTRADA como
            # ultimo argumento e escrever nele destruiria o original.
            if "ffprobe" in str(cmd[0]):
                Ok.stdout = "36.0"
                return Ok()
            Path(cmd[-1]).write_bytes(b"editado")
            return Ok()

        with mock.patch.object(editor.subprocess, "run", side_effect=falso_run):
            resultado = editor.editar_item(ids[0])

        self.assertEqual("completed", resultado["status"])
        self.assertNotEqual(str(entrada), resultado["saida"])
        self.assertIn("editados", resultado["saida"])
        self.assertEqual(b"conteudo-de-video", entrada.read_bytes())

    def test_entrada_sumida_marca_falha(self):
        t = self._template()
        ids = editor.enfileirar(self.projeto["id"], t["id"], [str(self._video("some.mp4"))])["ids"]
        Path(self.tmp / "some.mp4").unlink()
        self.assertEqual("failed", editor.editar_item(ids[0])["status"])

    def test_ffmpeg_ausente_nao_derruba(self):
        t = self._template()
        ids = editor.enfileirar(self.projeto["id"], t["id"], [str(self._video())])["ids"]
        with mock.patch.object(editor.subprocess, "run", side_effect=FileNotFoundError()):
            resultado = editor.editar_item(ids[0])
        self.assertEqual("failed", resultado["status"])
        self.assertIn("ffmpeg", resultado["erro"])

    def test_progresso_da_fila(self):
        t = self._template()
        editor.enfileirar(self.projeto["id"], t["id"],
                          [str(self._video("a.mp4")), str(self._video("b.mp4"))])
        self.assertEqual(0.0, editor.fila(self.projeto["id"])["progresso"])


class ExportTests(Base):
    def _edicao_pronta(self, nome="pronto.mp4"):
        saida = projetos.pasta_de(self.projeto, "editados") / nome
        saida.write_bytes(b"video-editado")
        store.inserir("mass_edicoes", {
            "projeto_id": self.projeto["id"], "entrada": "x.mp4",
            "saida": str(saida), "status": "completed", "created_at": store.agora(),
        })
        return saida

    def test_zip_junta_os_editados(self):
        self._edicao_pronta("a.mp4"); self._edicao_pronta("b.mp4")
        resultado = exportar.gerar_zip(self.projeto["id"], "lote-teste")
        self.assertEqual(2, resultado["arquivos"])
        import zipfile

        with zipfile.ZipFile(resultado["zip"]) as z:
            self.assertEqual({"a.mp4", "b.mp4"}, set(z.namelist()))

    def test_zip_sem_nada_pronto_e_recusado(self):
        with self.assertRaises(store.MassaError):
            exportar.gerar_zip(self.projeto["id"])

    def test_zip_vai_para_exports_e_nao_para_editados(self):
        self._edicao_pronta()
        caminho = Path(exportar.gerar_zip(self.projeto["id"])["zip"])
        self.assertEqual("exports", caminho.parent.name)


class PostadorTests(Base):
    def _pronto(self, nome="pub.mp4"):
        arquivo = projetos.pasta_de(self.projeto, "editados") / nome
        arquivo.write_bytes(b"video")
        return arquivo

    def test_modo_padrao_e_api_e_dry_run(self):
        estado = postador.flags()
        self.assertEqual("api", estado["modo"])
        self.assertTrue(estado["dry_run"])
        self.assertFalse(estado["habilitado"])

    def test_enfileira_sem_repetir_arquivo(self):
        arquivo = self._pronto()
        primeiro = postador.enfileirar(self.projeto["id"], [str(arquivo)], "oi", ["oferta"])
        segundo = postador.enfileirar(self.projeto["id"], [str(arquivo)], "oi")
        self.assertEqual(1, primeiro["enfileirados"])
        self.assertEqual(1, segundo["repetidos"])

    def test_desligado_nao_publica(self):
        arquivo = self._pronto()
        ids = postador.enfileirar(self.projeto["id"], [str(arquivo)])["ids"]
        resultado = postador.publicar_item(ids[0])
        self.assertEqual("queued", resultado["status"])
        self.assertIn("MASS_PUBLISH_ENABLED", resultado["erro"])

    def test_dry_run_monta_tudo_e_nao_confirma(self):
        os.environ["MASS_PUBLISH_ENABLED"] = "true"
        os.environ["LOCAL_PUBLISHER_DRY_RUN"] = "true"
        arquivo = self._pronto()
        ids = postador.enfileirar(self.projeto["id"], [str(arquivo)])["ids"]
        with mock.patch.object(postador, "_publicar_api",
                               side_effect=AssertionError("nao pode publicar")):
            resultado = postador.publicar_item(ids[0])
        self.assertEqual("completed", resultado["status"])
        self.assertEqual(1, resultado["dry_run"])
        self.assertIn("NAO confirmada", resultado["erro"])

    def test_publicacao_real_usa_a_api_oficial(self):
        os.environ["MASS_PUBLISH_ENABLED"] = "true"
        os.environ["LOCAL_PUBLISHER_DRY_RUN"] = "false"
        arquivo = self._pronto()
        ids = postador.enfileirar(self.projeto["id"], [str(arquivo)], "oferta", ["promo"])["ids"]
        with mock.patch.object(postador, "_publicar_api",
                               return_value={"url": "https://instagram.com/p/1"}) as api:
            resultado = postador.publicar_item(ids[0])
        self.assertEqual("completed", resultado["status"])
        self.assertEqual(0, resultado["dry_run"])
        self.assertEqual("https://instagram.com/p/1", resultado["url_publicada"])
        self.assertTrue(api.called)

    def test_desafio_da_plataforma_pede_acao_manual(self):
        os.environ["MASS_PUBLISH_ENABLED"] = "true"
        os.environ["LOCAL_PUBLISHER_DRY_RUN"] = "false"
        arquivo = self._pronto()
        ids = postador.enfileirar(self.projeto["id"], [str(arquivo)])["ids"]
        with mock.patch.object(postador, "_publicar_api",
                               side_effect=store.MassaError("checkpoint required")):
            resultado = postador.publicar_item(ids[0])
        self.assertEqual("manual_action_required", resultado["status"])

    def test_modo_local_sem_sessao_pede_login(self):
        os.environ["MASS_PUBLISH_ENABLED"] = "true"
        os.environ["LOCAL_PUBLISHER_DRY_RUN"] = "false"
        os.environ["MASS_PUBLISHER_MODE"] = "local"
        os.environ["MASS_SESSIONS_DIR"] = str(self.tmp / "sessoes")
        arquivo = self._pronto()
        ids = postador.enfileirar(self.projeto["id"], [str(arquivo)])["ids"]
        resultado = postador.publicar_item(ids[0])
        self.assertEqual("manual_action_required", resultado["status"])
        self.assertIn("sessao", resultado["erro"].lower())

    def test_legenda_junta_descricao_e_hashtags(self):
        arquivo = self._pronto()
        ids = postador.enfileirar(self.projeto["id"], [str(arquivo)], "Confira", ["promo", "#js"])["ids"]
        item = store.obter("mass_publicacoes", ids[0])
        legenda = postador._legenda(item)
        self.assertIn("Confira", legenda)
        self.assertIn("#promo", legenda)
        self.assertIn("#js", legenda)
        self.assertNotIn("##", legenda)

    def test_intervalo_bloqueia_postagem_seguida(self):
        os.environ["MASS_PUBLISH_INTERVALO"] = "3600"
        store.inserir("mass_publicacoes", {
            "projeto_id": self.projeto["id"], "arquivo": "x.mp4", "status": "completed",
            "dry_run": 0, "publicado_em": store.agora(), "created_at": store.agora(),
        })
        permitido, motivo = postador.dentro_do_intervalo(self.projeto["id"])
        self.assertFalse(permitido)
        self.assertEqual("intervalo_minimo", motivo)

    def test_dry_run_nao_conta_para_o_intervalo(self):
        os.environ["MASS_PUBLISH_INTERVALO"] = "3600"
        store.inserir("mass_publicacoes", {
            "projeto_id": self.projeto["id"], "arquivo": "x.mp4", "status": "completed",
            "dry_run": 1, "publicado_em": store.agora(), "created_at": store.agora(),
        })
        self.assertTrue(postador.dentro_do_intervalo(self.projeto["id"])[0])


if __name__ == "__main__":
    unittest.main()


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        os.environ["MASS_ADMIN_TOKEN"] = "admin-massa"
        from fastapi.testclient import TestClient
        from massa.main import app

        self.client = TestClient(app)
        self.admin = {"X-Mass-Token": "admin-massa"}

    def test_modulo_desligado_esconde_rotas(self):
        os.environ["MASS_CONTENT_STUDIO_ENABLED"] = "false"
        try:
            self.assertEqual(404, self.client.get("/mass/v1/projetos",
                                                  headers=self.admin).status_code)
        finally:
            os.environ["MASS_CONTENT_STUDIO_ENABLED"] = "true"

    def test_sem_token_nao_le(self):
        self.assertEqual(401, self.client.get("/mass/v1/projetos").status_code)

    def test_health_declara_processamento_local(self):
        dados = self.client.get("/mass/v1/health").json()
        self.assertIn("local", dados["processamento"])
        self.assertEqual("api", dados["postador"]["modo"])
        self.assertTrue(dados["postador"]["dry_run"])

    def test_detectar_links_conta_e_classifica(self):
        r = self.client.post("/mass/v1/links/detectar", headers=self.admin, json={
            "texto": "https://instagram.com/reel/1 https://youtu.be/2"})
        self.assertEqual(2, r.json()["total"])
        self.assertEqual(1, r.json()["por_plataforma"]["instagram"])

    def test_ajuda_traz_os_tutoriais(self):
        topicos = self.client.get("/mass/v1/ajuda", headers=self.admin).json()["topicos"]
        titulos = [t["titulo"] for t in topicos]
        self.assertIn("Como baixar em massa", titulos)
        self.assertIn("Como criar template", titulos)

    def test_fluxo_projeto_template_e_fila(self):
        proj = self.client.post("/mass/v1/projetos", headers=self.admin,
                                json={"nome": "Projeto API"})
        self.assertEqual(201, proj.status_code)
        pid = proj.json()["id"]

        tpl = self.client.post("/mass/v1/templates", headers=self.admin,
                               json={"nome": f"tpl-api-{store.uid()[:6]}",
                                     "cta_texto": "COMPRE AGORA"})
        self.assertEqual(201, tpl.status_code)

        fila = self.client.post(f"/mass/v1/projetos/{pid}/downloads", headers=self.admin,
                                json={"urls": ["https://a.com/1", "https://a.com/2"]})
        self.assertEqual(2, fila.json()["enfileirados"])

        hist = self.client.get(f"/mass/v1/projetos/{pid}/historico", headers=self.admin).json()
        self.assertEqual(2, hist["downloads"]["queued"])

    def test_template_invalido_volta_422(self):
        r = self.client.post("/mass/v1/templates", headers=self.admin,
                             json={"nome": "ruim", "formato": "3:7"})
        self.assertEqual(422, r.status_code)

    def test_sessao_nao_vaza_conteudo(self):
        os.environ["MASS_SESSIONS_DIR"] = str(self.tmp / "sess")
        dados = self.client.get("/mass/v1/sessao/principal", headers=self.admin).json()
        self.assertEqual({"conta", "salva"}, set(dados))
