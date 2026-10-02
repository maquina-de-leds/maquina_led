import unittest
from unittest.mock import patch
import fontes_academicas as f
import scraper as s
from test_scraper import Repo

class CorrecaoBuscaTests(unittest.TestCase):
    @patch.object(s.time,'sleep')
    def test_pdf_oficial_sem_instituicao_no_resumo_continua_lido(self,sleep):
        repo=Repo(); lidas=[]
        def fonte(url,*args):
            lidas.append(url)
            return [],[]
        resultados=[{'href':'https://www.mackenzie.br/alunos.pdf','title':'Projetos aprovados 2025'},
                    {'href':'https://outra.edu.br/alunos.pdf','title':'Nutrição Universidade Outra 2025'}]
        with patch.object(s,'consultas_leads',return_value=['teste']):
            s.processar_instituicao(repo,{**repo.item,'instituicao':'Universidade Presbiteriana Mackenzie','fonte_validacao':'SIGLA=Mackenzie'},search_fn=lambda *a:resultados,source_fn=fonte)
        self.assertEqual(lidas,['https://www.mackenzie.br/alunos.pdf'])

    def test_noticia_oficial_tenta_copia_publica_apos_falha(self):
        url='https://www.mackenzie.br/noticias/artigo/n/a/i/projeto'
        registro={'nome':'Ana Silva'}
        with patch.object(f,'_carregar_url',side_effect=[RuntimeError('503'),([registro],[])]) as leitura:
            self.assertEqual(f.carregar_fonte(url,'Mackenzie'),([registro],[]))
        self.assertEqual(leitura.call_args_list[1].args[0],'https://portal.mackenzie.br/noticias/artigo/n/a/i/projeto')

    def test_area_profissional_nao_e_pessoa(self):
        self.assertIsNone(f.pessoa('Indústria de Alimentos'))
        repo=Repo()
        self.assertFalse(s.salvar_lead(repo,'Indústria de Alimentos','Mackenzie',None,None,'Nutrição 2026','https://mackenzie.br',ano_forcado=2026,periodo_forcado='2026/1'))
        self.assertEqual(repo.saved,[])
    def test_tcc_em_div_sem_paragrafo(self):
        html='<title>Mostra de TCC - Universidade Presbiteriana Mackenzie</title><div>NUTRIÇÃO 2026.1</div><div>01 - CHIARA AURICHIO CUNHA</div><div>07 - LAURA AMABILE FORMIGONI KELER e VICTORIA GREGORIO BLASI</div>'
        r,_=f.ler_html(html,'https://mackenzie.br/tcc','Universidade Presbiteriana Mackenzie','Mackenzie')
        self.assertEqual({x['nome'] for x in r},{'CHIARA AURICHIO CUNHA','LAURA AMABILE FORMIGONI KELER','VICTORIA GREGORIO BLASI'})
        self.assertEqual({x['periodo'] for x in r},{'2026/1'})
    def test_resultado_linkedin_com_vinculo(self):
        r=f.extrair_resultado_busca({'title':'Ana Silva - LinkedIn','body':'Graduanda de Nutrição na Mackenzie em 2026, 8º semestre.'},'Universidade Presbiteriana Mackenzie','Mackenzie')
        self.assertEqual(r[0]['nome'],'Ana Silva')
        self.assertEqual(r[0]['ano'],2026)
    def test_ano_na_consulta_nao_inventa_ano(self):
        self.assertEqual(f.extrair_resultado_busca({'title':'Ana Silva','body':'Nutrição Mackenzie'},'Mackenzie'),[])
    def test_periodo_sem_ano_fica_pendente(self):
        r=f.extrair_resultado_busca({'title':'Ana Silva','body':'Estudante de Nutrição Mackenzie, 7º período'},'Mackenzie')
        self.assertIsNone(r[0]['ano'])
        repo=Repo()
        self.assertTrue(s.salvar_lead(repo,r[0]['nome'],'Mackenzie',None,None,r[0]['evidencia'],'https://example.org',ano_forcado=None,periodo_forcado=r[0]['periodo']))
        self.assertIsNone(repo.saved[0]['ano_alvo'])
    def test_resultado_antigo_nao_usa_data_de_indexacao(self):
        self.assertEqual(f.extrair_resultado_busca({'title':'Ana Silva','body':'Graduanda de Nutrição Mackenzie, artigo de 2017 indexado em 2025'},'Mackenzie'),[])
    def test_linkedin_permitido_endereco_local_bloqueado(self):
        self.assertTrue(f.url_permitida('https://br.linkedin.com/in/aluna'))
        self.assertFalse(f.url_permitida('http://127.0.0.1/a'))
    @patch.object(s.time,'sleep')
    def test_falha_consulta_nao_impede_proxima(self,sleep):
        repo=Repo(); calls=[]
        def busca(q,n):
            calls.append(q)
            return None if q=='falha' else []
        with patch.object(s,'consultas_leads',return_value=['falha','seguinte']):
            s.processar_instituicao(repo,repo.item,search_fn=busca,continuar_falhas=True)
        self.assertEqual(calls,['falha','seguinte'])
        self.assertEqual(repo.cp['status'],'erro')

class FormatosReaisTests(unittest.TestCase):
    def test_tabela_separa_aluno_do_orientador(self):
        linhas=[('Programa Mackenzie — alunos até 25/06/2025','pdf'),('Nome completo do aluno (a) Campus Curso Nome do Orientador','pdf'),('Fernanda Carolina dos Santos CCBS Higienópolis Nutrição','pdf'),('Andrea Carvalheiro Guerra Matias CCBS Mackenzie','pdf')]
        r=f.extrair_documento(linhas,'Universidade Presbiteriana Mackenzie','Mackenzie')
        self.assertEqual([x['nome'] for x in r],['Fernanda Carolina dos Santos'])
    def test_biografia_estudante_nao_inclui_coordenadora(self):
        html='<title>Jornada de Iniciação Científica Mackenzie</title><meta name="citation_publication_date" content="2025-11-06"><div>Geovanna Romeiro de Paiva, Universidade Presbiteriana Mackenzie</div><p>Graduanda do curso de nutrição</p><div>Juliana Masami Morimoto, Universidade Presbiteriana Mackenzie</div><p>Coordenadora do curso de nutrição</p>'
        r,_=f.ler_html(html,'https://eventoscopq.mackenzie.br/jornada','Universidade Presbiteriana Mackenzie','Mackenzie')
        self.assertEqual([x['nome'] for x in r],['Geovanna Romeiro de Paiva'])
    def test_lista_em_noticia_separa_professoras(self):
        html='<title>Mackenzie Nutrição</title><meta property="article:published_time" content="2025-05-19"><p>As alunas Ana Raquel Alves de Pontes, Sara Silva Santos e as professoras Ana Cristina Cabral e Rosana Farah, do curso de Nutrição da Universidade Presbiteriana Mackenzie, desenvolveram um projeto.</p>'
        r,_=f.ler_html(html,'https://mackenzie.br/noticia','Universidade Presbiteriana Mackenzie','Mackenzie')
        self.assertEqual({x['nome'] for x in r},{'Ana Raquel Alves de Pontes','Sara Silva Santos'})

    def test_biografia_em_edicao_antiga_nao_usa_republicacao(self):
        html='<title>Mackenzie Nutrição</title><meta name="citation_publication_date" content="2025-11-27"><p>v. 9 n. 12 (2017)</p><div>Ana Silva, Universidade Presbiteriana Mackenzie</div><p>Graduanda do curso de Nutrição</p>'
        r,_=f.ler_html(html,'https://revista.example/article','Universidade Presbiteriana Mackenzie','Mackenzie')
        self.assertEqual(r,[])

    def test_pagina_do_curso_nao_extrai_rotulos(self):
        html='<title>Nutrição Mackenzie</title><p>O aluno realiza TCC e estágio em 2026.</p><ul><li>Avaliações e Premiações</li><li>Currículo Lattes</li><li>Indústria de Alimentos</li><li>Área Comercial</li></ul>'
        r,_=f.ler_html(html,'https://mackenzie.br/nutricao','Universidade Presbiteriana Mackenzie','Mackenzie')
        self.assertEqual(r,[])
