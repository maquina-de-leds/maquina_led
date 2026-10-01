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


print("🚀 SCRAPER OFICIAL MACKENZIE INICIADO", flush=True)


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
# CONFIGURAÇÃO
# ============================================================

FACULDADE = {
    "nome": "Universidade Presbiteriana Mackenzie",
    "sigla": "Mackenzie",
    "cidade": "São Paulo",
    "estado": "SP",
    "dominio": "mackenzie.br",
}

ETAPA = "fontes_oficiais_mackenzie_2025_2026"

MAX_RESULTADOS = 10

PAUSA_MIN = 3
PAUSA_MAX = 5


stats = {
    "buscas": 0,
    "paginas_oficiais": 0,
    "paginas_validas": 0,
    "nomes_extraidos": 0,
    "salvos": 0,
    "duplicados": 0,
    "rejeitados": 0,
    "erros": 0,
}


# ============================================================
# CONSULTAS
# ============================================================

CONSULTAS = [

    (
        'site:mackenzie.br '
        '"Nutrição" "TCC" "2026"'
    ),

    (
        'site:mackenzie.br '
        '"Nutrição" "TCC" "2025"'
    ),

    (
        'site:mackenzie.br '
        '"Nutrição" "8º semestre"'
    ),

    (
        'site:mackenzie.br '
        '"Nutrição" "8ª etapa"'
    ),

    (
        'site:mackenzie.br '
        '"Nutrição" "7º semestre"'
    ),

    (
        'site:mackenzie.br '
        '"Nutrição" "7ª etapa"'
    ),

    (
        'site:mackenzie.br '
        '"Nutrição" "estágio obrigatório"'
    ),

    (
        'site:mackenzie.br '
        '"Nutrição" "estágio curricular"'
    ),

    (
        'site:mackenzie.br '
        '"Nutrição" "formandos" "2026"'
    ),

    (
        'site:mackenzie.br '
        '"Nutrição" "formandos" "2025"'
    ),

    (
        'site:mackenzie.br '
        '"Nutrição" "formatura" "2026"'
    ),

    (
        'site:mackenzie.br '
        '"Nutrição" "formatura" "2025"'
    ),

    (
        'site:mackenzie.br '
        '"Nutrição" "colação" "2026"'
    ),

    (
        'site:mackenzie.br '
        '"Nutrição" "colação" "2025"'
    ),
]


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
# PÁGINA OFICIAL?
# ============================================================

def url_oficial(url):

    if not url:
        return False

    try:

        host = (
            urlparse(url)
            .netloc
            .lower()
        )

        return (
            host.endswith(
                "mackenzie.br"
            )
        )

    except Exception:

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
        f"🔎 {consulta}",
        flush=True
    )

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

        print(
            f"⚠️ Erro na busca: "
            f"{erro}",
            flush=True
        )

        stats["erros"] += 1

        return []


# ============================================================
# BAIXAR PÁGINA
# ============================================================

def baixar_pagina(url):

    try:

        resposta = requests.get(
            url,
            timeout=30,
            headers={
                "User-Agent":
                    "Mozilla/5.0"
            }
        )

        resposta.raise_for_status()

        tipo = (
            resposta.headers
            .get(
                "Content-Type",
                ""
            )
            .lower()
        )

        if (
            "text/html"
            not in tipo
        ):

            return None

        return resposta.text

    except Exception as erro:

        print(
            f"   ⚠️ Não abriu página: "
            f"{erro}",
            flush=True
        )

        return None


# ============================================================
# PROVA DE NUTRIÇÃO
# ============================================================

def tem_nutricao(texto):

    t = normalizar(texto)

    return (
        "nutricao" in t
        or
        "curso de nutricao"
        in t
    )


# ============================================================
# PROVA DE FASE FINAL
# ============================================================

def identificar_fase(texto):

    t = normalizar(texto)

    regras = [

        (
            "TCC",
            [
                "tcc",
                "trabalho de conclusao",
                "trabalho de conclusão",
            ]
        ),

        (
            "8º semestre",
            [
                "8 semestre",
                "8º semestre",
                "oitavo semestre",
                "8 etapa",
                "8ª etapa",
            ]
        ),

        (
            "7º semestre",
            [
                "7 semestre",
                "7º semestre",
                "setimo semestre",
                "sétimo semestre",
                "7 etapa",
                "7ª etapa",
            ]
        ),

        (
            "estágio final",
            [
                "estagio obrigatorio",
                "estágio obrigatório",
                "estagio curricular",
                "estágio curricular",
                "estagio supervisionado",
                "estágio supervisionado",
            ]
        ),

        (
            "formatura",
            [
                "formatura",
                "formando",
                "formanda",
                "formandos",
            ]
        ),

        (
            "colação",
            [
                "colacao de grau",
                "colação de grau",
                "colacao",
                "colação",
            ]
        ),
    ]

    for fase, sinais in regras:

        for sinal in sinais:

            if normalizar(
                sinal
            ) in t:

                return fase

    return None


# ============================================================
# ANO
# ============================================================

def identificar_ano(texto):

    t = normalizar(texto)

    if "2026" in t:
        return 2026

    if "2025" in t:
        return 2025

    return None


# ============================================================
# NOME PARECE PESSOA?
# ============================================================

def nome_parece_pessoa(nome):

    if not nome:
        return False

    nome = re.sub(
        r"\s+",
        " ",
        nome
    ).strip()

    if len(nome) < 7:
        return False

    if len(nome) > 80:
        return False

    palavras = nome.split()

    if len(palavras) < 2:
        return False

    if len(palavras) > 7:
        return False

    n = normalizar(nome)

    proibidos = [

        "universidade",

        "mackenzie",

        "nutricao",

        "faculdade",

        "centro",

        "curso",

        "coordenacao",

        "departamento",

        "professor",

        "professora",

        "orientador",

        "orientadora",

        "formatura",

        "trabalho",

        "conclusao",

        "estagio",

        "evento",

        "jornada",

        "congresso",

        "alunos",

        "alunas",
    ]

    if any(
        termo in n
        for termo in proibidos
    ):

        return False

    return True


# ============================================================
# EXTRAIR NOMES
# ============================================================

def extrair_nomes(
    soup
):

    encontrados = []

    seletores = [
        "li",
        "p",
        "td",
        "h3",
        "h4",
        "strong",
    ]

    textos = []

    for seletor in seletores:

        for elemento in soup.select(
            seletor
        ):

            texto = (
                elemento
                .get_text(
                    " ",
                    strip=True
                )
            )

            if texto:

                textos.append(
                    texto
                )

    padrao_nome = re.compile(

        r"\b("
        r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ]"
        r"[a-záéíóúâêôãõç]+"
        r"(?:\s+"
        r"(?:de|da|do|das|dos|e)"
        r")?"
        r"(?:\s+"
        r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ]"
        r"[a-záéíóúâêôãõç]+"
        r"){1,5}"
        r")\b"
    )

    for texto in textos:

        contexto = normalizar(
            texto
        )

        # prioriza trechos acadêmicos
        if not any(
            palavra in contexto
            for palavra in [
                "aluna",
                "aluno",
                "graduanda",
                "graduando",
                "discente",
                "autora",
                "autor",
                "tcc",
                "trabalho",
                "formanda",
                "formando",
                "estagio",
                "estágio",
            ]
        ):

            continue

        matches = (
            padrao_nome
            .findall(texto)
        )

        for nome in matches:

            nome = re.sub(
                r"\s+",
                " ",
                nome
            ).strip()

            if nome_parece_pessoa(
                nome
            ):

                encontrados.append(
                    nome
                )

    return list(
        dict.fromkeys(
            encontrados
        )
    )


# ============================================================
# EXISTE?
# ============================================================

def existe(
    nome
):

    try:

        resposta = (
            supabase
            .table("leds")
            .select("id")
            .eq(
                "instituicao",
                FACULDADE["nome"]
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
            f"{erro}",
            flush=True
        )

        return None


# ============================================================
# SALVAR
# ============================================================

def salvar_lead(
    nome,
    ano,
    fase,
    url
):

    duplicado = existe(
        nome
    )

    if duplicado is True:

        stats[
            "duplicados"
        ] += 1

        print(
            f"   ♻️ Duplicado: "
            f"{nome}",
            flush=True
        )

        return False

    if duplicado is None:

        return False

    dados = {

        "nome":
            nome,

        "instagram":
            None,

        "linkedin":
            None,

        "whatsapp":
            None,

        "nicho":
            "nutricionista",

        "origem":
            "fonte_oficial_mackenzie",

        "origem_lead":
            "fonte_academica",

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
            FACULDADE[
                "cidade"
            ],

        "estado":
            FACULDADE[
                "estado"
            ],

        "instituicao":
            FACULDADE[
                "nome"
            ],

        "ano_alvo":
            ano,

        "periodo_alvo":
            fase,

        "pontuacao":
            10,

        "evidencia":
            (
                f"Fonte oficial Mackenzie | "
                f"Nutrição | "
                f"{fase} | "
                f"{ano}"
            ),

        "fonte_url":
            url,

        "fonte_validacao":
            "site oficial Mackenzie",
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
            f"   ✅ SALVO: "
            f"{nome} | "
            f"{fase} | "
            f"{ano}",
            flush=True
        )

        return True

    except Exception as erro:

        print(
            f"   ❌ Erro salvando "
            f"{nome}: "
            f"{erro}",
            flush=True
        )

        stats[
            "erros"
        ] += 1

        return False


# ============================================================
# PROCESSAR PÁGINA
# ============================================================

def processar_pagina(
    url
):

    if not url_oficial(
        url
    ):

        return

    stats[
        "paginas_oficiais"
    ] += 1

    html = baixar_pagina(
        url
    )

    if not html:

        return

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    texto = soup.get_text(
        " ",
        strip=True
    )

    # --------------------------------------------
    # TEM QUE SER NUTRIÇÃO
    # --------------------------------------------

    if not tem_nutricao(
        texto
    ):

        stats[
            "rejeitados"
        ] += 1

        return

    # --------------------------------------------
    # TEM QUE TER FASE FINAL
    # --------------------------------------------

    fase = identificar_fase(
        texto
    )

    if not fase:

        stats[
            "rejeitados"
        ] += 1

        print(
            "   ⛔ Página sem prova "
            "de fase final",
            flush=True
        )

        return

    # --------------------------------------------
    # TEM QUE SER 2025/2026
    # --------------------------------------------

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

        print(
            "   ⛔ Página fora de "
            "2025/2026",
            flush=True
        )

        return

    stats[
        "paginas_validas"
    ] += 1

    print(
        f"   ✅ Página válida: "
        f"{fase} | {ano}",
        flush=True
    )

    # --------------------------------------------
    # EXTRAIR NOMES
    # --------------------------------------------

    nomes = extrair_nomes(
        soup
    )

    stats[
        "nomes_extraidos"
    ] += len(
        nomes
    )

    print(
        f"   👥 Nomes candidatos: "
        f"{len(nomes)}",
        flush=True
    )

    for nome in nomes:

        salvar_lead(
            nome=nome,
            ano=ano,
            fase=fase,
            url=url
        )


# ============================================================
# CHECKPOINT
# ============================================================

def checkpoint_existe():

    try:

        resposta = (
            supabase
            .table(
                "controle_busca"
            )
            .select("*")
            .eq(
                "etapa",
                ETAPA
            )
            .limit(1)
            .execute()
        )

        if resposta.data:

            return resposta.data[0]

        return None

    except Exception:

        return None


def salvar_checkpoint(
    indice
):

    atual = checkpoint_existe()

    dados = {

        "estado":
            "SP",

        "cidade":
            "São Paulo",

        "instituicao":
            FACULDADE["nome"],

        "etapa":
            ETAPA,

        "status":
            "pendente",

        "indice_pesquisa":
            indice,

        "total_pesquisas":
            len(CONSULTAS),

        "consulta_atual":
            (
                CONSULTAS[indice]
                if indice
                < len(CONSULTAS)
                else "concluido"
            ),

        "fonte_atual":
            "mackenzie.br",

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
                .update(
                    dados
                )
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
                .insert(
                    dados
                )
                .execute()
            )

    except Exception as erro:

        print(
            f"⚠️ Checkpoint: "
            f"{erro}",
            flush=True
        )


def indice_atual():

    atual = checkpoint_existe()

    if not atual:

        return 0

    indice = atual.get(
        "indice_pesquisa"
    )

    if indice is None:

        return 0

    return int(
        indice
    )


# ============================================================
# EXECUTAR
# ============================================================

def executar():

    print("")
    print(
        "=" * 65,
        flush=True
    )

    print(
        "BUSCA EM FONTES OFICIAIS — MACKENZIE",
        flush=True
    )

    print(
        "NUTRIÇÃO | 2025 / 2026 | FASE FINAL",
        flush=True
    )

    print(
        "=" * 65,
        flush=True
    )

    inicio = indice_atual()

    if inicio >= len(
        CONSULTAS
    ):

        print(
            "✅ Todas as consultas "
            "já foram processadas.",
            flush=True
        )

        return

    urls_processadas = set()

    with DDGS() as ddgs:

        for indice in range(
            inicio,
            len(CONSULTAS)
        ):

            consulta = (
                CONSULTAS[
                    indice
                ]
            )

            resultados = pesquisar(
                ddgs,
                consulta
            )

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

                if not url_oficial(
                    url
                ):

                    continue

                if url in urls_processadas:

                    continue

                urls_processadas.add(
                    url
                )

                print(
                    f"   📄 {url}",
                    flush=True
                )

                processar_pagina(
                    url
                )

            salvar_checkpoint(
                indice + 1
            )

            pausa()

    print("")
    print(
        "=" * 65,
        flush=True
    )

    print(
        "RESUMO",
        flush=True
    )

    print(
        "=" * 65,
        flush=True
    )

    print(
        f"Buscas: "
        f"{stats['buscas']}",
        flush=True
    )

    print(
        f"Páginas oficiais: "
        f"{stats['paginas_oficiais']}",
        flush=True
    )

    print(
        f"Páginas válidas: "
        f"{stats['paginas_validas']}",
        flush=True
    )

    print(
        f"Nomes extraídos: "
        f"{stats['nomes_extraidos']}",
        flush=True
    )

    print(
        f"Novos salvos: "
        f"{stats['salvos']}",
        flush=True
    )

    print(
        f"Duplicados: "
        f"{stats['duplicados']}",
        flush=True
    )

    print(
        f"Rejeitados: "
        f"{stats['rejeitados']}",
        flush=True
    )

    print(
        f"Erros: "
        f"{stats['erros']}",
        flush=True
    )

    print(
        "=" * 65,
        flush=True
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    executar()

    print(
        "✅ SCRAPER FINALIZADO",
        flush=True
    )
