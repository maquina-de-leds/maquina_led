import os
import re
import time
import random
import unicodedata
from datetime import datetime, timezone

from ddgs import DDGS
from supabase import create_client

print("🚀 MÁQUINA 1 - CAPTAÇÃO NACIONAL DE LEADS", flush=True)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

ETAPA_CAPTACAO = "captacao_nacional_nutricao_v3"
MAX_RESULTADOS = 30
MAX_INSTITUICOES_POR_EXECUCAO = 8
PAUSA_MIN = 1.5
PAUSA_MAX = 3.0

ESTADOS = [
    ("AC", "Acre"),
    ("AL", "Alagoas"),
    ("AP", "Amapá"),
    ("AM", "Amazonas"),
    ("BA", "Bahia"),
    ("CE", "Ceará"),
    ("DF", "Distrito Federal"),
    ("ES", "Espírito Santo"),
    ("GO", "Goiás"),
    ("MA", "Maranhão"),
    ("MT", "Mato Grosso"),
    ("MS", "Mato Grosso do Sul"),
    ("MG", "Minas Gerais"),
    ("PA", "Pará"),
    ("PB", "Paraíba"),
    ("PR", "Paraná"),
    ("PE", "Pernambuco"),
    ("PI", "Piauí"),
    ("RJ", "Rio de Janeiro"),
    ("RN", "Rio Grande do Norte"),
    ("RS", "Rio Grande do Sul"),
    ("RO", "Rondônia"),
    ("RR", "Roraima"),
    ("SC", "Santa Catarina"),
    ("SP", "São Paulo"),
    ("SE", "Sergipe"),
    ("TO", "Tocantins"),
]

stats = {
    "estados_descobertos": 0,
    "instituicoes_descobertas": 0,
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

    texto = unicodedata.normalize(
        "NFKD",
        texto
    )

    texto = "".join(
        c
        for c in texto
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
    for tentativa in range(1, 4):

        try:
            return list(
                ddgs.text(
                    consulta,
                    max_results=max_results
                )
            )

        except Exception as exc:

            print(
                f"      ⚠️ Busca falhou "
                f"({tentativa}/3): {exc}",
                flush=True
            )

            if tentativa < 3:
                time.sleep(
                    2 * tentativa
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
    "noticia",
    "noticias",
    "vestibular",
]


def limpar_nome_instituicao(texto):

    texto = limpar_espacos(
        texto
    )

    texto = re.sub(
        r"\s+[|–—]\s+.*$",
        "",
        texto
    )

    texto = re.sub(
        r"(?i)^\s*(curso de\s+)?"
        r"nutri[cç][aã]o\s*[-:|–—]\s*",
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

    texto = (
        f"{titulo} "
        f"{corpo}"
    )

    candidatos = []

    padroes = [
        r"\bUniversidade\s+[\wÀ-ÿ .,'&()\-]{3,90}",
        r"\bCentro\s+Universit[aá]rio\s+[\wÀ-ÿ .,'&()\-]{3,90}",
        r"\bFaculdade\s+[\wÀ-ÿ .,'&()\-]{3,90}",
        r"\bInstituto\s+Federal\s+[\wÀ-ÿ .,'&()\-]{3,90}",
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

        nome = nome[
            :120
        ].strip(
            " -–—|:,.;"
        )

        nome_n = normalizar(
            nome
        )

        if len(nome) < 5:
            continue

        if len(nome) > 120:
            continue

        if any(
            b in nome_n
            for b in BLOQUEIOS_IES
        ):
            continue

        if "nutricao" in nome_n:

            nome = limpar_nome_instituicao(
                nome
            )

            nome_n = normalizar(
                nome
            )

        if not any(
            m in nome_n
            for m in MARCADORES_IES
        ):
            continue

        if nome_n not in vistos:

            vistos.add(
                nome_n
            )

            saida.append(
                nome
            )

    return saida


def instituicao_existe(
    uf,
    instituicao
):

    try:

        resposta = (
            supabase
            .table(
                "instituicoes_nutricao"
            )
            .select(
                "id,status"
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

        if resposta.data:
            return resposta.data[0]

        return None

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


def salvar_instituicao(
    uf,
    instituicao,
    fonte_url
):

    if instituicao_existe(
        uf,
        instituicao
    ):
        return False

    dados = {

        "estado":
            uf,

        "cidade":
            None,

        "instituicao":
            instituicao,

        "curso":
            "Nutrição",

        "origem":
            "descoberta_web_nacional",

        "fonte_url":
            fonte_url or None,

        "status":
            "pendente",

        "fonte_validacao":
            "busca_web_curso_nutricao",

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
            f"   ➕ {instituicao}",
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


def checkpoint_descoberta(
    uf
):

    etapa = (
        f"descoberta_nutricao_"
        f"{uf}_v3"
    )

    try:

        resposta = (
            supabase
            .table(
                "controle_busca"
            )
            .select(
                "id,status"
            )
            .eq(
                "etapa",
                etapa
            )
            .limit(1)
            .execute()
        )

        if resposta.data:
            return resposta.data[0]

        return None

    except Exception:

        return None


def marcar_descoberta(
    uf,
    status,
    total=0,
    erro=None
):

    etapa = (
        f"descoberta_nutricao_"
        f"{uf}_v3"
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

        resposta = (
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

        if resposta.data:

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
                    resposta.data[0]["id"]
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


def validar_instituicao(
    ddgs,
    instituicao,
    estado_nome
):

    consulta = (
        f'"{instituicao}" '
        f'"Nutrição" '
        f'"{estado_nome}"'
    )

    resultados = buscar_ddgs(
        ddgs,
        consulta,
        max_results=8
    )

    if resultados is None:
        return None

    if not resultados:
        return False

    tokens = [
        p
        for p
        in normalizar(
            instituicao
        ).split()
        if len(p) >= 5
    ]

    for resultado in resultados:

        texto = normalizar(
            f'{resultado.get("title", "")} '
            f'{resultado.get("body", "")} '
            f'{resultado.get("href", "")}'
        )

        if "nutricao" not in texto:
            continue

        if (
            tokens
            and
            not any(
                token in texto
                for token in tokens
            )
        ):
            continue

        return True

    return False


def descobrir_instituicoes_estado(
    ddgs,
    uf,
    estado_nome
):

    cp = checkpoint_descoberta(
        uf
    )

    if (
        cp
        and
        cp.get(
            "status"
        )
        == "concluido"
    ):

        print(
            f"📚 {uf}: lista de faculdades "
            f"já descoberta anteriormente.",
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

        f'"curso de Nutrição" '
        f'"{estado_nome}" universidade',

        f'"graduação em Nutrição" '
        f'"{estado_nome}" faculdade',

        f'"bacharelado em Nutrição" '
        f'"{estado_nome}"',

        f'"Nutrição" '
        f'"{estado_nome}" '
        f'"Centro Universitário"',

        f'"Nutrição" '
        f'"{estado_nome}" '
        f'"Universidade Federal"',

        f'"Nutrição" '
        f'"{estado_nome}" '
        f'"Universidade Estadual"',

        f'"Nutrição" '
        f'"{estado_nome}" '
        f'"faculdade" "MEC"',
    ]

    candidatos = {}

    buscas_ok = 0

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

        buscas_ok += 1

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

    if buscas_ok < 4:

        marcar_descoberta(
            uf,
            "erro",
            erro=(
                f"Apenas {buscas_ok}/"
                f"{len(consultas)} "
                f"buscas de instituições "
                f"executaram"
            ),
        )

        print(
            f"❌ {uf}: descoberta incompleta. "
            f"Será tentada novamente.",
            flush=True
        )

        return False

    validadas_total = 0

    candidatos_ordenados = sorted(
        candidatos.values(),
        key=lambda x: normalizar(
            x[0]
        )
    )

    for (
        instituicao,
        url
    ) in candidatos_ordenados:

        validacao = validar_instituicao(
            ddgs,
            instituicao,
            estado_nome
        )

        if validacao is None:
            continue

        if not validacao:
            continue

        validadas_total += 1

        salvar_instituicao(
            uf,
            instituicao,
            url
        )

        pausa()

    if validadas_total == 0:

        marcar_descoberta(
            uf,
            "erro",
            erro=(
                "Nenhuma faculdade "
                "validada nesta tentativa"
            )
        )

        print(
            f"❌ {uf}: nenhuma faculdade "
            f"validada. Estado não será pulado.",
            flush=True
        )

        return False

    marcar_descoberta(
        uf,
        "concluido",
        total=validadas_total
    )

    stats[
        "estados_descobertos"
    ] += 1

    print(
        f"✅ {uf}: {validadas_total} "
        f"faculdade(s) de Nutrição "
        f"validada(s).",
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

    if len(nome) < 6:
        return False

    if len(nome) > 90:
        return False

    if re.search(
        r"\d",
        nome
    ):
        return False

    nome_n = normalizar(
        nome
    )

    if any(
        b in nome_n
        for b in BLOQUEIOS_PESSOA
    ):
        return False

    partes = [
        p.strip(
            ".,;:()[]{}"
        )
        for p
        in nome.split()
    ]

    if len(partes) < 2:
        return False

    if len(partes) > 7:
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
        r"(?i)\s*\|\s*LinkedIn.*$",
        "",
        titulo
    )

    titulo = re.sub(
        r"(?i)\s*[-–—]\s*LinkedIn.*$",
        "",
        titulo
    )

    titulo = re.sub(
        r"(?i)\s*\|\s*Instagram.*$",
        "",
        titulo
    )

    titulo = re.sub(
        r"(?i)\s*[-–—]\s*Instagram.*$",
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

    texto = (
        f'{url} '
        f'{resultado.get("body", "")} '
        f'{resultado.get("title", "")}'
    )

    achado = re.search(
        r"instagram\.com/"
        r"([A-Za-z0-9._]+)",
        texto,
        flags=re.I
    )

    if not achado:
        return None

    usuario = achado.group(
        1
    ).lower()

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


def instagram_ja_usado(
    instagram
):

    if not instagram:
        return False

    try:

        resposta = (
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
            resposta.data
        )

    except Exception as exc:

        print(
            f"      ⚠️ Não consegui confirmar "
            f"Instagram duplicado: {exc}",
            flush=True
        )

        return True


def identificar_ano(
    texto
):

    texto_n = normalizar(
        texto
    )

    if "2026" in texto_n:
        return 2026

    if "2025" in texto_n:
        return 2025

    return None


def identificar_periodo(
    texto
):

    texto_n = normalizar(
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
            sinal in texto_n
            for sinal in sinais
        ):
            return rotulo

    return None


def lead_qualificado(
    texto
):

    texto_n = normalizar(
        texto
    )

    tem_nutricao = any(
        sinal in texto_n
        for sinal in [
            "nutricao",
            "nutricionista",
            "estudante de nutricao",
            "graduanda em nutricao",
            "graduando em nutricao",
        ]
    )

    if not tem_nutricao:
        return False

    ano = identificar_ano(
        texto
    )

    periodo = identificar_periodo(
        texto
    )

    return (
        ano in (
            2025,
            2026
        )
        or
        periodo is not None
    )


def lead_existe(
    nome,
    instituicao
):

    try:

        resposta = (
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
            resposta.data
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
            f"      ♻️ DUPLICADO: {nome}",
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
            f"      ⚠️ Instagram "
            f"{instagram} já pertence "
            f"a outro lead; salvando "
            f"sem Instagram.",
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
            "captacao_nacional_fila",

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
            cidade or None,

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
            "busca_web_2025_2026_fase_final",
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

        complemento = (
            f" | {instagram}"
            if instagram
            else
            " | Instagram pendente"
        )

        print(
            f"      ✅ SALVO: "
            f"{nome}{complemento}",
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

        resposta = (
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

        if resposta.data:

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
                    resposta.data[0]["id"]
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

    id_instituicao = item[
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
        ""
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
        f"🏫 {uf} | {instituicao}",
        flush=True
    )

    print(
        "=" * 72,
        flush=True
    )

    atualizar_instituicao(
        id_instituicao,
        "processando"
    )

    salvar_checkpoint_captacao(
        uf,
        cidade,
        instituicao,
        "processando"
    )

    vistos_execucao = set()

    encontrados_instituicao = 0

    salvos_antes = stats[
        "leads_salvos"
    ]

    buscas_ok = 0

    consultas = consultas_leads(
        instituicao
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

            texto = (
                f"{titulo} "
                f"{corpo} "
                f"{consulta}"
            )

            if not lead_qualificado(
                texto
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

            if chave in vistos_execucao:
                continue

            vistos_execucao.add(
                chave
            )

            instagram = (
                extrair_instagram(
                    resultado
                )
            )

            encontrados_instituicao += 1

            stats[
                "leads_encontrados"
            ] += 1

            # SALVA IMEDIATAMENTE
            # COM OU SEM INSTAGRAM.
            salvar_lead(
                nome=nome,
                instituicao=instituicao,
                cidade=cidade,
                uf=uf,
                texto=texto,
                url=url,
                instagram=instagram,
            )

        pausa()

    # Só conclui a faculdade
    # se a maioria das pesquisas
    # realmente conseguiu rodar.
    minimo_buscas_ok = max(
        10,
        int(
            len(consultas)
            * 0.70
        )
    )

    if buscas_ok < minimo_buscas_ok:

        atualizar_instituicao(
            id_instituicao,
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
            encontrados=
                encontrados_instituicao,
            salvos=
                (
                    stats[
                        "leads_salvos"
                    ]
                    -
                    salvos_antes
                ),
            erro=(
                f"Apenas {buscas_ok}/"
                f"{len(consultas)} "
                f"buscas executaram"
            ),
        )

        print(
            "   ❌ Busca incompleta. "
            "Faculdade ficará para "
            "nova tentativa.",
            flush=True
        )

        return False

    atualizar_instituicao(
        id_instituicao,
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
        encontrados=
            encontrados_instituicao,
        salvos=
            novos,
    )

    print(
        f"   ✅ CONCLUÍDA | "
        f"candidatos: "
        f"{encontrados_instituicao} | "
        f"novos: {novos}",
        flush=True,
    )

    return True


def fila_estado(
    uf
):

    try:

        resposta = (
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
            resposta.data
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
        "RESUMO MÁQUINA 1",
        flush=True
    )

    print(
        "=" * 72,
        flush=True
    )

    print(
        f"Estados descobertos nesta execução: "
        f"{stats['estados_descobertos']}",
        flush=True
    )

    print(
        f"Novas faculdades descobertas: "
        f"{stats['instituicoes_descobertas']}",
        flush=True
    )

    print(
        f"Faculdades processadas: "
        f"{stats['instituicoes_processadas']}",
        flush=True
    )

    print(
        f"Faculdades concluídas: "
        f"{stats['instituicoes_concluidas']}",
        flush=True
    )

    print(
        f"Faculdades com erro: "
        f"{stats['instituicoes_erro']}",
        flush=True
    )

    print(
        f"Leads candidatos encontrados: "
        f"{stats['leads_encontrados']}",
        flush=True
    )

    print(
        f"Novos leads salvos: "
        f"{stats['leads_salvos']}",
        flush=True
    )

    print(
        f"Duplicados ignorados: "
        f"{stats['duplicados']}",
        flush=True
    )

    print(
        f"Resultados rejeitados: "
        f"{stats['rejeitados']}",
        flush=True
    )

    print(
        f"Erros: "
        f"{stats['erros']}",
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
        "🇧🇷 FILA NACIONAL | "
        "NUTRIÇÃO | "
        "2025/2026 | "
        "FASE FINAL",
        flush=True
    )

    print(
        "=" * 72,
        flush=True
    )

    processadas_nesta_execucao = 0

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

            # ================================================
            # 1. DESCOBRE E SALVA A LISTA
            # DE FACULDADES DE NUTRIÇÃO DO ESTADO
            # ================================================

            if not descobrir_instituicoes_estado(
                ddgs,
                uf,
                estado_nome
            ):

                print(
                    f"⏭️ {uf}: não vou pular "
                    f"um estado cuja descoberta "
                    f"falhou.",
                    flush=True
                )

                resumo()

                return

            # ================================================
            # 2. PEGA A FILA DO ESTADO
            # ================================================

            fila = fila_estado(
                uf
            )

            if fila is None:

                resumo()

                return

            if not fila:

                print(
                    f"🏁 {uf}: nenhuma faculdade "
                    f"pendente. Próximo estado.",
                    flush=True
                )

                continue

            print(
                f"📚 {uf}: "
                f"{len(fila)} "
                f"faculdade(s) pendente(s).",
                flush=True
            )

            # ================================================
            # 3. FACULDADE POR FACULDADE
            # ================================================

            for item in fila:

                if (
                    processadas_nesta_execucao
                    >=
                    MAX_INSTITUICOES_POR_EXECUCAO
                ):

                    print(
                        "\n⏸️ Limite seguro desta "
                        "execução atingido.",
                        flush=True
                    )

                    print(
                        "➡️ A próxima execução "
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

                processadas_nesta_execucao += 1

                pausa()

            # ================================================
            # 4. CONFERE SE TERMINOU O ESTADO
            # ================================================

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
