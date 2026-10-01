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


print("🚀 MÁQUINA DE LEADS - MACKENZIE", flush=True)


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

INSTITUICAO = "Universidade Presbiteriana Mackenzie"
ESTADO = "SP"
CIDADE = "São Paulo"

ETAPA = "mackenzie_captacao_ampliada_v1"

MAX_RESULTADOS = 15

PAUSA_MIN = 2
PAUSA_MAX = 4


# Fonte oficial já validada
URL_TCC_2026 = (
    "https://www.mackenzie.br/"
    "universidade/unidades-academicas/"
    "ccbs/tcc-e-pesquisa/mostra-de-tcc"
)


# ============================================================
# CONSULTAS COMPLEMENTARES
# ============================================================

CONSULTAS = [

    '"Universidade Presbiteriana Mackenzie" "Nutrição" "2025"',

    '"Universidade Presbiteriana Mackenzie" "Nutrição" "2026"',

    '"Mackenzie" "Nutrição" "TCC" "2025"',

    '"Mackenzie" "Nutrição" "TCC" "2026"',

    '"Mackenzie" "Nutrição" "formanda"',

    '"Mackenzie" "Nutrição" "formando"',

    '"Mackenzie" "Nutrição" "colação de grau"',

    '"Mackenzie" "Nutrição" "8º semestre"',

    '"Mackenzie" "Nutrição" "7º semestre"',

    '"Mackenzie" "Nutrição" "estágio obrigatório"',
]


stats = {
    "fontes": 0,
    "nomes_encontrados": 0,
    "salvos": 0,
    "duplicados": 0,
    "instagram_encontrado": 0,
    "linkedin_encontrado": 0,
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
# NOME
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

    texto = normalizar(nome)

    proibidos = [
        "universidade",
        "mackenzie",
        "nutricao",
        "centro",
        "curso",
        "evento",
        "professor",
        "professora",
        "coordenador",
        "coordenadora",
        "mostra de tcc",
        "trabalho de conclusao",
    ]

    for termo in proibidos:

        if termo in texto:
            return False

    return True


# ============================================================
# DUPLICIDADE
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
            f"⚠️ Erro ao verificar duplicidade: {erro}",
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
            "buscar_contato",
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
            f"✅ SALVO: {nome}",
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
# ATUALIZAR CONTATO
# ============================================================

def atualizar_contato(
    lead_id,
    instagram=None,
    linkedin=None
):

    if not lead_id:
        return

    dados = {}

    if instagram:
        dados["instagram"] = instagram
        dados["proxima_acao"] = "primeiro_contato_instagram"

    if linkedin:
        dados["linkedin"] = linkedin

    if not dados:
        return

    try:

        (
            supabase
            .table("leds")
            .update(dados)
            .eq(
                "id",
                lead_id
            )
            .execute()
        )

    except Exception as erro:

        print(
            f"⚠️ Erro atualizando contato: {erro}",
            flush=True
        )

        stats["erros"] += 1


# ============================================================
# INSTAGRAM
# ============================================================

def extrair_instagram_url(url):

    if not url:
        return None

    try:

        host = (
            urlparse(url)
            .netloc
            .lower()
        )

        if "instagram.com" not in host:
            return None

        caminho = (
            urlparse(url)
            .path
            .strip("/")
        )

        if not caminho:
            return None

        primeira = caminho.split("/")[0]

        proibidos = [
            "p",
            "reel",
            "reels",
            "explore",
            "stories",
            "accounts",
        ]

        if primeira.lower() in proibidos:
            return None

        if len(primeira) < 2:
            return None

        return f"@{primeira}"

    except Exception:

        return None


def buscar_instagram(
    ddgs,
    nome
):

    consultas = [

        f'"{nome}" Nutrição Instagram',

        f'"{nome}" nutricionista Instagram',

        f'"{nome}" Mackenzie Instagram',

        f'"{nome}" site:instagram.com',
    ]

    for consulta in consultas:

        try:

            resultados = list(
                ddgs.text(
                    consulta,
                    max_results=8
                )
            )

        except Exception:

            continue

        for resultado in resultados:

            url = (
                resultado.get("href")
                or resultado.get("url")
                or ""
            )

            handle = extrair_instagram_url(
                url
            )

            if not handle:
                continue

            texto = normalizar(
                (
                    resultado.get("title", "")
                    + " "
                    + resultado.get("body", "")
                )
            )

            nome_normalizado = normalizar(
                nome
            )

            primeiro_nome = (
                nome_normalizado
                .split()[0]
            )

            sobrenome = (
                nome_normalizado
                .split()[-1]
            )

            # confirmação simples
            if (
                primeiro_nome in texto
                or
                sobrenome in texto
                or
                "nutricao" in texto
                or
                "nutricionista" in texto
            ):

                return handle

        pausa()

    return None


# ============================================================
# LINKEDIN
# ============================================================

def buscar_linkedin(
    ddgs,
    nome
):

    consultas = [

        f'"{nome}" "Mackenzie" Nutrição LinkedIn',

        f'"{nome}" Nutrição site:linkedin.com/in',
    ]

    for consulta in consultas:

        try:

            resultados = list(
                ddgs.text(
                    consulta,
                    max_results=5
                )
            )

        except Exception:

            continue

        for resultado in resultados:

            url = (
                resultado.get("href")
                or resultado.get("url")
                or ""
            )

            if "linkedin.com/in/" not in url:
                continue

            texto = normalizar(
                (
                    resultado.get("title", "")
                    + " "
                    + resultado.get("body", "")
                )
            )

            nome_n = normalizar(
                nome
            )

            partes = nome_n.split()

            if not partes:
                continue

            primeiro = partes[0]
            ultimo = partes[-1]

            if (
                primeiro in texto
                or
                ultimo in texto
            ):

                return url

        pausa()

    return None


# ============================================================
# ENRIQUECER LEAD
# ============================================================

def enriquecer_lead(
    ddgs,
    lead_id,
    nome
):

    print(
        f"   🔍 Procurando contato: {nome}",
        flush=True
    )

    instagram = buscar_instagram(
        ddgs,
        nome
    )

    if instagram:

        stats[
            "instagram_encontrado"
        ] += 1

        print(
            f"   📸 Instagram: {instagram}",
            flush=True
        )

        atualizar_contato(
            lead_id,
            instagram=instagram
        )

        return

    print(
        "   📸 Instagram não encontrado",
        flush=True
    )

    linkedin = buscar_linkedin(
        ddgs,
        nome
    )

    if linkedin:

        stats[
            "linkedin_encontrado"
        ] += 1

        print(
            f"   💼 LinkedIn encontrado",
            flush=True
        )

        atualizar_contato(
            lead_id,
            linkedin=linkedin
        )

    else:

        print(
            "   💼 LinkedIn não encontrado",
            flush=True
        )


# ============================================================
# FONTE OFICIAL MACKENZIE
# ============================================================

def extrair_tcc_2026():

    print("")
    print(
        "📚 Fonte oficial Mackenzie - TCC 2026.1",
        flush=True
    )

    try:

        resposta = requests.get(
            URL_TCC_2026,
            timeout=30,
            headers={
                "User-Agent":
                    "Mozilla/5.0"
            }
        )

        resposta.raise_for_status()

    except Exception as erro:

        print(
            f"❌ Falha ao abrir fonte oficial: {erro}",
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
        inicio + 15000
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

        partes = re.split(
            r"\s+E\s+",
            bloco
        )

        for nome in partes:

            nome = nome.strip().title()

            if nome_valido(nome):

                nomes.append(
                    nome
                )

    nomes = list(
        dict.fromkeys(
            nomes
        )
    )

    stats[
        "nomes_encontrados"
    ] += len(
        nomes
    )

    print(
        f"👥 Pessoas encontradas: {len(nomes)}",
        flush=True
    )

    return nomes


# ============================================================
# BUSCA COMPLEMENTAR
# ============================================================

def identificar_ano(texto):

    t = normalizar(
        texto
    )

    if "2026" in t:
        return 2026

    if "2025" in t:
        return 2025

    return None


def identificar_periodo(texto):

    t = normalizar(
        texto
    )

    if "8º semestre" in t or "8o semestre" in t:
        return "8º semestre"

    if "7º semestre" in t or "7o semestre" in t:
        return "7º semestre"

    if "tcc" in t:
        return "TCC"

    if "colacao" in t:
        return "formada/o"

    if "formanda" in t or "formando" in t:
        return "formanda/o"

    if "estagio obrigatorio" in t:
        return "estágio obrigatório"

    return "2025/2026"


def extrair_nome_resultado(
    resultado
):

    titulo = (
        resultado.get(
            "title",
            ""
        )
    )

    titulo = re.sub(
        r"\s*[-|–].*$",
        "",
        titulo
    ).strip()

    titulo = re.sub(
        r"\s+\|\s+LinkedIn.*$",
        "",
        titulo,
        flags=re.I
    )

    if nome_valido(
        titulo
    ):

        return titulo

    return None


def buscar_complementares(
    ddgs
):

    print("")
    print(
        "🌐 Busca complementar 2025/2026",
        flush=True
    )

    candidatos = []

    for consulta in CONSULTAS:

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
                f"⚠️ Busca falhou: {erro}",
                flush=True
            )

            stats["erros"] += 1
            continue

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

            nt = normalizar(
                texto
            )

            # precisa ter nutrição + Mackenzie
            if (
                "nutricao"
                not in nt
            ):
                continue

            if (
                "mackenzie"
                not in nt
            ):
                continue

            ano = identificar_ano(
                texto
            )

            # aceita 2025/2026 ou sinais claros de fase final
            periodo = identificar_periodo(
                texto
            )

            fase_final = any(
                termo in nt
                for termo in [
                    "7º semestre",
                    "7o semestre",
                    "8º semestre",
                    "8o semestre",
                    "tcc",
                    "formanda",
                    "formando",
                    "colacao",
                    "estagio obrigatorio",
                ]
            )

            if (
                ano not in [
                    2025,
                    2026
                ]
                and
                not fase_final
            ):
                continue

            nome = extrair_nome_resultado(
                resultado
            )

            if not nome:
                continue

            candidatos.append(
                {
                    "nome":
                        nome,

                    "ano":
                        ano or 2026,

                    "periodo":
                        periodo,

                    "fonte_url":
                        url,

                    "evidencia":
                        texto[:1000],
                }
            )

        pausa()

    # remove repetidos
    unicos = {}

    for candidato in candidatos:

        chave = normalizar(
            candidato["nome"]
        )

        if chave not in unicos:

            unicos[chave] = candidato

    resultado = list(
        unicos.values()
    )

    stats[
        "nomes_encontrados"
    ] += len(
        resultado
    )

    print(
        f"👥 Candidatos complementares: {len(resultado)}",
        flush=True
    )

    return resultado


# ============================================================
# CHECKPOINT
# ============================================================

def salvar_checkpoint():

    try:

        existente = (
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
                stats[
                    "nomes_encontrados"
                ],

            "leads_salvos":
                stats[
                    "salvos"
                ],

            "atualizado_em":
                agora(),

            "finalizado_em":
                agora(),
        }

        if existente.data:

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
                    existente.data[0]["id"]
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
            f"⚠️ Checkpoint falhou: {erro}",
            flush=True
        )


# ============================================================
# EXECUÇÃO
# ============================================================

def executar():

    print("")
    print(
        "=" * 60,
        flush=True
    )

    print(
        "CAPTAÇÃO MACKENZIE - NUTRIÇÃO 2025/2026",
        flush=True
    )

    print(
        "=" * 60,
        flush=True
    )

    nomes_oficiais = extrair_tcc_2026()

    with DDGS() as ddgs:

        # ----------------------------------------------------
        # FONTE OFICIAL
        # ----------------------------------------------------

        for nome in nomes_oficiais:

            lead_id = salvar_lead(
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

            enriquecer_lead(
                ddgs,
                lead_id,
                nome
            )

            pausa()

        # ----------------------------------------------------
        # COMPLEMENTARES
        # ----------------------------------------------------

        complementares = buscar_complementares(
            ddgs
        )

        for candidato in complementares:

            lead_id = salvar_lead(

                nome=
                    candidato[
                        "nome"
                    ],

                ano=
                    candidato[
                        "ano"
                    ],

                periodo=
                    candidato[
                        "periodo"
                    ],

                evidencia=
                    candidato[
                        "evidencia"
                    ],

                fonte_url=
                    candidato[
                        "fonte_url"
                    ],

                origem=
                    "busca_publica_mackenzie_2025_2026"
            )

            enriquecer_lead(
                ddgs,
                lead_id,
                candidato[
                    "nome"
                ]
            )

            pausa()

    salvar_checkpoint()

    print("")
    print(
        "=" * 60,
        flush=True
    )

    print(
        "RESUMO",
        flush=True
    )

    print(
        "=" * 60,
        flush=True
    )

    print(
        f"Nomes encontrados: "
        f"{stats['nomes_encontrados']}",
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
        f"Instagram encontrados: "
        f"{stats['instagram_encontrado']}",
        flush=True
    )

    print(
        f"LinkedIn encontrados: "
        f"{stats['linkedin_encontrado']}",
        flush=True
    )

    print(
        f"Erros: "
        f"{stats['erros']}",
        flush=True
    )

    print(
        "=" * 60,
        flush=True
    )


if __name__ == "__main__":

    executar()

    print(
        "✅ PROCESSAMENTO FINALIZADO",
        flush=True
    )
