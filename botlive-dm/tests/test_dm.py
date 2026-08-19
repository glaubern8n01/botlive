"""Respondedor de comentarios: casamento de regra, travas e idempotencia.

Nenhum teste toca a rede: o envio real e substituido por mock. O que se prova
aqui e o comportamento das travas, que e o que impede conta derrubada e
mensagem duplicada.
"""

import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DM_DATABASE_PATH"] = str(Path(tempfile.mkdtemp()) / "dm.db")

from dm import enviar, regras, store

store.DB_PATH = Path(os.environ["DM_DATABASE_PATH"])

CONTA = "principal"


class Base(unittest.TestCase):
    def setUp(self):
        store.migrar()
        with store.conectar() as db:
            for t in ("dm_respostas", "dm_comentarios", "dm_regras", "dm_audit"):
                db.execute(f"DELETE FROM {t}")
        for chave in ("DM_ENABLED", "DM_DRY_RUN", "DM_MAX_POR_HORA", "DM_MAX_POR_DIA"):
            os.environ.pop(chave, None)

    def _regra(self, palavras=("preco", "link"), **extra):
        r = regras.criar(CONTA, extra.pop("nome", "afiliado"), list(palavras),
                         extra.pop("resposta", "Oi! Segue o link do produto:"),
                         link=extra.pop("link", "https://loja.invalido/p/1"), **extra)
        regras.ativar(r["id"])
        return r

    def _comentario(self, texto, comment_id="c1", media_id=""):
        return {"comment_id": comment_id, "conta": CONTA, "texto": texto,
                "media_id": media_id, "autor": "@fulano"}


class RegraTests(Base):
    def test_regra_nasce_desligada(self):
        r = regras.criar(CONTA, "teste", ["preco"], "resposta")
        self.assertEqual(0, r["ativa"])

    def test_regra_sem_palavra_e_recusada(self):
        with self.assertRaises(store.DmError):
            regras.criar(CONTA, "vazia", [], "resposta")

    def test_link_invalido_e_recusado(self):
        with self.assertRaises(store.DmError):
            regras.criar(CONTA, "x", ["preco"], "resposta", link="loja.com")

    def test_casa_ignorando_acento_e_caixa(self):
        self._regra(palavras=["preco"])
        self.assertIsNotNone(regras.casar("Quanto é o PREÇO?", CONTA))

    def test_nao_casa_palavra_dentro_de_outra(self):
        """'link' nao pode disparar em 'linkin park'."""
        self._regra(palavras=["link"])
        self.assertIsNone(regras.casar("curto linkin park", CONTA))
        self.assertIsNotNone(regras.casar("manda o link", CONTA))

    def test_regra_desligada_nao_casa(self):
        r = regras.criar(CONTA, "off", ["preco"], "resposta")
        self.assertIsNone(regras.casar("preco?", CONTA))
        regras.ativar(r["id"])
        self.assertIsNotNone(regras.casar("preco?", CONTA))

    def test_regra_presa_a_um_post_nao_vale_em_outro(self):
        self._regra(palavras=["quero"], nome="post-especifico", media_id="media-A")
        self.assertIsNotNone(regras.casar("quero", CONTA, "media-A"))
        self.assertIsNone(regras.casar("quero", CONTA, "media-B"))

    def test_prioridade_decide_quando_duas_casam(self):
        self._regra(palavras=["quero"], nome="generica", prioridade=200)
        especifica = self._regra(palavras=["quero"], nome="especifica", prioridade=10)
        self.assertEqual(especifica["id"], regras.casar("quero", CONTA)["id"])

    def test_link_entra_na_resposta_uma_vez_so(self):
        r = self._regra(link="https://loja.invalido/p/1")
        texto = regras.montar_resposta(r)
        self.assertEqual(1, texto.count("https://loja.invalido/p/1"))


class EnvioTests(Base):
    def test_flags_nascem_seguras(self):
        f = enviar.flags()
        self.assertFalse(f["enabled"])
        self.assertTrue(f["dry_run"])

    def test_comentario_sem_regra_nao_manda_nada(self):
        self._regra(palavras=["preco"])
        r = enviar.responder(self._comentario("que video legal"))
        self.assertEqual("sem_regra", r["status"])

    def test_modulo_desligado_mostra_o_que_mandaria(self):
        self._regra()
        r = enviar.responder(self._comentario("qual o preco?"))
        self.assertEqual("modulo_desligado", r["status"])
        self.assertIn("loja.invalido", r["texto_previsto"])

    def test_dry_run_nao_chama_a_api(self):
        os.environ["DM_ENABLED"] = "true"
        os.environ["DM_DRY_RUN"] = "true"
        self._regra()
        with mock.patch.object(enviar, "_post", side_effect=AssertionError("nao pode enviar")):
            r = enviar.responder(self._comentario("manda o link"))
        self.assertEqual("simulado", r["status"])

    def test_envio_real_usa_private_reply_com_o_comment_id(self):
        os.environ["DM_ENABLED"] = "true"
        os.environ["DM_DRY_RUN"] = "false"
        self._regra()
        chamadas = []

        def falso(ig_user_id, token, comment_id, texto):
            chamadas.append({"comment_id": comment_id, "texto": texto})
            return {"message_id": "m-1"}

        with mock.patch.object(enviar, "_credenciais",
                               return_value={"ig_user_id": "17841", "access_token": "t"}), \
             mock.patch.object(enviar, "_post", side_effect=falso):
            r = enviar.responder(self._comentario("qual o preco?", comment_id="c-real"))

        self.assertEqual("enviado", r["status"])
        self.assertEqual("c-real", chamadas[0]["comment_id"])
        self.assertIn("loja.invalido", chamadas[0]["texto"])

    def test_mesmo_comentario_nunca_recebe_duas_mensagens(self):
        os.environ["DM_ENABLED"] = "true"
        os.environ["DM_DRY_RUN"] = "false"
        self._regra()
        with mock.patch.object(enviar, "_credenciais",
                               return_value={"ig_user_id": "17841", "access_token": "t"}), \
             mock.patch.object(enviar, "_post", return_value={"message_id": "m-1"}) as post:
            enviar.responder(self._comentario("preco", comment_id="dup"))
            segundo = enviar.responder(self._comentario("preco", comment_id="dup"))
        self.assertEqual("ja_respondido", segundo["status"])
        self.assertEqual(1, post.call_count)

    def test_teto_por_hora_interrompe(self):
        os.environ["DM_ENABLED"] = "true"
        os.environ["DM_DRY_RUN"] = "false"
        os.environ["DM_MAX_POR_HORA"] = "1"
        self._regra()
        with mock.patch.object(enviar, "_credenciais",
                               return_value={"ig_user_id": "17841", "access_token": "t"}), \
             mock.patch.object(enviar, "_post", return_value={"message_id": "m"}):
            enviar.responder(self._comentario("preco", comment_id="t1"))
            segundo = enviar.responder(self._comentario("preco", comment_id="t2"))
        self.assertEqual("teto_atingido", segundo["status"])
        self.assertEqual("teto_por_hora", segundo["motivo"])

    def test_simulado_nao_gasta_o_teto(self):
        os.environ["DM_ENABLED"] = "true"
        os.environ["DM_DRY_RUN"] = "true"
        os.environ["DM_MAX_POR_HORA"] = "1"
        self._regra()
        enviar.responder(self._comentario("preco", comment_id="s1"))
        self.assertTrue(enviar.dentro_do_teto(CONTA)[0])

    def test_falha_da_api_fica_registrada(self):
        os.environ["DM_ENABLED"] = "true"
        os.environ["DM_DRY_RUN"] = "false"
        self._regra()
        with mock.patch.object(enviar, "_credenciais",
                               return_value={"ig_user_id": "17841", "access_token": "t"}), \
             mock.patch.object(enviar, "_post", side_effect=store.DmError("HTTP 400")):
            with self.assertRaises(store.DmError):
                enviar.responder(self._comentario("preco", comment_id="f1"))
        registro = enviar.ja_respondido("f1")
        self.assertEqual("falha", registro["status"])

    def test_conta_sem_token_da_erro_com_instrucao(self):
        os.environ["DM_ENABLED"] = "true"
        os.environ["DM_DRY_RUN"] = "false"
        self._regra()
        with self.assertRaises(store.DmError) as erro:
            enviar.responder(self._comentario("preco", comment_id="sem-token"))
        self.assertIn("autorizar", str(erro.exception))

    def test_comentario_repetido_nao_duplica_registro(self):
        a = enviar.registrar_comentario("c9", CONTA, "preco")
        b = enviar.registrar_comentario("c9", CONTA, "preco")
        self.assertEqual(a["id"], b["id"])


if __name__ == "__main__":
    unittest.main()


class ApiTests(Base):
    """Superficie HTTP: gestao por token, webhook por assinatura HMAC."""

    def setUp(self):
        super().setUp()
        os.environ["DM_ADMIN_TOKEN"] = "admin-dm"
        os.environ["DM_APP_SECRET"] = "segredo-do-app"
        os.environ["DM_WEBHOOK_VERIFY_TOKEN"] = "verifica-me"
        from fastapi.testclient import TestClient
        from dm.main import app

        self.client = TestClient(app)
        self.admin = {"X-Dm-Token": "admin-dm"}

    def _assinar(self, corpo: bytes) -> str:
        import hashlib, hmac as h

        return "sha256=" + h.new(b"segredo-do-app", corpo, hashlib.sha256).hexdigest()

    def test_sem_token_nao_le_regras(self):
        self.assertEqual(401, self.client.get("/dm/v1/regras").status_code)

    def test_health_diz_a_mecanica(self):
        dados = self.client.get("/dm/v1/health").json()
        self.assertIn("Private Reply", dados["mecanica"])
        self.assertTrue(dados["uma_resposta_por_comentario"])

    def test_testar_mostra_resposta_sem_enviar(self):
        self._regra()
        r = self.client.post("/dm/v1/testar", headers=self.admin,
                             json={"conta": CONTA, "texto": "qual o preco?"})
        self.assertTrue(r.json()["casou"])
        self.assertIn("loja.invalido", r.json()["resposta"])

    def test_webhook_recusa_assinatura_errada(self):
        r = self.client.post("/dm/v1/webhook", content=b"{}",
                             headers={"X-Hub-Signature-256": "sha256=errado"})
        self.assertEqual(403, r.status_code)

    def test_webhook_sem_assinatura_e_recusado(self):
        self.assertEqual(403, self.client.post("/dm/v1/webhook", content=b"{}").status_code)

    def test_verificacao_do_webhook_devolve_challenge(self):
        r = self.client.get("/dm/v1/webhook", params={
            "hub.mode": "subscribe", "hub.challenge": "12345",
            "hub.verify_token": "verifica-me"})
        self.assertEqual("12345", r.text)

    def test_verificacao_com_token_errado_e_recusada(self):
        r = self.client.get("/dm/v1/webhook", params={
            "hub.mode": "subscribe", "hub.challenge": "1", "hub.verify_token": "x"})
        self.assertEqual(403, r.status_code)

    def test_webhook_processa_comentario_e_nao_repete(self):
        import json as j

        self._regra()
        os.environ["DM_ENABLED"] = "true"
        os.environ["DM_DRY_RUN"] = "true"
        os.environ["DM_CONTA_PADRAO"] = CONTA
        corpo = j.dumps({"entry": [{"id": "17841", "changes": [
            {"field": "comments", "value": {"id": "wh-1", "text": "qual o preco?",
                                            "from": {"username": "fulano"},
                                            "media": {"id": "m-1"}}}]}]}).encode()
        cab = {"X-Hub-Signature-256": self._assinar(corpo)}
        primeiro = self.client.post("/dm/v1/webhook", content=corpo, headers=cab).json()
        segundo = self.client.post("/dm/v1/webhook", content=corpo, headers=cab).json()
        self.assertEqual("simulado", primeiro["processados"][0]["status"])
        self.assertEqual("ja_respondido", segundo["processados"][0]["status"])
