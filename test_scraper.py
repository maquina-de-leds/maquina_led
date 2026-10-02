import unittest
from unittest.mock import patch
import ast
from pathlib import Path
import scraper as s
import fontes_academicas as f

class Repo:
    def __init__(self):
        self.cp=None
        self.item=dict(id=1,instituicao='Universidade Teste',estado='SP')
        self.saved=[]
    def controle_get(self,*args): return self.cp
    def controle_salvar(self,etapa,data): self.cp=data.copy()
    def atualizar_instituicao(self,iid,**data): self.item.update(data)
    def lead_existe(self,*args): return False
    def instagram_usado(self,*args): return False
    def inserir_lead(self,data): self.saved.append(data)

class FontesTests(unittest.TestCase):
    def test_noticia_multicurso_lista_por_rotulo(self):
        out=self.extract('''<title>Universidade Teste — Outorga de grau</title><meta property="article:published_time" content="2026-04-29"><p>Publicado em 29/04/2026</p>
        <p>Formandos receberam a outorga de grau em abril de 2026.</p><p>Psicologia: Ana Silva.</p>
        <p>Nutrição: Melissa Gomes da Silva.</p>''')
        self.assertEqual([x['nome'] for x in out],['Melissa Gomes da Silva'])
        self.assertEqual(out[0]['ano'],2026)
    def test_noticia_oradora_explicitamente_do_curso(self):
        out=self.extract('''<title>Universidade Teste — Colação de grau</title><p>Turma do semestre 2026.1.</p>
        <p>Após a cerimônia, a Giovanna Kimie, do Curso de Nutrição, fez o discurso como oradora dos formandos.
        O formando Paulo César, do Curso de Administração, fez o juramento.</p>''')
        self.assertEqual([x['nome'] for x in out],['Giovanna Kimie'])
        self.assertEqual(out[0]['periodo'],'2026/1')
    def test_semestre_explicito_em_paragrafo_longo(self):
        self.assertEqual(f.periodo_academico('Colação de grau para 234 formandos de 23 cursos de graduação na modalidade presencial e a distância, que concluíram no semestre 2026.1.'),(2026,'2026/1'))
    def test_rotulo_de_curso_em_secao_docente_nao_salva_professor(self):
        out=self.extract('''<title>Universidade Teste — Colação de grau Nutrição 2026</title>
        <h2>Professores homenageados</h2><p>Nutrição: Maria Silva.</p>''')
        self.assertEqual(out,[])
    def test_ano_de_publicacao_sozinho_nao_comprova_turma(self):
        out=self.extract('''<title>Universidade Teste — Outorga de grau</title><meta property="article:published_time" content="2026-04-29"><p>Publicado em 29/04/2026</p>
        <p>Formandos receberam a outorga de grau.</p><p>Nutrição: Ana Silva.</p>''')
        self.assertEqual(out,[])
    def extract(self,html):
        return f.ler_html(html,'https://universidade.edu.br/turmas','Universidade Teste')[0]
    def test_lista_nutricao_exclui_professores_e_outro_curso(self):
        html='''<title>Universidade Teste</title><h1>Formandos de Educação Física e Nutrição</h1>
        <p>Colação de grau em abril de 2025.</p>
        <p>Professora Maria Docente, paraninfa.</p>
        <p>Os formandos de Educação Física são: Pedro Santos; João Lima.</p>
        <p>Os formandos de Nutrição que irão colar grau são: Ana Silva; Bruna Souza; e Carla Ribeiro.</p>'''
        out=self.extract(html)
        self.assertEqual([x['nome'] for x in out],['Ana Silva','Bruna Souza','Carla Ribeiro'])
        self.assertEqual({x['ano'] for x in out},{2025})
    def test_ano_da_turma_prevalece_publicacao(self):
        html='''<title>Universidade Teste — Formatura Nutrição</title><p>Publicado em 13/03/2026</p>
        <p>Curso de Nutrição, referente ao 2º semestre de 2025.</p>
        <p>São formandos desta turma: Ana Silva, Bruna Souza e Carla Ribeiro.</p>'''
        out=self.extract(html)
        self.assertEqual(len(out),3)
        self.assertEqual({x['periodo'] for x in out},{'2025/2'})
    def test_listas_por_secao_sem_contaminar_ano_ou_curso(self):
        out=self.extract('''<title>Universidade Teste</title><h2>Formandos Nutrição 2025.1</h2><ul><li>Ana Silva</li></ul>
        <h2>Formandos Nutrição 2024.2</h2><ul><li>Bruna Souza</li></ul>
        <h2>Formandos Psicologia 2026.2</h2><ul><li>Carla Ribeiro</li></ul>
        <h2>Formandos Nutrição 2026.2</h2><ul><li>Daniel Santos</li></ul>''')
        self.assertEqual([(x['nome'],x['periodo']) for x in out],[('Ana Silva','2025/1'),('Daniel Santos','2026/2')])
    def test_instagram_pessoal_apenas_quando_associado(self):
        out=self.extract('''<title>Universidade Teste</title><h2>Formandos Nutrição 2026/1</h2>
        <ul><li>Ana Silva <a href="https://instagram.com/ana.nutri">Instagram</a></li><li>Bruna Souza</li></ul>
        <footer><a href="https://instagram.com/universidade">Instagram</a></footer>''')
        self.assertEqual(out[0]['instagram'],'@ana.nutri')
        self.assertIsNone(out[1]['instagram'])
    def test_instagram_nao_e_compartilhado_por_lista(self):
        self.assertIsNone(f.instagram_associado('Ana Silva; Bruna Souza @turma','Ana Silva'))
    def test_tcc_autores_e_orientadores_separados(self):
        out=self.extract('''<title>Universidade Teste</title><h1>TCC Nutrição 2026.1</h1>
        <p>Autores: Ana Silva e Bruna Souza</p><p>Orientadora: Maria Docente</p>''')
        self.assertEqual([x['nome'] for x in out],['Ana Silva','Bruna Souza'])
        self.assertTrue(all('TCC' in x['evidencia'] for x in out))
    def test_metadados_de_repositorio(self):
        html='''<title>Universidade Teste — TCC Nutrição</title>
        <meta name="dc.contributor.author" content="Silva, Ana">
        <meta name="dc.date.issued" content="2025-09-10">'''
        self.assertEqual([x['nome'] for x in self.extract(html)],['Ana Silva'])
    def test_vinculo_ou_data_ausentes_nao_inventam_lead(self):
        self.assertEqual(self.extract('<h1>Formandos Nutrição 2025</h1><li>Ana Silva</li>'),[])
        self.assertEqual(self.extract('<title>Universidade Teste</title><h1>Formandos Nutrição</h1><li>Ana Silva</li>'),[])
    def test_titulo_documento_nao_e_pessoa(self):
        for title in ['Trabalho de Conclusão','Alimentação Saudável','Mostra De TCC','Consumo nutricional']:
            self.assertIsNone(f.pessoa(title))
    def test_pdf_texto_estruturado(self):
        lines=[('Universidade Teste','pdf'),('Formandos Nutrição 2026.2','pdf'),('1 - Ana Silva','pdf'),('2 - Bruna Souza','pdf')]
        self.assertEqual([x['nome'] for x in f.extrair_documento(lines,'Universidade Teste')],['Ana Silva','Bruna Souza'])
    def test_pdf_parser(self):
        from pypdf import PdfWriter
        import io
        pdf=PdfWriter(); pdf.add_blank_page(width=100,height=100)
        data=io.BytesIO(); pdf.write(data)
        self.assertEqual(f.ler_pdf(data.getvalue(),'Universidade Teste'),([],[]))
    def test_links_pdf_e_bloqueio(self):
        _, links=f.ler_html('<a href="/nutricao-2025.pdf">Lista</a><a href="https://linkedin.com/in/aluno">Pessoa</a>', 'https://universidade.edu.br/turma','Universidade Teste')
        self.assertEqual(links,['https://universidade.edu.br/nutricao-2025.pdf'])
        for url in ['http://127.0.0.1/x']:
            self.assertFalse(f.url_permitida(url))

class FluxoTests(unittest.TestCase):
    def test_nome_existente_com_sigla_da_faculdade_nao_duplica(self):
        repo=Repo()
        repo.instituicao_de_lead_por_alias=lambda nome,alias:'UniAteneu' if alias=='UNIATENEU' else None
        self.assertFalse(s.salvar_lead(repo,'Giovanna Kimie','Centro Universitário Ateneu','Fortaleza','CE','Nutrição 2026/1','https://uniateneu.edu.br/fonte',ano_forcado=2026,periodo_forcado='2026/1',instituicao_alias='UNIATENEU'))
        self.assertEqual(repo.saved,[])
        self.assertEqual(s.stats['duplicados'],1)
    def setUp(self):
        for key in s.stats: s.stats[key]=0
    def test_consultas_institucionais(self):
        qs=s.consultas_leads('Universidade Teste','UT')
        self.assertTrue(any('site:linkedin.com/in' in q for q in qs))
        for year in (2025,2026):
            for signal in ('"formandos"','"TCC"','"turma"'):
                self.assertTrue(any(signal in q and str(year) in q for q in qs))
    @patch.object(s.time,'sleep')
    def test_segunda_varredura_completa(self,sleep):
        repo=Repo(); calls=[]
        def search(q,*args): calls.append(q); return []
        s.processar_instituicao(repo,repo.item.copy(),search,lambda *args:([],[]))
        first=calls.copy(); calls.clear()
        s.processar_instituicao(repo,repo.item.copy(),search,lambda *args:([],[]))
        self.assertEqual(calls,first)
        self.assertEqual(repo.item['status'],'concluido')
    @patch.object(s.time,'sleep')
    def test_salva_nome_com_e_sem_instagram_e_fonte(self,sleep):
        repo=Repo()
        def source(url,*args):
            if 'linkedin.com' in url: return [],[]
            return [dict(nome='Ana Silva',ano=2025,periodo='2025/2',instagram='@ana.nutri',evidencia='Turma Nutrição 2025/2 Ana Silva'),dict(nome='Bruna Souza',ano=2026,periodo='2026/2',instagram=None,evidencia='TCC Nutrição 2026/2 Bruna Souza')],[]
        results=[dict(href='https://universidade.edu.br/turma'),dict(href='https://linkedin.com/in/aluno')]
        with patch.object(s,'consultas_leads',return_value=['test']):
            s.processar_instituicao(repo,repo.item.copy(),lambda *args:results,source)
        self.assertEqual(len(repo.saved),2)
        self.assertEqual(repo.saved[0]['instagram'],'@ana.nutri')
        self.assertIsNone(repo.saved[1]['instagram'])
        self.assertEqual(repo.saved[1]['proxima_acao'],'buscar_instagram')
        self.assertEqual(repo.saved[0]['fonte_url'],'https://universidade.edu.br/turma')
    @patch.object(s.time,'sleep')
    def test_fontes_inacessiveis_nao_concluem_instituicao(self,sleep):
        repo=Repo()
        def fail(*args): raise RuntimeError('403')
        with patch.object(s,'consultas_leads',return_value=['test']):
            s.processar_instituicao(repo,repo.item.copy(),lambda *args:[dict(href='https://universidade.edu.br/turma')],fail)
        self.assertEqual(repo.item['status'],'erro')
        self.assertEqual(repo.cp['indice_pesquisa'],0)
    @patch.object(s.time,'sleep')
    def test_busca_indisponivel(self,sleep):
        def fail(*args): raise RuntimeError('No results found')
        self.assertIsNone(s.buscar_web('test',fetch_fn=fail))
    @patch.object(s.time,'sleep')
    def test_cidade_da_fila_nao_e_atribuida_sem_evidencia(self,sleep):
        for contexto,expected in [('Colação em Sorocaba 2026/1',('Não identificado',None)),('Colação em Itu 2026/1',('Itu','SP'))]:
            repo=Repo();item=dict(repo.item,cidade='Itu')
            record=dict(nome='Ana Silva',ano=2026,periodo='2026/1',evidencia='Formanda de Nutrição 2026/1',contexto_academico=contexto)
            with patch.object(s,'consultas_leads',return_value=['test']):
                s.processar_instituicao(repo,item,lambda *a:[dict(href='https://universidade.edu.br/turma')],lambda *a:([record],[]))
            self.assertEqual((repo.saved[0]['cidade'],repo.saved[0]['estado']),expected)
    def test_maquina2_nao_chama_busca_linkedin(self):
        tree=ast.parse(Path(__file__).with_name('enriquecimento.py').read_text())
        self.assertFalse(any(isinstance(x,ast.Call) and isinstance(x.func,ast.Name) and x.func.id=='buscar_linkedin' for x in ast.walk(tree)))


class MunicipiosTests(unittest.TestCase):
    def arquivo_ead(self, linhas):
        import tempfile,zipfile
        tmp=tempfile.NamedTemporaryFile(suffix='.zip')
        with zipfile.ZipFile(tmp.name,'w') as z:
            z.writestr('MICRODADOS_ED_SUP_IES_2024.CSV','CO_IES;NO_IES;SG_IES\n1;Universidade Teste;UT\n2;Faculdade Outra;FO\n')
            z.writestr('MICRODADOS_CADASTRO_CURSOS_2024.CSV','CO_IES;SG_UF;NO_MUNICIPIO;NO_CINE_ROTULO;NU_ANO_CENSO;TP_MODALIDADE_ENSINO\n'+linhas)
        return tmp
    def test_sede_ead_nao_inventa_municipio_quando_polo_existe(self):
        with self.arquivo_ead('1;;;Nutrição;2024;2\n1;SP;Itu;Nutrição;2024;2\n') as tmp:
            rows=s.ler_fila_inep_zip(tmp.name)
        self.assertEqual([(r['estado'],r['cidade']) for r in rows],[('SP','Itu')])
    def test_sede_ead_sem_oferta_municipal_exige_conferencia(self):
        with self.arquivo_ead('1;;;Nutrição;2024;2\n2;SP;Itu;Nutrição;2024;1\n') as tmp:
            with self.assertRaises(RuntimeError):s.ler_fila_inep_zip(tmp.name)
    def test_fila_usa_municipio_do_curso_e_nao_sede(self):
        import tempfile,zipfile
        ies='CO_IES;NO_IES;SG_IES;NO_MUNICIPIO_IES\n1;Universidade Teste;UT;Capital\n'
        cursos='CO_IES;SG_UF;NO_MUNICIPIO;NO_CINE_ROTULO;NU_ANO_CENSO\n1;SP;Itu;Nutrição;2024\n1;SP;Sorocaba;Nutrição;2024\n1;SP;Sorocaba;Nutrição;2024\n1;SP;Capital;Direito;2024\n'
        with tempfile.NamedTemporaryFile(suffix='.zip') as tmp:
            with zipfile.ZipFile(tmp.name,'w') as z:
                z.writestr('MICRODADOS_ED_SUP_IES_2024.CSV',ies.encode('utf-8'))
                z.writestr('MICRODADOS_CADASTRO_CURSOS_2024.CSV',cursos.encode('utf-8'))
            rows=s.ler_fila_inep_zip(tmp.name)
        self.assertEqual({r['cidade'] for r in rows},{'Itu','Sorocaba'})
        self.assertEqual(len(rows),2)
    def test_todos_estados_e_df_estao_no_planejamento(self):
        self.assertEqual(len(s.ESTADOS),27)
        self.assertIn(('DF','Distrito Federal'),s.ESTADOS)
    def test_criterios_amplos_e_localizacao(self):
        qs=s.consultas_leads('Universidade Teste','UT','Itu','SP')
        self.assertTrue(any('"Itu" SP' in q for q in qs))
        for signal in ('"recém-formados"','"último período"','"estágio final"','"mostra" "autores"'):
            self.assertTrue(any(signal in q for q in qs))
    def test_mackenzie_formato_numerado_generico(self):
        out=f.ler_html('<title>Universidade Teste — Mostra de TCC</title><h2>Nutrição 2026.1</h2><p>1 - Ana Silva e Bruna Souza</p>', 'https://universidade.edu.br/tcc','Universidade Teste')[0]
        self.assertEqual([r['nome'] for r in out],['Ana Silva','Bruna Souza'])


class FilaFaculdadesTests(unittest.TestCase):
    def test_polos_estados_e_status_nao_repetem_faculdade(self):
        dados = [dict(id=3,instituicao="Universidade Teste",estado="SP",cidade="A",status="pendente"),
                 dict(id=1,instituicao="Universidade Teste",estado="AC",cidade="B",status="concluido"),
                 dict(id=2,instituicao="Outra Faculdade",estado="DF",cidade="C",status="erro")]
        fila = s.agrupar_faculdades(dados)
        self.assertEqual(len(fila), 2)
        item = next(x for x in fila if x["instituicao"] == "Universidade Teste")
        self.assertEqual(item["id"], 1)
        self.assertIsNone(item["cidade"])
        self.assertIsNone(item["estado"])
        self.assertIn("faculdade_1", s.etapa_captacao_item(item))
        self.assertEqual(s.agrupar_faculdades(list(reversed(dados))), fila)

    def test_pesquisa_nacional_salva_nome_sem_instagram(self):
        repo = Repo()
        item = s.agrupar_faculdades([repo.item])[0]
        registro = dict(nome="Ana Silva",ano=2026,periodo="2026/1",
                        evidencia="Nutrição turma 2026/1",contexto_academico="Nutrição turma 2026/1")
        with patch.object(s,"consultas_leads",return_value=["Nutrição turma 2026"]), patch.object(s.time,"sleep"):
            self.assertTrue(s.processar_instituicao(repo,item,
                search_fn=lambda *args: [{"href":"https://universidade.edu.br/turma"}],
                source_fn=lambda *args: ([registro],[])))
        self.assertEqual(len(repo.saved),1)
        self.assertEqual(repo.saved[0]["nome"],"Ana Silva")
        self.assertEqual(repo.cp["status"],"concluido")

class ConsultasDiversificadasTests(unittest.TestCase):
    def test_fontes_academicas_alem_de_turma(self):
        consultas = s.consultas_leads("Universidade Teste", "UT")
        for sinal in ["TCC", "defesa", "apresentação", "repositório", "colação", "estágio final", "último período", "lista de formandos", "entrega"]:
            self.assertTrue(any(sinal in q for q in consultas), sinal)
        self.assertTrue(all("Nutrição" in q for q in consultas))
        self.assertTrue(any("2025" in q for q in consultas))
        self.assertTrue(any("2026" in q for q in consultas))

class AlunoIndividualTests(unittest.TestCase):
    def extrair(self, trecho):
        return f.ler_html('<title>Universidade Teste — Nutrição</title>'+trecho,
                          'https://universidade.edu.br/noticia', 'Universidade Teste')[0]

    def test_aluno_individual_sem_turma_tcc_ou_instagram(self):
        out=self.extrair('<p>Em 2026, a aluna Ana Silva, do curso de Nutrição, apresentou seu trabalho.</p>')
        self.assertEqual([x['nome'] for x in out], ['Ana Silva'])
        self.assertEqual(out[0]['ano'], 2026)
        self.assertIsNone(out[0]['instagram'])

    def test_estudante_sem_prefixo_curso(self):
        out=self.extrair('<p>Em 2025, o estudante Bruno Santos de Nutrição participou da jornada acadêmica.</p>')
        self.assertEqual([x['nome'] for x in out], ['Bruno Santos'])

    def test_grupo_com_aluno_identificado(self):
        out=self.extrair('<h1>Grupo de alunos de Nutrição — 2026/2</h1><p>Alunos: Ana Silva</p>')
        self.assertEqual([x['nome'] for x in out], ['Ana Silva'])
        self.assertEqual(out[0]['periodo'], '2026/2')

    def test_publicacao_recente_sem_periodo_academico_nao_inventa_ano(self):
        out=self.extrair('<p>Publicado em 2026</p><p>A aluna Ana Silva, do curso de Nutrição, apresentou seu trabalho.</p>')
        self.assertEqual(out, [])

    def test_professora_nao_entra_como_aluna(self):
        out=self.extrair('<p>Em 2026, a professora Ana Silva do curso de Nutrição orientou os alunos.</p>')
        self.assertEqual(out, [])

if __name__=='__main__': unittest.main(verbosity=2)


class MenusNaoSaoAlunosTests(unittest.TestCase):
    def test_rotulos_reais_do_piloto_nao_sao_pessoas(self):
        nomes=['Laboratório de Informática','Estilo II','Sou Aluno','Uno Medical e Office',
               'Trabalhe Conosco','Pós-graduação Lato Sensu','Tipo Sanguíneo','Ensino Médio',
               'Página de Privacidade','Uso de Cookies','Processos Seletivos',
               'Pesquisa e Extensão','Regulamentos e Normas','Diretório Acadêmico',
               'Empresa Júnior','Procedimentos de Matrícula','Calendário de Matrícula']
        for nome in nomes:
            self.assertIsNone(f.pessoa(nome),nome)

    def test_menu_em_div_nao_entra_na_lista_de_formandos(self):
        html='<title>Universidade Teste — Nutrição formandos 2026/1</title><div class="menu-principal"><ul><li><a>Ana Menu</a></li></ul></div><h2>Alunos de Nutrição 2026/1</h2><ul><li>Ana Silva</li></ul>'
        out=f.ler_html(html,'https://universidade.edu.br/turma','Universidade Teste')[0]
        self.assertEqual([x['nome'] for x in out],['Ana Silva'])

class AtributosHtmlTests(unittest.TestCase):
    def test_atributos_sem_valor_nao_quebram_leitura(self):
        html='<title>Universidade Teste Nutrição 2026/1</title><p class role>A aluna Ana Silva do curso de Nutrição apresentou seu trabalho.</p>'
        out=f.ler_html(html,'https://universidade.edu.br/noticia','Universidade Teste')[0]
        self.assertEqual([x['nome'] for x in out],['Ana Silva'])
    def test_centro_e_relacionados_nao_sao_pessoas(self):
        for nome in ['Centro Universitário Uniateneu','Assuntos Relacionados']:
            self.assertIsNone(f.pessoa(nome))


class ArtigoAlunoRecenteTests(unittest.TestCase):
    def linhas(self, data='2026', escola='Universidade Teste'):
        return [(x,'pdf') for x in [f'Received: 13/04/{data} - Accepted: 27/05/{data}',
            'Nutrição e recuperação muscular', 'Vitor Manoel Matos Moutinho',
            'Acadêmico do curso de Nutrição da', escola+'. Brasil.',
            'E-mail: teste@example.org', 'Karine Rodrigues da Silva Neumann',
            'Docente do curso de Nutrição da', escola+'. Brasil.',
            'Revisão de artigos de 2015 a 2025']]
    def test_artigo_recente_aluno_sem_semestre_ignora_docente(self):
        out=f.extrair_autores_alunos_pdf(self.linhas(),'Universidade Teste')
        self.assertEqual([r['nome'] for r in out],['Vitor Manoel Matos Moutinho'])
        self.assertEqual(out[0]['ano'],2026)
        self.assertIsNone(out[0]['instagram'])
    def test_artigo_antigo_nao_usa_ano_das_referencias(self):
        self.assertEqual(f.extrair_autores_alunos_pdf(self.linhas('2024'),'Universidade Teste'),[])
    def test_vinculo_de_outra_faculdade_nao_e_reaproveitado(self):
        self.assertEqual(f.extrair_autores_alunos_pdf(self.linhas(escola='Outra Faculdade'),'Universidade Teste'),[])


class GruposAcademicosTests(unittest.TestCase):
    def extrair(self,conteudo):
        return f.ler_html('<title>Universidade Teste</title>'+conteudo,
                          'https://universidade.edu.br/grupo','Universidade Teste')[0]
    def test_grupo_estudos_com_lista_membros(self):
        out=self.extrair('<h1>Grupo de estudos de Nutrição 2026/2</h1><p>Membros: Ana Silva; Bruno Santos</p>')
        self.assertEqual([x['nome'] for x in out],['Ana Silva','Bruno Santos'])
        self.assertTrue(all(x['periodo']=='2026/2' for x in out))
    def test_liga_aluno_unico_sem_instagram(self):
        out=self.extrair('<h1>Liga acadêmica de Nutrição 2025</h1><p>Integrantes: Carla Souza</p>')
        self.assertEqual([x['nome'] for x in out],['Carla Souza'])
        self.assertIsNone(out[0]['instagram'])
    def test_grupo_so_primeiro_nome_nao_salva(self):
        self.assertEqual(self.extrair('<h1>Grupo de alunos de Nutrição 2026/1</h1><p>Membros: Ana</p>'),[])
    def test_docente_do_grupo_nao_e_aluno(self):
        out=self.extrair('<h1>Grupo de estudos de Nutrição 2026/1</h1><p>Professora: Ana Silva</p><p>Membros: Carla Souza</p>')
        self.assertEqual([x['nome'] for x in out],['Carla Souza'])
    def test_consultas_grupos_tem_ano_curso_e_faculdade(self):
        qs=s.consultas_leads('Universidade Teste','UT')
        for criterio in ['grupo de alunos','grupo de estudantes','grupo de estudos','liga acadêmica','centro acadêmico']:
            for ano in ['2025','2026']:
                self.assertTrue(any(criterio in q and ano in q and 'Nutrição' in q and 'Universidade Teste' in q for q in qs))
