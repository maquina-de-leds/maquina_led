import unittest
from colecoes_academicas import ler_colecao

class ColecaoTests(unittest.TestCase):
    def pagina(self,ano='2025'):
        return f'<h1>Search</h1><p>Showing 1 out of a total of 2 results for collection: TCC Nutrição.</p><div class="artifact-description"><div class="artifact-title"><a href="/handle/123/456">Pesquisa</a></div><span class="author"><span>Silva, Ana</span><span>Souza, Bruna</span></span><span class="date">{ano}-12-05</span></div><a href="?page=2">Next Page</a><footer>2026</footer>'
    def test_autores_data_por_item_e_paginacao(self):
        r=ler_colecao(self.pagina(),'https://repositorio.ufsc.br/handle/123/1','Universidade Federal de Santa Catarina','UFSC')
        self.assertEqual([x['nome'] for x in r['documentos'][0]['registros']],['Ana Silva','Bruna Souza'])
        self.assertEqual(r['total'],2)
        self.assertEqual(len(r['proximas']),1)
        self.assertEqual(r['documentos'][0]['registros'][0]['ano'],2025)
    def test_ano_antigo_nao_usa_rodape(self):
        self.assertEqual(ler_colecao(self.pagina('2024'),'https://repositorio.ufsc.br/x','UFSC','UFSC')['documentos'],[])
    def test_colecao_de_outro_curso_nao_qualifica(self):
        self.assertEqual(ler_colecao(self.pagina().replace('TCC Nutrição','TCC Engenharia'),'https://repositorio.ufsc.br/x','UFSC','UFSC')['documentos'],[])
    def test_nao_atribui_faculdade_da_consulta_a_outra_fonte(self):
        r=ler_colecao(self.pagina(),'https://repositorio.ufsc.br/x','Mackenzie','Mackenzie')
        self.assertIsNone(r['documentos'][0]['registros'][0]['instituicao'])
