import requests, os, tempfile, json
from scraper import ler_fila_inep_zip, ESTADOS
from fontes_academicas import ler_html
url="https://download.inep.gov.br/microdados/microdados_censo_da_educacao_superior_2024.zip"
ok=False
for ca in [True, "/etc/ssl/certs/ca-certificates.crt"]:
    try:
        print("DOWNLOAD CA:",ca,flush=True)
        with requests.get(url,verify=ca,stream=True,timeout=(20,90)) as r:
            r.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=".zip") as f:
                size=0
                for chunk in r.iter_content(1024*1024):
                    size+=len(chunk)
                    if size>1024**3: raise RuntimeError("arquivo maior que limite")
                    f.write(chunk)
                f.flush()
                print("BYTES:",size)
                rows=ler_fila_inep_zip(f.name)
                print("FILA REAL:",len(rows),"UF:",sorted({x["estado"] for x in rows}))
                ok=True
                break
    except Exception as e: print("FALHA:",type(e).__name__,str(e),flush=True)
for url,inst in [
("https://uno.edu.br/noticias/outorga-de-grau-1","Unochapecó"),
("https://site.uno.edu.br/noticias/ciclo-concluido","Unochapecó"),
("https://uniateneu.edu.br/uniateneu-realizou-colacao-de-grau-para-celebrar-a-formatura-de-alunos-de-diferentes-cursos-de-graduacao/","UniAteneu")]:
    try:
        r=requests.get(url,timeout=30); r.raise_for_status()
        result=ler_html(r.text,url,inst)
        print("PAGINA REAL:",url,json.dumps(result,ensure_ascii=False),flush=True)
    except Exception as e: print("FALHA PAGINA:",url,str(e),flush=True)
if not ok: raise SystemExit(1)
