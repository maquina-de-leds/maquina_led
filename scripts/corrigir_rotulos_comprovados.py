"""Revisão reversível de seis rótulos comprovados; nenhuma varredura ampla."""
import json,signal,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scraper as s
import fontes_academicas as f
inicio=time.monotonic()
signal.signal(signal.SIGALRM,lambda *a:(_ for _ in ()).throw(TimeoutError('Limite de três minutos')))
signal.alarm(180)
repo=s.SupabaseRepo.from_env()
casos={'https://www.unirio.br/ccbs/nutricao/':['Mais Notícias','Matriz Curricular','Programa de Disciplinas','Horários de Disciplinas','Residência Multiprofissional'],
       'https://www.passeidireto.com/arquivo/201106163/protocolo-tcc-para-imagem-corporal':['Aula Hortaliças']}
revisoes=[]
for url,nomes in casos.items():
    for nome in nomes:
        assert f.pessoa(nome) is None
        rows=repo.client.table('leds').select('id,nome,status,qualificado,nao_contatar').ilike('nome',nome).eq('fonte_url',url).execute().data or []
        for row in rows:
            repo.client.table('leds').update(dict(status='revisao',qualificado=False,nao_contatar=True)).eq('id',row['id']).eq('nome',row['nome']).eq('fonte_url',url).execute()
            atual=repo.client.table('leds').select('id,status,qualificado,nao_contatar').eq('id',row['id']).execute().data[0]
            assert atual['status']=='revisao' and not atual['qualificado'] and atual['nao_contatar']
            revisoes.append(dict(id=row['id'],nome=nome,antes=row,depois=atual,fonte=url))
print('REVISOES CONFIRMADAS',json.dumps(revisoes,ensure_ascii=False),flush=True)
# Releitura da fonte que produziu os cinco títulos, sem gravar candidatos.
registros,_=f.carregar_fonte('https://www.unirio.br/ccbs/nutricao/',None,None)
assert not any(r['nome'] in casos['https://www.unirio.br/ccbs/nutricao/'] for r in registros)
print('RESULTADO REGRESSAO REAL',json.dumps(dict(revisoes_confirmadas=len(revisoes),nomes_da_pagina=[r['nome'] for r in registros],novas_gravacoes=0,segundos=round(time.monotonic()-inicio,1)),ensure_ascii=False),flush=True)
