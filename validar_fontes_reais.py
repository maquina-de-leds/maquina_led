import requests,certifi,zipfile,os,collections,json
from remotezip import RemoteZip
from scraper import localizar_membro,leitor_csv_zip,valor,normalizar,ESTADOS
url="https://download.inep.gov.br/microdados/microdados_censo_da_educacao_superior_2024.zip"
pem=requests.get("https://www.detic.unicamp.br/wp-content/uploads/sites/38/2026/05/intermediate_2025.pem",timeout=20);pem.raise_for_status()
with open("inep-ca.pem","w") as f:f.write(open(certifi.where()).read()+"\n"+pem.text)
os.makedirs("cache_inep",exist_ok=True)
path="cache_inep/cadastros_2024.zip"
if not os.path.exists(path):
    for attempt in range(3):
        try:
            with RemoteZip(url,verify="inep-ca.pem",timeout=(20,90)) as remote:
                print("ARQUIVOS:",[(x.filename,x.file_size,x.compress_size) for x in remote.infolist() if x.filename.upper().endswith(".CSV")],flush=True)
                names=[localizar_membro(remote,"CADASTRO_CURSOS"),localizar_membro(remote,"ED_SUP_IES")]
                assert all(names)
                with zipfile.ZipFile(path+".tmp","w",zipfile.ZIP_DEFLATED) as slim:
                    for name in names:
                        print("LENDO:",name,flush=True)
                        slim.writestr(name,remote.read(name))
                os.replace(path+".tmp",path)
                break
        except Exception as e:
            print("FALHA RANGE:",str(e),flush=True)
            if attempt==2:raise
with zipfile.ZipFile(path) as z:
    name=localizar_membro(z,"ED_SUP_IES")
    text,rows=leitor_csv_zip(z,name)
    institutions={valor(r,"CO_IES"):r for r in rows};text.close()
    name=localizar_membro(z,"CADASTRO_CURSOS")
    text,rows=leitor_csv_zip(z,name)
    bad=[];good=[];ufs={e[0] for e in ESTADOS}
    for row in rows:
        if normalizar(valor(row,"NO_CINE_ROTULO"))!="nutricao":continue
        reasons=[]
        if valor(row,"CO_IES") not in institutions: reasons.append("IES")
        if valor(row,"SG_UF").upper() not in ufs:reasons.append("UF")
        if not valor(row,"NO_MUNICIPIO"):reasons.append("MUNICIPIO")
        if reasons:
            bad.append(row)
        else:good.append(row)
    text.close()
    print("CONTAGENS:",len(good),len(bad),flush=True)
    print("SEM VINCULO MODALIDADES:",dict(collections.Counter(valor(r,"TP_MODALIDADE_ENSINO") for r in bad)),flush=True)
    print("SEM VINCULO CAMPOS:",dict(collections.Counter(k for r in bad for k in ("CO_IES","SG_UF","NO_MUNICIPIO") if not valor(r,k))),flush=True)
    print("AMOSTRA SEM VINCULO:",json.dumps([{k:valor(r,k) for k in ("CO_IES","CO_CURSO","NO_CURSO","TP_MODALIDADE_ENSINO","SG_UF","NO_MUNICIPIO")} for r in bad[:4]],ensure_ascii=False),flush=True)
    print("IES SEM VINCULO:",json.dumps([{k:valor(institutions.get(valor(r,"CO_IES"),{}),k) for k in ("CO_IES","NO_IES","SG_UF_IES","NO_MUNICIPIO_IES","SG_UF","NO_MUNICIPIO")} for r in bad[:3]],ensure_ascii=False),flush=True)
