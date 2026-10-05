"""Regressões da auditoria; nenhuma conexão ou gravação externa."""
import io
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import fontes_academicas as f
import scraper as s
import enriquecimento as e
from test_scraper import Repo
from test_retomada_fontes import RepoPendencias


class QualificacaoTests(unittest.TestCase):
    def salvar(self, evidencia, indicio=False, instagram=None):
        repo = Repo()
        s.salvar_lead(repo, 'Ana Silva', 'Universidade Teste', None, None,
                      evidencia, 'https://example.org/fonte', instagram=instagram,
                      ano_forcado=2026, periodo_forcado='2026/1', candidato_indicio=indicio)
        return repo.saved[0]

    def test_aluna_segundo_semestre_nao_e_fase_final(self):
        linhas = [('Publicado: 01/06/2026', 'pdf'), ('Ana Silva', 'pdf'),
                  ('Acadêmica de Nutrição Universidade Teste, segundo semestre', 'pdf')]
        registro = f.extrair_autores_alunos_pdf(linhas, 'Universidade Teste')[0]
        dados = self.salvar(registro['evidencia'], registro['candidato_indicio'])
        self.assertFalse(dados['qualificado'])
        self.assertEqual(dados['proxima_acao'], 'validar_fase_academica')

    def test_candidato_com_instagram_nao_vai_para_contato(self):
        dados = self.salvar('Aluna Nutrição 2026', instagram='@ana.nutri')
        self.assertFalse(dados['qualificado'])
        self.assertEqual(dados['proxima_acao'], 'validar_fase_academica')

    def test_tcc_formandos_e_fase_final_permanecem_qualificados(self):
        for texto in ('Nutrição TCC 2026', 'Formandos Nutrição 2026', 'Nutrição último semestre 2026', 'Nutrição 7º semestre 2026'):
            with self.subTest(texto=texto):
                self.assertTrue(self.salvar(texto)['qualificado'])

    def test_indicio_explicito_prevalece_sobre_tcc(self):
        self.assertFalse(self.salvar('Autoria TCC Nutrição 2026', indicio=True)['qualificado'])

    def test_semestre_calendario_nao_e_semestre_inicial_do_aluno(self):
        self.assertTrue(f.fase_final_comprovada('Formandos Nutrição referente ao 2º semestre de 2025'))
        self.assertFalse(f.fase_final_comprovada('Aluna Nutrição cursando 2º semestre, TCC em outro projeto 2026'))

    def test_lista_de_formandos_conserva_evidencia_de_fase_final(self):
        registros, _ = f.ler_html('<title>Universidade Teste</title><h1>Formandos Nutrição 2026.1</h1><ul><li>Ana Silva</li></ul>', 'https://example.org/lista', 'Universidade Teste')
        self.assertTrue(self.salvar(registros[0]['evidencia'])['qualificado'])

    def test_vinculo_sem_fase_final_preservado_pela_captura(self):
        repo = Repo()
        resultado = {'title': 'Ana Silva', 'body': 'Estudante de Nutrição Universidade Teste 2026.', 'href': 'https://example.org/aluna'}
        with patch.object(s, 'consultas_leads', return_value=['uma']), patch.object(s.time, 'sleep'):
            s.processar_instituicao(repo, repo.item, lambda *a: [resultado], lambda *a: ([], []))
        self.assertFalse(repo.saved[0]['qualificado'])

    def test_semestre_invertido_e_ano_primeiro(self):
        for texto in ('Curso de Nutrição semestre 2/2025', 'semestre 2025/2', 'semestre 2.2025', 'Nutrição referente ao 2º semestre de 2025'):
            self.assertEqual(f.periodo_academico(texto), (2025, '2025/2'))


class Maquina2Tests(unittest.TestCase):
    def test_falha_de_banco_nao_vira_fila_vazia_ou_instagram_livre(self):
        client = Mock(); client.table.side_effect = RuntimeError('banco indisponível')
        with patch.object(e, 'supabase', client):
            with self.assertRaises(RuntimeError): e.buscar_pendentes()
            with self.assertRaises(RuntimeError): e.instagram_ja_usado('@ana.nutri', 7)

    def test_atualizacao_de_contato_condicionada_ao_estado_atual(self):
        client = Mock(); q = client.table.return_value
        q.update.return_value = q; q.eq.return_value = q; q.or_.return_value = q; q.execute.return_value.data = []
        with patch.object(e, 'supabase', client):
            self.assertFalse(e.atualizar_lead(7, instagram='@ana.nutri'))
        self.assertIn(unittest.mock.call('qualificado', True), q.eq.call_args_list)
        self.assertIn(unittest.mock.call('nao_contatar', False), q.eq.call_args_list)

    def candidato(self):
        return {'id': 7, 'nome': 'Ana Silva', 'instituicao': 'Universidade Teste',
                'qualificado': False, 'instagram': None, 'nao_contatar': False}

    def test_fila_restringe_qualificados_sem_instagram_e_exclui_nao_contatar(self):
        client = Mock(); query = client.table.return_value
        for method in ('select', 'eq', 'is_', 'order', 'limit'):
            getattr(query, method).return_value = query
        lead = self.candidato(); lead['qualificado'] = True; lead['instituicao'] = 'Instituto Saúde'
        query.execute.return_value.data = [lead]
        with patch.object(e, 'supabase', client):
            self.assertEqual(len(e.buscar_pendentes()), 1)
        self.assertIn(unittest.mock.call('nao_contatar', False), query.eq.call_args_list)
        self.assertIn(unittest.mock.call('qualificado', True), query.eq.call_args_list)
        query.is_.assert_called_with('instagram', 'null')

    def test_nao_contatar_nem_valida(self):
        lead = self.candidato(); lead['nao_contatar'] = True
        with patch.object(e, 'validar_candidato') as validar:
            e.processar_lead(Mock(), lead)
            validar.assert_not_called()

    def validar(self, resultado, atualizou=True):
        lead = self.candidato(); client = Mock(); q = client.table.return_value
        q.update.return_value = q; q.eq.return_value = q
        q.or_.return_value = q
        q.execute.return_value.data = [lead] if atualizou else []
        with patch.object(e, 'supabase', client), patch('scraper.buscar_web', return_value=[resultado]), patch.object(e, 'pausa'):
            validou = e.validar_candidato(Mock(), lead)
        return validou, lead, q

    def test_promove_nome_curso_faculdade_e_fase_confirmados(self):
        validou, lead, query = self.validar({'title': 'Ana Silva', 'body': 'Formanda em Nutrição Universidade Teste 2026.', 'href': 'https://example.org/ana'})
        self.assertTrue(validou); self.assertTrue(lead['qualificado'])
        self.assertEqual(lead['proxima_acao'], 'buscar_instagram')
        self.assertIn(unittest.mock.call('nao_contatar', False), query.eq.call_args_list)

    def test_homonimo_outro_curso_e_aluna_inicial_nao_promovidos(self):
        for titulo, body in [('Bruna Silva', 'Formanda Nutrição Universidade Teste 2026'), ('Ana Silva', 'Formanda Psicologia Universidade Teste 2026'), ('Ana Silva', 'Aluna Nutrição Universidade Teste 2026 2º semestre')]:
            validou, lead, query = self.validar({'title': titulo, 'body': body, 'href': 'https://example.org/pessoa'})
            self.assertFalse(validou); self.assertFalse(lead['qualificado']); query.update.assert_not_called()

    def test_atualizacao_bloqueada_nao_promove_em_memoria(self):
        validou, lead, _ = self.validar({'title': 'Ana Silva', 'body': 'Formanda Nutrição Universidade Teste 2026', 'href': 'https://example.org/pessoa'}, False)
        self.assertFalse(validou); self.assertFalse(lead['qualificado'])


class RetomadaTests(unittest.TestCase):
    @patch.object(s.time, 'sleep')
    def test_falha_isolada_preserva_primeira_consulta_apos_resultados_validos(self, _):
        repo = RepoPendencias()
        def buscar(q, n):
            return None if q == 'falhou' else []
        with patch.object(s, 'consultas_leads', return_value=['falhou', 'ok']):
            self.assertFalse(s.processar_instituicao(repo, repo.item, search_fn=buscar, continuar_falhas=True))
        self.assertEqual(repo.cp['consulta_atual'], 'falhou')
        self.assertEqual(repo.cp['indice_pesquisa'], 0)
        self.assertEqual(repo.cp['ultimo_erro'], 'Busca externa indisponível')

    def test_alternativa_vazia_nao_oculta_falha_de_fonte(self):
        with patch.object(f, '_carregar_url', side_effect=[([], []), RuntimeError('503'), ([], []), ([], [])]):
            with self.assertRaises(RuntimeError):
                f.carregar_fonte('https://www.mackenzie.br/noticias/artigo/n/a/i/materia', 'Mackenzie')

    @patch.object(s.time, 'sleep')
    def test_timeout_misto_nao_vira_busca_vazia(self, _):
        def buscar(q, backend, n):
            if backend == 'bing' or q == 'Brasil': return [] if q != 'Brasil' else [{'title': 'Brasil'}]
            raise TimeoutError('timeout')
        self.assertIsNone(s.buscar_web('consulta', fetch_fn=buscar))

    @patch.object(s.time, 'sleep')
    def test_pdf_sem_texto_preserva_url_e_nao_conclui_faculdade(self, _):
        from pypdf import PdfWriter
        writer = PdfWriter(); writer.add_blank_page(width=100, height=100)
        data = io.BytesIO(); writer.write(data)
        repo = RepoPendencias(); url = 'https://example.org/doc.pdf'
        repo.pendentes[url] = '503'
        s.retentar_fontes_pendentes(repo, repo.item, {'total_pesquisas': 2}, lambda *a: f.ler_pdf(data.getvalue(), 'Universidade Teste'), 6)
        self.assertIn(url, repo.fontes_pendentes(repo.item)); self.assertEqual(repo.cp['status'], 'erro')

    def test_formato_nao_suportado_fica_inconclusivo(self):
        with self.assertRaises(f.ExtracaoInconclusiva):
            f._interpretar_documento(b'arquivo imagem', 'image/png', 'utf-8', 'https://example.org/x', 'Universidade Teste', None)

    def test_backoff_e_teto_de_tentativas(self):
        repo = s.SupabaseRepo(Mock()); repo.controle_get = Mock()
        for tentativas, minutos, esperado in [(1, 5, False), (1, 31, True), (3, 31, False), (3, 121, True), (5, 10000, False)]:
            repo.controle_get.return_value = {'status': 'erro', 'tentativas': tentativas, 'atualizado_em': (datetime.now(timezone.utc) - timedelta(minutes=minutos)).isoformat()}
            self.assertEqual(repo.fonte_pode_retentar({'id': 1}, 'https://example.org/doc'), esperado)

    def test_url_adiada_nao_e_marcada_concluida(self):
        repo = RepoPendencias(); repo.pendentes['https://example.org/doc'] = '503'
        repo.fonte_pode_retentar = lambda *a: False
        source = Mock()
        s.retentar_fontes_pendentes(repo, repo.item, {'total_pesquisas': 2}, source, 6)
        source.assert_not_called(); self.assertEqual(repo.cp['status'], 'erro')


class BancoTests(unittest.TestCase):
    def repo(self):
        client = Mock(); q = client.table.return_value
        for method in ('insert', 'select', 'eq', 'is_', 'ilike', 'limit', 'order', 'range'):
            getattr(q, method).return_value = q
        return s.SupabaseRepo(client), q

    def test_dedup_acento_caixa_e_espacos(self):
        repo, q = self.repo()
        q.execute.side_effect = [SimpleNamespace(data=[]), SimpleNamespace(data=[{'nome': 'Júlia  Silva', 'instituicao': 'Universidade  São Paulo'}])]
        self.assertTrue(repo.lead_existe('Julia Silva', 'universidade sao paulo'))

    def test_fonte_ja_capitalizada_consulta_url_exata(self):
        repo, q = self.repo()
        q.execute.return_value = SimpleNamespace(data=[{'id': 7}])
        self.assertTrue(repo.fonte_ja_capitalizada('https://repositorio.exemplo.edu/colecao'))
        q.eq.assert_called_with('fonte_url', 'https://repositorio.exemplo.edu/colecao')
        q.limit.assert_called_with(1)

    @patch.object(s.time, 'sleep')
    def test_timeout_apos_commit_nao_reinsere(self, sleep):
        repo, q = self.repo(); q.execute.side_effect = TimeoutError('timeout')
        repo.lead_existe = Mock(return_value=True)
        self.assertFalse(repo.inserir_lead({'nome': 'Ana Silva', 'instituicao': 'UT'}))
        self.assertEqual(q.insert.call_count, 1); sleep.assert_not_called()

    @patch.object(s.time, 'sleep')
    def test_timeout_antes_commit_repete_e_confirma(self, sleep):
        repo, q = self.repo(); q.execute.side_effect = [TimeoutError('timeout'), SimpleNamespace(data=[{'id': 1}])]
        repo.lead_existe = Mock(return_value=False)
        self.assertTrue(repo.inserir_lead({'nome': 'Ana Silva', 'instituicao': 'UT'}))
        self.assertEqual(q.insert.call_count, 2); sleep.assert_called_once_with(1)

    @patch.object(s.time, 'sleep')
    def test_erro_de_schema_nao_recebe_retry(self, sleep):
        repo, q = self.repo(); q.execute.side_effect = ValueError('coluna inexistente')
        repo.lead_existe = Mock(return_value=False)
        with self.assertRaises(ValueError): repo.inserir_lead({'nome': 'Ana Silva', 'instituicao': 'UT'})
        self.assertEqual(q.insert.call_count, 1); sleep.assert_not_called()

    def test_conflito_confirmado_nao_incrementa_novos(self):
        repo = Repo(); repo.inserir_lead = Mock(return_value=False)
        with patch.dict(s.stats, {'leads_salvos': 0, 'duplicados': 0}):
            self.assertFalse(s.salvar_lead(repo, 'Ana Silva', 'UT', None, None, 'Nutrição TCC 2026', 'https://example.org/x', ano_forcado=2026, periodo_forcado='2026/1'))
            self.assertEqual(s.stats['leads_salvos'], 0); self.assertEqual(s.stats['duplicados'], 1)

    def test_instagram_completado_preserva_validacao(self):
        repo, q = self.repo(); q.update.return_value = q
        repo.instagram_usado = Mock(return_value=False)
        q.execute.side_effect = [SimpleNamespace(data=[{'id': 1, 'instagram': None, 'qualificado': False, 'nao_contatar': False}]), SimpleNamespace(data=[{'id': 1}])]
        self.assertTrue(repo.completar_instagram('Ana Silva', 'UT', '@ana.nutri'))
        self.assertEqual(q.update.call_args.args[0]['proxima_acao'], 'validar_fase_academica')


class EditalRealTests(unittest.TestCase):
    def test_edital_uniarp_nove_nomes_sem_docentes_e_semestre_explicito(self):
        from pathlib import Path
        dados = (Path(__file__).parent / 'tests/fixtures/uniarp_tcc_2025.pdf').read_bytes()
        registros, _ = f.ler_pdf(dados, 'Universidade Alto Vale do Rio do Peixe', 'UNIARP')
        esperados = {'Bruno Santos Abdalla de Oliveira', 'Gabriel de Bortoli Tibes da Luz',
                     'Nicolle Aparecida da Luz', 'Tiago Valentim Pedroso da Silva',
                     'Evelyn Cristina dos Santos Pereira', 'Grazieli da Silva Caetano',
                     'Jessica Camile Favarin', 'Silas Rodrigues da Silva', 'Vivian Baseggio'}
        self.assertEqual({f.norm(r['nome']) for r in registros}, {f.norm(n) for n in esperados})
        self.assertEqual(len(registros), 9)
        self.assertEqual({r['periodo'] for r in registros}, {'2025/2'})
        self.assertTrue(all(f.fase_final_comprovada(r['evidencia']) for r in registros))

