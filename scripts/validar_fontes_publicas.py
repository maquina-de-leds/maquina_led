"""Validação real somente de leitura, sem acesso ao banco ou nomes pré-carregados."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fontes_academicas import carregar_fonte, norm

urls=[
'https://www.mackenzie.br/universidade/unidades-academicas/ccbs/tcc-e-pesquisa/mostra-de-tcc',
'https://www.mackenzie.br/noticias/artigo/n/a/i/alunos-de-nutricao-criam-e-book-de-receitas-saudaveis-e-praticas',
'https://eventoscopq.mackenzie.br/jornada/pt_BR/article/view/317',
'https://www.mackenzie.br/fileadmin/ARQUIVOS/Public/pesquisa-inovacao/incubadora/Vitrine_2024/Lista_unificada_projetos_aprovador.23.06.25.pdf'
]
vistos={}; pendentes=[]
for url in urls:
    try:
        registros,_=carregar_fonte(url,'Universidade Presbiteriana Mackenzie','Mackenzie')
        print('FONTE REAL',url,json.dumps(registros,ensure_ascii=False),flush=True)
        if not registros: pendentes.append(url)
        for r in registros: vistos[norm(r['nome'])]=r['nome']
    except Exception as exc:
        pendentes.append(url)
        print('FONTE PENDENTE',url,str(exc)[:250],flush=True)
try:
    rotulos,_=carregar_fonte('https://www.mackenzie.br/graduacao/sao-paulo-higienopolis/nutricao','Universidade Presbiteriana Mackenzie','Mackenzie')
    assert not rotulos, 'Página geral de curso produziu candidatos: '+repr(rotulos)
except Exception as exc:
    pendentes.append('pagina geral do curso')
    print('VALIDACAO PENDENTE',str(exc)[:250],flush=True)
print('RESULTADO REAL',json.dumps({'nomes_unicos':len(vistos),'nomes':list(vistos.values()),'fontes_pendentes':pendentes,'gravacoes_no_banco':0},ensure_ascii=False),flush=True)
if pendentes or len(vistos)<34: raise SystemExit(2)
