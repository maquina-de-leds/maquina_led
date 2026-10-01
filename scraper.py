import os
import re
import time
import random
import unicodedata
from datetime import datetime, timezone

from ddgs import DDGS
from supabase import create_client

print("🚀 MÁQUINA 1 - CAPTAÇÃO NACIONAL DE LEADS V4", flush=True)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

DISCOVERY_VERSION = "v4"
ETAPA_CAPTACAO = "captacao_nacional_nutricao_v4"
MAX_RESULTADOS = 30
MAX_INSTITUICOES_POR_EXECUCAO = 8
PAUSA_MIN = 1.0
PAUSA_MAX = 2.0

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
    "estados_descobertos": 0,
    "estados_descoberta_falhou": 0,
    "instituicoes_descobertas": 0,
    "instituicoes_reabertas": 0,
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


def pausa():
    time.sleep(random.uniform(PAUSA_MIN, PAUSA_MAX))


def normalizar(texto):
    texto = str(texto or "").strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        c for c in texto
        if not unicodedata.combining(c)
    )
    texto = re.sub(
        r"\s+",
        " ",
        texto
    )
    return texto.strip()


def limpar_espacos(texto):
    return re.sub(
        r"\s+",
        " ",
        str(texto or "")
    ).strip()


def buscar_ddgs(
    ddgs,
    consulta,
    max_results=MAX_RESULTADOS
):
    backends = [
        "google,brave,bing,yahoo,duckduckgo",
        "google,brave,bing",
        "bing,yahoo,duckduckgo",
    ]

    ultimo_erro = None

    for tentativa, backend in enumerate(
        backends,
        start=1
    ):
        try:

            resultados = ddgs.text(
                consulta,
                region="br-pt",
                safesearch="moderate",
                max_results=max_results,
                backend=backend,
            )

            return list(
                resultados or []
            )

        except Exception as exc:

            ultimo_erro = exc

            print(
                f"      ⚠️ Busca falhou "
                f"({tentativa}/{len(backends)}) "
                f"[{backend}]: {exc}",
                flush=True,
            )

            if tentativa < len(backends):
                time.sleep(
                    1.5 * tentativa
                )

    print(
        f"      ❌ Busca indisponível: "
        f"{ultimo_erro}",
        flush=True
    )

    return None


# ============================================================
# DESCOBERTA DE FACULDADES
# ============================================================

MARCADORES_IES = [
    "universidade",
    "faculdade",
    "centro universitario",
    "instituto federal",
]

BLOQUEIOS_IES = [
    "wikipedia",
    "ranking",
    "melhores faculdades",
    "quero bolsa",
    "mensalidade",
    "vestibular",
    "faculdades de nutricao",
    "lista de faculdades",
    "educabras",
    "cursos.io",
]


def limpar_nome_instituicao(texto):

    texto = limpar_espacos(
        texto
    )

    texto = re.sub(
        r"(?i)^pdf\s+minist[eé]rio\s+da\s+educa[cç][aã]o\s+",
        "",
        texto
    )

    texto = re.sub(
        r"(?i)^curso de\s+",
        "",
        texto
    )

    texto = re.split(
        r"\s+[|–—]\s+",
        texto,
        maxsplit=1
    )[0]

    texto = re.sub(
        r"\s+-\s+(?:[A-Z0-9]{2,12}|"
        r"[a-z0-9.-]+\.(?:br|com|org)(?:\.[a-z]{2})?)\s*$",
        "",
        texto,
        flags=re.I,
    )

    cortes = [
        r"\s+foi\s+",
        r"\s+anunciou\s+",
        r"\s+anuncia\s+",
        r"\s+prepara\s+",
        r"\s+oferece\s+",
        r"\s+abre\s+",
        r"\s+o\s+curso\s+",
        r"\s+curso\s+de\s+nutri[cç][aã]o\s+",
        r"\s+pr[oó]-reitoria\s+de(?:\s+|$)",
        r"\s+centro\s+de\s+\.\.\.",
        r"\s+jun\s+\d{1,2},\s+\d{4}",
        r"\s+documentos\b",
        r"\s+prepara\s+profissionais\b",
    ]

    for corte in cortes:

        texto = re.split(
            corte,
            texto,
            maxsplit=1,
            flags=re.I
        )[0]

    texto = re.sub(
        r"\s*\([A-Z0-9.-]{2,12}\)\s*$",
        "",
        texto
    )

    texto = re.sub(
        r"(?i)\s*[-:|–—]\s*"
        r"(curso de\s+)?nutri[cç][aã]o.*$",
        "",
        texto
    )

    texto = re.sub(
        r"(?i)\s*[-:|–—]\s*"
        r"gradua[cç][aã]o.*$",
        "",
        texto
    )

    return limpar_espacos(
        texto
    ).strip(
        " -–—|:,.;"
    )


def extrair_instituicoes_resultado(
    resultado
):

    titulo = limpar_espacos(
        resultado.get(
            "title",
            ""
        )
    )

    corpo = limpar_espacos(
        resultado.get(
            "body",
            ""
        )
    )

    url = str(
        resultado.get(
            "href"
        )
        or
        resultado.get(
            "url"
        )
        or
        ""
    )

    contexto = normalizar(
        f"{titulo} {corpo} {url}"
    )

    if "nutricao" not in contexto:
        return []

    if any(
        x in contexto
        for x in [
            "foi transformado",
            "foi transformada",
            "instituicao extinta",
            "instituicao descredenciada",
            "antiga denominacao",
            "antigo nome",
        ]
    ):
        return []

    candidatos = []

    texto = (
        f"{titulo} "
        f"{corpo}"
    )

    padroes = [
        r"\bUniversidade\s+"
        r"[A-ZÁÀÂÃÉÈÊÍÌÓÒÔÕÚÙÇ]"
        r"[\wÀ-ÿ .,'&()\-]{2,75}",

        r"\bCentro\s+Universit[aá]rio\s+"
        r"[A-ZÁÀÂÃÉÈÊÍÌÓÒÔÕÚÙÇ]"
        r"[\wÀ-ÿ .,'&()\-]{2,75}",

        r"\bFaculdade\s+"
        r"[A-ZÁÀÂÃÉÈÊÍÌÓÒÔÕÚÙÇ]"
        r"[\wÀ-ÿ .,'&()\-]{2,75}",

        r"\bInstituto\s+Federal\s+"
        r"[A-ZÁÀÂÃÉÈÊÍÌÓÒÔÕÚÙÇ]"
        r"[\wÀ-ÿ .,'&()\-]{2,75}",
    ]

    for padrao in padroes:

        for achado in re.finditer(
            padrao,
            texto,
            flags=re.I
        ):

            candidatos.append(
                limpar_nome_instituicao(
                    achado.group(0)
                )
            )

    titulo_limpo = (
        limpar_nome_instituicao(
            titulo
        )
    )

    if any(
        m in normalizar(
            titulo_limpo
        )
        for m in MARCADORES_IES
    ):

        candidatos.append(
            titulo_limpo
        )

    saida = []
    vistos = set()

    for nome in candidatos:

        nome = limpar_nome_instituicao(
            nome
        )[:100].strip(
            " -–—|:,.;"
        )

        n = normalizar(
            nome
        )

        if not (
            5 <= len(nome) <= 100
        ):
            continue

        if any(
            b in n
            for b in BLOQUEIOS_IES
        ):
            continue

        if not any(
            m in n
            for m in MARCADORES_IES
        ):
            continue

        moldura = (
            f" {n} "
        )

        sobras_ruins = [
            " ministerio da educacao ",
            " pro-reitoria ",
            " curso de nutricao ",
            " prepara profissionais ",
            " abertura de vagas ",
            " anunciou ",
            " documentos ",
        ]

        if any(
            x in moldura
            for x in sobras_ruins
        ):
            continue

        if n not in vistos:

            vistos.add(
                n
            )

            saida.append(
                nome
            )

    return saida


def buscar_instituicao_existente(
    uf,
    instituicao
):

    try:

        r = (
            supabase
            .table(
                "instituicoes_nutricao"
            )
            .select(
                "id,status,cidade,instituicao"
            )
            .eq(
                "estado",
                uf
            )
            .ilike(
                "instituicao",
                instituicao
            )
            .limit(1)
            .execute()
        )

        return (
            r.data[0]
            if r.data
            else None
        )

    except Exception as exc:

        print(
            f"   ⚠️ Erro verificando "
            f"instituição: {exc}",
            flush=True
        )

        stats[
            "erros"
        ] += 1

        return None


def salvar_ou_reabrir_instituicao(
    uf,
    instituicao,
    fonte_url
):

    existente = (
        buscar_instituicao_existente(
            uf,
            instituicao
        )
    )

    if existente:

        try:

            dados = {
                "status":
                    "pendente",

                "fonte_url":
                    fonte_url or None,

                "fonte_validacao":
                    f"descoberta_web_"
                    f"{DISCOVERY_VERSION}",

                "validada":
                    True,
            }

            if not existente.get(
                "cidade"
            ):

                dados[
                    "cidade"
                ] = "Não identificado"

            (
                supabase
                .table(
                    "instituicoes_nutricao"
                )
                .update(
                    dados
                )
                .eq(
                    "id",
                    existente["id"]
                )
                .execute()
            )

            stats[
                "instituicoes_reabertas"
            ] += 1

            print(
                f"   ♻️ Reaberta na fila: "
                f"{instituicao}",
                flush=True
            )

            return True

        except Exception as exc:

            print(
                f"   ⚠️ Não reabriu "
                f"{instituicao}: {exc}",
                flush=True
            )

            stats[
                "erros"
            ] += 1

            return False

    dados = {

        "estado":
            uf,

        "cidade":
            "Não identificado",

        "instituicao":
            instituicao,

        "curso":
            "Nutrição",

        "origem":
            f"descoberta_web_nacional_"
            f"{DISCOVERY_VERSION}",

        "fonte_url":
            fonte_url or None,

        "status":
            "pendente",

        "fonte_validacao":
            f"descoberta_web_"
            f"{DISCOVERY_VERSION}",

        "validada":
            True,

        "tentativa_descoberta":
            0,
    }

    try:

        (
            supabase
            .table(
                "instituicoes_nutricao"
            )
            .insert(
                dados
            )
            .execute()
        )

        stats[
            "instituicoes_descobertas"
        ] += 1

        print(
            f"   ➕ Faculdade adicionada: "
            f"{instituicao}",
            flush=True
        )

        return True

    except Exception as exc:

        print(
            f"   ⚠️ Não salvou instituição "
            f"{instituicao}: {exc}",
            flush=True
        )

        stats[
            "erros"
        ] += 1

        return False


def quantidade_instituicoes_estado(
    uf
):

    try:

        r = (
            supabase
            .table(
                "instituicoes_nutricao"
            )
            .select(
                "id",
                count="exact"
            )
            .eq(
                "estado",
                uf
            )
            .execute()
        )

        return (
            r.count or 0
        )

    except Exception:

        return 0


def etapa_descoberta(
    uf
):

    return (
        f"descoberta_nutricao_"
        f"{uf}_"
        f"{DISCOVERY_VERSION}"
    )


def checkpoint_descoberta(
    uf
):

    try:

        r = (
            supabase
            .table(
                "controle_busca"
            )
            .select(
                "id,status"
            )
            .eq(
                "etapa",
                etapa_descoberta(
                    uf
                )
            )
            .limit(1)
            .execute()
        )

        return (
            r.data[0]
            if r.data
            else None
        )

    except Exception:

        return None


def marcar_descoberta(
    uf,
    status,
    total=0,
    erro=None
):

    etapa = (
        etapa_descoberta(
            uf
        )
    )

    dados = {

        "estado":
            uf,

        "cidade":
            None,

        "instituicao":
            None,

        "etapa":
            etapa,

        "status":
            status,

        "leads_encontrados":
            total,

        "leads_salvos":
            total,

        "ultimo_erro":
            erro,

        "atualizado_em":
            agora(),
    }

    try:

        r = (
            supabase
            .table(
                "controle_busca"
            )
            .select(
                "id"
            )
            .eq(
                "etapa",
                etapa
            )
            .limit(1)
            .execute()
        )

        if r.data:

            (
                supabase
                .table(
                    "controle_busca"
                )
                .update(
                    dados
                )
                .eq(
                    "id",
                    r.data[0]["id"]
                )
                .execute()
            )

        else:

            dados[
                "tentativas"
            ] = 0

            dados[
                "iniciado_em"
            ] = agora()

            (
                supabase
                .table(
                    "controle_busca"
                )
                .insert(
                    dados
                )
                .execute()
            )

    except Exception as exc:

        print(
            f"   ⚠️ Falha no checkpoint "
            f"de descoberta: {exc}",
            flush=True
        )


def descobrir_instituicoes_estado(
    ddgs,
    uf,
    estado_nome
):

    cp = checkpoint_descoberta(
        uf
    )

    total_existente = (
        quantidade_instituicoes_estado(
            uf
        )
    )

    if (
        cp
        and
        cp.get(
            "status"
        ) == "concluido"
        and
        total_existente > 0
    ):

        print(
            f"📚 {uf}: descoberta "
            f"{DISCOVERY_VERSION} "
            f"já concluída "
            f"({total_existente} no banco).",
            flush=True
        )

        return True

    print(
        f"📚 DESCOBRINDO FACULDADES "
        f"DE NUTRIÇÃO — "
        f"{estado_nome}/{uf}",
        flush=True
    )

    marcar_descoberta(
        uf,
        "processando"
    )

    consultas = [

        f'"Nutrição" '
        f'"{estado_nome}" '
        f'universidade faculdade graduação',

        f'"curso de Nutrição" '
        f'"{estado_nome}"',

        f'"bacharelado em Nutrição" '
        f'"{estado_nome}"',

        f'"Nutrição" '
        f'"{estado_nome}" '
        f'"Universidade Federal" '
        f'OR "Centro Universitário"',
    ]

    candidatos = {}

    buscas_executadas = 0

    for consulta in consultas:

        print(
            f"   🔎 {consulta}",
            flush=True
        )

        resultados = buscar_ddgs(
            ddgs,
            consulta,
            max_results=40
        )

        if resultados is None:
            continue

        buscas_executadas += 1

        for resultado in resultados:

            url = (
                resultado.get(
                    "href"
                )
                or
                resultado.get(
                    "url"
                )
                or
                ""
            )

            instituicoes = (
                extrair_instituicoes_resultado(
                    resultado
                )
            )

            for instituicao in instituicoes:

                candidatos[
                    normalizar(
                        instituicao
                    )
                ] = (
                    instituicao,
                    url
                )

        pausa()

    if buscas_executadas == 0:

        marcar_descoberta(
            uf,
            "erro",
            erro=(
                "Nenhuma busca externa "
                "conseguiu executar"
            )
        )

        stats[
            "estados_descoberta_falhou"
        ] += 1

        print(
            f"❌ {uf}: busca externa "
            f"indisponível; ficará pendente "
            f"para próxima execução.",
            flush=True
        )

        return False

    gravadas = 0

    candidatos_ordenados = sorted(
        candidatos.values(),
        key=lambda x:
            normalizar(
                x[0]
            )
    )

    for (
        instituicao,
        url
    ) in candidatos_ordenados:

        if salvar_ou_reabrir_instituicao(
            uf,
            instituicao,
            url
        ):

            gravadas += 1

    total_no_banco = (
        quantidade_instituicoes_estado(
            uf
        )
    )

    if (
        gravadas == 0
        and
        total_no_banco == 0
    ):

        marcar_descoberta(
            uf,
            "erro",
            erro=(
                "Nenhuma instituição válida "
                "encontrada nesta passagem"
            )
        )

        stats[
            "estados_descoberta_falhou"
        ] += 1

        print(
            f"❌ {uf}: nenhuma instituição "
            f"válida encontrada; "
            f"ficará pendente.",
            flush=True
        )

        return False

    marcar_descoberta(
        uf,
        "concluido",
        total=total_no_banco
    )

    stats[
        "estados_descobertos"
    ] += 1

    print(
        f"✅ {uf}: "
        f"{total_no_banco} "
        f"instituição(ões) "
        f"na fila/banco.",
        flush=True
    )

    return True


# ============================================================
# CAPTAÇÃO DE LEADS
# ============================================================

BLOQUEIOS_PESSOA = [
    "universidade",
    "faculdade",
    "centro universitario",
    "vestibular",
    "curso",
    "campus",
    "evento",
    "congresso",
    "encontro cientifico",
    "google docs",
    "pos ead",
    "pos-graduacao",
    "pos graduacao",
    "programa",
    "secretaria",
    "reitoria",
    "inscricoes",
    "edital",
    "processo seletivo",
    "portal do aluno",
    "noticia",
    "noticias",
    "experiencia transformadora",
    "projeto pedagogico",
    "matriz curricular",
    "grade curricular",
    "revista",
    "anais",
    " pdf",
]


def nome_parece_pessoa(
    nome
):

    nome = limpar_espacos(
        nome
    ).strip(
        " -–—|:,.;"
    )

    if (
        len(nome) < 6
        or
        len(nome) > 90
        or
        re.search(
            r"\d",
            nome
        )
    ):
        return False

    n = normalizar(
        nome
    )

    if any(
        b in n
        for b in BLOQUEIOS_PESSOA
    ):
        return False

    partes = [
        p.strip(
            ".,;:()[]{}"
        )
        for p in nome.split()
    ]

    if (
        len(partes) < 2
        or
        len(partes) > 7
    ):
        return False

    conectores = {
        "de",
        "da",
        "do",
        "das",
        "dos",
        "e",
    }

    principais = [
        p
        for p in partes
        if normalizar(
            p
        )
        not in conectores
    ]

    if len(principais) < 2:
        return False

    inicio_bloqueado = {
        "estudante",
        "aluno",
        "aluna",
        "nutricao",
        "nutricionista",
        "trabalho",
        "mostra",
        "semana",
        "palestra",
        "projeto",
        "tcc",
    }

    if (
        normalizar(
            partes[0]
        )
        in inicio_bloqueado
    ):
        return False

    return True


def limpar_nome_titulo(
    titulo
):

    titulo = limpar_espacos(
        titulo
    )

    titulo = re.sub(
        r"(?i)\s*[|\-–—]\s*LinkedIn.*$",
        "",
        titulo
    )

    titulo = re.sub(
        r"(?i)\s*[|\-–—]\s*Instagram.*$",
        "",
        titulo
    )

    titulo = re.sub(
        r"\s*\(@[A-Za-z0-9._]+\).*$",
        "",
        titulo
    )

    titulo = re.sub(
        r"(?i)\s*[-–—|]\s*"
        r"(estudante|graduanda|graduando|"
        r"acad[eê]mica|acad[eê]mico|"
        r"nutricionista|nutri[cç][aã]o|"
        r"tcc|universidade|faculdade).*$",
        "",
        titulo,
    )

    return limpar_espacos(
        titulo
    ).strip(
        " -–—|:,.;"
    )


def extrair_instagram(
    resultado
):

    texto = " ".join(
        str(
            resultado.get(
                k,
                ""
            )
            or
            ""
        )
        for k in (
            "href",
            "url",
            "body",
            "title"
        )
    )

    m = re.search(
        r"instagram\.com/"
        r"([A-Za-z0-9._]+)",
        texto,
        flags=re.I
    )

    if not m:
        return None

    usuario = (
        m.group(
            1
        ).lower()
    )

    bloqueados = {
        "p",
        "reel",
        "reels",
        "stories",
        "explore",
        "accounts",
        "direct",
        "tv",
    }

    if usuario in bloqueados:
        return None

    return (
        "@"
        + usuario
    )


def identificar_ano(
    texto
):

    n = normalizar(
        texto
    )

    if "2026" in n:
        return 2026

    if "2025" in n:
        return 2025

    return None


def identificar_periodo(
    texto
):

    n = normalizar(
        texto
    )

    grupos = [

        (
            "8º período/semestre",
            [
                "8º periodo",
                "8o periodo",
                "8 periodo",
                "8º semestre",
                "8o semestre",
                "8 semestre",
                "8/8",
                "8 de 8",
            ]
        ),

        (
            "7º período/semestre",
            [
                "7º periodo",
                "7o periodo",
                "7 periodo",
                "7º semestre",
                "7o semestre",
                "7 semestre",
                "7/8",
                "7 de 8",
            ]
        ),

        (
            "TCC",
            [
                "tcc",
                "trabalho de conclusao",
            ]
        ),

        (
            "estágio final/obrigatório",
            [
                "estagio obrigatorio",
                "estagio supervisionado",
                "estagio curricular",
                "estagio final",
            ]
        ),

        (
            "formando",
            [
                "formanda",
                "formando",
                "formandas",
                "formandos",
                "concluinte",
                "concluintes",
            ]
        ),

        (
            "recém-formado",
            [
                "recem formada",
                "recem formado",
                "recem-formada",
                "recem-formado",
                "colacao de grau",
                "formatura 2025",
                "formatura 2026",
            ]
        ),
    ]

    for (
        rotulo,
        sinais
    ) in grupos:

        if any(
            s in n
            for s in sinais
        ):
            return rotulo

    return None


def lead_qualificado(
    texto
):

    n = normalizar(
        texto
    )

    sinais_nutricao = [
        "nutricao",
        "nutricionista",
        "estudante de nutricao",
        "graduanda em nutricao",
        "graduando em nutricao",
    ]

    if not any(
        s in n
        for s in sinais_nutricao
    ):
        return False

    return (
        identificar_ano(
            texto
        ) in (
            2025,
            2026
        )
        or
        identificar_periodo(
            texto
        ) is not None
    )


def relacionado_a_instituicao(
    texto,
    instituicao
):

    ntexto = normalizar(
        texto
    )

    palavras = [
        p
        for p in normalizar(
            instituicao
        ).split()
        if (
            len(p) >= 5
            and
            p not in {
                "universidade",
                "faculdade",
                "centro",
                "universitario",
                "instituto",
                "federal",
            }
        )
    ]

    if not palavras:
        return True

    return any(
        p in ntexto
        for p in palavras
    )


def lead_existe(
    nome,
    instituicao
):

    try:

        r = (
            supabase
            .table(
                "leds"
            )
            .select(
                "id"
            )
            .eq(
                "instituicao",
                instituicao
            )
            .ilike(
                "nome",
                nome
            )
            .limit(1)
            .execute()
        )

        return bool(
            r.data
        )

    except Exception as exc:

        print(
            f"      ⚠️ Erro verificando "
            f"duplicidade: {exc}",
            flush=True
        )

        stats[
            "erros"
        ] += 1

        return True


def instagram_ja_usado(
    instagram
):

    if not instagram:
        return False

    try:

        r = (
            supabase
            .table(
                "leds"
            )
            .select(
                "id"
            )
            .eq(
                "instagram",
                instagram
            )
            .limit(1)
            .execute()
        )

        return bool(
            r.data
        )

    except Exception:

        return True


def salvar_lead(
    nome,
    instituicao,
    cidade,
    uf,
    texto,
    url,
    instagram
):

    if lead_existe(
        nome,
        instituicao
    ):

        stats[
            "duplicados"
        ] += 1

        print(
            f"      ♻️ DUPLICADO: "
            f"{nome}",
            flush=True
        )

        return False

    if (
        instagram
        and
        instagram_ja_usado(
            instagram
        )
    ):

        print(
            f"      ⚠️ {instagram} "
            f"já usado; salvando este "
            f"lead sem Instagram.",
            flush=True
        )

        instagram = None

    ano = identificar_ano(
        texto
    )

    periodo = identificar_periodo(
        texto
    )

    dados = {

        "nome":
            nome,

        "instagram":
            instagram,

        "linkedin":
            None,

        "whatsapp":
            None,

        "nicho":
            "nutricionista",

        "origem":
            "captacao_nacional_fila_v4",

        "status":
            "novo",

        "app_baixado":
            False,

        "nao_contatar":
            False,

        "qualificado":
            True,

        "data_primeiro_contato":
            None,

        "data_ultimo_contato":
            None,

        "proxima_acao":
            (
                "primeiro_contato_instagram"
                if instagram
                else
                "buscar_instagram"
            ),

        "tentativas_contato":
            0,

        "cliente":
            False,

        "funil_destino":
            None,

        "cidade":
            cidade
            or
            "Não identificado",

        "estado":
            uf,

        "instituicao":
            instituicao,

        "pontuacao":
            10,

        "evidencia":
            limpar_espacos(
                texto
            )[:1500],

        "fonte_url":
            url or None,

        "ano_alvo":
            ano,

        "periodo_alvo":
            (
                periodo
                or
                (
                    "2025/2026"
                    if ano
                    else None
                )
            ),

        "origem_lead":
            "captacao_academica",

        "rede_processada":
            False,

        "nivel_rede":
            0,

        "fonte_validacao":
            "busca_web_2025_2026_fase_final_v4",
    }

    try:

        (
            supabase
            .table(
                "leds"
            )
            .insert(
                dados
            )
            .execute()
        )

        stats[
            "leads_salvos"
        ] += 1

        extra = (
            f" | {instagram}"
            if instagram
            else
            " | Instagram pendente"
        )

        print(
            f"      ✅ SALVO: "
            f"{nome}{extra}",
            flush=True
        )

        return True

    except Exception as exc:

        stats[
            "erros"
        ] += 1

        print(
            f"      ❌ Erro salvando "
            f"{nome}: {exc}",
            flush=True
        )

        return False


def consultas_leads(
    instituicao
):

    return [

        f'"{instituicao}" '
        f'"Nutrição" "TCC" "2026"',

        f'"{instituicao}" '
        f'"Nutrição" "TCC" "2025"',

        f'"{instituicao}" '
        f'"Nutrição" "formanda" "2026"',

        f'"{instituicao}" '
        f'"Nutrição" "formando" "2026"',

        f'"{instituicao}" '
        f'"Nutrição" "recém-formada" "2025"',

        f'"{instituicao}" '
        f'"Nutrição" "recém-formado" "2025"',

        f'"{instituicao}" '
        f'"Nutrição" "7º período" "2026"',

        f'"{instituicao}" '
        f'"Nutrição" "8º período" "2026"',

        f'"{instituicao}" '
        f'"Nutrição" "7/8" "2026"',

        f'"{instituicao}" '
        f'"Nutrição" "8/8" "2026"',

        f'"{instituicao}" '
        f'"Nutrição" '
        f'"estágio obrigatório" "2026"',

        f'site:linkedin.com/in '
        f'"{instituicao}" '
        f'"Nutrição" "2026"',

        f'site:linkedin.com/in '
        f'"{instituicao}" '
        f'"Nutrição" "2025"',

        f'site:instagram.com '
        f'"{instituicao}" '
        f'"Nutrição" "2026"',

        f'site:instagram.com '
        f'"{instituicao}" '
        f'"Nutrição" "2025"',
    ]


def atualizar_instituicao(
    id_instituicao,
    status
):

    try:

        (
            supabase
            .table(
                "instituicoes_nutricao"
            )
            .update(
                {
                    "status":
                        status,

                    "ultima_verificacao":
                        agora()
                }
            )
            .eq(
                "id",
                id_instituicao
            )
            .execute()
        )

    except Exception as exc:

        print(
            f"   ⚠️ Falha atualizando "
            f"instituição: {exc}",
            flush=True
        )


def salvar_checkpoint_captacao(
    uf,
    cidade,
    instituicao,
    status,
    encontrados=0,
    salvos=0,
    erro=None
):

    dados = {

        "estado":
            uf,

        "cidade":
            cidade or None,

        "instituicao":
            instituicao,

        "etapa":
            ETAPA_CAPTACAO,

        "status":
            status,

        "leads_encontrados":
            encontrados,

        "leads_salvos":
            salvos,

        "ultimo_erro":
            erro,

        "atualizado_em":
            agora(),
    }

    try:

        r = (
            supabase
            .table(
                "controle_busca"
            )
            .select(
                "id"
            )
            .eq(
                "etapa",
                ETAPA_CAPTACAO
            )
            .limit(1)
            .execute()
        )

        if r.data:

            (
                supabase
                .table(
                    "controle_busca"
                )
                .update(
                    dados
                )
                .eq(
                    "id",
                    r.data[0]["id"]
                )
                .execute()
            )

        else:

            dados[
                "tentativas"
            ] = 0

            dados[
                "iniciado_em"
            ] = agora()

            (
                supabase
                .table(
                    "controle_busca"
                )
                .insert(
                    dados
                )
                .execute()
            )

    except Exception as exc:

        print(
            f"   ⚠️ Falha salvando "
            f"checkpoint: {exc}",
            flush=True
        )


def processar_instituicao(
    ddgs,
    item
):

    iid = item[
        "id"
    ]

    uf = item[
        "estado"
    ]

    cidade = (
        item.get(
            "cidade"
        )
        or
        "Não identificado"
    )

    instituicao = item[
        "instituicao"
    ]

    print(
        "\n"
        + "=" * 72,
        flush=True
    )

    print(
        f"🏫 {uf} | "
        f"{instituicao}",
        flush=True
    )

    print(
        "=" * 72,
        flush=True
    )

    atualizar_instituicao(
        iid,
        "processando"
    )

    salvar_checkpoint_captacao(
        uf,
        cidade,
        instituicao,
        "processando"
    )

    vistos = set()

    encontrados = 0

    salvos_antes = stats[
        "leads_salvos"
    ]

    buscas_ok = 0

    consultas = (
        consultas_leads(
            instituicao
        )
    )

    for consulta in consultas:

        print(
            f"   🔎 {consulta}",
            flush=True
        )

        resultados = buscar_ddgs(
            ddgs,
            consulta,
            max_results=MAX_RESULTADOS
        )

        if resultados is None:
            continue

        buscas_ok += 1

        for resultado in resultados:

            titulo = limpar_espacos(
                resultado.get(
                    "title",
                    ""
                )
            )

            corpo = limpar_espacos(
                resultado.get(
                    "body",
                    ""
                )
            )

            url = (
                resultado.get(
                    "href"
                )
                or
                resultado.get(
                    "url"
                )
                or
                ""
            )

            texto_real = (
                f"{titulo} "
                f"{corpo} "
                f"{url}"
            )

            # IMPORTANTE:
            # NÃO usa a própria consulta
            # para qualificar o lead.

            if not lead_qualificado(
                texto_real
            ):
                continue

            if not relacionado_a_instituicao(
                texto_real,
                instituicao
            ):
                continue

            nome = limpar_nome_titulo(
                titulo
            )

            if not nome_parece_pessoa(
                nome
            ):

                stats[
                    "rejeitados"
                ] += 1

                continue

            chave = normalizar(
                nome
            )

            if chave in vistos:
                continue

            vistos.add(
                chave
            )

            instagram = (
                extrair_instagram(
                    resultado
                )
            )

            encontrados += 1

            stats[
                "leads_encontrados"
            ] += 1

            salvar_lead(
                nome,
                instituicao,
                cidade,
                uf,
                texto_real,
                url,
                instagram
            )

        pausa()

    minimo_ok = max(
        8,
        int(
            len(consultas)
            * 0.55
        )
    )

    if buscas_ok < minimo_ok:

        atualizar_instituicao(
            iid,
            "erro"
        )

        stats[
            "instituicoes_erro"
        ] += 1

        salvar_checkpoint_captacao(
            uf,
            cidade,
            instituicao,
            "erro",
            encontrados,
            (
                stats[
                    "leads_salvos"
                ]
                -
                salvos_antes
            ),
            (
                f"Apenas "
                f"{buscas_ok}/"
                f"{len(consultas)} "
                f"buscas executaram"
            ),
        )

        print(
            "   ❌ Busca incompleta; "
            "instituição ficará para "
            "nova tentativa.",
            flush=True
        )

        return False

    atualizar_instituicao(
        iid,
        "concluido"
    )

    stats[
        "instituicoes_processadas"
    ] += 1

    stats[
        "instituicoes_concluidas"
    ] += 1

    novos = (
        stats[
            "leads_salvos"
        ]
        -
        salvos_antes
    )

    salvar_checkpoint_captacao(
        uf,
        cidade,
        instituicao,
        "concluido",
        encontrados,
        novos
    )

    print(
        f"   ✅ CONCLUÍDA | "
        f"candidatos: "
        f"{encontrados} | "
        f"novos: {novos}",
        flush=True
    )

    return True


def fila_estado(
    uf
):

    try:

        r = (
            supabase
            .table(
                "instituicoes_nutricao"
            )
            .select(
                "*"
            )
            .eq(
                "estado",
                uf
            )
            .in_(
                "status",
                [
                    "pendente",
                    "processando",
                    "erro",
                ]
            )
            .order(
                "instituicao"
            )
            .execute()
        )

        return (
            r.data
            or
            []
        )

    except Exception as exc:

        stats[
            "erros"
        ] += 1

        print(
            f"❌ Erro lendo fila "
            f"de {uf}: {exc}",
            flush=True
        )

        return None


def resumo():

    print(
        "\n"
        + "=" * 72,
        flush=True
    )

    print(
        "RESUMO MÁQUINA 1 V4",
        flush=True
    )

    print(
        "=" * 72,
        flush=True
    )

    itens = [
        (
            "Estados descobertos nesta execução",
            "estados_descobertos"
        ),
        (
            "Estados com descoberta pendente",
            "estados_descoberta_falhou"
        ),
        (
            "Novas faculdades descobertas",
            "instituicoes_descobertas"
        ),
        (
            "Faculdades reabertas",
            "instituicoes_reabertas"
        ),
        (
            "Faculdades processadas",
            "instituicoes_processadas"
        ),
        (
            "Faculdades concluídas",
            "instituicoes_concluidas"
        ),
        (
            "Faculdades com erro",
            "instituicoes_erro"
        ),
        (
            "Leads candidatos encontrados",
            "leads_encontrados"
        ),
        (
            "Novos leads salvos",
            "leads_salvos"
        ),
        (
            "Duplicados ignorados",
            "duplicados"
        ),
        (
            "Resultados rejeitados",
            "rejeitados"
        ),
        (
            "Erros",
            "erros"
        ),
    ]

    for (
        rotulo,
        chave
    ) in itens:

        print(
            f"{rotulo}: "
            f"{stats[chave]}",
            flush=True
        )

    print(
        "=" * 72,
        flush=True
    )


def executar():

    print(
        "=" * 72,
        flush=True
    )

    print(
        "🇧🇷 FILA NACIONAL V4 | "
        "NUTRIÇÃO | "
        "2025/2026 | "
        "FASE FINAL",
        flush=True
    )

    print(
        "=" * 72,
        flush=True
    )

    processadas = 0

    with DDGS() as ddgs:

        for (
            uf,
            estado_nome
        ) in ESTADOS:

            print(
                "\n"
                + "#" * 72,
                flush=True
            )

            print(
                f"📍 ESTADO: "
                f"{estado_nome} "
                f"({uf})",
                flush=True
            )

            print(
                "#" * 72,
                flush=True
            )

            descoberta_ok = (
                descobrir_instituicoes_estado(
                    ddgs,
                    uf,
                    estado_nome
                )
            )

            if not descoberta_ok:

                print(
                    f"⏭️ {uf}: descoberta pendente; "
                    f"seguindo para outro estado "
                    f"e tentando {uf} novamente "
                    f"no próximo ciclo.",
                    flush=True
                )

                continue

            fila = fila_estado(
                uf
            )

            if fila is None:
                continue

            if not fila:

                print(
                    f"🏁 {uf}: nenhuma "
                    f"faculdade pendente. "
                    f"Próximo estado.",
                    flush=True
                )

                continue

            print(
                f"📚 {uf}: "
                f"{len(fila)} "
                f"faculdade(s) pendente(s).",
                flush=True
            )

            for item in fila:

                if (
                    processadas
                    >=
                    MAX_INSTITUICOES_POR_EXECUCAO
                ):

                    print(
                        "\n⏸️ Limite seguro "
                        "desta execução atingido.",
                        flush=True
                    )

                    print(
                        "➡️ Próxima execução "
                        "retoma pelas "
                        "pendentes/processando/erro.",
                        flush=True
                    )

                    resumo()

                    return

                processar_instituicao(
                    ddgs,
                    item
                )

                processadas += 1

                pausa()

            restante = fila_estado(
                uf
            )

            if restante == []:

                print(
                    f"🏁 ESTADO {uf} "
                    f"CONCLUÍDO → "
                    f"próximo estado.",
                    flush=True
                )

    resumo()

    print(
        "✅ CICLO FINALIZADO",
        flush=True
    )


if __name__ == "__main__":
    executar()
