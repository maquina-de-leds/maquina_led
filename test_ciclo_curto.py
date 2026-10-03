import unittest
from unittest.mock import patch
import fontes_academicas as f
import scraper as s
from test_scraper import Repo

class CicloCurtoTests(unittest.TestCase):
    def test_instituicao_sao_luis_nao_e_pessoa(self):
        self.assertIsNone(f.pessoa('São Luís'))
        self.assertIsNone(f.pessoa('Versão Final do Tcc'))
        self.assertEqual(f.pessoa('São Luís Silva'), 'São Luís Silva')
        self.assertEqual(f.pessoa('Ana Carolina Silva'), 'Ana Carolina Silva')

    def test_resultado_institucional_nao_cria_aluno(self):
        r={'title':'São Luís','href':'https://www.saoluis.br/',
           'body':'Estude Nutrição em 2026. Curso para estudantes.'}
        self.assertEqual(f.extrair_resultado_busca(r,'CESUPI'), [])

    @patch.object(s.time,'sleep')
    def test_fonte_inacessivel_nao_reinicia_janela(self, sleep):
        repo=Repo(); chamadas=[]
        r={'title':'Turma Nutrição 2026','href':'https://example.org/turma',
           'body':'Universidade Teste alunos Nutrição 2026'}
        def busca(q,*a): chamadas.append(q); return [r]
        def fonte(*a,**k): raise RuntimeError('503')
        with patch.object(s,'consultas_leads',return_value=['a','b','c']):
            s.processar_instituicao(repo,repo.item,search_fn=busca,source_fn=fonte,limite_consultas=1)
            self.assertEqual(repo.cp['indice_pesquisa'],1)
            self.assertEqual(repo.cp['status'],'processando')
            s.processar_instituicao(repo,repo.item,search_fn=busca,source_fn=fonte,limite_consultas=1)
        self.assertEqual(chamadas,['a','b'])
        self.assertEqual(repo.cp['indice_pesquisa'],2)
        self.assertEqual(repo.cp['ultimo_erro'],'Janela com fontes pendentes; repetir ao finalizar')

class ResultadoCicloTests(unittest.TestCase):
    def test_pendencias_externas_nao_sao_falha_de_execucao(self):
        from unittest.mock import Mock
        repo=Mock(); repo.fila_nacional.return_value=[{'id':1}]
        with patch.object(s.SupabaseRepo,'from_env',return_value=repo), patch.object(s,'garantir_fila_oficial',return_value=True), patch.object(s,'preparar_varredura_v58',return_value=True), patch.object(s,'processar_instituicao',return_value=True), patch.dict(s.stats,{'erros':2,'instituicoes_erro':0}):
            s.executar()

    def test_busca_indisponivel_continua_sendo_falha(self):
        from unittest.mock import Mock
        repo=Mock(); repo.fila_nacional.return_value=[{'id':1}]
        with patch.object(s.SupabaseRepo,'from_env',return_value=repo), patch.object(s,'garantir_fila_oficial',return_value=True), patch.object(s,'preparar_varredura_v58',return_value=True), patch.object(s,'processar_instituicao',return_value=False):
            with self.assertRaises(SystemExit) as exc: s.executar()
            self.assertEqual(exc.exception.code,2)

if __name__=='__main__': unittest.main()
