"""Confere leitura real sem fornecer nomes esperados ao extrator."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scraper as s
from fontes_academicas import carregar_fonte
repo=s.SupabaseRepo.from_env()
ies='Universidade Presbiteriana Mackenzie'
# Bloqueio reversível e restrito ao falso positivo confirmado nesta execução.
q=repo.client.table('leds').select('id,nome').eq('instituicao',ies).eq('nome','Indústria de Alimentos').eq('fonte_url','https://www.mackenzie.br/graduacao/sao-paulo-higienopolis/nutricao').eq('origem','captacao_nacional_fila_v58').execute().data or []
for r in q:
    repo.client.table('leds').update({'nao_contatar':True,'qualificado':False,'proxima_acao':'revisar_nome_extraido'}).eq('id',r['id']).execute()
    confirmado=repo.client.table('leds').select('nao_contatar,qualificado').eq('id',r['id']).execute().data
    assert confirmado[0]['nao_contatar'] and not confirmado[0]['qualificado']
    print('FALSO POSITIVO BLOQUEADO:',r['nome'],flush=True)
urls=[
'https://www.mackenzie.br/universidade/unidades-academicas/ccbs/tcc-e-pesquisa/mostra-de-tcc',
'https://www.mackenzie.br/noticias/artigo/n/a/i/alunos-de-nutricao-criam-e-book-de-receitas-saudaveis-e-praticas',
'https://eventoscopq.mackenzie.br/jornada/pt_BR/article/view/317',
'https://www.mackenzie.br/fileadmin/ARQUIVOS/Public/pesquisa-inovacao/incubadora/Vitrine_2024/Lista_unificada_projetos_aprovador.23.06.25.pdf'
]
vistos={}; erros=[];novos=0
for url in urls:
    try:
        registros,_=carregar_fonte(url,ies,'Mackenzie')
        print('LEITURA REAL:',url,'|',json.dumps(registros,ensure_ascii=False),flush=True)
        for r in registros:
            vistos[s.normalizar(r['nome'])]=r['nome']
            novos+=int(s.salvar_lead(repo,r['nome'],ies,None,'SP',r['evidencia'],url,instagram=r.get('instagram'),ano_forcado=r['ano'],periodo_forcado=r['periodo'],instituicao_alias='Mackenzie'))
    except Exception as exc:
        erros.append(url)
        print('LEITURA PENDENTE:',url,str(exc)[:250],flush=True)
print('DIAGNOSTICO FINAL:',json.dumps({'nomes_unicos':len(vistos),'nomes':list(vistos.values()),'novos':novos,'fontes_pendentes':erros},ensure_ascii=False),flush=True)
if erros or len(vistos)<22: raise SystemExit(2)
