import unittest
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch
import fontes_academicas as f

class TabelaTests(unittest.TestCase):
    def test_junta_nome_na_coluna_aluno_sem_copiar_banca(self):
        p=Mock(); p.extract_text.return_value='Nutrição UNIARP Trabalho de Conclusão de Curso semestre 2/2025'
        p.extract_tables.return_value=[[['ALUNO','TÍTULO','BANCA'],['Ana\nCarolina\nda Silva','Título do trabalho','Prof. Maria Santos'],['Bruno\nOliveira','Outro título','Prof. Carlos Silva']]]
        biblioteca=MagicMock(); biblioteca.open.return_value.__enter__.return_value=SimpleNamespace(pages=[p])
        with patch.dict('sys.modules',{'pdfplumber':biblioteca}):
            r=f.extrair_alunos_tabela_pdf(b'pdf','Universidade Alto Vale do Rio do Peixe','UNIARP')
        self.assertEqual([x['nome'] for x in r],['Ana Carolina da Silva','Bruno Oliveira'])
        self.assertEqual({x['ano'] for x in r},{2025})
    def test_tabela_sem_coluna_aluno_nao_cria_leads(self):
        p=Mock(); p.find_tables.return_value=[]; p.extract_words.return_value=[]; p.extract_text.return_value='Nutrição TCC semestre 2/2025'; p.extract_tables.return_value=[[['BANCA','TÍTULO'],['Maria Santos','Pesquisa']]]
        biblioteca=MagicMock(); biblioteca.open.return_value.__enter__.return_value=SimpleNamespace(pages=[p])
        with patch.dict('sys.modules',{'pdfplumber':biblioteca}):
            self.assertEqual(f.extrair_alunos_tabela_pdf(b'pdf',None),[])

    def test_nome_dividido_entre_paginas_e_recomposto(self):
        p1=Mock(); p2=Mock()
        p1.extract_text.return_value='Nutrição UNIARP TCC semestre 2/2025'; p2.extract_text.return_value='Continuação das bancas'
        p1.extract_tables.return_value=[[['ALUNO','BANCA'],['Bruno Oliveira','Prof. Maria Santos'],['Evelyn','Prof. Maria Santos']]]
        p2.extract_tables.return_value=[[['Cristina dos\nSantos Pereira','Prof. Maria Santos'],['Vivian\nBaseggio','Prof. Maria Santos']]]
        biblioteca=MagicMock(); biblioteca.open.return_value.__enter__.return_value=SimpleNamespace(pages=[p1,p2])
        with patch.dict('sys.modules',{'pdfplumber':biblioteca}):
            r=f.extrair_alunos_tabela_pdf(b'pdf','Universidade Alto Vale do Rio do Peixe','UNIARP')
        self.assertEqual([x['nome'] for x in r],['Bruno Oliveira','Evelyn Cristina dos Santos Pereira','Vivian Baseggio'])

    def test_tabela_multicurso_exige_nutricao_na_linha_do_aluno(self):
        p=Mock(); p.extract_text.return_value='TCC Nutrição e Administração 2025'
        p.extract_tables.return_value=[[['ALUNO','CURSO','BANCA'],['Ana Silva','Nutrição','Maria Santos'],['Bruno Oliveira','Administração','Maria Santos']]]
        biblioteca=MagicMock(); biblioteca.open.return_value.__enter__.return_value=SimpleNamespace(pages=[p])
        with patch.dict('sys.modules',{'pdfplumber':biblioteca}):
            r=f.extrair_alunos_tabela_pdf(b'pdf',None)
        self.assertEqual([x['nome'] for x in r],['Ana Silva'])

    def test_coluna_sem_bordas_junta_linhas_e_exclui_titulo_e_docente(self):
        def w(t,x,y): return {'text':t,'x0':x,'x1':x+len(t)*5,'top':y,'bottom':y+10}
        p=Mock(); p.extract_words.return_value=[w('ALUNO',50,20),w('TÍTULO',150,20),w('BANCA',300,20),w('Ana',50,60),w('Carolina',50,72),w('da',50,84),w('Silva',65,84),w('Nutrição',140,65),w('Prof.',300,60),w('Maria',330,60),w('Bruno',50,140),w('Oliveira',50,152)]
        tabela=Mock(); tabela.extract.return_value=[['ALUNO','TÍTULO','BANCA']]; tabela.rows=[SimpleNamespace(cells=[(45,18,120,32),(120,18,280,32),(280,18,400,32)])]; p.find_tables.return_value=[tabela]
        self.assertEqual(f.nomes_coluna_aluno(SimpleNamespace(pages=[p])),['Ana Carolina da Silva','Bruno Oliveira'])
