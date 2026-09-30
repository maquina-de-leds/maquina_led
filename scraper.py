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
# MÁQUINA DE LEADS - CAPTAÇÃO RÁPIDA
# ============================================================
#
# REGRA:
#
# 1 faculdade por execução
#
# encontrou lead válido
#       ↓
# SALVA IMEDIATAMENTE
#       ↓
# continua procurando
#       ↓
# terminou faculdade
#       ↓
# checkpoint
#       ↓
# próxima execução = próxima faculdade
#
# FILTRO:
# SOMENTE NUTRIÇÃO
# SOMENTE 2025 / 2026
#
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

PAUSA_MIN = 6
PAUSA_MAX = 10


# ============================================================
# ESTATÍSTICAS
# ============================================================

stats = {
    "buscas": 0,
    "resultados": 0,
    "validos": 0,
    "salvos": 0,
    "duplicados": 0,
    "rejeitados": 0,
    "institucionais": 0,
    "erros": 0,
}


vistos = set()


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

ETAPA_CHECKPOINT = "captacao_faculdades_2025_2026"


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
            f"⚠️ Erro lendo checkpoint: "
            f"{erro}"
        )

        return None


def obter_indice_faculdade():

    checkpoint = buscar_checkpoint()

    if not checkpoint:

        return 0

    indice = (
        checkpoint.get(
            "indice_pesquisa"
        )
        or 0
    )

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

    if status == "concluido":

        dados["finalizado_em"] = agora()

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
            f"⚠️ Erro salvando checkpoint: "
            f"{erro}"
        )

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
                    max_results=
                        MAX_RESULTADOS
                )
            )

            return resultados

        except Exception as erro:

            mensagem = str(
                erro
            )

            if (
                "No results found"
                in mensagem
            ):

                return []

            print(
                f"⚠️ Tentativa "
                f"{tentativa}/"
                f"{MAX_TENTATIVAS}: "
                f"{mensagem}"
            )

            if tentativa < MAX_TENTATIVAS:

                time.sleep(15)

    stats["erros"] += 1

    return []


# ============================================================
# CONSULTAS
# ============================================================

def montar_consultas(
    faculdade
):

    sigla = faculdade["sigla"]

    return [

        (
            f'site:linkedin.com/in '
            f'"{sigla}" '
            f'"Nutrição" '
            f'"2026"'
        ),

        (
            f'site:linkedin.com/in '
            f'"{sigla}" '
            f'"Nutrição" '
            f'"2025"'
        ),

        (
            f'site:linkedin.com/in '
            f'"{sigla}" '
            f'"formanda" '
            f'"Nutrição"'
        ),

        (
            f'site:linkedin.com/in '
            f'"{sigla}" '
            f'"formando" '
            f'"Nutrição"'
        ),

        (
            f'site:linkedin.com/in '
            f'"{sigla}" '
            f'"último período" '
            f'"Nutrição"'
        ),

        (
            f'site:linkedin.com/in '
            f'"{sigla}" '
            f'"TCC" '
            f'"Nutrição" '
            f'"2026"'
        ),

        (
            f'site:instagram.com '
            f'"{sigla}" '
            f'"Nutrição" '
            f'"2026"'
        ),

        (
            f'site:instagram.com '
            f'"{sigla}" '
            f'"Nutrição" '
            f'"2025"'
        ),
    ]


# ============================================================
# IDENTIFICAR REDE SOCIAL
# ============================================================

def identificar_rede(
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
        )

        # LinkedIn pessoa
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

        # Instagram
        if (
            "instagram.com"
            in dominio
        ):

            partes = [
                parte
                for parte
                in parsed.path.split("/")
                if parte
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
                "direct",
                "tv",
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
                    "@"
                    + usuario
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

    if not titulo:

        return ""

    nome = titulo.strip()

    nome = re.sub(
        r"\s*[\|\-–—]\s*LinkedIn.*$",
        "",
        nome,
        flags=re.I
    )

    nome = re.sub(
        r"\s*[\|\-–—]\s*Instagram.*$",
        "",
        nome,
        flags=re.I
    )

    nome = re.sub(
        r"\s*[\|\-–—].*$",
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
# VALIDAR NOME DE PESSOA
# ============================================================

def nome_parece_pessoa(
    nome
):

    if not nome:

        return False

    nome_limpo = nome.strip()

    # evita texto gigante
    if len(nome_limpo) > 80:

        return False

    # precisa ter pelo menos duas palavras
    palavras = nome_limpo.split()

    if len(palavras) < 2:

        return False

    texto = normalizar(
        nome_limpo
    )

    proibidos = [
        "universidade",
        "faculdade",
        "nutricao mackenzie",
        "curso de nutricao",
        "centro universitario",
        "empresa",
        "limited",
        "ltda",
        "turma",
        "comissao",
        "formatura",
        "atletica",
        "instituto",
        "escola",
    ]

    if any(
        termo in texto
        for termo in proibidos
    ):

        return False

    # evita caracteres estranhos
    caracteres_validos = re.sub(
        r"[A-Za-zÀ-ÿ'´`\-\s]",
        "",
        nome_limpo
    )

    if len(caracteres_validos) > 3:

        return False

    return True


# ============================================================
# VERIFICAR FACULDADE
# ============================================================

def tem_faculdade(
    texto,
    faculdade
):

    t = normalizar(
        texto
    )

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

        return True

    # nome completo
    if (
        nome
        and nome in t
    ):

        return True

    return False


# ============================================================
# VERIFICAR NUTRIÇÃO
# ============================================================

def tem_nutricao(
    texto
):

    t = normalizar(
        texto
    )

    sinais = [

        "nutricao",

        "nutricionista",

        "graduanda em nutricao",

        "graduando em nutricao",

        "estudante de nutricao",

        "formanda em nutricao",

        "formando em nutricao",
    ]

    return any(
        sinal in t
        for sinal in sinais
    )


# ============================================================
# IDENTIFICAR ANO
# ============================================================

def identificar_ano(
    texto
):

    t = normalizar(
        texto
    )

    # 2026 tem prioridade
    if "2026" in t:

        return 2026

    if "2025" in t:

        return 2025

    return None


# ============================================================
# FASE DO CURSO
# ============================================================

def identificar_fase(
    texto
):

    t = normalizar(
        texto
    )

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

    return None


# ============================================================
# PERFIL INSTITUCIONAL
# ============================================================

def perfil_institucional(
    nome,
    instagram
):

    n = normalizar(
        nome
    )

    i = normalizar(
        instagram
    )

    termos = [
        "nutricao mackenzie",
        "nutricao unip",
        "nutricao usp",
        "curso de nutricao",
        "faculdade",
        "universidade",
        "turma",
        "formatura",
        "comissao",
        "atletica",
    ]

    if any(
        termo in n
        for termo in termos
    ):

        return True

    handles = [
        "nutricao_",
        "nutricao.",
        "turma",
        "formatura",
        "atletica",
        "comissao",
    ]

    if instagram:

        if any(
            termo in i
            for termo in handles
        ):

            return True

    return False


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
            .select(
                "id,nome,instituicao"
            )
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
            f"⚠️ Erro verificando "
            f"duplicidade: {erro}"
        )

        # em caso de dúvida não salva
        return None


# ============================================================
# SALVAR NA HORA
# ============================================================

def salvar_lead(
    nome,
    faculdade,
    ano,
    fase,
    linkedin,
    instagram,
    fonte_url
):

    existente = existe_no_supabase(
        nome,
        linkedin,
        instagram,
        faculdade
    )

    if existente is True:

        stats[
            "duplicados"
        ] += 1

        print(
            f"♻️ Duplicado: "
            f"{nome}"
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
            "resultado público indexado",
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

        print("")
        print(
            "✅ LEAD SALVO NA HORA"
        )

        print(
            f"   Nome: "
            f"{nome}"
        )

        print(
            f"   Faculdade: "
            f"{faculdade['sigla']}"
        )

        print(
            f"   Ano: "
            f"{ano}"
        )

        if fase:

            print(
                f"   Fase: "
                f"{fase}"
            )

        if linkedin:

            print(
                f"   LinkedIn: "
                f"{linkedin}"
            )

        if instagram:

            print(
                f"   Instagram: "
                f"{instagram}"
            )

        print("")

        return True

    except Exception as erro:

        print(
            f"❌ Erro salvando lead: "
            f"{erro}"
        )

        stats["erros"] += 1

        return False


# ============================================================
# PROCESSAR RESULTADO
# ============================================================

def processar_resultado(
    resultado,
    faculdade
):

    stats[
        "resultados"
    ] += 1

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

    # Só aceitamos LinkedIn pessoa
    # ou perfil Instagram.
    if tipo is None:

        return False

    texto = (
        f"{titulo} "
        f"{corpo}"
    )

    nome = extrair_nome(
        titulo
    )

    if not nome_parece_pessoa(
        nome
    ):

        stats[
            "rejeitados"
        ] += 1

        return False

    chave = (
        normalizar(nome)
        + "|"
        + faculdade["sigla"]
    )

    if chave in vistos:

        return False

    vistos.add(
        chave
    )

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

    # --------------------------------------------------------
    # PRECISA CONTER NUTRIÇÃO
    # --------------------------------------------------------

    if not tem_nutricao(
        texto
    ):

        stats[
            "rejeitados"
        ] += 1

        return False

    # --------------------------------------------------------
    # PRECISA TER REFERÊNCIA À FACULDADE
    # --------------------------------------------------------

    if not tem_faculdade(
        texto,
        faculdade
    ):

        stats[
            "rejeitados"
        ] += 1

        return False

    # --------------------------------------------------------
    # SOMENTE 2025 OU 2026
    # --------------------------------------------------------

    ano = identificar_ano(
        texto
    )

    if ano not in [
        2025,
        2026
    ]:

        stats[
            "rejeitados"
        ] += 1

        return False

    fase = identificar_fase(
        texto
    )

    stats[
        "validos"
    ] += 1

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

        fonte_url=url
    )


# ============================================================
# EXECUÇÃO DE UMA FACULDADE
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
        f"🏫 FACULDADE:"
    )

    print(
        f"{faculdade['nome']}"
    )

    print(
        f"📍 "
        f"{faculdade['cidade']}/"
        f"{faculdade['estado']}"
    )

    print(
        "🎯 SOMENTE 2025 / 2026"
    )

    print(
        "💾 Achou lead válido = salva imediatamente"
    )

    print(
        "================================================="
    )

    consultas = montar_consultas(
        faculdade
    )

    for numero, consulta in enumerate(
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
            consulta
        )

        for resultado in resultados:

            processar_resultado(
                resultado,
                faculdade
            )

        pausa()


# ============================================================
# EXECUTAR
# ============================================================

def executar():

    indice = obter_indice_faculdade()

    # chegou ao final?
    if indice >= len(FACULDADES):

        print("")
        print(
            "✅ TODAS AS FACULDADES "
            "DO TESTE FORAM PROCESSADAS."
        )

        return

    faculdade = (
        FACULDADES[indice]
    )

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

    # marca início
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

    # --------------------------------------------------------
    # FACULDADE CONCLUÍDA
    # PRÓXIMA EXECUÇÃO IRÁ PARA A SEGUINTE
    # --------------------------------------------------------

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

    print(
        f"Próxima execução começa "
        f"na faculdade "
        f"{proximo_indice + 1}"
        if proximo_indice < len(FACULDADES)
        else
        "Todas as faculdades foram concluídas."
    )

    print(
        "================================================="
    )


# ============================================================
# INICIAR
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
    f"Buscas: "
    f"{stats['buscas']}"
)

print(
    f"Resultados analisados: "
    f"{stats['resultados']}"
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
    f"Institucionais rejeitados: "
    f"{stats['institucionais']}"
)

print(
    f"Outros rejeitados: "
    f"{stats['rejeitados']}"
)

print(
    f"Erros: "
    f"{stats['erros']}"
)

print(
    "================================================="
)
