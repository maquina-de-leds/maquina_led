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
# MÁQUINA DE LEADS - NUTRIÇÃO
# 1 FACULDADE POR EXECUÇÃO
# SOMENTE 2025 / 2026
#
# REGRA PRINCIPAL:
#
# Faculdade atual
#      ↓
# busca direcionada
#      ↓
# achou pessoa de Nutrição?
#      ↓
# SALVA IMEDIATAMENTE
#      ↓
# continua procurando
#      ↓
# terminou faculdade
#      ↓
# próxima execução = próxima faculdade
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
# FACULDADES JÁ VALIDADAS
# ============================================================

FACULDADES = [

    # SÃO PAULO
    {
        "nome": "Universidade Presbiteriana Mackenzie",
        "sigla": "Mackenzie",
        "cidade": "São Paulo",
        "estado": "SP",
    },

    {
        "nome": "Universidade Paulista",
        "sigla": "UNIP",
        "cidade": "São Paulo",
        "estado": "SP",
    },

    {
        "nome": "PUC-Campinas",
        "sigla": "PUC Campinas",
        "cidade": "Campinas",
        "estado": "SP",
    },

    {
        "nome": "Universidade Anhembi Morumbi",
        "sigla": "Anhembi Morumbi",
        "cidade": "São Paulo",
        "estado": "SP",
    },

    {
        "nome": "Universidade Nove de Julho",
        "sigla": "UNINOVE",
        "cidade": "São Paulo",
        "estado": "SP",
    },

    {
        "nome": "Faculdade Santa Marcelina",
        "sigla": "Santa Marcelina",
        "cidade": "São Paulo",
        "estado": "SP",
    },

    {
        "nome": "Centro Universitário São Camilo",
        "sigla": "São Camilo",
        "cidade": "São Paulo",
        "estado": "SP",
    },

    {
        "nome": "Universidade de Sorocaba",
        "sigla": "UNISO",
        "cidade": "Sorocaba",
        "estado": "SP",
    },

    {
        "nome": "Universidade de Ribeirão Preto",
        "sigla": "UNAERP",
        "cidade": "Ribeirão Preto",
        "estado": "SP",
    },

    {
        "nome": "Universidade de São Paulo",
        "sigla": "USP",
        "cidade": "São Paulo",
        "estado": "SP",
    },


    # MINAS GERAIS
    {
        "nome": "Universidade Federal de Viçosa",
        "sigla": "UFV",
        "cidade": "Viçosa",
        "estado": "MG",
    },

    {
        "nome": "Pontifícia Universidade Católica de Minas Gerais",
        "sigla": "PUC Minas",
        "cidade": "Belo Horizonte",
        "estado": "MG",
    },


    # RIO DE JANEIRO
    {
        "nome": "Universidade Federal do Rio de Janeiro",
        "sigla": "UFRJ",
        "cidade": "Rio de Janeiro",
        "estado": "RJ",
    },

    {
        "nome": "Universidade Federal do Estado do Rio de Janeiro",
        "sigla": "UNIRIO",
        "cidade": "Rio de Janeiro",
        "estado": "RJ",
    },

    {
        "nome": "Universidade do Estado do Rio de Janeiro",
        "sigla": "UERJ",
        "cidade": "Rio de Janeiro",
        "estado": "RJ",
    },

    {
        "nome": "Universidade Estácio de Sá",
        "sigla": "Estácio",
        "cidade": "Rio de Janeiro",
        "estado": "RJ",
    },


    # BAHIA
    {
        "nome": "Universidade Salvador",
        "sigla": "UNIFACS",
        "cidade": "Salvador",
        "estado": "BA",
    },

    {
        "nome": "Centro Universitário Jorge Amado",
        "sigla": "UNIJORGE",
        "cidade": "Salvador",
        "estado": "BA",
    },

    {
        "nome": "Universidade Federal da Bahia",
        "sigla": "UFBA",
        "cidade": "Salvador",
        "estado": "BA",
    },
]


# ============================================================
# CONFIGURAÇÃO
# ============================================================

MAX_RESULTADOS = 20
MAX_TENTATIVAS = 2

PAUSA_MIN = 5
PAUSA_MAX = 8

ETAPA_CHECKPOINT = "captacao_faculdades_2025_2026"


# ============================================================
# ESTATÍSTICAS
# ============================================================

stats = {
    "buscas": 0,
    "resultados": 0,
    "candidatos": 0,
    "validos": 0,
    "salvos": 0,
    "duplicados": 0,
    "rejeitados_nome": 0,
    "rejeitados_nutricao": 0,
    "institucionais": 0,
    "erros": 0,
}


vistos_execucao = set()


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
# CHECKPOINT
# ============================================================

def buscar_checkpoint():

    try:

        resposta = (
            supabase
            .table("controle_busca")
            .select("*")
            .eq(
                "etapa",
                ETAPA_CHECKPOINT
            )
            .limit(1)
            .execute()
        )

        if resposta.data:
            return resposta.data[0]

        return None

    except Exception as erro:

        print(
            f"⚠️ Erro lendo checkpoint: {erro}"
        )

        return None


def obter_indice_faculdade():

    checkpoint = buscar_checkpoint()

    if not checkpoint:
        return 0

    indice = checkpoint.get(
        "indice_pesquisa"
    )

    if indice is None:
        return 0

    return int(indice)


def salvar_checkpoint(
    indice,
    faculdade,
    status
):

    atual = buscar_checkpoint()

    dados = {
        "estado":
            faculdade["estado"],

        "cidade":
            faculdade["cidade"],

        "instituicao":
            faculdade["nome"],

        "etapa":
            ETAPA_CHECKPOINT,

        "status":
            status,

        "indice_pesquisa":
            indice,

        "total_pesquisas":
            len(FACULDADES),

        "consulta_atual":
            faculdade["nome"],

        "fonte_atual":
            "busca_web_publica",

        "atualizado_em":
            agora(),
    }

    if not atual:
        dados["iniciado_em"] = agora()

    try:

        if atual:

            (
                supabase
                .table("controle_busca")
                .update(dados)
                .eq(
                    "id",
                    atual["id"]
                )
                .execute()
            )

        else:

            (
                supabase
                .table("controle_busca")
                .insert(dados)
                .execute()
            )

        return True

    except Exception as erro:

        print(
            f"⚠️ Erro salvando checkpoint: {erro}"
        )

        stats["erros"] += 1

        return False


# ============================================================
# BUSCA
# ============================================================

def pesquisar(
    ddgs,
    consulta
):

    stats["buscas"] += 1

    print("")
    print(
        f"🔎 {consulta}"
    )

    for tentativa in range(
        1,
        MAX_TENTATIVAS + 1
    ):

        try:

            resultados = list(
                ddgs.text(
                    consulta,
                    max_results=MAX_RESULTADOS
                )
            )

            return resultados

        except Exception as erro:

            mensagem = str(erro)

            if "No results found" in mensagem:

                return []

            print(
                f"⚠️ Tentativa "
                f"{tentativa}/"
                f"{MAX_TENTATIVAS}: "
                f"{mensagem}"
            )

            if tentativa < MAX_TENTATIVAS:

                time.sleep(12)

    stats["erros"] += 1

    return []


# ============================================================
# CONSULTAS
#
# AGORA TODAS JÁ LEVAM:
# - faculdade
# - Nutrição
# - 2025 OU 2026
#
# Portanto faculdade e ano fazem parte
# da evidência da própria consulta.
# ============================================================

def montar_consultas(
    faculdade
):

    sigla = faculdade["sigla"]

    return [

        {
            "consulta": (
                f'site:linkedin.com/in '
                f'"{sigla}" '
                f'"Nutrição" '
                f'"2026"'
            ),
            "ano": 2026,
            "fase": None,
        },

        {
            "consulta": (
                f'site:linkedin.com/in '
                f'"{sigla}" '
                f'"Nutrição" '
                f'"2025"'
            ),
            "ano": 2025,
            "fase": None,
        },

        {
            "consulta": (
                f'site:linkedin.com/in '
                f'"{sigla}" '
                f'"formanda" '
                f'"Nutrição" '
                f'"2026"'
            ),
            "ano": 2026,
            "fase": "formando",
        },

        {
            "consulta": (
                f'site:linkedin.com/in '
                f'"{sigla}" '
                f'"formando" '
                f'"Nutrição" '
                f'"2026"'
            ),
            "ano": 2026,
            "fase": "formando",
        },

        {
            "consulta": (
                f'site:linkedin.com/in '
                f'"{sigla}" '
                f'"TCC" '
                f'"Nutrição" '
                f'"2026"'
            ),
            "ano": 2026,
            "fase": "TCC",
        },

        {
            "consulta": (
                f'site:linkedin.com/in '
                f'"{sigla}" '
                f'"último período" '
                f'"Nutrição" '
                f'"2026"'
            ),
            "ano": 2026,
            "fase": "último período",
        },

        {
            "consulta": (
                f'site:instagram.com '
                f'"{sigla}" '
                f'"Nutrição" '
                f'"2026"'
            ),
            "ano": 2026,
            "fase": None,
        },

        {
            "consulta": (
                f'site:instagram.com '
                f'"{sigla}" '
                f'"Nutrição" '
                f'"2025"'
            ),
            "ano": 2025,
            "fase": None,
        },
    ]


# ============================================================
# IDENTIFICAR REDE
# ============================================================

def identificar_rede(
    url
):

    if not url:
        return None, None

    try:

        parsed = urlparse(url)

        dominio = (
            parsed.netloc
            .lower()
            .replace("www.", "")
        )

        # LINKEDIN DE PESSOA
        if (
            "linkedin.com"
            in dominio
            and "/in/"
            in parsed.path
        ):

            return (
                "linkedin",
                url
            )

        # INSTAGRAM
        if "instagram.com" in dominio:

            partes = [
                parte
                for parte
                in parsed.path.split("/")
                if parte
            ]

            if not partes:

                return None, None

            usuario = partes[0].lower()

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

                return None, None

            if re.match(
                r"^[a-zA-Z0-9._]+$",
                usuario
            ):

                return (
                    "instagram",
                    "@"
                    + usuario
                )

    except Exception:

        pass

    return None, None


# ============================================================
# EXTRAIR NOME
# ============================================================

def extrair_nome(
    titulo,
    tipo
):

    if not titulo:
        return ""

    nome = titulo.strip()

    if tipo == "linkedin":

        nome = re.sub(
            r"\s*[\|\-–—]\s*LinkedIn.*$",
            "",
            nome,
            flags=re.I
        )

        nome = re.sub(
            r"\s*[\|\-–—].*$",
            "",
            nome
        )

    elif tipo == "instagram":

        # Exemplo:
        # Maria Silva (@maria.nutri) • Instagram
        nome = re.sub(
            r"\s*\(@[^)]+\).*$",
            "",
            nome
        )

        nome = re.sub(
            r"\s*[\|\-–—•].*$",
            "",
            nome
        )

    nome = re.sub(
        r"\s+",
        " ",
        nome
    )

    return nome.strip()


# ============================================================
# NOME PARECE PESSOA?
# ============================================================

def nome_parece_pessoa(
    nome
):

    if not nome:

        return False

    if len(nome) < 4:

        return False

    if len(nome) > 80:

        return False

    palavras = nome.split()

    if len(palavras) < 2:

        return False

    texto = normalizar(nome)

    proibidos = [
        "universidade",
        "faculdade",
        "centro universitario",
        "curso de nutricao",
        "nutricao mackenzie",
        "limited",
        "ltda",
        "company",
        "empresa",
        "turma",
        "formatura",
        "comissao",
        "atletica",
        "instituto",
        "escola",
        "departamento",
    ]

    if any(
        termo in texto
        for termo in proibidos
    ):

        return False

    # Bloqueia títulos estranhos/idiomas aleatórios
    caracteres_invalidos = re.sub(
        r"[A-Za-zÀ-ÿ'´`\-\s.]",
        "",
        nome
    )

    if len(caracteres_invalidos) > 2:

        return False

    return True


# ============================================================
# NUTRIÇÃO
# ============================================================

def tem_sinal_nutricao(
    texto,
    nome,
    instagram
):

    t = normalizar(texto)
    n = normalizar(nome)
    i = normalizar(instagram)

    sinais_fortes = [
        "nutricao",
        "nutricionista",
        "nutrition",
        "graduanda em nutricao",
        "graduando em nutricao",
        "estudante de nutricao",
        "formanda em nutricao",
        "formando em nutricao",
        "bacharel em nutricao",
        "nutri ",
        " nutri",
    ]

    if any(
        sinal in t
        for sinal in sinais_fortes
    ):
        return True

    if "nutri" in n:
        return True

    if instagram and "nutri" in i:
        return True

    return False


# ============================================================
# PERFIL INSTITUCIONAL
# ============================================================

def perfil_institucional(
    nome,
    instagram
):

    nome_norm = normalizar(nome)
    insta_norm = normalizar(instagram)

    termos_nome = [
        "universidade",
        "faculdade",
        "curso de nutricao",
        "nutricao mackenzie",
        "turma",
        "formatura",
        "comissao",
        "atletica",
        "centro academico",
        "liga academica",
        "departamento",
    ]

    if any(
        termo in nome_norm
        for termo in termos_nome
    ):
        return True

    termos_handle = [
        "nutricao_",
        "nutricao.",
        "turmanutri",
        "formaturan",
        "atletica",
        "comissao",
        "centroacademico",
    ]

    if instagram:

        if any(
            termo in insta_norm
            for termo in termos_handle
        ):
            return True

    return False


# ============================================================
# IDENTIFICAR FASE PELO RESULTADO
# ============================================================

def identificar_fase_resultado(
    texto,
    fase_consulta
):

    t = normalizar(texto)

    regras = [

        (
            [
                "recem-formada",
                "recem formada",
                "recem-formado",
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
            ],
            "estágio final"
        ),

        (
            [
                "formatura",
                "colacao",
                "conclusao",
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

    return fase_consulta


# ============================================================
# DUPLICIDADE
# ============================================================

def existe_no_supabase(
    nome,
    linkedin,
    instagram,
    faculdade
):

    try:

        if linkedin:

            resposta = (
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

            if resposta.data:
                return True

        if instagram:

            resposta = (
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

            if resposta.data:
                return True

        resposta = (
            supabase
            .table("leds")
            .select("id")
            .eq(
                "instituicao",
                faculdade["nome"]
            )
            .ilike(
                "nome",
                nome
            )
            .limit(1)
            .execute()
        )

        if resposta.data:
            return True

        return False

    except Exception as erro:

        print(
            f"⚠️ Erro verificando duplicidade: "
            f"{erro}"
        )

        # dúvida = não salva
        return None


# ============================================================
# SALVAR IMEDIATAMENTE
# ============================================================

def salvar_lead(
    nome,
    faculdade,
    ano,
    fase,
    linkedin,
    instagram,
    fonte_url,
    consulta
):

    existente = existe_no_supabase(
        nome,
        linkedin,
        instagram,
        faculdade
    )

    if existente is True:

        stats["duplicados"] += 1

        print(
            f"♻️ Duplicado ignorado: {nome}"
        )

        return False

    if existente is None:
        return False

    evidencia = (
        f"Nutrição | "
        f"{faculdade['sigla']} | "
        f"{ano}"
    )

    if fase:

        evidencia += (
            f" | {fase}"
        )

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
            "captacao_web_publica",

        "origem_lead":
            "busca_principal",

        "lead_origem":
            None,

        "nivel_rede":
            0,

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
            fase,

        "pontuacao":
            10,

        "evidencia":
            evidencia,

        "fonte_url":
            fonte_url,

        "fonte_validacao":
            consulta,
    }

    try:

        (
            supabase
            .table("leds")
            .insert(dados)
            .execute()
        )

        stats["salvos"] += 1

        print("")
        print(
            "✅ LEAD SALVO NA HORA"
        )

        print(
            f"   Nome: {nome}"
        )

        print(
            f"   Faculdade: "
            f"{faculdade['sigla']}"
        )

        print(
            f"   Ano: {ano}"
        )

        if fase:

            print(
                f"   Fase: {fase}"
            )

        if linkedin:

            print(
                f"   LinkedIn: {linkedin}"
            )

        if instagram:

            print(
                f"   Instagram: {instagram}"
            )

        print("")

        return True

    except Exception as erro:

        print(
            f"❌ Erro salvando {nome}: "
            f"{erro}"
        )

        stats["erros"] += 1

        return False


# ============================================================
# PROCESSAR RESULTADO
# ============================================================

def processar_resultado(
    resultado,
    faculdade,
    contexto_busca
):

    stats["resultados"] += 1

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

    tipo, rede = identificar_rede(
        url
    )

    if tipo is None:
        return False

    nome = extrair_nome(
        titulo,
        tipo
    )

    if not nome_parece_pessoa(
        nome
    ):

        stats[
            "rejeitados_nome"
        ] += 1

        return False

    instagram = None
    linkedin = None

    if tipo == "linkedin":
        linkedin = rede

    elif tipo == "instagram":
        instagram = rede

    if perfil_institucional(
        nome,
        instagram
    ):

        stats[
            "institucionais"
        ] += 1

        return False

    texto_resultado = (
        f"{titulo} "
        f"{corpo}"
    )

    # --------------------------------------------------------
    # ÚNICA VALIDAÇÃO FORTE NO RESULTADO:
    # TEM QUE EXISTIR SINAL DE NUTRIÇÃO.
    #
    # Faculdade e ano já vieram da consulta.
    # --------------------------------------------------------

    if not tem_sinal_nutricao(
        texto_resultado,
        nome,
        instagram
    ):

        stats[
            "rejeitados_nutricao"
        ] += 1

        return False

    chave = (
        normalizar(nome)
        + "|"
        + faculdade["sigla"]
    )

    if chave in vistos_execucao:
        return False

    vistos_execucao.add(
        chave
    )

    ano = contexto_busca["ano"]

    fase = identificar_fase_resultado(
        texto_resultado,
        contexto_busca["fase"]
    )

    stats["candidatos"] += 1
    stats["validos"] += 1

    # --------------------------------------------------------
    # SALVA IMEDIATAMENTE
    # --------------------------------------------------------

    return salvar_lead(
        nome=nome,
        faculdade=faculdade,
        ano=ano,
        fase=fase,
        linkedin=linkedin,
        instagram=instagram,
        fonte_url=url,
        consulta=contexto_busca[
            "consulta"
        ]
    )


# ============================================================
# EXECUTAR UMA FACULDADE
# ============================================================

def executar_faculdade(
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
        "🎯 SOMENTE 2025 / 2026"
    )

    print(
        "💾 Achou lead = salva imediatamente"
    )

    print(
        "================================================="
    )

    consultas = montar_consultas(
        faculdade
    )

    for numero, contexto in enumerate(
        consultas,
        start=1
    ):

        print("")
        print(
            f"Pesquisa "
            f"{numero}/"
            f"{len(consultas)}"
        )

        resultados = pesquisar(
            ddgs,
            contexto["consulta"]
        )

        for resultado in resultados:

            processar_resultado(
                resultado,
                faculdade,
                contexto
            )

        pausa()


# ============================================================
# EXECUTAR
# ============================================================

def executar():

    indice = obter_indice_faculdade()

    if indice >= len(FACULDADES):

        print("")
        print(
            "✅ TODAS AS FACULDADES "
            "FORAM PROCESSADAS."
        )

        return

    faculdade = FACULDADES[
        indice
    ]

    print("")
    print(
        "================================================="
    )

    print(
        "MÁQUINA DE LEADS"
    )

    print(
        "NUTRIÇÃO - 2025 / 2026"
    )

    print(
        "================================================="
    )

    print(
        f"Faculdade "
        f"{indice + 1}/"
        f"{len(FACULDADES)}"
    )

    salvar_checkpoint(
        indice,
        faculdade,
        "processando"
    )

    with DDGS() as ddgs:

        executar_faculdade(
            ddgs,
            faculdade
        )

    proximo_indice = (
        indice + 1
    )

    salvar_checkpoint(
        proximo_indice,
        faculdade,
        "pendente"
    )

    print("")
    print(
        "================================================="
    )

    print(
        "✅ FACULDADE CONCLUÍDA"
    )

    if proximo_indice < len(
        FACULDADES
    ):

        proxima = FACULDADES[
            proximo_indice
        ]

        print(
            f"Próxima: "
            f"{proxima['nome']}"
        )

    else:

        print(
            "Todas as faculdades "
            "foram concluídas."
        )

    print(
        "================================================="
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
    "RESUMO DA EXECUÇÃO"
)

print(
    "================================================="
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
    f"Candidatos de pessoa: "
    f"{stats['candidatos']}"
)

print(
    f"Leads válidos: "
    f"{stats['validos']}"
)

print(
    f"Leads salvos: "
    f"{stats['salvos']}"
)

print(
    f"Duplicados: "
    f"{stats['duplicados']}"
)

print(
    f"Rejeitados por nome: "
    f"{stats['rejeitados_nome']}"
)

print(
    f"Rejeitados sem sinal de Nutrição: "
    f"{stats['rejeitados_nutricao']}"
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
