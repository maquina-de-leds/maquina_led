import unittest
from fontes_academicas import ler_html
class OjsLinksTests(unittest.TestCase):
    def test_edicao_recente_segue_artigo_sem_qualificar_autores(self):
        h='<h1>Jornada 2025</h1><div class="obj_article_summary"><a href="/article/view/1">Consumo alimentar</a><div>Ana Silva, Professora Maria Santos</div></div><div class="obj_article_summary"><a href="/article/view/2">Direito civil</a></div>'
        r,l=ler_html(h,'https://revista.edu/issue/view/1','Universidade Teste')
        self.assertEqual(r,[])
        self.assertEqual(l,['https://revista.edu/article/view/1'])
    def test_layout_has_sidebar_preserva_conteudo_principal(self):
        h='<div class="pkp_structure_content has_sidebar"><h1>Jornada 2025</h1><div class="obj_article_summary"><a href="/article/view/1">Consumo alimentar</a></div><div class="sidebar"><a href="/article/view/2">Nutrição no menu</a></div></div>'
        self.assertEqual(ler_html(h,'https://revista.edu/issue/view/1','Universidade Teste')[1],['https://revista.edu/article/view/1'])
    def test_edicao_antiga_nao_abre_artigos_pela_data_do_rodape(self):
        h='<h1>Jornada 2024</h1><div class="obj_article_summary"><a href="/article/view/1">Consumo alimentar</a></div><footer>2026</footer>'
        self.assertEqual(ler_html(h,'https://revista.edu/issue/view/1','Universidade Teste')[1],[])
    def test_pdf_de_metadados_sem_extensao_e_seguido(self):
        h='<meta name="citation_pdf_url" content="https://revista.edu/article/download/1/2"><h1>Artigo</h1>'
        self.assertEqual(ler_html(h,'https://revista.edu/article/view/1','Universidade Teste')[1],['https://revista.edu/article/download/1/2'])
    def test_autoria_sem_biografia_e_indicio_nao_matricula_confirmada(self):
        h='<meta name="citation_author" content="Ana Silva"><meta name="citation_author" content="Maria Santos"><meta name="citation_date" content="2025"><meta name="citation_title" content="Consumo alimentar de universitários"><h1>Consumo alimentar de universitários</h1><p>Universidade Teste. Nutrição.</p><div>v. 10 n. 1 (2025)</div>'
        r,_=ler_html(h,'https://revista.edu/article/view/1','Universidade Teste')
        self.assertEqual([x['nome'] for x in r],['Ana Silva'])
        self.assertTrue(r[0]['candidato_indicio'])
        self.assertIn('NÃO confirmados',r[0]['evidencia'])
    def test_biografia_docente_impede_candidato_autoral(self):
        h='<meta name="citation_author" content="Ana Silva"><meta name="citation_date" content="2025"><meta name="citation_title" content="Consumo alimentar"><p>Universidade Teste. Nutrição.</p><div class="author_bio">Ana Silva. Professora do curso de Nutrição.</div>'
        self.assertEqual(ler_html(h,'https://revista.edu/article/view/1','Universidade Teste')[0],[])
