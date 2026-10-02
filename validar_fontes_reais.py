from scraper import ler_fila_inep_zip,ESTADOS
import collections,json
records=ler_fila_inep_zip("cache_inep/cadastros_2024.zip")
states=collections.Counter(r["estado"] for r in records)
assert set(states)=={uf for uf,_ in ESTADOS}
print("FILA VALIDADA:",len(records),"FACULDADES:",len({r["instituicao"] for r in records}),"MUNICIPIOS:",len({(r["estado"],r["cidade"]) for r in records}),flush=True)
print("POR UF:",json.dumps(dict(sorted(states.items())),ensure_ascii=False),flush=True)
