import unittest
from unittest.mock import patch

import maquina3 as m


class FakeRepo:
    def __init__(self):
        self.saved_checkpoints = []

    def controle_salvar(self, etapa, dados):
        self.saved_checkpoints.append((etapa, dict(dados)))


class FakeLeadRepo(FakeRepo):
    def __init__(self):
        super().__init__()
        self.leads = []

    def instagram_usado(self, instagram):
        return any(x.get("instagram") == instagram for x in self.leads)

    def lead_existe(self, nome, instituicao):
        return any(x.get("nome") == nome and x.get("instituicao") == instituicao for x in self.leads)

    def inserir_lead(self, dados):
        self.leads.append(dict(dados))
        return True


class Machine3Tests(unittest.TestCase):
    def test_queries_cover_target_years_and_course(self):
        item = {"id": 3, "instituicao": "Universidade Teste", "estado": "SP"}
        queries = m.consultas_lote(item)
        self.assertEqual(len(queries), 6)
        self.assertTrue(all("Nutrição" in q for q in queries))
        self.assertTrue(any("2025" in q for q in queries))
        self.assertTrue(any("2026" in q for q in queries))
        self.assertFalse(any("site:instagram.com" in q for q in queries))
        self.assertTrue(any("TCC" in q for q in queries))
        self.assertTrue(any("último semestre" in q for q in queries))

    def test_uses_google_search_backend(self):
        with patch.object(m, "ddgs_texto", return_value=[{"href": "https://example.edu/"}]) as search:
            results = m.buscar_google("Nutrição formandos 2025")
        self.assertEqual(len(results), 1)
        search.assert_called_once_with("Nutrição formandos 2025", backend="google", max_results=m.MAX_RESULTADOS_BUSCA)

    def test_falls_back_if_google_is_unavailable(self):
        fallback = [{"href": "https://example.edu/"}]
        with patch.object(m, "ddgs_texto", side_effect=RuntimeError("Google unavailable")) as google, \
             patch.object(m, "buscar_web", return_value=fallback) as alternate:
            results = m.buscar_google("Nutrição formandos 2025")
        self.assertEqual(results, fallback)
        self.assertEqual(google.call_count, 2)
        alternate.assert_called_once_with("Nutrição formandos 2025", max_results=m.MAX_RESULTADOS_BUSCA)

    def test_state_sequence_starts_sc_sp_pr_then_covers_all_states(self):
        self.assertEqual(m.ORDEM_ESTADOS_M3[:3], ["SC", "SP", "PR"])
        self.assertEqual(len(m.ORDEM_ESTADOS_M3), 27)
        self.assertEqual(len(set(m.ORDEM_ESTADOS_M3)), 27)
        items = [
            {"id": 1, "estado": "SP", "instituicao": "Faculdade SP"},
            {"id": 2, "estado": "PR", "instituicao": "Faculdade PR"},
            {"id": 3, "estado": "SC", "instituicao": "Faculdade SC"},
        ]
        self.assertEqual(m.selecionar_lote(items)[0]["estado"], "SC")

    def test_selects_maximum_five_and_one_state(self):
        items = [
            {"id": i, "estado": "SP", "instituicao": f"Faculdade {i}"}
            for i in range(1, 8)
        ] + [{"id": 20, "estado": "RJ", "instituicao": "Outra UF"}]
        lote = m.selecionar_lote(items)
        self.assertEqual(len(lote), 5)
        self.assertEqual({x["estado"] for x in lote}, {"SP"})

    def test_extracts_named_people_from_public_institution_instagram_snippet(self):
        item = {"id": 3, "instituicao": "Centro Universitário Teste", "estado": "SP"}
        result = {
            "href": "https://www.instagram.com/p/abc123/",
            "title": "Centro Universitário Teste | Formandos de Nutrição 2025: Ana Souza, Beatriz Lima",
            "body": "Parabéns pela colação de grau da turma de Nutrição 2025.",
        }
        candidates = m.candidatos_instagram_publico(result, item)
        self.assertEqual([x["nome"] for x in candidates], ["Ana Souza", "Beatriz Lima"])
        self.assertEqual({x["ano"] for x in candidates}, {2025})
        self.assertTrue(all("Instagram público institucional" in x["evidencia"] for x in candidates))

    def test_requires_institution_course_and_academic_phase_in_public_instagram_snippet(self):
        item = {"id": 4, "instituicao": "Centro Universitário Teste", "estado": "SP"}
        result = {
            "href": "https://www.instagram.com/p/abc123/",
            "title": "Formandos de Nutrição 2026: Ana Souza",
            "body": "8º período.",
        }
        self.assertEqual(m.candidatos_instagram_publico(result, item), [])

    def test_extracts_2026_final_semester_candidates_from_public_post(self):
        item = {"id": 5, "instituicao": "Centro Universitário Teste", "estado": "SP"}
        result = {
            "href": "https://www.instagram.com/p/abc123/",
            "title": "Centro Universitário Teste: Nutrição, último semestre de 2026",
            "body": "Aluna Ana Souza concluindo o último semestre.",
        }
        candidates = m.candidatos_instagram_publico(result, item)
        self.assertEqual([x["nome"] for x in candidates], ["Ana Souza"])
        self.assertEqual(candidates[0]["ano"], 2026)

    def test_extracts_candidates_from_general_public_google_snippets(self):
        repo = FakeRepo()
        item = {"id": 9, "estado": "SP", "instituicao": "Universidade Teste"}
        result = {"href": "https://universidade-teste.edu.br/formandos", "title": "Nutrição 2026"}
        candidate = {
            "nome": "Ana Souza",
            "ano": 2026,
            "periodo": "2026",
            "instituicao": "Universidade Teste",
            "evidencia": "Universidade Teste | Nutrição | formanda 2026",
            "fonte_url": result["href"],
        }
        with patch.object(m, "buscar_google", return_value=[result]), \
             patch.object(m, "extrair_resultado_busca", side_effect=[[candidate], [], [], [], [], []]), \
             patch.object(m, "carregar_fonte", return_value=([], [])), \
             patch.object(m, "buscar_instagram_da_pessoa", return_value={"instagram": "@anasouza.nutri", "instagram_url": "https://www.instagram.com/anasouza.nutri/", "evidencia": "Ana Souza nutricionista"}), \
             patch.object(m, "salvar_lead") as save:
            self.assertTrue(m.processar_faculdade(repo, item))
        save.assert_called_once()
        self.assertEqual(save.call_args.args[1], "Ana Souza")
        self.assertEqual(save.call_args.kwargs["instagram"], "@anasouza.nutri")

    def test_extracts_handle_only_from_matching_public_profile(self):
        result = {
            "href": "https://www.instagram.com/nutriamandagasparin/",
            "title": "Amanda Gasparin (@nutriamandagasparin) • Instagram",
            "body": "Nutricionista em Chapecó, CRN 10-13039",
        }
        perfil = m.extrair_perfil_instagram_publico([result], {"nome": "Amanda Gasparin"})
        self.assertEqual(perfil["instagram"], "@nutriamandagasparin")
        self.assertEqual(perfil["instagram_url"], "https://www.instagram.com/nutriamandagasparin/")

    def test_extracts_handle_linked_from_professional_directory(self):
        result = {
            "href": "https://dietbox.me/pt-BR/amanda-gasparin",
            "title": "Nutricionista Amanda Gasparin em Chapecó",
            "body": "CRN 10-13039. Instagram www.instagram.com/nutriamandagasparin",
        }
        perfil = m.extrair_perfil_instagram_publico([result], {"nome": "Amanda Gasparin"})
        self.assertEqual(perfil["instagram"], "@nutriamandagasparin")

    def test_qualification_requires_person_course_year_and_recent_phase(self):
        valid = {
            "nome": "Ana Souza",
            "ano": 2025,
            "evidencia": "Formanda do curso de Nutrição, colação de grau em 2025",
        }
        no_phase = {**valid, "evidencia": "Estudante de Nutrição em 2025"}
        organization = {**valid, "nome": "Universidade Teste"}
        no_course = {**valid, "evidencia": "Formanda com colação de grau em 2025"}
        self.assertTrue(m.lead_qualificado_maquina3(valid))
        self.assertFalse(m.lead_qualificado_maquina3(no_phase))
        self.assertFalse(m.lead_qualificado_maquina3(organization))
        self.assertFalse(m.lead_qualificado_maquina3(no_course))

    def test_reuses_instagram_result_for_repeated_name(self):
        item = {"instituicao": "Universidade Teste", "cidade": "Chapecó"}
        registro = {"nome": "Ana Souza", "evidencia": "Formanda de Nutrição em 2025"}
        perfil = {
            "instagram": "@anasouza.nutri",
            "instagram_url": "https://www.instagram.com/anasouza.nutri/",
            "evidencia": "Ana Souza nutricionista",
        }
        cache = {}
        with patch.object(m, "buscar_instagram_da_pessoa", return_value=perfil) as search:
            first, used = m.enriquecer_com_instagram([dict(registro)], item, 0, cache)
            second, used = m.enriquecer_com_instagram([dict(registro)], item, used, cache)
        self.assertEqual(search.call_count, 1)
        self.assertEqual(first[0]["instagram"], "@anasouza.nutri")
        self.assertEqual(second[0]["instagram"], "@anasouza.nutri")
        self.assertEqual(used, 1)

    def test_uses_other_public_nutritionist_profile_only_as_fallback(self):
        results = [{
            "href": "https://www.instagram.com/carlanutri/",
            "title": "Carla Mendes (@carlanutri) • Instagram",
            "body": "Nutricionista clínica, CRN 12345",
        }]
        perfil = m.extrair_perfil_relacionado(results, "Ana Souza")
        self.assertEqual(perfil["nome"], "Carla Mendes")
        self.assertEqual(perfil["instagram"], "@carlanutri")
        self.assertIsNone(m.extrair_perfil_relacionado(results, "Carla Mendes"))

    def test_reserve_search_can_find_related_nutritionist_outside_institution(self):
        result = {
            "href": "https://www.instagram.com/carlanutri/",
            "title": "Carla Mendes (@carlanutri) • Instagram",
            "body": "Nutricionista clínica, CRN 12345",
        }
        with patch.object(m, "buscar_google", side_effect=[[], [result]]) as search, \
             patch.object(m, "extrair_perfil_instagram_publico", return_value=None):
            fallback = m.buscar_instagram_da_pessoa(
                {"nome": "Ana Souza"},
                {"instituicao": "Universidade Teste", "cidade": "Chapecó"},
            )
        self.assertEqual(search.call_count, 2)
        self.assertNotIn("Universidade Teste", search.call_args_list[1].args[0])
        self.assertEqual(fallback["fallback_lead"]["instagram"], "@carlanutri")

    def test_saves_related_profile_without_falsifying_graduation_year(self):
        repo = FakeLeadRepo()
        item = {"cidade": "Chapecó", "estado": "SC"}
        perfil = {
            "nome": "Carla Mendes",
            "instagram": "@carlanutri",
            "instagram_url": "https://www.instagram.com/carlanutri/",
            "evidencia": "Nutricionista clínica, CRN 12345",
        }
        before = m.stats["leads_salvos"]
        self.assertTrue(m.salvar_profissional_relacionado(repo, perfil, item, "Ana Souza"))
        saved = repo.leads[0]
        self.assertEqual(saved["nome"], "Carla Mendes")
        self.assertEqual(saved["instagram"], "@carlanutri")
        self.assertIsNone(saved["ano_alvo"])
        self.assertIsNone(saved["periodo_alvo"])
        self.assertFalse(saved["qualificado"])
        m.stats["leads_salvos"] = before

    def test_rejects_post_and_unrelated_profile(self):
        registro = {"nome": "Amanda Gasparin"}
        post = {"href": "https://www.instagram.com/p/abc123/", "title": "Amanda Gasparin Nutricionista"}
        wrong = {"href": "https://www.instagram.com/nutri.outroperfil/", "title": "Nutricionista em Chapecó"}
        self.assertIsNone(m.extrair_perfil_instagram_publico([post], registro))
        self.assertIsNone(m.extrair_perfil_instagram_publico([wrong], registro))

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
        with patch.object(m, "buscar_google", return_value=resultados) as search, \
             patch.object(m, "carregar_fonte", return_value=([], [])) as fetch, \
             patch.object(m, "salvar_lead") as save:
            self.assertTrue(m.processar_faculdade(repo, item))
        self.assertEqual(search.call_count, 6)
        self.assertEqual(fetch.call_count, 12)
        save.assert_not_called()
        self.assertEqual(repo.saved_checkpoints[-1][1]["status"], "concluido")


if __name__ == "__main__":
    unittest.main()

