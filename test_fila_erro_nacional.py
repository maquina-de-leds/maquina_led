import unittest
from datetime import datetime, timedelta, timezone
import scraper as s


class FakeRepo:
    def __init__(self, checkpoint):
        self.checkpoint = checkpoint

    def controle_get(self, etapa):
        return self.checkpoint

    def controle_salvar(self, etapa, data):
        self.checkpoint = dict(data)


def item(uf, status, updated, name):
    return {
        "estado": uf, "instituicao": name,
        "_status_checkpoint": status,
        "_ultimo_checkpoint": updated,
    }


class TestFilaEstadoAvancaFalhas(unittest.TestCase):
    def test_falha_recente_nao_bloqueia_proximo_estado(self):
        agora = datetime.now(timezone.utc)
        repo = FakeRepo({"estado": "AC", "status": "processando"})
        fila = [
            item("AC", "erro", (agora - timedelta(minutes=20)).isoformat(), "UFAC"),
            item("AL", "pendente", "", "Faculdade AL"),
        ]
        resultado = s.fila_estado_atual(repo, fila)
        self.assertEqual([x["instituicao"] for x in resultado], ["Faculdade AL"])
        self.assertEqual(repo.checkpoint["estado"], "AL")

    def test_rota_concluida_reabre_falha_antiga(self):
        agora = datetime.now(timezone.utc)
        repo = FakeRepo({"estado": "TO", "status": "concluido"})
        erro = item("AC", "erro", (agora - timedelta(hours=2)).isoformat(), "UFAC")
        resultado = s.fila_estado_atual(repo, [erro])
        self.assertEqual(resultado, [erro])
        self.assertEqual(repo.checkpoint["estado"], "AC")

    def test_rota_concluida_aguarda_cooldown_da_falha(self):
        agora = datetime.now(timezone.utc)
        repo = FakeRepo({"estado": "TO", "status": "concluido"})
        erro = item("AC", "erro", (agora - timedelta(minutes=30)).isoformat(), "UFAC")
        self.assertEqual(s.fila_estado_atual(repo, [erro]), [])


if __name__ == "__main__":
    unittest.main()
