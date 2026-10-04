import unittest
from unittest.mock import Mock, MagicMock, patch
import scraper as s
import enriquecimento as e

class OperacaoNacionalTests(unittest.TestCase):
    def test_retomada_tem_vaga_e_fila_avanca(self):
        nova = {'id': 1}
        antiga = {'id': 2, '_janela_encerrada': True, '_ultimo_checkpoint': '2026-10-01'}
        recente = {'id': 3, '_janela_encerrada': True, '_ultimo_checkpoint': '2026-10-04'}
        self.assertEqual(s.selecionar_janela([nova, recente, antiga], 2), [antiga, nova])
        self.assertEqual(s.selecionar_janela([nova], 0), [])

    def test_falha_nao_impede_segunda_faculdade(self):
        repo = Mock(); repo.fila_nacional.return_value = [{'id': 1}, {'id': 2}]
        with patch.object(s.SupabaseRepo, 'from_env', return_value=repo), patch.object(s, 'garantir_fila_oficial', return_value=True), patch.object(s, 'preparar_varredura_v58', return_value=True), patch.object(s, 'processar_instituicao', side_effect=[False, True]) as processar, patch.dict(s.stats, {k: 0 for k in s.stats}):
            with self.assertRaises(SystemExit): s.executar()
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
