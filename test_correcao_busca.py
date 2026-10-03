import unittest
from unittest.mock import patch, Mock
import fontes_academicas as f
import scraper as s
from test_scraper import Repo

class CorrecaoBuscaTests(unittest.TestCase):
    @patch.object(s.time,'sleep')
    def test_catalogo_generico_de_curso_nao_trava_captura(self,sleep):
        repo=Repo(); fonte=Mock(side_effect=RuntimeError('403'))
        r={'href':'https://carreiras.stoodi.com.br/cursos/nutricao-257/','title':'Curso de Nutrição','body':'Conheça faculdades e mensalidades de Nutrição.'}
        with patch.object(s,'consultas_leads',return_value=['a','b']):
            s.processar_instituicao(repo,repo.item,search_fn=lambda *a:[r],source_fn=fonte,limite_consultas=1)
        fonte.assert_not_called()
        self.assertEqual(repo.cp['status'],'processando')
        self.assertIsNone(repo.cp['ultimo_erro'])

    def test_alias_joinville_corrige_grafia_apenas_na_consulta(self):
        item={'instituicao':'Católica de Santa Catarina em Joinville','fonte_validacao':'SIGLA=Católica em Joinvile'}
        self.assertEqual(s.alias_instituicao(item),'Católica em Joinville')
        self.assertEqual(item['fonte_validacao'],'SIGLA=Católica em Joinvile')

    def test_alias_unopar_quando_nome_longo_nao_tem_sigla(self):
        self.assertEqual(s.alias_instituicao({'instituicao':'Centro Universitário Anhanguera Pitágoras Unopar de Campo Grande'}),'Unopar')
        self.assertEqual(s.alias_instituicao({'instituicao':'Centro Universitário Unopar','fonte_validacao':'SIGLA= '}),'Unopar')
        self.assertIsNone(s.alias_instituicao({'instituicao':'Universidade Teste'}))

    @patch.object(s.time,'sleep')
    def test_novos_criterios_anteriores_ao_checkpoint_nao_sao_pulados(self,sleep):
        repo=Repo(); chamadas=[]
        with patch.object(s,'consultas_leads',return_value=['a','b','c']):
            s.processar_instituicao(repo,repo.item,search_fn=lambda *a:[],limite_consultas=1)
        with patch.object(s,'consultas_leads',return_value=['a','novo1','b','novo2','c']):
            s.processar_instituicao(repo,repo.item,search_fn=lambda q,*a:chamadas.append(q) or [],limite_consultas=2)
        self.assertEqual(chamadas,['a','novo1'])

    @patch.object(s.time,'sleep')
    def test_janela_curta_retoma_e_nao_conclui_faculdade(self,sleep):
        repo=Repo(); chamadas=[]
        def busca(q,*a): chamadas.append(q); return []
        with patch.object(s,'consultas_leads',return_value=['a','b','c']):
            s.processar_instituicao(repo,repo.item,search_fn=busca,limite_consultas=1)
            self.assertEqual(repo.cp['status'],'processando')
            self.assertEqual(repo.cp['consulta_atual'],'b')
            s.processar_instituicao(repo,repo.item,search_fn=busca,limite_consultas=1)
        self.assertEqual(chamadas,['a','b'])
        self.assertEqual(repo.cp['indice_pesquisa'],2)
        self.assertEqual(repo.cp['status'],'processando')

    @patch.object(s.time,'sleep')
    def test_fonte_nova_nao_desloca_consulta_pendente(self,sleep):
        repo=Repo(); chamadas=[]
        with patch.object(s,'consultas_leads',return_value=['a','b','c']):
            s.processar_instituicao(repo,repo.item,search_fn=lambda *a:[],limite_consultas=1)
            repo.fontes_da_instituicao=lambda *a:['https://example.org/fonte']
            s.processar_instituicao(repo,repo.item,search_fn=lambda q,*a:chamadas.append(q) or [],limite_consultas=1)
        self.assertEqual(chamadas,['b'])
        self.assertEqual(repo.cp['total_pesquisas'],4)
        self.assertEqual(repo.cp['consulta_atual'],'c')

    def test_fila_nacional_le_checkpoints_em_lote_e_preserva_ordem(self):
        from types import SimpleNamespace
        dados=[{'id':1,'instituicao':'Faculdade A','estado':'SP'},
               {'id':2,'instituicao':'Faculdade B','estado':'CE'},
               {'id':3,'instituicao':'Faculdade C','estado':'SC'}]
        itens=s.agrupar_faculdades(dados)
        cps=[{'etapa':s.etapa_captacao_item(itens[0]),'status':'concluido'},
             {'etapa':s.etapa_captacao_item(itens[1]),'status':'erro'}]
        client=Mock(); client.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value=SimpleNamespace(data=dados)
        client.table.return_value.select.return_value.order.return_value.range.return_value.execute.return_value=SimpleNamespace(data=cps)
        repo=s.SupabaseRepo(client)
        with patch.object(repo,'controle_get') as individual:
            fila=repo.fila_nacional()
        individual.assert_not_called()
        self.assertEqual([x['instituicao'] for x in fila],['Faculdade C','Faculdade B'])
        self.assertEqual(client.table.call_count,2)
        cps[1]['status']='processando'
        self.assertEqual([x['instituicao'] for x in repo.fila_nacional()],['Faculdade B','Faculdade C'])

    def test_limite_429_nao_repete_requisicao(self):
        response=Mock(status_code=429)
        response.raise_for_status.side_effect=RuntimeError('429')
        requests=Mock(); requests.get.return_value=response
        with patch.dict('sys.modules',{'requests':requests}):
            with self.assertRaisesRegex(RuntimeError,'429'):
                f._carregar_url('https://example.org/fonte',None)
        self.assertEqual(requests.get.call_count,1)
        response.close.assert_called_once()

    def test_redirecionamento_login_instagram_nao_e_seguido(self):
        response=Mock(status_code=302,headers={'Location':'https://www.instagram.com/accounts/login/?next=perfil'})
        requests=Mock(); requests.get.return_value=response
        with patch.dict('sys.modules',{'requests':requests}):
            self.assertEqual(f._carregar_url('https://example.org/fonte',None),([],[]))
        self.assertEqual(requests.get.call_count,1)
        response.close.assert_called_once()

    def test_maquina1_nao_faz_requisicao_ao_instagram(self):
        requests=Mock()
        with patch.dict('sys.modules',{'requests':requests}):
            self.assertEqual(f._carregar_url('https://www.instagram.com/nutriformandos/',None),([],[]))
        requests.get.assert_not_called()

    @patch.object(s.time,'sleep')
    def test_maquina1_salva_evidencia_indexada_sem_acessar_perfil(self,sleep):
        repo=Repo()
        resultado={'href':'https://www.instagram.com/ana.nutricao/','title':'Ana Silva','body':'Graduanda em Nutrição, formando em 2026.'}
        fonte=Mock()
        with patch.object(s,'consultas_leads',return_value=['teste']):
            s.processar_instituicao(repo,repo.item,search_fn=lambda *a:[resultado],source_fn=fonte)
        fonte.assert_not_called()
        self.assertEqual([x['nome'] for x in repo.saved],['Ana Silva'])
        self.assertEqual(repo.cp['status'],'concluido')
        self.assertIsNone(repo.saved[0]['instagram'])

    def test_alternativa_tem_data_propria_e_preserva_url(self):
        u='https://jornal.org/noticia/recem-formada-em-nutricao-conquista-vaga'
        alternativa={'href':'https://universidade.edu.br/noticia/recem-formada-em-nutricao-conquista-vaga','title':'Recém-formada em Nutrição conquista vaga','body':'28 Jan 2025. Recém-formada em Nutrição, Ana Silva foi aprovada.'}
        def busca(q,*a): return [] if q.startswith('site:') else [alternativa]
        r,_=f.recuperar_fonte_na_busca(u,None,None,busca)
        self.assertEqual([x['nome'] for x in r],['Ana Silva'])
        self.assertEqual(r[0]['ano'],2025)
        self.assertEqual(r[0]['fonte_url'],alternativa['href'])
        alternativa['title']='Recém-formada em Nutrição ...'
        self.assertEqual(f.recuperar_fonte_na_busca(u,None,None,busca)[0][0]['nome'],'Ana Silva')
        alternativa['body']=alternativa['body'].replace('2025','2024')
        with patch.object(f,'carregar_fonte',return_value=([],[])):
            self.assertEqual(f.recuperar_fonte_na_busca(u,None,None,busca)[0],[])

    @patch.object(s.time,'sleep')
    def test_noticia_falecimento_nao_e_aberta_pela_captacao(self,sleep):
        repo=Repo()
        resultado={'href':'https://example.org/noticia','title':'Recém-formada em Nutrição morre em acidente','body':'2026 Ana Silva'}
        with patch.object(s,'consultas_leads',return_value=['teste']):
            with patch('fontes_academicas.carregar_fonte') as fonte:
                s.processar_instituicao(repo,repo.item,search_fn=lambda *a:[resultado])
                fonte.assert_not_called()
        self.assertEqual(repo.saved,[])

    def test_duplicado_sem_instituicao_nao_e_inserido(self):
        repo=Repo(); repo.lead_existe=lambda *a:True
        self.assertFalse(s.salvar_lead(repo,'Ana Silva',None,None,None,'Nutrição 2026','https://example.org',ano_forcado=2026,periodo_forcado='2026'))
        self.assertEqual(repo.saved,[])

    def test_mesmo_nome_e_fonte_com_faculdade_diferente_nao_duplica(self):
        repo=Repo(); repo.lead_da_fonte=lambda *a:{'id':1,'instituicao':None}
        self.assertFalse(s.salvar_lead(repo,'Ana Silva','Faculdade Teste',None,None,'Nutrição 2026','https://example.org',ano_forcado=2026,periodo_forcado='2026'))
        self.assertEqual(repo.saved,[])

    @patch.object(s.time,'sleep')
    def test_captacao_salva_indice_apos_503_e_preserva_pendencia(self,sleep):
        repo=Repo(); u='https://example.org/noticias/alunos-de-nutricao-criam-livro'
        def busca(q,*a):
            if q.startswith('site:'):
                return [{'href':u,'title':'Alunos de Nutrição criam livro','body':'2025. As alunas Ana Silva e as professoras Maria Souza, do curso de Nutrição da Universidade Teste, desenvolveram o livro.'}]
            return [{'href':u,'title':'Alunos de Nutrição criam livro'}]
        def fonte(*a): raise RuntimeError('503')
        with patch.object(s,'consultas_leads',return_value=['consulta']):
            s.processar_instituicao(repo,repo.item,search_fn=busca,source_fn=fonte)
        self.assertEqual([x['nome'] for x in repo.saved],['Ana Silva'])
        self.assertEqual(repo.cp['status'],'erro')
        self.assertIn('Fontes inacessíveis',repo.cp['ultimo_erro'])
        self.assertIn('índice público',repo.saved[0]['evidencia'])

    def test_lista_indexada_separa_alunas_das_professoras(self):
        r={'title':'Alunos de Nutrição criam e-book','body':'19 de maio de 2025. As alunas Ana Silva, Beatriz Santos e as professoras Maria Souza, do curso de Nutrição da Mackenzie, desenvolveram o livro.'}
        self.assertEqual([x['nome'] for x in f.extrair_resultado_busca(r,'Mackenzie')],['Ana Silva','Beatriz Santos'])
        r['body']=r['body'].replace('19 de maio de 2025. ','')
        self.assertEqual(f.extrair_resultado_busca(r,'Mackenzie'),[])

    def test_recuperacao_indexada_exige_mesma_materia(self):
        u='https://example.org/noticias/alunos-de-nutricao-criam-livro'
        r={'href':u,'title':'Nutrição','body':'2025. As alunas Ana Silva e as professoras Maria Souza, do curso de Nutrição, desenvolveram o livro.'}
        self.assertEqual(f.recuperar_fonte_na_busca(u,None,None,lambda *a:[r])[0][0]['nome'],'Ana Silva')
        r['href']='https://outra.org/noticias/alunos-de-nutricao-criam-livro'
        self.assertEqual(f.recuperar_fonte_na_busca(u,None,None,lambda *a:[r])[0][0]['nome'],'Ana Silva')
        r['href']='https://outra.org/noticias/noticia-de-outro-assunto'
        self.assertEqual(f.recuperar_fonte_na_busca(u,None,None,lambda *a:[r])[0],[])

    @patch.object(s.time,'sleep')
    def test_interrupcao_runner_retoma_consulta_sem_repetir_inicio(self,sleep):
        repo=Repo(); repo.cp={**repo.item,'status':'processando','indice_pesquisa':2,'total_pesquisas':3,'ultimo_erro':None,'leads_encontrados':4,'leads_salvos':2}
        chamadas=[]
        with patch.object(s,'consultas_leads',return_value=['a','b','c']):
            s.processar_instituicao(repo,repo.item,search_fn=lambda q,*a:chamadas.append(q) or [])
        self.assertEqual(chamadas,['c'])
        self.assertEqual(repo.cp['status'],'concluido')
        self.assertEqual(repo.cp['leads_encontrados'],4)
        self.assertEqual(repo.cp['leads_salvos'],2)

    @patch.object(s.time,'sleep')
    def test_fonte_pendente_nao_se_perde_na_interrupcao(self,sleep):
        repo=Repo()
        def fonte(*a): raise RuntimeError('503')
        def busca(q,*a):
            if q=='b': raise KeyboardInterrupt()
            return [{'href':'https://example.org/nutricao','title':'Nutrição formandos 2026'}]
        with patch.object(s,'consultas_leads',return_value=['a','b']):
            with self.assertRaises(KeyboardInterrupt): s.processar_instituicao(repo,repo.item,search_fn=busca,source_fn=fonte)
            self.assertIsNotNone(repo.cp['ultimo_erro'])
            chamadas=[]
            s.processar_instituicao(repo,repo.item,search_fn=lambda q,*a:chamadas.append(q) or [])
            self.assertEqual(chamadas,['a','b'])

    def test_noticia_falecimento_nao_captura_pessoa(self):
        linhas=[('Recém-formada em Nutrição morre em acidente','h1'),('08 Ago 2026','text'),('Recém-formada em Nutrição, Ana Diankelley Oliveira, foi identificada como a vítima.','p')]
        self.assertEqual(f.extrair_documento(linhas,None),[])

    def test_noticia_aluno_e_docentes_no_mesmo_paragrafo(self):
        linhas=[('28 Jan 2025','text'),('Recém-formada em Nutrição pela Unifev, Júlia Parpineli Bernini Silva, celebra sua aprovação. Os professores apoiaram a aluna. O reitor Osvaldo Gastaldon comemorou.','p')]
        r=f.extrair_documento(linhas,None,None)
        self.assertEqual([x['nome'] for x in r],['Júlia Parpineli Bernini Silva'])
        self.assertEqual(r[0]['ano'],2025)

    def test_data_editorial_apos_menu_permite_noticia_recente(self):
        linhas=[('Navegação '+str(i),'p') for i in range(35)]
        linhas += [('28 Jan 2025','div'),('Recém-formada em Nutrição pela Unifev, Júlia Parpineli Bernini Silva, celebra sua aprovação.','p')]
        r=f.extrair_documento(linhas,None)
        self.assertEqual([x['nome'] for x in r],['Júlia Parpineli Bernini Silva'])
        self.assertEqual(r[0]['ano'],2025)

    def test_post_institucional_identifica_recem_formada_no_corpo(self):
        resultado={'title':'UniFil - Instagram','body':'February 20, 2026: Recém-formada em Nutrição, Thais Camargo Prestes foi aprovada na Residência Multiprofissional em Oncologia.'}
        r=f.extrair_resultado_busca(resultado,'Mackenzie')
        self.assertEqual([x['nome'] for x in r],['Thais Camargo Prestes'])
        self.assertEqual(r[0]['ano'],2026)
        self.assertIsNone(r[0]['instituicao'])

    def test_post_de_terceiro_extrai_aluna_e_nao_autora_do_post(self):
        r=f.extrair_resultado_busca({'title':'Beatriz Moreti - LinkedIn','body':'A aluna do Curso de Nutrição da Universidade Presbiteriana Mackenzie, Un Hwa Moreira, foi premiada no Ganepão 2026.'},'Universidade Presbiteriana Mackenzie','Mackenzie')
        self.assertEqual([x['nome'] for x in r],['Un Hwa Moreira'])

    def test_noticia_recem_formada_sem_faculdade_pesquisada(self):
        html='<meta property="article:published_time" content="2025-02-20"><h1>Trajetória profissional</h1><p>Recém-formada em Nutrição pela Unifacisa, Carolina Nóbrega Dantas, compartilha sua trajetória.</p>'
        registros,_=f.ler_html(html,'https://example.org/noticia','Mackenzie')
        self.assertEqual([r['nome'] for r in registros],['Carolina Nóbrega Dantas'])
        self.assertIsNone(registros[0]['instituicao'])
        self.assertEqual(registros[0]['ano'],2025)

    @patch.object(s.time,'sleep')
    def test_tres_falhas_pausam_e_retomam_primeira_pendente(self,sleep):
        repo=Repo(); chamadas=[]
        def falha(q,*a): chamadas.append(q); return None
        with patch.object(s,'consultas_leads',return_value=['a','b','c','d']):
            self.assertFalse(s.processar_instituicao(repo,repo.item,search_fn=falha,continuar_falhas=True))
            self.assertEqual(chamadas,['a','b','c'])
            self.assertEqual(repo.cp['indice_pesquisa'],0)
            chamadas.clear()
            def recuperado(q,*a): chamadas.append(q); return []
            self.assertTrue(s.processar_instituicao(repo,repo.item,search_fn=recuperado,continuar_falhas=True))
            self.assertEqual(chamadas,['a','b','c','d'])

    def test_artigo_em_ingles_tenta_endereco_portugues(self):
        with patch.object(f,'_carregar_url',return_value=([{'nome':'Ana Silva'}],[])) as leitura:
            f.carregar_fonte('https://eventoscopq.mackenzie.br/jornada/en/article/view/2554','Mackenzie')
        self.assertEqual(leitura.call_args.args[0],'https://eventoscopq.mackenzie.br/jornada/pt_BR/article/view/2554')

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
        self.assertEqual(lidas,['https://www.mackenzie.br/alunos.pdf','https://outra.edu.br/alunos.pdf'])

    def test_busca_sem_faculdade_salva_sem_atribuir_mackenzie(self):
        registros=f.extrair_resultado_busca({'title':'Ana Silva','body':'Graduanda de Nutrição, formando em 2026.'},'Mackenzie')
        self.assertEqual(registros[0]['nome'],'Ana Silva')
        self.assertIsNone(registros[0]['instituicao'])
        repo=Repo()
        self.assertTrue(s.salvar_lead(repo,'Ana Silva',None,None,None,registros[0]['evidencia'],'https://example.org',ano_forcado=2026,periodo_forcado=registros[0]['periodo']))
        self.assertIsNone(repo.saved[0]['instituicao'])

    def test_nome_sem_nutricao_ou_periodo_nao_basta(self):
        for texto in ['Graduanda de Direito em 2026','Graduanda de Nutrição']:
            self.assertEqual(f.extrair_resultado_busca({'title':'Ana Silva','body':texto},'Mackenzie'),[])

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

class RepositorioXHTMLTests(unittest.TestCase):
    def test_tcc_com_declaracao_xml_decodificada(self):
        pagina = '<?xml version="1.0" encoding="UTF-8"?><html><head><title>TCC Nutrição</title><meta name="dc.date.issued" content="2025-12-06"><meta name="dc.contributor.author" content="Farias, Valesca Maria de"></head><body><p>TCC (graduação) - Universidade Federal de Santa Catarina, Nutrição.</p></body></html>'
        registros,_=f.ler_html(pagina,'https://repositorio.ufsc.br/handle/123456789/270578','Universidade Federal de Santa Catarina','UFSC')
        self.assertEqual([r['nome'] for r in registros],['Valesca Maria de Farias'])
        self.assertEqual(registros[0]['ano'],2025)

class DescobertaRepositorioTests(unittest.TestCase):
    def test_prioriza_autores_sem_prender_razao_social(self):
        q=s.consultas_leads("Universidade Federal de Santa Catarina","UFSC")
        self.assertEqual(q[0],"UFSC Nutrição 2025 TCC repositório")
        self.assertIn("UFSC Nutrição 2026 TCC repositório",q)
        self.assertTrue(any('"grupo de alunos"' in x for x in q))
        self.assertTrue(any('"formandos"' in x for x in q))
