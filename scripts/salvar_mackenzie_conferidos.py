"""Salva nomes conferidos na pesquisa assistida; confirma banco e repetição."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scraper as s
repo=s.SupabaseRepo.from_env()
rows=repo.client.table("instituicoes_nutricao").select("*").ilike("instituicao","%Mackenzie%").execute().data or []
item=next(x for x in rows if s.normalizar(x["instituicao"])==s.normalizar("Universidade Presbiteriana Mackenzie"))
escola=item["instituicao"]
alias=s.alias_instituicao(item)
casos=[]
url="https://www.mackenzie.br/memorias/150-anos/acontece/arquivo/n/a/i/alunos-de-nutricao-criam-e-book-de-receitas-saudaveis-e-praticas"
for nome in ["Ana Raquel Alves de Pontes","Isabela Santos da Costa Marcon","Jaqueline Trindade Moreira","Maria Letícia Villani","Lina Martins Halverso","Sara Silva Santos","Fatima Ali Farhat","Camily Malveira Silva Chaves"]:
    casos.append((nome,url,"Notícia oficial de 19/05/2025 identifica as alunas do curso de Nutrição da Universidade Presbiteriana Mackenzie como autoras do projeto integrador Educar e Comunicar. Vínculo acadêmico em 2025; conclusão e semestre pendentes."))
casos.append(("Geovanna Romeiro de Paiva","https://eventoscopq.mackenzie.br/jornada/pt_BR/article/view/317","Jornada de Iniciação Científica edição 2025, publicado em 06/11/2025: biografia identifica Geovanna como graduanda do curso de Nutrição da Universidade Presbiteriana Mackenzie. Semestre e conclusão pendentes."))
url="https://www.mackenzie.br/fileadmin/ARQUIVOS/Public/pesquisa-inovacao/incubadora/Vitrine_2024/Lista_unificada_projetos_aprovador.23.06.25.pdf"
for nome in ["Fernanda Carolina dos Santos","Eliza Thomazini Zambom Cicero da Silva","Maria Luiza Andrade Ataide"]:
    casos.append((nome,url,"Lista oficial de projetos aprovados identificada em 23/06/2025: coluna de aluno vinculada ao curso Nutrição, CCBS, Higienópolis. Nome separado do orientador. Evidência acadêmica conferida na pesquisa assistida; conclusão e semestre pendentes."))
novos=duplicados=0
for nome,url,ev in casos:
    texto=escola+" | Nutrição | "+nome+" | "+ev
    novo=s.salvar_lead(repo,nome,escola,None,"SP",texto,url,ano_forcado=2025,periodo_forcado="2025 (semestre não informado)",instituicao_alias=alias)
    assert repo.lead_existe(s.formatar_nome_pessoa(nome),escola) or repo.instituicao_de_lead_por_alias(s.formatar_nome_pessoa(nome),alias), "Não confirmou gravação"
    novos+=int(novo)
    duplicados+=int(not novo)
    assert not s.salvar_lead(repo,nome,escola,None,"SP",texto,url,ano_forcado=2025,periodo_forcado="2025 (semestre não informado)",instituicao_alias=alias), "Duplicação na repetição"
    print("CONFIRMADO:",nome,"| novo:",novo,flush=True)
print("RESULTADO MACKENZIE: candidatos=",len(casos),"novos=",novos,"já existentes=",duplicados,"repetição sem novas inserções",flush=True)
