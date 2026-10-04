"""Teste curto de descoberta e gravação real, sem alterar a fila nacional.
Repetição após corrigir nomes de recém-formadas citados no corpo do resultado.
Confere também a data editorial quando ela aparece depois do menu.
Valida a captura após a correção da alternância de janelas da fila.
"""
import json,re,signal,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scraper as s
import fontes_academicas as f

repo=s.SupabaseRepo.from_env(); gravados=[]; existentes=[]; falhas_operacionais=[]; repeticoes_confirmadas=[]
inicio=time.monotonic(); nomes={}; pendentes=[]; fontes=set(); consultas_feitas=0; metricas=[]; adiadas=[]; acessos_indisponiveis=[]; recuperadas=[]
ies='Universidade Presbiteriana Mackenzie'
print('FILA REAL ANTES DO TESTE',json.dumps([{'instituicao':i['instituicao'],'status':i.get('_status_checkpoint'),'janela_encerrada':i.get('_janela_encerrada')} for i in repo.fila_nacional()[:8]],ensure_ascii=False),flush=True)
consultas=[]  # teste focado das fontes descobertas na web; sem repetir as buscas já medidas

def registrar(registros,url):
    for r in registros:
        chave=f.norm(r['nome'])
        if chave in nomes: continue
        url=r.get('fonte_url') or url
        r['fonte_url']=url
        nomes[chave]=r
        try:
            rows=repo.client.table('leds').select('id,nome,instituicao,fonte_url').eq('fonte_url',url).ilike('nome',s.formatar_nome_pessoa(r['nome'])).execute().data or []
            if rows:
                existentes.append(r['nome']); print('DUPLICADO CONFIRMADO:',r['nome'],flush=True); continue
            inst=r.get('instituicao',ies)
            inseriu=s.salvar_lead(repo,r['nome'],inst,None,None,r['evidencia'],url,ano_forcado=r['ano'],periodo_forcado=r['periodo'],instituicao_alias='Mackenzie' if inst==ies else None)
            assert repo.lead_existe(s.formatar_nome_pessoa(r['nome']),inst), 'Gravação não confirmada'
            if inseriu:
                gravados.append(r['nome'])
                antes=s.stats['leads_salvos']
                repetiu=s.salvar_lead(repo,r['nome'],inst,None,None,r['evidencia'],url,ano_forcado=r['ano'],periodo_forcado=r['periodo'],instituicao_alias='Mackenzie' if inst==ies else None)
                assert not repetiu and s.stats['leads_salvos']==antes, 'Repetição inseriu novo registro'
                repeticoes_confirmadas.append(r['nome'])
            else: existentes.append(r['nome'])
            print('REGISTRO CONFIRMADO:',r['nome'],'| novo:',inseriu,flush=True)
        except Exception as exc:
            falhas_operacionais.append({'nome':r['nome'],'erro':str(exc)[:150]})
def esgotado(*args): raise TimeoutError('Limite de tempo desta operação')
signal.signal(signal.SIGALRM,esgotado)
def executar(fn,limite):
    restante=360-(time.monotonic()-inicio)
    if restante<=0: raise TimeoutError('Limite total de seis minutos')
    signal.setitimer(signal.ITIMER_REAL,min(limite,restante))
    try: return fn()
    finally: signal.setitimer(signal.ITIMER_REAL,0)
# Fonte pública descoberta na web; nomes são extraídos pelo leitor, não pré-carregados.
fontes_alvo=[('https://uniarp.edu.br/wp-content/uploads/2025/11/Edital-Bancas-finais-de-TCC-II-Nutricao.pdf','Universidade Alto Vale do Rio do Peixe','UNIARP'),('https://pt.scribd.com/document/929685366/Resumo-Ampliado-Pre-TCC-Ariane','Universidade Pitágoras Unopar','Unopar')]
for fonte_alvo,instituicao_alvo,alias_alvo in fontes_alvo:
    try:
        registros,_=executar(lambda:f.carregar_fonte(fonte_alvo,instituicao_alvo,alias_alvo),20)
        print('CABEÇALHO REAL',json.dumps({'fonte':fonte_alvo,'registros':registros},ensure_ascii=False),flush=True)
        registrar(registros,fonte_alvo)
        if not registros:
            documento=f.CACHE_DOCUMENTOS.get(fonte_alvo)
            print('DIAGNÓSTICO DE FORMATO',json.dumps({'fonte':fonte_alvo,'bytes':len(documento[0]) if documento else None,'tipo':documento[1] if documento else None,'pdf':bool(documento and documento[0].startswith(b'%PDF'))},ensure_ascii=False),flush=True)
            if documento and documento[0].startswith(b'%PDF'):
                import io,pdfplumber
                with pdfplumber.open(io.BytesIO(documento[0])) as pdf:
                    for numero,pagina in enumerate(pdf.pages[:2]):
                        print('DIAGNÓSTICO DE TABELA',json.dumps({'pagina':numero+1,'texto':(pagina.extract_text() or '')[:3000],'tabelas':pagina.extract_tables()},ensure_ascii=False),flush=True)
    except Exception as exc:
        pendentes.append({'fonte':fonte_alvo,'erro':str(exc)[:150]})
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
            if re.search(r'\b(?:morre|morreu|falecimento|obito)\b',f.norm(str(resultado.get('title') or ''))):
                adiadas.append({'fonte':url,'motivo':'Notícia de falecimento; pessoa fora do público de captura'})
                continue
            host=s.urlparse(url).hostname or ''
            if 'nutricao' not in resumo and not (host.endswith('mackenzie.br') and any(t in url for t in ['mostra-de-tcc','.pdf'])):
                adiadas.append({'fonte':url,'motivo':'Sem evidência de Nutrição no resumo; fora do diagnóstico rápido'})
                continue
            if not re.search(f.FASE,resumo) and not (host.endswith('mackenzie.br') and any(t in url for t in ['mostra-de-tcc','.pdf'])):
                adiadas.append({'fonte':url,'motivo':'Resumo sem indício acadêmico; página genérica fora do teste curto'})
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
                acessos_indisponiveis.append({'fonte':url,'erro':str(exc)[:150]})
                try:
                    registros,_=executar(lambda:f.recuperar_fonte_na_busca(url,ies,'Mackenzie',s.buscar_web),30)
                    if not registros: raise RuntimeError('Nenhuma evidência recuperada em publicação alternativa')
                    registrar(registros,url)
                    recuperadas.append({'fonte':url,'nomes':len(registros),'fontes_usadas':list({r.get('fonte_url') for r in registros})})
                except Exception as recuperacao:
                    pendentes.append({'fonte':url,'erro':str(exc)[:150],'recuperacao':str(recuperacao)[:150]})
    except Exception as exc:
        falhas_operacionais.append({'consulta':consulta,'erro':str(exc)[:150]})
    finally:
        metrica={'consulta':consulta,'segundos':round(time.monotonic()-comeco,1),'nomes_adicionados':len(set(nomes)-anteriores)}
        metricas.append(metrica)
        print('TEMPO E RESULTADO',json.dumps(metrica,ensure_ascii=False),flush=True)
nao_executadas=consultas[consultas_feitas:]
print('DIAGNOSTICO RAPIDO',json.dumps({'segundos':round(time.monotonic()-inicio,1),'consultas_executadas':consultas_feitas,'consultas_nao_executadas':nao_executadas,'nomes_unicos':len(nomes),'registros':list(nomes.values()),'pendencias':pendentes,'acessos_diretos_indisponiveis':acessos_indisponiveis,'fontes_recuperadas':recuperadas,'gravacoes_no_banco':len(gravados),'novos_confirmados':gravados,'duplicados_confirmados':existentes,'varredura_completa':False,'falhas_operacionais':falhas_operacionais,'repeticoes_sem_reinserir':repeticoes_confirmadas},ensure_ascii=False),flush=True)
print('EFICIENCIA',json.dumps({'buscas':metricas,'fontes_adiadas':adiadas},ensure_ascii=False),flush=True)
if pendentes: print("AVISOS EXTERNOS: fontes permanecem pendentes; alunos não foram invalidados",flush=True)
if falhas_operacionais or nao_executadas: raise SystemExit(2)
