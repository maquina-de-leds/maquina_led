"""Busca completa independente na Mackenzie e compara nomes únicos com a base."""
import json,sys,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scraper as s
from fontes_academicas import carregar_fonte
repo=s.SupabaseRepo.from_env()
rows=repo.client.table("instituicoes_nutricao").select("*").eq("origem",s.ORIGEM_IES).ilike("instituicao","%Mackenzie%").execute().data or []
base=next(x for x in s.agrupar_faculdades(rows) if s.normalizar(x["instituicao"])==s.normalizar("Universidade Presbiteriana Mackenzie"))
alias=s.alias_instituicao(base)
if s.normalizar(alias) not in {"mackenzie","upm"}:
    base["fonte_validacao"]=(base.get("fonte_validacao") or "")+" | SIGLA=Mackenzie"
def nomes_banco():
    nomes={}
    for offset in range(0,100000,1000):
        lote=repo.client.table("leds").select("nome,instituicao,nao_contatar").ilike("instituicao","%Mackenzie%").order("id").range(offset,offset+999).execute().data or []
        for r in lote:
            if not r.get("nao_contatar"): nomes[s.normalizar(r["nome"])]=r["nome"]
        if len(lote)<1000: return nomes
    raise RuntimeError("Paginação incompleta")
antes=nomes_banco()
print("BASE ANTES:",json.dumps(list(antes.values()),ensure_ascii=False),flush=True)
vistos={}
original_salvar=s.salvar_lead
def salvar_observado(repo,nome,*args,**kw):
    vistos[s.normalizar(s.formatar_nome_pessoa(nome))]=s.formatar_nome_pessoa(nome)
    return original_salvar(repo,nome,*args,**kw)
s.salvar_lead=salvar_observado
class Piloto:
    def __getattr__(self,n): return getattr(repo,n)
    def atualizar_instituicao(self,*a,**kw): pass
    def inserir_lead(self,d):
        repo.inserir_lead(d)
        assert repo.lead_existe(d["nome"],d["instituicao"])
        print("GRAVACAO CONFIRMADA:",d["nome"],flush=True)
def fonte(url,ies,alias):
    registros,links=carregar_fonte(url,ies,alias)
    for r in registros: vistos[s.normalizar(r["nome"])]=r["nome"]
    return registros,links
def busca(q,max_results):
    resultados=s.buscar_web(q,max_results)
    print("RESULTADOS BUSCA:",json.dumps({"consulta":q,"indisponivel":resultados is None,"urls":[r.get("href") or r.get("url") for r in resultados or []]},ensure_ascii=False),flush=True)
    return resultados
item=dict(base,id="mackenzie_completo_"+os.environ.get("GITHUB_RUN_ID","local"))
consultas=s.consultas_leads(item["instituicao"],s.alias_instituicao(item))
print("CONSULTAS PLANEJADAS:",len(consultas),flush=True)
ok=s.processar_instituicao(Piloto(),item,search_fn=busca,source_fn=fonte,continuar_falhas=True)
depois=nomes_banco()
resultado={"busca_terminou":ok,"consultas_planejadas":len(consultas),"base_antes":len(antes),"nomes_unicos_encontrados":len(vistos),"nomes_anteriores_reencontrados":[antes[k] for k in antes.keys() & vistos.keys()],"nomes_anteriores_nao_reencontrados":[antes[k] for k in antes.keys()-vistos.keys()],"novos_confirmados":[depois[k] for k in depois.keys()-antes.keys()],"base_depois":len(depois),"stats":s.stats}
print("COMPARACAO FINAL:",json.dumps(resultado,ensure_ascii=False),flush=True)
print("Teste isolado: não conclui nem avança outras faculdades.",flush=True)
if not ok or s.stats["erros"]: raise SystemExit(2)

# Revalidar descoberta e gravação com cópias oficiais e filtro institucional corrigidos.
