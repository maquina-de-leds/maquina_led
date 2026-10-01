import os
import re
import time
import random
import unicodedata
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from supabase import create_client


print("🚀 MÁQUINA 1 - CAPTAÇÃO DE LEADS", flush=True)


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
# CONFIGURAÇÃO ATUAL - MACKENZIE
# ============================================================

INSTITUICAO = "Universidade Presbiteriana Mackenzie"
ESTADO = "SP"
CIDADE = "São Paulo"

ETAPA = "captacao_mackenzie_2025_2026_v3"

PAUSA_MIN = 2
PAUSA_MAX = 4

MAX_RESULTADOS = 15


URL_TCC_2026 = (
    "https://www.mackenzie.br/"
    "universidade/unidades-academicas/"
    "ccbs/tcc-e-pesquisa/mostra-de-tcc"
)


CONSULTAS = [

    '"Mackenzie" "Nutrição" "2025"',

    '"Mackenzie" "Nutrição" "2026"',

    '"Mackenzie" "Nutrição" "formanda"',

    '"Mackenzie" "Nutrição" "formando"',

    '"Mackenzie" "Nutrição" "TCC"',

    '"Mackenzie" "Nutrição" "7º semestre"',

    '"Mackenzie" "Nutrição" "8º semestre"',

    '"Mackenzie" "Nutrição" "estágio obrigatório"',

    '"Mackenzie" "Nutrição" "colação de grau"',

    '"Universidade Presbiteriana Mackenzie" nutricionista "2025"',

    '"Universidade Presbiteriana Mackenzie" nutricionista "2026"',
]


stats = {
    "oficiais": 0,
    "complementares": 0,
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

    if not texto:
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
# VALIDAR NOME
# ============================================================

def nome_valido(nome):

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

    texto = normalizar(
        nome
    )

    proibidos = [
        "universidade",
        "mackenzie",
        "nutricao",
        "faculdade",
        "curso",
        "campus",
        "evento",
        "professor",
        "professora",
        "coordenador",
        "coordenadora",
        "mostra",
        "trabalho de conclusao",
        "centro academico",
        "secretaria",
        "reitoria",
    ]

    for termo in proibidos:

        if termo in texto:
            return False

    return True


# ============================================================
# VERIFICAR DUPLICIDADE
# ============================================================

def buscar_lead(nome):

    try:

        resposta = (
            supabase
            .table("leds")
            .select(
                "id,nome,instagram,linkedin"
            )
            .eq(
                "instituicao",
                INSTITUICAO
            )
            .ilike(
                "nome",
                nome
            )
            .limit(1)
            .execute()
        )

        if resposta.data:
            return resposta.data[0]

        return None

    except Exception as erro:

        print(
            f"⚠️ Erro verificando duplicidade: {erro}",
            flush=True
        )

        stats["erros"] += 1

        return None


# ============================================================
# SALVAR LEAD
# ============================================================

def salvar_lead(
    nome,
    ano,
    periodo,
    evidencia,
    fonte_url,
    origem
):

    existente = buscar_lead(
        nome
    )

    if existente:

        stats["duplicados"] += 1

        print(
            f"♻️ Já existe: {nome}",
            flush=True
        )

        return existente["id"]

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
            origem,

        "origem_lead":
            "captacao_academica",

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
            CIDADE,

        "estado":
            ESTADO,

        "instituicao":
            INSTITUICAO,

        "ano_alvo":
            ano,

        "periodo_alvo":
            periodo,

        "pontuacao":
            10,

        "evidencia":
            evidencia,

        "fonte_url":
            fonte_url,

        "fonte_validacao":
            origem,

        "proxima_acao":
            "buscar_instagram",

        "rede_processada":
            False,

        "nivel_rede":
            0,
    }

    try:

        resposta = (
            supabase
            .table("leds")
            .insert(dados)
            .execute()
        )

        stats["salvos"] += 1

        print(
            f"✅ NOVO LEAD SALVO: {nome}",
            flush=True
        )

        if resposta.data:
            return resposta.data[0]["id"]

    except Exception as erro:

        print(
            f"❌ Erro salvando {nome}: {erro}",
            flush=True
        )

        stats["erros"] += 1

    return None


# ============================================================
# FONTE OFICIAL - MACKENZIE 2026.1
# ============================================================

def extrair_tcc_2026():

    print("")
    print(
        "📚 Buscando fonte oficial Mackenzie...",
        flush=True
    )

    try:

        resposta = requests.get(
            URL_TCC_2026,
            timeout=40,
            headers={
                "User-Agent":
                    "Mozilla/5.0"
            }
        )

        resposta.raise_for_status()

    except Exception as erro:

        print(
            f"❌ Fonte oficial falhou: {erro}",
            flush=True
        )

        stats["erros"] += 1

        return []

    soup = BeautifulSoup(
        resposta.text,
        "html.parser"
    )

    texto = soup.get_text(
        "\n",
        strip=True
    )

    inicio = texto.find(
        "NUTRIÇÃO 2026.1"
    )

    if inicio == -1:

        inicio = texto.find(
            "Nutrição 2026.1"
        )

    if inicio == -1:

        print(
            "❌ Seção Nutrição 2026.1 não encontrada",
            flush=True
        )

        return []

    trecho = texto[
        inicio:
        inicio + 18000
    ]

    padrao = re.compile(
        r"\d{2}\s*-\s*([A-ZÁÀÂÃÉÈÊÍÌÓÒÔÕÚÙÇ\s]+)",
        re.MULTILINE
    )

    encontrados = padrao.findall(
        trecho
    )

    nomes = []

    for bloco in encontrados:

        bloco = re.sub(
            r"\s+",
            " ",
            bloco
        ).strip()

        pessoas = re.split(
            r"\s+E\s+",
            bloco
        )

        for nome in pessoas:

            nome = (
                nome
                .strip()
                .title()
            )

            nome = re.sub(
                r"\s+[A-ZÀ-Ú]$",
                "",
                nome
            ).strip()

            if nome_valido(
                nome
            ):

                nomes.append(
                    nome
                )

    nomes = list(
        dict.fromkeys(
            nomes
        )
    )

    print(
        f"👥 Pessoas oficiais encontradas: {len(nomes)}",
        flush=True
    )

    stats[
        "oficiais"
    ] += len(
        nomes
    )

    return nomes


# ============================================================
# IDENTIFICAR ANO
# ============================================================

def identificar_ano(texto):

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
# IDENTIFICAR FASE
# ============================================================

def identificar_periodo(texto):

    t = normalizar(
        texto
    )

    if (
        "8º semestre" in t
        or
        "8o semestre" in t
        or
        "8 semestre" in t
        or
        "8º periodo" in t
        or
        "8o periodo" in t
    ):
        return "8º semestre/período"

    if (
        "7º semestre" in t
        or
        "7o semestre" in t
        or
        "7 semestre" in t
        or
        "7º periodo" in t
        or
        "7o periodo" in t
    ):
        return "7º semestre/período"

    if "tcc" in t:
        return "TCC"

    if "trabalho de conclusao" in t:
        return "TCC"

    if "estagio obrigatorio" in t:
        return "estágio obrigatório"

    if "estagio supervisionado" in t:
        return "estágio supervisionado"

    if (
        "formanda" in t
        or
        "formando" in t
    ):
        return "formanda/o"

    if (
        "formatura" in t
        or
        "colacao" in t
    ):
        return "formada/o"

    if (
        "graduada" in t
        or
        "graduado" in t
    ):
        return "graduada/o"

    return "2025/2026"


# ============================================================
# VERIFICAR SE RESULTADO É DO NOSSO PÚBLICO
# ============================================================

def resultado_valido(texto):

    t = normalizar(
        texto
    )

    if "nutricao" not in t:
        return False

    if "mackenzie" not in t:
        return False

    ano = identificar_ano(
        texto
    )

    fase_final = any(
        termo in t
        for termo in [
            "7º semestre",
            "7o semestre",
            "7 semestre",
            "8º semestre",
            "8o semestre",
            "8 semestre",
            "7º periodo",
            "7o periodo",
            "8º periodo",
            "8o periodo",
            "tcc",
            "trabalho de conclusao",
            "formanda",
            "formando",
            "formatura",
            "colacao",
            "estagio obrigatorio",
            "estagio supervisionado",
            "graduada",
            "graduado",
        ]
    )

    if (
        ano in [
            2025,
            2026
        ]
        or
        fase_final
    ):
        return True

    return False


# ============================================================
# EXTRAIR NOME DO RESULTADO
# ============================================================

def extrair_nome_resultado(
    resultado
):

    titulo = (
        resultado
        .get(
            "title",
            ""
        )
        .strip()
    )

    if not titulo:
        return None

    # LinkedIn costuma retornar:
    # "Nome Sobrenome - descrição | LinkedIn"

    titulo = re.sub(
        r"\s*\|\s*LinkedIn.*$",
        "",
        titulo,
        flags=re.I
    )

    titulo = re.sub(
        r"\s*[-–]\s*(Nutrição|Nutricionista|Universidade|Mackenzie).*$",
        "",
        titulo,
        flags=re.I
    )

    titulo = re.sub(
        r"\s+",
        " ",
        titulo
    ).strip()

    if nome_valido(
        titulo
    ):
        return titulo

    return None


# ============================================================
# BUSCA COMPLEMENTAR
# ============================================================

def buscar_complementares():

    print("")
    print(
        "🌐 Iniciando busca complementar...",
        flush=True
    )

    candidatos = {}

    with DDGS() as ddgs:

        for consulta in CONSULTAS:

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

            except Exception as erro:

                print(
                    f"⚠️ Busca indisponível: {erro}",
                    flush=True
                )

                pausa()

                continue

            print(
                f"   Resultados: {len(resultados)}",
                flush=True
            )

            for resultado in resultados:

                titulo = (
                    resultado.get(
                        "title",
                        ""
                    )
                )

                corpo = (
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
                    titulo
                    + " "
                    + corpo
                )

                if not resultado_valido(
                    texto
                ):
                    continue

                nome = extrair_nome_resultado(
                    resultado
                )

                if not nome:

                    stats[
                        "rejeitados"
                    ] += 1

                    continue

                chave = normalizar(
                    nome
                )

                if chave in candidatos:
                    continue

                ano = identificar_ano(
                    texto
                )

                periodo = identificar_periodo(
                    texto
                )

                candidatos[
                    chave
                ] = {
                    "nome":
                        nome,

                    "ano":
                        ano or 2026,

                    "periodo":
                        periodo,

                    "evidencia":
                        texto[:1000],

                    "fonte_url":
                        url,
                }

            pausa()

    resultado = list(
        candidatos.values()
    )

    stats[
        "complementares"
    ] += len(
        resultado
    )

    print("")
    print(
        f"👥 Complementares encontrados: {len(resultado)}",
        flush=True
    )

    return resultado


# ============================================================
# CHECKPOINT
# ============================================================

def salvar_checkpoint():

    try:

        resposta = (
            supabase
            .table(
                "controle_busca"
            )
            .select("id")
            .eq(
                "etapa",
                ETAPA
            )
            .limit(1)
            .execute()
        )

        dados = {

            "estado":
                ESTADO,

            "cidade":
                CIDADE,

            "instituicao":
                INSTITUICAO,

            "etapa":
                ETAPA,

            "status":
                "concluido",

            "leads_encontrados":
                (
                    stats["oficiais"]
                    +
                    stats["complementares"]
                ),

            "leads_salvos":
                stats["salvos"],

            "atualizado_em":
                agora(),

            "finalizado_em":
                agora(),
        }

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
            f"⚠️ Erro no checkpoint: {erro}",
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
        "MÁQUINA 1 - CAPTAÇÃO",
        flush=True
    )

    print(
        "MACKENZIE - NUTRIÇÃO 2025/2026",
        flush=True
    )

    print(
        "=" * 65,
        flush=True
    )

    # ========================================================
    # FONTE OFICIAL
    # ========================================================

    nomes = extrair_tcc_2026()

    for nome in nomes:

        salvar_lead(
            nome=
                nome,

            ano=
                2026,

            periodo=
                "TCC 2026.1",

            evidencia=
                "Mostra de TCC Nutrição 2026.1 - Mackenzie",

            fonte_url=
                URL_TCC_2026,

            origem=
                "fonte_oficial_mackenzie_tcc_2026"
        )

    # ========================================================
    # BUSCA COMPLEMENTAR
    # ========================================================

    complementares = buscar_complementares()

    for candidato in complementares:

        salvar_lead(

            nome=
                candidato["nome"],

            ano=
                candidato["ano"],

            periodo=
                candidato["periodo"],

            evidencia=
                candidato["evidencia"],

            fonte_url=
                candidato["fonte_url"],

            origem=
                "busca_publica_mackenzie_2025_2026"
        )

    salvar_checkpoint()

    # ========================================================
    # RESUMO
    # ========================================================

    print("")
    print(
        "=" * 65,
        flush=True
    )

    print(
        "RESUMO DA CAPTAÇÃO",
        flush=True
    )

    print(
        "=" * 65,
        flush=True
    )

    print(
        f"Fonte oficial: "
        f"{stats['oficiais']}",
        flush=True
    )

    print(
        f"Complementares: "
        f"{stats['complementares']}",
        flush=True
    )

    print(
        f"Novos salvos: "
        f"{stats['salvos']}",
        flush=True
    )

    print(
        f"Já existentes: "
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


if __name__ == "__main__":

    executar()

    print(
        "✅ MÁQUINA 1 FINALIZADA",
        flush=True
    )
