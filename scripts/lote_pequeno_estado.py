"""Reteste corrigido do lote real limitado de Santa Catarina; conserva a fila nacional e retoma consultas pendentes."""
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
ufsc_item=next(x for x in fila if s.normalizar(x['instituicao'])=='universidade federal de santa catarina')
itens.append(ufsc_item)
assert len(itens)==3, 'Não há duas faculdades elegíveis na fila para este lote'
print('LOTE SELECIONADO',json.dumps({'uf':uf,'rodada':os.getenv('GITHUB_RUN_ATTEMPT','1'),'faculdades':[x['instituicao'] for x in itens],'consultas_por_faculdade':2,'limite_pesquisa_segundos':360},ensure_ascii=False),flush=True)
class Observador:
    def __init__(self): self.novos=[]; self.existentes=[]; self.candidatos=[]
    def __getattr__(self,k): return getattr(real,k)
    def inserir_lead(self,dados):
        executar(lambda:real.inserir_lead(dados),20)
        assert executar(lambda:real.lead_existe(dados['nome'],dados['instituicao']),20), 'Novo lead não confirmado'
        self.novos.append({'nome':dados['nome'],'instituicao':dados['instituicao'],'fonte':dados['fonte_url']})
    def fontes_da_instituicao(self,*a): return [] # Este teste mede busca nova, sem injetar fontes já salvas.
    def lead_da_fonte(self,nome,url):
        self.candidatos.append(nome)
        r=executar(lambda:real.lead_da_fonte(nome,url),20)
        if r is not None: self.existentes.append(nome)
        return r
    def lead_existe(self,nome,inst):
        r=executar(lambda:real.lead_existe(nome,inst),20)
        if r: self.existentes.append(nome)
        return r
# Correção reversível do único rótulo comprovadamente salvo como pessoa.
erro_url="https://www.passeidireto.com/arquivo/201106163/protocolo-tcc-para-imagem-corporal"
rotulo=executar(lambda:real.lead_da_fonte("Aula Hortaliças",erro_url),20)
if rotulo:
    executar(lambda:real.client.table('leds').update(dict(qualificado=False,nao_contatar=True,status="revisao")).eq('id',rotulo['id']).eq('nome','Aula Hortaliças').eq('fonte_url',erro_url).execute(),20)
    print("ROTULO EM REVISAO REVERSIVEL",json.dumps(dict(id=rotulo['id'],nome=rotulo['nome'],estado_anterior={k:rotulo.get(k) for k in ['qualificado','nao_contatar','status']}),ensure_ascii=False),flush=True)
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
        delta_criterios=int(depois.get('total_pesquisas') or 0)-int(antes.get('total_pesquisas') or 0)
        retomada=bool(antes.get('status')=='processando' and not antes.get('ultimo_erro') and antes.get('consulta_atual') and delta_criterios in (0,1))
        if retomada and consultas_feitas[q0:]:
            assert consultas_feitas[q0]==antes['consulta_atual'], 'Retomada não começou na consulta persistida'
        assert depois.get('status')!='concluido' or depois.get('indice_pesquisa')==depois.get('total_pesquisas'), 'Faculdade concluída com pesquisa incompleta'
        if not ok or depois.get('status')=='erro': problemas.append({'faculdade':item['instituicao'],'erro':depois.get('ultimo_erro')})
        resultados.append({'faculdade':item['instituicao'],'checkpoint_real':depois,'retomada_confirmada':retomada,'novos_criterios_reabriram_pesquisa':delta_criterios>1,'nomes_unicos_encontrados':sorted(set(repo.candidatos[c0:])),'novos_confirmados':repo.novos[n0:],'existentes_confirmados':sorted(set(repo.existentes[d0:])),'consultas_realizadas':consultas_feitas[q0:]})
    except Exception as e:
        problemas.append({'faculdade':item['instituicao'],'erro':str(e)[:180],'checkpoint_preservado':real.controle_get(etapa)})
print('RESULTADO LOTE ESTADUAL',json.dumps({'uf':uf,'segundos':round(time.monotonic()-inicio,1),'faculdades':resultados,'novos_confirmados':repo.novos,'existentes_confirmados':sorted(set(repo.existentes)),'nomes_unicos_encontrados':sorted(set(repo.candidatos)),'fontes_inacessiveis':fontes_falhas,'pendencias':problemas,'agendamento_ativado':False},ensure_ascii=False),flush=True)
if problemas or len(resultados)!=3: raise SystemExit(2)

# Fontes reais identificadas em pesquisa assistida; não contam como descoberta automática.
fontes_ufsc=["https://repositorio.ufsc.br/handle/123456789/270578?show=full", "https://repositorio.ufsc.br/handle/123456789/270580?show=full"]
ufsc=[]
for url in fontes_ufsc:
    registros,_=executar(lambda:f.carregar_fonte(url,"Universidade Federal de Santa Catarina","UFSC"),25)
    assert registros, "Fonte UFSC não forneceu autores qualificados"
    for r in registros:
        assert r["ano"]==2025 and f.pessoa(r["nome"]), "Autor fora do critério"
        args=dict(repo=real,nome=r["nome"],instituicao="Universidade Federal de Santa Catarina",cidade=None,uf=None,texto=r["evidencia"],url=url,ano_forcado=r["ano"],periodo_forcado=r["periodo"],instituicao_alias="UFSC")
        novo=executar(lambda:s.salvar_lead(**args),20)
        confirmado=executar(lambda:real.lead_existe(r["nome"],args["instituicao"]),20)
        assert confirmado, "Gravação não confirmada no Supabase"
        antes=executar(lambda:real.lead_da_fonte(r["nome"],url),20)
        repetido=executar(lambda:s.salvar_lead(**args),20)
        depois=executar(lambda:real.lead_da_fonte(r["nome"],url),20)
        assert not repetido and antes and depois and antes["id"]==depois["id"], "Releitura duplicou ou trocou registro"
        ufsc.append(dict(nome=r["nome"],id=depois["id"],novo=novo,confirmado=confirmado,releitura_duplicada_ignorada=True,fonte=url))
print("RESULTADO REPOSITORIO SC",json.dumps(dict(tipo="fontes_identificadas_em_pesquisa_assistida",nomes_unicos=len({r["nome"] for r in ufsc}),novos_confirmados=sum(r["novo"] for r in ufsc),existentes_confirmados=sum(not r["novo"] for r in ufsc),releituras_duplicadas_ignoradas=len(ufsc),leads=ufsc,segundos_totais=round(time.monotonic()-inicio,1)),ensure_ascii=False),flush=True)
