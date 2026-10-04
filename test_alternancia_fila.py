import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import scraper as s
from test_scraper import Repo

class AlternanciaTests(unittest.TestCase):
    def test_janela_encerrada_cede_vez_sem_perder_retomada(self):
        dados=[{'id':1,'instituicao':'Faculdade A','estado':'SP'}, {'id':2,'instituicao':'Faculdade B','estado':'CE'}]
        itens=s.agrupar_faculdades(dados)
        cps=[{'etapa':s.etapa_captacao_item(itens[0]),'status':'processando','atualizado_em':'2026-10-04', 'ultimo_erro':'Janela encerrada; próxima consulta preservada'}]
        client=Mock()
        client.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value=SimpleNamespace(data=dados)
        client.table.return_value.select.return_value.order.return_value.range.return_value.execute.return_value=SimpleNamespace(data=cps)
        repo=s.SupabaseRepo(client)
        self.assertEqual([i['instituicao'] for i in repo.fila_nacional()],['Faculdade B','Faculdade A'])
        cps[0]['ultimo_erro']=None
        self.assertEqual([i['instituicao'] for i in repo.fila_nacional()],['Faculdade A','Faculdade B'])

    @patch.object(s.time,'sleep')
    def test_janela_encerrada_retoma_proxima_consulta(self,sleep):
        repo=Repo(); chamadas=[]
        with patch.object(s,'consultas_leads',return_value=['a','b','c']):
            s.processar_instituicao(repo,repo.item,search_fn=lambda q,*a:chamadas.append(q) or [],limite_consultas=1)
            self.assertEqual(repo.cp['ultimo_erro'],'Janela encerrada; próxima consulta preservada')
            s.processar_instituicao(repo,repo.item,search_fn=lambda q,*a:chamadas.append(q) or [],limite_consultas=1)
        self.assertEqual(chamadas,['a','b'])
        self.assertEqual(repo.cp['indice_pesquisa'],2)
