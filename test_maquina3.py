import unittest
from unittest.mock import patch

import maquina3 as m


class FakeRepo:
    def __init__(self):
        self.saved_checkpoints = []

    def controle_salvar(self, etapa, dados):
        self.saved_checkpoints.append((etapa, dict(dados)))


class Machine3Tests(unittest.TestCase):
    def test_queries_cover_target_years_and_course(self):
        item = {"id": 3, "instituicao": "Universidade Teste", "estado": "SP"}
        queries = m.consultas_lote(item)
        self.assertEqual(len(queries), 4)
        self.assertTrue(all("Nutrição" in q for q in queries))
        self.assertTrue(any("2025" in q for q in queries))
        self.assertTrue(any("2026" in q for q in queries))

    def test_selects_maximum_five_and_one_state(self):
        items = [
            {"id": i, "estado": "SP", "instituicao": f"Faculdade {i}"}
            for i in range(1, 8)
        ] + [{"id": 20, "estado": "RJ", "instituicao": "Outra UF"}]
        lote = m.selecionar_lote(items)
        self.assertEqual(len(lote), 5)
        self.assertEqual({x["estado"] for x in lote}, {"SP"})

    def test_skips_instagram_and_caps_source_pages(self):
        repo = FakeRepo()
        item = {"id": 8, "estado": "SP", "instituicao": "Universidade Teste"}
        resultados = [
            {"href": "https://univ.edu.br/lista"},
            {"href": "https://univ.edu.br/lista"},
            {"href": "https://instagram.com/p/abc"},
            {"href": "https://univ.edu.br/formandos"},
            {"href": "https://univ.edu.br/tcc"},
        ]
        with patch.object(m, "buscar_web", return_value=resultados) as search, \
             patch.object(m, "carregar_fonte", return_value=([], [])) as fetch, \
             patch.object(m, "salvar_lead") as save:
            self.assertTrue(m.processar_faculdade(repo, item))
        self.assertEqual(search.call_count, 4)
        self.assertEqual(fetch.call_count, 8)
        save.assert_not_called()
        self.assertEqual(repo.saved_checkpoints[-1][1]["status"], "concluido")


if __name__ == "__main__":
    unittest.main()
