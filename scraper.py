import os
import re
import unicodedata
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from supabase import create_client


print("🚀 SCRAPER SEGURO MACKENZIE INICIADO", flush=True)


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
}

URL_TCC_2026_1 = (
    "https://www.mackenzie.br/"
    "universidade/unidades-academicas/"
    "ccbs/tcc-e-pesquisa/mostra-de-tcc"
)


stats = {
    "fontes_processadas": 0,
    "nomes_extraidos": 0,
    "salvos": 0,
    "duplicados": 0,
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


# ============================================================
# NOME PARECE PESSOA
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

    palavras = nome.split()

    if len(palavras) < 2:
        return False

    if len(palavras) > 8:
        return False

    proibidos = [
        "universidade",
        "faculdade",
        "curso",
        "nutricao",
        "reitoria",
        "coordenadoria",
        "departamento",
        "laboratorio",
        "programa",
        "campus",
        "graduacao",
        "pos",
        "pesquisa",
        "atendimento",
    ]

    n = normalizar(nome)

    if any(
        palavra in n
        for palavra in proibidos
    ):
        return False

    return True


# ============================================================
# EXTRAÇÃO EXCLUSIVA DA MOSTRA DE TCC
# ============================================================

def extrair_tcc_2026_1():

    print(
        "📚 Processando fonte oficial TCC 2026.1",
        flush=True
    )

    resposta = requests.get(
        URL_TCC_2026_1,
        timeout=40,
        headers={
            "User-Agent": "Mozilla/5.0"
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
        in soup.get_text("\n").splitlines()
        if linha.strip()
    ]

    nomes = []

    dentro_nutricao = False
    contador_trabalhos = 0

    for linha in linhas:

        linha_norm = normalizar(
            linha
        )

        # começa exatamente na seção Nutrição 2026.1
        if (
            linha_norm
            == "nutricao 2026.1"
        ):

            dentro_nutricao = True

            continue

        if not dentro_nutricao:

            continue

        # só aceita linhas numeradas 01 até 19
        match = re.match(
            r"^(\d{1,2})\s*-\s*(.+)$",
            linha
        )

        if not match:

            continue

        numero = int(
            match.group(1)
        )

        if numero < 1 or numero > 19:

            continue

        contador_trabalhos += 1

        bloco_nomes = (
            match
            .group(2)
            .strip()
        )

        # separa os trabalhos em dupla
        partes = re.split(
            r"\s+e\s+",
            bloco_nomes,
            flags=re.I
        )

        for parte in partes:

            nome = re.sub(
                r"\s+",
                " ",
                parte
            ).strip(
                " -"
            )

            if nome_parece_pessoa(
                nome
            ):

                nomes.append(
                    nome
                )

        # depois do trabalho 19, encerra
        if numero == 19:

            break

    nomes = list(
        dict.fromkeys(
            nomes
        )
    )

    print(
        f"   Trabalhos encontrados: "
        f"{contador_trabalhos}",
        flush=True
    )

    print(
        f"   Pessoas encontradas: "
        f"{len(nomes)}",
        flush=True
    )

    return nomes


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

        stats[
            "erros"
        ] += 1

        return None


# ============================================================
# SALVAR
# ============================================================

def salvar_lead(
    nome
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
            "fonte_academica_oficial",

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
            2026,

        "periodo_alvo":
            "TCC 2026.1",

        "pontuacao":
            10,

        "evidencia":
            (
                "Fonte oficial Mackenzie | "
                "Nutrição | "
                "TCC 2026.1"
            ),

        "fonte_url":
            URL_TCC_2026_1,

        "fonte_validacao":
            "Mostra de TCC oficial Mackenzie",
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
            f"{nome}",
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

        stats[
            "erros"
        ] += 1

        return False


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
        "MACKENZIE — EXTRAÇÃO SEGURA",
        flush=True
    )

    print(
        "SOMENTE FONTES COM ESTRUTURA VALIDADA",
        flush=True
    )

    print(
        "=" * 65,
        flush=True
    )

    nomes = extrair_tcc_2026_1()

    stats[
        "fontes_processadas"
    ] += 1

    stats[
        "nomes_extraidos"
    ] += len(
        nomes
    )

    for nome in nomes:

        salvar_lead(
            nome
        )

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
        f"Fontes processadas: "
        f"{stats['fontes_processadas']}",
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
