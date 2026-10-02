import unittest
from unittest.mock import patch
import fontes_academicas as f
import scraper as s
from test_scraper import Repo

class CorrecaoBuscaTests(unittest.TestCase):
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
