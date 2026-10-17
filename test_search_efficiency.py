import unittest
from unittest.mock import patch

import scraper


class MachineOneSearchEfficiencyTests(unittest.TestCase):
    def test_queries_are_bounded_and_cover_both_years_and_academic_signals(self):
        queries = scraper.consultas_leads(
            "Universidade Teste", "UT", cidade="Itu", uf="SP"
        )
        self.assertLessEqual(len(queries), 36)
        self.assertGreater(len(queries), 20)
        self.assertEqual(len(queries), len(set(queries)))
        for year in ("2025", "2026"):
            self.assertTrue(any(year in q for q in queries))
        for signal in (
            '"formandos"', '"TCC"', "defesa", "apresentação", "repositório",
            '"colação de grau"', '"recém-formados"', '"último período"',
            '"estágio final"', '"mostra" "autores"', '"turma"',
            '"Itu" SP', "site:linkedin.com/in",
        ):
            self.assertTrue(any(signal in q for q in queries), signal)
        self.assertFalse(any("instagram" in q.lower() or "site:instagram.com" in q.lower()
                             for q in queries))

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


if __name__ == "__main__":
    unittest.main()
