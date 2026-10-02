import requests, os, tempfile, json
from scraper import ler_fila_inep_zip, ESTADOS
from fontes_academicas import ler_html
url="https://download.inep.gov.br/microdados/microdados_censo_da_educacao_superior_2024.zip"
import certifi
pem=requests.get("https://www.detic.unicamp.br/wp-content/uploads/sites/38/2026/05/intermediate_2025.pem",timeout=25)
pem.raise_for_status()
bundle="inep-ca.pem"
with open(bundle,"w") as dest:
    dest.write(open(certifi.where()).read()+"\n"+pem.text)
ok=False
import ssl, time
for attempt in range(3):
    try:
        leaf=ssl.get_server_certificate(("download.inep.gov.br",443),timeout=10)
        with open("leaf.pem","w") as out: out.write(leaf)
        info=ssl._ssl._test_decode_cert("leaf.pem")
        print("LEAF:",info,flush=True)
        for issuer_url in info.get("caIssuers",[]):
            from urllib.parse import urlparse
            if urlparse(issuer_url).hostname not in {"secure.globalsign.com","crt.globalsign.com"}:
                print("EMISSOR NÃO PREVISTO:",issuer_url); continue
            issuer_url=issuer_url.replace("http://","https://",1)
            cert=requests.get(issuer_url,timeout=20);cert.raise_for_status()
            pem2=cert.text if b"BEGIN CERTIFICATE" in cert.content else ssl.DER_cert_to_PEM_cert(cert.content)
            with open(bundle,"a") as out: out.write("\n"+pem2)
        break
    except Exception as e: print("LEAF FALHA",str(e),flush=True)
for ca in [bundle,bundle,bundle]:
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
        from fontes_academicas import Pagina
        page=Pagina(); page.feed(r.text)
        for text,tag in page.linhas:
            if any(w in text.lower() for w in ["nutri","melissa","giovanna","semestre"]):
                print("CONTEXTO",tag,text,flush=True)
        result=ler_html(r.text,url,inst)
        print("PAGINA REAL:",url,"CONTAGEM:",len(result[0]),"PERIODOS:",sorted({x["periodo"] for x in result[0]}),flush=True)
    except Exception as e: print("FALHA PAGINA:",url,str(e),flush=True)
if not ok: raise SystemExit(1)
