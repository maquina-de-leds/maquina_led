import requests,csv,io,json
from fontes_academicas import ler_html,norm
url="https://dadosabertos.mec.gov.br/images/conteudo/Ind-ensino-superior/2022/PDA_Dados_Cursos_Graduacao_Brasil.csv"
try:
    r=requests.get(url,timeout=(15,45));r.raise_for_status()
    rows=list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig") if r.encoding=="utf-8" else r.content.decode("cp1252")),delimiter=";"))
    print("MEC CABECALHO:",list(rows[0]) if rows else [],"TOTAL:",len(rows),flush=True)
    nutrition=[row for row in rows if any(norm(v)=="nutricao" for v in row.values() if v)]
    print("MEC NUTRICAO:",len(nutrition),"AMOSTRA:",nutrition[:2],flush=True)
except Exception as e: print("MEC FALHA:",type(e).__name__,str(e),flush=True)
for url,inst,expected in [
("https://uno.edu.br/noticias/outorga-de-grau-1","Unochapecó",13),
("https://site.uno.edu.br/noticias/ciclo-concluido","Unochapecó",0),
("https://uniateneu.edu.br/uniateneu-realizou-colacao-de-grau-para-celebrar-a-formatura-de-alunos-de-diferentes-cursos-de-graduacao/","UniAteneu",1)]:
    r=requests.get(url,timeout=30);r.raise_for_status()
    result=ler_html(r.text,url,inst)[0]
    print("PAGINA REAL:",url,"NOMES:",[(x["nome"],x["periodo"]) for x in result],flush=True)
    assert len(result)==expected
    if inst=="UniAteneu": assert result[0]["periodo"]=="2026/1"
