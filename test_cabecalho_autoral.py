import unittest
import fontes_academicas as f

class CabecalhoTests(unittest.TestCase):
    def html(self,curso='Nutrição',ano='2025',nome='Ana Silva',papel='Autora'):
        return f'<title>Resumo Ampliado – Pré-TCC</title><h1>Resumo Ampliado – Pré-TCC</h1><h2>{papel}: {nome}</h2><h2>Curso: Bacharelado em {curso} – UNOPAR</h2><p>Ano: {ano}</p>'
    def extrair(self,**kw):
        return f.ler_html(self.html(**kw),'https://example.org/tcc','Universidade Pitágoras Unopar','Unopar')[0]
    def test_autora_curso_ano_em_campos_separados(self):
        r=self.extrair(); self.assertEqual([x['nome'] for x in r],['Ana Silva'])
        self.assertEqual(r[0]['ano'],2025); self.assertTrue(r[0]['candidato_indicio'])
    def test_nao_confunde_quimica_com_nutricao(self):
        self.assertEqual(self.extrair(curso='Química'),[])
    def test_ano_antigo_nao_e_atualizado_por_menu(self):
        self.assertEqual(self.extrair(ano='2024'),[])
    def test_enviado_por_nao_e_autor(self):
        self.assertEqual(self.extrair(papel='Enviado por'),[])
    def test_primeiro_nome_nao_e_salvo(self):
        self.assertEqual(self.extrair(nome='Ana'),[])
