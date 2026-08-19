"""Fase 6: catalogo nao auditado, matriz, perfis e prioridade de provider."""

import os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MEDIA_AUDIT_PATH"] = str(Path(tempfile.mkdtemp()) / "auditorias.json")

from mediastack import catalog, matrix, profiles, providers
from mediastack.providers import Provider, ProviderError


def limpar_auditorias():
    caminho = Path(os.environ["MEDIA_AUDIT_PATH"])
    if caminho.exists():
        caminho.unlink()


class CatalogoTests(unittest.TestCase):
    def setUp(self):
        limpar_auditorias()

    def test_catalogo_tem_as_quinze_ferramentas(self):
        self.assertEqual(15, len(catalog.FERRAMENTAS))

    def test_nada_nasce_auditado(self):
        self.assertTrue(all(x.auditoria == "NAO AUDITADO" for x in catalog.todas()))
        self.assertTrue(all(not x.usavel_em_producao for x in catalog.todas()))

    def test_dado_nao_medido_e_none_e_nao_zero(self):
        wan = catalog.obter("wan2gp")
        self.assertIsNone(wan.vram_gb)
        self.assertIsNone(wan.licenca)
        self.assertIsNone(wan.headless)

    def test_wangp_tem_prioridade_declarada_muito_alta(self):
        self.assertEqual("muito-alta", catalog.obter("wan2gp").prioridade_declarada)

    def test_auditoria_concluida_exige_licenca_e_commit(self):
        with self.assertRaises(ValueError):
            catalog.registrar_auditoria("wan2gp", auditoria="AUDITADO")
        with self.assertRaises(ValueError):
            catalog.registrar_auditoria("wan2gp", auditoria="AUDITADO", licenca="MIT")

    def test_nivel_invalido_e_recusado(self):
        with self.assertRaises(ValueError):
            catalog.registrar_auditoria("wan2gp", auditoria="TALVEZ")

    def test_ferramenta_desconhecida_e_recusada(self):
        with self.assertRaises(KeyError):
            catalog.registrar_auditoria("inventada", auditoria="PARCIAL")

    def test_auditoria_registrada_aparece_no_catalogo(self):
        catalog.registrar_auditoria(
            "wan2gp", auditoria="AUDITADO", licenca="Apache-2.0",
            commit_auditado="abc1234", vram_gb=6.0, ram_gb=16.0, headless=True,
        )
        wan = catalog.obter("wan2gp")
        self.assertEqual("AUDITADO", wan.auditoria)
        self.assertTrue(wan.usavel_em_producao)
        self.assertEqual(6.0, wan.vram_gb)

    def test_capacidade_desconhecida_e_recusada(self):
        with self.assertRaises(ValueError):
            catalog.por_capacidade("teletransporte")


class MatrizTests(unittest.TestCase):
    def setUp(self):
        limpar_auditorias()

    def test_matriz_marca_o_que_ninguem_mediu(self):
        linha = next(x for x in matrix.matriz() if x["id"] == "openshorts")
        self.assertEqual("não medido", linha["licenca"])
        self.assertEqual("não medido", linha["vram_gb"])
        self.assertIn("licenca", linha["pendencias"])

    def test_matriz_com_perfil_nao_da_veredito_sem_medida(self):
        linha = next(x for x in matrix.matriz(profiles.LOW_RESOURCE) if x["id"] == "wan2gp")
        self.assertEqual("não medido", linha["cabe_no_perfil"])

    def test_proposta_cobre_tudo_mas_nao_esta_pronta(self):
        resultado = matrix.menor_conjunto()
        self.assertEqual([], resultado["sem_cobertura"])
        self.assertFalse(resultado["pronta_para_producao"])
        self.assertTrue(resultado["nao_auditadas"])
        self.assertIn("licenca", resultado["campos_pendentes"])

    def test_proposta_e_menor_que_o_catalogo(self):
        resultado = matrix.menor_conjunto()
        self.assertLess(len(resultado["ferramentas"]), len(catalog.FERRAMENTAS))

    def test_proposta_prefere_wangp(self):
        proposta = matrix.menor_conjunto()
        self.assertIn("wan2gp", proposta["ferramentas"])
        self.assertEqual("wan2gp", proposta["ferramentas"][0])
        for capacidade in ("imagem", "video", "tts"):
            self.assertEqual("wan2gp", proposta["cobertura"][capacidade])

    def test_prioridade_declarada_vence_cobertura_bruta(self):
        # moneyprinterturbo cobre 4 capacidades, mas e prioridade media e o
        # documento manda compara-la antes de adotar: nao pode liderar.
        proposta = matrix.menor_conjunto()
        self.assertNotIn("moneyprinterturbo", proposta["ferramentas"])

    def test_somente_auditadas_nao_inventa_stack(self):
        resultado = matrix.menor_conjunto(somente_auditadas=True)
        self.assertEqual([], resultado["ferramentas"])
        self.assertEqual(len(matrix.COBERTURA_MINIMA), len(resultado["sem_cobertura"]))
        self.assertFalse(resultado["pronta_para_producao"])

    def test_ferramenta_descartada_sai_da_proposta(self):
        catalog.registrar_auditoria("moneyprinterturbo", auditoria="DESCARTADO")
        self.assertNotIn("moneyprinterturbo", matrix.menor_conjunto()["ferramentas"])

    def test_resumo_aponta_capacidades_sem_ferramenta_auditada(self):
        resumo = matrix.resumo_auditoria()
        self.assertEqual(15, resumo["total"])
        self.assertEqual([], resumo["prontas_para_producao"])
        self.assertIn("video", resumo["capacidades_sem_ferramenta_auditada"])


class PerfilTests(unittest.TestCase):
    def test_perfis_crescem_em_orcamento(self):
        self.assertLess(profiles.LOW_RESOURCE.vram_gb, profiles.BALANCED.vram_gb)
        self.assertLess(profiles.BALANCED.vram_gb, profiles.QUALITY.vram_gb)

    def test_perfil_padrao_e_o_mais_conservador(self):
        os.environ.pop("MEDIA_PROFILE", None)
        self.assertEqual("LOW_RESOURCE", profiles.obter().nome)

    def test_perfil_desconhecido_e_recusado(self):
        with self.assertRaises(ValueError):
            profiles.obter("MAQUINA_DO_VIZINHO")

    def test_sem_medida_nao_ha_veredito_de_hardware(self):
        self.assertIsNone(profiles.cabe_no_hardware(profiles.LOW_RESOURCE, None, 8))


class ProviderTests(unittest.TestCase):
    def setUp(self):
        providers.limpar()
        self.local = providers.registrar(Provider("wangp-local", "video", "local", vram_gb=6, ram_gb=16))
        self.gratuito = providers.registrar(Provider("ffmpeg", "video", "gratuito", ram_gb=4))
        self.free = providers.registrar(Provider("algum-free-tier", "video", "free_tier", ram_gb=2))
        self.pago = providers.registrar(Provider("api-paga", "video", "pago", custo_por_uso=0.12, ram_gb=2))

    def test_ordem_de_prioridade_do_projeto(self):
        fila = [x.id for x in providers.candidatos("video")]
        self.assertEqual(["wangp-local", "ffmpeg", "algum-free-tier"], fila)

    def test_pago_nao_entra_sem_autorizacao(self):
        self.assertFalse(self.pago.utilizavel)
        self.assertNotIn("api-paga", [x.id for x in providers.candidatos("video")])

    def test_autorizacao_de_pago_exige_confirmacao_literal(self):
        with self.assertRaises(ProviderError):
            providers.autorizar_pago("api-paga", "sim")
        providers.autorizar_pago("api-paga", "autorizo custo")
        self.assertTrue(self.pago.utilizavel)

    def test_pago_autorizado_ainda_fica_por_ultimo(self):
        providers.autorizar_pago("api-paga", "autorizo custo")
        self.assertEqual("wangp-local", providers.escolher("video").id)
        self.assertEqual("api-paga", providers.candidatos("video")[-1].id)

    def test_pago_indisponivel_nao_derruba_o_gratuito(self):
        providers.autorizar_pago("api-paga", "autorizo custo")
        self.pago.disponivel = False
        self.assertEqual("wangp-local", providers.escolher("video").id)

    def test_queda_do_local_cai_para_o_proximo(self):
        self.local.disponivel = False
        self.assertEqual("ffmpeg", providers.escolher("video").id)

    def test_provider_pago_sem_custo_declarado_e_recusado(self):
        with self.assertRaises(ProviderError):
            Provider("pago-sem-preco", "video", "pago")

    def test_provider_gratuito_com_custo_e_recusado(self):
        with self.assertRaises(ProviderError):
            Provider("gratuito-caro", "video", "gratuito", custo_por_uso=1.0)

    def test_perfil_filtra_provider_pesado(self):
        escolhido = providers.escolher("video", profiles.LOW_RESOURCE)
        self.assertEqual("wangp-local", escolhido.id)
        magro = profiles.Perfil("MAGRO", 2.0, 8.0, "teste")
        self.assertEqual("ffmpeg", providers.escolher("video", magro).id)

    def test_capacidade_sem_provider_e_reportada_e_nao_estoura(self):
        plano = providers.plano(["video", "tts"])
        self.assertEqual("wangp-local", plano["escolhidos"]["video"])
        self.assertIn("tts", plano["sem_cobertura"])
        self.assertEqual([], plano["usa_pago"])
        self.assertEqual(0, plano["custo_estimado"])

    def test_plano_avisa_quando_depende_de_pago(self):
        providers.limpar()
        providers.registrar(Provider("so-paga", "tts", "pago", custo_por_uso=0.5))
        providers.autorizar_pago("so-paga", "autorizo custo")
        plano = providers.plano(["tts"])
        self.assertEqual(["tts"], plano["usa_pago"])
        self.assertEqual(0.5, plano["custo_estimado"])

    def test_revogar_pago_devolve_o_bloqueio(self):
        providers.autorizar_pago("api-paga", "autorizo custo")
        providers.revogar_pago("api-paga")
        self.assertFalse(self.pago.utilizavel)


if __name__ == "__main__":
    unittest.main()
