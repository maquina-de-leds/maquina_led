import unittest

from fontes_academicas import extrair_resultado_busca


class PerfisSociaisPublicosTests(unittest.TestCase):
    def test_instagram_linkado_no_resultado_publico_do_linkedin(self):
        resultado = {
            "title": "Helena Santos | LinkedIn",
            "body": "Nutricionista. Instagram: https://www.instagram.com/nutrihelenasantos/",
            "href": "https://br.linkedin.com/in/helena-santos",
        }
        registros = extrair_resultado_busca(resultado, "UFBA")
        self.assertEqual(len(registros), 1)
        self.assertEqual(registros[0]["instagram"], "@nutrihelenasantos")
        self.assertTrue(registros[0]["perfil_social_publico"])
        self.assertIsNone(registros[0]["ano"])
        self.assertIsNone(registros[0]["seguidores_instagram"])

    def test_contagem_instagram_aplica_limite_de_tres_mil(self):
        abaixo = {
            "title": "Helena Santos (@nutrihelenasantos) • Instagram",
            "body": "Nutricionista | 2,6 mil seguidores",
            "href": "https://www.instagram.com/nutrihelenasantos/",
        }
        acima = {
            "title": "Helena Santos (@nutrihelenasantos) • Instagram",
            "body": "Nutricionista | 3,1 mil seguidores",
            "href": "https://www.instagram.com/nutrihelenasantos/",
        }
        registros = extrair_resultado_busca(abaixo, "UFBA")
        self.assertEqual(registros[0]["seguidores_instagram"], 2600)
        self.assertEqual(extrair_resultado_busca(acima, "UFBA"), [])


if __name__ == "__main__":
    unittest.main()
