import unittest
from unittest.mock import Mock, patch
import scraper as s
from test_retomada_fontes import RepoPendencias

class OrcamentoTests(unittest.TestCase):
    @patch.object(s.time,'sleep')
    def test_limite_preserva_urls_nao_lidas_e_proxima_consulta(self,sleep):
        repo=RepoPendencias(); fonte=Mock()
        resultados=[{'href':'https://example.org/a','title':'Nutrição alunos 2026'}, {'href':'https://example.org/b','title':'Nutrição alunos 2026'}]
        with patch.object(s,'consultas_leads',return_value=['a','b','c']), patch.object(s.time,'monotonic',side_effect=[0,0,2,2,2]):
            s.processar_instituicao(repo,repo.item,search_fn=lambda *a:resultados,source_fn=fonte,limite_consultas=3,prazo=1)
        fonte.assert_not_called()
        self.assertEqual(set(repo.fontes_pendentes(repo.item)),{'https://example.org/a','https://example.org/b'})
        self.assertEqual(repo.cp['indice_pesquisa'],1)
        self.assertEqual(repo.cp['consulta_atual'],'b')
        self.assertEqual(repo.cp['ultimo_erro'],'Janela com fontes pendentes; repetir ao finalizar')

    def test_retomada_de_fontes_respeita_limite_sem_concluir_indevidamente(self):
        repo=RepoPendencias(); repo.pendentes={'https://example.org/a':'503'}; fonte=Mock()
        with patch.object(s.time,'monotonic',return_value=2):
            s.retentar_fontes_pendentes(repo,repo.item,{'total_pesquisas':226},fonte,6,prazo=1)
        fonte.assert_not_called()
        self.assertEqual(repo.fontes_pendentes(repo.item),['https://example.org/a'])
        self.assertEqual(repo.cp['status'],'erro')
        self.assertEqual(repo.cp['indice_pesquisa'],226)
