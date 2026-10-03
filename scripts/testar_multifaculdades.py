"""Coleção real PUC Goiás e comparação Mackenzie; orçamento por etapa de seis minutos."""
import json,signal,sys,time,runpy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import requests
import scraper as s
from colecoes_academicas import ler_colecao
repo=s.SupabaseRepo.from_env(); inicio=time.monotonic(); fila=['https://repositorio.pucgoias.edu.br/jspui/handle/123456789/79']; vistas=set(); nomes={}; novos=[]; existentes=[]; pendentes=[]
def limite(*a): raise TimeoutError('Orçamento de seis minutos atingido')
signal.signal(signal.SIGALRM,limite);signal.alarm(360)
while fila:
    url=fila.pop(0)
    if url in vistas: continue
    try:
        r=requests.get(url,timeout=(8,18));r.raise_for_status()
        dados=ler_colecao(r.text,r.url,'Pontifícia Universidade Católica de Goiás','pucgoias')
        print('PAGINA PUC',json.dumps(dict(url=url,documentos_elegiveis=len(dados['documentos']),proximas=dados['proximas']),ensure_ascii=False),flush=True)
        vistas.add(url)
        for d in dados['documentos']:
            for lead in d['registros']:
                chave=s.normalizar(lead['nome'])
                if chave in nomes:continue
                nomes[chave]=lead
                inseriu=s.salvar_lead(repo,lead['nome'],lead['instituicao'],None,None,lead['evidencia'],lead['fonte_url'],ano_forcado=lead['ano'],periodo_forcado=lead['periodo'],instituicao_alias='pucgoias')
                assert repo.lead_existe(lead['nome'],lead['instituicao'])
                (novos if inseriu else existentes).append(lead['nome'])
        fila.extend(u for u in dados['proximas'] if u not in vistas)
    except Exception as e:
        pendentes.append(dict(url=url,erro=type(e).__name__));break
for lead in nomes.values():
    assert not s.salvar_lead(repo,lead['nome'],lead['instituicao'],None,None,lead['evidencia'],lead['fonte_url'],ano_forcado=lead['ano'],periodo_forcado=lead['periodo'],instituicao_alias='pucgoias')
    assert repo.lead_existe(lead['nome'],lead['instituicao'])
signal.alarm(0)
print('RESULTADO PUC',json.dumps(dict(segundos=round(time.monotonic()-inicio,1),paginas_lidas=len(vistas),nomes_unicos=len(nomes),novos_confirmados=novos,existentes_confirmados=existentes,repeticao_sem_inserir=len(nomes),pendencias=pendentes,proximas_pendentes=fila,colecao_completa=not pendentes and not fila),ensure_ascii=False),flush=True)
# Mantém as quatro fontes reais de referência e compara gravações atuais.
try:
    runpy.run_path(str(Path(__file__).with_name('testar_mackenzie_completo.py')),run_name='__main__')
except SystemExit as e:
    pendentes.append(dict(etapa='referencia_mackenzie',codigo=e.code))
# Busca adicional curta, independente da releitura da referência.
import fontes_academicas as f
adicionais={}; novos_m=[]; falhas_m=[]
for consulta in ['Mackenzie Nutrição 2026 TCC autores alunos','Mackenzie Nutrição 2025 grupo alunos formatura']:
    try:
        signal.alarm(45)
        resultados=s.buscar_web(consulta,max_results=6)
        if resultados is None: raise RuntimeError('Buscador indisponível')
        print('BUSCA ADICIONAL MACKENZIE',json.dumps(dict(consulta=consulta,resultados=resultados),ensure_ascii=False),flush=True)
        for resultado in resultados:
            registros=f.extrair_resultado_busca(resultado,'Universidade Presbiteriana Mackenzie','Mackenzie')
            for lead in registros:
                chave=s.normalizar(lead['nome'])
                if chave in adicionais: continue
                adicionais[chave]=lead
                inst=lead.get('instituicao')
                salvo=s.salvar_lead(repo,lead['nome'],inst,None,None,lead['evidencia'],lead['fonte_url'],ano_forcado=lead['ano'],periodo_forcado=lead['periodo'],instituicao_alias='Mackenzie' if inst else None)
                assert repo.lead_existe(lead['nome'],inst)
                if salvo:novos_m.append(lead['nome'])
    except Exception as e: falhas_m.append(dict(consulta=consulta,erro=type(e).__name__))
    finally:signal.alarm(0)
print('EXPLORACAO MACKENZIE',json.dumps(dict(nomes_unicos=len(adicionais),novos_confirmados=novos_m,nomes=list(adicionais),pendencias=falhas_m),ensure_ascii=False),flush=True)
if pendentes or fila:raise SystemExit(2)
