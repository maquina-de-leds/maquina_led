import csv
import io
import json
import os
import re
import tempfile
import time
import unicodedata
import zipfile
from datetime import datetime, timezone
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

    def contar_pendentes_uf(self, uf):
        r=(self.client.table("instituicoes_nutricao").select("id",count="exact")
           .eq("origem",ORIGEM_IES).eq("estado",uf)
           .in_("status",["pendente","processando","erro"]).execute())
        return r.count or 0

    def atualizar_instituicao(self, iid, **dados):
        dados["ultima_verificacao"] = agora()
        self.client.table("instituicoes_nutricao").update(dados).eq("id", iid).execute()

    def lead_existe(self, nome, instituicao):
        r = (
            self.client.table("leds")
            .select("id")
            .eq("instituicao", instituicao)
            .ilike("nome", nome)
            .limit(1)
            .execute()
        )
        return bool(r.data)

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

    def instituicao_de_lead_por_alias(self, nome, alias):
        if not re.fullmatch(r"[A-Za-zÀ-ÿ0-9 .-]{2,30}",alias or ""): return None
        rows=(self.client.table("leds").select("instituicao").ilike("instituicao",alias)
              .ilike("nome",nome).limit(1).execute()).data
        return rows[0]["instituicao"] if rows else None

    def completar_instagram(self, nome, instituicao, instagram):
        if self.instagram_usado(instagram): return False
        rows = (self.client.table("leds").select("id,instagram")
                .eq("instituicao",instituicao).ilike("nome",nome).limit(1).execute()).data
        if rows and not rows[0].get("instagram"):
            (self.client.table("leds").update({"instagram":instagram,"proxima_acao":"primeiro_contato_instagram"})
             .eq("id",rows[0]["id"]).is_("instagram","null").execute())
            return True
        return False

    def inserir_lead(self, dados):
        self.client.table("leds").insert(dados).execute()


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
    with DDGS(timeout=20) as ddgs:
        return list(ddgs.text(
            consulta,
            region="br-pt",
            safesearch="moderate",
            max_results=max_results,
            backend=backend,
        ) or [])


def buscar_web(consulta, max_results=MAX_RESULTADOS, fetch_fn=ddgs_texto):
    """Busca robusta para o runner do GitHub.

    Testes reais mostraram que forçar Brave/Bing podia retornar zero para a
    mesma consulta que o metabusca backend='auto' encontrava corretamente.
    Também repetimos uma vez quando a resposta vem vazia, porque o índice pode
    oscilar entre chamadas consecutivas no mesmo runner.
    """
    ultimo_erro = None

    for tentativa in range(1, 3):
        try:
            try:
                resultados = fetch_fn(consulta, "auto", max_results)
            except TypeError:
                resultados = fetch_fn(consulta, max_results)

            resultados = list(resultados or [])
            if resultados:
                return resultados

            if tentativa < 2:
                time.sleep(4.0)
                continue

            if ultimo_erro is not None:
                return None
            return []

        except Exception as exc:
            ultimo_erro = exc
            msg = str(exc)

            if tentativa < 2:
                time.sleep(4.0)
                continue

            if "No results found" in msg:
                try:
                    saude = fetch_fn("Brasil", "auto", 1)
                    if list(saude or []):
                        return []
                except Exception:
                    pass

    print(f"      ⚠️ Busca externa indisponível: {ultimo_erro}", flush=True)
    return None


def alias_instituicao(item):
    fonte = str(item.get("fonte_validacao") or "")
    m = re.search(r"(?:^|\|)\s*SIGLA=([^|]+)", fonte, flags=re.I)
    if not m:
        return None
    alias = limpar_espacos(m.group(1))
    return alias if 2 <= len(alias) <= 30 else None


def consultas_leads(instituicao, alias=None, cidade=None, uf=None):
    # Mesma estratégia para toda IES/município; o nome e a sigla são alternativos.
    termos = list(dict.fromkeys(limpar_espacos(t) for t in (instituicao, alias) if t))
    sinais = ('"formandos"', '"colação de grau"', '"TCC"', '"concluintes"',
              '"turma"', '"recém-formados"', '"recém-formadas"',
              '"último semestre"', '"último período"', '"estágio final"',
              '"alunos" "conclusão"', '"mostra" "autores"')
    consultas = [f'"{termo}" Nutrição {sinal} {ano} -site:linkedin.com'
                 for ano in (2025, 2026) for sinal in sinais for termo in termos]
    if cidade and normalizar(cidade) != "nao identificado":
        consultas += [f'"{instituicao}" "{cidade}" {uf or ""} Nutrição "turma" {ano} -site:linkedin.com'
                      for ano in (2025,2026)]
    return consultas


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


def salvar_lead(repo, nome, instituicao, cidade, uf, texto, url, instagram=None, linkedin=None, ano_forcado=None, periodo_forcado=None, instituicao_alias=None):
    nome = formatar_nome_pessoa(nome)
    instituicao_existente = instituicao if repo.lead_existe(nome,instituicao) else None
    if not instituicao_existente and instituicao_alias and hasattr(repo,"instituicao_de_lead_por_alias"):
        instituicao_existente = repo.instituicao_de_lead_por_alias(nome,instituicao_alias)
    if instituicao_existente:
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
    if ano not in {2025,2026} or not periodo:
        raise ValueError("Lead precisa de ano/período extraídos da fonte acadêmica")
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
        "qualificado": True,
        "data_primeiro_contato": None,
        "data_ultimo_contato": None,
        "proxima_acao": "primeiro_contato_instagram" if instagram else "buscar_instagram",
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
        "fonte_validacao": "fonte_publica_validada_v58",
    }
    repo.inserir_lead(dados)
    stats["leads_salvos"] += 1
    print(f"      ✅ SALVO: {nome}" + (f" | {instagram}" if instagram else " | Instagram pendente"), flush=True)
    return True


# ============================================================
# CAPTACAO / CHECKPOINT
# ============================================================

def etapa_captacao_item(item):
    return f"{ETAPA_CAPTACAO}_{item['id']}"


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


def processar_instituicao(repo, item, search_fn=buscar_web, source_fn=None):
    from fontes_academicas import carregar_fonte, url_permitida
    source_fn = source_fn or carregar_fonte
    iid, instituicao, uf = item["id"], item["instituicao"], item["estado"]
    cidade = item.get("cidade") or "Não identificado"
    alias = alias_instituicao(item)
    consultas = consultas_leads(instituicao, alias, cidade, uf)
    total = len(consultas)
    cp = repo.controle_get(etapa_captacao_item(item))
    inicio = 0
    if cp and cp.get("instituicao") == instituicao and cp.get("estado") == uf and cp.get("status") in {"processando", "erro"}:
        # Nova varredura repete tudo; falha de busca retoma apenas a consulta interrompida.
        if cp.get("ultimo_erro") == "Busca externa indisponível":
            inicio = min(max(int(cp.get("indice_pesquisa") or 0), 0), total-1)
    print(f"\n🏫 {uf} | {cidade} | {instituicao} | WEB / TURMAS", flush=True)
    repo.atualizar_instituicao(iid, status="processando")
    salvos_antes = stats["leads_salvos"]
    encontrados_local = 0
    fontes_vistas = set()
    falhas_fontes = 0
    for idx in range(inicio, total):
        consulta = consultas[idx]
        print(f"   🔎 [{idx+1}/{total}] {consulta}", flush=True)
        checkpoint_captacao(repo,item,"processando",idx,total,consulta=consulta,
                            encontrados=encontrados_local,salvos=stats["leads_salvos"]-salvos_antes)
        resultados = search_fn(consulta, MAX_RESULTADOS)
        if resultados is None:
            repo.atualizar_instituicao(iid,status="erro")
            stats["instituicoes_erro"] += 1
            checkpoint_captacao(repo,item,"erro",idx,total,consulta=consulta,erro="Busca externa indisponível",
                                encontrados=encontrados_local,salvos=stats["leads_salvos"]-salvos_antes)
            return False
        fila = [(str(r.get("href") or r.get("url") or ""),0) for r in resultados]
        for url, depth in fila:
            if url in fontes_vistas or not url_permitida(url): continue
            fontes_vistas.add(url)
            try:
                stats["fontes_visitadas"] += 1
                registros, links = source_fn(url,instituicao,alias)
                if not registros: stats["fontes_sem_nomes"] += 1
            except Exception as exc:
                falhas_fontes += 1
                stats["erros"] += 1
                print(f"      ⚠️ FONTE PENDENTE: {url} | {str(exc)[:250]}",flush=True)
                continue
            print(f"      📄 FONTE: {url} | pessoas: {len(registros)}",flush=True)
            if depth == 0:
                fila.extend((link,1) for link in links if url_permitida(link))
            for registro in registros:
                encontrados_local += 1
                stats["leads_encontrados"] += 1
                contexto = normalizar(registro.get("contexto_academico", ""))
                cidade_confirmada = bool(cidade and re.search(r'(?<!\w)'+re.escape(normalizar(cidade))+r'(?!\w)',contexto))
                salvar_lead(repo,registro["nome"],instituicao,cidade if cidade_confirmada else None,
                            uf if cidade_confirmada else None,registro["evidencia"],url,
                            instagram=registro.get("instagram"),
                            ano_forcado=registro["ano"],periodo_forcado=registro["periodo"],instituicao_alias=alias)
        checkpoint_captacao(repo,item,"processando",idx+1,total,
                            encontrados=encontrados_local,salvos=stats["leads_salvos"]-salvos_antes)
        time.sleep(PAUSA_ENTRE_BUSCAS)
    novos = stats["leads_salvos"]-salvos_antes
    tentativas = int(item.get("tentativa_descoberta") or 0)
    repetir_zero = encontrados_local == 0 and tentativas < 1
    if falhas_fontes or repetir_zero:
        repo.atualizar_instituicao(iid,status="erro",tentativa_descoberta=tentativas+1)
        stats["instituicoes_erro"] += 1
        motivo = (f"Fontes inacessíveis: {falhas_fontes}; repetir varredura"
                  if falhas_fontes else "Nenhum candidato encontrado; programada segunda varredura")
        checkpoint_captacao(repo,item,"erro",0,total,erro=motivo,encontrados=encontrados_local,salvos=novos)
        print(f"   🔁 REVISITAR: {motivo}",flush=True)
    else:
        repo.atualizar_instituicao(iid,status="concluido",tentativa_descoberta=tentativas)
        stats["instituicoes_concluidas"] += 1
        checkpoint_captacao(repo,item,"concluido",total,total,encontrados=encontrados_local,salvos=novos)
    stats["instituicoes_processadas"] += 1
    print(f"   RESUMO | pessoas: {encontrados_local} | novos: {novos} | fontes com falha: {falhas_fontes}",flush=True)
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
        ("Resultados rejeitados", "rejeitados"),
        ("Fontes visitadas", "fontes_visitadas"),
        ("Fontes sem nomes extraídos", "fontes_sem_nomes"),
        ("Erros", "erros"),
    ]:
        print(f"{rotulo}: {stats[chave]}", flush=True)
    print("=" * 72, flush=True)


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

    processadas = 0
    for uf, estado_nome in ESTADOS:
        print("\n" + "#" * 72, flush=True)
        print(f"📍 ESTADO: {estado_nome} ({uf})", flush=True)
        print("#" * 72, flush=True)
        try:
            fila = repo.fila_estado(uf)
        except Exception as exc:
            stats["erros"] += 1
            print(f"❌ Erro lendo fila de {uf}: {exc}", flush=True)
            continue

        if not fila:
            print(f"🏁 {uf}: nenhuma instituição V5 pendente.", flush=True)
            continue

        print(f"📚 {uf}: {len(fila)} instituição(ões) pendente(s).", flush=True)
        for item in fila:
            if processadas >= MAX_INSTITUICOES_POR_EXECUCAO:
                print("\n⏸️ Limite seguro desta execução atingido.", flush=True)
                print("➡️ A próxima execução retoma a fila V5.", flush=True)
                resumo()
                if stats["erros"]: raise SystemExit(2)
                return
            ok = processar_instituicao(repo, item)
            processadas += 1
            if not ok:
                print("⏸️ Busca externa instável. Encerrando este ciclo para evitar excesso de requisições.", flush=True)
                resumo()
                raise SystemExit(2)

    resumo()
    if stats["erros"]: raise SystemExit(2)
    print(f"✅ CICLO {VERSAO.upper()} FINALIZADO", flush=True)


def preparar_lista():
    repo = SupabaseRepo.from_env()
    if not garantir_fila_oficial(repo): raise SystemExit(1)
    print("LISTA CARREGADA: instituicoes_nutricao",flush=True)
    print("Estados/DF, município da oferta, faculdade, curso, fonte e status.",flush=True)
    for uf,nome in ESTADOS:
        print(f"{uf} | {nome} | pendentes: {repo.contar_pendentes_uf(uf)}",flush=True)


if __name__ == "__main__":
    import sys
    if "--preparar-fila" in sys.argv:
        preparar_lista()
    else:
        executar()
