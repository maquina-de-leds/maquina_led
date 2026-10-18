import unittest
from unittest.mock import patch

import enriquecimento as m2


class BuscaFake:
    def __init__(self, resultados):
        self.resultados = resultados

    def text(self, consulta, max_results=10, backend=None):
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

    def test_nome_do_lead_sem_evidencia_tematica_nao_qualifica(self):
        resultado = {
            "title": "Ana Souza (@ana.souza)",
            "href": "https://www.instagram.com/ana.souza/",
        }
        self.assertFalse(m2.resultado_compativel(resultado, {"nome": "Ana Souza"}))

    def test_rejeita_congresso_mesmo_com_nutricao_no_titulo(self):
        self.assertFalse(m2.resultado_compativel({
            "title": "Ganepão • maior congresso de nutrição da América Latina",
            "href": "https://www.instagram.com/ganepao/",
        }))

    def test_nao_transfere_tema_de_outro_perfil_concatenado(self):
        self.assertFalse(m2.resultado_compativel({
            "title": "Ana Souza (@anasouza) • Instagram photos and videosBia | Nutrição - Instagram",
            "body": "Ana Souza Instagram. Nutricionista Bia (@bia.nutri)",
            "href": "https://www.instagram.com/anasouza/",
        }))

    def test_nao_extrai_handle_solto_de_pagina_de_terceiro(self):
        self.assertIsNone(m2._perfil_do_resultado({
            "title": "Nutricionistas famosos", "body": "instagram.com/ana.nutri/",
            "href": "https://exemplo.com/lista",
        }))

    def test_candidato_independente_sem_vinculo_de_identidade(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        cliente = MagicMock()
        cliente.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(data=[{"id": 123}])
        with patch.object(m2, "supabase", cliente), patch.object(m2, "instagram_ja_usado", return_value=False):
            self.assertTrue(m2.salvar_candidato({"id": 7, "nome": "Ana Souza"}, {
                "instagram": "@bia.nutri", "nome_perfil": "Bia Santos | Nutrição",
                "fonte_url": "https://www.instagram.com/bia.nutri/",
            }))
        self.assertIsNone(cliente.table.return_value.insert.call_args.args[0]["lead_origem_id"])

    def test_gravacao_rejeita_candidato_sem_evidencia(self):
        from unittest.mock import MagicMock
        cliente = MagicMock()
        with patch.object(m2, "supabase", cliente):
            self.assertFalse(m2.salvar_candidato({"id": 7, "nome": "Ana Souza"}, {
                "instagram": "@ana.souza", "nome_perfil": "Ana Souza",
                "fonte_url": "https://www.instagram.com/ana.souza/",
            }))
        cliente.table.assert_not_called()

    def test_aceita_handle_publico_com_sinal_de_nutricao(self):
        resultado = {
            "title": "Perfil profissional",
            "href": "https://www.instagram.com/marina.nutri/",
        }
        self.assertTrue(m2.resultado_compativel(resultado))

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


    def test_filtro_m2_nao_impoe_espera_de_14_dias(self):
        from datetime import datetime, timezone
        class Consulta:
            def __init__(self):
                self.expressao = None
            def or_(self, expressao):
                self.expressao = expressao
                return self

        consulta = Consulta()
        instante = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        m2.filtrar_pendentes_rebusca(consulta, agora=instante)
        self.assertIn("maquina2_verificado_em.is.null", consulta.expressao)
        self.assertEqual(m2.INTERVALO_REBUSCA_DIAS, 0)
        self.assertIn("maquina2_verificado_em.lt.2026-10-18T12:00:00+00:00", consulta.expressao)

    def test_registra_cooldown_fora_da_tabela_de_leads(self):
        import ast
        from pathlib import Path
        tree = ast.parse(Path(m2.__file__).read_text())
        atualizacoes_leds = []
        gravacoes_controle = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            chamada = ast.unparse(node.func.value)
            if node.func.attr == "update" and ('.table("leds")' in chamada or ".table('leds')" in chamada):
                atualizacoes_leds.append(node)
            if node.func.attr in {"insert", "update"} and ('.table("controle_busca")' in chamada or ".table('controle_busca')" in chamada):
                gravacoes_controle.append(node)
        self.assertEqual(len(atualizacoes_leds), 0)
        self.assertGreaterEqual(len(gravacoes_controle), 2)



    def test_busca_usa_bing_quando_google_falha_sem_usar_auto(self):
        chamadas = []
        class Busca:
            def text(self, consulta, max_results=10, backend=None):
                chamadas.append(backend)
                if backend == "google":
                    raise ConnectionError("TLS indisponível")
                return [{"title": "Bia Nutricionista",
                         "href": "https://www.instagram.com/bia.nutri/"}]
        with patch.object(m2, "montar_consultas_instagram", return_value=["Nutrição"]), \
             patch.object(m2, "instagram_ja_usado", return_value=False), \
             patch.object(m2, "pausa"), patch("scraper.time.sleep"):
            encontrados = m2.buscar_instagram(Busca(), {"id": 7}, limite=1)
        self.assertEqual(chamadas, ["google", "bing"])
        self.assertEqual(encontrados[0]["instagram"], "@bia.nutri")
        self.assertEqual(m2.stats["erros"], 0)

    def test_falha_dos_dois_buscadores_nao_vira_sucesso_vazio(self):
        class Busca:
            def text(self, *args, **kwargs):
                raise ConnectionError("offline")
        with patch.object(m2, "montar_consultas_instagram", return_value=["Nutrição"]), \
             patch.object(m2, "pausa"), patch("scraper.time.sleep"):
            encontrados = m2.buscar_instagram(Busca(), {"id": 7})
        self.assertEqual(encontrados, [])
        self.assertEqual(m2.stats["erros"], 1)


class CiclosMaquina2Tests(unittest.TestCase):
    def estado(self):
        return {"id": 9, "status": "processando", "indice_pesquisa": 100,
                "tentativas": 0, "leads_encontrados": 0, "leads_salvos": 0}

    def test_parcial_nao_pausa_nem_perde_marco(self):
        estado = self.estado()
        m2.registrar_progresso_ciclo(estado, 49, 149)
        self.assertEqual(estado["status"], "processando")
        self.assertEqual(estado["indice_pesquisa"], 100)
        self.assertEqual(estado["leads_salvos"], 49)
        self.assertEqual(estado["tentativas"], 0)

    def test_50_salvos_abrem_pausa_persistente_de_300_segundos(self):
        from datetime import datetime, timezone, timedelta
        agora = datetime(2026, 10, 18, 18, 0, tzinfo=timezone.utc)
        estado = self.estado()
        m2.registrar_progresso_ciclo(estado, 50, 170, agora=agora)
        self.assertEqual(estado["status"], "pausa")
        self.assertEqual(estado["indice_pesquisa"], 170)
        self.assertEqual(estado["tentativas"], 1)
        self.assertEqual(estado["leads_encontrados"], 50)
        self.assertEqual(m2.segundos_pausa_ciclo(estado, agora=agora), 300)
        self.assertEqual(m2.segundos_pausa_ciclo(estado, agora=agora+timedelta(seconds=100)), 200)
        self.assertEqual(m2.segundos_pausa_ciclo(estado, agora=agora+timedelta(seconds=301)), 0)

    def test_contagem_exclui_base_antiga_e_deduplica_caixa(self):
        from types import SimpleNamespace
        class Consulta:
            def __init__(self):
                self.base = None
            def select(self, *args): return self
            def gt(self, campo, valor):
                self.base = valor
                return self
            def order(self, *args): return self
            def range(self, inicio, fim): return self
            def execute(self):
                return SimpleNamespace(data=[
                    {"id": 101, "instagram": "@Ana.Nutri"},
                    {"id": 102, "instagram": "@ana.nutri"},
                    {"id": 103, "instagram": "@Bia.Nutri"},
                ])
        class Cliente:
            def __init__(self): self.consulta = Consulta()
            def table(self, nome):
                assert nome == "instagram_candidatos"
                return self.consulta
        cliente = Cliente()
        with patch.object(m2, "supabase", cliente), patch.object(m2, "handles_anteriores_ciclo", return_value=set()):
            self.assertEqual(m2.contar_novos_arrobas_ciclo(self.estado()), (2, 103))
        self.assertEqual(cliente.consulta.base, 100)

    def test_contagem_exclui_antigos_e_instituicoes_sem_mudar_marco(self):
        from unittest.mock import MagicMock
        cliente = MagicMock()
        cliente.table.return_value.select.return_value.gt.return_value.order.return_value.range.return_value.execute.return_value.data = [
            {"id": 101, "instagram": "ana.nutri", "nome_perfil": "Ana Nutricionista"},
            {"id": 102, "instagram": "@ganepao", "nome_perfil": "Ganepão | Congresso de Nutrição"},
            {"id": 103, "instagram": "@bia.nutri", "nome_perfil": "Bia Nutricionista"},
        ]
        estado = self.estado()
        with patch.object(m2, "supabase", cliente), patch.object(m2, "handles_anteriores_ciclo", return_value={"@ana.nutri"}):
            self.assertEqual(m2.contar_novos_arrobas_ciclo(estado), (1, 103))
        self.assertEqual(estado["indice_pesquisa"], 100)

    def test_continua_varios_lotes_ate_50_sem_pausar_antes(self):
        estado = self.estado()
        banco = {"novos": 0, "cursor": 0}
        sementes = []
        def lote(**kwargs):
            sementes.append(m2.stats["instagram_encontrado"])
            banco["novos"] = min(50, banco["novos"] + 20)
            banco["cursor"] += 50
            m2.stats["pendentes"] = 50
        with patch.object(m2, "conectar_banco", return_value=object()), \
             patch.object(m2, "carregar_ciclo_m2", return_value=estado), \
             patch.object(m2, "salvar_ciclo_m2"), \
             patch.object(m2, "contar_novos_arrobas_ciclo", side_effect=lambda e: (banco["novos"], 100+banco["novos"])), \
             patch.object(m2, "obter_cursor_m2", side_effect=lambda: banco["cursor"]), \
             patch.object(m2, "executar", side_effect=lote) as executar, \
             patch.object(m2.time, "monotonic", return_value=0), \
             patch.object(m2.time, "sleep") as dormir:
            m2.executar_ciclos(duracao_maxima=60)
        self.assertEqual(executar.call_count, 3)
        self.assertEqual(sementes, [0, 20, 40])
        self.assertEqual(estado["status"], "pausa")
        self.assertEqual(estado["leads_salvos"], 50)
        dormir.assert_not_called()  # Pausa fica persistida para o próximo runner.

    def test_falha_preserva_gravacoes_parciais_e_sinaliza_erro(self):
        estado = self.estado()
        banco = {"novos": 0}
        def falhar(**kwargs):
            banco["novos"] = 12
            raise RuntimeError("buscador indisponível")
        with patch.object(m2, "conectar_banco", return_value=object()), \
             patch.object(m2, "carregar_ciclo_m2", return_value=estado), \
             patch.object(m2, "salvar_ciclo_m2"), \
             patch.object(m2, "contar_novos_arrobas_ciclo", side_effect=lambda e: (banco["novos"], 100+banco["novos"])), \
             patch.object(m2, "obter_cursor_m2", return_value=0), \
             patch.object(m2, "executar", side_effect=falhar), \
             patch.object(m2.time, "monotonic", return_value=0):
            with self.assertRaisesRegex(RuntimeError, "buscador"):
                m2.executar_ciclos(duracao_maxima=60)
        self.assertEqual(estado["leads_salvos"], 12)
        self.assertEqual(estado["indice_pesquisa"], 100)


if __name__ == "__main__":
    unittest.main()
