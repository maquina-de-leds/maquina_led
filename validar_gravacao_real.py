import requests
import scraper as s
from fontes_academicas import ler_html
repo=s.SupabaseRepo.from_env()
sources=[
("https://uno.edu.br/noticias/outorga-de-grau-1","Unochapecó","Chapecó","SC","2025/2",13),
("https://uniateneu.edu.br/uniateneu-realizou-colacao-de-grau-para-celebrar-a-formatura-de-alunos-de-diferentes-cursos-de-graduacao/","UniAteneu","Fortaleza","CE","2026/1",1)]
batch=[]
# Confere todas as fontes antes da primeira gravação.
for url,inst,city,uf,period,expected in sources:
    r=requests.get(url,timeout=30);r.raise_for_status()
    records=[x for x in ler_html(r.text,url,inst)[0] if x["periodo"]==period]
    assert len(records)==expected,(inst,len(records),expected)
    batch.extend((x,url,inst,city,uf) for x in records)
print("CANDIDATOS CONFERIDOS:",len(batch),flush=True)
for item,url,inst,city,uf in batch:
    s.salvar_lead(repo,item["nome"],inst,city,uf,item["evidencia"],url,
                  instagram=item["instagram"],ano_forcado=item["ano"],periodo_forcado=item["periodo"])
print("PRIMEIRA PASSAGEM: novos=",s.stats["leads_salvos"],"duplicados=",s.stats["duplicados"],flush=True)
saved_before=s.stats["leads_salvos"]
duplicates_before=s.stats["duplicados"]
for item,url,inst,city,uf in batch:
    assert repo.lead_existe(s.formatar_nome_pessoa(item["nome"]),inst)
    s.salvar_lead(repo,item["nome"],inst,city,uf,item["evidencia"],url,
                  instagram=item["instagram"],ano_forcado=item["ano"],periodo_forcado=item["periodo"])
assert s.stats["leads_salvos"]==saved_before
assert s.stats["duplicados"]-duplicates_before==len(batch)
print("VALIDACAO: 14 pessoas presentes no banco; segunda passagem não inseriu duplicados.",flush=True)
