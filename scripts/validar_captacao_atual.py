"""Piloto nacional limitado: audita a fila e captura em duas faculdades, sem avançar a fila nacional."""
import json,signal,sys,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scraper as s
import fontes_academicas as f
inicio=time.monotonic(); repo=s.SupabaseRepo.from_env(); problemas=[]; casos_reais=[]; buscas=[]
def esgotado(*a): raise TimeoutError('Orçamento de seis minutos do piloto esgotado')
signal.signal(signal.SIGALRM,esgotado)
def executar(fn,segundos):
    restante=360-(time.monotonic()-inicio)
    if restante<=0: raise TimeoutError('Orçamento de seis minutos do piloto esgotado')
    signal.setitimer(signal.ITIMER_REAL,min(segundos,restante))
    try: return fn()
    finally: signal.setitimer(signal.ITIMER_REAL,0)
def ler_tabela(tabela,origem=None):
    dados=[]; offset=0
    while True:
        q=repo.client.table(tabela).select('*').order('id').range(offset,offset+999)
        if origem: q=q.eq('origem',origem)
        lote=executar(lambda:q.execute(),20).data or []; dados.extend(lote)
        if len(lote)<1000: return dados
        offset+=1000
dados=ler_tabela('instituicoes_nutricao',s.ORIGEM_IES); fila=s.agrupar_faculdades(dados)
ufs=sorted({r['estado'] for r in dados}); esperadas=sorted(x[0] for x in s.ESTADOS)
assert ufs==esperadas, 'Cobertura de estados incompleta'
assert all(s.normalizar(r.get('curso'))=='nutricao' for r in dados), 'Curso diferente na fila'
assert len({s.normalizar(x['instituicao']) for x in fila})==len(fila), 'Faculdade duplicada na fila'
assert all(x['estado'] is None and x['cidade'] is None for x in fila), 'Restrição municipal inesperada'
pendentes=executar(repo.fila_nacional,40)
assert all(x['_status_checkpoint']!='concluido' for x in pendentes)
print('AUDITORIA FILA',json.dumps({'faculdades_nutricao':len(fila),'ufs':ufs,'pendentes':len(pendentes),'primeiras':[{'instituicao':x['instituicao'],'checkpoint':x['_status_checkpoint']} for x in pendentes[:5]],'municipio_e_uf_nao_restringem_busca':True},ensure_ascii=False),flush=True)
assert (repo.controle_get(s.ETAPA_MIGRACAO_BUSCA) or {}).get('status')=='concluido', 'Migração V5.8 ainda pendente'
class Piloto:
    def __init__(self): self.cp={}; self.confirmados=[]; self.novos=[]; self.transicoes=[]
    def __getattr__(self,k): return getattr(repo,k)
    def fontes_da_instituicao(self,*a): return []
    def controle_get(self,etapa): return self.cp.get(etapa)
    def controle_salvar(self,etapa,dados): self.cp[etapa]={**dados,'estado':dados.get('estado') or 'BR'}
    def atualizar_instituicao(self,iid,**dados): self.transicoes.append({'id':iid,**dados})
    def inserir_lead(self,dados):
        repo.inserir_lead(dados)
        assert repo.lead_existe(dados['nome'],dados['instituicao']), 'Nova gravação não confirmada'
        self.novos.append(dados['nome'])
    def lead_existe(self,nome,instituicao):
        existe=repo.lead_existe(nome,instituicao)
        if existe: self.confirmados.append(nome)
        return existe
    def lead_da_fonte(self,nome,url):
        row=repo.lead_da_fonte(nome,url)
        if row is not None: self.confirmados.append(nome)
        return row
piloto=Piloto(); s.PAUSA_ENTRE_BUSCAS=0
casos=[('Unochapecó','https://uno.edu.br/noticias/outorga-de-grau-1',13),('UniAteneu','https://uniateneu.edu.br/uniateneu-realizou-colacao-de-grau-para-celebrar-a-formatura-de-alunos-de-diferentes-cursos-de-graduacao/',1)]
for alias,url,referencia in casos:
    try:
        item=next(x for x in fila if s.normalizar(s.alias_instituicao(x) or '')==s.normalizar(alias))
        todas=s.consultas_leads(item['instituicao'],s.alias_instituicao(item))
        assert all('mackenzie' not in s.normalizar(q) for q in todas), 'Faculdade anterior vazou na consulta'
        assert all(str(ano) in ' '.join(todas) for ano in [2025,2026])
        tcc=next(q for q in todas if f'"{s.alias_instituicao(item)}"' in q and '"TCC"' in q and '2025' in q)
        formandos=next(q for q in todas if f'"{s.alias_instituicao(item)}"' in q and '"formandos"' in q and '2026' in q)
        oficial='FONTE OFICIAL CONTROLADA '+item['instituicao']; consultas=[oficial,tcc,formandos]
        print('CONSULTAS PILOTO',json.dumps({'faculdade':item['instituicao'],'ufs_cadastro':sorted({r['estado'] for r in dados if r['instituicao']==item['instituicao']}),'total_criterios_gerados':len(todas),'consultas_executadas':consultas},ensure_ascii=False),flush=True)
        lidos={}; fontes_falharam=[]
        def buscar(q,max_results):
            if q==oficial: return [{'href':url}]
            resultados=executar(lambda:s.buscar_web(q,min(max_results,4)),25)
            buscas.append({'consulta':q,'resultados':len(resultados) if resultados is not None else None})
            print('BUSCA WEB PILOTO',json.dumps({'consulta':q,'resultados':resultados},ensure_ascii=False),flush=True)
            return resultados
        def fonte(u,inst,sigla):
            try:
                registros,_=executar(lambda:f.carregar_fonte(u,inst,sigla),25)
                lidos[u]=registros
                print('FONTE PILOTO',json.dumps({'url':u,'nomes':[r['nome'] for r in registros]},ensure_ascii=False),flush=True)
                return registros,[]
            except Exception as e:
                fontes_falharam.append({'url':u,'erro':str(e)[:150]}); raise
        antes=dict(s.stats); n0=len(piloto.novos); confirmados0=len(piloto.confirmados)
        with patch.object(s,'consultas_leads',return_value=consultas):
            ok=s.processar_instituicao(piloto,item,search_fn=buscar,source_fn=fonte,continuar_falhas=True)
        cp=piloto.cp[s.etapa_captacao_item(item)]
        resultado={'faculdade':item['instituicao'],'etapa_isolada':s.etapa_captacao_item(item),'nomes_unicos_lidos':len({s.normalizar(r['nome']) for regs in lidos.values() for r in regs}),'fonte_controlada_lidos':len(lidos.get(url,[])),'referencia_anterior':referencia,'novos_confirmados':piloto.novos[n0:],'existentes_confirmados':sorted(set(piloto.confirmados[confirmados0:])),'duplicados_ignorados':s.stats['duplicados']-antes['duplicados'],'checkpoint_piloto':cp,'fontes_inacessiveis':fontes_falharam,'ok':ok}
        casos_reais.append(resultado)
        if not ok or cp['status']!='concluido' or len(lidos.get(url,[]))<referencia: problemas.append({'faculdade':item['instituicao'],'erro':'Piloto incompleto; verificar fontes e checkpoint'})
    except Exception as e:
        problemas.append({'faculdade':alias,'erro':str(e)[:200]})
print('RESULTADO PRE BRASIL',json.dumps({'segundos':round(time.monotonic()-inicio,1),'faculdades_cadastradas':len(fila),'ufs':ufs,'casos':casos_reais,'buscas':buscas,'pendencias':problemas,'fila_nacional_alterada':False,'checkpoint_piloto_em_memoria':True,'gravacoes_reais':piloto.novos,'agendamento_nacional_ativo':False},ensure_ascii=False),flush=True)
if problemas or len(casos_reais)!=2: raise SystemExit(2)
