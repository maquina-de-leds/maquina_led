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

VERSAO = "v5.7"
ETAPA_CARGA_IES = "carga_inep_nutricao_v54"
ETAPA_CAPTACAO = "captacao_nacional_nutricao_v57"
ETAPA_MIGRACAO_BUSCA = "migracao_busca_nutricao_v57"
ORIGEM_IES = "inep_censo_superior_v54"
MAX_RESULTADOS = 12
MAX_INSTITUICOES_POR_EXECUCAO = 4
PAUSA_ENTRE_BUSCAS = 3.0

INEP_FONTES = [
    (2024, "https://download.inep.gov.br/microdados/microdados_censo_da_educacao_superior_2024.zip"),
]

# Espelho processado e versionado a partir dos microdados oficiais do INEP 2024.
# É usado porque o servidor de download do INEP pode resetar conexões longas
# no GitHub Actions. A carga é validada antes de tocar a fila.
INEP_MIRROR_URL = (
    "https://raw.githubusercontent.com/esidiao/"
    "observatorio-educacao-superior/main/data/instituicoes.json"
)

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
    "revisao_necessaria": 0,
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


def carregar_instituicoes_mirror_inep():
    """Carrega fila estruturada de IES de Nutrição a partir de espelho reproduzível.

    O JSON é gerado publicamente a partir dos microdados oficiais do Censo da
    Educação Superior 2024. Validamos ano, volume e presença de uma referência
    conhecida antes de aceitar a carga.
    """
    import requests

    print("📥 Carregando espelho estruturado do Censo INEP 2024...", flush=True)
    ultimo = None

    for tentativa in range(1, 5):
        try:
            r = requests.get(
                INEP_MIRROR_URL,
                timeout=(20, 90),
                headers={"User-Agent": "Mozilla/5.0 MaquinaLeads/1.0"},
            )
            r.raise_for_status()
            data = r.json()

            if str(data.get("ano_censo")) != "2024":
                raise RuntimeError(f"ano inesperado no espelho: {data.get('ano_censo')}")

            ies = data.get("instituicoes") or {}
            if len(ies) < 2000:
                raise RuntimeError(f"espelho incompleto: apenas {len(ies)} IES totais")

            registros = []
            vistos = set()
            nutricao_ies = 0

            for item in ies.values():
                oferta = item.get("oferta") or {}
                nutricao = oferta.get("nutricao")
                if not nutricao:
                    continue

                # Ignora registros sem qualquer atividade observada em Nutrição.
                if not any(int(nutricao.get(k) or 0) > 0 for k in ("vagas", "matriculas", "concluintes", "cursos")):
                    continue

                nutricao_ies += 1
                instituicao = formatar_nome_instituicao(item.get("nome") or "")
                if not instituicao:
                    continue

                sigla = limpar_espacos(item.get("sigla") or "")
                uf_sede = str(item.get("uf_sede") or "").strip().upper()
                cidade_sede = limpar_espacos(item.get("municipio_sede") or "")
                ufs = [str(x).strip().upper() for x in (item.get("ufs") or []) if str(x).strip()]
                if not ufs and uf_sede:
                    ufs = [uf_sede]

                for uf in ufs:
                    if uf not in {x[0] for x in ESTADOS}:
                        continue
                    cidade = cidade_sede if uf == uf_sede and cidade_sede else "Não identificado"
                    chave = (uf, normalizar(instituicao))
                    if chave in vistos:
                        continue
                    vistos.add(chave)
                    registros.append({
                        "estado": uf,
                        "cidade": cidade,
                        "instituicao": instituicao,
                        "curso": "Nutrição",
                        "origem": ORIGEM_IES,
                        "fonte_url": INEP_FONTES[0][1],
                        "status": "pendente",
                        "fonte_validacao": (
                            "INEP Censo Superior 2024 - espelho processado validado"
                            + (f" | SIGLA={sigla}" if sigla else "")
                        ),
                        "validada": True,
                        "tentativa_descoberta": 0,
                    })

            if nutricao_ies < 500:
                raise RuntimeError(f"carga de Nutrição suspeita: apenas {nutricao_ies} IES")

            acre = [
                x for x in registros
                if x["estado"] == "AC"
                and normalizar(x["instituicao"]) == "universidade federal do acre"
            ]
            if not acre:
                raise RuntimeError("validação de referência falhou: UFAC não encontrada no Acre")

            print(
                f"✅ Espelho validado: {len(ies)} IES totais, "
                f"{nutricao_ies} com Nutrição, {len(registros)} filas IES/UF.",
                flush=True,
            )
            return 2024, registros

        except Exception as exc:
            ultimo = exc
            print(f"   ⚠️ Tentativa {tentativa}/4 falhou: {exc}", flush=True)
            if tentativa < 4:
                time.sleep(2 * tentativa)

    raise RuntimeError(f"espelho estruturado indisponível após 4 tentativas: {ultimo}")


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
        ano, registros = carregar_instituicoes_mirror_inep()
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


def preparar_varredura_v57(repo):
    """Reabre a fila uma única vez para aplicar buscas e filtros V5.7.

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
            "instituicao": "Reabertura da fila para V5.7",
            "status": "concluido",
            "ultimo_erro": None,
            "finalizado_em": agora(),
        })

        print("🔄 Fila oficial reaberta uma vez para a varredura V5.7.", flush=True)
        return True

    except Exception as exc:
        stats["erros"] += 1
        repo.controle_salvar(ETAPA_MIGRACAO_BUSCA, {
            "estado": "BR",
            "cidade": "Nacional",
            "instituicao": "Reabertura da fila para V5.7",
            "status": "erro",
            "ultimo_erro": str(exc)[:1000],
        })
        print(f"❌ Falha preparando a fila V5.7: {exc}", flush=True)
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


def consultas_leads(instituicao, alias=None):
    # Descoberta ampla; aprovação depende exclusivamente da evidência do perfil.
    termos = list(dict.fromkeys(limpar_espacos(t) for t in (alias, instituicao) if t))
    sinais = [
        '"último período"', '"último semestre"', '"7º semestre"',
        '"8º semestre"', '"7º período"', '"8º período"',
        '"recém-formada"', '"recém-formado"', 'concluinte',
        '"estágio final"', '"graduanda em Nutrição"',
        '"estudante de Nutrição"',
    ]
    sinais += [f'{sinal} {ano}' for ano in (2025, 2026)
               for sinal in ('"formatura prevista"', 'TCC', '"colação de grau"')]
    return [f'site:linkedin.com/in "{termo}" Nutrição {sinal}'
            for sinal in sinais for termo in termos]

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


# Uma decisão reúne motivo, ano e período da mesma evidência.
PADRAO_FINAL = r"\b(?:[78](?:o|º)?\s+(?:periodo|semestre)|[78]/8|ultimo\s+(?:periodo|semestre)|recem[- ]formad[oa]|concluinte|formand[oa]|formatura|colacao de grau|conclusao|concluir|concluid[oa]|graduad[oa]|tcc|trabalho de conclusao|estagio final)\b"
PADRAO_ANO = r"\b(20\d{2})(?:[./][12])?\b"


def avaliar_lead(texto):
    n = normalizar(re.sub(r"https?://\S+", "", str(texto or "")))
    def decisao(status, motivo, ano=None, periodo=None, evidencia=None):
        return dict(status=status, motivo=motivo, ano=ano,
                    periodo=periodo, evidencia=evidencia)
    if not re.search(r"\b(?:nutricao|nutricionista)\b", n):
        return decisao("rejeitado", "curso_ausente")
    # Outro curso ou papel de orientação exige confirmação humana.
    if re.search(r"\b(?:psicologia|enfermagem|fisioterapia|medicina|direito|engenharia)\b", n):
        return decisao("revisao", "mais_de_um_curso")
    if re.search(r"\b(?:orientador[a]?|coorientador[a]?|professor[a]?|docente)\b", n):
        return decisao("revisao", "papel_academico_ambiguo")
    if re.search(r"\b(?:nao|nunca|ainda nao)\b.{0,70}" + PADRAO_FINAL, n):
        return decisao("revisao", "negacao_da_fase_final")
    if re.search(r"\b[1-6](?:o|º)?\s+(?:periodo|semestre)\b", n):
        return decisao("revisao", "periodo_inicial_ou_contraditorio")
    # Pontos nas datas semestrais não encerram a evidência.
    blocos = re.split(r"[!;|]|(?<!\d)\.(?!\d)", n)
    for bloco in blocos:
        curso = re.search(r"\b(?:nutricao|nutricionista)\b", bloco)
        intervalo = re.search(r"\b(20\d{2})(?:[./][12])?\s*-\s*(20\d{2})(?:[./][12])?\b", bloco)
        if curso and intervalo:
            inicio, fim = map(int, intervalo.groups())
            if fim < inicio:
                return decisao("rejeitado", "intervalo_invertido")
            if fim in (2025, 2026):
                return decisao("qualificado", "formacao_com_data", fim, "conclusão", bloco.strip())
            return decisao("rejeitado", "formacao_fora_da_janela", fim)
    for bloco in blocos:
        for sinal in re.finditer(PADRAO_FINAL, bloco):
            # O ano deve estar perto do sinal, sem atravessar outra sentença.
            anos = [(abs(m.start()-sinal.start()), int(m.group(1)))
                    for m in re.finditer(PADRAO_ANO, bloco)
                    if abs(m.start()-sinal.start()) <= 100]
            if not anos:
                continue
            _, ano = min(anos)
            if ano not in (2025, 2026):
                return decisao("rejeitado", "fase_fora_da_janela", ano)
            # Ano de emprego/publicação não prova data acadêmica.
            if re.search(r"\b(?:emprego|contratad[oa]|publicacao|atualizad[oa])\b", bloco):
                continue
            periodo = sinal.group(0)
            return decisao("qualificado", "fase_final_com_data", ano, periodo, bloco.strip())
    return decisao("revisao", "sem_evidencia_academica_datada")


def identificar_ano(texto):
    return avaliar_lead(texto)["ano"]


def identificar_periodo(texto):
    return avaliar_lead(texto)["periodo"]


def lead_qualificado(texto):
    return avaliar_lead(texto)["status"] == "qualificado"


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

    if (host == "linkedin.com" or host.endswith(".linkedin.com")) and urlparse(url).path.lower().startswith("/in/"):
        titulo = re.sub(r"(?i)\s*[|\-–—•]\s*LinkedIn.*$", "", titulo)
        candidato = re.split(r"\s+[\-–—|•]\s+", titulo, maxsplit=1)[0]
    elif host == "instagram.com" or host.endswith(".instagram.com"):
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


def contexto_resultado_perfil(resultado, nome=None):
    """Isola o primeiro perfil do resultado.

    Alguns buscadores agregam vários perfis do LinkedIn no mesmo snippet.
    Sem este corte, evidência de uma segunda pessoa poderia qualificar a primeira.
    """
    titulo = limpar_espacos(resultado.get("title", ""))
    corpo = limpar_espacos(resultado.get("body", ""))
    url = str(resultado.get("href") or resultado.get("url") or "")

    # O primeiro "LinkedIn" normalmente encerra o título do primeiro perfil.
    idx_t = titulo.lower().find("linkedin")
    if idx_t > 0:
        titulo = titulo[:idx_t]

    # Um convite inicial pertence ao perfil atual; os próximos iniciam outro.
    corpo = re.sub(r"(?i)^(?:veja o perfil de|view|mira el perfil de)\s+", "", corpo)

    # O texto útil do primeiro perfil vem antes do convite "Veja/View/Mira...".
    corpo_n = normalizar(corpo)
    cortes = [
        "veja o perfil de",
        "veja ",
        "view ",
        "mira el perfil de",
    ]
    indices = []
    for marcador in cortes:
        i = corpo_n.find(marcador)
        if i >= 0:
            indices.append(i)
    if indices:
        corpo = corpo[:min(indices)]

    return limpar_espacos(f"{titulo} {corpo} {url}")


def extrair_instagram(resultado):
    url = str(resultado.get("href") or resultado.get("url") or "")
    m = re.search(r"instagram\.com/([A-Za-z0-9._]+)", url, flags=re.I)
    if not m:
        return None
    usuario = m.group(1).lower()
    if usuario in {"p", "reel", "reels", "stories", "explore", "accounts", "direct", "tv"}:
        return None
    return "@" + usuario


def relacionado_a_instituicao(texto, instituicao, cidade="", alias=None):
    ntexto, inst = normalizar(texto), normalizar(instituicao)
    # UFMT e UFMS não são intercambiáveis.
    if inst == "universidade federal de mato grosso":
        ntexto = ntexto.replace("universidade federal de mato grosso do sul", "")
    if inst and re.search(rf"(?<!\w){re.escape(inst)}(?!\w)", ntexto):
        return True
    alias_n = normalizar(alias or "")
    return bool(alias_n and re.search(rf"(?<!\w){re.escape(alias_n)}(?!\w)", ntexto))

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
        "origem": "captacao_nacional_fila_v57",
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
        "fonte_validacao": "fonte_publica_validada_v57",
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
    alias = alias_instituicao(item)
    consultas = consultas_leads(instituicao, alias)
    total = len(consultas)

    cp = repo.controle_get(etapa_captacao_item(item))
    inicio = 0
    nova_varredura = bool(cp and cp.get("status") == "erro"
                         and cp.get("ultimo_erro") == "Nenhum candidato encontrado; programada segunda varredura")
    if not nova_varredura and cp and cp.get("instituicao") == instituicao and cp.get("estado") == uf and cp.get("status") in {"processando", "erro"}:
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
            url = str(resultado.get("href") or resultado.get("url") or "")
            nome = extrair_nome_resultado(resultado)
            if not nome:
                stats["rejeitados"] += 1
                continue

            texto_real = contexto_resultado_perfil(resultado, nome)
            avaliacao = avaliar_lead(texto_real)
            if avaliacao["status"] != "qualificado":
                stats["rejeitados"] += 1
                if avaliacao["status"] == "revisao":
                    stats["revisao_necessaria"] += 1
                print(f"      FILTRO: {nome} | {avaliacao['status']} | {avaliacao['motivo']}", flush=True)
                continue
            if not relacionado_a_instituicao(texto_real, instituicao, cidade, alias):
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

    novos = stats["leads_salvos"] - salvos_antes

    # Busca pública pode oscilar. Se uma instituição inteira vier zerada,
    # damos uma segunda varredura em execução futura antes de considerá-la
    # realmente concluída.
    tentativas_zero = int(item.get("tentativa_descoberta") or 0)

    if encontrados_local == 0 and tentativas_zero < 1:
        tentativas_zero += 1
        repo.atualizar_instituicao(
            iid,
            status="erro",
            tentativa_descoberta=tentativas_zero,
        )
        stats["instituicoes_processadas"] += 1
        stats["instituicoes_erro"] += 1
        checkpoint_captacao(
            repo,
            item,
            "erro",
            total,
            total,
            encontrados=0,
            salvos=novos,
            erro="Nenhum candidato encontrado; programada segunda varredura",
        )
        print(
            "   🔁 ZERO LEADS: instituição ficará para uma segunda varredura "
            "antes de ser concluída.",
            flush=True,
        )
        return True

    repo.atualizar_instituicao(
        iid,
        status="concluido",
        tentativa_descoberta=tentativas_zero,
    )
    stats["instituicoes_processadas"] += 1
    stats["instituicoes_concluidas"] += 1
    checkpoint_captacao(repo, item, "concluido", total, total, encontrados=encontrados_local, salvos=novos)
    print(f"   ✅ CONCLUÍDA | candidatos web: {encontrados_local} | novos totais: {novos}", flush=True)
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
        ("Candidatos que exigem revisão", "revisao_necessaria"),
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

    if not preparar_varredura_v57(repo):
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
    print(f"✅ CICLO {VERSAO.upper()} FINALIZADO", flush=True)


if __name__ == "__main__":
    executar()
