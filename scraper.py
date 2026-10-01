import csv
import io
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

VERSAO = "v5"
ETAPA_CARGA_IES = "carga_inep_nutricao_v5"
ETAPA_CAPTACAO = "captacao_nacional_nutricao_v5"
ORIGEM_IES = "inep_censo_superior_v5"
MAX_RESULTADOS = 12
MAX_INSTITUICOES_POR_EXECUCAO = 1
PAUSA_ENTRE_BUSCAS = 2.0

INEP_FONTES = [
    (2024, "https://download.inep.gov.br/microdados/microdados_censo_da_educacao_superior_2024.zip"),
]

MACKENZIE_TCC_URL = (
    "https://www.mackenzie.br/universidade/unidades-academicas/"
    "ccbs/tcc-e-pesquisa/mostra-de-tcc"
)

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
}


def agora():
    return datetime.now(timezone.utc).isoformat()


def limpar_espacos(texto):
    return re.sub(r"\s+", " ", str(texto or "")).strip()


def normalizar(texto):
    texto = limpar_espacos(texto).lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
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


def extrair_instituicoes_inep(caminho_zip, ano):
    """Retorna uma linha por IES/UF que oferta graduação em Nutrição no Censo Superior."""
    ufs_validas = {x[0] for x in ESTADOS}
    with zipfile.ZipFile(caminho_zip) as zf:
        arq_cursos = localizar_membro(zf, f"MICRODADOS_CADASTRO_CURSOS_{ano}")
        arq_ies = localizar_membro(zf, f"MICRODADOS_ED_SUP_IES_{ano}")
        if not arq_cursos or not arq_ies:
            raise RuntimeError(
                f"Arquivos esperados do Censo {ano} nao encontrados no ZIP. "
                f"Cursos={bool(arq_cursos)} IES={bool(arq_ies)}"
            )

        ies_por_codigo = {}
        texto_ies, leitor_ies = leitor_csv_zip(zf, arq_ies)
        try:
            for row in leitor_ies:
                co_ies = valor(row, "CO_IES")
                if not co_ies:
                    continue
                ies_por_codigo[co_ies] = {
                    "instituicao": valor(row, "NO_IES"),
                    "sigla": valor(row, "SG_IES"),
                    "estado": valor(row, "SG_UF_IES", "SG_UF"),
                    "cidade": valor(row, "NO_MUNICIPIO_IES", "NO_MUNICIPIO"),
                }
        finally:
            texto_ies.close()

        # Uma IES pode aparecer muitas vezes (campi/polos/linhas do mesmo curso).
        # Para a máquina de leads basta uma fila por IES+UF; pesquisar a mesma IES
        # dezenas de vezes por polo só gera carga e duplicidade.
        unicos = {}
        texto_cursos, leitor_cursos = leitor_csv_zip(zf, arq_cursos)
        try:
            for row in leitor_cursos:
                cine = valor(row, "NO_CINE_ROTULO")
                nome_curso = valor(row, "NO_CURSO")
                # O rótulo CINE é a classificação canônica do Censo. Só usamos
                # NO_CURSO como fallback para arquivos que eventualmente não o tragam.
                if cine:
                    if normalizar(cine) != "nutricao":
                        continue
                else:
                    nome_norm = normalizar(nome_curso)
                    if not (nome_norm == "nutricao" or nome_norm.startswith("nutricao ")):
                        continue

                co_ies = valor(row, "CO_IES")
                ies = ies_por_codigo.get(co_ies, {})
                instituicao = ies.get("instituicao", "")
                if not instituicao:
                    continue

                uf = (valor(row, "SG_UF", "SG_UF_CURSO") or ies.get("estado", "")).strip().upper()
                if uf not in ufs_validas:
                    continue

                cidade_curso = valor(row, "NO_MUNICIPIO", "NO_MUNICIPIO_CURSO")
                cidade_sede = ies.get("cidade", "")
                cidade = limpar_espacos(cidade_curso or cidade_sede) or "Não identificado"
                instituicao = limpar_espacos(instituicao)
                modalidade = valor(row, "TP_MODALIDADE_ENSINO")

                # Presencial com município identificado é a melhor representação.
                # Depois vem qualquer linha com município, e por último a sede da IES.
                prioridade = (2 if modalidade == "1" else 0) + (1 if cidade_curso else 0)
                chave = (uf, normalizar(instituicao))
                atual = unicos.get(chave)
                if atual is None or prioridade > atual[0]:
                    unicos[chave] = (
                        prioridade,
                        {
                            "estado": uf,
                            "cidade": cidade,
                            "instituicao": instituicao,
                            "curso": "Nutrição",
                            "origem": ORIGEM_IES,
                            "fonte_url": INEP_FONTES[0][1],
                            "status": "pendente",
                            "fonte_validacao": f"INEP Censo da Educação Superior {ano}",
                            "validada": True,
                            "tentativa_descoberta": 0,
                        },
                    )
        finally:
            texto_cursos.close()

    registros = [v[1] for v in unicos.values()]
    return sorted(registros, key=lambda x: (x["estado"], normalizar(x["instituicao"])))


def baixar_microdados_inep():
    import requests

    erros = []
    for ano, url in INEP_FONTES:
        destino = os.path.join(tempfile.gettempdir(), f"microdados_censo_superior_{ano}.zip")
        try:
            print(f"📥 Baixando base oficial do INEP {ano}...", flush=True)
            with requests.get(
                url,
                stream=True,
                timeout=(30, 300),
                headers={"User-Agent": "Mozilla/5.0 MaquinaLeads/1.0"},
            ) as r:
                r.raise_for_status()
                total = 0
                proximo_aviso = 25 * 1024 * 1024
                with open(destino, "wb") as f:
                    for bloco in r.iter_content(chunk_size=1024 * 1024):
                        if not bloco:
                            continue
                        f.write(bloco)
                        total += len(bloco)
                        if total >= proximo_aviso:
                            print(f"   ... {total // (1024 * 1024)} MB", flush=True)
                            proximo_aviso += 25 * 1024 * 1024
            if not zipfile.is_zipfile(destino):
                raise RuntimeError("arquivo baixado nao e um ZIP valido")
            return ano, destino
        except Exception as exc:
            erros.append(f"{ano}: {exc}")
            print(f"⚠️ Falha na fonte INEP {ano}: {exc}", flush=True)
            try:
                if os.path.exists(destino):
                    os.remove(destino)
            except OSError:
                pass

    raise RuntimeError("Nenhuma fonte oficial do INEP ficou acessivel: " + " | ".join(erros))


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

    def inserir_lead(self, dados):
        self.client.table("leds").insert(dados).execute()


# ============================================================
# CARGA DETERMINISTICA DA FILA DE INSTITUICOES
# ============================================================

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
        ano, caminho = baixar_microdados_inep()
        registros = extrair_instituicoes_inep(caminho, ano)
        if not registros:
            raise RuntimeError("o filtro oficial nao encontrou nenhum curso de Nutricao")
        repo.limpar_residuos_v4()
        repo.upsert_ies(registros)
        total = repo.contar_ies_v5()
        if total < 20:
            raise RuntimeError(f"carga suspeita: apenas {total} registros de Nutricao")
        repo.controle_salvar(ETAPA_CARGA_IES, {
            "estado": None,
            "cidade": None,
            "instituicao": None,
            "status": "concluido",
            "ultimo_erro": None,
            "leads_encontrados": len(registros),
            "leads_salvos": total,
            "fonte_atual": f"INEP {ano}",
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


# ============================================================
# BUSCA WEB CONTROLADA
# ============================================================

def ddgs_texto(consulta, backend, max_results):
    from ddgs import DDGS
    with DDGS(timeout=15) as ddgs:
        return list(ddgs.text(
            consulta,
            region="br-pt",
            safesearch="moderate",
            max_results=max_results,
            backend=backend,
        ) or [])


def buscar_web(consulta, max_results=MAX_RESULTADOS, fetch_fn=ddgs_texto):
    """Busca com diagnóstico de 'sem resultado' versus indisponibilidade do motor.

    DDGS pode lançar 'No results found' tanto para uma consulta realmente vazia
    quanto quando um backend deixa de responder. Se todos os backends disserem
    isso, fazemos uma única consulta de saúde antes de concluir que o resultado é vazio.
    """
    backends = ["brave", "bing"]
    sem_resultado = 0
    erros_reais = []

    for backend in backends:
        try:
            resultados = fetch_fn(consulta, backend, max_results)
            if resultados:
                return resultados
            # Retorno normal vazio do backend: resultado vazio confiável.
            return []
        except Exception as exc:
            msg = str(exc)
            if "No results found" in msg:
                sem_resultado += 1
            else:
                erros_reais.append(f"{backend}: {msg}")
            time.sleep(0.5)

    if sem_resultado:
        # Diagnóstico barato: se uma busca extremamente ampla funciona, tratamos
        # 'No results found' da consulta específica como vazio real. Se nem a
        # busca de saúde funciona, não concluímos a instituição por engano.
        for backend in backends:
            try:
                saude = fetch_fn("Brasil", backend, 1)
                if saude:
                    return []
            except Exception as exc:
                erros_reais.append(f"health/{backend}: {exc}")

    detalhe = " | ".join(erros_reais[-4:]) or "backends sem resposta verificável"
    print(f"      ⚠️ Busca externa indisponível: {detalhe}", flush=True)
    return None


def consultas_leads(instituicao):
    return [
        f'"{instituicao}" "Nutrição" "TCC" "2026"',
        f'"{instituicao}" "Nutrição" "TCC" "2025"',
        f'"{instituicao}" "Nutrição" "formanda" "2026"',
        f'"{instituicao}" "Nutrição" "formatura" "2025"',
        f'site:linkedin.com/in "{instituicao}" "Nutrição" "2026"',
        f'site:instagram.com "{instituicao}" "Nutrição" "2026"',
    ]


SINAIS_FASE_FINAL = [
    "tcc", "trabalho de conclusao", "formanda", "formando", "formandas", "formandos",
    "concluinte", "concluintes", "colacao de grau", "formatura", "recem-formad",
    "7º periodo", "7o periodo", "7 periodo", "8º periodo", "8o periodo", "8 periodo",
    "7º semestre", "7o semestre", "7 semestre", "8º semestre", "8o semestre", "8 semestre",
    "7/8", "8/8", "estagio obrigatorio", "estagio supervisionado", "estagio final",
    "ultimo semestre", "ultimo periodo",
]

BLOQUEIOS_PESSOA = [
    "universidade", "faculdade", "centro universitario", "instituto", "vestibular", "curso",
    "campus", "evento", "congresso", "google docs", "pos ead", "pos-graduacao", "programa",
    "secretaria", "reitoria", "inscricoes", "edital", "processo seletivo", "portal do aluno",
    "noticia", "noticias", "projeto pedagogico", "matriz curricular", "grade curricular",
    "revista", "anais", "mostra de tcc", "trabalho de conclusao",
]


def identificar_ano(texto):
    n = normalizar(texto)
    if "2026" in n:
        return 2026
    if "2025" in n:
        return 2025
    return None


def identificar_periodo(texto):
    n = normalizar(texto)
    grupos = [
        ("8º período/semestre", ["8º periodo", "8o periodo", "8 periodo", "8º semestre", "8o semestre", "8 semestre", "8/8"]),
        ("7º período/semestre", ["7º periodo", "7o periodo", "7 periodo", "7º semestre", "7o semestre", "7 semestre", "7/8"]),
        ("TCC", ["tcc", "trabalho de conclusao"]),
        ("estágio final/obrigatório", ["estagio obrigatorio", "estagio supervisionado", "estagio final"]),
        ("formando", ["formanda", "formando", "concluinte", "colacao de grau", "formatura"]),
        ("recém-formado", ["recem-formada", "recem-formado"]),
    ]
    for rotulo, sinais in grupos:
        if any(s in n for s in sinais):
            return rotulo
    return None


def lead_qualificado(texto):
    n = normalizar(texto)
    if "nutricao" not in n and "nutricionista" not in n:
        return False
    ano = identificar_ano(texto)
    if ano not in (2025, 2026):
        return False
    return any(s in n for s in SINAIS_FASE_FINAL)


def nome_parece_pessoa(nome):
    nome = limpar_espacos(nome).strip(" -–—|:,.;")
    if len(nome) < 6 or len(nome) > 90 or re.search(r"\d", nome):
        return False
    n = normalizar(nome)
    if any(b in n for b in BLOQUEIOS_PESSOA):
        return False
    partes = nome.split()
    if len(partes) < 2 or len(partes) > 7:
        return False
    conectores = {"de", "da", "do", "das", "dos", "e"}
    principais = [p for p in partes if normalizar(p) not in conectores]
    if len(principais) < 2:
        return False
    if normalizar(partes[0]) in {"estudante", "aluno", "aluna", "nutricao", "nutricionista", "tcc", "mostra"}:
        return False
    return True


def extrair_nome_resultado(resultado):
    """Extrai nome somente de perfis sociais individualizados.

    Títulos genéricos de páginas/TCC não são tratados como pessoas. Isso evita
    repetir o problema das versões antigas, que confundiam título de documento
    com nome de aluno. Páginas oficiais em lista usam adaptadores específicos.
    """
    titulo = limpar_espacos(resultado.get("title", ""))
    url = str(resultado.get("href") or resultado.get("url") or "")
    host = urlparse(url).netloc.lower()

    if "linkedin.com" in host and "/in/" in url.lower():
        titulo = re.sub(r"(?i)\s*[|\-–—•]\s*LinkedIn.*$", "", titulo)
        candidato = re.split(r"\s+[\-–—|•]\s+", titulo, maxsplit=1)[0]
    elif "instagram.com" in host:
        caminho = urlparse(url).path.strip("/").split("/")[0].lower()
        if not caminho or caminho in {"p", "reel", "reels", "stories", "explore", "accounts", "direct", "tv"}:
            return None
        titulo = re.sub(r"\s*\(@[A-Za-z0-9._]+\).*$", "", titulo)
        titulo = re.sub(r"(?i)\s*[|\-–—•]\s*Instagram.*$", "", titulo)
        candidato = re.split(r"\s+[\-–—|•]\s+", titulo, maxsplit=1)[0]
    else:
        return None

    candidato = limpar_espacos(candidato).strip(" -–—|•:,.;")
    return candidato if nome_parece_pessoa(candidato) else None


def extrair_instagram(resultado):
    url = str(resultado.get("href") or resultado.get("url") or "")
    m = re.search(r"instagram\.com/([A-Za-z0-9._]+)", url, flags=re.I)
    if not m:
        return None
    usuario = m.group(1).lower()
    if usuario in {"p", "reel", "reels", "stories", "explore", "accounts", "direct", "tv"}:
        return None
    return "@" + usuario


def relacionado_a_instituicao(texto, instituicao, cidade=""):
    ntexto = normalizar(texto)
    inst = normalizar(instituicao)
    if inst and inst in ntexto:
        return True
    ignorar = {"universidade", "faculdade", "centro", "universitario", "instituto", "federal", "estadual", "de", "da", "do", "das", "dos", "e"}
    tokens = [p for p in inst.split() if len(p) >= 4 and p not in ignorar]
    matches = sum(1 for p in tokens if p in ntexto)
    if matches >= min(2, max(1, len(tokens))):
        return True
    ncidade = normalizar(cidade)
    return bool(ncidade and ncidade != "nao identificado" and ncidade in ntexto and matches >= 1)


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


def salvar_lead(repo, nome, instituicao, cidade, uf, texto, url, instagram=None, linkedin=None, ano_forcado=None, periodo_forcado=None):
    nome = formatar_nome_pessoa(nome)
    if repo.lead_existe(nome, instituicao):
        stats["duplicados"] += 1
        print(f"      ♻️ DUPLICADO: {nome}", flush=True)
        return False
    if instagram and repo.instagram_usado(instagram):
        instagram = None

    ano = ano_forcado or identificar_ano(texto)
    periodo = periodo_forcado or identificar_periodo(texto)
    dados = {
        "nome": nome,
        "instagram": instagram,
        "linkedin": linkedin,
        "whatsapp": None,
        "nicho": "nutricionista",
        "origem": "captacao_nacional_fila_v5",
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
        "fonte_validacao": "fonte_publica_validada_v5",
    }
    repo.inserir_lead(dados)
    stats["leads_salvos"] += 1
    print(f"      ✅ SALVO: {nome}" + (f" | {instagram}" if instagram else " | Instagram pendente"), flush=True)
    return True


# ============================================================
# ADAPTADOR OFICIAL MACKENZIE (FONTE ESTRUTURADA)
# ============================================================

def extrair_nomes_mackenzie_html(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    linhas = [limpar_espacos(x) for x in soup.stripped_strings]
    dentro = False
    nomes = []
    for linha in linhas:
        n = normalizar(linha)
        if "nutricao 2026.1" in n:
            dentro = True
            continue
        if dentro and ("cursos de graduacao" in n or "cursos de pós-graduação" in n or "cursos de pos-graduacao" in n):
            break
        if not dentro:
            continue
        m = re.match(r"^\d{1,2}\s*-\s*(.+)$", linha)
        if not m:
            continue
        bloco = m.group(1)
        for parte in re.split(r"\s+e\s+", bloco, flags=re.I):
            parte = limpar_espacos(parte)
            if nome_parece_pessoa(parte):
                nomes.append(parte)
    # dedupe preservando ordem
    out = []
    vistos = set()
    for nome in nomes:
        k = normalizar(nome)
        if k not in vistos:
            vistos.add(k)
            out.append(nome)
    return out


def processar_adaptadores_oficiais(repo, item):
    inst_n = normalizar(item.get("instituicao"))
    if not (item.get("estado") == "SP" and inst_n == "universidade presbiteriana mackenzie"):
        return 0
    import requests
    try:
        r = requests.get(MACKENZIE_TCC_URL, timeout=(20, 60), headers={"User-Agent": "Mozilla/5.0 MaquinaLeads/1.0"})
        r.raise_for_status()
        nomes = extrair_nomes_mackenzie_html(r.text)
        salvos = 0
        for nome in nomes:
            stats["leads_encontrados"] += 1
            if salvar_lead(
                repo, nome, item["instituicao"], item.get("cidade") or "São Paulo", item["estado"],
                "Mostra de TCC Nutrição 2026.1 - Universidade Presbiteriana Mackenzie",
                MACKENZIE_TCC_URL, ano_forcado=2026, periodo_forcado="TCC"
            ):
                salvos += 1
        if nomes:
            print(f"   📄 Fonte oficial Mackenzie: {len(nomes)} nome(s) lido(s), {salvos} novo(s).", flush=True)
        return salvos
    except Exception as exc:
        print(f"   ⚠️ Adaptador Mackenzie indisponível: {exc}", flush=True)
        return 0


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


def processar_instituicao(repo, item, search_fn=buscar_web, adapter_fn=processar_adaptadores_oficiais):
    iid = item["id"]
    instituicao = item["instituicao"]
    cidade = item.get("cidade") or "Não identificado"
    uf = item["estado"]
    consultas = consultas_leads(instituicao)
    total = len(consultas)

    cp = repo.controle_get(etapa_captacao_item(item))
    inicio = 0
    if cp and cp.get("instituicao") == instituicao and cp.get("estado") == uf and cp.get("status") in {"processando", "erro"}:
        try:
            inicio = max(0, min(int(cp.get("indice_pesquisa") or 0), total - 1))
        except Exception:
            inicio = 0

    print("\n" + "=" * 72, flush=True)
    print(f"🏫 {uf} | {cidade} | {instituicao}", flush=True)
    print("=" * 72, flush=True)

    repo.atualizar_instituicao(iid, status="processando")
    checkpoint_captacao(repo, item, "processando", inicio, total, consulta=consultas[inicio])

    salvos_antes = stats["leads_salvos"]
    encontrados_local = 0

    # Adaptadores oficiais sao idempotentes por causa da deduplicacao.
    adapter_fn(repo, item)

    for idx in range(inicio, total):
        consulta = consultas[idx]
        print(f"   🔎 [{idx + 1}/{total}] {consulta}", flush=True)
        checkpoint_captacao(repo, item, "processando", idx, total, consulta=consulta, encontrados=encontrados_local, salvos=stats["leads_salvos"] - salvos_antes)
        resultados = search_fn(consulta, MAX_RESULTADOS)
        if resultados is None:
            repo.atualizar_instituicao(iid, status="erro")
            stats["instituicoes_erro"] += 1
            checkpoint_captacao(repo, item, "erro", idx, total, consulta=consulta, erro="Busca externa indisponível", encontrados=encontrados_local, salvos=stats["leads_salvos"] - salvos_antes)
            print("   ❌ Falha real de conexão. A próxima execução retoma exatamente desta consulta.", flush=True)
            return False

        for resultado in resultados:
            titulo = limpar_espacos(resultado.get("title", ""))
            corpo = limpar_espacos(resultado.get("body", ""))
            url = str(resultado.get("href") or resultado.get("url") or "")
            texto_real = limpar_espacos(f"{titulo} {corpo} {url}")
            if not lead_qualificado(texto_real):
                continue
            if not relacionado_a_instituicao(texto_real, instituicao, cidade):
                continue
            nome = extrair_nome_resultado(resultado)
            if not nome:
                stats["rejeitados"] += 1
                continue
            encontrados_local += 1
            stats["leads_encontrados"] += 1
            linkedin = url if "linkedin.com/in/" in url.lower() else None
            salvar_lead(
                repo, nome, instituicao, cidade, uf, texto_real, url,
                extrair_instagram(resultado), linkedin=linkedin
            )

        checkpoint_captacao(repo, item, "processando", idx + 1, total, consulta=None, encontrados=encontrados_local, salvos=stats["leads_salvos"] - salvos_antes)
        time.sleep(PAUSA_ENTRE_BUSCAS)

    repo.atualizar_instituicao(iid, status="concluido")
    stats["instituicoes_processadas"] += 1
    stats["instituicoes_concluidas"] += 1
    novos = stats["leads_salvos"] - salvos_antes
    checkpoint_captacao(repo, item, "concluido", total, total, encontrados=encontrados_local, salvos=novos)
    print(f"   ✅ CONCLUÍDA | candidatos web: {encontrados_local} | novos totais: {novos}", flush=True)
    return True


def resumo():
    print("\n" + "=" * 72, flush=True)
    print("RESUMO MÁQUINA 1 V5", flush=True)
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
        ("Erros", "erros"),
    ]:
        print(f"{rotulo}: {stats[chave]}", flush=True)
    print("=" * 72, flush=True)


def executar():
    print("🚀 MÁQUINA 1 - CAPTAÇÃO NACIONAL DE LEADS V5", flush=True)
    print("📚 Fonte da fila: INEP / Censo da Educação Superior", flush=True)
    repo = SupabaseRepo.from_env()

    if not garantir_fila_oficial(repo):
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
                return
            ok = processar_instituicao(repo, item)
            processadas += 1
            if not ok:
                print("⏸️ Busca externa instável. Encerrando este ciclo para evitar excesso de requisições.", flush=True)
                resumo()
                return

    resumo()
    print("✅ CICLO V5 FINALIZADO", flush=True)


if __name__ == "__main__":
    executar()
