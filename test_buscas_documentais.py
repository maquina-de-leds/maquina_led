import unittest
import scraper as s
class BuscasDocumentaisTests(unittest.TestCase):
 def test_fontes_antigas_e_novas_preservadas(self):
  consultas=s.consultas_leads('Universidade Presbiteriana Mackenzie','Mackenzie')
  for termo in ['outorga de grau','boletim de serviços','calendário defesas','juramentista','grupo de alunos','TCC repositório','liga acadêmica']:
   self.assertTrue(any(termo in c for c in consultas),termo)
  self.assertEqual(len(consultas),len(set(consultas)))
 def test_troca_faculdade_e_ambos_anos(self):
  consultas=s.consultas_documentos_alunos('Universidade Federal de Santa Catarina','UFSC')
  self.assertTrue(all(c.startswith('UFSC Nutrição ') for c in consultas))
  self.assertEqual(len([c for c in consultas if '2025' in c]),10)
  self.assertEqual(len([c for c in consultas if '2026' in c]),10)
