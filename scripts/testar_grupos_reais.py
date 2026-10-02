"""Busca real de grupos vs consulta de formandos; grava e confere candidatos novos."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scraper as s
repo=s.SupabaseRepo.from_env()
dados=[]
for offset in range(0,20000,1000):
    lote=(repo.client.table('instituicoes_nutricao').select('*').eq('origem',s.ORIGEM_IES)
          .order('id').range(offset,offset+999).execute()).data or []
    dados.extend(lote)
    if len(lote)<1000: break
else: raise RuntimeError('Conferir paginação da fila')
fila=s.agrupar_faculdades(dados)
class Piloto:
    def __init__(self): self.novos=[]
    def __getattr__(self,nome): return getattr(repo,nome)
    def atualizar_instituicao(self,*args,**kwargs): pass
    def inserir_lead(self,dados):
        repo.inserir_lead(dados)
        assert repo.lead_existe(dados['nome'],dados['instituicao'])
        self.novos.append(dados)
        print('BANCO CONFIRMADO:',dados['nome'],'|',dados['instituicao'],'|',dados['fonte_url'],flush=True)
piloto=Piloto()
s.MAX_RESULTADOS=4
original=s.consultas_leads
resumos=[]
for alias in ['Unochapecó','UniAteneu']:
    base=next(x for x in fila if s.normalizar(s.alias_instituicao(x))==s.normalizar(alias))
    for estrategia in ['grupos','formandos_controle']:
        item=dict(base,id='grupos_20261002_'+estrategia+'_'+str(base['id']))
        if estrategia=='grupos':
            criterios=[('"grupo de alunos"',2025),('"grupo de estudantes"',2026),
                       ('"liga acadêmica" "integrantes"',2026),('"centro acadêmico" "membros"',2025)]
        else: criterios=[('"formandos"',2025)]
        consultas=[f'"{alias}" Nutrição {sinal} {ano} -site:linkedin.com' for sinal,ano in criterios]
        antes=dict(s.stats)
        def busca(q,max_results):
            resultados=s.buscar_web(q,max_results)
            print('RESULTADOS BUSCA:',json.dumps(dict(estrategia=estrategia,consulta=q,
                resultados=[dict(titulo=r.get('title'),url=r.get('href') or r.get('url')) for r in resultados or []],
                indisponivel=resultados is None),ensure_ascii=False),flush=True)
            return resultados
        s.consultas_leads=lambda *args, consultas=consultas: consultas
        try: ok=s.processar_instituicao(piloto,item,search_fn=busca)
        finally: s.consultas_leads=original
        resultado=dict(faculdade=base['instituicao'],estrategia=estrategia,
                       consultas_planejadas=len(consultas),busca_estavel=ok,
                       **{k:s.stats[k]-antes[k] for k in ['leads_encontrados','leads_salvos','duplicados','fontes_visitadas','fontes_sem_nomes','erros']})
        resumos.append(resultado)
        print('COMPARACAO:',json.dumps(resultado,ensure_ascii=False),flush=True)
        if not ok: break
    if not ok: break
antes=s.stats['leads_salvos']
for lead in piloto.novos:
    assert not s.salvar_lead(repo,lead['nome'],lead['instituicao'],None,None,lead['evidencia'],lead['fonte_url'],
                           instagram=lead['instagram'],ano_forcado=lead['ano_alvo'],periodo_forcado=lead['periodo_alvo'])
assert s.stats['leads_salvos']==antes
print('NOVOS CONFIRMADOS:',len(piloto.novos),'| REPETICAO: nenhuma inserção duplicada',flush=True)
print('RESUMOS DO TESTE:',json.dumps(resumos,ensure_ascii=False),flush=True)
s.resumo()
print('Pesquisa limitada: checkpoints separados; fila nacional não foi concluída.',flush=True)
if s.stats['erros'] or any(not r['busca_estavel'] for r in resumos): raise SystemExit(2)
