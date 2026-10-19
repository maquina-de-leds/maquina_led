import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from types import SimpleNamespace
import scraper as s
import fontes_academicas as f
from test_scraper import Repo


class CiclosMaquina1Tests(unittest.TestCase):
    def setUp(self):
        self.stats = dict(s.stats)

    def tearDown(self):
        s.stats.update(self.stats)

    def estado(self):
        return {"status": "processando", "indice_pesquisa": 100,
                "leads_salvos": 0, "leads_encontrados": 0, "tentativas": 0}

    def test_parcial_preserva_marco_e_nao_pausa(self):
        estado = self.estado()
        s.registrar_progresso_ciclo_m1(estado, 49, 149)
        self.assertEqual(estado["leads_salvos"], 49)
        self.assertEqual(estado["indice_pesquisa"], 100)
        self.assertEqual(estado["status"], "processando")

    def test_50_leads_abrem_pausa_de_5_minutos(self):
        estado = self.estado()
        agora = datetime(2026, 10, 18, 18, 0, tzinfo=timezone.utc)
        s.registrar_progresso_ciclo_m1(estado, 50, 170, instante=agora)
        self.assertEqual(estado["status"], "pausa")
        self.assertEqual(estado["indice_pesquisa"], 170)
        self.assertEqual(estado["leads_encontrados"], 50)
        self.assertEqual(estado["tentativas"], 1)
        self.assertEqual(s.segundos_pausa_ciclo_m1(estado, instante=agora), 300)
        self.assertEqual(s.segundos_pausa_ciclo_m1(estado, instante=agora+timedelta(seconds=100)), 200)
        self.assertEqual(s.segundos_pausa_ciclo_m1(estado, instante=agora+timedelta(seconds=301)), 0)

    def salvar(self, repo, nome="Ana Silva"):
        return s.salvar_lead(repo, nome, "Universidade Teste", None, "SP",
                             "Formandos de Nutrição em 2026/1", "https://example.org/formandos",
                             ano_forcado=2026, periodo_forcado="2026/1")

    def test_para_na_meta_sem_descartar_gravacao_e_sem_gravar_51(self):
        repo = Repo()
        repo._limite_novos_ciclo_m1 = 1
        repo._novos_ciclo_m1 = 0
        with patch.object(f, "pessoa", return_value=True), patch.object(f, "fase_final_comprovada", return_value=True):
            with self.assertRaises(s.MetaCicloM1):
                self.salvar(repo)
            with self.assertRaises(s.MetaCicloM1):
                self.salvar(repo, "Bruna Souza")
        self.assertEqual(len(repo.saved), 1)
        self.assertEqual(repo.saved[0]["lead_origem"], s.TAG_CICLO_M1)
        self.assertTrue(repo.saved[0]["qualificado"])

    def test_captura_legada_ou_m3_nao_recebe_tag_do_ciclo_m1(self):
        repo = Repo()
        with patch.object(f, "pessoa", return_value=True), patch.object(f, "fase_final_comprovada", return_value=True):
            self.assertTrue(self.salvar(repo))
        self.assertNotIn("lead_origem", repo.saved[0])

    def test_contagem_exige_tag_m1_qualificado_e_marco(self):
        class Consulta:
            def __init__(self): self.filtros = []
            def select(self, *args): return self
            def eq(self, campo, valor):
                self.filtros.append((campo, valor))
                return self
            def gt(self, campo, valor):
                self.filtros.append(("gt", campo, valor))
                return self
            def order(self, *args): return self
            def range(self, *args): return self
            def execute(self): return SimpleNamespace(data=[{"id": 101}, {"id": 102}])
        consulta = Consulta()
        class Cliente:
            def table(self, nome):
                assert nome == "leds"
                return consulta
        repo = SimpleNamespace(client=Cliente())
        self.assertEqual(s.contar_novos_leads_ciclo_m1(repo, self.estado()), (2, 102))
        self.assertIn(("lead_origem", s.TAG_CICLO_M1), consulta.filtros)
        self.assertIn(("qualificado", True), consulta.filtros)
        self.assertIn(("gt", "id", 100), consulta.filtros)

    def test_varios_lotes_compoem_50_sem_zerar_parcial(self):
        estado = self.estado()
        banco = {"novos": 0}
        repo = SimpleNamespace()
        limites = []
        def lote(**kwargs):
            limites.append(repo._limite_novos_ciclo_m1)
            banco["novos"] = min(50, banco["novos"]+20)
            s.stats["instituicoes_processadas"] += 1
        with patch.object(s.SupabaseRepo, "from_env", return_value=repo), \
             patch.object(s, "carregar_ciclo_m1", return_value=estado), \
             patch.object(s, "salvar_ciclo_m1"), \
             patch.object(s, "contar_novos_leads_ciclo_m1", side_effect=lambda r,e: (banco["novos"], 100+banco["novos"])), \
             patch.object(s, "executar", side_effect=lote), \
             patch.object(s.time, "monotonic", return_value=0), \
             patch.object(s.time, "sleep") as dormir:
            s.executar_ciclos_m1(duracao_maxima=60)
        self.assertEqual(limites, [50, 30, 10])
        self.assertEqual(estado["status"], "pausa")
        self.assertEqual(estado["leads_salvos"], 50)
        dormir.assert_not_called()



    def test_nao_repete_lote_sem_busca_fonte_ou_gravacao_real(self):
        estado = self.estado()
        repo = SimpleNamespace()
        def lote(**kwargs):
            # Visitar novamente um checkpoint em espera não é trabalho externo.
            s.stats["instituicoes_processadas"] += 6
        with patch.object(s.SupabaseRepo, "from_env", return_value=repo), \
             patch.object(s, "carregar_ciclo_m1", return_value=estado), \
             patch.object(s, "salvar_ciclo_m1"), \
             patch.object(s, "contar_novos_leads_ciclo_m1", return_value=(0, 100)), \
             patch.object(s, "executar", side_effect=lote) as executar, \
             patch.object(s.time, "monotonic", return_value=0):
            s.executar_ciclos_m1(duracao_maxima=60)
        executar.assert_called_once()
        self.assertEqual(estado["indice_pesquisa"], 100)
        self.assertEqual(estado["leads_salvos"], 0)
        self.assertEqual(estado["tentativas"], 0)


if __name__ == "__main__":
    unittest.main()
