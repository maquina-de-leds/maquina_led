"""Edição real: descobre artigos pelo índice, sem nomes pré-carregados."""
import json,runpy,signal,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scraper as s
import fontes_academicas as f
inicio=time.monotonic();repo=s.SupabaseRepo.from_env();ies='Universidade Presbiteriana Mackenzie'
runpy.run_path(str(Path(__file__).with_name('testar_mackenzie_completo.py')),run_name='__main__')
def limite(*a):raise TimeoutError('Limite de leitura')
signal.signal(signal.SIGALRM,limite)
def ler(u):
    restante=350-(time.monotonic()-inicio)
    if restante<=0:raise TimeoutError('Limite total')
    signal.setitimer(signal.ITIMER_REAL,min(20,restante))
    try:return f.carregar_fonte(u,ies,'Mackenzie')
    finally:signal.setitimer(signal.ITIMER_REAL,0)
indice='https://eventoscopq.mackenzie.br/jornada/pt_BR/issue/view/13'
_,links=ler(indice);confirmados=[];vistos=set();pendentes=[]
print('ÍNDICE REAL',json.dumps(dict(url=indice,artigos=links),ensure_ascii=False),flush=True)
for url in links:
    try:registros,anexos=ler(url)
    except Exception as exc:
        pendentes.append(dict(fonte=url,erro=type(exc).__name__));continue
    print('ARTIGO REAL',json.dumps(dict(url=url,nomes=[r['nome'] for r in registros],anexos=anexos),ensure_ascii=False),flush=True)
    for r in registros:
        chave=f.norm(r['nome'])
        if chave in vistos:continue
        novo=s.salvar_lead(repo,r['nome'],ies,None,None,r['evidencia'],url,ano_forcado=r['ano'],periodo_forcado=r['periodo'],instituicao_alias='Mackenzie',candidato_indicio=r.get('candidato_indicio',False))
        assert repo.lead_existe(s.formatar_nome_pessoa(r['nome']),ies)
        assert s.salvar_lead(repo,r['nome'],ies,None,None,r['evidencia'],url,ano_forcado=r['ano'],periodo_forcado=r['periodo'],instituicao_alias='Mackenzie',candidato_indicio=r.get('candidato_indicio',False)) is False
        vistos.add(chave);confirmados.append(dict(nome=r['nome'],novo=bool(novo),candidato_indicio=r.get('candidato_indicio',False),fonte=url,confirmado_no_banco=True))
print('RESULTADO JORNADA',json.dumps(dict(segundos=round(time.monotonic()-inicio,1),nomes_unicos=len(confirmados),novos=sum(r['novo'] for r in confirmados),existentes=sum(not r['novo'] for r in confirmados),registros=confirmados,pendencias=pendentes,varredura_completa=False,instagram_acessado=False),ensure_ascii=False),flush=True)
if not links or pendentes:raise SystemExit(2)
