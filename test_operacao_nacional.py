import unittest
from unittest.mock import Mock, MagicMock, patch
import scraper as s
import enriquecimento as e

class OperacaoNacionalTests(unittest.TestCase):
    def test_chave_pessoa_ignora_acento_pontuacao_particulas_e_inicial_final(self):
        self.assertEqual(s.chave_nome_pessoa("Victoria Barbosa d Avila C"),
                         s.chave_nome_pessoa("Victoria Barbosa d'Ávila"))

    def test_extrator_rejeita_titulo_instituicao_e_secao_como_nome(self):
        from fontes_academicas import pessoa
        for texto in ("Universidade Presbiteriana Mackenzie", "Currículo Lattes",
                      "Avaliações e Premiações", "Indústria de Alimentos",
                      "Mostra de TCC Nutrição"):
            self.assertIsNone(pessoa(texto), texto)

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

    def test_instagram_aceita_outros_perfis_ligados_a_nutricao(self):
        lead = {'nome': 'Ana Silva', 'instituicao': 'Universidade Teste'}
        self.assertTrue(e.resultado_compativel(
            {'title': 'Maria Silva | Nutrição', 'body': 'Nutricionista'}, lead))
        self.assertTrue(e.resultado_compativel(
            {'title': 'Ana Silva | Nutrição Faculdade Outra'}, lead))
        self.assertTrue(e.resultado_compativel(
            {'title': 'Mariana Silva | Nutrição'}, lead))
        self.assertFalse(e.resultado_compativel(
            {'title': 'Ana Silva | Psicologia Universidade Teste'}, lead))
        self.assertFalse(e.resultado_compativel(
            {'title': 'Maria Silva | Odontologia Universidade Teste'}, lead))

    def test_nao_contatar_legado_bloqueia_maquina2(self):
        with patch.object(e, 'validar_candidato') as validar:
            e.processar_lead(Mock(), {'nome': 'Ana Silva', 'qualificado': False, 'não_contatar': True})
            validar.assert_not_called()

    def test_prazo_maquina2_preserva_lead_e_continua_lote(self):
        import sys
        from types import SimpleNamespace
        client = Mock()
        leads=[{'id': 1}, {'id': 2}]
        with patch.dict(sys.modules, {'ddgs': SimpleNamespace(DDGS=MagicMock())}), patch.object(e, 'conectar_banco', return_value=client), patch.object(e, 'buscar_pendentes', return_value=leads), patch.object(e, 'processar_lead', side_effect=[e.JanelaEncerrada(), None]) as processar, patch.object(e, 'salvar_cursor_m2') as salvar_cursor, patch.object(e, 'registrar_verificacao_m2') as registrar, patch.dict(e.stats, {k:0 for k in e.stats}):
            e.executar()
            self.assertEqual(processar.call_count,2)
            self.assertEqual([c.args for c in salvar_cursor.call_args_list],[(1,),(2,)])
            registrar.assert_called_once_with(leads[1])
            self.assertNotIn(unittest.mock.call('leds'), client.table.call_args_list)

    def test_falha_maquina2_sinalizada_apos_preservar_lote(self):
        import sys
        from types import SimpleNamespace
        client=Mock()
        leads=[{'id':1},{'id':2}]
        with patch.dict(sys.modules, {'ddgs': SimpleNamespace(DDGS=MagicMock())}), patch.object(e, 'conectar_banco', return_value=client), patch.object(e, 'buscar_pendentes', return_value=leads), patch.object(e, 'processar_lead', side_effect=[RuntimeError('banco'),None]) as processar, patch.object(e, 'salvar_cursor_m2') as salvar_cursor, patch.object(e, 'registrar_verificacao_m2') as registrar, patch.dict(e.stats, {k:0 for k in e.stats}):
            with self.assertRaises(RuntimeError): e.executar()
            self.assertEqual(processar.call_count,2)
            self.assertEqual([c.args for c in salvar_cursor.call_args_list],[(1,),(2,)])
            registrar.assert_called_once_with(leads[1])
            self.assertNotIn(unittest.mock.call('leds'), client.table.call_args_list)

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

    def test_fila_separa_mesma_faculdade_por_estado(self):
        dados = [
            {"id": 1, "instituicao": "Universidade Exemplo", "estado": "RJ"},
            {"id": 2, "instituicao": "Universidade Exemplo", "estado": "SP"},
            {"id": 3, "instituicao": "Universidade Exemplo", "estado": "SP", "cidade": "Campinas"},
        ]
        fila = s.agrupar_faculdades(dados)
        self.assertEqual([(i["estado"], i["id"]) for i in fila], [("SP", 2), ("RJ", 1)])

    def test_janela_esgota_estado_atual_antes_do_proximo(self):
        sp_nova = {"id": 1, "estado": "SP", "instituicao": "Faculdade SP"}
        sp_retomada = {"id": 2, "estado": "SP", "instituicao": "Outra SP", "_ultimo_checkpoint": "2026-10-15"}
        rj_nova = {"id": 3, "estado": "RJ", "instituicao": "Faculdade RJ"}
        self.assertEqual(s.selecionar_janela([rj_nova, sp_retomada, sp_nova], 4),
                         [sp_nova, sp_retomada])

    def test_consultas_incluem_nome_do_estado(self):
        consultas = s.consultas_leads("Universidade Exemplo", uf="SP")
        self.assertTrue(any("São Paulo" in consulta for consulta in consultas))

    def test_cursor_persistente_avanca_e_nao_volta_a_sp(self):
        class RepoCursor:
            checkpoint = None

            def controle_get(self, etapa):
                return self.checkpoint

            def controle_salvar(self, etapa, dados):
                self.checkpoint = dict(dados, etapa=etapa)

        repo = RepoCursor()
        sp = {"id": 1, "estado": "SP", "instituicao": "Faculdade SP"}
        rj = {"id": 2, "estado": "RJ", "instituicao": "Faculdade RJ"}
        self.assertEqual(s.fila_estado_atual(repo, [sp, rj]), [sp])
        self.assertEqual(repo.checkpoint["estado"], "SP")

        self.assertEqual(s.fila_estado_atual(repo, [rj]), [rj])
        self.assertEqual(repo.checkpoint["estado"], "RJ")

        sp_nova = {"id": 3, "estado": "SP", "instituicao": "Nova Faculdade SP"}
        self.assertEqual(s.fila_estado_atual(repo, [sp_nova, rj]), [rj])
        self.assertEqual(repo.checkpoint["estado"], "RJ")

    def test_cursor_marca_roteiro_concluido_quando_fila_esvazia(self):
        class RepoCursor:
            checkpoint = None

            def controle_get(self, etapa):
                return self.checkpoint

            def controle_salvar(self, etapa, dados):
                self.checkpoint = dict(dados, etapa=etapa)

        repo = RepoCursor()
        self.assertEqual(s.fila_estado_atual(repo, []), [])
        self.assertEqual(repo.checkpoint["status"], "concluido")
        sp = {"id": 1, "estado": "SP", "instituicao": "Nova Faculdade SP"}
        self.assertEqual(s.fila_estado_atual(repo, [sp]), [])
