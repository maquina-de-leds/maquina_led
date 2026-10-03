import unittest
from fontes_academicas import extrair_resultado_busca as extrair
class PerfilFaseTests(unittest.TestCase):
    def test_ingresso_antigo_nao_apaga_setimo_semestre(self):
        r=extrair(dict(title='Leticia Gomes Biserra - LinkedIn',body='Estudante de Nutrição Mackenzie (7º semestre). Formação acadêmica 2023 - 2027.',href='https://br.linkedin.com/in/leticia'),'Mackenzie')
        self.assertEqual(len(r),1)
        self.assertIsNone(r[0]['ano'])
        self.assertIn('7º período/semestre',r[0]['periodo'])
        self.assertIn('2027',r[0]['evidencia'])
    def test_artigo_antigo_indexado_recentemente_continua_protegido(self):
        r=extrair(dict(title='Ana Silva',body='Graduanda de Nutrição. Artigo 2017 indexado em 2025.',href='https://revista.edu/artigo'),'Mackenzie')
        self.assertEqual(r,[])
    def test_professor_nao_e_capturado_com_semestre_da_turma(self):
        r=extrair(dict(title='Ana Silva - LinkedIn',body='Professora de Nutrição Mackenzie para estudantes do 7º semestre. 2023 - 2026.',href='https://br.linkedin.com/in/ana'),'Mackenzie')
        self.assertEqual(r,[])
    def test_nome_sem_sobrenome_nao_entra(self):
        r=extrair(dict(title='Laura - LinkedIn',body='Graduanda de Nutrição Mackenzie no 7º semestre. 2023 - 2026.',href='https://br.linkedin.com/in/laura'),'Mackenzie')
        self.assertEqual(r,[])
