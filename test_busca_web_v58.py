"""Testes de regressão do buscador web da Máquina 1 V5.8."""
import unittest
from unittest.mock import patch

import scraper as s


class BuscarWebV58Tests(unittest.TestCase):
    @patch.object(s.time, "sleep")
    def test_lista_vazia_repete_uma_vez_e_depois_retorna_vazio(self, sleep):
        chamadas = []

        def fetch(consulta, backend, max_results):
            chamadas.append((consulta, backend, max_results))
            return []

        resultado = s.buscar_web("Nutrição turma 2026", max_results=5, fetch_fn=fetch)

        self.assertEqual(resultado, [])
        self.assertEqual(chamadas, [("Nutrição turma 2026", "auto", 5)] * 2)
        sleep.assert_called_once_with(4.0)

    @patch.object(s.time, "sleep")
    def test_lista_vazia_na_primeira_tentativa_retorna_resultado_no_retry(self, sleep):
        chamadas = []
        achado = {
            "title": "Turma de Nutrição 2026",
            "href": "https://universidade.edu.br/turma",
        }

        def fetch(consulta, backend, max_results):
            chamadas.append((consulta, backend, max_results))
            return [] if len(chamadas) == 1 else [achado]

        resultado = s.buscar_web("Nutrição turma 2026", fetch_fn=fetch)

        self.assertEqual(resultado, [achado])
        self.assertEqual(len(chamadas), 2)
        self.assertTrue(all(chamada[1] == "auto" for chamada in chamadas))
        sleep.assert_called_once_with(4.0)

    @patch.object(s.time, "sleep")
    def test_erro_transitorio_repete_e_retorna_resultado(self, sleep):
        chamadas = []
        achado = {
            "title": "Formandos",
            "href": "https://universidade.edu.br/formandos",
        }

        def fetch(consulta, backend, max_results):
            chamadas.append(consulta)
            if len(chamadas) == 1:
                raise RuntimeError("timeout temporário")
            return [achado]

        resultado = s.buscar_web("formandos Nutrição", fetch_fn=fetch)

        self.assertEqual(resultado, [achado])
        self.assertEqual(chamadas, ["formandos Nutrição"] * 2)
        sleep.assert_called_once_with(4.0)

    @patch.object(s.time, "sleep")
    def test_sem_resultados_confirmado_por_busca_de_saude_retorna_vazio(self, sleep):
        chamadas = []

        def fetch(consulta, backend, max_results):
            chamadas.append((consulta, backend, max_results))
            if consulta == "Brasil":
                return [{"title": "Resultado de saúde"}]
            raise RuntimeError("No results found")

        resultado = s.buscar_web(
            "consulta sem ocorrências",
            max_results=3,
            fetch_fn=fetch,
        )

        self.assertEqual(resultado, [])
        self.assertEqual(chamadas, [
            ("consulta sem ocorrências", "auto", 3),
            ("consulta sem ocorrências", "auto", 3),
            ("Brasil", "auto", 1),
        ])
        sleep.assert_called_once_with(4.0)

    @patch.object(s.time, "sleep")
    def test_falha_persistente_do_motor_retorna_none(self, sleep):
        chamadas = []

        def fetch(consulta, backend, max_results):
            chamadas.append((consulta, backend, max_results))
            raise RuntimeError("serviço indisponível")

        resultado = s.buscar_web("Nutrição 2026", fetch_fn=fetch)

        self.assertIsNone(resultado)
        self.assertEqual(len(chamadas), 2)
        self.assertTrue(all(chamada[1] == "auto" for chamada in chamadas))
        sleep.assert_called_once_with(4.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
