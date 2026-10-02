"""Confere deduplicação da captura principal com um lead real já existente."""
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scraper as s
repo=s.SupabaseRepo.from_env(); inicio=time.monotonic()
nome='Thais Camargo Prestes'; url='https://www.instagram.com/p/DU_njLwjuNr/'
def existentes():
    return (repo.client.table('leds').select('id,nome,instituicao,evidencia,ano_alvo,periodo_alvo,fonte_url')
            .ilike('nome',nome).eq('fonte_url',url).execute()).data or []
antes=existentes()
assert antes, 'Lead de referência ausente; nenhuma tentativa de gravação realizada'
r=antes[0]
assert r['instituicao'] is None, 'Este teste exige referência real sem instituição'
for tentativa in range(2):
    inseriu=s.salvar_lead(repo,r['nome'],r['instituicao'],None,None,r['evidencia'],r['fonte_url'],ano_forcado=r['ano_alvo'],periodo_forcado=r['periodo_alvo'])
    assert not inseriu, 'A função tentou inserir um duplicado'
depois=existentes()
assert {x['id'] for x in antes}=={x['id'] for x in depois}, 'IDs mudaram após verificar duplicação'
print('DEDUPLICAÇÃO REAL:',json.dumps({'nome':nome,'instituicao':None,'tentativas':2,'registros_antes':len(antes),'registros_depois':len(depois),'novos_inseridos':0,'ids_preservados':True,'segundos':round(time.monotonic()-inicio,1)},ensure_ascii=False),flush=True)
