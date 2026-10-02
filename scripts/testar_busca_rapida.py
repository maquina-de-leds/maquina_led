"""Diagnóstico real de descoberta em até seis minutos, sem gravar no banco."""
import json,signal,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scraper as s
import fontes_academicas as f

inicio=time.monotonic(); nomes={}; pendentes=[]; fontes=set(); consultas_feitas=0
ies='Universidade Presbiteriana Mackenzie'
sinais=['"TCC"','"formandos"','"grupo de alunos"','"iniciação científica"','"projetos aprovados"','"e-book" "alunas"']
consultas=[f'"Mackenzie" Nutrição {sinal} {ano}' for sinal in sinais[:4] for ano in (2025,2026)]
consultas += ['"Nutrição" "recém-formada" "2025"','"Nutrição" "formanda" "2026"',
              '"Nutrição" "7º semestre"','"Nutrição" "8º semestre"']
def esgotado(*args): raise TimeoutError('Limite de tempo desta operação')
signal.signal(signal.SIGALRM,esgotado)
def executar(fn,limite):
    restante=360-(time.monotonic()-inicio)
    if restante<=0: raise TimeoutError('Limite total de seis minutos')
    signal.setitimer(signal.ITIMER_REAL,min(limite,restante))
    try: return fn()
    finally: signal.setitimer(signal.ITIMER_REAL,0)
for consulta in consultas:
    if time.monotonic()-inicio>=360: break
    consultas_feitas+=1
    try:
        resultados=executar(lambda:s.buscar_web(consulta,max_results=6),30)
        if resultados is None: raise RuntimeError('Buscador indisponível após verificar e repetir')
        print('BUSCA REAL',json.dumps({'consulta':consulta,'resultados':resultados},ensure_ascii=False),flush=True)
        for resultado in resultados:
            url=resultado.get('href') or resultado.get('url') or ''
            registros=f.extrair_resultado_busca(resultado,ies,'Mackenzie')
            for r in registros: nomes[f.norm(r['nome'])]=r
            if url in fontes or not f.url_permitida(url): continue
            resumo=f.norm(str(resultado.get('title') or '')+' '+str(resultado.get('body') or ''))
            host=s.urlparse(url).hostname or ''
            if 'nutricao' not in resumo and not (host=='mackenzie.br' or host.endswith('.mackenzie.br')):
                continue
            if s.urlparse(url).path.rstrip('/').endswith('/pg'):
                print('PAGINA DE NAVEGACAO, FORA DO DIAGNOSTICO RAPIDO',url,flush=True)
                continue
            fontes.add(url)
            try:
                registros,_=executar(lambda:f.carregar_fonte(url,ies,'Mackenzie'),20)
                print('FONTE REAL',url,json.dumps(registros,ensure_ascii=False),flush=True)
                for r in registros: nomes[f.norm(r['nome'])]=r
            except Exception as exc:
                pendentes.append({'fonte':url,'erro':str(exc)[:150]})
    except Exception as exc:
        pendentes.append({'consulta':consulta,'erro':str(exc)[:150]})
nao_executadas=consultas[consultas_feitas:]
print('DIAGNOSTICO RAPIDO',json.dumps({'segundos':round(time.monotonic()-inicio,1),'consultas_executadas':consultas_feitas,'consultas_nao_executadas':nao_executadas,'nomes_unicos':len(nomes),'registros':list(nomes.values()),'pendencias':pendentes,'gravacoes_no_banco':0,'varredura_completa':False},ensure_ascii=False),flush=True)
if pendentes or nao_executadas: raise SystemExit(2)
