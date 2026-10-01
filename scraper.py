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


print("🚀 SCRAPER UNIP INICIADO", flush=True)


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
    "nome": "Universidade Paulista",
    "sigla": "UNIP",
    "cidade": "São Paulo",
    "estado": "SP",
    "dominio": "unip.br",
}

ETAPA = "captacao_unip_2025_2026"

MAX_RESULTADOS = 15
PAUSA_MIN = 3
PAUSA_MAX = 5


CONSULTAS = [

    'site:unip.br "Nutrição" "discente" "2026"',

    'site:unip.br "Nutrição" "aluna" "2026"',

    'site:unip.br "Nutrição" "aluno" "2026"',

    'site:unip.br "Nutrição" "TCC" "2026"',

    'site:unip.br "Nutrição" "estágio" "2026"',

    'site:unip.br "Nutrição" "formanda" "2026"',

    'site:unip.br "Nutrição" "formando" "2026"',

    'site:unip.br "Nutrição" "formatura" "2026"',

    'site:unip.br "Nutrição" "formatura" "2025"',

    'site:unip.br "Nutrição" "egresso" "2025"',

]


stats = {
    "buscas": 0,
    "resultados": 0,
    "candidatos": 0,
    "qualificados": 0,
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


def pausa():

    time.sleep(
        random.uniform(
            PAUSA_MIN,
            PAUSA_MAX
        )
    )


# ============================================================
# URL OFICIAL
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
                "unip.br"
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

        stats[
            "resultados"
        ] += len(
            resultados
        )

        return resultados

    except Exception as erro:

        print(
            f"⚠️ Busca falhou: "
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
            f"   ⚠️ Falha ao abrir página: "
            f"{erro}",
            flush=True
        )

        return None


# ============================================================
# NOME DE PESSOA
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

    if len(nome) > 90:
        return False

    partes = nome.split()

    if len(partes) < 2:
        return False

    if len(partes) > 8:
        return False

    n = normalizar(nome)

    proibidos = [
        "universidade",
        "paulista",
        "nutricao",
        "curso",
        "professor",
        "professora",
        "coordenador",
        "coordenadora",
        "campus",
        "evento",
        "encontro",
        "palestra",
        "mesa redonda",
        "iniciacao cientifica",
    ]

    if any(
        termo in n
        for termo in proibidos
    ):

        return False

    return True


# ============================================================
# EXTRAIR NOMES DE DIScentes
# ============================================================

def extrair_discentes(
    soup
):

    nomes = []

    blocos = soup.find_all(
        ["h2", "h3", "h4", "p"]
    )

    for elemento in blocos:

        texto = (
            elemento
            .get_text(
                " ",
                strip=True
            )
        )

        t = normalizar(
            texto
        )

        # Só olha blocos com contexto discente
        if not any(
            sinal in t
            for sinal in [
                "discente do curso de nutricao",
                "aluna do curso de nutricao",
                "aluno do curso de nutricao",
                "graduanda do curso de nutricao",
                "graduando do curso de nutricao",
                "estudante do curso de nutricao",
            ]
        ):

            continue

        # tenta pegar título anterior com nome
        anterior = elemento.find_previous(
            ["h2", "h3", "h4"]
        )

        if anterior:

            nome = (
                anterior
                .get_text(
                    " ",
                    strip=True
                )
            )

            nome = re.sub(
                r"^(Profa?\.?|Prof\.?|Dra?\.?|Ma\.?|Me\.?)\s+",
                "",
                nome,
                flags=re.I
            ).strip()

            if nome_parece_pessoa(
                nome
            ):

                nomes.append(
                    nome
                )

    return list(
        dict.fromkeys(
            nomes
        )
    )


# ============================================================
# QUALIFICAÇÃO
# ============================================================

def tem_nutricao(texto):

    t = normalizar(texto)

    return (
        "nutricao"
        in t
    )


def identificar_fase(
    texto
):

    t = normalizar(texto)

    regras = [

        (
            "TCC",
            [
                "tcc",
                "trabalho de conclusao",
            ]
        ),

        (
            "estágio final",
            [
                "estagio obrigatorio",
                "estagio supervisionado",
                "estagio curricular",
                "preceptora de estagio",
                "preceptor de estagio",
            ]
        ),

        (
            "formando",
            [
                "formanda",
                "formando",
                "formandos",
                "formandas",
            ]
        ),

        (
            "formatura",
            [
                "formatura",
                "colacao",
                "colação",
            ]
        ),

        (
            "egresso 2025",
            [
                "egresso",
                "egressa",
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


def identificar_ano(
    texto
):

    t = normalizar(
        texto
    )

    if "2026" in t:
        return 2026

    if "2025" in t:
        return 2025

    return None


# ============================================================
# DUPLICIDADE
# ============================================================

def existe_lead(
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

        stats["erros"] += 1

        return None


# ============================================================
# SALVAR
# ============================================================

def salvar_lead(
    nome,
    ano,
    fase,
    url,
    evidencia
):

    duplicado = existe_lead(
        nome
    )

    if duplicado is True:

        stats[
            "duplicados"
        ] += 1

        print(
            f"♻️ Duplicado: "
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
            "fonte_oficial_unip",

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
            FACULDADE["cidade"],

        "estado":
            FACULDADE["estado"],

        "instituicao":
            FACULDADE["nome"],

        "ano_alvo":
            ano,

        "periodo_alvo":
            fase,

        "pontuacao":
            10,

        "evidencia":
            evidencia,

        "fonte_url":
            url,

        "fonte_validacao":
            "site oficial UNIP",
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
            f"{fase} | "
            f"{ano}",
            flush=True
        )

        return True

    except Exception as erro:

        print(
            f"❌ Erro salvando "
            f"{nome}: "
            f"{erro}",
            flush=True
        )

        stats["erros"] += 1

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

    if not tem_nutricao(
        texto
    ):

        return

    nomes = extrair_discentes(
        soup
    )

    if not nomes:

        return

    stats[
        "candidatos"
    ] += len(
        nomes
    )

    fase = identificar_fase(
        texto
    )

    ano = identificar_ano(
        texto
    )

    print(
        f"   👤 Candidatos: "
        f"{len(nomes)}",
        flush=True
    )

    # --------------------------------------------------------
    # SÓ QUALIFICA COM FASE + ANO
    # --------------------------------------------------------

    if (
        not fase
        or
        ano not in [
            2025,
            2026
        ]
    ):

        for nome in nomes:

            print(
                f"   ⏸️ CANDIDATO SEM FASE FINAL: "
                f"{nome}",
                flush=True
            )

        stats[
            "rejeitados"
        ] += len(
            nomes
        )

        return

    # --------------------------------------------------------
    # LEAD QUALIFICADO
    # --------------------------------------------------------

    for nome in nomes:

        stats[
            "qualificados"
        ] += 1

        evidencia = (
            f"Fonte oficial UNIP | "
            f"Nutrição | "
            f"{fase} | "
            f"{ano}"
        )

        salvar_lead(
            nome=nome,
            ano=ano,
            fase=fase,
            url=url,
            evidencia=evidencia
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


def indice_atual():

    atual = buscar_checkpoint()

    if not atual:
        return 0

    valor = atual.get(
        "indice_pesquisa"
    )

    if valor is None:
        return 0

    return int(
        valor
    )


def salvar_checkpoint(
    indice
):

    atual = buscar_checkpoint()

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
            "unip.br",

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


# ============================================================
# EXECUÇÃO
# ============================================================

def executar():

    print("")
    print(
        "=" * 65,
        flush=True
    )

    print(
        "UNIP — BUSCA SEGURA DE LEADS",
        flush=True
    )

    print(
        "NUTRIÇÃO | 2025 / 2026",
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
            "✅ UNIP já concluída.",
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
        "RESUMO UNIP",
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
        f"Resultados: "
        f"{stats['resultados']}",
        flush=True
    )

    print(
        f"Candidatos: "
        f"{stats['candidatos']}",
        flush=True
    )

    print(
        f"Qualificados: "
        f"{stats['qualificados']}",
        flush=True
    )

    print(
        f"Salvos: "
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
        "✅ SCRAPER UNIP FINALIZADO",
        flush=True
    )
