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
        out=self.extract('''<title>Universidade Teste — Outorga de grau</title><p>Publicado em 29/04/2026</p>
        <p>Formandos receberam a outorga de grau.</p><p>Psicologia: Ana Silva.</p>
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
        for url in ['https://linkedin.com/in/aluno','https://br.linkedin.com/in/aluno','http://127.0.0.1/x']:
            self.assertFalse(f.url_permitida(url))

class FluxoTests(unittest.TestCase):
    def setUp(self):
        for key in s.stats: s.stats[key]=0
    def test_consultas_institucionais(self):
        qs=s.consultas_leads('Universidade Teste','UT')
        self.assertFalse(any('site:linkedin.com/in' in q for q in qs))
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
    def test_maquina2_nao_chama_busca_linkedin(self):
        tree=ast.parse(Path(__file__).with_name('enriquecimento.py').read_text())
        self.assertFalse(any(isinstance(x,ast.Call) and isinstance(x.func,ast.Name) and x.func.id=='buscar_linkedin' for x in ast.walk(tree)))


class MunicipiosTests(unittest.TestCase):
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

if __name__=='__main__': unittest.main(verbosity=2)
