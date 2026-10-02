"""Teste curto de descoberta e gravação real, sem alterar a fila nacional."""
import json,signal,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scraper as s
import fontes_academicas as f

repo=s.SupabaseRepo.from_env(); gravados=[]; existentes=[]
inicio=time.monotonic(); nomes={}; pendentes=[]; fontes=set(); consultas_feitas=0; metricas=[]; adiadas=[]
ies='Universidade Presbiteriana Mackenzie'
consultas=['"Nutrição" "recém-formada" 2025 notícia',
           '"Nutrição" "formada em fevereiro" 2025',
           '"Mackenzie" "Nutrição" "aluna" "premiada" 2026',
           '"Nutrição" "formandos" 2026 nomes']
def registrar(registros,url):
    for r in registros:
        chave=f.norm(r['nome'])
        if chave in nomes: continue
        r['fonte_url']=url
        nomes[chave]=r
        try:
            rows=repo.client.table('leds').select('id,nome,instituicao,fonte_url').eq('fonte_url',url).ilike('nome',s.formatar_nome_pessoa(r['nome'])).execute().data or []
            if rows:
                existentes.append(r['nome']); print('DUPLICADO CONFIRMADO:',r['nome'],flush=True); continue
            inst=r.get('instituicao',ies)
            inseriu=s.salvar_lead(repo,r['nome'],inst,None,None,r['evidencia'],url,ano_forcado=r['ano'],periodo_forcado=r['periodo'],instituicao_alias='Mackenzie' if inst==ies else None)
            assert repo.lead_existe(s.formatar_nome_pessoa(r['nome']),inst), 'Gravação não confirmada'
            if inseriu: gravados.append(r['nome'])
            else: existentes.append(r['nome'])
            print('REGISTRO CONFIRMADO:',r['nome'],'| novo:',inseriu,flush=True)
        except Exception as exc:
            pendentes.append({'nome':r['nome'],'erro':str(exc)[:150]})
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
    comeco=time.monotonic(); anteriores=set(nomes)
    try:
        resultados=executar(lambda:s.buscar_web(consulta,max_results=6),30)
        if resultados is None: raise RuntimeError('Buscador indisponível após verificar e repetir')
        print('BUSCA REAL',json.dumps({'consulta':consulta,'resultados':resultados},ensure_ascii=False),flush=True)
        for resultado in resultados:
            url=resultado.get('href') or resultado.get('url') or ''
            registros=f.extrair_resultado_busca(resultado,ies,'Mackenzie')
            registrar(registros,url)
            if url in fontes or not f.url_permitida(url): continue
            resumo=f.norm(str(resultado.get('title') or '')+' '+str(resultado.get('body') or ''))
            host=s.urlparse(url).hostname or ''
            if 'nutricao' not in resumo and not (host.endswith('mackenzie.br') and any(t in url for t in ['mostra-de-tcc','.pdf'])):
                adiadas.append({'fonte':url,'motivo':'Sem evidência de Nutrição no resumo; fora do diagnóstico rápido'})
                continue
            if any(t in resumo for t in ['exemplo de curriculo','modelo de curriculo','modelos de curriculo','exemplos de curriculo']):
                adiadas.append({'fonte':url,'motivo':'Página de modelo de currículo, não evidência de pessoa real'})
                continue
            if s.urlparse(url).path.rstrip('/').endswith('/pg'):
                print('PAGINA DE NAVEGACAO, FORA DO DIAGNOSTICO RAPIDO',url,flush=True)
                continue
            fontes.add(url)
            try:
                registros,_=executar(lambda:f.carregar_fonte(url,ies,'Mackenzie'),20)
                print('FONTE REAL',url,json.dumps(registros,ensure_ascii=False),flush=True)
                registrar(registros,url)
            except Exception as exc:
                pendentes.append({'fonte':url,'erro':str(exc)[:150]})
    except Exception as exc:
        pendentes.append({'consulta':consulta,'erro':str(exc)[:150]})
    finally:
        metrica={'consulta':consulta,'segundos':round(time.monotonic()-comeco,1),'nomes_adicionados':len(set(nomes)-anteriores)}
        metricas.append(metrica)
        print('TEMPO E RESULTADO',json.dumps(metrica,ensure_ascii=False),flush=True)
nao_executadas=consultas[consultas_feitas:]
print('DIAGNOSTICO RAPIDO',json.dumps({'segundos':round(time.monotonic()-inicio,1),'consultas_executadas':consultas_feitas,'consultas_nao_executadas':nao_executadas,'nomes_unicos':len(nomes),'registros':list(nomes.values()),'pendencias':pendentes,'gravacoes_no_banco':len(gravados),'novos_confirmados':gravados,'duplicados_confirmados':existentes,'varredura_completa':False},ensure_ascii=False),flush=True)
print('EFICIENCIA',json.dumps({'buscas':metricas,'fontes_adiadas':adiadas},ensure_ascii=False),flush=True)
if pendentes or nao_executadas: raise SystemExit(2)
