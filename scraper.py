import csv
import io
import json
import os
import re
import tempfile
import time
import unicodedata
import zipfile
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

# ============================================================
# CONFIGURACAO
# ============================================================

VERSAO = "v5.8"
ETAPA_CARGA_IES = "carga_inep_nutricao_municipal_v58"
ETAPA_CAPTACAO = "captacao_nacional_nutricao_v58"
ETAPA_MIGRACAO_BUSCA = "migracao_busca_nutricao_v58"
ORIGEM_IES = "inep_censo_superior_municipal_v58"
MAX_RESULTADOS = 12
MAX_INSTITUICOES_POR_EXECUCAO = 4
PAUSA_ENTRE_BUSCAS = 3.0

INEP_FONTES = [
    (2024, "https://download.inep.gov.br/microdados/microdados_censo_da_educacao_superior_2024.zip"),
]

ESTADOS = [
    ("AC", "Acre"), ("AL", "Alagoas"), ("AP", "Amapá"), ("AM", "Amazonas"),
    ("BA", "Bahia"), ("CE", "Ceará"), ("DF", "Distrito Federal"),
    ("ES", "Espírito Santo"), ("GO", "Goiás"), ("MA", "Maranhão"),
    ("MT", "Mato Grosso"), ("MS", "Mato Grosso do Sul"), ("MG", "Minas Gerais"),
    ("PA", "Pará"), ("PB", "Paraíba"), ("PR", "Paraná"), ("PE", "Pernambuco"),
    ("PI", "Piauí"), ("RJ", "Rio de Janeiro"), ("RN", "Rio Grande do Norte"),
    ("RS", "Rio Grande do Sul"), ("RO", "Rondônia"), ("RR", "Roraima"),
    ("SC", "Santa Catarina"), ("SP", "São Paulo"), ("SE", "Sergipe"),
    ("TO", "Tocantins"),
]

stats = {
    "ies_carregadas": 0,
    "instituicoes_processadas": 0,
    "instituicoes_concluidas": 0,
    "instituicoes_erro": 0,
    "leads_encontrados": 0,
    "leads_salvos": 0,
    "duplicados": 0,
    "rejeitados": 0,
    "erros": 0,
    "fontes_visitadas": 0,
    "fontes_sem_nomes": 0,
    "consultas_banco_evitadas": 0,
}


def agora():
    return datetime.now(timezone.utc).isoformat()


def limpar_espacos(texto):
    return re.sub(r"\s+", " ", str(texto or "")).strip()


def normalizar(texto):
    texto = limpar_espacos(texto).lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[‐‑‒–—−]", "-", texto)
    return texto


def valor(row, *nomes):
    mapa = {str(k or "").strip().upper(): v for k, v in row.items()}
    for nome in nomes:
        v = mapa.get(nome.upper())
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return ""


def encoding_membro(zf, nome):
    with zf.open(nome) as f:
        amostra = f.read(65536)
    try:
        amostra.decode("utf-8-sig")
        return "utf-8-sig"
    except UnicodeDecodeError:
        return "latin1"


def leitor_csv_zip(zf, nome):
    enc = encoding_membro(zf, nome)
    bruto = zf.open(nome)
    texto = io.TextIOWrapper(bruto, encoding=enc, newline="")
    # O Censo Superior usa ';'. Sniffer fica como protecao para alteracoes futuras.
    cabecalho = texto.readline()
    texto.seek(0)
    delimitador = ";" if cabecalho.count(";") >= cabecalho.count(",") else ","
    return texto, csv.DictReader(texto, delimiter=delimitador)


def localizar_membro(zf, trecho):
    trecho = trecho.upper()
    for nome in zf.namelist():
        if trecho in nome.upper() and nome.upper().endswith(".CSV"):
            return nome
    return None


def formatar_nome_instituicao(nome):
    partes = limpar_espacos(nome).lower().split()
    conectores = {"de", "da", "do", "das", "dos", "e", "em"}
    out = []
    for i, p in enumerate(partes):
        if i > 0 and p in conectores:
            out.append(p)
        else:
            out.append(p[:1].upper() + p[1:])
    return " ".join(out)


# ============================================================
# REPOSITORIO SUPABASE
# ============================================================

class SupabaseRepo:
    def __init__(self, client):
        self.client = client
        self._leads_confirmados = {}

    @classmethod
    def from_env(cls):
        from supabase import create_client
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_KEY"]
        return cls(create_client(url, key))

    def controle_get(self, etapa):
        r = (
            self.client.table("controle_busca")
            .select("*")
            .eq("etapa", etapa)
            .limit(1)
            .execute()
        )
        return r.data[0] if r.data else None

    def controle_salvar(self, etapa, dados):
        payload = dict(dados)
        payload["etapa"] = etapa
        payload["atualizado_em"] = agora()

        # A tabela controle_busca exige estes campos preenchidos.
        # Checkpoints nacionais usam valores neutros em vez de NULL.
        if not payload.get("estado"):
            payload["estado"] = "BR"
        if not payload.get("cidade"):
            payload["cidade"] = "Nacional"
        if not payload.get("instituicao"):
            payload["instituicao"] = "Carga oficial INEP"

        atual = self.controle_get(etapa)
        if atual:
            self.client.table("controle_busca").update(payload).eq("id", atual["id"]).execute()
        else:
            payload.setdefault("tentativas", 0)
            payload.setdefault("iniciado_em", agora())
            self.client.table("controle_busca").insert(payload).execute()

    def contar_ies_v5(self):
        r = (
            self.client.table("instituicoes_nutricao")
            .select("id", count="exact")
            .eq("origem", ORIGEM_IES)
            .execute()
        )
        return r.count or 0

    def upsert_ies(self, registros):
        for inicio in range(0, len(registros), 100):
            lote = registros[inicio: inicio + 100]
            (
                self.client.table("instituicoes_nutricao")
                .upsert(lote, on_conflict="estado,cidade,instituicao")
                .execute()
            )

    def limpar_residuos_v4(self):
        try:
            (
                self.client.table("instituicoes_nutricao")
                .delete()
                .eq("origem", "descoberta_web_nacional_v4")
                .execute()
            )
            print("🧹 Resíduos V4 removidos da fila de instituições.", flush=True)
        except Exception as exc:
            print(f"⚠️ Não foi possível limpar resíduos V4; eles serão ignorados: {exc}", flush=True)

    def fila_estado(self, uf):
        r = (
            self.client.table("instituicoes_nutricao")
            .select("*")
            .eq("origem", ORIGEM_IES)
            .eq("estado", uf)
            .in_("status", ["pendente", "processando", "erro"])
            .execute()
        )
        dados = r.data or []
        ordem = {"pendente": 0, "processando": 1, "erro": 2}
        return sorted(dados, key=lambda x: (ordem.get(x.get("status"), 9), normalizar(x.get("instituicao"))))

    def fila_nacional(self):
        # Todas as ofertas, inclusive concluídas, preservadas como origem.
        dados = []
        offset = 0
        while True:
            r = (self.client.table("instituicoes_nutricao").select("*")
                 .eq("origem", ORIGEM_IES).order("id")
                 .range(offset, offset + 999).execute())
            lote = r.data or []
            dados.extend(lote)
            if len(lote) < 1000:
                break
            offset += 1000
        checkpoints={}
        offset=0
        while True:
            r=(self.client.table("controle_busca").select("etapa,status,atualizado_em,ultimo_erro")
               .order("id").range(offset,offset+999).execute())
            lote=r.data or []
            checkpoints.update({x["etapa"]:x for x in lote})
            if len(lote)<1000: break
            offset+=1000
        fila = []
        faculdades = agrupar_faculdades(dados)
        self._instituicoes_por_dominio_alias = {}
        for faculdade in faculdades:
            sigla = normalizar(alias_instituicao(faculdade))
            if re.fullmatch(r'[a-z0-9-]{4,30}', sigla or ''):
                self._instituicoes_por_dominio_alias.setdefault(sigla, set()).add(normalizar(faculdade['instituicao']))
        for item in faculdades:
            cp = checkpoints.get(etapa_captacao_item(item))
            if cp and cp.get("status") == "concluido":
                continue
            item["tentativa_descoberta"] = int(item.get("tentativa_descoberta") or 0) if cp else 0
            item["_ultimo_checkpoint"] = cp.get("atualizado_em") or "" if cp else ""
            item["_status_checkpoint"] = cp.get("status") if cp else "pendente"
            item["_janela_encerrada"] = bool(cp and cp.get("ultimo_erro") in ("Janela encerrada; próxima consulta preservada", "Janela com fontes pendentes; repetir ao finalizar"))
            fila.append(item)
        # Uma execução interrompida deve retomar antes de abrir outra faculdade.
        ordem={"processando":0,"pendente":1,"erro":2}
        return sorted(fila,key=lambda x:(1 if x.get("_janela_encerrada") else ordem.get(x["_status_checkpoint"],1),x["_ultimo_checkpoint"],normalizar(x["instituicao"])))

    def resultado_de_outra_faculdade(self, resultado, instituicao, alias=None):
        """Domínio de outra IES conhecida não prova vínculo com a IES pesquisada."""
        url = str(resultado.get('href') or resultado.get('url') or '')
        host = (urlparse(url).hostname or '').lower()
        mapa = getattr(self, '_instituicoes_por_dominio_alias', {})
        donos = set().union(*(mapa.get(parte, set()) for parte in host.split('.')))
        if not donos or normalizar(instituicao) in donos:
            return False
        texto = normalizar(str(resultado.get('title') or '')+' '+str(resultado.get('body') or resultado.get('snippet') or ''))
        vinculo = any(re.search(r'(?<!\w)'+re.escape(normalizar(termo))+r'(?!\w)', texto)
                      for termo in (instituicao, alias) if termo)
        return not vinculo

    def contar_pendentes_uf(self, uf):
        r=(self.client.table("instituicoes_nutricao").select("id",count="exact")
           .eq("origem",ORIGEM_IES).eq("estado",uf)
           .in_("status",["pendente","processando","erro"]).execute())
        return r.count or 0

    def atualizar_instituicao(self, iid, **dados):
        dados["ultima_verificacao"] = agora()
        self.client.table("instituicoes_nutricao").update(dados).eq("id", iid).execute()

    def lead_existe(self, nome, instituicao):
        consulta=self.client.table("leds").select("id")
        consulta=consulta.eq("instituicao",instituicao) if instituicao else consulta.is_("instituicao","null")
        r = (
            consulta.ilike("nome", nome)
            .limit(1)
            .execute()
        )
        if r.data:
            return True
        # Consulta canônica paginada cobre acentos e variantes de caixa/espaço.
        if not hasattr(self, '_identidades_existentes'):
            identidades = set()
            for offset in range(0, 100000, 1000):
                rows = (self.client.table('leds').select('nome,instituicao')
                        .order('id').range(offset, offset + 999).execute()).data or []
                identidades.update((normalizar(x['nome']), normalizar(x.get('instituicao'))) for x in rows)
                if len(rows) < 1000:
                    self._identidades_existentes = identidades
                    break
            else:
                raise RuntimeError('Paginação de identidades incompleta')
        return (normalizar(nome), normalizar(instituicao)) in self._identidades_existentes

    def instagram_usado(self, instagram):
        if not instagram:
            return False
        r = (
            self.client.table("leds")
            .select("id")
            .eq("instagram", instagram)
            .limit(1)
            .execute()
        )
        return bool(r.data)

    def lead_da_fonte(self, nome, url):
        if not url: return None
        rows=(self.client.table("leds").select("id,instituicao").eq("fonte_url",url)
              .ilike("nome",nome).limit(1).execute()).data or []
        return rows[0] if rows else None

    def instituicao_de_lead_por_alias(self, nome, alias):
        if not re.fullmatch(r"[A-Za-zÀ-ÿ0-9 .-]{2,30}",alias or ""): return None
        rows=(self.client.table("leds").select("instituicao").ilike("instituicao",alias)
              .ilike("nome",nome).limit(1).execute()).data
        return rows[0]["instituicao"] if rows else None

    def completar_instagram(self, nome, instituicao, instagram):
        if self.instagram_usado(instagram): return False
        consulta=self.client.table("leds").select("id,instagram,qualificado,nao_contatar")
        consulta=consulta.eq("instituicao",instituicao) if instituicao else consulta.is_("instituicao","null")
        rows=consulta.ilike("nome",nome).limit(1).execute().data
        if rows and not rows[0].get("instagram") and not rows[0].get('nao_contatar'):
            acao = 'primeiro_contato_instagram' if rows[0].get('qualificado') else 'validar_fase_academica'
            resposta = (self.client.table("leds").update({"instagram":instagram,"proxima_acao":acao})
             .eq("id",rows[0]["id"]).is_("instagram","null").execute())
            return bool(resposta.data)
        return False

    def isolar_erros_de_nome_comprovados(self):
        # Correção reversível: preservar nome, evidência e URL; impedir contato.
        casos = (
            ("São Luís", "https://www.saoluis.br/"),
            ("Versão Final do Tcc", "https://uni20.com.br/course/view.php?id=6447"),
            ("Nicolle Avaliação Aparecida de da Luz", "https://uniarp.edu.br/wp-content/uploads/2025/11/Edital-Bancas-finais-de-TCC-II-Nutricao.pdf"),
            ("Conformidade Legal", "https://www2.ufjf.br/nutricao/tcc-2025/"),
            ("Semana Acadêmica", "https://cursos.unipampa.edu.br/cursos/nutricao/2025/"),
            ("Material e Métodos", "https://oficial.unimar.br/wp-content/uploads/2026/07/Nutriciencia-2025-.pdf"),
            ("Consentimento Livre e Esclarecido", "https://oficial.unimar.br/wp-content/uploads/2026/07/Nutriciencia-2025-.pdf"),
            ("Del Ré", "https://oficial.unimar.br/wp-content/uploads/2026/07/Nutriciencia-2025-.pdf"),
        )
        for nome, url in casos:
            r = (self.client.table("leds").update({
                "nao_contatar": True, "qualificado": False,
                "proxima_acao": "revisar_nome",
                "fonte_validacao": "erro_comprovado_extracao_nome_revisao",
            }).eq("nome", nome).eq("fonte_url", url)
                .eq("origem", "captacao_nacional_fila_v58")
                .eq("nao_contatar", False).execute())
            print(f"REVISÃO DE NOME COMPROVADA: {nome} | registros isolados: {len(r.data or [])}", flush=True)

    def registrar_pendencia_fonte(self, item, url, erro=None, concluida=False, somente_nova=False):
        import hashlib
        etapa = etapa_captacao_item(item) + "_fonte_" + hashlib.sha256(url.encode()).hexdigest()[:20]
        atual = self.controle_get(etapa)
        if somente_nova and atual: return
        tentativas = 0 if concluida else int((atual or {}).get('tentativas') or 0) + 1
        self.controle_salvar(etapa, {
            "instituicao": item["instituicao"], "estado": item.get("estado"),
            "cidade": item.get("cidade"), "status": "concluido" if concluida else "erro",
            "consulta_atual": url, "ultimo_erro": None if concluida else str(erro)[:1000],
            'tentativas': tentativas,
        })

    def fonte_pode_retentar(self, item, url):
        import hashlib
        etapa = etapa_captacao_item(item) + '_fonte_' + hashlib.sha256(url.encode()).hexdigest()[:20]
        cp = self.controle_get(etapa)
        if not cp or cp.get('status') != 'erro':
            return True
        tentativas = int(cp.get('tentativas') or 0)
        if tentativas >= 5:
            print(f'FONTE REQUER REVISÃO: {url}; cinco tentativas preservadas', flush=True)
            return False
        try:
            atualizacao = datetime.fromisoformat(cp['atualizado_em'].replace('Z', '+00:00'))
            espera = timedelta(minutes=min(24 * 60, 30 * 2 ** max(0, tentativas - 1)))
            return datetime.now(timezone.utc) >= atualizacao + espera
        except (KeyError, ValueError, TypeError):
            return True

    def fontes_pendentes(self, item):
        rows=[]
        for offset in range(0,100000,1000):
            lote=(self.client.table("controle_busca").select("consulta_atual")
                  .like("etapa", etapa_captacao_item(item) + "_fonte_%")
                  .eq("status", "erro").order("atualizado_em")
                  .range(offset,offset+999).execute()).data or []
            rows.extend(r["consulta_atual"] for r in lote if r.get("consulta_atual"))
            if len(lote)<1000: return list(dict.fromkeys(rows))
        raise RuntimeError("Paginação das fontes pendentes incompleta")

    def fontes_concluidas(self, item):
        urls=set()
        for offset in range(0,100000,1000):
            lote=(self.client.table('controle_busca').select('consulta_atual')
                  .like('etapa', etapa_captacao_item(item)+'_fonte_%')
                  .eq('status','concluido').order('id').range(offset,offset+999).execute()).data or []
            urls.update(r['consulta_atual'] for r in lote if r.get('consulta_atual'))
            if len(lote)<1000: return urls
        raise RuntimeError('Paginação das fontes concluídas incompleta')

    def contar_leads(self):
        return self.client.table("leds").select("id", count="exact", head=True).execute().count

    def inserir_lead(self, dados):
        for tentativa in range(3):
            try:
                self.client.table('leds').insert(dados).execute()
                if hasattr(self, '_identidades_existentes'):
                    self._identidades_existentes.add((normalizar(dados['nome']), normalizar(dados.get('instituicao'))))
                return True
            except Exception as exc:
                # Timeout pode ocorrer depois do commit; confirmar antes de repetir.
                self.__dict__.pop('_identidades_existentes', None)
                if self.lead_existe(dados['nome'], dados.get('instituicao')):
                    return False
                codigo = str(getattr(exc, 'code', ''))
                transitorio = isinstance(exc, (TimeoutError, ConnectionError)) or codigo in {'503', '504', '502', '500', '429', '08006', '08003', '40001', '40P01'} or any(t in str(exc).lower() for t in ('timeout', 'timed out', 'connection reset', 'temporarily unavailable'))
                if tentativa == 2 or not transitorio:
                    raise
                time.sleep(2 ** tentativa)

    def fontes_da_instituicao(self, instituicao):
        fontes=[]
        for offset in range(0,100000,1000):
            rows=(self.client.table("leds").select("fonte_url").eq("instituicao",instituicao)
                  .eq("nao_contatar",False).order("id").range(offset,offset+999).execute()).data or []
            for row in rows:
                if row.get("fonte_url") and row["fonte_url"] not in fontes:
                    fontes.append(row["fonte_url"])
            if len(rows)<1000: return fontes
        raise RuntimeError("Paginação das fontes incompleta")


# ============================================================
# CARGA DETERMINISTICA DA FILA DE INSTITUICOES
# ============================================================

def ler_fila_inep_zip(caminho, ano=2024):
    """Cruza cadastro de cursos/IES pelo CO_IES, preservando município da oferta."""
    with zipfile.ZipFile(caminho) as zf:
        cursos_nome = localizar_membro(zf, "CADASTRO_CURSOS") or localizar_membro(zf, "DM_CURSO")
        ies_nome = localizar_membro(zf, "ED_SUP_IES") or localizar_membro(zf, "DM_IES")
        if not cursos_nome or not ies_nome:
            raise RuntimeError("ZIP INEP sem cadastro de cursos e instituições")
        ies = {}
        texto, rows = leitor_csv_zip(zf, ies_nome)
        try:
            for row in rows:
                cod = valor(row,"CO_IES")
                nome = valor(row,"NO_IES")
                if cod and nome:
                    ies[cod] = (formatar_nome_instituicao(nome),valor(row,"SG_IES"))
        finally: texto.close()
        texto, rows = leitor_csv_zip(zf,cursos_nome)
        required = {"CO_IES","SG_UF","NO_MUNICIPIO","NO_CINE_ROTULO"}
        if not required.issubset({str(c).upper() for c in (rows.fieldnames or [])}):
            texto.close()
            raise RuntimeError("Cadastro INEP sem campos necessários para curso/município")
        registros = {}; sem_vinculo = 0; sedes_ead = []; ies_municipais = set()
        try:
            for row in rows:
                if normalizar(valor(row,"NO_CINE_ROTULO")) != "nutricao": continue
                if valor(row,"NU_ANO_CENSO") and valor(row,"NU_ANO_CENSO") != str(ano):
                    raise RuntimeError("Ano divergente no cadastro de cursos")
                cod = valor(row,"CO_IES")
                uf, cidade = valor(row,"SG_UF").upper(),limpar_espacos(valor(row,"NO_MUNICIPIO"))
                # A linha sede EaD não é um município de oferta. Os polos da
                # mesma IES estão em linhas próprias; não usar cidade da sede.
                if cod in ies and not uf and not cidade and valor(row,"TP_MODALIDADE_ENSINO") == "2":
                    sedes_ead.append(cod)
                    continue
                if cod not in ies or uf not in {e[0] for e in ESTADOS} or not cidade:
                    sem_vinculo += 1; continue
                ies_municipais.add(cod)
                nome, sigla = ies[cod]
                key = (uf,normalizar(cidade),normalizar(nome))
                registros[key] = dict(estado=uf,cidade=cidade,instituicao=nome,curso="Nutrição",
                                      origem=ORIGEM_IES,fonte_url=INEP_FONTES[0][1],status="pendente",
                                      fonte_validacao=f"INEP {ano} cadastro de cursos por município | CO_IES={cod} | SIGLA={sigla}",
                                      validada=True,tentativa_descoberta=0)
        finally: texto.close()
        sem_vinculo += sum(cod not in ies_municipais for cod in sedes_ead)
        if sedes_ead:
            print(f"ℹ️ INEP: {len(sedes_ead)} linhas sede EaD; {sum(cod in ies_municipais for cod in sedes_ead)} com faculdade já representada nas ofertas municipais.",flush=True)
        if sem_vinculo:
            raise RuntimeError(f"{sem_vinculo} ofertas de Nutrição sem município/instituição; carga incompleta")
        return list(registros.values())


def carregar_instituicoes_municipais_inep():
    import requests
    ano, url = INEP_FONTES[0]
    arquivo_local = os.environ.get("INEP_CADASTROS_PATH")
    if arquivo_local:
        registros = ler_fila_inep_zip(arquivo_local,ano)
        if {r["estado"] for r in registros} != {e[0] for e in ESTADOS} or len(registros)<500:
            raise RuntimeError("Arquivo local INEP sem cobertura nacional validada")
        print(f"✅ INEP em cache validado: {len(registros)} combinações faculdade/município",flush=True)
        return ano,registros
    for tentativa in range(1,4):
        try:
            print(f"📥 INEP {ano}: preparando fila faculdade/município, tentativa {tentativa}/3",flush=True)
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp,"inep.zip")
                # O servidor envia só a folha. Completar a intermediária mantém
                # a verificação de hostname e a cadeia até as raízes habituais.
                import certifi, ssl, hashlib
                cert_url = "https://www.detic.unicamp.br/wp-content/uploads/sites/38/2026/05/intermediate_2025.pem"
                cert_response = requests.get(cert_url,timeout=(10,30))
                cert_response.raise_for_status()
                pem = cert_response.text
                fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
                if fingerprint != "e10747d4da7bab09cba9952f019d3534cb9fba070bf13d8791b1699cd2ff59dd":
                    raise RuntimeError("Certificado intermediário diferente do validado; revisar fonte")
                ca_path = os.path.join(tmp,"inep-ca.pem")
                with open(ca_path,"w") as bundle:
                    with open(certifi.where()) as roots: bundle.write(roots.read()+"\n"+pem)
                with requests.get(url,stream=True,timeout=(20,90),verify=ca_path) as response:
                    response.raise_for_status()
                    size = 0
                    with open(path,"wb") as dest:
                        for chunk in response.iter_content(1024*1024):
                            size += len(chunk)
                            if size > 1024*1024*1024: raise RuntimeError("ZIP INEP acima de 1 GB")
                            dest.write(chunk)
                registros = ler_fila_inep_zip(path,ano)
            estados = {r["estado"] for r in registros}
            if estados != {e[0] for e in ESTADOS} or len(registros) < 500:
                raise RuntimeError("Fila municipal incompleta: conferir estados e quantidade")
            print(f"✅ INEP: {len(registros)} combinações faculdade/município nos 26 estados e DF",flush=True)
            return ano,registros
        except Exception as exc:
            print(f"⚠️ Carga municipal INEP: {exc}",flush=True)
            if tentativa == 3: raise
            time.sleep(3.0)


def garantir_fila_oficial(repo):
    cp = repo.controle_get(ETAPA_CARGA_IES)
    total = repo.contar_ies_v5()
    if cp and cp.get("status") == "concluido" and total > 0:
        print(f"📚 Base oficial INEP V5 já carregada: {total} registros.", flush=True)
        return True

    repo.controle_salvar(ETAPA_CARGA_IES, {
        "estado": None,
        "cidade": None,
        "instituicao": None,
        "status": "processando",
        "ultimo_erro": None,
        "leads_encontrados": 0,
        "leads_salvos": 0,
    })

    try:
        ano, registros = carregar_instituicoes_municipais_inep()
        if not registros:
            raise RuntimeError("o filtro oficial nao encontrou nenhum curso de Nutricao")
        repo.upsert_ies(registros)
        total = repo.contar_ies_v5()
        if total < len(registros):
            raise RuntimeError(f"carga suspeita: apenas {total} registros de Nutricao")
        repo.controle_salvar(ETAPA_CARGA_IES, {
            "estado": None,
            "cidade": None,
            "instituicao": None,
            "status": "concluido",
            "ultimo_erro": None,
            "leads_encontrados": len(registros),
            "leads_salvos": total,
            "fonte_atual": f"INEP {ano} cadastro de cursos por município",
            "finalizado_em": agora(),
        })
        stats["ies_carregadas"] = total
        print(f"✅ Fila oficial carregada: {total} registro(s) de IES/cidade com Nutrição.", flush=True)
        return True
    except Exception as exc:
        stats["erros"] += 1
        repo.controle_salvar(ETAPA_CARGA_IES, {
            "estado": None,
            "cidade": None,
            "instituicao": None,
            "status": "erro",
            "ultimo_erro": str(exc)[:1000],
        })
        print(f"❌ Falha na carga oficial do INEP: {exc}", flush=True)
        return False


def preparar_varredura_v58(repo):
    """Reabre a fila uma única vez para aplicar buscas e filtros V5.8.

    Os leads existentes são preservados; a deduplicação impede reinserção.
    """
    cp = repo.controle_get(ETAPA_MIGRACAO_BUSCA)
    if cp and cp.get("status") == "concluido":
        return True

    try:
        (
            repo.client.table("instituicoes_nutricao")
            .update({
                "status": "pendente",
                "tentativa_descoberta": 0,
                "ultima_verificacao": agora(),
            })
            .eq("origem", ORIGEM_IES)
            .execute()
        )

        repo.controle_salvar(ETAPA_MIGRACAO_BUSCA, {
            "estado": "BR",
            "cidade": "Nacional",
            "instituicao": "Reabertura da fila para V5.8",
            "status": "concluido",
            "ultimo_erro": None,
            "finalizado_em": agora(),
        })

        print("🔄 Fila oficial reaberta uma vez para a varredura V5.8.", flush=True)
        return True

    except Exception as exc:
        stats["erros"] += 1
        repo.controle_salvar(ETAPA_MIGRACAO_BUSCA, {
            "estado": "BR",
            "cidade": "Nacional",
            "instituicao": "Reabertura da fila para V5.8",
            "status": "erro",
            "ultimo_erro": str(exc)[:1000],
        })
        print(f"❌ Falha preparando a fila V5.8: {exc}", flush=True)
        return False


# ============================================================
# BUSCA WEB CONTROLADA
# ============================================================

def ddgs_texto(consulta, backend="auto", max_results=MAX_RESULTADOS):
    from ddgs import DDGS
    with DDGS(timeout=10) as ddgs:
        return list(ddgs.text(
            consulta,
            region="br-pt",
            safesearch="moderate",
            max_results=max_results,
            backend=backend,
        ) or [])


def buscar_web(consulta, max_results=MAX_RESULTADOS, fetch_fn=ddgs_texto):
    """Automático com repetição e Bing alternativo, comprovados no runner."""
    erros=[]; respondeu_vazio=False
    for indice,backend in enumerate(('auto','auto','bing')):
        try:
            try: resultados=fetch_fn(consulta,backend,max_results)
            except TypeError: resultados=fetch_fn(consulta,max_results)
            resultados=list(resultados or [])
            print(f"      BUSCADOR: {backend} | resultados: {len(resultados)}",flush=True)
            if resultados: return resultados
            respondeu_vazio=True
        except Exception as exc:
            erros.append((backend,exc))
            print(f"      BUSCADOR: {backend} | erro: {type(exc).__name__}",flush=True)
        if indice==0: time.sleep(4.0)
    if respondeu_vazio and not erros: return []
    # Controle de saúde não transforma timeout da consulta original em vazio.
    if any('no results' not in str(exc).lower() for _, exc in erros):
        print('      ⚠️ Busca parcial: consulta original mantém pendência', flush=True)
        return None
    if erros and not respondeu_vazio and not any('no results' in str(e).lower() for _,e in erros):
        print("      ⚠️ Busca externa indisponível em automático e Bing",flush=True)
        return None
    # 'No results found' sozinho não comprova que o mecanismo está disponível.
    for backend in ('auto','bing'):
        try:
            if list(fetch_fn('Brasil',backend,1) or []):
                print(f"      CONTROLE BUSCADOR: {backend} respondeu; consulta sem resultados",flush=True)
                return []
        except Exception: pass
    print("      ⚠️ Busca externa indisponível após controle de funcionamento",flush=True)
    return None


def alias_instituicao(item):
    fonte = str(item.get("fonte_validacao") or "")
    m = re.search(r"(?:^|\|)\s*SIGLA=([^|]+)", fonte, flags=re.I)
    if not m:
        nome=normalizar(item.get('instituicao'))
        return 'Unopar' if re.search(r'\bunopar\b',nome) else None
    alias = limpar_espacos(m.group(1))
    if 'joinville' in normalizar(item.get('instituicao')):
        alias=re.sub(r'\bjoinvile\b','Joinville',alias,flags=re.I)
    return alias if 2 <= len(alias) <= 30 else ('Unopar' if re.search(r'\bunopar\b',normalizar(item.get('instituicao'))) else None)


def consultas_documentos_alunos(instituicao, alias=None):
    """Fontes complementares; curso e período são lidos na evidência encontrada."""
    termo = limpar_espacos(alias or instituicao)
    sinais = ('relação de concluintes', 'outorga de grau nomes',
              'calendário defesas autores', 'filetype:pdf alunos',
              'projeto integrador alunas autores', 'liga acadêmica nova gestão integrantes',
              'centro acadêmico diretoria', 'juramentista oradora formanda',
              'boletim de serviços concluintes', 'aptos a colar grau')
    simples=[f'{termo} Nutrição {sinal}' for sinal in ('e-book','graduandas artigo','mostra TCC','liga integrantes')]
    perfis=[f'{termo} Nutrição "{fase}º semestre"' for fase in (7,8)]
    perfis += [f'{termo} Nutrição site:linkedin.com/in "{fase}º semestre"' for fase in (7,8)]
    return simples + [f'{termo} Nutrição {ano} {sinal}' for ano in (2025,2026) for sinal in sinais] + perfis


def consultas_leads(instituicao, alias=None, cidade=None, uf=None):
    # Mesma estratégia para toda IES/município; o nome e a sigla são alternativos.
    termos = list(dict.fromkeys(limpar_espacos(t) for t in (instituicao, alias) if t))
    sinais = ('"formandos"', '"colação de grau"', '"TCC"', '"concluintes"',
              '"turma"', '"recém-formados"', '"recém-formadas"',
              '"último semestre"', '"último período"', '"estágio final"',
              '"alunos" "conclusão"', '"mostra" "autores"',
              '"defesa" "TCC"', '"apresentação" "trabalho de conclusão"',
              '"repositório"', '"lista de formandos"',
              '"cerimônia de formatura"', '"concluíram"',
              '"jornada acadêmica" "trabalhos"', '"entrega" "TCC"', '"aluno"', '"aluna"',
              '"grupo de alunos"', '"estudante" "apresentação"', '"acadêmico do curso"',
              '"acadêmica do curso"', '"discente" "artigo"',
              '"grupo de estudantes"', '"grupo de estudos"', '"turma de nutrição"',
              '"liga acadêmica" "integrantes"', '"centro acadêmico" "membros"',
              '"alunos de nutrição"', '"estudantes de nutrição"',
              '"grupo" "alunos"', '"projeto integrador"', '"iniciação científica"',
              '"iniciação tecnológica"', '"projetos aprovados"', '"resultado" "monitoria"',
              '"extensão" "alunos"', '"workshop" "alunos"', '"caderno de resumos"',
              '"anais" "autores"', '"ebook" "alunos"', '"e-book" "alunas"',
              '"semana acadêmica"', '"jornada" "graduanda"')
    # Consultas menos restritas antecipam documentos com autores, sem exigir
    # que a página use a razão social ou a palavra exata "formandos".
    curto = limpar_espacos(alias or instituicao)
    prioritarias = [f'{curto} Nutrição {ano} {sinal}'
                   for ano in (2025, 2026)
                   for sinal in ('TCC repositório', 'trabalho de conclusão de curso autores')]
    consultas = prioritarias + consultas_documentos_alunos(instituicao, alias) + [f'"{termo}" Nutrição {sinal} {ano}'
                 for ano in (2025, 2026) for sinal in sinais for termo in termos]
    if cidade and normalizar(cidade) != "nao identificado":
        consultas += [f'"{instituicao}" "{cidade}" {uf or ""} Nutrição "turma" {ano}'
                      for ano in (2025,2026)]
    consultas += [f'site:linkedin.com/in "{instituicao}" Nutrição {ano}' for ano in (2025,2026)]
    return list(dict.fromkeys(consultas))


def formatar_nome_pessoa(nome):
    partes = limpar_espacos(nome).lower().split()
    conectores = {"de", "da", "do", "das", "dos", "e"}
    saida = []
    for i, p in enumerate(partes):
        if i > 0 and p in conectores:
            saida.append(p)
        else:
            saida.append(p[:1].upper() + p[1:])
    return " ".join(saida)


def salvar_lead(repo, nome, instituicao, cidade, uf, texto, url, instagram=None, linkedin=None, ano_forcado=None, periodo_forcado=None, instituicao_alias=None, candidato_indicio=False):
    from fontes_academicas import pessoa, fase_final_comprovada
    if not pessoa(nome):
        stats["rejeitados"] += 1
        return False
    nome = formatar_nome_pessoa(nome)
    cache=getattr(repo,"_leads_confirmados",None)
    chave=(normalizar(nome),url,instituicao,instituicao_alias)
    reutilizado=isinstance(cache,dict) and bool(url) and chave in cache
    if reutilizado:
        existente_fonte={"instituicao":cache[chave]}
        stats["consultas_banco_evitadas"] += 1
    else:
        existente_fonte=repo.lead_da_fonte(nome,url) if hasattr(repo,"lead_da_fonte") else None
    existe=existente_fonte is not None or repo.lead_existe(nome,instituicao)
    instituicao_existente=existente_fonte.get("instituicao") if existente_fonte is not None else instituicao
    if not existe and instituicao_alias and hasattr(repo,"instituicao_de_lead_por_alias"):
        instituicao_existente = repo.instituicao_de_lead_por_alias(nome,instituicao_alias)
        existe=instituicao_existente is not None
    if existe:
        if isinstance(cache,dict) and url:
            cache[chave]=instituicao_existente
        if instagram and hasattr(repo,"completar_instagram"):
            if repo.completar_instagram(nome,instituicao_existente,instagram):
                print(f"      Instagram completado pela fonte: {nome} | {instagram}",flush=True)
        stats["duplicados"] += 1
        print(f"      ♻️ DUPLICADO: {nome}", flush=True)
        return False
    if instagram and repo.instagram_usado(instagram):
        instagram = None

    ano = ano_forcado
    periodo = periodo_forcado
    periodo_sem_ano = ano is None and periodo and re.search(r'[78]º período/semestre',periodo) and "nutricao" in normalizar(texto)
    if (ano not in {2025,2026} and not periodo_sem_ano) or not periodo:
        raise ValueError("Lead precisa de ano/período extraídos da fonte acadêmica")
    candidato_indicio = candidato_indicio or not fase_final_comprovada(texto)
    dados = {
        "nome": nome,
        "instagram": instagram,
        "linkedin": linkedin,
        "whatsapp": None,
        "nicho": "nutricionista",
        "origem": "captacao_nacional_fila_v58",
        "status": "novo",
        "app_baixado": False,
        "nao_contatar": False,
        "qualificado": not candidato_indicio,
        "data_primeiro_contato": None,
        "data_ultimo_contato": None,
        "proxima_acao": "validar_fase_academica" if candidato_indicio else ("primeiro_contato_instagram" if instagram else "buscar_instagram"),
        "tentativas_contato": 0,
        "cliente": False,
        "funil_destino": None,
        "cidade": cidade or "Não identificado",
        "estado": uf,
        "instituicao": instituicao,
        "pontuacao": 10,
        "evidencia": limpar_espacos(texto)[:1500],
        "fonte_url": url or None,
        "ano_alvo": ano,
        "periodo_alvo": periodo or ("2025/2026" if ano else None),
        "origem_lead": "captacao_academica",
        "rede_processada": False,
        "nivel_rede": 0,
        "fonte_validacao": "candidato_academico_fase_a_validar" if candidato_indicio else "fonte_publica_validada_v58",
    }
    if repo.inserir_lead(dados) is False:
        stats['duplicados'] += 1
        return False
    if isinstance(cache,dict) and url:
        if len(cache)>=20000: cache.clear()
        cache[chave]=instituicao
    stats["leads_salvos"] += 1
    print(f"      ✅ SALVO: {nome}" + (f" | {instagram}" if instagram else " | Instagram pendente"), flush=True)
    return True


# ============================================================
# CAPTACAO / CHECKPOINT
# ============================================================

def agrupar_faculdades(dados):
    """Uma pesquisa nacional por instituição; polos não são novas faculdades."""
    grupos = {}
    for registro in sorted(dados, key=lambda x: x["id"]):
        chave = normalizar(registro["instituicao"])
        if chave not in grupos:
            item = dict(registro)
            item.update(cidade=None, estado=None, escopo_faculdade=True,
                        tentativa_descoberta=registro.get("tentativa_descoberta", 0))
            grupos[chave] = item
    return sorted(grupos.values(), key=lambda x: normalizar(x["instituicao"]))


def etapa_captacao_item(item):
    return f"{ETAPA_CAPTACAO}_{'faculdade_' if item.get('escopo_faculdade') else ''}{item['id']}"


def checkpoint_captacao(repo, item, status, indice, total, consulta=None, erro=None, encontrados=0, salvos=0):
    repo.controle_salvar(etapa_captacao_item(item), {
        "estado": item.get("estado"),
        "cidade": item.get("cidade"),
        "instituicao": item.get("instituicao"),
        "status": status,
        "indice_pesquisa": indice,
        "total_pesquisas": total,
        "consulta_atual": consulta,
        "ultimo_erro": erro,
        "leads_encontrados": encontrados,
        "leads_salvos": salvos,
        "finalizado_em": agora() if status == "concluido" else None,
    })


def processar_instituicao(repo, item, search_fn=buscar_web, source_fn=None, continuar_falhas=False, limite_consultas=None, prazo=None):
    from fontes_academicas import carregar_fonte, url_permitida, extrair_resultado_busca, recuperar_fonte_na_busca, acesso_reservado_maquina2, FASE
    source_fn = source_fn or carregar_fonte
    iid, instituicao, uf = item["id"], item["instituicao"], item["estado"]
    cidade = item.get("cidade") or "Não identificado"
    alias = alias_instituicao(item)
    consultas = consultas_leads(instituicao, alias, None if item.get("escopo_faculdade") else cidade, uf)
    fontes_conhecidas=repo.fontes_da_instituicao(instituicao) if hasattr(repo,"fontes_da_instituicao") else []
    if fontes_conhecidas: consultas.insert(0,"FONTES PÚBLICAS JÁ DESCOBERTAS")
    total = len(consultas)
    cp = repo.controle_get(etapa_captacao_item(item))
    inicio = 0
    if cp and cp.get("ultimo_erro", "") and str(cp["ultimo_erro"]).startswith("Fontes inacessíveis") and cp.get("indice_pesquisa") == cp.get("total_pesquisas") and hasattr(repo,"fontes_pendentes"):
        return retentar_fontes_pendentes(repo,item,cp,source_fn,limite_consultas or 6,prazo=prazo)
    if cp and cp.get("instituicao") == instituicao and cp.get("estado") == (uf or "BR") and cp.get("status") in {"processando", "erro"}:
        # Nova varredura repete tudo; falha de busca retoma apenas a consulta interrompida.
        if cp.get("ultimo_erro") == "Busca externa indisponível" or str(cp.get("ultimo_erro") or "").startswith("Falha isolada na faculdade:"):
            inicio = (consultas.index(cp["consulta_atual"]) if cp.get("consulta_atual") in consultas
                      else min(max(int(cp.get("indice_pesquisa") or 0), 0), total-1))
        elif cp.get("status") == "processando" and cp.get("ultimo_erro") in (None, "Janela encerrada; próxima consulta preservada", "Janela com fontes pendentes; repetir ao finalizar") and cp.get("total_pesquisas") == total:
            # Interrupção do runner: continuar da próxima consulta ainda não concluída.
            inicio = min(max(int(cp.get("indice_pesquisa") or 0), 0), total)
        if cp.get('status')=='processando' and cp.get('ultimo_erro') in (None, 'Janela encerrada; próxima consulta preservada', 'Janela com fontes pendentes; repetir ao finalizar') and total-int(cp.get('total_pesquisas') or 0) in (0,1) and cp.get('consulta_atual') in consultas:
            inicio=consultas.index(cp['consulta_atual'])
    print(f"\n🏫 {uf} | {cidade} | {instituicao} | WEB / TURMAS", flush=True)
    repo.atualizar_instituicao(iid, status="processando")
    salvos_antes = stats["leads_salvos"]
    encontrados_local = int(cp.get("leads_encontrados") or 0) if inicio else 0
    salvos_checkpoint = int(cp.get("leads_salvos") or 0) if inicio else 0
    fontes_vistas = set(repo.fontes_concluidas(item)) if hasattr(repo, "fontes_concluidas") else set()
    pendentes_conhecidas=set(repo.fontes_pendentes(item)) if hasattr(repo,"fontes_pendentes") else set()
    falhas_fontes = int(bool(inicio and cp and cp.get("ultimo_erro") == "Janela com fontes pendentes; repetir ao finalizar"))
    falhas_busca_seguidas = 0
    primeira_busca_pendente = None
    fim=min(total,inicio+max(1,int(limite_consultas))) if limite_consultas is not None else total
    for idx in range(inicio, fim):
        if prazo is not None and time.monotonic() >= prazo:
            fim=idx
            print("LIMITE DO CICLO: próxima consulta preservada",flush=True)
            break
        consulta = consultas[idx]
        inicio_consulta=time.monotonic()
        nomes_consulta=set()
        salvos_consulta=stats["leads_salvos"]
        duplicados_consulta=stats["duplicados"]
        fontes_consulta=stats["fontes_visitadas"]
        print(f"   🔎 [{idx+1}/{total}] {consulta}", flush=True)
        indice_cp = primeira_busca_pendente if primeira_busca_pendente is not None else idx
        checkpoint_captacao(repo,item,"erro" if primeira_busca_pendente is not None else "processando",indice_cp,total,consulta=consultas[indice_cp],erro="Busca externa indisponível" if primeira_busca_pendente is not None else ("Fontes pendentes; repetir varredura" if falhas_fontes else None),
                            encontrados=encontrados_local,salvos=salvos_checkpoint+stats["leads_salvos"]-salvos_antes)
        resultados = ([{"href":url} for url in fontes_conhecidas] if consulta=="FONTES PÚBLICAS JÁ DESCOBERTAS"
                      else search_fn(consulta, MAX_RESULTADOS))
        if resultados is None:
            if continuar_falhas:
                if primeira_busca_pendente is None:
                    primeira_busca_pendente = idx
                falhas_fontes += 1
                stats["erros"] += 1
                falhas_busca_seguidas += 1
                print(f"      CONSULTA PENDENTE: {consulta}",flush=True)
                if falhas_busca_seguidas >= 3:
                    retomar=primeira_busca_pendente
                    repo.atualizar_instituicao(iid,status="erro")
                    stats["instituicoes_erro"] += 1
                    checkpoint_captacao(repo,item,"erro",retomar,total,consulta=consultas[retomar],erro="Busca externa indisponível",
                                        encontrados=encontrados_local,salvos=salvos_checkpoint+stats["leads_salvos"]-salvos_antes)
                    print("      BUSCADOR INDISPONÍVEL: três falhas seguidas; retomar da primeira consulta pendente.",flush=True)
                    return False
                continue
            repo.atualizar_instituicao(iid,status="erro")
            stats["instituicoes_erro"] += 1
            checkpoint_captacao(repo,item,"erro",idx,total,consulta=consulta,erro="Busca externa indisponível",
                                encontrados=encontrados_local,salvos=salvos_checkpoint+stats["leads_salvos"]-salvos_antes)
            return False
        falhas_busca_seguidas = 0
        if hasattr(repo, 'resultado_de_outra_faculdade') and consulta != 'FONTES PÚBLICAS JÁ DESCOBERTAS':
            relacionados=[]
            for resultado in resultados:
                if repo.resultado_de_outra_faculdade(resultado, instituicao, alias):
                    print('FONTE DE OUTRA FACULDADE: pesquisa atual segue para outros resultados |', resultado.get('href') or resultado.get('url'), flush=True)
                else:
                    relacionados.append(resultado)
            resultados=relacionados
        for resultado in resultados:
            url_resultado=str(resultado.get("href") or resultado.get("url") or "")
            if not url_permitida(url_resultado): continue
            for registro in extrair_resultado_busca(resultado,instituicao,alias):
                nomes_consulta.add(normalizar(registro["nome"]))
                encontrados_local += 1
                stats["leads_encontrados"] += 1
                registro["evidencia"] += " | Consultado em "+agora()
                print("      EVIDÊNCIA NA BUSCA:",registro["nome"],"|",url_resultado,flush=True)
                salvar_lead(repo,registro["nome"],registro.get("instituicao",instituicao),None,None,registro["evidencia"],url_resultado,
                            ano_forcado=registro["ano"],periodo_forcado=registro["periodo"],instituicao_alias=alias if registro.get("instituicao",instituicao)==instituicao else None)
        termos=[normalizar(t) for t in (instituicao,alias) if t]
        resultados_relacionados=[]
        for resultado in resultados:
            texto=normalizar(str(resultado.get("title") or "")+" "+str(resultado.get("body") or resultado.get("snippet") or ""))
            if re.search(r"\b(?:morre|morreu|falecimento|obito)\b",normalizar(str(resultado.get("title") or ""))):
                print("      NOTÍCIA DE FALECIMENTO: fora da captura",flush=True)
                continue
            # Fontes conhecidas e resultados sem resumo continuam sendo lidos.
            host=(urlparse(str(resultado.get("href") or resultado.get("url") or "")).hostname or "").lower()
            hosts_conhecidos={(urlparse(u).hostname or "").lower() for u in fontes_conhecidas}
            host_institucional=host in hosts_conhecidos or any(t and t.replace(' ','') in host.split('.') for t in termos)
            contexto_academico=bool(re.search(FASE+r'|projetos aprovados|iniciacao cientifica',texto)) or bool(re.search(r'\.pdf(?:\?|$)',str(resultado.get('href') or resultado.get('url') or '')))
            if host_institucional or not texto.strip() or (contexto_academico and ('nutricao' in texto or any(re.search(r'(?<!\w)'+re.escape(t)+r'(?!\w)',texto) for t in termos))):
                resultados_relacionados.append(resultado)
            else:
                print("      RESULTADO SEM CONTEXTO ACADÊMICO RELEVANTE:",resultado.get("href") or resultado.get("url"),flush=True)
        fila = [(str(r.get("href") or r.get("url") or ""),0) for r in resultados_relacionados]
        for posicao,(url, depth) in enumerate(fila):
            if prazo is not None and time.monotonic() >= prazo and hasattr(repo,"registrar_pendencia_fonte"):
                adiadas={u for u,_ in fila[posicao:] if u not in fontes_vistas and url_permitida(u) and not acesso_reservado_maquina2(u)}
                for adiada in adiadas:
                    repo.registrar_pendencia_fonte(item,adiada,"Leitura adiada pelo limite de tempo",somente_nova=True)
                falhas_fontes += len(adiadas)
                print(f"LIMITE DO CICLO: {len(adiadas)} URLs preservadas para leitura posterior",flush=True)
                break
            if url in fontes_vistas or not url_permitida(url): continue
            if url in pendentes_conhecidas and hasattr(repo, 'fonte_pode_retentar') and not repo.fonte_pode_retentar(item, url):
                continue
            if acesso_reservado_maquina2(url):
                print(f"      ACESSO AO INSTAGRAM RESERVADO À MÁQUINA 2: {url}; evidências da busca já processadas",flush=True)
                continue
            fontes_vistas.add(url)
            fonte_lida = False
            try:
                stats["fontes_visitadas"] += 1
                registros, links = source_fn(url,instituicao,alias)
                fonte_lida = True
                if not registros: stats["fontes_sem_nomes"] += 1
            except Exception as exc:
                falhas_fontes += 1
                stats["erros"] += 1
                if hasattr(repo,"registrar_pendencia_fonte"):
                    repo.registrar_pendencia_fonte(item,url,exc)
                    pendentes_conhecidas.add(url)
                print(f"      ⚠️ FONTE PENDENTE: {url} | {str(exc)[:250]}",flush=True)
                try:
                    registros,links=recuperar_fonte_na_busca(url,instituicao,alias,search_fn)
                except Exception as recuperacao:
                    print(f"      ÍNDICE INDISPONÍVEL: {str(recuperacao)[:150]}",flush=True)
                    registros,links=[],[]
                if not registros: continue
                print(f"      RECUPERADO NO ÍNDICE: {len(registros)} nomes; acesso direto ainda pendente",flush=True)
            print(f"      📄 FONTE: {url} | pessoas: {len(registros)}",flush=True)
            from urllib.parse import parse_qs
            for link in links:
                destino=urlparse(link); atual=urlparse(url)
                pagina=(destino.hostname==atual.hostname and destino.path==atual.path
                        and bool({'offset','page'} & set(parse_qs(destino.query))))
                if url_permitida(link) and (depth==0 or pagina):
                    fila.append((link,depth if pagina else 1))
            for registro in registros:
                nomes_consulta.add(normalizar(registro["nome"]))
                encontrados_local += 1
                stats["leads_encontrados"] += 1
                contexto = normalizar(registro.get("contexto_academico", ""))
                cidade_confirmada = bool(cidade and re.search(r'(?<!\w)'+re.escape(normalizar(cidade))+r'(?!\w)',contexto))
                salvar_lead(repo,registro["nome"],registro.get("instituicao",instituicao),cidade if cidade_confirmada else None,
                            uf if cidade_confirmada else None,registro["evidencia"],registro.get("fonte_url",url),
                            instagram=registro.get("instagram"),candidato_indicio=registro.get("candidato_indicio",False),
                            ano_forcado=registro["ano"],periodo_forcado=registro["periodo"],instituicao_alias=alias if registro.get("instituicao",instituicao)==instituicao else None)
            if fonte_lida and hasattr(repo, 'registrar_pendencia_fonte'):
                repo.registrar_pendencia_fonte(item, url, concluida=True)
                pendentes_conhecidas.discard(url)
        indice_cp = primeira_busca_pendente if primeira_busca_pendente is not None else idx + 1
        checkpoint_captacao(repo,item,"erro" if primeira_busca_pendente is not None else "processando",indice_cp,total,consulta=consultas[indice_cp] if indice_cp<total else None,erro="Busca externa indisponível" if primeira_busca_pendente is not None else ("Fontes pendentes; repetir varredura" if falhas_fontes else None),
                            encontrados=encontrados_local,salvos=salvos_checkpoint+stats["leads_salvos"]-salvos_antes)
        print("RESULTADO DA CONSULTA:",json.dumps({"consulta":consulta,"segundos":round(time.monotonic()-inicio_consulta,1),"nomes_unicos_na_consulta":len(nomes_consulta),"novos_salvos":stats["leads_salvos"]-salvos_consulta,"ocorrencias_duplicadas":stats["duplicados"]-duplicados_consulta,"fontes_visitadas":stats["fontes_visitadas"]-fontes_consulta},ensure_ascii=False),flush=True)
        time.sleep(PAUSA_ENTRE_BUSCAS)
    novos = stats["leads_salvos"]-salvos_antes
    if primeira_busca_pendente is not None:
        repo.atualizar_instituicao(iid, status='erro')
        stats['instituicoes_erro'] += 1
        checkpoint_captacao(repo, item, 'erro', primeira_busca_pendente, total,
                            consulta=consultas[primeira_busca_pendente], erro='Busca externa indisponível',
                            encontrados=encontrados_local, salvos=salvos_checkpoint+novos)
        return False
    if fim<total:
        if not falhas_fontes:
            checkpoint_captacao(repo,item,"processando",fim,total,consulta=consultas[fim],erro="Janela encerrada; próxima consulta preservada",encontrados=encontrados_local,salvos=salvos_checkpoint+novos)
        if falhas_fontes:
            checkpoint_captacao(repo,item,"processando",fim,total,consulta=consultas[fim],erro="Janela com fontes pendentes; repetir ao finalizar",encontrados=encontrados_local,salvos=salvos_checkpoint+novos)
        stats["instituicoes_processadas"]+=1
        print(f"   JANELA LIMITADA: {fim}/{total}; faculdade ainda não concluída; novos: {novos}",flush=True)
        return True
    if hasattr(repo,"fontes_pendentes"):
        falhas_fontes=len(repo.fontes_pendentes(item))
    tentativas = int(item.get("tentativa_descoberta") or 0)
    repetir_zero = encontrados_local == 0 and tentativas < 1
    if falhas_fontes or repetir_zero:
        item["tentativa_descoberta"] = tentativas + 1
        repo.atualizar_instituicao(iid,status="erro",tentativa_descoberta=tentativas+1)
        # Pendência externa/segunda varredura preserva a fila, sem falha técnica do ciclo.
        motivo = (f"Fontes inacessíveis: {falhas_fontes}; repetir varredura"
                  if falhas_fontes else "Nenhum candidato encontrado; programada segunda varredura")
        checkpoint_captacao(repo,item,"erro",total if falhas_fontes and hasattr(repo,"fontes_pendentes") else 0,total,erro=motivo,encontrados=encontrados_local,salvos=salvos_checkpoint+novos)
        print(f"   🔁 REVISITAR: {motivo}",flush=True)
    else:
        repo.atualizar_instituicao(iid,status="concluido",tentativa_descoberta=tentativas)
        stats["instituicoes_concluidas"] += 1
        checkpoint_captacao(repo,item,"concluido",total,total,encontrados=encontrados_local,salvos=salvos_checkpoint+novos)
    stats["instituicoes_processadas"] += 1
    print(f"   RESUMO | pessoas: {encontrados_local} | novos: {novos} | fontes com falha: {falhas_fontes}",flush=True)
    return True


def retentar_fontes_pendentes(repo, item, cp, source_fn, limite, prazo=None):
    from fontes_academicas import url_permitida, acesso_reservado_maquina2
    urls=repo.fontes_pendentes(item)
    total=int(cp.get("total_pesquisas") or 0)
    encontrados=int(cp.get("leads_encontrados") or 0)
    salvos=int(cp.get("leads_salvos") or 0)
    antes=stats["leads_salvos"]
    print(f"REPROCESSAR SOMENTE FONTES PENDENTES: {item['instituicao']} | {len(urls)} fontes",flush=True)
    disponiveis = [url for url in urls if not hasattr(repo, 'fonte_pode_retentar') or repo.fonte_pode_retentar(item, url)]
    for url in disponiveis[:limite]:
        if prazo is not None and time.monotonic() >= prazo:
            print("LIMITE DO CICLO: fontes restantes mantidas para retomada",flush=True)
            break
        if not url_permitida(url) or acesso_reservado_maquina2(url): continue
        try:
            stats["fontes_visitadas"]+=1
            registros,links=source_fn(url,item["instituicao"],alias_instituicao(item))
        except Exception as exc:
            repo.registrar_pendencia_fonte(item,url,exc)
            stats["erros"]+=1
            print(f"FONTE AINDA PENDENTE: {url} | {type(exc).__name__}",flush=True)
            continue
        for registro in registros:
            encontrados+=1
            stats["leads_encontrados"]+=1
            salvar_lead(repo,registro["nome"],registro.get("instituicao",item["instituicao"]),None,None,
                        registro["evidencia"],registro.get("fonte_url",url),instagram=registro.get("instagram"),
                        ano_forcado=registro["ano"],periodo_forcado=registro["periodo"],
                        candidato_indicio=registro.get("candidato_indicio",False))
        # Links descobertos também precisam de leitura, sem reiniciar as consultas.
        for link in links:
            if url_permitida(link) and not acesso_reservado_maquina2(link):
                repo.registrar_pendencia_fonte(item,link,"Link descoberto na retomada; leitura pendente",somente_nova=True)
        repo.registrar_pendencia_fonte(item,url,concluida=True)
    restantes=repo.fontes_pendentes(item)
    # Pendências legadas sem URLs persistidas não comprovam cobertura completa.
    concluida=not restantes and bool(urls)
    status="concluido" if concluida else "erro"
    repo.atualizar_instituicao(item["id"],status=status)
    checkpoint_captacao(repo,item,status,total,total,
                        erro=None if concluida else f"Fontes inacessíveis: {len(restantes)}; retomada somente das fontes pendentes",
                        encontrados=encontrados,salvos=salvos+stats["leads_salvos"]-antes)
    stats["instituicoes_processadas"]+=1
    if concluida: stats["instituicoes_concluidas"]+=1
    print(f"FONTES RESTANTES: {len(restantes)} | consultas preservadas: {total}/{total}",flush=True)
    return True


def resumo():
    print("\n" + "=" * 72, flush=True)
    print(f"RESUMO MÁQUINA 1 {VERSAO.upper()}", flush=True)
    print("=" * 72, flush=True)
    for rotulo, chave in [
        ("IES oficiais carregadas", "ies_carregadas"),
        ("Instituições processadas", "instituicoes_processadas"),
        ("Instituições concluídas", "instituicoes_concluidas"),
        ("Instituições com erro", "instituicoes_erro"),
        ("Leads candidatos encontrados", "leads_encontrados"),
        ("Novos leads salvos", "leads_salvos"),
        ("Duplicados ignorados", "duplicados"),
        ("Reconsultas ao banco evitadas neste processo", "consultas_banco_evitadas"),
        ("Resultados rejeitados", "rejeitados"),
        ("Fontes visitadas", "fontes_visitadas"),
        ("Fontes sem nomes extraídos", "fontes_sem_nomes"),
        ("Erros", "erros"),
    ]:
        print(f"{rotulo}: {stats[chave]}", flush=True)
    print("=" * 72, flush=True)


def recuperar_pendencias_registradas(repo, fila):
    # URLs de falhas reais de 04/10, sem nomes de alunos nem credenciais.
    etapa=ETAPA_CAPTACAO + "_pendencias_logs_20261004"
    if repo.controle_get(etapa): return
    from pathlib import Path
    caminho=Path(__file__).parent / "fontes_publicas" / "pendencias_logs_20261004.json"
    dados=json.loads(caminho.read_text())
    for item in fila:
        for url,erro in dados.get(item["instituicao"],{}).items():
            repo.registrar_pendencia_fonte(item,url,erro,somente_nova=True)
    repo.controle_salvar(etapa,{"status":"concluido","instituicao":"Migração de fontes pendentes dos logs"})
    print("PENDÊNCIAS DOS LOGS PRESERVADAS: retentar as fontes sem reiniciar a faculdade",flush=True)


def selecionar_janela(fila, limite):
    """Primeira passagem por todas as faculdades; depois retoma a menos recente."""
    novas = [i for i in fila if not i.get('_ultimo_checkpoint')]
    retomadas = sorted([i for i in fila if i not in novas],
                       key=lambda i: (i.get('_ultimo_checkpoint') or '', normalizar(i.get('instituicao'))))
    return (novas + retomadas)[:max(0, limite)]



def registrar_falha_instituicao(repo, item, exc):
    """Registra falha isolada sem apagar o progresso já salvo da faculdade."""
    stats['erros'] += 1
    stats['instituicoes_erro'] += 1
    mensagem = f'{type(exc).__name__}: {str(exc)[:700]}'
    print(f"FACULDADE COM FALHA: {item.get('instituicao') or item.get('id')} | {mensagem}; seguindo para a próxima", flush=True)
    try:
        repo.atualizar_instituicao(item['id'], status='erro')
    except Exception as registro:
        print(f'AVISO: falha ao registrar estado da faculdade: {type(registro).__name__}', flush=True)
    try:
        etapa = etapa_captacao_item(item)
        anterior = repo.controle_get(etapa) or {}
        repo.controle_salvar(etapa, {
            'estado': item.get('estado'), 'cidade': item.get('cidade'),
            'instituicao': item.get('instituicao'), 'status': 'erro',
            'indice_pesquisa': anterior.get('indice_pesquisa', 0),
            'total_pesquisas': anterior.get('total_pesquisas', 0),
            'consulta_atual': anterior.get('consulta_atual'),
            'leads_encontrados': anterior.get('leads_encontrados', 0),
            'leads_salvos': anterior.get('leads_salvos', 0),
            'ultimo_erro': 'Falha isolada na faculdade: ' + mensagem,
        })
    except Exception as registro:
        print(f'AVISO: registro da falha indisponível: {type(registro).__name__}; progresso anterior preservado', flush=True)


def executar():
    print(f"🚀 MÁQUINA 1 - CAPTAÇÃO NACIONAL DE LEADS {VERSAO.upper()}", flush=True)
    print("📚 Fonte da fila: INEP / Censo da Educação Superior", flush=True)
    repo = SupabaseRepo.from_env()

    if not garantir_fila_oficial(repo):
        resumo()
        raise SystemExit(1)

    if not preparar_varredura_v58(repo):
        resumo()
        raise SystemExit(1)

    try:
        repo.isolar_erros_de_nome_comprovados()
    except Exception as exc:
        stats['erros'] += 1
        print(f'AVISO: revisão de nomes adiada: {type(exc).__name__}; captura continua', flush=True)
    try:
        print(f"📊 Total de cadastros no Supabase antes do ciclo: {repo.contar_leads()}", flush=True)
    except Exception as exc:
        print(f"⚠️ Contagem do banco indisponível: {type(exc).__name__}", flush=True)
    fila = repo.fila_nacional()
    try:
        recuperar_pendencias_registradas(repo,fila)
    except Exception as exc:
        stats['erros'] += 1
        print(f'AVISO: recuperação de pendências legadas adiada: {type(exc).__name__}; captura continua', flush=True)
    print(f"📚 Fila nacional: {len(fila)} faculdades pendentes (inclui EaD).", flush=True)
    prazo=time.monotonic()+360
    falhas_instituicoes = 0
    for item in selecionar_janela(fila, MAX_INSTITUICOES_POR_EXECUCAO):
        if time.monotonic() >= prazo:
            print("LIMITE DO CICLO: faculdades restantes preservadas na fila",flush=True)
            break
        try:
            if not processar_instituicao(repo, item, continuar_falhas=False, limite_consultas=6, prazo=prazo):
                falhas_instituicoes += 1
                print("FACULDADE PENDENTE: ciclo continua nas demais; checkpoint preservado", flush=True)
        except Exception as exc:
            falhas_instituicoes += 1
            registrar_falha_instituicao(repo, item, exc)
    if len(fila) > MAX_INSTITUICOES_POR_EXECUCAO:
        print("⏸️ A próxima execução retoma por faculdade.", flush=True)

    try:
        proximas=repo.fila_nacional()[:MAX_INSTITUICOES_POR_EXECUCAO]
        print("PRÓXIMAS FACULDADES NA FILA:",json.dumps([{ "instituicao":i["instituicao"],"status":i.get("_status_checkpoint"),"janela_encerrada":i.get("_janela_encerrada",False)} for i in proximas],ensure_ascii=False),flush=True)
    except Exception as exc:
        print(f"AVISO: não foi possível conferir a próxima janela: {type(exc).__name__}",flush=True)
    resumo()
    if falhas_instituicoes or stats["instituicoes_erro"] or stats["erros"]:
        print(f"⚠️ CICLO FINALIZADO COM PENDÊNCIAS: {falhas_instituicoes} faculdades com falha, {stats['erros']} ocorrências; checkpoints preservados; cobertura incompleta; próximo ciclo continua a fila.", flush=True)
    else:
        print(f"✅ CICLO {VERSAO.upper()} FINALIZADO", flush=True)


def preparar_lista():
    repo = SupabaseRepo.from_env()
    if not garantir_fila_oficial(repo): raise SystemExit(1)
    print("LISTA CARREGADA: instituicoes_nutricao",flush=True)
    print(f"Faculdades pendentes na pesquisa nacional: {len(repo.fila_nacional())}. Inclui EaD.",flush=True)


if __name__ == "__main__":
    import sys
    if "--preparar-fila" in sys.argv:
        preparar_lista()
    else:
        executar()

