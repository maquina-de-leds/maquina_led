import unittest
from colecoes_academicas import ler_colecao
class JspuiTests(unittest.TestCase):
 def test_autor_data_paginacao_sem_facetas(self):
  pagina='<h2>TCC Nutrição</h2><table><tr><th id="t1">Data do documento</th><th id="t2">Título</th><th id="t3">Autor(es)</th></tr><tr><td headers="t1">10-Jun-2026</td><td headers="t2"><a href="/handle/1/2">Trabalho pronto</a></td><td headers="t3">Silva, Maria Carolina</td></tr></table><a href="?offset=20">Próximo &gt;</a><a href="?author_page=1">Próximo &gt;</a>'
  r=ler_colecao(pagina,'https://pucgoias.edu.br/handle/1/1','PUC Goiás','pucgoias')
  self.assertEqual(r['documentos'][0]['registros'][0]['nome'],'Maria Carolina Silva')
  self.assertEqual(len(r['proximas']),1)
  self.assertEqual(ler_colecao(pagina.replace('10-Jun-2026','10-Jun-2024'),'https://pucgoias.edu.br/handle/1/1','PUC Goiás','pucgoias')['documentos'],[])
 def test_outra_colecao(self):
  self.assertEqual(ler_colecao('<h2>Enfermagem</h2>','https://pucgoias.edu.br','PUC Goiás')['documentos'],[])
