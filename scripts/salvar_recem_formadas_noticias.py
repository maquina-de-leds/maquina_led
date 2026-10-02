"""Salvamento restrito às duas evidências públicas conferidas e autorizadas."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scraper as s
repo=s.SupabaseRepo.from_env()
casos=[
 {'nome':'Júlia Parpineli Bernini Silva','instituicao':'Centro Universitário de Votuporanga','alias':'Unifev','data':'28/01/2025','url':'https://www.unifev.edu.br/noticia/35586/recem-formada-em-nutricao-pela-unifev-julia-bernini-conquista-vaga-em-especializacao-na-unesp-e-se-prepara-para-novos-desafios-profissionais'},
 {'nome':'Carolina Nóbrega Dantas','instituicao':'Unifacisa','alias':'Unifacisa','data':'20/02/2025','url':'https://unifacisa.edu.br/carolina-nobrega-dantas-da-graduacao-a-residencia-em-vigilancia-em-saude/'}
]
confirmados=[]
for c in casos:
    evidencia=(f"Notícia oficial de {c['alias']}, publicada em {c['data']}, descreve {c['nome']} como recém-formada em Nutrição. "
               "Evidência lida na pesquisa assistida e aceita pelo usuário. Ano da notícia: 2025; data e semestre exatos da conclusão não informados. "
               "Máquina 2: localizar Instagram e confirmar identidade e fase acadêmica.")
    existentes=repo.client.table('leds').select('id,nome,instituicao,fonte_url,instagram').ilike('nome',c['nome']).execute().data or []
    existente=next((r for r in existentes if r.get('fonte_url')==c['url'] or s.normalizar(c['alias']) in s.normalizar(r.get('instituicao')) or s.normalizar(r.get('instituicao'))==s.normalizar(c['instituicao'])),None)
    if existente:
        print('JÁ EXISTENTE, PRESERVADO:',json.dumps(existente,ensure_ascii=False),flush=True)
        confirmados.append({'nome':c['nome'],'novo':False,'id':existente['id']})
        continue
    novo=s.salvar_lead(repo,c['nome'],c['instituicao'],None,None,evidencia,c['url'],ano_forcado=2025,
                      periodo_forcado='2025 (notícia de recém-formada; semestre da conclusão não informado)',instituicao_alias=c['alias'])
    rows=repo.client.table('leds').select('id,nome,instituicao,instagram,fonte_url,evidencia,ano_alvo,periodo_alvo,proxima_acao').ilike('nome',c['nome']).execute().data or []
    registro=next((r for r in rows if r.get('fonte_url')==c['url'] or s.normalizar(c['alias']) in s.normalizar(r.get('instituicao'))),None)
    assert registro, 'Gravação não confirmada: '+c['nome']
    print('CONFIRMADO NO SUPABASE:',json.dumps(registro,ensure_ascii=False),flush=True)
    confirmados.append({'nome':c['nome'],'novo':novo,'id':registro['id']})
assert len(confirmados)==2
print('RESULTADO FINAL:',json.dumps({'confirmados':confirmados,'novos':sum(bool(r['novo']) for r in confirmados)},ensure_ascii=False),flush=True)
