import unittest
from unittest.mock import Mock, patch
import scraper as s

class CacheTests(unittest.TestCase):
    def repo(self):
        repo=s.SupabaseRepo(Mock())
        repo.lead_da_fonte=Mock(return_value=None)
        repo.lead_existe=Mock(return_value=False)
        repo.inserir_lead=Mock()
        repo.completar_instagram=Mock(return_value=True)
        repo.instagram_usado=Mock(return_value=False)
        return repo
    def salvar(self,repo,inst='Universidade A',instagram=None):
        return s.salvar_lead(repo,'Ana Silva',inst,None,None,'Nutrição 2026','https://example.org/a',instagram=instagram,ano_forcado=2026,periodo_forcado='2026/2')
    def test_repeticao_confirmada_nao_reconsulta_nem_reinsere(self):
        repo=self.repo()
        self.assertTrue(self.salvar(repo))
        self.assertFalse(self.salvar(repo))
        self.assertEqual(repo.lead_da_fonte.call_count,1)
        self.assertEqual(repo.lead_existe.call_count,1)
        self.assertEqual(repo.inserir_lead.call_count,1)
    def test_cache_nao_impede_completar_instagram(self):
        repo=self.repo(); self.salvar(repo)
        self.assertFalse(self.salvar(repo,instagram='@ana.nutri'))
        repo.completar_instagram.assert_called_once_with('Ana Silva','Universidade A','@ana.nutri')
    def test_falha_de_gravacao_nao_e_memorizada(self):
        repo=self.repo(); repo.inserir_lead.side_effect=RuntimeError('Banco indisponível')
        with self.assertRaises(RuntimeError): self.salvar(repo)
        self.assertEqual(repo._leads_confirmados,{})
        repo.inserir_lead.side_effect=None
        self.assertTrue(self.salvar(repo))
        self.assertEqual(repo.lead_da_fonte.call_count,2)
    def test_contexto_de_faculdade_nao_e_transferido(self):
        repo=self.repo(); self.salvar(repo)
        self.assertTrue(self.salvar(repo,inst='Universidade B'))
        self.assertEqual(repo.lead_da_fonte.call_count,2)
