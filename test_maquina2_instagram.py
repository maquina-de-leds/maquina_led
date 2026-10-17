import unittest
from unittest.mock import patch

import enriquecimento as m2


class BuscaFake:
    def __init__(self, resultados):
        self.resultados = resultados

    def text(self, consulta, max_results=10):
        return self.resultados


class Maquina2InstagramTests(unittest.TestCase):
    def setUp(self):
        for chave in m2.stats:
            m2.stats[chave] = 0


    def test_aceita_pessoa_com_instituicao_universitaria(self):
        lead = {
            "nome": "Geovanna Silva Alves",
            "nicho": "Nutrição",
            "instituicao": "Universidade Presbiteriana Mackenzie",
            "cidade": "São Paulo",
            "estado": "SP",
            "evidencia": "Aluna de Nutrição da universidade em 2025",
            "fonte_url": "https://www.mackenzie.br/noticia",
        }
        self.assertTrue(m2.lead_apto_para_enriquecimento(lead))

    def test_rejeita_instituicao_salva_como_nome(self):
        lead = {
            "nome": "Universidade Presbiteriana Mackenzie",
            "nicho": "Nutrição",
            "instituicao": "Universidade Presbiteriana Mackenzie",
        }
        self.assertFalse(m2.lead_apto_para_enriquecimento(lead))

    def test_rejeita_outro_nicho(self):
        lead = {
            "nome": "Geovanna Silva Alves",
            "nicho": "Fisioterapia",
            "instituicao": "Universidade Exemplo",
        }
        self.assertFalse(m2.lead_apto_para_enriquecimento(lead))

    def test_aceita_outro_perfil_com_evidencia_de_nutricao(self):
        resultado = {
            "title": "Raquel Alves | Nutrição Funcional e Saúde Intestinal",
            "body": "Nutricionista",
        }
        self.assertTrue(m2.resultado_compativel(resultado))

    def test_rejeita_perfil_sem_evidencia_de_nutricao(self):
        resultado = {
            "title": "Raquel Alves | Saúde e bem-estar",
            "body": "Conteúdo sobre qualidade de vida",
        }
        self.assertFalse(m2.resultado_compativel(resultado))

    def test_retorna_varios_perfis_distintos_da_mesma_busca(self):
        resultados = [
            {
                "title": "Raquel Alves | Nutrição Funcional",
                "href": "https://www.instagram.com/raquel.alves/",
            },
            {
                "title": "Marina Costa, nutricionista",
                "href": "https://www.instagram.com/marina.nutri/",
            },
            {
                "title": "Perfil repetido de Nutrição",
                "href": "https://www.instagram.com/raquel.alves/",
            },
            {
                "title": "Clínica de odontologia",
                "href": "https://www.instagram.com/clinica.odonto/",
            },
            {
                "title": "Paula Lima | Nutricionista",
                "href": "https://www.instagram.com/paula.nutri/",
            },
        ]
        lead = {"id": 7, "nome": "Ana Souza"}
        with patch.object(m2, "montar_consultas_instagram", return_value=["Ana Souza Nutrição"]), \
             patch.object(m2, "url_permitida", return_value=True), \
             patch.object(m2, "instagram_ja_usado", return_value=False), \
             patch.object(m2, "pausa"):
            achados = m2.buscar_instagram(BuscaFake(resultados), lead, limite=2)
        self.assertEqual(
            [item["instagram"] for item in achados],
            ["@raquel.alves", "@marina.nutri"],
        )
        self.assertEqual(achados[0]["nome_perfil"], "Raquel Alves | Nutrição Funcional")

    def test_salva_multiplos_candidatos_sem_atualizar_lead_origem(self):
        lead = {
            "id": 7,
            "nome": "Ana Souza Alves",
            "instituicao": "Faculdade Exemplo",
        }
        encontrados = [
            {"instagram": "@raquel.nutri", "nome_perfil": "Raquel Alves"},
            {"instagram": "@marina.nutri", "nome_perfil": "Marina Costa"},
        ]
        with patch.object(m2, "parece_pessoa", return_value=True), \
             patch.object(m2, "buscar_instagram", return_value=encontrados), \
             patch.object(m2, "salvar_candidato", return_value=True) as salvar, \
             patch.object(m2, "atualizar_lead") as atualizar:
            m2.processar_lead(object(), lead)
        self.assertEqual(salvar.call_count, 2)
        atualizar.assert_not_called()
        self.assertEqual(m2.stats["instagram_encontrado"], 2)


    def test_maquina2_nao_contem_atualizacao_na_tabela_de_leads(self):
        import ast
        from pathlib import Path
        tree = ast.parse(Path(m2.__file__).read_text())
        atualizacoes_leds = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "update":
                continue
            chamada = ast.unparse(node.func.value)
            if '.table("leds")' in chamada or ".table('leds')" in chamada:
                atualizacoes_leds.append(node.lineno)
        self.assertEqual(atualizacoes_leds, [])

if __name__ == "__main__":
    unittest.main()
