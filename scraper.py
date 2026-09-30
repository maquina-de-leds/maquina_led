import os
import re
import time
import random
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse

from ddgs import DDGS
from supabase import create_client


# ============================================================
# MÁQUINA DE LEADS - TESTE VALIDADO
# ============================================================
#
# FOCO:
#   Nutrição
#   somente 2025 e 2026
#
# FLUXO:
#
# Faculdade
#   ↓
# procura candidatos públicos
#   ↓
# LinkedIn / Instagram
#   ↓
# valida Nutrição + 2025/2026
#   ↓
# salva no Supabase
#   ↓
# expansão pela mesma rede acadêmica
#   ↓
# tenta gerar até 3 novos leads relacionados
#
# IMPORTANTE:
# Não acessa lista privada de amigos/seguidores.
# A expansão utiliza somente informações públicas/indexadas.
# ============================================================


# ============================================================
# SUPABASE
# ============================================================

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


# ============================================================
# FACULDADES DO TESTE
#
# Começamos pelas regiões que já validamos manualmente.
# Depois ampliaremos nacionalmente.
# ============================================================

FACULDADES = [

    # --------------------------------------------------------
    # SÃO PAULO
    # --------------------------------------------------------

    {
        "nome": "Universidade Presbiteriana Mackenzie",
        "sigla": "Mackenzie",
        "cidade": "São Paulo",
        "estado": "SP",
        "dominio": "mackenzie.br",
    },

    {
        "nome": "Universidade Paulista",
        "sigla": "UNIP",
        "cidade": "São Paulo",
        "estado": "SP",
        "dominio": "unip.br",
    },

    {
        "nome": "PUC-Campinas",
        "sigla": "PUC Campinas",
        "cidade": "Campinas",
        "estado": "SP",
        "dominio": "puc-campinas.edu.br",
    },

    {
        "nome": "Universidade Anhembi Morumbi",
        "sigla": "Anhembi Morumbi",
        "cidade": "São Paulo",
        "estado": "SP",
        "dominio": "anhembi.br",
    },

    {
        "nome": "Universidade Nove de Julho",
        "sigla": "UNINOVE",
        "cidade": "São Paulo",
        "estado": "SP",
        "dominio": "uninove.br",
    },

    {
        "nome": "Faculdade Santa Marcelina",
        "sigla": "Santa Marcelina",
        "cidade": "São Paulo",
        "estado": "SP",
        "dominio": "santamarcelina.edu.br",
    },

    {
        "nome": "Centro Universitário São Camilo",
        "sigla": "São Camilo",
        "cidade": "São Paulo",
        "estado": "SP",
        "dominio": "saocamilo-sp.br",
    },

    {
        "nome": "Universidade de Sorocaba",
        "sigla": "UNISO",
        "cidade": "Sorocaba",
        "estado": "SP",
        "dominio": "uniso.br",
    },

    {
        "nome": "Universidade de Ribeirão Preto",
        "sigla": "UNAERP",
        "cidade": "Ribeirão Preto",
        "estado": "SP",
        "dominio": "unaerp.br",
    },

    {
        "nome": "Universidade de São Paulo",
        "sigla": "USP",
        "cidade": "São Paulo",
        "estado": "SP",
        "dominio": "usp.br",
    },


    # --------------------------------------------------------
    # MINAS GERAIS
    # --------------------------------------------------------

    {
        "nome": "Universidade Federal de Viçosa",
        "sigla": "UFV",
        "cidade": "Viçosa",
        "estado": "MG",
        "dominio": "ufv.br",
    },

    {
        "nome": "Pontifícia Universidade Católica de Minas Gerais",
        "sigla": "PUC Minas",
        "cidade": "Belo Horizonte",
        "estado": "MG",
        "dominio": "pucminas.br",
    },


    # --------------------------------------------------------
    # RIO DE JANEIRO
    # --------------------------------------------------------

    {
        "nome": "Universidade Federal do Rio de Janeiro",
        "sigla": "UFRJ",
        "cidade": "Rio de Janeiro",
        "estado": "RJ",
        "dominio": "ufrj.br",
    },

    {
        "nome": "Universidade Federal do Estado do Rio de Janeiro",
        "sigla": "UNIRIO",
        "cidade": "Rio de Janeiro",
        "estado": "RJ",
        "dominio": "unirio.br",
    },

    {
        "nome": "Universidade do Estado do Rio de Janeiro",
        "sigla": "UERJ",
        "cidade": "Rio de Janeiro",
        "estado": "RJ",
        "dominio": "uerj.br",
    },

    {
        "nome": "Universidade Estácio de Sá",
        "sigla": "Estácio",
        "cidade": "Rio de Janeiro",
        "estado": "RJ",
        "dominio": "estacio.br",
    },


    # --------------------------------------------------------
    # BAHIA
    # --------------------------------------------------------

    {
        "nome": "Universidade Salvador",
        "sigla": "UNIFACS",
        "cidade": "Salvador",
        "estado": "BA",
        "dominio": "unifacs.br",
    },

    {
        "nome": "Centro Universitário Jorge Amado",
        "sigla": "UNIJORGE",
        "cidade": "Salvador",
        "estado": "BA",
        "dominio": "unijorge.edu.br",
    },

    {
        "nome": "Universidade Federal da Bahia",
        "sigla": "UFBA",
        "cidade": "Salvador",
        "estado": "BA",
        "dominio": "ufba.br",
    },
]


# ============================================================
# LIMITES DO TESTE
# ============================================================

MAX_FACULDADES_POR_EXECUCAO = 10

MAX_RESULTADOS_POR_BUSCA = 20

MAX_LEADS_PRINCIPAIS_POR_FACULDADE = 10

MAX_EXPANSAO_POR_LEAD = 3

MAX_NIVEL_REDE = 1

PONTUACAO_MINIMA = 9

PAUSA_MIN = 4
PAUSA_MAX = 7

MAX_TENTATIVAS_BUSCA = 3


# ============================================================
# ESTATÍSTICAS
# ============================================================

stats = {

    "faculdades": 0,

    "buscas": 0,

    "resultados": 0,

    "candidatos": 0,

    "qualificados": 0,

    "salvos": 0,

    "duplicados": 0,

    "expansoes": 0,

    "rejeitados_ano": 0,

    "rejeitados_nicho": 0,

    "institucionais": 0,

    "erros": 0,
}


# ============================================================
# MEMÓRIA DA EXECUÇÃO
# ============================================================

vistos = set()

salvos_execucao = set()

expandidos_execucao = set()


# ============================================================
# UTILIDADES
# ============================================================

def agora():

    return datetime.now(
        timezone.utc
    ).isoformat()


def normalizar(texto):

    if texto is None:
        return ""

    texto = str(texto).lower()

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


def pausa():

    time.sleep(
        random.uniform(
            PAUSA_MIN,
            PAUSA_MAX
        )
    )


# ============================================================
# PESQUISA
# ============================================================

def pesquisar(
    ddgs,
    consulta
):

    stats["buscas"] += 1

    for tentativa in range(
        1,
        MAX_TENTATIVAS_BUSCA + 1
    ):

        try:

            print(
                f"      🔎 {consulta}"
            )

            resultados = list(
                ddgs.text(
                    consulta,
                    max_results=
                        MAX_RESULTADOS_POR_BUSCA
                )
            )

            return resultados

        except Exception as erro:

            print(
                f"      ⚠️ Tentativa "
                f"{tentativa}/"
                f"{MAX_TENTATIVAS_BUSCA}: "
                f"{erro}"
            )

            if tentativa < MAX_TENTATIVAS_BUSCA:

                time.sleep(
                    10 * tentativa
                )

    stats["erros"] += 1

    return []


# ============================================================
# IDENTIFICAR LINKEDIN / INSTAGRAM
# ============================================================

def extrair_rede(
    url
):

    if not url:
        return (
            None,
            None
        )

    try:

        parsed = urlparse(
            url
        )

        dominio = (
            parsed.netloc
            .lower()
            .replace(
                "www.",
                ""
            )
        )

        # ----------------------------------------------------
        # LINKEDIN
        # ----------------------------------------------------

        if "linkedin.com" in dominio:

            if "/in/" in parsed.path:

                return (
                    "linkedin",
                    url
                )

        # ----------------------------------------------------
        # INSTAGRAM
        # ----------------------------------------------------

        if "instagram.com" in dominio:

            partes = [
                p
                for p
                in parsed.path.split("/")
                if p
            ]

            if not partes:

                return (
                    None,
                    None
                )

            usuario = (
                partes[0]
                .lower()
            )

            bloqueados = {
                "p",
                "reel",
                "reels",
                "stories",
                "explore",
                "accounts",
            }

            if usuario in bloqueados:

                return (
                    None,
                    None
                )

            if re.match(
                r"^[a-zA-Z0-9._]+$",
                usuario
            ):

                return (
                    "instagram",
                    "@" + usuario
                )

    except Exception:

        pass

    return (
        None,
        None
    )


# ============================================================
# EXTRAIR NOME
# ============================================================

def extrair_nome(
    titulo
):

    titulo = (
        titulo
        or ""
    ).strip()

    if not titulo:

        return ""

    # remove partes típicas dos resultados
    titulo = re.sub(
        r"\s*[\|\-–—]\s*LinkedIn.*$",
        "",
        titulo,
        flags=re.I
    )

    titulo = re.sub(
        r"\s*[\|\-–—].*$",
        "",
        titulo
    )

    titulo = re.sub(
        r"\s+",
        " ",
        titulo
    )

    return titulo.strip()


# ============================================================
# CONTA INSTITUCIONAL
# ============================================================

def conta_institucional(
    nome,
    texto,
    instagram
):

    nome_norm = normalizar(
        nome
    )

    texto_norm = normalizar(
        texto
    )

    instagram_norm = normalizar(
        instagram
    )

    bloqueados = [
        "universidade",
        "faculdade",
        "centro academico",
        "diretorio academico",
        "atletica",
        "turma nutricao",
        "formatura nutricao",
        "comissao de formatura",
        "liga academica",
        "projeto de extensao",
        "departamento de nutricao",
        "curso de nutricao",
    ]

    handle_bloqueado = [
        "nutricao.uf",
        "nutricao_uf",
        "nutricao.un",
        "nutricao_uni",
        "turmanutri",
        "formaturan",
        "atletica",
    ]

    if any(
        termo in nome_norm
        for termo in bloqueados
    ):

        return True

    if any(
        termo in instagram_norm
        for termo in handle_bloqueado
    ):

        return True

    # Se o texto parece claramente institucional
    # e não traz indicação de pessoa.
    sinais_pessoa = [
        "estudante",
        "graduanda",
        "graduando",
        "formanda",
        "formando",
        "nutricionista",
        "bacharel",
        "estagio",
        "tcc",
    ]

    institucional = any(
        termo in texto_norm
        for termo in bloqueados
    )

    pessoa = any(
        termo in texto_norm
        for termo in sinais_pessoa
    )

    return (
        institucional
        and not pessoa
    )


# ============================================================
# CONFIRMAR NUTRIÇÃO
# ============================================================

def prova_nutricao(
    texto
):

    t = normalizar(
        texto
    )

    fortes = [

        "nutricionista",

        "graduanda em nutricao",

        "graduando em nutricao",

        "estudante de nutricao",

        "formanda em nutricao",

        "formando em nutricao",

        "bacharel em nutricao",

        "curso de nutricao",

        "graduacao em nutricao",

        "nutricao",
    ]

    return any(
        termo in t
        for termo in fortes
    )


# ============================================================
# CONFIRMAR SOMENTE 2025 OU 2026
# ============================================================

def identificar_ano_alvo(
    texto
):

    t = normalizar(
        texto
    )

    # --------------------------------------------------------
    # PRIORIDADE PARA 2026
    # --------------------------------------------------------

    if "2026" in t:

        return 2026

    # --------------------------------------------------------
    # DEPOIS 2025
    # --------------------------------------------------------

    if "2025" in t:

        return 2025

    # --------------------------------------------------------
    # NENHUM OUTRO ANO SERVE
    # --------------------------------------------------------

    return None


# ============================================================
# IDENTIFICAR FASE
# ============================================================

def identificar_periodo(
    texto
):

    t = normalizar(
        texto
    )

    regras = [

        (
            [
                "recem-formada",
                "recem-formado",
                "recem formada",
                "recem formado",
            ],
            "recém-formado"
        ),

        (
            [
                "formanda",
                "formando",
            ],
            "formando"
        ),

        (
            [
                "ultimo periodo",
                "ultimo semestre",
                "ultimo ano",
            ],
            "último período"
        ),

        (
            [
                "9 periodo",
                "9o periodo",
                "9º periodo",
            ],
            "9º período"
        ),

        (
            [
                "8 periodo",
                "8o periodo",
                "8º periodo",
                "8/8",
                "8 de 8",
            ],
            "8º período"
        ),

        (
            [
                "7 periodo",
                "7o periodo",
                "7º periodo",
                "7/8",
                "7 de 8",
            ],
            "7º período"
        ),

        (
            [
                "tcc",
                "trabalho de conclusao",
            ],
            "TCC"
        ),

        (
            [
                "estagio obrigatorio",
                "estagio curricular",
                "estagio final",
            ],
            "estágio final"
        ),

        (
            [
                "conclusao",
                "conclusao prevista",
                "formatura",
                "colacao",
            ],
            "conclusão"
        ),
    ]

    for termos, descricao in regras:

        if any(
            termo in t
            for termo in termos
        ):

            return descricao

    return None


# ============================================================
# PONTUAÇÃO
# ============================================================

def pontuar(
    texto,
    faculdade,
    ano,
    periodo
):

    t = normalizar(
        texto
    )

    pontos = 0

    if "nutricao" in t:

        pontos += 3

    if "nutricionista" in t:

        pontos += 3

    if ano in [
        2025,
        2026
    ]:

        pontos += 4

    if periodo:

        pontos += 4

    sigla = normalizar(
        faculdade["sigla"]
    )

    nome = normalizar(
        faculdade["nome"]
    )

    if (
        sigla
        and sigla in t
    ):

        pontos += 3

    elif (
        nome
        and nome in t
    ):

        pontos += 3

    cidade = normalizar(
        faculdade["cidade"]
    )

    if (
        cidade
        and cidade in t
    ):

        pontos += 1

    return pontos


# ============================================================
# DUPLICIDADE
# ============================================================

def ja_existe(
    nome=None,
    instagram=None,
    linkedin=None
):

    try:

        if instagram:

            r = (
                supabase
                .table("leds")
                .select("id")
                .eq(
                    "instagram",
                    instagram
                )
                .limit(1)
                .execute()
            )

            if r.data:

                return True

        if linkedin:

            r = (
                supabase
                .table("leds")
                .select("id")
                .eq(
                    "linkedin",
                    linkedin
                )
                .limit(1)
                .execute()
            )

            if r.data:

                return True

        # Nome só é usado como terceira proteção.
        if nome:

            r = (
                supabase
                .table("leds")
                .select("id,nome")
                .ilike(
                    "nome",
                    nome
                )
                .limit(3)
                .execute()
            )

            if r.data:

                return True

        return False

    except Exception as erro:

        print(
            f"      ⚠️ Erro verificando "
            f"duplicidade: {erro}"
        )

        # Em caso de dúvida não salva.
        return None


# ============================================================
# SALVAR
# ============================================================

def salvar(
    nome,
    faculdade,
    ano,
    periodo,
    evidencia,
    fonte_url,
    instagram=None,
    linkedin=None,
    origem_lead="busca_principal",
    lead_origem=None,
    nivel_rede=0,
    pontuacao=0
):

    chave_local = (
        linkedin
        or instagram
        or normalizar(nome)
    )

    if chave_local in salvos_execucao:

        return False

    existente = ja_existe(
        nome=nome,
        instagram=instagram,
        linkedin=linkedin
    )

    if existente is True:

        stats[
            "duplicados"
        ] += 1

        salvos_execucao.add(
            chave_local
        )

        return False

    if existente is None:

        return False

    dados = {

        "nome":
            nome[:150],

        "instagram":
            instagram,

        "linkedin":
            linkedin,

        "whatsapp":
            None,

        "nicho":
            "nutricionista",

        "origem":
            "busca_web_publica",

        "origem_lead":
            origem_lead,

        "lead_origem":
            lead_origem,

        "nivel_rede":
            nivel_rede,

        "rede_processada":
            False,

        "status":
            "novo",

        "app_baixado":
            False,

        "nao_contatar":
            False,

        "qualificado":
            True,

        "cliente":
            False,

        "tentativas_contato":
            0,

        "cidade":
            faculdade["cidade"],

        "estado":
            faculdade["estado"],

        "instituicao":
            faculdade["nome"],

        "ano_alvo":
            ano,

        "periodo_alvo":
            periodo,

        "pontuacao":
            pontuacao,

        "evidencia":
            evidencia[:1000],

        "fonte_url":
            fonte_url,

        "fonte_validacao":
            "web pública indexada",
    }

    try:

        (
            supabase
            .table("leds")
            .insert(dados)
            .execute()
        )

        stats[
            "salvos"
        ] += 1

        salvos_execucao.add(
            chave_local
        )

        print("")
        print(
            f"      ✅ LEAD SALVO"
        )

        print(
            f"         Nome: "
            f"{nome}"
        )

        print(
            f"         Faculdade: "
            f"{faculdade['sigla']}"
        )

        print(
            f"         Ano: "
            f"{ano}"
        )

        if periodo:

            print(
                f"         Fase: "
                f"{periodo}"
            )

        if linkedin:

            print(
                f"         LinkedIn: "
                f"{linkedin}"
            )

        if instagram:

            print(
                f"         Instagram: "
                f"{instagram}"
            )

        return True

    except Exception as erro:

        print(
            f"      ❌ Erro salvando "
            f"{nome}: {erro}"
        )

        stats["erros"] += 1

        return False


# ============================================================
# ENRIQUECER CANDIDATO
# ============================================================

def enriquecer_candidato(
    ddgs,
    nome,
    faculdade
):

    textos = []

    instagram = None
    linkedin = None

    melhor_url = None

    consultas = [

        (
            f'"{nome}" '
            f'"{faculdade["sigla"]}" '
            f'"Nutrição"'
        ),

        (
            f'"{nome}" '
            f'"Nutrição" '
            f'"2026"'
        ),

        (
            f'"{nome}" '
            f'"Nutrição" '
            f'"2025"'
        ),

        (
            f'site:linkedin.com/in '
            f'"{nome}" '
            f'"Nutrição"'
        ),

        (
            f'site:instagram.com '
            f'"{nome}" '
            f'"Nutrição"'
        ),
    ]

    for consulta in consultas:

        resultados = pesquisar(
            ddgs,
            consulta
        )

        for resultado in resultados:

            titulo = (
                resultado.get("title")
                or ""
            )

            corpo = (
                resultado.get("body")
                or ""
            )

            url = (
                resultado.get("href")
                or result.get("url")
                if False else
                resultado.get("href")
                or resultado.get("url")
                or ""
            )

            texto = (
                f"{titulo} "
                f"{corpo}"
            )

            textos.append(
                texto
            )

            tipo, valor = extrair_rede(
                url
            )

            if (
                tipo == "linkedin"
                and not linkedin
            ):

                linkedin = valor

                melhor_url = url

            if (
                tipo == "instagram"
                and not instagram
            ):

                instagram = valor

                if not melhor_url:

                    melhor_url = url

        pausa()

    texto_total = " ".join(
        textos
    )

    return {
        "texto":
            texto_total,

        "instagram":
            instagram,

        "linkedin":
            linkedin,

        "url":
            melhor_url,
    }


# ============================================================
# PROCESSAR UM RESULTADO
# ============================================================

def processar_resultado(
    ddgs,
    resultado,
    faculdade,
    origem_lead="busca_principal",
    lead_origem=None,
    nivel_rede=0
):

    titulo = (
        resultado.get("title")
        or ""
    )

    corpo = (
        resultado.get("body")
        or ""
    )

    url = (
        resultado.get("href")
        or resultado.get("url")
        or ""
    )

    texto_inicial = (
        f"{titulo} "
        f"{corpo}"
    )

    stats[
        "resultados"
    ] += 1

    nome = extrair_nome(
        titulo
    )

    if len(nome) < 4:

        return None

    chave = normalizar(
        nome
    )

    if chave in vistos:

        return None

    vistos.add(
        chave
    )

    stats[
        "candidatos"
    ] += 1

    tipo, valor = extrair_rede(
        url
    )

    linkedin = (
        valor
        if tipo == "linkedin"
        else None
    )

    instagram = (
        valor
        if tipo == "instagram"
        else None
    )

    if conta_institucional(
        nome,
        texto_inicial,
        instagram
    ):

        stats[
            "institucionais"
        ] += 1

        return None

    # --------------------------------------------------------
    # ENRIQUECIMENTO
    # --------------------------------------------------------

    enriquecido = enriquecer_candidato(
        ddgs,
        nome,
        faculdade
    )

    texto_total = (
        texto_inicial
        + " "
        + enriquecido["texto"]
    )

    if enriquecido["linkedin"]:

        linkedin = (
            enriquecido[
                "linkedin"
            ]
        )

    if enriquecido["instagram"]:

        instagram = (
            enriquecido[
                "instagram"
            ]
        )

    fonte_url = (
        enriquecido["url"]
        or url
    )

    # --------------------------------------------------------
    # PRECISA SER NUTRIÇÃO
    # --------------------------------------------------------

    if not prova_nutricao(
        texto_total
    ):

        stats[
            "rejeitados_nicho"
        ] += 1

        return None

    # --------------------------------------------------------
    # SOMENTE 2025 / 2026
    # --------------------------------------------------------

    ano = identificar_ano_alvo(
        texto_total
    )

    if ano not in [
        2025,
        2026
    ]:

        stats[
            "rejeitados_ano"
        ] += 1

        return None

    periodo = identificar_periodo(
        texto_total
    )

    pontos = pontuar(
        texto_total,
        faculdade,
        ano,
        periodo
    )

    if pontos < PONTUACAO_MINIMA:

        return None

    stats[
        "qualificados"
    ] += 1

    evidencia = (
        f"Nutrição | "
        f"{ano}"
    )

    if periodo:

        evidencia += (
            f" | {periodo}"
        )

    evidencia += (
        f" | {faculdade['sigla']}"
    )

    sucesso = salvar(

        nome=nome,

        faculdade=faculdade,

        ano=ano,

        periodo=periodo,

        evidencia=evidencia,

        fonte_url=fonte_url,

        instagram=instagram,

        linkedin=linkedin,

        origem_lead=origem_lead,

        lead_origem=lead_origem,

        nivel_rede=nivel_rede,

        pontuacao=pontos
    )

    if not sucesso:

        return None

    return {

        "nome":
            nome,

        "ano":
            ano,

        "instagram":
            instagram,

        "linkedin":
            linkedin,

        "faculdade":
            faculdade,
    }


# ============================================================
# CONSULTAS PRINCIPAIS DA FACULDADE
# ============================================================

def consultas_faculdade(
    faculdade
):

    ref = (
        faculdade["sigla"]
    )

    return [

        (
            f'site:linkedin.com/in '
            f'"{ref}" '
            f'"Nutrição" '
            f'"2026"'
        ),

        (
            f'site:linkedin.com/in '
            f'"{ref}" '
            f'"Nutrição" '
            f'"2025"'
        ),

        (
            f'site:linkedin.com/in '
            f'"{ref}" '
            f'"formanda" '
            f'"Nutrição"'
        ),

        (
            f'site:linkedin.com/in '
            f'"{ref}" '
            f'"último período" '
            f'"Nutrição"'
        ),

        (
            f'site:linkedin.com/in '
            f'"{ref}" '
            f'"TCC" '
            f'"Nutrição" '
            f'"2026"'
        ),

        (
            f'site:instagram.com '
            f'"{ref}" '
            f'"Nutrição" '
            f'"2026"'
        ),

        (
            f'"{ref}" '
            f'"Nutrição" '
            f'"formatura" '
            f'"2025"'
        ),

        (
            f'"{ref}" '
            f'"Nutrição" '
            f'"TCC" '
            f'"2026"'
        ),
    ]


# ============================================================
# EXPANSÃO POR REDE
# ============================================================

def expandir_rede(
    ddgs,
    lead
):

    if not lead:

        return

    if (
        lead["nome"]
        in expandidos_execucao
    ):

        return

    expandidos_execucao.add(
        lead["nome"]
    )

    faculdade = (
        lead["faculdade"]
    )

    ano = (
        lead["ano"]
    )

    nome_origem = (
        lead["nome"]
    )

    print("")
    print(
        f"      🌐 EXPANSÃO DE REDE:"
    )

    print(
        f"         Origem: "
        f"{nome_origem}"
    )

    # --------------------------------------------------------
    # Não tenta acessar seguidores privados.
    # Procura colegas públicos da mesma rede acadêmica.
    # --------------------------------------------------------

    consultas = [

        (
            f'site:linkedin.com/in '
            f'"{faculdade["sigla"]}" '
            f'"Nutrição" '
            f'"{ano}" '
            f'"TCC"'
        ),

        (
            f'site:linkedin.com/in '
            f'"{faculdade["sigla"]}" '
            f'"Nutrição" '
            f'"{ano}" '
            f'"formanda"'
        ),

        (
            f'"{faculdade["sigla"]}" '
            f'"Nutrição" '
            f'"{ano}" '
            f'"{nome_origem}"'
        ),

        (
            f'site:instagram.com '
            f'"{faculdade["sigla"]}" '
            f'"Nutrição" '
            f'"{ano}"'
        ),
    ]

    novos = 0

    for consulta in consultas:

        if (
            novos
            >= MAX_EXPANSAO_POR_LEAD
        ):

            break

        resultados = pesquisar(
            ddgs,
            consulta
        )

        for resultado in resultados:

            if (
                novos
                >= MAX_EXPANSAO_POR_LEAD
            ):

                break

            novo = processar_resultado(

                ddgs=ddgs,

                resultado=resultado,

                faculdade=faculdade,

                origem_lead=
                    "expansao_rede",

                lead_origem=
                    nome_origem,

                nivel_rede=1
            )

            if novo:

                novos += 1

                stats[
                    "expansoes"
                ] += 1

        pausa()

    print(
        f"         Novos leads: "
        f"{novos}"
    )


# ============================================================
# PROCESSAR FACULDADE
# ============================================================

def processar_faculdade(
    ddgs,
    faculdade
):

    print("")
    print(
        "================================================="
    )

    print(
        f"🏫 {faculdade['nome']}"
    )

    print(
        f"📍 {faculdade['cidade']}/"
        f"{faculdade['estado']}"
    )

    print(
        "🎯 Somente 2025 e 2026"
    )

    print(
        "================================================="
    )

    stats[
        "faculdades"
    ] += 1

    leads_faculdade = []

    consultas = consultas_faculdade(
        faculdade
    )

    for numero, consulta in enumerate(
        consultas,
        start=1
    ):

        if (
            len(leads_faculdade)
            >= MAX_LEADS_PRINCIPAIS_POR_FACULDADE
        ):

            break

        print("")
        print(
            f"   Pesquisa principal "
            f"{numero}/"
            f"{len(consultas)}"
        )

        resultados = pesquisar(
            ddgs,
            consulta
        )

        for resultado in resultados:

            if (
                len(leads_faculdade)
                >= MAX_LEADS_PRINCIPAIS_POR_FACULDADE
            ):

                break

            lead = processar_resultado(

                ddgs=ddgs,

                resultado=resultado,

                faculdade=faculdade,

                origem_lead=
                    "busca_principal",

                lead_origem=
                    None,

                nivel_rede=0
            )

            if lead:

                leads_faculdade.append(
                    lead
                )

        pausa()

    print("")
    print(
        f"   ✅ Leads principais "
        f"encontrados nesta faculdade: "
        f"{len(leads_faculdade)}"
    )

    # --------------------------------------------------------
    # EXPANSÃO
    # --------------------------------------------------------

    for lead in leads_faculdade:

        expandir_rede(
            ddgs,
            lead
        )


# ============================================================
# EXECUTAR
# ============================================================

def executar():

    print("")
    print(
        "================================================="
    )

    print(
        "MÁQUINA DE LEADS - TESTE 2025/2026"
    )

    print(
        "================================================="
    )

    print(
        "Nutrição"
    )

    print(
        "LinkedIn + Instagram + Web pública"
    )

    print(
        "Busca principal + expansão por rede"
    )

    print(
        "================================================="
    )

    with DDGS() as ddgs:

        for indice, faculdade in enumerate(
            FACULDADES[:MAX_FACULDADES_POR_EXECUCAO],
            start=1
        ):

            print("")
            print(
                f"FACULDADE "
                f"{indice}/"
                f"{min(MAX_FACULDADES_POR_EXECUCAO, len(FACULDADES))}"
            )

            processar_faculdade(
                ddgs,
                faculdade
            )


# ============================================================
# INÍCIO
# ============================================================

executar()


# ============================================================
# RESUMO
# ============================================================

print("")
print(
    "================================================="
)

print(
    "RESUMO FINAL"
)

print(
    "================================================="
)

print(
    f"Faculdades processadas: "
    f"{stats['faculdades']}"
)

print(
    f"Buscas realizadas: "
    f"{stats['buscas']}"
)

print(
    f"Resultados analisados: "
    f"{stats['resultados']}"
)

print(
    f"Candidatos encontrados: "
    f"{stats['candidatos']}"
)

print(
    f"Qualificados 2025/2026: "
    f"{stats['qualificados']}"
)

print(
    f"Leads salvos: "
    f"{stats['salvos']}"
)

print(
    f"Leads vindos de expansão: "
    f"{stats['expansoes']}"
)

print(
    f"Duplicados: "
    f"{stats['duplicados']}"
)

print(
    f"Rejeitados por ano: "
    f"{stats['rejeitados_ano']}"
)

print(
    f"Rejeitados por nicho: "
    f"{stats['rejeitados_nicho']}"
)

print(
    f"Institucionais rejeitados: "
    f"{stats['institucionais']}"
)

print(
    f"Erros: "
    f"{stats['erros']}"
)

print(
    "================================================="
)

print(
    "TESTE CONCLUÍDO"
)

print(
    "================================================="
)
