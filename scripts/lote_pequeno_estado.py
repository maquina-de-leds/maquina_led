"""Lote real limitado de Santa Catarina; conserva a fila nacional e retoma consultas pendentes."""
import json,os,signal,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scraper as s
import fontes_academicas as f
inicio=time.monotonic(); uf='SC'; problemas=[]; consultas_feitas=[]; fontes_falhas=[]
signal.signal(signal.SIGALRM,lambda *a:(_ for _ in ()).throw(TimeoutError('Limite de pesquisa do lote atingido')))
def executar(fn,limite):
    restante=360-(time.monotonic()-inicio)
    if restante<=0: raise TimeoutError('Orçamento de seis minutos esgotado')
    signal.setitimer(signal.ITIMER_REAL,min(limite,restante))
    try: return fn()
    finally: signal.setitimer(signal.ITIMER_REAL,0)
real=s.SupabaseRepo.from_env()
registros=[]; offset=0
while True:
    q=real.client.table('instituicoes_nutricao').select('*').eq('origem',s.ORIGEM_IES).order('id').range(offset,offset+999)
    lote=executar(lambda:q.execute(),20).data or []; registros.extend(lote)
    if len(lote)<1000: break
    offset+=1000
nomes_estado={s.normalizar(r['instituicao']) for r in registros if r['estado']==uf and s.normalizar(r['curso'])=='nutricao'}
fila=executar(real.fila_nacional,40)
# Seleção estável permite repetir o mesmo lote sem saltar para novas faculdades.
itens=sorted([x for x in fila if s.normalizar(x['instituicao']) in nomes_estado],key=lambda x:s.normalizar(x['instituicao']))[:2]
assert len(itens)==2, 'Não há duas faculdades elegíveis na fila para este lote'
print('LOTE SELECIONADO',json.dumps({'uf':uf,'rodada':os.getenv('GITHUB_RUN_ATTEMPT','1'),'faculdades':[x['instituicao'] for x in itens],'consultas_por_faculdade':2,'limite_pesquisa_segundos':360},ensure_ascii=False),flush=True)
class Observador:
    def __init__(self): self.novos=[]; self.existentes=[]; self.candidatos=[]
    def __getattr__(self,k): return getattr(real,k)
    def inserir_lead(self,dados):
        executar(lambda:real.inserir_lead(dados),20)
        assert executar(lambda:real.lead_existe(dados['nome'],dados['instituicao']),20), 'Novo lead não confirmado'
        self.novos.append({'nome':dados['nome'],'instituicao':dados['instituicao'],'fonte':dados['fonte_url']})
    def lead_da_fonte(self,nome,url):
        self.candidatos.append(nome)
        r=executar(lambda:real.lead_da_fonte(nome,url),20)
        if r is not None: self.existentes.append(nome)
        return r
    def lead_existe(self,nome,inst):
        r=executar(lambda:real.lead_existe(nome,inst),20)
        if r: self.existentes.append(nome)
        return r
repo=Observador(); s.PAUSA_ENTRE_BUSCAS=0; resultados=[]
def buscar(q,max_results):
    antes=time.monotonic()
    r=executar(lambda:s.buscar_web(q,max_results),25)
    consultas_feitas.append(q)
    print('BUSCA LOTE REAL',json.dumps({'consulta':q,'segundos':round(time.monotonic()-antes,1),'resultados':r},ensure_ascii=False),flush=True)
    return r
def fonte(url,inst,alias):
    try: return executar(lambda:f.carregar_fonte(url,inst,alias),20)
    except Exception as e:
        fontes_falhas.append({'fonte':url,'erro':str(e)[:160]}); raise
for item in itens:
    etapa=s.etapa_captacao_item(item); antes=real.controle_get(etapa) or {}; n0=len(repo.novos); d0=len(repo.existentes); c0=len(repo.candidatos); q0=len(consultas_feitas)
    print('FACULDADE INICIO',json.dumps({'instituicao':item['instituicao'],'etapa':etapa,'checkpoint_anterior':{'status':antes.get('status'),'indice':antes.get('indice_pesquisa'),'consulta':antes.get('consulta_atual')}},ensure_ascii=False),flush=True)
    try:
        ok=s.processar_instituicao(repo,item,search_fn=buscar,source_fn=fonte,continuar_falhas=True,limite_consultas=2)
        depois=real.controle_get(etapa) or {}
        retomada=bool(antes.get('status')=='processando' and not antes.get('ultimo_erro') and antes.get('consulta_atual'))
        if retomada and consultas_feitas[q0:]:
            assert consultas_feitas[q0]==antes['consulta_atual'], 'Retomada não começou na consulta persistida'
        assert depois.get('status')!='concluido' or depois.get('indice_pesquisa')==depois.get('total_pesquisas'), 'Faculdade concluída com pesquisa incompleta'
        if not ok or depois.get('status')=='erro': problemas.append({'faculdade':item['instituicao'],'erro':depois.get('ultimo_erro')})
        resultados.append({'faculdade':item['instituicao'],'checkpoint_real':depois,'retomada_confirmada':retomada,'nomes_unicos_encontrados':sorted(set(repo.candidatos[c0:])),'novos_confirmados':repo.novos[n0:],'existentes_confirmados':sorted(set(repo.existentes[d0:])),'consultas_realizadas':consultas_feitas[q0:]})
    except Exception as e:
        problemas.append({'faculdade':item['instituicao'],'erro':str(e)[:180],'checkpoint_preservado':real.controle_get(etapa)})
print('RESULTADO LOTE ESTADUAL',json.dumps({'uf':uf,'segundos':round(time.monotonic()-inicio,1),'faculdades':resultados,'novos_confirmados':repo.novos,'existentes_confirmados':sorted(set(repo.existentes)),'nomes_unicos_encontrados':sorted(set(repo.candidatos)),'fontes_inacessiveis':fontes_falhas,'pendencias':problemas,'agendamento_ativado':False},ensure_ascii=False),flush=True)
if problemas or len(resultados)!=2: raise SystemExit(2)
