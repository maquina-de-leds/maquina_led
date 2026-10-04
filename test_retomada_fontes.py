import unittest
from unittest.mock import patch
import scraper as s
import fontes_academicas as f
from test_scraper import Repo

class RepoPendencias(Repo):
    def __init__(self):
        super().__init__(); self.pendentes={}; self.concluidas=set()
    def registrar_pendencia_fonte(self,item,url,erro=None,concluida=False,somente_nova=False):
        if somente_nova and (url in self.pendentes or url in self.concluidas): return
        if concluida:
            self.pendentes.pop(url,None); self.concluidas.add(url)
        else: self.pendentes[url]=erro
    def fontes_pendentes(self,item): return list(self.pendentes)

class RetomadaTests(unittest.TestCase):
    @patch.object(s.time,'sleep')
    def test_503_retoma_url_sem_repetir_buscas(self,sleep):
        repo=RepoPendencias(); url='https://example.org/nutricao'
        def falha(*a): raise RuntimeError('503')
        with patch.object(s,'consultas_leads',return_value=['a','b']):
            s.processar_instituicao(repo,repo.item,search_fn=lambda *a:[{'href':url,'title':'Nutrição alunos 2026'}],source_fn=falha)
            self.assertEqual(repo.cp['indice_pesquisa'],2)
            self.assertEqual(repo.cp['status'],'erro')
            def nao_buscar(*a): self.fail('Não deve repetir buscas concluídas')
            s.processar_instituicao(repo,repo.item,search_fn=nao_buscar,source_fn=lambda *a:([],[]))
        self.assertEqual(repo.cp['status'],'concluido')
        self.assertEqual(repo.fontes_pendentes(repo.item),[])

    def test_fonte_persistente_mantem_progresso_sem_apagar_alunos(self):
        repo=RepoPendencias(); repo.pendentes={'https://example.org/nutricao':'403'}
        cp={'total_pesquisas':226,'leads_encontrados':34,'leads_salvos':34}
        def falha(*a): raise RuntimeError('403')
        s.retentar_fontes_pendentes(repo,repo.item,cp,falha,6)
        self.assertEqual(repo.cp['indice_pesquisa'],226)
        self.assertEqual(repo.cp['leads_salvos'],34)
        self.assertEqual(repo.cp['status'],'erro')

    def test_links_da_retomada_nao_se_perdem(self):
        repo=RepoPendencias(); repo.pendentes={'https://example.org/a':'503'}
        s.retentar_fontes_pendentes(repo,repo.item,{'total_pesquisas':2},lambda *a:([],['https://example.org/b']),6)
        self.assertEqual(repo.fontes_pendentes(repo.item),['https://example.org/b'])
        self.assertEqual(repo.cp['status'],'erro')

    def test_conformidade_legal_nao_e_nome(self):
        self.assertIsNone(f.pessoa('Conformidade Legal'))
        self.assertEqual(f.pessoa('Gabriella Lara Martins'),'Gabriella Lara Martins')
