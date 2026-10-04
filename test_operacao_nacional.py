import unittest
from unittest.mock import Mock, MagicMock, patch
import scraper as s
import enriquecimento as e

class OperacaoNacionalTests(unittest.TestCase):
    def test_faculdade_nova_tem_prioridade_sobre_retomada(self):
        nova = {'id': 1}
        antiga = {'id': 2, '_janela_encerrada': True, '_ultimo_checkpoint': '2026-10-01'}
        recente = {'id': 3, '_janela_encerrada': True, '_ultimo_checkpoint': '2026-10-04'}
        self.assertEqual(s.selecionar_janela([nova, recente, antiga], 2), [nova, antiga])
        self.assertEqual(s.selecionar_janela([nova], 0), [])

    def test_falha_nao_impede_segunda_faculdade(self):
        repo = Mock(); repo.fila_nacional.return_value = [{'id': 1}, {'id': 2}]
        with patch.object(s.SupabaseRepo, 'from_env', return_value=repo), patch.object(s, 'garantir_fila_oficial', return_value=True), patch.object(s, 'preparar_varredura_v58', return_value=True), patch.object(s, 'processar_instituicao', side_effect=[False, True]) as processar, patch.dict(s.stats, {k: 0 for k in s.stats}):
            s.executar()
            self.assertEqual(processar.call_count, 2)

    def test_host_instagram_falso_rejeitado(self):
        self.assertIsNone(e.extrair_instagram_url('https://instagram.com.example.org/ana'))
        self.assertEqual(e.extrair_instagram_url('https://www.instagram.com/ana.nutri/'), '@ana.nutri')

    def test_instagram_exige_identidade_curso_e_vinculo(self):
        lead = {'nome': 'Ana Silva', 'instituicao': 'Universidade Teste'}
        for texto in ['Maria Silva Nutrição Universidade Teste', 'Ana Silva Psicologia Universidade Teste', 'Ana Silva Nutrição Faculdade Outra', 'Mariana Silva Nutrição Universidade Teste']:
            self.assertFalse(e.resultado_compativel({'title': texto}, lead))
        self.assertTrue(e.resultado_compativel({'title': 'Ana Silva', 'body': 'Nutricionista Universidade Teste'}, lead))

    def test_nao_contatar_legado_bloqueia_maquina2(self):
        with patch.object(e, 'validar_candidato') as validar:
            e.processar_lead(Mock(), {'nome': 'Ana Silva', 'qualificado': False, 'não_contatar': True})
            validar.assert_not_called()

    def test_prazo_maquina2_preserva_lead_e_continua_lote(self):
        import sys
        from types import SimpleNamespace
        client = Mock(); q = client.table.return_value
        q.update.return_value=q; q.eq.return_value=q
        leads=[{'id': 1}, {'id': 2}]
        with patch.dict(sys.modules, {'ddgs': SimpleNamespace(DDGS=MagicMock())}), patch.object(e, 'conectar_banco', return_value=client), patch.object(e, 'buscar_pendentes', return_value=leads), patch.object(e, 'processar_lead', side_effect=[e.JanelaEncerrada(), None]) as processar, patch.dict(e.stats, {k:0 for k in e.stats}):
            e.executar()
            self.assertEqual(processar.call_count,2)
            self.assertEqual(q.update.call_count,2)
            self.assertEqual(q.update.call_args.args[0]['maquina2_tentativas'],1)

    def test_falha_maquina2_sinalizada_apos_preservar_lote(self):
        import sys
        from types import SimpleNamespace
        client=Mock(); q=client.table.return_value; q.update.return_value=q; q.eq.return_value=q
        with patch.dict(sys.modules, {'ddgs': SimpleNamespace(DDGS=MagicMock())}), patch.object(e, 'conectar_banco', return_value=client), patch.object(e, 'buscar_pendentes', return_value=[{'id':1},{'id':2}]), patch.object(e, 'processar_lead', side_effect=[RuntimeError('banco'),None]) as processar, patch.dict(e.stats, {k:0 for k in e.stats}):
            with self.assertRaises(RuntimeError): e.executar()
            self.assertEqual(processar.call_count,2)
            self.assertEqual(q.update.call_count,2)

    def test_excecao_inesperada_nao_interrompe_outras_faculdades(self):
        repo=Mock(); repo.fila_nacional.return_value=[{'id':1,'instituicao':'A'},{'id':2,'instituicao':'B'}]
        repo.controle_get.return_value={'indice_pesquisa':9,'total_pesquisas':20,'leads_salvos':3,'leads_encontrados':4,'consulta_atual':'TCC'}
        with patch.object(s.SupabaseRepo,'from_env',return_value=repo), patch.object(s,'garantir_fila_oficial',return_value=True), patch.object(s,'preparar_varredura_v58',return_value=True), patch.object(s,'processar_instituicao',side_effect=[ValueError('documento malformado'),True]) as processar, patch.dict(s.stats,{k:0 for k in s.stats}):
            s.executar()
            self.assertEqual(processar.call_count,2)
        dados=repo.controle_salvar.call_args.args[1]
        self.assertEqual(dados['indice_pesquisa'],9)
        self.assertEqual(dados['leads_salvos'],3)
        self.assertEqual(dados['status'],'erro')

    def test_falha_no_registro_do_erro_nao_interrompe_proxima(self):
        repo=Mock(); repo.fila_nacional.return_value=[{'id':1,'instituicao':'A'},{'id':2,'instituicao':'B'}]
        repo.atualizar_instituicao.side_effect=ConnectionError('banco')
        repo.controle_get.side_effect=ConnectionError('banco')
        with patch.object(s.SupabaseRepo,'from_env',return_value=repo), patch.object(s,'garantir_fila_oficial',return_value=True), patch.object(s,'preparar_varredura_v58',return_value=True), patch.object(s,'processar_instituicao',side_effect=[ValueError('site'),True]) as processar, patch.dict(s.stats,{k:0 for k in s.stats}):
            s.executar()
            self.assertEqual(processar.call_count,2)

    @patch.object(s.time,'sleep')
    def test_fonte_com_erro_pula_para_proximo_site_e_salva(self, dormir):
        from test_retomada_fontes import RepoPendencias
        import fontes_academicas as f
        repo=RepoPendencias()
        resultados=[{'href':'https://example.org/erro','title':'Universidade Teste Nutrição TCC 2026'}, {'href':'https://example.org/ok','title':'Universidade Teste Nutrição TCC 2026'}]
        registro={'nome':'Ana Silva','instituicao':'Universidade Teste','ano':2026,'periodo':'2026/1','evidencia':'Nutrição TCC 2026 Universidade Teste'}
        fonte=Mock(side_effect=[ValueError('HTML inválido'),([registro],[])])
        with patch.object(s,'consultas_leads',return_value=['TCC']), patch.object(f,'recuperar_fonte_na_busca',return_value=([],[])), patch.dict(s.stats,{k:0 for k in s.stats}):
            s.processar_instituicao(repo,repo.item,search_fn=lambda *a:resultados,source_fn=fonte)
        self.assertEqual(fonte.call_count,2)
        self.assertEqual(repo.saved[0]['nome'],'Ana Silva')
        self.assertIn('https://example.org/erro',repo.pendentes)

    @patch.object(s.time,'sleep')
    def test_falha_isolada_retoma_consulta_sem_reiniciar(self, dormir):
        from test_scraper import Repo
        repo=Repo()
        repo.cp={'instituicao':'Universidade Teste','estado':'SP','status':'erro','ultimo_erro':'Falha isolada na faculdade: ValueError','indice_pesquisa':1,'total_pesquisas':3,'consulta_atual':'b','leads_salvos':2}
        chamadas=[]
        with patch.object(s,'consultas_leads',return_value=['a','b','c']):
            s.processar_instituicao(repo,repo.item,search_fn=lambda q,*a:chamadas.append(q) or [],limite_consultas=1)
        self.assertEqual(chamadas,['b'])
        self.assertEqual(repo.cp['indice_pesquisa'],2)
        self.assertEqual(repo.cp['leads_salvos'],2)

    def test_primeira_passagem_nao_reserva_vaga_para_faculdade_antiga(self):
        antigas=[{'id':1,'_ultimo_checkpoint':'2026-10-01','_janela_encerrada':True}]
        novas=[{'id':2},{'id':3}]
        self.assertEqual(s.selecionar_janela(antigas+novas,2),novas)

    def test_sem_faculdade_nova_retomada_alterna_por_ultima_visita(self):
        itens=[{'id':1,'_ultimo_checkpoint':'2026-10-04'}, {'id':2,'_ultimo_checkpoint':'2026-10-01'}]
        self.assertEqual([i['id'] for i in s.selecionar_janela(itens,2)],[2,1])

    @patch.object(s.time,'sleep')
    def test_fonte_concluida_nao_reabre_na_proxima_janela(self, dormir):
        from test_retomada_fontes import RepoPendencias
        repo=RepoPendencias(); url='https://example.org/nutricao'
        repo.fontes_concluidas=lambda item: repo.concluidas
        resultados=[{'href':url,'title':'Universidade Teste Nutrição alunos 2026'}]
        fonte=Mock(return_value=([],[]))
        with patch.object(s,'consultas_leads',return_value=['a','b','c']), patch.dict(s.stats,{k:0 for k in s.stats}):
            s.processar_instituicao(repo,repo.item,search_fn=lambda *a:resultados,source_fn=fonte,limite_consultas=1)
            self.assertIn(url,repo.concluidas)
            s.processar_instituicao(repo,repo.item,search_fn=lambda *a:resultados,source_fn=fonte,limite_consultas=1)
        self.assertEqual(fonte.call_count,1)
        self.assertEqual(repo.cp['indice_pesquisa'],2)

    def test_repositorio_de_outra_faculdade_nao_reprocessa_mesma_lista(self):
        repo=s.SupabaseRepo(Mock())
        repo._instituicoes_por_dominio_alias={'univag':{'centro universitario de varzea grande'}}
        resultado={'href':'https://www.repositoriodigital.univag.com.br/index.php/nutri/issue/view/4','title':'Nutrição TCC 2026'}
        self.assertTrue(repo.resultado_de_outra_faculdade(resultado,'Centro Universitário Cambury','Cambury'))
        self.assertFalse(repo.resultado_de_outra_faculdade(resultado,'Centro Universitário de Várzea Grande','Univag'))
        resultado['body']='Trabalho colaborativo de Nutrição Cambury 2026'
        self.assertFalse(repo.resultado_de_outra_faculdade(resultado,'Centro Universitário Cambury','Cambury'))

    def test_dominio_desconhecido_continua_disponivel_para_descoberta(self):
        repo=s.SupabaseRepo(Mock())
        self.assertFalse(repo.resultado_de_outra_faculdade({'href':'https://revista.example.org/tcc'},'Faculdade A','FA'))
