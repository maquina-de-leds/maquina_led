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
# MACKENZIE
# ============================================================

FACULDADE = {
    "nome": "Universidade Presbiteriana Mackenzie",
    "sigla": "Mackenzie",
    "cidade": "São Paulo",
    "estado": "SP",
}

URL_TCC = (
    "https://www.mackenzie.br/"
    "universidade/unidades-academicas/"
    "ccbs/tcc-e-pesquisa/mostra-de-tcc"
)


# ============================================================
# CONFIGURAÇÕES
# ============================================================

ETAPA = "expansao_mackenzie_2026"

SEMENTES_POR_EXECUCAO = 5

MAX_RELACIONADOS_POR_SEMENTE = 3

MAX_RESULTADOS_POR_BUSCA = 10

MAX_NOVOS_POR_EXECUCAO = 20

PAUSA_MIN = 3
PAUSA_MAX = 5


stats = {
    "sementes_processadas": 0,
    "buscas": 0,
    "resultados": 0,
    "perfis_enriquecidos": 0,
    "novos_relacionados": 0,
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
# EXTRAÇÃO DA LISTA OFICIAL
# ============================================================

def extrair_sementes_oficiais():

    resposta = requests.get(
        URL_TCC,
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

    dentro = False

    for linha in linhas:

        n = normalizar(linha)

        if "nutricao 2026.1" in n:

            dentro = True
            continue

        if dentro and any(
            curso in n
            for curso in [
                "fisioterapia",
                "psicologia",
                "farmacia",
            ]
        ):

            break

        if not dentro:
            continue

        match = re.match(
            r"^\d{1,2}\s*-\s*(.+)$",
            linha
        )

        if not match:
            continue

        bloco = match.group(1)

        partes = re.split(
            r"\s+e\s+",
            bloco,
            flags=re.I
        )

        for parte in partes:

            nome = re.sub(
                r"\s+",
                " ",
                parte
            ).strip(" -")

            if nome_parece_pessoa(nome):

                nomes.append(nome)

    return list(
        dict.fromkeys(nomes)
    )


# ============================================================
# NOME DE PESSOA
# ============================================================

def nome_parece_pessoa(nome):

    if not nome:
        return False

    nome = nome.strip()

    if len(nome) < 5:
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
        "faculdade",
        "nutricao mackenzie",
        "curso de nutricao",
        "departamento",
        "turma",
        "formatura",
        "comissao",
        "atletica",
        "instituto",
        "escola",
        "anhanguera",
        "linkedin",
        "instagram",
    ]

    if any(
        termo in n
        for termo in proibidos
    ):
        return False

    return True


# ============================================================
# CHECKPOINT DA EXPANSÃO
# ============================================================

def buscar_checkpoint():

    try:

        resposta = (
            supabase
            .table("controle_busca")
            .select("*")
            .eq("etapa", ETAPA)
            .limit(1)
            .execute()
        )

        if resposta.data:
            return resposta.data[0]

        return None

    except Exception as erro:

        print(
            f"⚠️ Erro checkpoint: {erro}"
        )

        return None


def indice_atual():

    checkpoint = buscar_checkpoint()

    if not checkpoint:
        return 0

    valor = checkpoint.get(
        "indice_pesquisa"
    )

    if valor is None:
        return 0

    return int(valor)


def salvar_checkpoint(
    indice,
    nome_atual,
    status
):

    atual = buscar_checkpoint()

    dados = {
        "estado": "SP",
        "cidade": "São Paulo",
        "instituicao":
            FACULDADE["nome"],
        "etapa": ETAPA,
        "status": status,
        "indice_pesquisa": indice,
        "consulta_atual": nome_atual,
        "fonte_atual":
            "expansao_por_lead",
        "atualizado_em": agora(),
    }

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

            dados[
                "iniciado_em"
            ] = agora()

            (
                supabase
                .table("controle_busca")
                .insert(dados)
                .execute()
            )

    except Exception as erro:

        print(
            f"⚠️ Erro salvando checkpoint: "
            f"{erro}"
        )

        stats["erros"] += 1


# ============================================================
# BUSCA
# ============================================================

def pesquisar(
    ddgs,
    consulta
):

    stats["buscas"] += 1

    print(
        f"   🔎 {consulta}"
    )

    try:

        resultados = list(
            ddgs.text(
                consulta,
                max_results=
                    MAX_RESULTADOS_POR_BUSCA
            )
        )

        stats[
            "resultados"
        ] += len(resultados)

        return resultados

    except Exception as erro:

        mensagem = str(erro)

        if (
            "No results found"
            in mensagem
        ):
            return []

        print(
            f"   ⚠️ Busca falhou: "
            f"{mensagem}"
        )

        stats["erros"] += 1

        return []


# ============================================================
# IDENTIFICAR PERFIL
# ============================================================

def identificar_perfil(url):

    if not url:
        return None, None

    try:

        parsed = urlparse(url)

        host = (
            parsed.netloc
            .lower()
            .replace("www.", "")
        )

        if (
            "linkedin.com"
            in host
            and "/in/"
            in parsed.path
        ):

            if (
                host == "linkedin.com"
                or
                host.startswith(
                    "br.linkedin.com"
                )
            ):

                return (
                    "linkedin",
                    url
                )

        if "instagram.com" in host:

            partes = [
                p
                for p
                in parsed.path.split("/")
                if p
            ]

            if not partes:
                return None, None

            usuario = partes[0]

            bloqueados = {
                "p",
                "reel",
                "reels",
                "stories",
                "explore",
                "accounts",
                "direct",
            }

            if usuario.lower() in bloqueados:
                return None, None

            return (
                "instagram",
                "@"
                + usuario
            )

    except Exception:
        pass

    return None, None


# ============================================================
# PROVAS
# ============================================================

def tem_nutricao(texto):

    t = normalizar(texto)

    return (
        "nutricao" in t
        or
        "nutricionista" in t
    )


def tem_mackenzie(texto):

    t = normalizar(texto)

    return (
        "universidade presbiteriana mackenzie"
        in t
        or
        (
            "mackenzie" in t
            and
            (
                "sao paulo" in t
                or
                "higienopolis" in t
            )
        )
    )


def tem_fase_alvo(texto):

    t = normalizar(texto)

    sinais = [
        "2025",
        "2026",
        "7 semestre",
        "7 periodo",
        "8 semestre",
        "8 periodo",
        "tcc",
        "trabalho de conclusao",
        "estagio obrigatorio",
        "estagio curricular",
        "formanda",
        "formando",
        "formatura",
        "colacao",
        "recem-formada",
        "recem-formado",
    ]

    return any(
        sinal in t
        for sinal in sinais
    )


# ============================================================
# EXTRAIR NOME DO TÍTULO
# ============================================================

def extrair_nome_titulo(titulo):

    if not titulo:
        return ""

    nome = titulo.strip()

    nome = re.sub(
        r"\s*[|–—]\s*LinkedIn.*$",
        "",
        nome,
        flags=re.I
    )

    nome = re.sub(
        r"\s*\(@[^)]+\).*$",
        "",
        nome
    )

    partes = re.split(
        r"\s+-\s+",
        nome,
        maxsplit=1
    )

    nome = partes[0]

    nome = re.sub(
        r"\s+",
        " ",
        nome
    )

    return nome.strip()


# ============================================================
# BUSCAR LEAD NO BANCO
# ============================================================

def buscar_lead(nome):

    try:

        resposta = (
            supabase
            .table("leds")
            .select("*")
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

        if resposta.data:
            return resposta.data[0]

        return None

    except Exception:

        return None


# ============================================================
# ENRIQUECER SEMENTE
# ============================================================

def enriquecer_semente(
    ddgs,
    nome
):

    lead = buscar_lead(nome)

    if not lead:
        return

    linkedin_atual = lead.get(
        "linkedin"
    )

    instagram_atual = lead.get(
        "instagram"
    )

    consultas = [

        (
            f'"{nome}" '
            f'"Mackenzie" '
            f'"Nutrição" '
            f'site:linkedin.com/in'
        ),

        (
            f'"{nome}" '
            f'"Mackenzie" '
            f'"Nutrição" '
            f'site:instagram.com'
        ),
    ]

    linkedin_novo = None
    instagram_novo = None

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
                or
                resultado.get("url")
                or ""
            )

            texto = (
                f"{titulo} {corpo}"
            )

            # nome precisa aparecer
            if (
                normalizar(nome)
                not in normalizar(texto)
            ):
                continue

            if not tem_nutricao(texto):
                continue

            if not tem_mackenzie(texto):
                continue

            tipo, perfil = (
                identificar_perfil(url)
            )

            if (
                tipo == "linkedin"
                and not linkedin_atual
            ):
                linkedin_novo = perfil

            if (
                tipo == "instagram"
                and not instagram_atual
            ):
                instagram_novo = perfil

        pausa()

    dados = {}

    if linkedin_novo:
        dados["linkedin"] = linkedin_novo

    if instagram_novo:
        dados["instagram"] = instagram_novo

    if dados:

        try:

            (
                supabase
                .table("leds")
                .update(dados)
                .eq(
                    "id",
                    lead["id"]
                )
                .execute()
            )

            stats[
                "perfis_enriquecidos"
            ] += 1

            print(
                f"   🔗 Perfil enriquecido"
            )

        except Exception as erro:

            print(
                f"   ⚠️ Erro enriquecendo: "
                f"{erro}"
            )


# ============================================================
# DUPLICIDADE
# ============================================================

def candidato_existe(
    nome,
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

    except Exception:

        return False


# ============================================================
# SALVAR RELACIONADO
# ============================================================

def salvar_relacionado(
    nome,
    semente,
    url,
    evidencia,
    linkedin=None,
    instagram=None
):

    if candidato_existe(
        nome,
        linkedin,
        instagram
    ):

        stats["duplicados"] += 1
        return False

    dados = {

        "nome": nome,

        "instagram": instagram,

        "linkedin": linkedin,

        "whatsapp": None,

        "nicho": "nutricionista",

        "origem":
            "expansao_lead_mackenzie",

        "origem_lead":
            "rede_academica",

        "lead_origem":
            semente,

        "nivel_rede": 1,

        "rede_processada": False,

        "status": "novo",

        "app_baixado": False,

        "nao_contatar": False,

        "qualificado": True,

        "cliente": False,

        "tentativas_contato": 0,

        "cidade":
            FACULDADE["cidade"],

        "estado":
            FACULDADE["estado"],

        "instituicao":
            FACULDADE["nome"],

        "ano_alvo": 2026,

        "periodo_alvo":
            "fase final / rede acadêmica",

        "pontuacao": 8,

        "evidencia": evidencia,

        "fonte_url": url,

        "fonte_validacao":
            "busca relacionada a aluno oficial",
    }

    try:

        (
            supabase
            .table("leds")
            .insert(dados)
            .execute()
        )

        stats[
            "novos_relacionados"
        ] += 1

        print(
            f"   ✅ NOVO RELACIONADO: "
            f"{nome}"
        )

        return True

    except Exception as erro:

        print(
            f"   ❌ Erro salvando "
            f"{nome}: {erro}"
        )

        stats["erros"] += 1

        return False


# ============================================================
# DESCOBRIR RELACIONADOS
# ============================================================

def descobrir_relacionados(
    ddgs,
    semente
):

    consultas = [

        (
            f'"{semente}" '
            f'"Mackenzie" '
            f'"Nutrição" '
            f'TCC 2026'
        ),

        (
            f'"{semente}" '
            f'"Mackenzie" '
            f'"Nutrição" '
            f'formatura 2026'
        ),

        (
            f'"{semente}" '
            f'"Mackenzie" '
            f'"Nutrição" '
            f'estágio 2026'
        ),
    ]

    encontrados = 0

    for consulta in consultas:

        if (
            encontrados
            >= MAX_RELACIONADOS_POR_SEMENTE
        ):
            break

        if (
            stats["novos_relacionados"]
            >= MAX_NOVOS_POR_EXECUCAO
        ):
            break

        resultados = pesquisar(
            ddgs,
            consulta
        )

        for resultado in resultados:

            if (
                encontrados
                >= MAX_RELACIONADOS_POR_SEMENTE
            ):
                break

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
                or
                resultado.get("url")
                or ""
            )

            texto = (
                f"{titulo} {corpo}"
            )

            if not tem_nutricao(texto):

                stats[
                    "rejeitados"
                ] += 1

                continue

            if not tem_mackenzie(texto):

                stats[
                    "rejeitados"
                ] += 1

                continue

            if not tem_fase_alvo(texto):

                stats[
                    "rejeitados"
                ] += 1

                continue

            nome = extrair_nome_titulo(
                titulo
            )

            if not nome_parece_pessoa(nome):

                stats[
                    "rejeitados"
                ] += 1

                continue

            if (
                normalizar(nome)
                == normalizar(semente)
            ):
                continue

            tipo, perfil = (
                identificar_perfil(url)
            )

            linkedin = None
            instagram = None

            if tipo == "linkedin":
                linkedin = perfil

            if tipo == "instagram":
                instagram = perfil

            evidencia = (
                f"Relacionado a {semente} | "
                f"Mackenzie | Nutrição | "
                f"fase final 2025/2026"
            )

            salvo = salvar_relacionado(
                nome=nome,
                semente=semente,
                url=url,
                evidencia=evidencia,
                linkedin=linkedin,
                instagram=instagram
            )

            if salvo:

                encontrados += 1

        pausa()


# ============================================================
# EXECUTAR
# ============================================================

def executar():

    print("")
    print(
        "=" * 65
    )

    print(
        "EXPANSÃO MACKENZIE"
    )

    print(
        "LEAD OFICIAL → ENRIQUECE → "
        "PROCURA NOVOS LEADS"
    )

    print(
        "=" * 65
    )

    sementes = (
        extrair_sementes_oficiais()
    )

    print(
        f"👥 Sementes oficiais encontradas: "
        f"{len(sementes)}"
    )

    indice = indice_atual()

    if indice >= len(sementes):

        print("")
        print(
            "✅ Todas as sementes já foram "
            "processadas."
        )

        return

    fim = min(
        indice
        + SEMENTES_POR_EXECUCAO,
        len(sementes)
    )

    lote = sementes[
        indice:fim
    ]

    print(
        f"📦 Processando sementes "
        f"{indice + 1} até {fim}"
    )

    print("")

    with DDGS() as ddgs:

        for posicao, semente in enumerate(
            lote,
            start=indice + 1
        ):

            print(
                "-" * 65
            )

            print(
                f"🌱 SEMENTE "
                f"{posicao}/{len(sementes)}"
            )

            print(
                f"   {semente}"
            )

            salvar_checkpoint(
                posicao - 1,
                semente,
                "processando"
            )

            enriquecer_semente(
                ddgs,
                semente
            )

            descobrir_relacionados(
                ddgs,
                semente
            )

            stats[
                "sementes_processadas"
            ] += 1

            salvar_checkpoint(
                posicao,
                semente,
                "pendente"
            )

            if (
                stats["novos_relacionados"]
                >= MAX_NOVOS_POR_EXECUCAO
            ):

                print("")
                print(
                    "🛑 Limite de novos leads "
                    "desta execução atingido."
                )

                break

    print("")
    print(
        "=" * 65
    )

    print(
        "RESUMO"
    )

    print(
        "=" * 65
    )

    print(
        f"Sementes processadas: "
        f"{stats['sementes_processadas']}"
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
        f"Perfis enriquecidos: "
        f"{stats['perfis_enriquecidos']}"
    )

    print(
        f"Novos relacionados: "
        f"{stats['novos_relacionados']}"
    )

    print(
        f"Duplicados: "
        f"{stats['duplicados']}"
    )

    print(
        f"Rejeitados: "
        f"{stats['rejeitados']}"
    )

    print(
        f"Erros: "
        f"{stats['erros']}"
    )

    print(
        "=" * 65
    )


# ============================================================
# INÍCIO
# ============================================================

if __name__ == "__main__":

    executar()
