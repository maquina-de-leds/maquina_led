import os
import re
import time
import random
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from supabase import create_client


SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


# ============================================================
# FACULDADES
# ============================================================

FACULDADES = [

    {
        "nome": "Universidade Presbiteriana Mackenzie",
        "sigla": "Mackenzie",
        "cidade": "São Paulo",
        "estado": "SP",
        "dominio": "mackenzie.br",

        "fontes_oficiais": [

            {
                "tipo": "lista_tcc",

                "url":
                    "https://www.mackenzie.br/"
                    "universidade/unidades-academicas/"
                    "ccbs/tcc-e-pesquisa/mostra-de-tcc",

                "ano": 2026,

                "fase": "TCC 2026.1",
            }

        ],
    },


    {
        "nome": "Universidade Paulista",
        "sigla": "UNIP",
        "cidade": "São Paulo",
        "estado": "SP",
        "dominio": "unip.br",
        "fontes_oficiais": [],
    },


    {
        "nome": "PUC-Campinas",
        "sigla": "PUC Campinas",
        "cidade": "Campinas",
        "estado": "SP",
        "dominio": "puc-campinas.edu.br",
        "fontes_oficiais": [],
    },


    {
        "nome": "Universidade Anhembi Morumbi",
        "sigla": "Anhembi Morumbi",
        "cidade": "São Paulo",
        "estado": "SP",
        "dominio": "anhembi.br",
        "fontes_oficiais": [],
    },


    {
        "nome": "Universidade Nove de Julho",
        "sigla": "UNINOVE",
        "cidade": "São Paulo",
        "estado": "SP",
        "dominio": "uninove.br",
        "fontes_oficiais": [],
    },

]


# ============================================================
# CONFIGURAÇÃO
# ============================================================

MAX_RESULTADOS = 20

MAX_TENTATIVAS = 2

PAUSA_MIN = 5
PAUSA_MAX = 8

ETAPA_CHECKPOINT = (
    "captacao_faculdades_2025_2026"
)


stats = {

    "fontes_oficiais": 0,

    "nomes_oficiais": 0,

    "buscas": 0,

    "resultados": 0,

    "validos": 0,

    "salvos": 0,

    "duplicados": 0,

    "rejeitados": 0,

    "erros": 0,
}


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


def nome_formatado(nome):

    palavras = nome.strip().split()

    return " ".join(
        p.capitalize()
        if len(p) > 2
        else p.lower()
        for p in palavras
    )


def pausa():

    time.sleep(
        random.uniform(
            PAUSA_MIN,
            PAUSA_MAX
        )
    )


# ============================================================
# NOME PARECE PESSOA?
# ============================================================

def nome_parece_pessoa(nome):

    if not nome:

        return False

    if len(nome) < 5:

        return False

    if len(nome) > 90:

        return False

    palavras = nome.split()

    if len(palavras) < 2:

        return False

    if len(palavras) > 8:

        return False

    proibidos = [

        "universidade",

        "faculdade",

        "centro universitario",

        "curso",

        "nutricao",

        "turma",

        "formatura",

        "comissao",

        "atletica",

        "instituto",

        "escola",

        "limited",

        "company",

        "ltda",
    ]

    n = normalizar(nome)

    if any(
        termo in n
        for termo in proibidos
    ):

        return False

    estranhos = re.sub(
        r"[A-Za-zÀ-ÿ'´`\-\s.]",
        "",
        nome
    )

    if len(estranhos) > 2:

        return False

    return True


# ============================================================
# SOCIAL
# ============================================================

def perfil_social(url):

    if not url:

        return None, None

    try:

        parsed = urlparse(url)

        host = (
            parsed.netloc
            .lower()
            .replace(
                "www.",
                ""
            )
        )

        # LinkedIn pessoa brasileira
        if (
            "linkedin.com"
            in host
            and "/in/"
            in parsed.path
        ):

            if (
                host.startswith(
                    "br.linkedin.com"
                )
                or host
                == "linkedin.com"
            ):

                return (
                    "linkedin",
                    url
                )

            return (
                None,
                None
            )

        # Instagram
        if "instagram.com" in host:

            partes = [
                p
                for p in parsed.path.split("/")
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
# EXTRAIR NOME DE RESULTADO WEB
# ============================================================

def extrair_nome_titulo(titulo):

    if not titulo:

        return ""

    nome = re.sub(
        r"\s*[|–—-]\s*LinkedIn.*$",
        "",
        titulo,
        flags=re.I
    )

    nome = re.sub(
        r"\s*\(@[^)]+\).*$",
        "",
        nome
    )

    nome = re.sub(
        r"\s*[|–—•].*$",
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
# CONFIRMA INSTITUIÇÃO
# ============================================================

def consulta_tem_instituicao(
    texto,
    faculdade
):

    t = normalizar(
        texto
    )

    nome = normalizar(
        faculdade["nome"]
    )

    sigla = normalizar(
        faculdade["sigla"]
    )

    cidade = normalizar(
        faculdade["cidade"]
    )

    if nome in t:

        return True

    if (
        sigla in t
        and cidade in t
    ):

        return True

    return False


# ============================================================
# CONFIRMA NUTRIÇÃO
# ============================================================

def tem_nutricao(texto):

    t = normalizar(
        texto
    )

    return (
        "nutricao" in t
        or
        "nutricionista" in t
    )


# ============================================================
# CHECKPOINT
# ============================================================

def buscar_checkpoint():

    try:

        resposta = (
            supabase
            .table(
                "controle_busca"
            )
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

    except Exception:

        return None


def obter_indice():

    checkpoint = buscar_checkpoint()

    if not checkpoint:

        return 0

    indice = checkpoint.get(
        "indice_pesquisa"
    )

    if indice is None:

        return 0

    return int(
        indice
    )


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
            "fonte_academica_mais_web",

        "atualizado_em":
            agora(),
    }

    try:

        if atual:

            (
                supabase
                .table(
                    "controle_busca"
                )
                .update(dados)
                .eq(
                    "id",
                    atual["id"]
                )
                .execute()
            )

        else:

            dados[
                "iniciado_em"
            ] = agora()

            (
                supabase
                .table(
                    "controle_busca"
                )
                .insert(dados)
                .execute()
            )

        return True

    except Exception as erro:

        print(
            f"⚠️ Erro checkpoint: "
            f"{erro}"
        )

        stats["erros"] += 1

        return False


# ============================================================
# DUPLICIDADE
# ============================================================

def existe(
    nome,
    faculdade,
    linkedin=None,
    instagram=None
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

        return bool(
            resposta.data
        )

    except Exception as erro:

        print(
            f"⚠️ Erro duplicidade: "
            f"{erro}"
        )

        return None


# ============================================================
# SALVAR LEAD
# ============================================================

def salvar_lead(
    nome,
    faculdade,
    ano,
    fase,
    fonte_url,
    fonte_validacao,
    linkedin=None,
    instagram=None,
    origem="fonte_academica_oficial"
):

    duplicado = existe(
        nome,
        faculdade,
        linkedin,
        instagram
    )

    if duplicado is True:

        stats[
            "duplicados"
        ] += 1

        print(
            f"♻️ Duplicado: "
            f"{nome}"
        )

        return False

    if duplicado is None:

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
            origem,

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
            (
                f"Nutrição | "
                f"{faculdade['sigla']} | "
                f"{ano} | "
                f"{fase}"
            ),

        "fonte_url":
            fonte_url,

        "fonte_validacao":
            fonte_validacao,
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

        print(
            f"✅ SALVO: "
            f"{nome} | "
            f"{ano} | "
            f"{fase}"
        )

        return True

    except Exception as erro:

        print(
            f"❌ Erro salvando "
            f"{nome}: "
            f"{erro}"
        )

        stats[
            "erros"
        ] += 1

        return False


# ============================================================
# FONTE OFICIAL MACKENZIE
# ============================================================

def extrair_tcc_mackenzie(
    url
):

    resposta = requests.get(

        url,

        timeout=40,

        headers={
            "User-Agent":
                "Mozilla/5.0"
        }
    )

    resposta.raise_for_status()

    soup = BeautifulSoup(
        resposta.text,
        "html.parser"
    )

    linhas = [

        linha.strip()

        for linha
        in soup.get_text(
            "\n"
        ).splitlines()

        if linha.strip()
    ]

    nomes = []

    dentro = False

    for linha in linhas:

        if (
            normalizar(linha)
            == "nutricao 2026.1"
        ):

            dentro = True

            continue

        if (
            dentro
            and normalizar(
                linha
            ).startswith(
                "cursos de graduacao"
            )
        ):

            break

        if not dentro:

            continue

        match = re.match(
            r"^(\d{1,2})\s*-\s*(.+)$",
            linha
        )

        if not match:

            continue

        bruto = (
            match
            .group(2)
            .strip()
        )

        # trabalhos em dupla
        partes = re.split(
            r"\s+e\s+",
            bruto,
            flags=re.I
        )

        for parte in partes:

            parte = re.sub(
                r"\s+",
                " ",
                parte
            ).strip(
                " -"
            )

            if nome_parece_pessoa(
                parte
            ):

                nomes.append(
                    nome_formatado(
                        parte
                    )
                )

    # remove duplicados preservando ordem
    return list(
        dict.fromkeys(
            nomes
        )
    )


# ============================================================
# PROCESSAR FONTES OFICIAIS
# ============================================================

def processar_fontes_oficiais(
    faculdade
):

    for fonte in faculdade.get(
        "fontes_oficiais",
        []
    ):

        try:

            print("")
            print(
                f"📚 Fonte oficial: "
                f"{fonte['tipo']}"
            )

            if (
                fonte["tipo"]
                == "lista_tcc"
            ):

                nomes = (
                    extrair_tcc_mackenzie(
                        fonte["url"]
                    )
                )

                stats[
                    "fontes_oficiais"
                ] += 1

                stats[
                    "nomes_oficiais"
                ] += len(
                    nomes
                )

                print(
                    f"👥 Nomes encontrados "
                    f"na fonte oficial: "
                    f"{len(nomes)}"
                )

                for nome in nomes:

                    salvar_lead(

                        nome=nome,

                        faculdade=
                            faculdade,

                        ano=
                            fonte["ano"],

                        fase=
                            fonte["fase"],

                        fonte_url=
                            fonte["url"],

                        fonte_validacao=
                            "site oficial da faculdade",

                        origem=
                            "fonte_academica_oficial"
                    )

        except Exception as erro:

            print(
                f"⚠️ Falha na fonte "
                f"oficial: {erro}"
            )

            stats[
                "erros"
            ] += 1


# ============================================================
# PESQUISA WEB COMPLEMENTAR
# ============================================================

def pesquisar(
    ddgs,
    consulta
):

    stats[
        "buscas"
    ] += 1

    print("")
    print(
        f"🔎 {consulta}"
    )

    for tentativa in range(
        1,
        MAX_TENTATIVAS + 1
    ):

        try:

            return list(
                ddgs.text(
                    consulta,
                    max_results=
                        MAX_RESULTADOS
                )
            )

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
                f"⚠️ Busca "
                f"{tentativa}/"
                f"{MAX_TENTATIVAS}: "
                f"{mensagem}"
            )

            if tentativa < (
                MAX_TENTATIVAS
            ):

                time.sleep(
                    12
                )

    stats[
        "erros"
    ] += 1

    return []


# ============================================================
# BLOCOS DE BUSCA
# ============================================================

def consultas_complementares(
    faculdade
):

    nome = (
        faculdade["nome"]
    )

    return [

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"7º semestre" '
                f'2026',

            "ano": 2026,

            "fase":
                "7º semestre",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"7º período" '
                f'2026',

            "ano": 2026,

            "fase":
                "7º período",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"8º semestre" '
                f'2026',

            "ano": 2026,

            "fase":
                "8º semestre",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"8º período" '
                f'2026',

            "ano": 2026,

            "fase":
                "8º período",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"TCC" '
                f'2026',

            "ano": 2026,

            "fase":
                "TCC",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"estágio obrigatório" '
                f'2026',

            "ano": 2026,

            "fase":
                "estágio obrigatório",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"formanda" '
                f'2026',

            "ano": 2026,

            "fase":
                "formando",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"formatura" '
                f'2025',

            "ano": 2025,

            "fase":
                "formado em 2025",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"recém-formada" '
                f'2025',

            "ano": 2025,

            "fase":
                "recém-formado",
        },

    ]


# ============================================================
# PROCESSAR RESULTADO COMPLEMENTAR
# ============================================================

def processar_resultado_web(
    resultado,
    faculdade,
    contexto
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

    tipo, rede = perfil_social(
        url
    )

    # só usamos perfil público de pessoa
    if not tipo:

        return False

    texto = (
        f"{titulo} "
        f"{corpo}"
    )

    # precisa provar Nutrição
    if not tem_nutricao(
        texto
    ):

        stats[
            "rejeitados"
        ] += 1

        return False

    # precisa provar a faculdade
    if not consulta_tem_instituicao(
        texto,
        faculdade
    ):

        stats[
            "rejeitados"
        ] += 1

        return False

    nome = extrair_nome_titulo(
        titulo
    )

    if not nome_parece_pessoa(
        nome
    ):

        stats[
            "rejeitados"
        ] += 1

        return False

    linkedin = (
        rede
        if tipo == "linkedin"
        else None
    )

    instagram = (
        rede
        if tipo == "instagram"
        else None
    )

    stats[
        "validos"
    ] += 1

    return salvar_lead(

        nome=nome,

        faculdade=faculdade,

        ano=contexto["ano"],

        fase=contexto["fase"],

        fonte_url=url,

        fonte_validacao=
            contexto["q"],

        linkedin=
            linkedin,

        instagram=
            instagram,

        origem=
            "busca_web_complementar"
    )


# ============================================================
# EXECUTAR
# ============================================================

def executar():

    indice = obter_indice()

    if indice >= len(
        FACULDADES
    ):

        print(
            "✅ Lista concluída."
        )

        return

    faculdade = (
        FACULDADES[
            indice
        ]
    )

    print("")
    print(
        "=" * 60
    )

    print(
        f"🏫 "
        f"{faculdade['nome']} "
        f"| "
        f"{faculdade['cidade']}/"
        f"{faculdade['estado']}"
    )

    print(
        "1) fonte acadêmica oficial"
    )

    print(
        "2) 7º/8º semestre"
    )

    print(
        "3) TCC"
    )

    print(
        "4) estágio"
    )

    print(
        "5) formatura 2025/2026"
    )

    print(
        "💾 Achou lead = salva na hora"
    )

    print(
        "=" * 60
    )

    salvar_checkpoint(
        indice,
        faculdade,
        "processando"
    )

    # --------------------------------------------------------
    # PRIMEIRO:
    # FONTES ACADÊMICAS OFICIAIS
    # --------------------------------------------------------

    processar_fontes_oficiais(
        faculdade
    )

    # --------------------------------------------------------
    # DEPOIS:
    # BUSCAS COMPLEMENTARES
    # --------------------------------------------------------

    with DDGS() as ddgs:

        for contexto in (
            consultas_complementares(
                faculdade
            )
        ):

            resultados = pesquisar(
                ddgs,
                contexto["q"]
            )

            for resultado in resultados:

                processar_resultado_web(
                    resultado,
                    faculdade,
                    contexto
                )

            pausa()

    # --------------------------------------------------------
    # TERMINOU A FACULDADE
    # --------------------------------------------------------

    proximo = (
        indice + 1
    )

    salvar_checkpoint(
        proximo,
        faculdade,
        "pendente"
    )

    print("")
    print(
        "✅ FACULDADE CONCLUÍDA"
    )

    if proximo < len(
        FACULDADES
    ):

        print(
            f"Próxima: "
            f"{FACULDADES[proximo]['nome']}"
        )


# ============================================================
# INÍCIO
# ============================================================

if __name__ == "__main__":

    executar()

    print("")
    print(
        "=" * 60
    )

    print(
        "RESUMO"
    )

    print(
        "=" * 60
    )

    for chave, valor in (
        stats.items()
    ):

        print(
            f"{chave}: "
            f"{valor}"
        )

    print(
        "=" * 60
    )
