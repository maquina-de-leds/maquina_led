"""Compara buscadores no runner; sem Supabase, credenciais ou alterações de dados."""
import json,signal,time,sys,importlib.metadata
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ddgs import DDGS
import requests
import fontes_academicas as f
inicio=time.monotonic();medidas=[]
print('VERSAO DDGS',importlib.metadata.version('ddgs'),flush=True)
def limite(*a):raise TimeoutError('Limite desta consulta')
signal.signal(signal.SIGALRM,limite)
for backend in ['auto','duckduckgo','bing','brave','google']:
 for consulta in ['Brasil','Mackenzie Nutrição e-book','site:mackenzie.br "mostra-de-tcc"']:
  comeco=time.monotonic();m=dict(backend=backend,consulta=consulta)
  try:
   signal.alarm(15)
   with DDGS(timeout=10) as d:
    resultados=list(d.text(consulta,region='br-pt',safesearch='moderate',max_results=5,backend=backend) or [])
   m.update(resultados=len(resultados),amostra=resultados[:3],erro=None)
  except Exception as e:m.update(resultados=None,erro=type(e).__name__,mensagem=str(e)[:250])
  finally:signal.alarm(0)
  m['segundos']=round(time.monotonic()-comeco,1);medidas.append(m);print('MEDIDA BUSCADOR',json.dumps(m,ensure_ascii=False),flush=True)
for url in ['https://www.mackenzie.br/universidade/unidades-academicas/ccbs/tcc-e-pesquisa/mostra-de-tcc','https://www.mackenzie.br/memorias/150-anos/acontece/arquivo/n/a/i/alunos-de-nutricao-criam-e-book-de-receitas-saudaveis-e-praticas']:
 try:
  signal.alarm(20);r=requests.get(url,timeout=15);r.raise_for_status();registros,_=f.ler_html(r.text,r.url,'Universidade Presbiteriana Mackenzie','Mackenzie');print('CONTROLE FONTE',json.dumps(dict(url=url,status=r.status_code,nomes=len(registros)),ensure_ascii=False),flush=True)
 except Exception as e:print('CONTROLE INDISPONIVEL',json.dumps(dict(url=url,erro=type(e).__name__),ensure_ascii=False),flush=True)
 finally:signal.alarm(0)
print('DIAGNOSTICO FINAL',json.dumps(dict(segundos=round(time.monotonic()-inicio,1),medidas=medidas,gravacoes=0),ensure_ascii=False),flush=True)
