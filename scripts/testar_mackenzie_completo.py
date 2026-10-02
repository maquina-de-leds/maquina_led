"""Validação curta de fontes reais, gravação e duplicação; sem varredura nacional."""
import json,signal,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scraper as s
from fontes_academicas import carregar_fonte, recuperar_fonte_na_busca
repo=s.SupabaseRepo.from_env(); inicio=time.monotonic(); vistos={}; novos=[]; pendentes=[]; duplicados=0; acessos_indisponiveis=[]; recuperadas=[]
ies='Universidade Presbiteriana Mackenzie'
fontes=[
('https://www.mackenzie.br/universidade/unidades-academicas/ccbs/tcc-e-pesquisa/mostra-de-tcc',22),
('https://www.mackenzie.br/memorias/150-anos/acontece/arquivo/n/a/i/alunos-de-nutricao-criam-e-book-de-receitas-saudaveis-e-praticas',8),
('https://eventoscopq.mackenzie.br/jornada/pt_BR/article/view/317',1),
('https://www.mackenzie.br/fileadmin/ARQUIVOS/Public/pesquisa-inovacao/incubadora/Vitrine_2024/Lista_unificada_projetos_aprovador.23.06.25.pdf',4)
]
def limite(*args): raise TimeoutError('Limite de leitura da fonte atingido')
signal.signal(signal.SIGALRM,limite)
for url,minimo in fontes:
    restante=360-(time.monotonic()-inicio)
    if restante<=0:
        pendentes.append({'fonte':url,'erro':'Orçamento total de leitura esgotado'}); continue
    try:
        signal.setitimer(signal.ITIMER_REAL,min(45,restante))
        try:
            try: registros,_=carregar_fonte(url,ies,'Mackenzie')
            except Exception as leitura:
                acessos_indisponiveis.append({'fonte':url,'erro':str(leitura)[:150]})
                signal.setitimer(signal.ITIMER_REAL,min(30,max(1,360-(time.monotonic()-inicio))))
                registros,_=recuperar_fonte_na_busca(url,ies,'Mackenzie',s.buscar_web)
                if not registros: raise leitura
                recuperadas.append({'fonte':url,'nomes':len(registros)})
                print('RECUPERADO NO ÍNDICE:',url,len(registros),flush=True)
        finally: signal.setitimer(signal.ITIMER_REAL,0)
        print('FONTE REAL:',json.dumps({'url':url,'pessoas':len(registros),'nomes':[r['nome'] for r in registros]},ensure_ascii=False),flush=True)
        if len(registros)<minimo: pendentes.append({'fonte':url,'erro':'Leitura menor que a última quantidade validada','lidos':len(registros),'referencia':minimo})
        for r in registros:
            instituicao=r.get('instituicao',ies)
            chave=(s.normalizar(r['nome']),instituicao)
            if chave in vistos: continue
            vistos[chave]=r['nome']
            inseriu=s.salvar_lead(repo,r['nome'],instituicao,None,None,r['evidencia'],r.get('fonte_url',url),instagram=r.get('instagram'),ano_forcado=r['ano'],periodo_forcado=r['periodo'],instituicao_alias='Mackenzie' if instituicao==ies else None)
            assert repo.lead_existe(s.formatar_nome_pessoa(r['nome']),instituicao), 'Registro não confirmado após salvar/verificar duplicado'
            if inseriu: novos.append(r['nome'])
            else: duplicados+=1
            print('CONFIRMADO NO BANCO:',r['nome'],'| novo:',inseriu,flush=True)
    except Exception as exc:
        signal.setitimer(signal.ITIMER_REAL,0)
        pendentes.append({'fonte':url,'erro':str(exc)[:250]})
        print('PENDENTE:',url,str(exc)[:250],flush=True)
print('RESULTADO REAL:',json.dumps({'segundos':round(time.monotonic()-inicio,1),'fontes_planejadas':len(fontes),'nomes_unicos':len(vistos),'nomes':list(vistos.values()),'novos_confirmados':novos,'duplicados_confirmados':duplicados,'pendencias':pendentes,'acessos_diretos_indisponiveis':acessos_indisponiveis,'fontes_recuperadas_no_indice':recuperadas,'pesquisas_extensas':0,'fila_nacional_alterada':False},ensure_ascii=False),flush=True)
if pendentes: raise SystemExit(2)
