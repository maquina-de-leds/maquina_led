import unittest
from unittest.mock import patch

import scraper
import fontes_academicas


class MachineOneSearchEfficiencyTests(unittest.TestCase):
    def setUp(self):
        scraper.RENDIMENTO_BUSCAS.clear()
        scraper.ORDEM_CONSULTAS_POR_INSTITUICAO.clear()

    def test_queries_are_bounded_and_cover_both_years_and_academic_signals(self):
        queries = scraper.consultas_leads(
            "Universidade Teste", "UT", cidade="Itu", uf="SP"
        )
        self.assertLessEqual(len(queries), 42)
        self.assertGreater(len(queries), 20)
        self.assertEqual(len(queries), len(set(queries)))
        for year in ("2025", "2026"):
            self.assertTrue(any(year in q for q in queries))
        for signal in (
            '"lista de alunos"', "aprovados", '"formandos"', '"TCC"', "defesa",
            "apresentação", "repositório",
            '"colação de grau"', '"recém-formados"', '"último período"',
            '"estágio final"', '"mostra" "autores"', '"turma"',
            'site:instagram.com/p/', '"grupo de WhatsApp"',
            '"Itu" SP', "site:linkedin.com/in",
        ):
            self.assertTrue(any(signal in q for q in queries), signal)
        self.assertTrue(any("site:instagram.com" in q.lower() for q in queries))
        self.assertTrue(all('"Universidade Teste"' in q and "Nutrição" in q for q in queries))

    def test_queries_prioritize_families_with_better_qualified_yield(self):
        scraper.RENDIMENTO_BUSCAS.clear()
        scraper.ORDEM_CONSULTAS_POR_INSTITUICAO.clear()
        scraper.RENDIMENTO_BUSCAS.update({
            "instagram_publico": {"consultas": 2, "nomes": 8},
            "formatura_colacao": {"consultas": 10, "nomes": 0},
        })
        queries = scraper.consultas_leads("Universidade Teste", "UT")
        self.assertEqual(scraper.familia_consulta(queries[0]), "instagram_publico")
        self.assertTrue(all('"Universidade Teste"' in q and "Nutrição" in q for q in queries))
        scraper.RENDIMENTO_BUSCAS.clear()

    def test_institution_brand_is_not_a_person_name(self):
        for entity in ("EAD UniCesumar", "Anhanguera Educacional", "Grupo Anhanguera", "Kroton Educacional"):
            with self.subTest(entity=entity):
                self.assertIsNone(fontes_academicas.pessoa(entity))
        self.assertTrue(fontes_academicas.pessoa("Ana Souza"))

    def test_institution_acronym_and_city_are_not_a_person_name(self):
        result = {
            "title": "Fib Bauru • Instagram",
            "body": "Estudante de Nutrição, formanda 2026 das Faculdades Integradas de Bauru",
            "href": "https://www.instagram.com/fibbauru/",
        }
        self.assertEqual(
            fontes_academicas.extrair_resultado_busca(
                result, "Faculdades Integradas de Bauru"
            ),
            [],
        )
        self.assertEqual(
            fontes_academicas.extrair_resultado_busca(
                {**result, "title": "Ana Souza • Instagram"},
                "Faculdades Integradas de Bauru",
            )[0]["nome"],
            "Ana Souza",
        )

    def test_public_instagram_result_keeps_handle_only_with_qualification_evidence(self):
        result = {
            "title": "Joana da Silva (@joana.nutri) • Instagram",
            "body": "Estudante de Nutrição, formanda 2026 da Universidade Teste",
            "href": "https://www.instagram.com/joana.nutri/",
        }
        extracted = fontes_academicas.extrair_resultado_busca(
            result, "Universidade Teste", "UT"
        )
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0]["nome"], "Joana da Silva")
        self.assertEqual(extracted[0]["instagram"], "@joana.nutri")

    def test_admission_approval_alone_does_not_qualify_as_student(self):
        result = {
            "title": "Joana da Silva aprovada em Nutrição 2026",
            "body": "Lista de aprovados no vestibular da Universidade Teste",
            "href": "https://universidade.example/aprovados",
        }
        self.assertEqual(
            fontes_academicas.extrair_resultado_busca(result, "Universidade Teste"), []
        )

    @patch.object(scraper.time, "sleep")
    def test_google_is_first_and_bing_is_fallback(self, _sleep):
        calls = []

        def fetch(query, backend, max_results):
            calls.append(backend)
            if backend == "bing":
                return [{"title": "resultado", "href": "https://example.org"}]
            return []

        results = scraper.buscar_web("Nutrição 2026", fetch_fn=fetch)
        self.assertEqual(calls, ["google", "google", "bing"])
        self.assertEqual(len(results), 1)

    @patch.object(scraper.time, "sleep")
    def test_successful_google_result_avoids_fallback(self, _sleep):
        calls = []

        def fetch(query, backend, max_results):
            calls.append(backend)
            return [{"title": "resultado", "href": "https://example.org"}]

        self.assertTrue(scraper.buscar_web("Nutrição 2026", fetch_fn=fetch))
        self.assertEqual(calls, ["google"])

    @patch.object(scraper.time, "sleep")
    def test_health_check_does_not_turn_failed_query_into_empty_result(self, _sleep):
        calls = []

        def fetch(query, backend, max_results):
            calls.append((query, backend))
            if query == "Brasil":
                return [{"title": "health check", "href": "https://example.org"}]
            raise RuntimeError("Temporary network error")

        self.assertIsNone(scraper.buscar_web("Nutrição 2026", fetch_fn=fetch))
        self.assertEqual(calls, [
            ("Nutrição 2026", "google"),
            ("Nutrição 2026", "google"),
            ("Nutrição 2026", "bing"),
        ])


if __name__ == "__main__":
    unittest.main()
