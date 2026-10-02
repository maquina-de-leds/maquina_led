"""Salvamento restrito às duas evidências públicas conferidas e autorizadas."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scraper as s
repo=s.SupabaseRepo.from_env()
casos=[
 {'nome':'Júlia Parpineli Bernini Silva','instituicao':'Centro Universitário de Votuporanga','alias':'Unifev','data':'28/01/2025','url':'https://www.unifev.edu.br/noticia/35586/recem-formada-em-nutricao-pela-unifev-julia-bernini-conquista-vaga-em-especializacao-na-unesp-e-se-prepara-para-novos-desafios-profissionais'},
 {'nome':'Carolina Nóbrega Dantas','instituicao':'Unifacisa','alias':'Unifacisa','data':'20/02/2025','url':'https://unifacisa.edu.br/carolina-nobrega-dantas-da-graduacao-a-residencia-em-vigilancia-em-saude/'},
 {'nome':'Júlia Sofia da Conceição','instituicao':'Faculdade IELUSC','alias':'IELUSC','data':'08/04/2025','url':'https://faculdade.ielusc.br/arquivos/noticia/recem-formada-em-nutricao-e-selecionada-para-residencia-multiprofissional-no-hospital-sao-jose/','periodo':'2025/1','evidencia_extra':'Notícia institucional informa expressamente que concluiu Nutrição em fevereiro de 2025; residência em Neurologia no Hospital Municipal São José.'},
 {'nome':'Un Hwa Chan Moreira','instituicao':'Universidade Presbiteriana Mackenzie','alias':'Mackenzie','data':'junho de 2026','ano':2026,'tipo':'aluna do curso de Nutrição','url':'https://br.linkedin.com/in/beatrizmoreti','evidencia_extra':'Resultado público do LinkedIn de Beatriz Moreti cita a aluna Un Hwa Moreira, da Nutrição Mackenzie, premiada em 12 de junho no Ganepão 2026. O perfil da professora é somente fonte da evidência, não Instagram nem perfil da aluna. Nome completo Un Hwa Chan Moreira e vínculo com Nutrição constam no documento institucional https://www.mackenzie.br/fileadmin/ARQUIVOS/Public/1-mackenzie/universidade/pro-reitoria/pesquisa-e-pos-graduacao/coordenadoria-de-pesquisa/iniciacao-cientifica-e-tecnologica/projetos_em_andamento_2023.pdf . Semestre e conclusão pendentes.'}
]
confirmados=[]
for c in casos:
    ano=c.get('ano',2025)
    evidencia=(f"Evidência pública de {c['alias']}, referente a {c['data']}, descreve {c['nome']} como {c.get('tipo','recém-formada em Nutrição')}. "
               "Evidência conferida na pesquisa assistida. "+c.get('evidencia_extra','Data e semestre exatos da conclusão não informados.')+" "
               "Máquina 2: localizar Instagram e confirmar identidade e fase acadêmica.")
    existentes=repo.client.table('leds').select('id,nome,instituicao,fonte_url,instagram').ilike('nome',c['nome']).execute().data or []
    existente=next((r for r in existentes if r.get('fonte_url')==c['url'] or s.normalizar(c['alias']) in s.normalizar(r.get('instituicao')) or s.normalizar(r.get('instituicao'))==s.normalizar(c['instituicao'])),None)
    if existente:
        print('JÁ EXISTENTE, PRESERVADO:',json.dumps(existente,ensure_ascii=False),flush=True)
        confirmados.append({'nome':c['nome'],'novo':False,'id':existente['id']})
        continue
    novo=s.salvar_lead(repo,c['nome'],c['instituicao'],None,None,evidencia,c['url'],ano_forcado=ano,
                      periodo_forcado=c.get('periodo',str(ano)+' (vínculo com Nutrição; semestre da conclusão não informado)'),instituicao_alias=c['alias'])
    rows=repo.client.table('leds').select('id,nome,instituicao,instagram,fonte_url,evidencia,ano_alvo,periodo_alvo,proxima_acao').ilike('nome',c['nome']).execute().data or []
    registro=next((r for r in rows if r.get('fonte_url')==c['url'] or s.normalizar(c['alias']) in s.normalizar(r.get('instituicao'))),None)
    assert registro, 'Gravação não confirmada: '+c['nome']
    print('CONFIRMADO NO SUPABASE:',json.dumps(registro,ensure_ascii=False),flush=True)
    confirmados.append({'nome':c['nome'],'novo':novo,'id':registro['id']})
assert len(confirmados)==len(casos)
print('RESULTADO FINAL:',json.dumps({'confirmados':confirmados,'novos':sum(bool(r['novo']) for r in confirmados)},ensure_ascii=False),flush=True)
