"""Pesquisa assistida pública, confirmação real e releitura da referência.

Os três indícios abaixo foram encontrados na web antes desta execução.
Não são apresentados como descoberta automática do GitHub nem como prova
de conclusão. A máquina 2 deve confirmar identidade e fase acadêmica.
"""
import json, runpy, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scraper as s

inicio = time.monotonic()
repo = s.SupabaseRepo.from_env()
ies = 'Universidade Presbiteriana Mackenzie'
casos = [
    dict(nome='Ana Carolina Crossi de Andrade', ano=2025,
         periodo='2025 (intervalo acadêmico termina em 2025; conclusão a validar)',
         url='https://br.linkedin.com/in/ana-carolina-crossi',
         evidencia='Resultado público apresenta formação Mackenzie 2022–2025 e participação no Workshop do curso de Nutrição. Artigo RBPFEX volume 19 número 123 (2025), https://www.rbpfex.com.br/index.php/rbpfex/pt_BR/article/view/3097, identifica a autora como graduanda em Nutrição. Não prova semestre exato de conclusão.'),
    dict(nome='Laura Rodrigues', ano=None, periodo='7º período/semestre (data e conclusão a validar)',
         url='https://br.linkedin.com/in/laura-rodrigues-04171537a',
         evidencia='Resultado público descreve Laura Rodrigues como graduanda de Nutrição do 7º semestre na Universidade Presbiteriana Mackenzie. Nome público com sobrenome; identidade, data e conclusão pendentes.'),
    dict(nome='Leticia Gomes Biserra', ano=None, periodo='7º período/semestre (conclusão não confirmada; intervalo termina em 2027)',
         url='https://br.linkedin.com/in/leticiagomesbiserra',
         evidencia='Resultado público descreve estudante de Nutrição Mackenzie no 7º semestre. Formação acadêmica indicada 2023–2027: existe divergência em relação à janela de conclusão 2025/2026. Capturada pelo indício explícito de 7º semestre, sem afirmar formatura em 2026.'),
]
confirmados = []
for c in casos:
    evidencia = c['evidencia'] + ' Pesquisa assistida pública em 03/10/2026; máquina 2 deve localizar Instagram e validar identidade e fase acadêmica. Sem acesso direto ao Instagram.'
    novo = s.salvar_lead(repo,c['nome'],ies,None,None,evidencia,c['url'],ano_forcado=c['ano'],periodo_forcado=c['periodo'],instituicao_alias='Mackenzie')
    assert repo.lead_existe(s.formatar_nome_pessoa(c['nome']),ies), 'Gravação não confirmada: '+c['nome']
    repetiu = s.salvar_lead(repo,c['nome'],ies,None,None,evidencia,c['url'],ano_forcado=c['ano'],periodo_forcado=c['periodo'],instituicao_alias='Mackenzie')
    assert repetiu is False, 'Duplicação na repetição: '+c['nome']
    confirmados.append(dict(nome=c['nome'],novo=bool(novo),fonte=c['url'],ano=c['ano'],periodo=c['periodo'],confirmado_no_banco=True,repeticao_sem_insercao=True))
    print('CANDIDATO PÚBLICO CONFIRMADO',json.dumps(confirmados[-1],ensure_ascii=False),flush=True)
# As quatro fontes reais continuam sendo relidas, sem apagar ou alterar alunos.
runpy.run_path(str(Path(__file__).with_name('testar_mackenzie_completo.py')),run_name='__main__')
print('RESULTADO NOVAS FONTES',json.dumps(dict(segundos=round(time.monotonic()-inicio,1),origem_descoberta='pesquisa assistida na web, anterior ao teste GitHub',candidatos=confirmados,novos=sum(c['novo'] for c in confirmados),existentes=sum(not c['novo'] for c in confirmados),instagram_acessado=False,fila_nacional_alterada=False),ensure_ascii=False),flush=True)
