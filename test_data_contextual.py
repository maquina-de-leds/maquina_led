import unittest
from fontes_academicas import extrair_resultado_busca,ler_html
class DataContextualTests(unittest.TestCase):
 def resultado(self,body):return extrair_resultado_busca(dict(title='Júlia Parpineli Bernini Silva | Mackenzie',body=body),'Universidade Presbiteriana Mackenzie','Mackenzie')
 def test_vinculo_recente_com_projeto_antigo(self):
  self.assertEqual(len(self.resultado('Graduanda em Nutrição na Mackenzie, último semestre em 2026. Projeto iniciado em 2023.')),1)
 def test_artigo_antigo_indexado(self):
  self.assertEqual(self.resultado('Graduanda de Nutrição Mackenzie, artigo de 2017 indexado em 2025'),[])
 def test_paginacao_disponivel_sem_autores(self):
  p='<h2>TCC Nutrição</h2><a href="?offset=20">Próximo &gt;</a>'
  _,links=ler_html(p,'https://pucgoias.edu.br/handle/1/1','PUC Goiás','pucgoias')
  self.assertIn('https://pucgoias.edu.br/handle/1/1?offset=20',links)
