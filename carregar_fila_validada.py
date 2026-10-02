import requests,ssl,hashlib,collections
import scraper as s
r=requests.get("https://www.detic.unicamp.br/wp-content/uploads/sites/38/2026/05/intermediate_2025.pem",timeout=30);r.raise_for_status()
fingerprint=hashlib.sha256(ssl.PEM_cert_to_DER_cert(r.text)).hexdigest()
print("CERTIFICADO INTERMEDIARIO:",fingerprint,flush=True)
assert fingerprint=="e10747d4da7bab09cba9952f019d3534cb9fba070bf13d8791b1699cd2ff59dd"
_,records=s.carregar_instituicoes_municipais_inep()
assert len(records)==6247
assert len({x["instituicao"] for x in records})==620
assert len({(x["estado"],x["cidade"]) for x in records})==1759
repo=s.SupabaseRepo.from_env()
assert s.garantir_fila_oficial(repo)
assert repo.contar_ies_v5()==len(records)
expected=collections.Counter(x["estado"] for x in records)
for uf,_ in s.ESTADOS:
    result=(repo.client.table("instituicoes_nutricao").select("id",count="exact").eq("origem",s.ORIGEM_IES).eq("estado",uf).execute())
    assert result.count==expected[uf],(uf,result.count,expected[uf])
    print("CONFERIDO NO BANCO:",uf,result.count,flush=True)
print("LISTA CONFIRMADA NO SUPABASE: 6247 combinações, 620 faculdades, 1759 municípios, 27 UFs.",flush=True)
