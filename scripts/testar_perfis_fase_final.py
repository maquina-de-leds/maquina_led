"""Descoberta automática real; nenhum nome pré-carregado para a busca."""
import json,runpy,signal,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scraper as s
import fontes_academicas as f
repo=s.SupabaseRepo.from_env();inicio=time.monotonic();ies='Universidade Presbiteriana Mackenzie'
runpy.run_path(str(Path(__file__).with_name('testar_mackenzie_completo.py')),run_name='__main__')
nomes={};metricas=[];pendentes=[]
def limite(*args):raise TimeoutError('Limite da consulta')
signal.signal(signal.SIGALRM,limite)
consultas=[q for q in s.consultas_documentos_alunos(ies,'Mackenzie') if 'º semestre' in q]
for q in consultas:
    if time.monotonic()-inicio>300:break
    try:
        signal.setitimer(signal.ITIMER_REAL,45)
        try:resultados=s.buscar_web(q,max_results=10)
        finally:signal.setitimer(signal.ITIMER_REAL,0)
        if resultados is None:raise RuntimeError('Buscador indisponível')
        print('BUSCA AUTOMÁTICA',json.dumps(dict(consulta=q,resultados=resultados),ensure_ascii=False),flush=True)
        extraidos=[]
        for resultado in resultados:
            for r in f.extrair_resultado_busca(resultado,ies,'Mackenzie'):
                chave=f.norm(r['nome'])
                if chave in nomes:continue
                url=resultado.get('href') or resultado.get('url')
                inst=r.get('instituicao')
                novo=s.salvar_lead(repo,r['nome'],inst,None,None,r['evidencia'],url,ano_forcado=r['ano'],periodo_forcado=r['periodo'],instituicao_alias='Mackenzie' if inst else None)
                assert repo.lead_existe(s.formatar_nome_pessoa(r['nome']),inst),'Gravação não confirmada'
                repetiu=s.salvar_lead(repo,r['nome'],inst,None,None,r['evidencia'],url,ano_forcado=r['ano'],periodo_forcado=r['periodo'],instituicao_alias='Mackenzie' if inst else None)
                assert repetiu is False,'Duplicação na repetição'
                nomes[chave]=dict(nome=r['nome'],novo=bool(novo),fonte=url,ano=r['ano'],periodo=r['periodo'],confirmado_no_banco=True)
                extraidos.append(r['nome'])
        metricas.append(dict(consulta=q,resultados=len(resultados),nomes=extraidos))
    except (TimeoutError,RuntimeError) as exc:
        # Erros de DB não são escondidos como fonte indisponível.
        if not isinstance(exc,TimeoutError) and str(exc)!='Buscador indisponível':raise
        pendentes.append(dict(consulta=q,erro=str(exc)))
print('RESULTADO PERFIS AUTOMÁTICOS',json.dumps(dict(segundos=round(time.monotonic()-inicio,1),nomes_unicos=len(nomes),novos=sum(r['novo'] for r in nomes.values()),existentes=sum(not r['novo'] for r in nomes.values()),nomes=list(nomes.values()),metricas=metricas,pendencias=pendentes,instagram_acessado=False,varredura_completa=False),ensure_ascii=False),flush=True)
if pendentes or len(metricas)!=len(consultas):raise SystemExit(2)
