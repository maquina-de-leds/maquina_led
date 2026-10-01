import os
import re
import csv
import io
import time
import random
import zipfile
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from supabase import create_client


print("🚀 MÁQUINA 1 - CAPTAÇÃO NACIONAL DE LEADS", flush=True)


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

NICHO = "nutricao"

ETAPA = "captacao_nacional_nutricao_v1"

ANO_INICIO = 2025
ANO_FIM = 2026

MAX_RESULTADOS_BUSCA = 12

PAUSA_MIN = 2
PAUSA_MAX = 4

# Quantas faculdades cada execução trabalha antes de encerrar.
# Depois podemos aumentar.
MAX_INSTITUICOES_POR_EXECUCAO = 8


# ============================================================
# ORDEM DOS 26 ESTADOS + DF
# ============================================================

UFS_BRASIL = [
    "AC",
    "AL",
    "AP",
    "AM",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "MG",
    "PA",
    "PB",
    "PR",
    "PE",
    "PI",
    "RJ",
    "RN",
    "RS",
    "RO",
    "RR",
    "SC",
    "SP",
    "SE",
    "TO",
]


# ============================================================
# INEP
# ============================================================

INEP_PAGE = (
    "https://www.gov.br/inep/pt-br/"
    "acesso-a-informacao/dados-abertos/"
    "microdados/censo-da-educacao-superior"
)


# ============================================================
# ESTATÍSTICAS
# ============================================================

stats = {
    "estados_verificados": 0,
    "instituicoes_descobertas": 0,
    "instituicoes_processadas": 0,
    "instituicoes_concluidas": 0,
    "instituicoes_com_erro": 0,
    "leads_encontrados": 0,
    "leads_salvos": 0,
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


def pausa():

    time.sleep(
        random.uniform(
            PAUSA_MIN,
            PAUSA_MAX
        )
    )


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


def texto_limpo(texto):

    texto = str(
        texto or ""
    )

    texto = re.sub(
        r"\s+",
        " ",
        texto
    )

    return texto.strip()


# ============================================================
# NOME DE PESSOA
# ============================================================

def nome_parece_pessoa(nome):

    if not nome:
        return False

    nome = texto_limpo(
        nome
    )

    if len(nome) < 7:
        return False

    if len(nome) > 90:
        return False

    partes = nome.split()

    if len(partes) < 2:
        return False

    if len(partes) > 8:
        return False

    # não aceita números no nome
    if re.search(
        r"\d",
        nome
    ):
        return False

    t = normalizar(
        nome
    )

    proibidos = [
        "universidade",
        "faculdade",
        "centro universitario",
        "vestibular",
        "curso",
        "campus",
        "evento",
        "congresso",
        "encontro cientifico",
        "google docs",
        "pos ead",
        "pos-graduacao",
        "pos graduacao",
        "programa",
        "secretaria",
        "reitoria",
        "inscricoes",
        "processo seletivo",
        "experiencia transformadora",
        "noticia",
        "notícias",
        "edital",
        "projeto pedagogico",
        "grade curricular",
        "matriz curricular",
        "portal do aluno",
    ]

    for termo in proibidos:

        if normalizar(
            termo
        ) in t:

            return False

    # cada parte relevante precisa ter aparência de nome
    partes_validas = 0

    for parte in partes:

        parte = parte.strip(
            ".,;:-_|/"
        )

        if len(parte) >= 2:
            partes_validas += 1

    return partes_validas >= 2


# ============================================================
# ANO / PERÍODO
# ============================================================

def identificar_ano(texto):

    t = normalizar(
        texto
    )

    # IMPORTANTE:
    # 2026 tem prioridade.
    if "2026" in t:
        return 2026

    if "2025" in t:
        return 2025

    return None


def identificar_periodo(texto):

    t = normalizar(
        texto
    )

    sinais = [
        (
            "8º semestre/período",
            [
                "8º semestre",
                "8o semestre",
                "8 semestre",
                "8º periodo",
                "8o periodo",
                "8 periodo",
                "8/8",
                "8 de 8",
            ]
        ),
        (
            "7º semestre/período",
            [
                "7º semestre",
                "7o semestre",
                "7 semestre",
                "7º periodo",
                "7o periodo",
                "7 periodo",
                "7/8",
                "7 de 8",
            ]
        ),
        (
            "TCC",
            [
                "tcc",
                "trabalho de conclusao",
            ]
        ),
        (
            "estágio obrigatório/final",
            [
                "estagio obrigatorio",
                "estagio supervisionado",
                "estagio curricular",
                "estagio final",
            ]
        ),
        (
            "formando",
            [
                "formanda",
                "formando",
                "formandas",
                "formandos",
                "concluinte",
            ]
        ),
        (
            "formado",
            [
                "recem-formada",
                "recem-formado",
                "graduada em nutricao",
                "graduado em nutricao",
                "formatura",
                "colacao de grau",
                "colacao",
            ]
        ),
    ]

    for periodo, termos in sinais:

        for termo in termos:

            if normalizar(
                termo
            ) in t:

                return periodo

    return None


# ============================================================
# VALIDAÇÃO DO LEAD
# ============================================================

def resultado_valido(
    texto,
    instituicao
):

    t = normalizar(
        texto
    )

    if (
        "nutricao"
        not in t
        and
        "nutricionista"
        not in t
    ):
        return False

    # Confirma vínculo com a instituição usando palavras
    # relevantes do nome da faculdade.
    palavras_inst = [
        p
        for p in normalizar(
            instituicao
        ).split()
        if len(p) >= 5
        and p not in [
            "universidade",
            "faculdade",
            "centro",
            "universitario",
        ]
    ]

    if palavras_inst:

        if not any(
            p in t
            for p in palavras_inst
        ):
            return False

    ano = identificar_ano(
        texto
    )

    periodo = identificar_periodo(
        texto
    )

    # REGRA PRINCIPAL
    if ano in [
        2025,
        2026
    ]:
        return True

    if periodo:
        return True

    return False


# ============================================================
# EXTRAIR NOME DO RESULTADO
# ============================================================

def extrair_nome_resultado(
    resultado
):

    titulo = texto_limpo(
        resultado.get(
            "title",
            ""
        )
    )

    if not titulo:
        return None

    # LinkedIn
    titulo = re.sub(
        r"\s*\|\s*LinkedIn.*$",
        "",
        titulo,
        flags=re.I
    )

    titulo = re.sub(
        r"\s*-\s*LinkedIn.*$",
        "",
        titulo,
        flags=re.I
    )

    # Remove descrições comuns após o nome
    titulo = re.sub(
        r"\s+[-–|]\s+"
        r"(Nutrição|Nutricionista|Graduanda|Graduando|"
        r"Estudante|Acadêmica|Acadêmico|"
        r"Universidade|Faculdade).*$",
        "",
        titulo,
        flags=re.I
    )

    titulo = texto_limpo(
        titulo
    )

    if nome_parece_pessoa(
        titulo
    ):

        return titulo

    return None


# ============================================================
# INSTAGRAM OPCIONAL
#
# IMPORTANTE:
# NÃO É CRITÉRIO PARA SALVAR O LEAD.
# Só aproveitamos se o próprio resultado já trouxer.
# ============================================================

def extrair_instagram_do_resultado(
    resultado
):

    texto = (
        str(
            resultado.get(
                "title",
                ""
            )
        )
        + " "
        + str(
            resultado.get(
                "body",
                ""
            )
        )
        + " "
        + str(
            resultado.get(
                "href",
                ""
            )
        )
    )

    # URL Instagram
    m = re.search(
        r"instagram\.com/([A-Za-z0-9._]+)",
        texto,
        flags=re.I
    )

    if m:

        usuario = m.group(1)

        proibidos = [
            "p",
            "reel",
            "reels",
            "stories",
            "explore",
            "accounts",
        ]

        if usuario.lower() not in proibidos:

            return (
                "@"
                + usuario
            )

    return None


# ============================================================
# DUPLICIDADE
# ============================================================

def buscar_lead_existente(
    nome,
    instituicao
):

    try:

        resposta = (
            supabase
            .table("leds")
            .select(
                "id,nome,instituicao"
            )
            .eq(
                "instituicao",
                instituicao
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
            f"      ⚠️ Erro verificando duplicidade: {erro}",
            flush=True
        )

        stats["erros"] += 1

        return None


# ============================================================
# SALVAR LEAD IMEDIATAMENTE
# ============================================================

def salvar_lead(
    nome,
    instituicao,
    cidade,
    estado,
    ano,
    periodo,
    evidencia,
    fonte_url,
    instagram=None
):

    existente = buscar_lead_existente(
        nome,
        instituicao
    )

    if existente:

        stats[
            "duplicados"
        ] += 1

        print(
            f"      ♻️ Duplicado ignorado: {nome}",
            flush=True
        )

        return False

    dados = {

        "nome":
            nome,

        "instagram":
            instagram,

        "linkedin":
            None,

        "whatsapp":
            None,

        "nicho":
            "nutricionista",

        "origem":
            "captacao_nacional",

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
            cidade,

        "estado":
            estado,

        "instituicao":
            instituicao,

        "ano_alvo":
            ano,

        "periodo_alvo":
            periodo or "2025/2026",

        "pontuacao":
            10,

        "evidencia":
            evidencia[:1500],

        "fonte_url":
            fonte_url,

        "fonte_validacao":
            "busca_publica",

        "proxima_acao":
            (
                "primeiro_contato_instagram"
                if instagram
                else "buscar_instagram"
            ),

        "rede_processada":
            False,

        "nivel_rede":
            0,
    }

    try:

        (
            supabase
            .table("leds")
            .insert(
                dados
            )
            .execute()
        )

        stats[
            "leads_salvos"
        ] += 1

        if instagram:

            print(
                f"      ✅ LEAD SALVO: "
                f"{nome} | {instagram}",
                flush=True
            )

        else:

            print(
                f"      ✅ LEAD SALVO: "
                f"{nome} | Instagram pendente",
                flush=True
            )

        return True

    except Exception as erro:

        print(
            f"      ❌ Erro salvando {nome}: {erro}",
            flush=True
        )

        stats["erros"] += 1

        return False


# ============================================================
# FILA DE INSTITUIÇÕES
# ============================================================

def buscar_instituicao_existente(
    estado,
    instituicao
):

    try:

        resposta = (
            supabase
            .table(
                "instituicoes_nutricao"
            )
            .select("*")
            .eq(
                "estado",
                estado
            )
            .eq(
                "instituicao",
                instituicao
            )
            .limit(1)
            .execute()
        )

        if resposta.data:
            return resposta.data[0]

        return None

    except Exception:

        return None


def inserir_instituicao(
    estado,
    cidade,
    instituicao,
    origem,
    fonte_url=None
):

    instituicao = texto_limpo(
        instituicao
    )

    if not instituicao:
        return

    existente = buscar_instituicao_existente(
        estado,
        instituicao
    )

    if existente:
        return

    dados = {

        "estado":
            estado,

        "cidade":
            cidade,

        "instituicao":
            instituicao,

        "curso":
            "Nutrição",

        "origem":
            origem,

        "fonte_url":
            fonte_url,

        "status":
            "pendente",

        "fonte_validacao":
            origem,

        "validada":
            True,

        "tentativa_descoberta":
            0,
    }

    try:

        (
            supabase
            .table(
                "instituicoes_nutricao"
            )
            .insert(
                dados
            )
            .execute()
        )

        stats[
            "instituicoes_descobertas"
        ] += 1

        print(
            f"      ➕ Faculdade adicionada: {instituicao}",
            flush=True
        )

    except Exception as erro:

        print(
            f"      ⚠️ Não foi possível adicionar "
            f"{instituicao}: {erro}",
            flush=True
        )


# ============================================================
# INEP - DESCOBRIR LINK DO MICRODADO
# ============================================================

def descobrir_zip_inep():

    print(
        "   📚 Tentando base oficial Inep...",
        flush=True
    )

    try:

        resposta = requests.get(
            INEP_PAGE,
            timeout=45,
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

        links = soup.find_all(
            "a",
            href=True
        )

        candidatos = []

        for link in links:

            texto = normalizar(
                link.get_text(
                    " ",
                    strip=True
                )
            )

            href = link.get(
                "href",
                ""
            )

            conjunto = normalizar(
                texto
                + " "
                + href
            )

            if (
                "2024"
                in conjunto
                and
                (
                    "microdados"
                    in conjunto
                    or
                    ".zip"
                    in conjunto
                )
            ):

                candidatos.append(
                    urljoin(
                        INEP_PAGE,
                        href
                    )
                )

        for url in candidatos:

            if ".zip" in url.lower():

                return url

        if candidatos:

            return candidatos[0]

    except Exception as erro:

        print(
            f"   ⚠️ Inep indisponível: {erro}",
            flush=True
        )

    return None


# ============================================================
# LOCALIZAR COLUNAS DO CSV
# ============================================================

def achar_coluna(
    colunas,
    possibilidades
):

    mapa = {
        normalizar(
            coluna
        ):
        coluna
        for coluna in colunas
    }

    for desejada in possibilidades:

        desejada_n = normalizar(
            desejada
        )

        for normalizada, original in mapa.items():

            if (
                desejada_n
                ==
                normalizada
                or
                desejada_n
                in normalizada
            ):

                return original

    return None


# ============================================================
# EXTRAIR FACULDADES DO INEP
# ============================================================

def carregar_instituicoes_inep():

    url = descobrir_zip_inep()

    if not url:

        return []

    print(
        f"   ⬇️ Baixando base oficial...",
        flush=True
    )

    try:

        resposta = requests.get(
            url,
            timeout=120,
            headers={
                "User-Agent":
                    "Mozilla/5.0"
            }
        )

        resposta.raise_for_status()

        conteudo = resposta.content

        if not zipfile.is_zipfile(
            io.BytesIO(
                conteudo
            )
        ):

            print(
                "   ⚠️ Link do Inep não retornou ZIP.",
                flush=True
            )

            return []

        resultados = []

        with zipfile.ZipFile(
            io.BytesIO(
                conteudo
            )
        ) as arquivo_zip:

            nomes = arquivo_zip.namelist()

            csvs = [
                nome
                for nome in nomes
                if nome.lower().endswith(
                    ".csv"
                )
                and
                (
                    "curso"
                    in normalizar(nome)
                    or
                    "microdados"
                    in normalizar(nome)
                )
            ]

            if not csvs:

                csvs = [
                    nome
                    for nome in nomes
                    if nome.lower().endswith(
                        ".csv"
                    )
                ]

            for nome_csv in csvs:

                try:

                    bruto = arquivo_zip.read(
                        nome_csv
                    )

                    texto = None

                    for encoding in [
                        "latin1",
                        "utf-8-sig",
                        "utf-8",
                    ]:

                        try:

                            texto = bruto.decode(
                                encoding
                            )

                            break

                        except Exception:

                            continue

                    if not texto:
                        continue

                    primeira = texto.splitlines()[
                        0
                    ]

                    separador = (
                        ";"
                        if primeira.count(";")
                        >= primeira.count(",")
                        else ","
                    )

                    leitor = csv.DictReader(
                        io.StringIO(
                            texto
                        ),
                        delimiter=separador
                    )

                    colunas = leitor.fieldnames or []

                    col_curso = achar_coluna(
                        colunas,
                        [
                            "NO_CURSO",
                            "nome curso",
                            "curso",
                        ]
                    )

                    col_ies = achar_coluna(
                        colunas,
                        [
                            "NO_IES",
                            "nome ies",
                            "instituicao",
                        ]
                    )

                    col_uf = achar_coluna(
                        colunas,
                        [
                            "SG_UF",
                            "uf",
                        ]
                    )

                    col_municipio = achar_coluna(
                        colunas,
                        [
                            "NO_MUNICIPIO",
                            "municipio",
                        ]
                    )

                    if not (
                        col_curso
                        and
                        col_ies
                        and
                        col_uf
                    ):

                        continue

                    for linha in leitor:

                        curso = normalizar(
                            linha.get(
                                col_curso,
                                ""
                            )
                        )

                        if (
                            "nutricao"
                            not in curso
                        ):

                            continue

                        ies = texto_limpo(
                            linha.get(
                                col_ies,
                                ""
                            )
                        )

                        uf = texto_limpo(
                            linha.get(
                                col_uf,
                                ""
                            )
                        ).upper()

                        municipio = (
                            texto_limpo(
                                linha.get(
                                    col_municipio,
                                    ""
                                )
                            )
                            if col_municipio
                            else ""
                        )

                        if (
                            ies
                            and
                            uf in UFS_BRASIL
                        ):

                            resultados.append({
                                "estado":
                                    uf,

                                "cidade":
                                    municipio,

                                "instituicao":
                                    ies,

                                "origem":
                                    "inep_censo_superior_2024",

                                "fonte_url":
                                    INEP_PAGE,
                            })

                    if resultados:

                        print(
                            f"   ✅ Inep: "
                            f"{len(resultados)} registros de Nutrição encontrados.",
                            flush=True
                        )

                        return resultados

                except Exception:

                    continue

    except Exception as erro:

        print(
            f"   ⚠️ Falha no download/processamento Inep: {erro}",
            flush=True
        )

    return []


# ============================================================
# FALLBACK WEB PARA DESCOBERTA DE FACULDADES
# ============================================================

def descobrir_instituicoes_web(
    estado
):

    print(
        f"   🌐 Descoberta web complementar em {estado}...",
        flush=True
    )

    consultas = [
        f'"curso de Nutrição" "{estado}" universidade',
        f'"curso de Nutrição" "{estado}" faculdade',
        f'"Nutrição" "{estado}" "graduação"',
    ]

    candidatos = {}

    try:

        with DDGS() as ddgs:

            for consulta in consultas:

                try:

                    resultados = list(
                        ddgs.text(
                            consulta,
                            max_results=20
                        )
                    )

                except Exception:

                    continue

                for resultado in resultados:

                    titulo = texto_limpo(
                        resultado.get(
                            "title",
                            ""
                        )
                    )

                    corpo = texto_limpo(
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

                    texto = normalizar(
                        titulo
                        + " "
                        + corpo
                    )

                    if "nutricao" not in texto:
                        continue

                    # procura nome de instituição
                    padroes = [
                        r"(Universidade\s+[A-ZÁÀÂÃÉÈÊÍÌÓÒÔÕÚÙÇ][^|–\-]{3,80})",
                        r"(Centro Universitário\s+[A-ZÁÀÂÃÉÈÊÍÌÓÒÔÕÚÙÇ][^|–\-]{3,80})",
                        r"(Faculdade\s+[A-ZÁÀÂÃÉÈÊÍÌÓÒÔÕÚÙÇ][^|–\-]{3,80})",
                    ]

                    encontrado = None

                    for padrao in padroes:

                        m = re.search(
                            padrao,
                            titulo,
                            flags=re.I
                        )

                        if m:

                            encontrado = texto_limpo(
                                m.group(1)
                            )

                            break

                    if not encontrado:
                        continue

                    chave = normalizar(
                        encontrado
                    )

                    candidatos[
                        chave
                    ] = {
                        "estado":
                            estado,

                        "cidade":
                            "",

                        "instituicao":
                            encontrado,

                        "origem":
                            "descoberta_web",

                        "fonte_url":
                            url,
                    }

                pausa()

    except Exception as erro:

        print(
            f"   ⚠️ Descoberta web falhou: {erro}",
            flush=True
        )

    return list(
        candidatos.values()
    )


# ============================================================
# PREPARAR FILA NACIONAL
# ============================================================

def preparar_fila_nacional():

    print("")
    print(
        "=" * 70,
        flush=True
    )

    print(
        "📚 PREPARANDO FILA NACIONAL DE NUTRIÇÃO",
        flush=True
    )

    print(
        "=" * 70,
        flush=True
    )

    # Primeiro tenta construir tudo pelo Inep de uma vez.
    registros = carregar_instituicoes_inep()

    if registros:

        unicos = {}

        for item in registros:

            chave = (
                item["estado"],
                normalizar(
                    item["instituicao"]
                )
            )

            if chave not in unicos:

                unicos[
                    chave
                ] = item

        print(
            f"📋 Instituições únicas na base: "
            f"{len(unicos)}",
            flush=True
        )

        for item in unicos.values():

            inserir_instituicao(
                estado=
                    item["estado"],

                cidade=
                    item["cidade"],

                instituicao=
                    item["instituicao"],

                origem=
                    item["origem"],

                fonte_url=
                    item["fonte_url"],
            )

        return

    # Se o download oficial falhar, não para a máquina.
    # Faz descoberta UF por UF.
    print(
        "⚠️ Base oficial não carregou nesta execução.",
        flush=True
    )

    print(
        "➡️ Usando descoberta web por estado.",
        flush=True
    )

    for estado in UFS_BRASIL:

        descobertas = descobrir_instituicoes_web(
            estado
        )

        for item in descobertas:

            inserir_instituicao(
                estado=
                    item["estado"],

                cidade=
                    item["cidade"],

                instituicao=
                    item["instituicao"],

                origem=
                    item["origem"],

                fonte_url=
                    item["fonte_url"],
            )


# ============================================================
# HÁ INSTITUIÇÕES NA FILA?
# ============================================================

def quantidade_instituicoes():

    try:

        resposta = (
            supabase
            .table(
                "instituicoes_nutricao"
            )
            .select(
                "id",
                count="exact"
            )
            .execute()
        )

        return (
            resposta.count
            or 0
        )

    except Exception:

        return 0


# ============================================================
# BUSCAR FILA DE UM ESTADO
# ============================================================

def buscar_fila_estado(
    estado
):

    try:

        resposta = (
            supabase
            .table(
                "instituicoes_nutricao"
            )
            .select("*")
            .eq(
                "estado",
                estado
            )
            .in_(
                "status",
                [
                    "pendente",
                    "processando",
                    "erro",
                ]
            )
            .order(
                "instituicao"
            )
            .execute()
        )

        return resposta.data or []

    except Exception as erro:

        print(
            f"❌ Erro lendo fila {estado}: {erro}",
            flush=True
        )

        stats["erros"] += 1

        return []


# ============================================================
# ATUALIZAR INSTITUIÇÃO
# ============================================================

def atualizar_instituicao(
    instituicao_id,
    status
):

    try:

        dados = {
            "status":
                status,

            "ultima_verificacao":
                agora(),
        }

        (
            supabase
            .table(
                "instituicoes_nutricao"
            )
            .update(
                dados
            )
            .eq(
                "id",
                instituicao_id
            )
            .execute()
        )

    except Exception as erro:

        print(
            f"⚠️ Erro atualizando instituição: {erro}",
            flush=True
        )


# ============================================================
# CHECKPOINT
# ============================================================

def salvar_checkpoint(
    estado,
    cidade,
    instituicao,
    status,
    leads_encontrados=0,
    leads_salvos=0,
    erro=None
):

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
                estado,

            "cidade":
                cidade,

            "instituicao":
                instituicao,

            "etapa":
                ETAPA,

            "status":
                status,

            "leads_encontrados":
                leads_encontrados,

            "leads_salvos":
                leads_salvos,

            "ultimo_erro":
                erro,

            "atualizado_em":
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
                "tentativas"
            ] = 0

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

    except Exception as erro_checkpoint:

        print(
            f"⚠️ Checkpoint falhou: {erro_checkpoint}",
            flush=True
        )


# ============================================================
# CONSULTAS DE LEADS DA FACULDADE
# ============================================================

def montar_consultas(
    instituicao
):

    return [
        f'"{instituicao}" "Nutrição" "2025"',
        f'"{instituicao}" "Nutrição" "2026"',
        f'"{instituicao}" "Nutrição" "7º período"',
        f'"{instituicao}" "Nutrição" "8º período"',
        f'"{instituicao}" "Nutrição" "7º semestre"',
        f'"{instituicao}" "Nutrição" "8º semestre"',
        f'"{instituicao}" "Nutrição" "TCC"',
        f'"{instituicao}" "Nutrição" "estágio obrigatório"',
        f'"{instituicao}" "Nutrição" "formanda"',
        f'"{instituicao}" "Nutrição" "formando"',
        f'"{instituicao}" "Nutrição" "recém-formada"',
        f'"{instituicao}" "Nutrição" "recém-formado"',
        f'"{instituicao}" nutricionista "2025"',
        f'"{instituicao}" nutricionista "2026"',
    ]


# ============================================================
# PROCESSAR FACULDADE
# ============================================================

def processar_instituicao(
    item
):

    instituicao = item[
        "instituicao"
    ]

    cidade = (
        item.get(
            "cidade"
        )
        or ""
    )

    estado = item[
        "estado"
    ]

    instituicao_id = item[
        "id"
    ]

    print("")
    print(
        "=" * 70,
        flush=True
    )

    print(
        f"🏫 {estado} | {instituicao}",
        flush=True
    )

    print(
        "=" * 70,
        flush=True
    )

    atualizar_instituicao(
        instituicao_id,
        "processando"
    )

    salvar_checkpoint(
        estado,
        cidade,
        instituicao,
        "processando"
    )

    consultas = montar_consultas(
        instituicao
    )

    candidatos = {}

    houve_busca_executada = False

    try:

        with DDGS() as ddgs:

            for consulta in consultas:

                print(
                    f"   🔎 {consulta}",
                    flush=True
                )

                try:

                    resultados = list(
                        ddgs.text(
                            consulta,
                            max_results=
                                MAX_RESULTADOS_BUSCA
                        )
                    )

                    houve_busca_executada = True

                except Exception as erro:

                    print(
                        f"      ⚠️ Busca indisponível: {erro}",
                        flush=True
                    )

                    pausa()

                    continue

                for resultado in resultados:

                    titulo = texto_limpo(
                        resultado.get(
                            "title",
                            ""
                        )
                    )

                    corpo = texto_limpo(
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
                        texto,
                        instituicao
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

                    instagram = (
                        extrair_instagram_do_resultado(
                            resultado
                        )
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

                        "instagram":
                            instagram,

                        "evidencia":
                            texto,

                        "fonte_url":
                            url,
                    }

                    # SALVA O LEAD IMEDIATAMENTE.
                    # Não espera terminar a faculdade.
                    stats[
                        "leads_encontrados"
                    ] += 1

                    salvar_lead(
                        nome=
                            nome,

                        instituicao=
                            instituicao,

                        cidade=
                            cidade,

                        estado=
                            estado,

                        ano=
                            ano or 2026,

                        periodo=
                            periodo,

                        evidencia=
                            texto,

                        fonte_url=
                            url,

                        instagram=
                            instagram,
                    )

                pausa()

    except Exception as erro:

        stats[
            "instituicoes_com_erro"
        ] += 1

        stats[
            "erros"
        ] += 1

        atualizar_instituicao(
            instituicao_id,
            "erro"
        )

        salvar_checkpoint(
            estado,
            cidade,
            instituicao,
            "erro",
            erro=str(
                erro
            )
        )

        print(
            f"❌ ERRO NA FACULDADE: {erro}",
            flush=True
        )

        return False

    # Se nenhuma busca sequer conseguiu rodar,
    # não marca como concluída.
    if not houve_busca_executada:

        atualizar_instituicao(
            instituicao_id,
            "erro"
        )

        stats[
            "instituicoes_com_erro"
        ] += 1

        print(
            "⚠️ Nenhuma consulta conseguiu executar.",
            flush=True
        )

        return False

    atualizar_instituicao(
        instituicao_id,
        "concluido"
    )

    salvar_checkpoint(
        estado,
        cidade,
        instituicao,
        "concluido",
        leads_encontrados=
            len(candidatos),
        leads_salvos=
            len(candidatos)
    )

    stats[
        "instituicoes_processadas"
    ] += 1

    stats[
        "instituicoes_concluidas"
    ] += 1

    print(
        f"   ✅ FACULDADE CONCLUÍDA | "
        f"Leads identificados: {len(candidatos)}",
        flush=True
    )

    return True


# ============================================================
# RESUMO
# ============================================================

def resumo():

    print("")
    print(
        "=" * 70,
        flush=True
    )

    print(
        "RESUMO DA MÁQUINA 1",
        flush=True
    )

    print(
        "=" * 70,
        flush=True
    )

    print(
        f"Estados verificados: "
        f"{stats['estados_verificados']}",
        flush=True
    )

    print(
        f"Novas instituições descobertas: "
        f"{stats['instituicoes_descobertas']}",
        flush=True
    )

    print(
        f"Instituições processadas: "
        f"{stats['instituicoes_processadas']}",
        flush=True
    )

    print(
        f"Instituições concluídas: "
        f"{stats['instituicoes_concluidas']}",
        flush=True
    )

    print(
        f"Instituições com erro: "
        f"{stats['instituicoes_com_erro']}",
        flush=True
    )

    print(
        f"Leads encontrados: "
        f"{stats['leads_encontrados']}",
        flush=True
    )

    print(
        f"Novos leads salvos: "
        f"{stats['leads_salvos']}",
        flush=True
    )

    print(
        f"Duplicados ignorados: "
        f"{stats['duplicados']}",
        flush=True
    )

    print(
        f"Resultados rejeitados: "
        f"{stats['rejeitados']}",
        flush=True
    )

    print(
        f"Erros: "
        f"{stats['erros']}",
        flush=True
    )

    print(
        "=" * 70,
        flush=True
    )


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def executar():

    print("")
    print(
        "=" * 70,
        flush=True
    )

    print(
        "🇧🇷 CAPTAÇÃO NACIONAL - NUTRIÇÃO",
        flush=True
    )

    print(
        "2025 / 2026 / FASE FINAL",
        flush=True
    )

    print(
        "=" * 70,
        flush=True
    )

    # ========================================================
    # 1. SE A FILA ESTIVER VAZIA, MONTA AUTOMATICAMENTE
    # ========================================================

    total_fila = quantidade_instituicoes()

    print(
        f"📋 Instituições atualmente na fila: "
        f"{total_fila}",
        flush=True
    )

    if total_fila == 0:

        preparar_fila_nacional()

    # ========================================================
    # 2. PERCORRER ESTADOS
    # ========================================================

    processadas_nesta_execucao = 0

    for estado in UFS_BRASIL:

        stats[
            "estados_verificados"
        ] += 1

        print("")
        print(
            "#" * 70,
            flush=True
        )

        print(
            f"📍 ESTADO: {estado}",
            flush=True
        )

        print(
            "#" * 70,
            flush=True
        )

        fila = buscar_fila_estado(
            estado
        )

        if not fila:

            print(
                f"✅ {estado}: sem faculdades pendentes.",
                flush=True
            )

            continue

        print(
            f"📚 Faculdades pendentes em {estado}: "
            f"{len(fila)}",
            flush=True
        )

        # ====================================================
        # FACULDADE POR FACULDADE
        # ====================================================

        for item in fila:

            if (
                processadas_nesta_execucao
                >=
                MAX_INSTITUICOES_POR_EXECUCAO
            ):

                print("")
                print(
                    "⏸️ Limite desta execução atingido.",
                    flush=True
                )

                print(
                    "➡️ Na próxima execução a máquina "
                    "continua das faculdades pendentes.",
                    flush=True
                )

                resumo()

                return

            processar_instituicao(
                item
            )

            processadas_nesta_execucao += 1

            pausa()

        # ====================================================
        # TERMINOU ESTADO
        # ====================================================

        restante = buscar_fila_estado(
            estado
        )

        if not restante:

            print("")
            print(
                f"🏁 {estado} CONCLUÍDO",
                flush=True
            )

            print(
                "➡️ Indo para o próximo estado...",
                flush=True
            )

    resumo()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    executar()

    print(
        "✅ MÁQUINA 1 FINALIZADA",
        flush=True
    )
