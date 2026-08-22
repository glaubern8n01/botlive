"""Testes do guarda de nicho, com as transcricoes REAIS do incidente.

Os dois primeiros textos sao copias literais do que o Whisper transcreveu dos
cortes do bahiaqz que levaram bloqueio por Content ID em 21/08/2026.
"""

import unittest

from nicho_guard import avaliar_transcricao


# Corte "DEMITE O TECNICO!" — jogo/transmissao de futebol na live de GTA.
FUTEBOL_REAL = (
    "Boa! Boa! E! Ataque e manco do caralho! Mano, em bizarro que de EBR, a gente "
    "nao errava nada, agora ele erra tudo! Aqui... vai! No EVA, comecou o campeonato, "
    "esta jogando de muleta! Que bolao! Que bolao! Demite o tecnico! Demite ele!"
)

# Corte "CARA QUASE FALOU NA LIVE" (@dantas) — jogo de construcao. Falso-positivo
# real da primeira versao, que acusava por "estadio" + "placar".
CONSTRUCAO_REAL = (
    "Mas o reboto fica do lado do placar, entendeu? Espera ai, eu estou construindo "
    "um estadio aqui. Tem 2900 ai, o. O reboto esta construindo. Ai, pera ai, cara. "
    "O cara esta me refutando."
)

GTA_REAL = (
    "A policia chegou na hora do assalto, o cara sacou a arma e o mecanico "
    "levou o carro pra oficina. Fui preso e o advogado me tirou da cadeia."
)


class ForaDoNichoTest(unittest.TestCase):
    def test_transmissao_de_futebol_vai_para_revisao(self):
        r = avaliar_transcricao(FUTEBOL_REAL)
        self.assertEqual(r.veredito, "fora_do_nicho")
        self.assertTrue(r.precisa_revisao)
        self.assertIn("tecnico", r.marcadores_fora)
        self.assertIn("campeonato", r.marcadores_fora)

    def test_reality_show_vai_para_revisao(self):
        r = avaliar_transcricao("O paredao de hoje elimina um participante do confinamento")
        self.assertEqual(r.veredito, "fora_do_nicho")

    def test_gameplay_de_gta_passa(self):
        r = avaliar_transcricao(GTA_REAL)
        self.assertEqual(r.veredito, "ok")
        self.assertFalse(r.precisa_revisao)


class FalsoPositivoTest(unittest.TestCase):
    def test_estadio_em_jogo_de_construcao_nao_acusa(self):
        """'estadio' e 'placar' sozinhos sao ambiguos: aparecem em jogo de
        construcao. Sem marcador FORTE, o guarda nao levanta a mao."""
        r = avaliar_transcricao(CONSTRUCAO_REAL)
        self.assertEqual(r.veredito, "ok")

    def test_uma_palavra_forte_sozinha_nao_basta(self):
        """Um marcador so nao acusa: 'campeonato' aparece em conversa de RP."""
        r = avaliar_transcricao("mano, o campeonato ta doido esse ano")
        self.assertEqual(r.veredito, "ok")

    def test_forte_mais_ambiguo_ja_acusa(self):
        """No piso de 2 marcadores com um forte, o guarda levanta a mao."""
        r = avaliar_transcricao("o juiz do campeonato mandou parar")
        self.assertEqual(r.veredito, "fora_do_nicho")

    def test_termo_do_nicho_vence_o_sinal_de_fora(self):
        """Streamer de RP comentando futebol dentro do jogo continua sendo RP."""
        r = avaliar_transcricao(
            "o tecnico do campeonato ta doido, mas a policia chegou e me prendeu no assalto"
        )
        self.assertEqual(r.veredito, "ok")
        self.assertIn("policia", r.marcadores_nicho)

    def test_fronteira_de_palavra(self):
        """'gol' dentro de 'golpe' e 'var' dentro de 'varanda' nao contam."""
        r = avaliar_transcricao("levei um golpe na varanda e caiu o titulo do documento")
        self.assertEqual(r.veredito, "ok")


class BordasTest(unittest.TestCase):
    def test_transcricao_vazia_e_sem_sinal(self):
        self.assertEqual(avaliar_transcricao("").veredito, "sem_sinal")
        self.assertEqual(avaliar_transcricao("   ").veredito, "sem_sinal")

    def test_acento_nao_muda_o_resultado(self):
        com = avaliar_transcricao("o técnico do campeonato e o bolão")
        sem = avaliar_transcricao("o tecnico do campeonato e o bolao")
        self.assertEqual(com.veredito, sem.veredito)
        self.assertEqual(com.veredito, "fora_do_nicho")

    def test_nicho_sem_lexico_nao_opina(self):
        r = avaliar_transcricao(FUTEBOL_REAL, nicho="futebol")
        self.assertEqual(r.veredito, "ok")

    def test_exigir_sinal_do_nicho_pega_narracao_generica(self):
        """A fala do Rio Shore nao tem palavra de futebol nem de RP. So a regra
        estrita pega — e ela manda 78% dos cortes para revisao, por isso e
        opcional e fica desligada por padrao."""
        generica = "Impossivel. Impossivel. Nao vai acontecer isso. Eu achei que ela ia dar isso."
        self.assertEqual(avaliar_transcricao(generica).veredito, "ok")
        self.assertEqual(
            avaliar_transcricao(generica, exigir_sinal_do_nicho=True).veredito, "sem_sinal"
        )


if __name__ == "__main__":
    unittest.main()
