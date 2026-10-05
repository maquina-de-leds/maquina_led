import csv
import tempfile
import unittest
from pathlib import Path

from instagram_enriquecimento_assistido import (
    agrupar_por_busca,
    elegivel,
    importar,
    ler_resultados,
    normalizar_handle,
    url_pesquisa_instagram,
)


class FakeResponse:
    def __init__(self, data=None):
        self.data = data or []


class FakeQuery:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.filters = []
        self.mode, self.payload = "select", None

    def select(self, *_args, **_kwargs):
        self.mode = "select"
        return self

    def eq(self, key, value):
        self.filters.append((key, "eq", value))
        return self

    def in_(self, key, values):
        self.filters.append((key, "in", values))
        return self

    def update(self, payload):
        self.mode, self.payload = "update", payload
        return self

    def insert(self, payload):
        self.mode, self.payload = "insert", payload
        return self

    def limit(self, _value):
        return self

    def execute(self):
        if self.mode == "insert":
            rows = self.payload if isinstance(self.payload, list) else [self.payload]
            if self.table == "instagram_candidatos":
                known = {r["instagram"].lower() for r in self.db.candidates}
                for row in rows:
                    if row["instagram"].lower() in known:
                        raise Exception("23505 unique violation")
                    self.db.candidates.append(dict(row))
                    known.add(row["instagram"].lower())
            return FakeResponse(rows)
        if self.mode == "update":
            self.db.lead_updates.append((self.table, self.payload))
            return FakeResponse([self.payload])
        rows = self.db.tables.get(self.table, [])
        for key, op, value in self.filters:
            if op == "eq":
                rows = [r for r in rows if r.get(key) == value]
            elif op == "in":
                rows = [r for r in rows if r.get(key) in value]
        return FakeResponse([dict(r) for r in rows])


class FakeSupabase:
    def __init__(self):
        self.tables = {
            "instagram_buscas": [{"id": 7, "lead_origem_id": 42, "nome_pesquisado": "Ana Nutri",
                                  "consulta": "Ana Nutri nutrição", "status": "pendente"}],
            "leds": [{"id": 42, "nome": "Ana Nutri", "instagram": None, "instagram_url": None,
                      "qualificado": True, "nao_contatar": False, "não_contatar": False}],
        }
        self.candidates = []
        self.lead_updates = []

    def table(self, name):
        if name == "instagram_candidatos":
            self.tables[name] = self.candidates
        return FakeQuery(self, name)


class EnriquecimentoAssistidoTests(unittest.TestCase):
    def test_normaliza_handle_e_url(self):
        self.assertEqual(normalizar_handle(" @Nutri.Ana "), "@nutri.ana")
        self.assertEqual(normalizar_handle("https://www.instagram.com/Nutri_Ana/"), "@nutri_ana")
        with self.assertRaises(ValueError):
            normalizar_handle("@nome inválido")

    def test_consulta_abre_instagram_com_nome_e_nutricao(self):
        url = url_pesquisa_instagram("Ana da Silva nutrição")
        self.assertTrue(url.startswith("https://www.instagram.com/explore/search/keyword/?q="))
        self.assertIn("nutri%C3%A7%C3%A3o", url)

    def test_elegibilidade_preserva_optout_e_lead_com_instagram(self):
        base = {"nome": "Ana da Silva", "qualificado": True}
        self.assertTrue(elegivel(base))
        self.assertFalse(elegivel({**base, "instagram": "@ana"}))
        self.assertFalse(elegivel({**base, "não_contatar": True}))
        self.assertFalse(elegivel({**base, "qualificado": False}))

    def test_le_resultados_com_varios_handles_na_mesma_busca(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "resultados.csv"
            with path.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["busca_id", "lead_id", "consulta", "instagram"])
                writer.writeheader()
                writer.writerow({"busca_id": 7, "lead_id": 42, "consulta": "Ana nutrição", "instagram": "@ana"})
                writer.writerow({"busca_id": 7, "lead_id": 42, "consulta": "Ana nutrição", "instagram": "@ana.nutri"})
            rows = ler_resultados(path)
        self.assertEqual(len(agrupar_por_busca(rows)["7"]), 2)

    def test_importa_todos_e_nao_altera_lead_original(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "resultados.csv"
            with path.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["busca_id", "lead_id", "consulta", "nome_perfil", "instagram"])
                writer.writeheader()
                writer.writerow({"busca_id": 7, "lead_id": 42, "consulta": "Ana Nutri nutrição", "nome_perfil": "Ana Nutri", "instagram": "@AnaNutri"})
                writer.writerow({"busca_id": 7, "lead_id": 42, "consulta": "Ana Nutri nutrição", "nome_perfil": "Ana Alimentação", "instagram": "@ana.alimenta"})
            db = FakeSupabase()
            resumo = importar(db, str(path))
        self.assertEqual(resumo["salvos"], 2)
        self.assertEqual({r["instagram"] for r in db.candidates}, {"@ananutri", "@ana.alimenta"})
        self.assertFalse(any(table == "leds" for table, _ in db.lead_updates))

    def test_duplicado_global_nao_grava_duas_vezes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "resultados.csv"
            with path.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["busca_id", "lead_id", "consulta", "instagram"])
                writer.writeheader()
                for handle in ("@AnaNutri", "@ananutri"):
                    writer.writerow({"busca_id": 7, "lead_id": 42, "consulta": "Ana Nutri nutrição", "instagram": handle})
            db = FakeSupabase()
            resumo = importar(db, str(path))
        self.assertEqual(resumo["salvos"], 1)
        self.assertEqual(resumo["duplicados"], 1)


if __name__ == "__main__":
    unittest.main()
