"""Migração/concorrência em PostgreSQL descartável, nunca no Supabase."""
import os
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

DSN = os.environ.get('PG_TEST_DSN')


@unittest.skipUnless(DSN, 'PostgreSQL descartável não configurado')
class UnicidadePostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        host = conninfo_to_dict(DSN).get('host', '')
        if host not in {'127.0.0.1', 'localhost'} and not host.startswith('/tmp/'):
            raise RuntimeError('Os testes SQL só aceitam banco local descartável')
        self.pg = psycopg
        self.conn = psycopg.connect(DSN, autocommit=True)
        self.conn.execute('DROP TABLE IF EXISTS public.leds')
        self.conn.execute('CREATE TABLE public.leds(id bigserial PRIMARY KEY, nome text, instituicao text, fonte_url text, origem text)')
        self.sql = (Path(__file__).parent / 'migrations/001_unicidade_leads.sql').read_text()

    def tearDown(self):
        self.conn.execute('ROLLBACK')
        self.conn.close()

    def test_migracao_idempotente_e_canonizacao(self):
        self.conn.execute(self.sql); self.conn.execute(self.sql)
        self.assertEqual(self.conn.execute("SELECT public.chave_lead_v58('  Júlia   São–Paulo  ')").fetchone()[0], 'julia sao-paulo')

    def test_variantes_de_acento_nao_duplicam(self):
        self.conn.execute(self.sql)
        self.conn.execute("INSERT INTO leds(nome,instituicao) VALUES ('Júlia Silva', 'Universidade São Paulo')")
        with self.assertRaises(self.pg.errors.UniqueViolation):
            self.conn.execute("INSERT INTO leds(nome,instituicao) VALUES ('julia  silva', 'universidade sao paulo')")

    def test_mesma_fonte_impede_variacao_da_instituicao(self):
        self.conn.execute(self.sql)
        self.conn.execute("INSERT INTO leds(nome,instituicao,fonte_url) VALUES ('Ana Silva','UT','https://example.org/tcc')")
        with self.assertRaises(self.pg.errors.UniqueViolation):
            self.conn.execute("INSERT INTO leds(nome,instituicao,fonte_url) VALUES ('Ana Silva','Universidade Teste','https://example.org/tcc')")

    def test_nomes_iguais_em_instituicoes_distintas_preservados(self):
        self.conn.execute(self.sql)
        self.conn.execute("INSERT INTO leds(nome,instituicao) VALUES ('Ana Silva','Faculdade A'),('Ana Silva','Faculdade B')")
        self.assertEqual(self.conn.execute('SELECT count(*) FROM leds').fetchone()[0], 2)

    def test_duplicados_legados_abortam_sem_apagar(self):
        self.conn.execute("INSERT INTO leds(nome,instituicao) VALUES ('Júlia Silva','UT'),('Julia Silva','UT')")
        with self.assertRaises(self.pg.errors.RaiseException):
            self.conn.execute(self.sql)
        self.conn.execute('ROLLBACK')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM leds').fetchone()[0], 2)

    def test_duas_insercoes_simultaneas_gravam_uma(self):
        from threading import Barrier
        self.conn.execute(self.sql); barreira = Barrier(2)
        def inserir(nome):
            with self.pg.connect(DSN, autocommit=True) as conn:
                barreira.wait(timeout=10)
                try:
                    conn.execute('INSERT INTO leds(nome,instituicao) VALUES (%s,%s)', (nome, 'UT'))
                    return 'salvo'
                except self.pg.errors.UniqueViolation:
                    return 'duplicado'
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(inserir, ['Júlia Silva', 'Julia Silva']))
        self.assertCountEqual(resultados, ['salvo', 'duplicado'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM leds').fetchone()[0], 1)


    def test_testes_legados_preservados_sem_liberar_duplicado_real(self):
        self.conn.execute("INSERT INTO leds(nome,origem) VALUES ('teste','teste_automacao'),('teste','teste_automacao')")
        self.conn.execute(self.sql)
        self.conn.execute("INSERT INTO leds(nome,instituicao) VALUES ('Ana Silva','UT')")
        with self.assertRaises(self.pg.errors.UniqueViolation):
            self.conn.execute("INSERT INTO leds(nome,instituicao) VALUES ('Ana Silva','UT')")
        self.assertEqual(self.conn.execute('SELECT count(*) FROM leds').fetchone()[0], 3)

    def test_mesma_fonte_legada_preservada_para_revisao(self):
        self.conn.execute("INSERT INTO leds(nome,instituicao,fonte_url) VALUES ('Ana Silva','UT','https://example.org/tcc'),('Ana Silva','Outra','https://example.org/tcc')")
        self.conn.execute(self.sql)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM leds').fetchone()[0], 2)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM leds WHERE duplicado_de IS NOT NULL AND nao_contatar AND NOT qualificado').fetchone()[0], 1)
