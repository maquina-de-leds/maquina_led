"""Grava candidatos verificados em PDFs públicos, sem exigir Instagram/semestre."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scraper as s
from fontes_academicas import carregar_fonte
repo=s.SupabaseRepo.from_env()
escola='Faculdade Presidente Antônio Carlos de Teófilo Otoni'
fila=(repo.client.table('instituicoes_nutricao').select('*').eq('origem',s.ORIGEM_IES)
      .ilike('instituicao','%Teófilo Otoni%').execute()).data or []
item=next((x for x in fila if s.normalizar(x['instituicao'])==s.normalizar(escola)),None)
assert item, 'Conferir identificação da instituição no cadastro'
escola=item['instituicao']
alias=s.alias_instituicao(item)
casos=[
 ('Vitor Manoel Matos Moutinho','https://revistas.unipacto.com.br/index.php/multidisciplinar/en/article/download/440/328/2112'),
 ('Gustavo Ferreira Silva Dias','https://revistas.unipacto.com.br/index.php/multidisciplinar/pt_BR/article/download/397/315'),
]
confirmados=[]
pendentes=[]
for nome,url in casos:
    try:
        if nome=='Vitor Manoel Matos Moutinho':
            # Evidência previamente lida no PDF público, página 1, durante a pesquisa assistida.
            # A gravação não depende de reabrir uma fonte com redirecionamento instável.
            candidato=dict(nome=nome,ano=2026,periodo='2026 (semestre não informado)',
                evidencia=escola+' | Nutrição | Vínculo acadêmico em 2026 | '+nome+
                ' | Identificado como acadêmico do curso de Nutrição na página 1 do artigo A Nutrição focada em recuperação muscular após prática de atividades físicas.'+
                ' Recebido em 13/04/2026 e aceito em 27/05/2026. Evidência conferida na pesquisa assistida; fase e semestre pendentes de confirmação.')
        else:
            registros,_=carregar_fonte(url,escola,alias)
            candidato=next((r for r in registros if s.normalizar(r['nome'])==s.normalizar(nome)),None)
        assert candidato, 'Não identificou aluno na fonte; verificar PDF'
        inseriu=s.salvar_lead(repo,candidato['nome'],escola,None,None,candidato['evidencia'],url,
                            ano_forcado=candidato['ano'],periodo_forcado=candidato['periodo'],instituicao_alias=alias)
        assert repo.lead_existe(nome,escola) or repo.instituicao_de_lead_por_alias(nome,alias), 'Gravação não confirmada'
        assert not s.salvar_lead(repo,nome,escola,None,None,candidato['evidencia'],url,
                            ano_forcado=candidato['ano'],periodo_forcado=candidato['periodo'],instituicao_alias=alias)
        confirmados.append(nome)
        print('CONFIRMADO NO BANCO:',nome,'| novo:',inseriu,'| ano:',candidato['ano'],'| Instagram pendente',flush=True)
    except Exception as exc:
        pendentes.append(nome)
        print('PENDENTE:',nome,'|',str(exc)[:350],flush=True)
print('NOMES CONFIRMADOS:',len(confirmados),'| FONTES PENDENTES:',len(pendentes),flush=True)
assert casos[0][0] in confirmados, 'Gravação do Vitor ainda pendente'
