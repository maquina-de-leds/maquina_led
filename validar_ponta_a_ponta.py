import scraper as s
from fontes_academicas import carregar_fonte
repo=s.SupabaseRepo.from_env()
rows=(repo.client.table("instituicoes_nutricao").select("*").eq("origem",s.ORIGEM_IES).eq("estado","CE").eq("cidade","Fortaleza").execute()).data
target=[r for r in rows if "ateneu" in s.normalizar(r["instituicao"])]
assert len(target)==1
item=target[0];inst=item["instituicao"];alias=s.alias_instituicao(item)
print("FACULDADE REAL DA FILA:",inst,"SIGLA:",alias,flush=True)
results=s.buscar_web('"UniAteneu" Nutrição "formandos" 2026 -site:linkedin.com',max_results=5)
assert results is not None
expected="https://uniateneu.edu.br/uniateneu-realizou-colacao-de-grau-para-celebrar-a-formatura-de-alunos-de-diferentes-cursos-de-graduacao/"
urls=[r.get("href") or r.get("url") or "" for r in results]
assert expected in urls
records,_=carregar_fonte(expected,inst,alias)
records=[r for r in records if r["nome"]=="Giovanna Kimie" and r["periodo"]=="2026/1"]
assert len(records)==1
record=records[0]
assert "fortaleza" in s.normalizar(record["contexto_academico"])
assert repo.lead_existe(record["nome"],inst) or repo.instituicao_de_lead_por_alias(record["nome"],alias)
saved=s.salvar_lead(repo,record["nome"],inst,"Fortaleza","CE",record["evidencia"],expected,ano_forcado=record["ano"],periodo_forcado=record["periodo"],instituicao_alias=alias)
assert not saved
assert s.stats["duplicados"]==1 and s.stats["leads_salvos"]==0
print("PONTA A PONTA CONFIRMADA: busca encontrou fonte; Nutrição 2026/1 e Fortaleza confirmados; nome já salvo via sigla não duplicou.",flush=True)
