import contextlib
import io
import unittest
from unittest.mock import patch
import scraper as s

class Repo:
    def __init__(self):
        self.cp = None
        self.item = dict(id=1, instituicao='Universidade Teste', estado='SP')
        self.saved = []
    def controle_get(self, etapa): return self.cp
    def controle_salvar(self, etapa, dados): self.cp = dados.copy()
    def atualizar_instituicao(self, iid, **dados): self.item.update(dados)
    def lead_existe(self, *args): return False
    def instagram_usado(self, *args): return False
    def inserir_lead(self, dados): self.saved.append(dados)

class QualificationTests(unittest.TestCase):
    def test_invalid_or_unproven_profiles(self):
        for text in [
            'Nutrição, recém-formada em 2019',
            'Nutrição. Não estou no último período: 2º semestre',
            'Nutricionista desde 2010; concluinte de Psicologia 2026',
            'Nutrição 2019–2023, orientadora de TCC 2026',
            'Nutrição: estágio supervisionado no 3º semestre, 2026',
            'Nutrição 2026–2025', 'Nutrição, TCC 2027',
            'Nutrição, recém-formada',
            'Nutrição; contratada em 2026 após TCC',
            'Nutrição 2021–2024; emprego em 2026',
        ]:
            with self.subTest(text=text): self.assertFalse(s.lead_qualificado(text))
    def test_valid_profiles_and_metadata(self):
        for text, year in [
            ('Nutrição, colação de grau em 2025', 2025),
            ('Nutrição 2021.1–2025.2', 2025),
            ('Nutrição, recém‑formada em 2026', 2026),
            ('Nutrição, recém formada em 2025', 2025),
            ('Nutrição, último período em 2026', 2026),
            ('Nutrição, 8º semestre em 2026', 2026),
            ('Nutrição, TCC 2025; emprego em 2026', 2025),
            ('Nutrição, estágio final 2026', 2026),
        ]:
            with self.subTest(text=text):
                self.assertTrue(s.lead_qualificado(text))
                self.assertEqual(s.identificar_ano(text), year)
                self.assertIsNotNone(s.identificar_periodo(text))
    def test_snippet_does_not_borrow_second_person(self):
        result=dict(title='Ana Silva | LinkedIn',body='Veja o perfil de Ana Silva. Nutrição UFAC. Veja o perfil de Maria Souza, recém-formada em Nutrição UFAC 2026.', href='https://linkedin.com/in/ana-silva')
        text=s.contexto_resultado_perfil(result)
        self.assertNotIn('Maria', text)
        self.assertFalse(s.lead_qualificado(text))
    def test_institution_overlap(self):
        self.assertFalse(s.relacionado_a_instituicao('Universidade Federal de Mato Grosso do Sul', 'Universidade Federal de Mato Grosso',alias='UFMT'))
        self.assertTrue(s.relacionado_a_instituicao('Nutrição UFMT 2026', 'Universidade Federal de Mato Grosso',alias='UFMT'))
        self.assertFalse(s.relacionado_a_instituicao('Universidade Federal do Rio Grande do Sul', 'Universidade Federal do Rio Grande do Norte'))
    def test_domain_and_person(self):
        self.assertIsNone(s.extrair_nome_resultado(dict(title='Ana Silva',href='https://fake-linkedin.com/in/ana')))
        self.assertEqual(s.extrair_nome_resultado(dict(title='Ana Silva | LinkedIn',href='https://br.linkedin.com/in/ana')), 'Ana Silva')
    def test_searches_cover_both_names_and_years(self):
        qs=s.consultas_leads('Universidade Teste','UT')
        for term in ('"Universidade Teste"','"UT"'):
            for signal in ('TCC 2025','TCC 2026','"7º período"','"estágio final"','"colação de grau" 2025'):
                self.assertTrue(any(term in q and signal in q for q in qs))

class SearchTests(unittest.TestCase):
    def setUp(self):
        for key in s.stats: s.stats[key]=0
    @patch.object(s.time,'sleep')
    def test_no_results_requires_health(self, sleep):
        def unavailable(*args): raise Exception('No results found')
        self.assertIsNone(s.buscar_web('test', fetch_fn=unavailable))
        def healthy(query,*args):
            if query=='Brasil': return [dict(title='Brasil')]
            raise Exception('No results found')
        self.assertEqual(s.buscar_web('test',fetch_fn=healthy), [])
    @patch.object(s.time,'sleep')
    def test_error_followed_by_empty_is_not_confirmed_empty(self, sleep):
        count=0
        def fetch(*args):
            nonlocal count
            count+=1
            if count==1: raise RuntimeError('timeout')
            return []
        self.assertIsNone(s.buscar_web('test',fetch_fn=fetch))
    @patch.object(s.time,'sleep')
    def test_second_scan_repeats_all_queries(self,sleep):
        repo=Repo(); calls=[]
        def search(query,*args): calls.append(query); return []
        adapter=lambda *args: 0
        s.processar_instituicao(repo,repo.item.copy(),search,adapter)
        first=calls.copy(); calls.clear()
        s.processar_instituicao(repo,repo.item.copy(),search,adapter)
        self.assertEqual(calls,first)
        self.assertEqual(repo.item['status'],'concluido')
    @patch.object(s.time,'sleep')
    def test_connection_failure_resumes_interrupted_query(self,sleep):
        repo=Repo(); calls=[]
        def search(query,*args): calls.append(query); return [] if len(calls)==1 else None
        s.processar_instituicao(repo,repo.item.copy(),search,lambda *args:0)
        failed=calls[-1]; calls.clear()
        s.processar_instituicao(repo,repo.item.copy(),lambda q,*args: calls.append(q) or [],lambda *args:0)
        self.assertEqual(calls[0],failed)
    @patch.object(s.time,'sleep')
    def test_only_valid_person_is_saved(self,sleep):
        repo=Repo()
        def search(*args):
            return [dict(title='Ana Silva | LinkedIn',body='Nutrição Universidade Teste, colação de grau em 2025',href='https://linkedin.com/in/ana'),dict(title='Maria Souza | LinkedIn',body='Nutrição Universidade Teste, recém-formada em 2019',href='https://linkedin.com/in/maria')]
        with patch.object(s,'consultas_leads',return_value=['test']):
            s.processar_instituicao(repo,repo.item.copy(),search,lambda *args:0)
        self.assertEqual([x['nome'] for x in repo.saved],['Ana Silva'])
        self.assertEqual(repo.saved[0]['ano_alvo'],2025)

if __name__=='__main__':
    with contextlib.redirect_stdout(io.StringIO()): unittest.main(verbosity=2)
