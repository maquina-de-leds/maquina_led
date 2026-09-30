import os
import re
import time
import random
import base64
import hashlib
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from supabase import create_client


# ============================================================
# MÁQUINA NACIONAL DE LEADS - NUTRIÇÃO
# ============================================================
#
# DESCOBERTA DAS FACULDADES:
#
# e-MEC
#   ↓
# Estado
#   ↓
# Município oficial
#   ↓
# Instituições oficiais naquele município
#   ↓
# Campus/endereço
#   ↓
# Cursos daquele campus
#   ↓
# Tem Nutrição?
#   ↓
# SIM → salva instituição no Supabase
#
# CAPTAÇÃO:
#
# instituição_nutricao
#   ↓
# busca pública/indexada
#   ↓
# filtro pessoa real
#   ↓
# 2025 / 2026 / final do curso
#   ↓
# salva lead imediatamente
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
# e-MEC
# ============================================================

EMEC_BASE = "https://emec.mec.gov.br/emec"

EMEC_CONSULTA_AVANCADA = (
    f"{EMEC_BASE}/nova-index/"
    "listar-consulta-avancada/list/1000"
)

EMEC_TOKEN_IES = (
    "d96957f455f6405d14c6542552b0f6eb"
)

EMEC_TOKEN_ENDERECO = (
    "aa547dc9e0377b562e2354d29f06085f"
)


# ============================================================
# ESTADOS
# ============================================================

ESTADOS = [
    ("SP", "São Paulo"),
    ("MG", "Minas Gerais"),
    ("RJ", "Rio de Janeiro"),
    ("PR", "Paraná"),
    ("SC", "Santa Catarina"),
    ("RS", "Rio Grande do Sul"),
    ("BA", "Bahia"),
    ("PE", "Pernambuco"),
    ("CE", "Ceará"),
    ("GO", "Goiás"),
    ("DF", "Distrito Federal"),
    ("ES", "Espírito Santo"),
    ("MT", "Mato Grosso"),
    ("MS", "Mato Grosso do Sul"),
    ("PA", "Pará"),
    ("MA", "Maranhão"),
    ("PB", "Paraíba"),
    ("RN", "Rio Grande do Norte"),
    ("AL", "Alagoas"),
    ("SE", "Sergipe"),
    ("PI", "Piauí"),
    ("RO", "Rondônia"),
    ("TO", "Tocantins"),
    ("AC", "Acre"),
    ("AP", "Amapá"),
    ("AM", "Amazonas"),
    ("RR", "Roraima"),
]


# ============================================================
# LIMITES
# ============================================================

# Quantos municípios oficiais do e-MEC serão inspecionados
# em uma execução.
#
# Isso é diferente de pesquisar cada cidade no Google.
# Aqui consultamos diretamente a estrutura oficial do MEC.
MAX_MUNICIPIOS_EMEC_POR_EXECUCAO = 20

# Até 5 faculdades terão seus leads pesquisados
# em cada execução.
MAX_FACULDADES_POR_EXECUCAO = 5

MAX_RESULTADOS_LEADS = 20

MAX_TENTATIVAS_HTTP = 3
MAX_TENTATIVAS_SUPABASE = 3

PAUSA_EMEC_MIN = 1.5
PAUSA_EMEC_MAX = 3.0

PAUSA_BUSCA_MIN = 5.0
PAUSA_BUSCA_MAX = 8.0

PONTUACAO_MINIMA = 9


# ============================================================
# HTTP
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
})


# ============================================================
# ESTATÍSTICAS
# ============================================================

estatisticas = {
    "estados_visitados": 0,
    "municipios_emec": 0,
    "ies_emec_analisadas": 0,
    "campus_analisados": 0,
    "instituicoes_nutricao_encontradas": 0,
    "instituicoes_novas": 0,
    "faculdades_processadas": 0,
    "pesquisas_leads": 0,
    "resultados_analisados": 0,
    "perfis_unicos": 0,
    "institucionais": 0,
    "fora_nicho": 0,
    "qualificados": 0,
    "salvos": 0,
    "duplicados": 0,
    "sem_resultado": 0,
    "erros": 0,
}


# ============================================================
# MEMÓRIA DA EXECUÇÃO
# ============================================================

evidencias_perfis = {}

salvos_execucao = set()

bloqueados_execucao = set()

qualificados_execucao = set()


# ============================================================
# UTILIDADES
# ============================================================

def agora_iso():

    return datetime.now(
        timezone.utc
    ).isoformat()


def normalizar_texto(texto):

    if texto is None:
        return ""

    texto = str(texto).lower()

    texto = unicodedata.normalize(
        "NFKD",
        texto
    )

    texto = "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(
            caractere
        )
    )

    texto = re.sub(
        r"\s+",
        " ",
        texto
    )

    return texto.strip()


def normalizar_instagram(usuario):

    if not usuario:
        return None

    usuario = (
        str(usuario)
        .strip()
        .lower()
        .lstrip("@")
    )

    return "@" + usuario


def b64(valor):

    return base64.b64encode(
        str(valor).encode("utf-8")
    ).decode("utf-8")


def pausa_emec():

    time.sleep(
        random.uniform(
            PAUSA_EMEC_MIN,
            PAUSA_EMEC_MAX
        )
    )


def pausa_busca():

    time.sleep(
        random.uniform(
            PAUSA_BUSCA_MIN,
            PAUSA_BUSCA_MAX
        )
    )


# ============================================================
# HTTP COM RETRY
# ============================================================

def http_get(
    url,
    params=None
):

    ultimo_erro = None

    for tentativa in range(
        1,
        MAX_TENTATIVAS_HTTP + 1
    ):

        try:

            resposta = session.get(
                url,
                params=params,
                timeout=40
            )

            resposta.raise_for_status()

            return resposta

        except Exception as erro:

            ultimo_erro = str(erro)

            print(
                f"⚠️ e-MEC GET "
                f"{tentativa}/"
                f"{MAX_TENTATIVAS_HTTP}: "
                f"{ultimo_erro}"
            )

            if tentativa < MAX_TENTATIVAS_HTTP:

                time.sleep(
                    5 * tentativa
                )

    estatisticas["erros"] += 1

    return None


def http_post(
    url,
    data
):

    ultimo_erro = None

    for tentativa in range(
        1,
        MAX_TENTATIVAS_HTTP + 1
    ):

        try:

            resposta = session.post(
                url,
                data=data,
                timeout=50
            )

            resposta.raise_for_status()

            return resposta

        except Exception as erro:

            ultimo_erro = str(erro)

            print(
                f"⚠️ e-MEC POST "
                f"{tentativa}/"
                f"{MAX_TENTATIVAS_HTTP}: "
                f"{ultimo_erro}"
            )

            if tentativa < MAX_TENTATIVAS_HTTP:

                time.sleep(
                    5 * tentativa
                )

    estatisticas["erros"] += 1

    return None


# ============================================================
# MUNICÍPIOS OFICIAIS DO e-MEC
# ============================================================

def obter_municipios_emec(
    uf
):

    hash_campo = hashlib.md5(
        "sg_uf".encode("utf-8")
    ).hexdigest()

    url = (
        f"{EMEC_BASE}/comum/json/"
        f"selecionar-municipio/"
        f"{hash_campo}/"
        f"{b64(uf)}"
    )

    resposta = http_get(
        url
    )

    if not resposta:
        return []

    try:

        dados = resposta.json()

    except Exception as erro:

        print(
            f"❌ Resposta de municípios "
            f"do e-MEC inválida: {erro}"
        )

        estatisticas["erros"] += 1

        return []

    municipios = []

    for item in dados:

        nome = (
            item.get("ds_municipio")
            or item.get("no_municipio")
            or ""
        ).strip()

        codigo = (
            item.get("co_municipio")
            or ""
        )

        if not nome or not codigo:
            continue

        municipios.append({
            "nome": nome,
            "codigo": str(codigo),
        })

    municipios.sort(
        key=lambda x:
            normalizar_texto(
                x["nome"]
            )
    )

    return municipios


# ============================================================
# CONSULTAR INSTITUIÇÕES OFICIAIS
# EM UM MUNICÍPIO
# ============================================================

def obter_instituicoes_municipio(
    uf,
    codigo_municipio
):

    payload = {
        "data[CONSULTA_AVANCADA][hid_template]":
            "listar-consulta-avancada-ies",

        "data[CONSULTA_AVANCADA][hid_order]":
            "ies.no_ies ASC",

        "data[CONSULTA_AVANCADA][hid_no_cidade_avancada]":
            "",

        "data[CONSULTA_AVANCADA][hid_no_regiao_avancada]":
            "",

        "data[CONSULTA_AVANCADA][hid_no_pais_avancada]":
            "",

        "data[CONSULTA_AVANCADA][hid_co_pais_avancada]":
            "",

        "data[CONSULTA_AVANCADA][rad_buscar_por]":
            "IES",

        "data[CONSULTA_AVANCADA][txt_no_ies]":
            "",

        "data[CONSULTA_AVANCADA][txt_no_curso]":
            "",

        "data[CONSULTA_AVANCADA][txt_no_especializacao]":
            "",

        "data[CONSULTA_AVANCADA][sel_co_area]":
            "",

        "data[CONSULTA_AVANCADA][sel_sg_uf]":
            uf,

        "data[CONSULTA_AVANCADA][sel_co_municipio]":
            codigo_municipio,

        # Situação ativa da IES.
        "data[CONSULTA_AVANCADA][sel_co_situacao_funcionamento_ies]":
            "10035",

        "captcha":
            "",
    }

    resposta = http_post(
        EMEC_CONSULTA_AVANCADA,
        payload
    )

    if not resposta:
        return None

    soup = BeautifulSoup(
        resposta.text,
        "html.parser"
    )

    instituicoes = []

    for linha in soup.find_all("tr"):

        colunas = linha.find_all("td")

        # A consulta de IES normalmente retorna
        # 8 colunas.
        if len(colunas) < 7:
            continue

        codigo = (
            colunas[0]
            .get_text(
                " ",
                strip=True
            )
        )

        nome = (
            colunas[1]
            .get_text(
                " ",
                strip=True
            )
        )

        situacao = (
            colunas[6]
            .get_text(
                " ",
                strip=True
            )
        )

        codigo_limpo = re.sub(
            r"\D",
            "",
            codigo
        )

        if not codigo_limpo:
            continue

        if not nome:
            continue

        instituicoes.append({
            "codigo": codigo_limpo,
            "nome": nome[:220],
            "situacao": situacao,
        })

    return instituicoes


# ============================================================
# CAMPI / ENDEREÇOS DA IES
# ============================================================

def obter_enderecos_ies(
    codigo_ies
):

    url = (
        f"{EMEC_BASE}/consulta-ies/"
        f"listar-endereco/"
        f"{EMEC_TOKEN_IES}/"
        f"{b64(codigo_ies)}/"
        f"list/1000"
    )

    resposta = http_get(
        url
    )

    if not resposta:
        return None

    soup = BeautifulSoup(
        resposta.text,
        "html.parser"
    )

    enderecos = []

    for linha in soup.find_all("tr"):

        colunas = linha.find_all("td")

        if len(colunas) < 6:
            continue

        codigo_endereco = (
            colunas[0]
            .get_text(
                " ",
                strip=True
            )
        )

        denominacao = (
            colunas[1]
            .get_text(
                " ",
                strip=True
            )
        )

        municipio = (
            colunas[4]
            .get_text(
                " ",
                strip=True
            )
        )

        uf = (
            colunas[5]
            .get_text(
                " ",
                strip=True
            )
        )

        codigo_limpo = re.sub(
            r"\D",
            "",
            codigo_endereco
        )

        uf_limpa = re.sub(
            r"[^A-Z]",
            "",
            uf.upper()
        )

        if not codigo_limpo:
            continue

        enderecos.append({
            "codigo":
                codigo_limpo,

            "denominacao":
                denominacao,

            "municipio":
                municipio,

            "uf":
                uf_limpa[-2:]
                if len(uf_limpa) >= 2
                else uf_limpa,
        })

    return enderecos


# ============================================================
# CURSOS DO CAMPUS
# ============================================================

def obter_cursos_campus(
    codigo_ies,
    codigo_endereco
):

    url = (
        f"{EMEC_BASE}/consulta-ies/"
        f"listar-curso-endereco/"
        f"{EMEC_TOKEN_IES}/"
        f"{b64(codigo_ies)}/"
        f"{EMEC_TOKEN_ENDERECO}/"
        f"{b64(codigo_endereco)}/"
        f"list/1000"
    )

    resposta = http_get(
        url
    )

    if not resposta:
        return None

    soup = BeautifulSoup(
        resposta.text,
        "html.parser"
    )

    cursos = []

    for linha in soup.find_all("tr"):

        colunas = linha.find_all("td")

        if not colunas:
            continue

        texto_colunas = [
            coluna.get_text(
                " ",
                strip=True
            )
            for coluna in colunas
        ]

        texto = " ".join(
            texto_colunas
        )

        if texto.strip():
            cursos.append(
                texto
            )

    return cursos


# ============================================================
# CAMPUS TEM NUTRIÇÃO?
# ============================================================

def campus_tem_nutricao(
    cursos
):

    if cursos is None:
        return None

    for curso in cursos:

        texto = normalizar_texto(
            curso
        )

        if re.search(
            r"\bnutricao\b",
            texto
        ):

            return True

    return False


# ============================================================
# INSTITUIÇÃO JÁ EXISTE?
# ============================================================

def buscar_instituicao_existente(
    uf,
    cidade,
    nome
):

    try:

        resposta = (
            supabase
            .table(
                "instituicoes_nutricao"
            )
            .select(
                "id,instituicao"
            )
            .eq(
                "estado",
                uf
            )
            .eq(
                "cidade",
                cidade
            )
            .execute()
        )

        registros = (
            resposta.data
            or []
        )

        nome_norm = normalizar_texto(
            nome
        )

        for registro in registros:

            existente = normalizar_texto(
                registro.get(
                    "instituicao"
                )
            )

            if existente == nome_norm:

                return registro

            if (
                existente
                and nome_norm
                and (
                    existente in nome_norm
                    or nome_norm in existente
                )
                and min(
                    len(existente),
                    len(nome_norm)
                ) >= 8
            ):

                return registro

        return None

    except Exception as erro:

        print(
            f"⚠️ Erro verificando "
            f"instituição: {erro}"
        )

        return "ERRO"


# ============================================================
# SALVAR FACULDADE DE NUTRIÇÃO
# ============================================================

def salvar_instituicao_nutricao(
    uf,
    cidade,
    nome,
    codigo_ies
):

    existente = (
        buscar_instituicao_existente(
            uf,
            cidade,
            nome
        )
    )

    if existente == "ERRO":
        return False

    if existente:
        return False

    fonte = (
        f"{EMEC_BASE}/consulta-ies/index/"
        f"{EMEC_TOKEN_IES}/"
        f"{b64(codigo_ies)}"
    )

    dados = {
        "estado":
            uf,

        "cidade":
            cidade,

        "instituicao":
            nome,

        "curso":
            "Nutrição",

        "origem":
            "e_MEC_oficial",

        "fonte_url":
            fonte,

        "status":
            "pendente",

        "ultima_verificacao":
            agora_iso(),

        "fonte_validacao":
            "e-MEC",

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
            .insert(dados)
            .execute()
        )

        estatisticas[
            "instituicoes_novas"
        ] += 1

        estatisticas[
            "instituicoes_nutricao_encontradas"
        ] += 1

        print(
            f"      ✅ NUTRIÇÃO CONFIRMADA:"
        )

        print(
            f"         {nome}"
        )

        print(
            f"         {cidade}/{uf}"
        )

        print(
            f"         Código e-MEC: "
            f"{codigo_ies}"
        )

        return True

    except Exception as erro:

        print(
            f"❌ Erro salvando instituição: "
            f"{erro}"
        )

        estatisticas["erros"] += 1

        return False


# ============================================================
# CHECKPOINT DA DESCOBERTA e-MEC
# ============================================================

def obter_checkpoint_emec(
    uf
):

    try:

        resposta = (
            supabase
            .table(
                "controle_busca"
            )
            .select("*")
            .eq(
                "estado",
                uf
            )
            .eq(
                "etapa",
                "descoberta_emec"
            )
            .limit(1)
            .execute()
        )

        if resposta.data:
            return resposta.data[0]

        return None

    except Exception as erro:

        print(
            f"⚠️ Erro lendo checkpoint "
            f"e-MEC: {erro}"
        )

        return None


def salvar_checkpoint_emec(
    uf,
    status,
    indice,
    total,
    municipio=None,
    erro=None
):

    atual = obter_checkpoint_emec(
        uf
    )

    dados = {
        "estado":
            uf,

        "cidade":
            municipio,

        "instituicao":
            None,

        "etapa":
            "descoberta_emec",

        "status":
            status,

        "indice_pesquisa":
            indice,

        "total_pesquisas":
            total,

        "consulta_atual":
            municipio,

        "fonte_atual":
            "e-MEC",

        "ultimo_erro":
            erro,

        "atualizado_em":
            agora_iso(),
    }

    if not atual:

        dados[
            "iniciado_em"
        ] = agora_iso()

    if status == "concluido":

        dados[
            "finalizado_em"
        ] = agora_iso()

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

            (
                supabase
                .table(
                    "controle_busca"
                )
                .insert(dados)
                .execute()
            )

        return True

    except Exception as erro_sql:

        print(
            f"⚠️ Erro gravando checkpoint "
            f"e-MEC: {erro_sql}"
        )

        estatisticas["erros"] += 1

        return False


# ============================================================
# DESCOBRIR FACULDADES DE NUTRIÇÃO NO e-MEC
# ============================================================

def descobrir_faculdades_emec(
    uf,
    estado_nome
):

    print("")
    print(
        "================================================="
    )

    print(
        f"🏛️ e-MEC OFICIAL - "
        f"{estado_nome}/{uf}"
    )

    print(
        "================================================="
    )

    municipios = obter_municipios_emec(
        uf
    )

    if not municipios:

        print(
            f"❌ e-MEC não retornou "
            f"municípios para {uf}."
        )

        return False

    total = len(
        municipios
    )

    checkpoint = obter_checkpoint_emec(
        uf
    )

    inicio = 0

    if checkpoint:

        status = (
            checkpoint.get("status")
            or ""
        )

        indice = (
            checkpoint.get(
                "indice_pesquisa"
            )
            or 0
        )

        if status == "concluido":

            print(
                f"✅ Varredura oficial de "
                f"{uf} já concluída."
            )

            return True

        inicio = max(
            0,
            indice
        )

        if inicio >= total:

            inicio = total

        if inicio > 0:

            print(
                f"♻️ Retomando no município "
                f"{inicio + 1}/{total}"
            )

    processados_execucao = 0

    for posicao in range(
        inicio,
        total
    ):

        if (
            processados_execucao
            >= MAX_MUNICIPIOS_EMEC_POR_EXECUCAO
        ):

            print("")
            print(
                f"⏸️ Limite de "
                f"{MAX_MUNICIPIOS_EMEC_POR_EXECUCAO} "
                f"municípios oficiais atingido."
            )

            print(
                "Na próxima execução "
                "continua exatamente daqui."
            )

            return True

        municipio = (
            municipios[
                posicao
            ]
        )

        nome_municipio = (
            municipio["nome"]
        )

        codigo_municipio = (
            municipio["codigo"]
        )

        numero = posicao + 1

        print("")
        print(
            f"📍 e-MEC "
            f"{numero}/{total}: "
            f"{nome_municipio}/{uf}"
        )

        salvar_checkpoint_emec(
            uf=uf,
            status="processando",
            indice=posicao,
            total=total,
            municipio=nome_municipio
        )

        instituicoes = (
            obter_instituicoes_municipio(
                uf,
                codigo_municipio
            )
        )

        # Se houve falha real no e-MEC,
        # NÃO avança o checkpoint.
        if instituicoes is None:

            salvar_checkpoint_emec(
                uf=uf,
                status="erro",
                indice=posicao,
                total=total,
                municipio=nome_municipio,
                erro=(
                    "Falha consultando "
                    "instituições no e-MEC"
                )
            )

            print(
                "⚠️ Não avançarei para não "
                "perder esta cidade."
            )

            return False

        print(
            f"   IES oficiais encontradas: "
            f"{len(instituicoes)}"
        )

        for ies in instituicoes:

            estatisticas[
                "ies_emec_analisadas"
            ] += 1

            codigo_ies = (
                ies["codigo"]
            )

            nome_ies = (
                ies["nome"]
            )

            enderecos = obter_enderecos_ies(
                codigo_ies
            )

            if enderecos is None:
                continue

            for endereco in enderecos:

                endereco_uf = (
                    endereco.get("uf")
                    or ""
                )

                endereco_cidade = (
                    endereco.get("municipio")
                    or ""
                )

                # Queremos especificamente
                # o campus daquele município.
                if (
                    normalizar_texto(
                        endereco_cidade
                    )
                    != normalizar_texto(
                        nome_municipio
                    )
                ):
                    continue

                if (
                    endereco_uf
                    and endereco_uf != uf
                ):
                    continue

                estatisticas[
                    "campus_analisados"
                ] += 1

                cursos = (
                    obter_cursos_campus(
                        codigo_ies,
                        endereco["codigo"]
                    )
                )

                if cursos is None:
                    continue

                tem_nutricao = (
                    campus_tem_nutricao(
                        cursos
                    )
                )

                if tem_nutricao:

                    salvar_instituicao_nutricao(
                        uf=uf,
                        cidade=nome_municipio,
                        nome=nome_ies,
                        codigo_ies=codigo_ies
                    )

                    # Já confirmamos a IES
                    # naquele município.
                    break

                pausa_emec()

            pausa_emec()

        estatisticas[
            "municipios_emec"
        ] += 1

        processados_execucao += 1

        # Só avança DEPOIS de concluir o município.
        proximo_indice = (
            posicao + 1
        )

        salvar_checkpoint_emec(
            uf=uf,
            status="processando",
            indice=proximo_indice,
            total=total,
            municipio=nome_municipio
        )

        pausa_emec()

    salvar_checkpoint_emec(
        uf=uf,
        status="concluido",
        indice=total,
        total=total,
        municipio=None
    )

    print("")
    print(
        f"✅ Varredura oficial "
        f"de {uf} concluída."
    )

    return True


# ============================================================
# FILA DE FACULDADES PARA BUSCAR LEADS
# ============================================================

def buscar_faculdades_pendentes(
    uf,
    limite
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
                uf
            )
            .eq(
                "status",
                "pendente"
            )
            .eq(
                "validada",
                True
            )
            .order("cidade")
            .order("instituicao")
            .limit(limite)
            .execute()
        )

        return (
            resposta.data
            or []
        )

    except Exception as erro:

        print(
            f"❌ Erro lendo fila: "
            f"{erro}"
        )

        estatisticas["erros"] += 1

        return []


def atualizar_status_faculdade(
    faculdade_id,
    status
):

    try:

        (
            supabase
            .table(
                "instituicoes_nutricao"
            )
            .update({
                "status":
                    status,

                "ultima_verificacao":
                    agora_iso(),
            })
            .eq(
                "id",
                faculdade_id
            )
            .execute()
        )

        return True

    except Exception as erro:

        print(
            f"⚠️ Erro atualizando "
            f"faculdade: {erro}"
        )

        estatisticas["erros"] += 1

        return False


# ============================================================
# CHECKPOINT DOS LEADS
# ============================================================

def obter_checkpoint_leads(
    instituicao
):

    try:

        resposta = (
            supabase
            .table(
                "controle_busca"
            )
            .select("*")
            .eq(
                "estado",
                instituicao["estado"]
            )
            .eq(
                "cidade",
                instituicao["cidade"]
            )
            .eq(
                "instituicao",
                instituicao["instituicao"]
            )
            .eq(
                "etapa",
                "busca_leads"
            )
            .limit(1)
            .execute()
        )

        if resposta.data:
            return resposta.data[0]

        return None

    except Exception as erro:

        print(
            f"⚠️ Erro lendo checkpoint "
            f"dos leads: {erro}"
        )

        return None


def salvar_checkpoint_leads(
    instituicao,
    status,
    indice,
    total,
    consulta=None,
    encontrados=0,
    salvos=0,
    erro=None
):

    atual = obter_checkpoint_leads(
        instituicao
    )

    dados = {
        "estado":
            instituicao["estado"],

        "cidade":
            instituicao["cidade"],

        "instituicao":
            instituicao["instituicao"],

        "etapa":
            "busca_leads",

        "status":
            status,

        "indice_pesquisa":
            indice,

        "total_pesquisas":
            total,

        "consulta_atual":
            consulta,

        "fonte_atual":
            "busca_web_indexada",

        "leads_encontrados":
            encontrados,

        "leads_salvos":
            salvos,

        "ultimo_erro":
            erro,

        "atualizado_em":
            agora_iso(),
    }

    if not atual:

        dados[
            "iniciado_em"
        ] = agora_iso()

    if status == "concluido":

        dados[
            "finalizado_em"
        ] = agora_iso()

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

            (
                supabase
                .table(
                    "controle_busca"
                )
                .insert(dados)
                .execute()
            )

        return True

    except Exception as erro_sql:

        print(
            f"⚠️ Erro salvando checkpoint: "
            f"{erro_sql}"
        )

        estatisticas["erros"] += 1

        return False


# ============================================================
# BUSCA WEB DOS LEADS
# ============================================================

def pesquisar_leads(
    ddgs,
    consulta
):

    estatisticas[
        "pesquisas_leads"
    ] += 1

    ultimo_erro = None

    for tentativa in range(
        1,
        4
    ):

        try:

            resultados = list(
                ddgs.text(
                    consulta,
                    max_results=
                        MAX_RESULTADOS_LEADS
                )
            )

            if not resultados:

                estatisticas[
                    "sem_resultado"
                ] += 1

            return (
                resultados,
                True,
                None
            )

        except Exception as erro:

            ultimo_erro = str(
                erro
            )

            if (
                "No results found"
                in ultimo_erro
            ):

                estatisticas[
                    "sem_resultado"
                ] += 1

                return (
                    [],
                    True,
                    None
                )

            print(
                f"⚠️ Busca "
                f"{tentativa}/3: "
                f"{ultimo_erro}"
            )

            if tentativa < 3:

                time.sleep(
                    15 * tentativa
                )

    estatisticas["erros"] += 1

    return (
        [],
        False,
        ultimo_erro
    )


# ============================================================
# CONSULTAS DOS LEADS
#
# Mantemos poucas consultas para reduzir bloqueios.
# ============================================================

def montar_consultas_leads(
    instituicao
):

    nome = (
        instituicao[
            "instituicao"
        ]
    )

    cidade = (
        instituicao[
            "cidade"
        ]
    )

    exclusoes = (
        "-psicologia "
        "-maquiagem "
        "-veterinaria "
        "-odontologia "
        "-atletica "
        "-comissao "
        "-turma "
        "-evento"
    )

    return [

        (
            f'site:instagram.com '
            f'"{nome}" '
            f'"Nutrição" '
            f'"formanda" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{nome}" '
            f'"Nutrição" '
            f'"formando" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{nome}" '
            f'"Nutrição" '
            f'"concluinte" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{nome}" '
            f'"Nutrição" '
            f'"7/8" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{nome}" '
            f'"Nutrição" '
            f'"8/8" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{nome}" '
            f'"Nutrição" '
            f'"último período" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{cidade}" '
            f'"nutricionista" '
            f'"2026" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{cidade}" '
            f'"nutricionista" '
            f'"2025" '
            f'{exclusoes}'
        ),
    ]


# ============================================================
# INSTAGRAM
# ============================================================

def extrair_instagram(
    url
):

    if not url:
        return None

    try:

        parsed = urlparse(
            url
        )

        dominio = (
            parsed.netloc
            .lower()
        )

        if "instagram.com" not in dominio:
            return None

        partes = [
            parte
            for parte
            in parsed.path.split("/")
            if parte
        ]

        if not partes:
            return None

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
            return None

        if not re.match(
            r"^[A-Za-z0-9._]+$",
            usuario
        ):
            return None

        return normalizar_instagram(
            usuario
        )

    except Exception:

        return None


# ============================================================
# FILTRO DE PERFIS
# ============================================================

HANDLES_BLOQUEADOS = {
    "@popular",
    "@tcc_nutricao",
}


TERMOS_FORA_NICHO = [
    "psicologia",
    "psicologa",
    "psicologo",
    "maquiagem",
    "maquiadora",
    "makeup",
    "veterinaria",
    "veterinario",
    "medicina veterinaria",
    "odontologia",
    "dentista",
    "fonoaudiologia",
    "fisioterapia",
    "fotografia",
    "engenharia",
    "arquitetura",
    "kumon",
]


PADROES_INSTITUCIONAIS = [
    r"^@?nutricao[._-]?uf",
    r"^@?nutricao[._-]?uni",
    r"^@?nutricao[._-]?fac",
    r"^@?nutricao[._-]?fai",
    r"^@?nutricao[._-]?ies",
    r"^@?turma",
    r"^@?formatura",
    r"^@?comissao",
    r"^@?atletica",
]


def fora_do_nicho(
    texto
):

    texto = normalizar_texto(
        texto
    )

    return any(
        termo in texto
        for termo
        in TERMOS_FORA_NICHO
    )


def conta_institucional(
    instagram,
    texto
):

    if instagram in HANDLES_BLOQUEADOS:
        return True

    handle = normalizar_texto(
        instagram
    )

    for padrao in PADROES_INSTITUCIONAIS:

        if re.search(
            padrao,
            handle
        ):
            return True

    texto_norm = normalizar_texto(
        texto
    )

    termos_institucionais = [
        "turma de nutricao",
        "comissao de formatura",
        "centro academico",
        "diretorio academico",
        "atletica",
        "universidade",
        "faculdade",
    ]

    sinais_pessoais = [
        "nutricionista",
        "graduanda",
        "graduando",
        "formanda",
        "formando",
        "estudante de nutricao",
        "academica de nutricao",
        "academico de nutricao",
        "crn",
        "atendimento",
    ]

    institucional = any(
        termo in texto_norm
        for termo in termos_institucionais
    )

    pessoal = any(
        termo in texto_norm
        for termo in sinais_pessoais
    )

    if institucional and not pessoal:
        return True

    return False


# ============================================================
# PROVA DE NUTRIÇÃO
# ============================================================

def e_nutricao(
    texto
):

    texto_norm = normalizar_texto(
        texto
    )

    fortes = [
        "nutricionista",
        "estudante de nutricao",
        "graduanda em nutricao",
        "graduando em nutricao",
        "academica de nutricao",
        "academico de nutricao",
        "formanda em nutricao",
        "formando em nutricao",
        "bacharel em nutricao",
        "crn",
    ]

    if any(
        termo in texto_norm
        for termo in fortes
    ):
        return True

    if "nutricao" in texto_norm:

        contexto = [
            "graduanda",
            "graduando",
            "formanda",
            "formando",
            "concluinte",
            "estudante",
            "academica",
            "academico",
            "crn",
            "atendimento",
        ]

        if any(
            termo in texto_norm
            for termo in contexto
        ):
            return True

    return False


# ============================================================
# COORTE
# ============================================================

def e_coorte_alvo(
    texto
):

    texto_norm = normalizar_texto(
        texto
    )

    ano_alvo = (
        "2025" in texto_norm
        or "2026" in texto_norm
    )

    conclusao = [
        "formatura",
        "formou",
        "formada",
        "formado",
        "colacao",
        "concluiu",
        "bacharel",
    ]

    final_curso = [
        "formanda",
        "formando",
        "concluinte",
        "ultimo periodo",
        "ultimo semestre",
        "ultimo ano",
        "7/8",
        "8/8",
        "7 de 8",
        "8 de 8",
        "tcc",
    ]

    concluiu = any(
        termo in texto_norm
        for termo in conclusao
    )

    esta_final = any(
        termo in texto_norm
        for termo in final_curso
    )

    return (
        (
            ano_alvo
            and concluiu
        )
        or esta_final
    )


# ============================================================
# PONTUAÇÃO
# ============================================================

def calcular_pontuacao(
    texto,
    instagram,
    instituicao
):

    texto_norm = normalizar_texto(
        texto
    )

    pontos = 0

    if "nutricionista" in texto_norm:
        pontos += 4

    if "nutricao" in texto_norm:
        pontos += 3

    if "crn" in texto_norm:
        pontos += 3

    if "nutri" in instagram:
        pontos += 2

    if any(
        termo in texto_norm
        for termo in [
            "formanda",
            "formando",
            "concluinte",
            "ultimo periodo",
            "ultimo semestre",
            "7/8",
            "8/8",
            "tcc",
        ]
    ):
        pontos += 5

    if "2026" in texto_norm:
        pontos += 4

    if "2025" in texto_norm:
        pontos += 3

    cidade = normalizar_texto(
        instituicao["cidade"]
    )

    if cidade and cidade in texto_norm:
        pontos += 2

    return pontos


# ============================================================
# EVIDÊNCIA
# ============================================================

def montar_evidencia(
    texto
):

    texto_norm = normalizar_texto(
        texto
    )

    itens = []

    mapa = [
        ("nutricionista", "nutricionista"),
        ("nutricao", "Nutrição"),
        ("crn", "CRN"),
        ("2025", "2025"),
        ("2026", "2026"),
        ("formanda", "formanda"),
        ("formando", "formando"),
        ("concluinte", "concluinte"),
        ("ultimo periodo", "último período"),
        ("ultimo semestre", "último semestre"),
        ("7/8", "7/8"),
        ("8/8", "8/8"),
        ("tcc", "TCC"),
        ("formatura", "formatura"),
        ("colacao", "colação"),
    ]

    for termo, descricao in mapa:

        if termo in texto_norm:

            itens.append(
                descricao
            )

    return " | ".join(
        dict.fromkeys(
            itens
        )
    )


# ============================================================
# DUPLICIDADE
# ============================================================

def verificar_duplicidade(
    instagram
):

    for tentativa in range(
        1,
        MAX_TENTATIVAS_SUPABASE + 1
    ):

        try:

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

            return bool(
                resposta.data
            )

        except Exception as erro:

            print(
                f"⚠️ Erro verificando "
                f"duplicidade: {erro}"
            )

            if tentativa < MAX_TENTATIVAS_SUPABASE:

                time.sleep(
                    4 * tentativa
                )

    return None


# ============================================================
# SALVAR LEAD
# ============================================================

def salvar_lead(
    lead
):

    instagram = (
        lead["instagram"]
    )

    if instagram in salvos_execucao:
        return False

    existente = verificar_duplicidade(
        instagram
    )

    if existente is True:

        estatisticas[
            "duplicados"
        ] += 1

        salvos_execucao.add(
            instagram
        )

        print(
            f"      ♻️ DUPLICADO: "
            f"{instagram}"
        )

        return False

    if existente is None:

        return False

    for tentativa in range(
        1,
        MAX_TENTATIVAS_SUPABASE + 1
    ):

        try:

            (
                supabase
                .table("leds")
                .insert(lead)
                .execute()
            )

            salvos_execucao.add(
                instagram
            )

            estatisticas[
                "salvos"
            ] += 1

            print(
                f"      ✅ SALVO NO SUPABASE: "
                f"{instagram}"
            )

            return True

        except Exception as erro:

            print(
                f"      ⚠️ Erro ao salvar "
                f"{instagram}: {erro}"
            )

            if tentativa < MAX_TENTATIVAS_SUPABASE:

                time.sleep(
                    4 * tentativa
                )

    estatisticas["erros"] += 1

    return False


# ============================================================
# PROCESSAR RESULTADO DE LEAD
# ============================================================

def processar_resultado_lead(
    resultado,
    instituicao
):

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

    instagram = extrair_instagram(
        url
    )

    if not instagram:
        return False

    estatisticas[
        "resultados_analisados"
    ] += 1

    if instagram in bloqueados_execucao:
        return False

    texto_novo = (
        f"{titulo} "
        f"{corpo} "
        f"{url}"
    )

    if fora_do_nicho(
        texto_novo
    ):

        bloqueados_execucao.add(
            instagram
        )

        estatisticas[
            "fora_nicho"
        ] += 1

        return False

    if conta_institucional(
        instagram,
        texto_novo
    ):

        bloqueados_execucao.add(
            instagram
        )

        estatisticas[
            "institucionais"
        ] += 1

        return False

    chave = (
        instituicao["id"],
        instagram
    )

    if chave not in evidencias_perfis:

        evidencias_perfis[
            chave
        ] = {
            "textos": [],
            "titulo": titulo,
            "url": url,
        }

        estatisticas[
            "perfis_unicos"
        ] += 1

    evidencias_perfis[
        chave
    ]["textos"].append(
        texto_novo
    )

    texto_completo = " ".join(
        evidencias_perfis[
            chave
        ]["textos"]
    )

    if not e_nutricao(
        texto_completo
    ):
        return False

    if not e_coorte_alvo(
        texto_completo
    ):
        return False

    pontos = calcular_pontuacao(
        texto_completo,
        instagram,
        instituicao
    )

    if pontos < PONTUACAO_MINIMA:
        return False

    if (
        instagram
        not in qualificados_execucao
    ):

        qualificados_execucao.add(
            instagram
        )

        estatisticas[
            "qualificados"
        ] += 1

    evidencia = montar_evidencia(
        texto_completo
    )

    nome = re.sub(
        r"\s[\|\-–—].*$",
        "",
        titulo
    ).strip()

    if not nome:

        nome = (
            instagram
            .replace("@", "")
        )

    print("")
    print(
        f"      🎯 QUALIFICADO: "
        f"{instagram}"
    )

    print(
        f"         {evidencia}"
    )

    lead = {
        "nome":
            nome[:150],

        "instagram":
            instagram,

        "whatsapp":
            None,

        "nicho":
            "nutricionista",

        "origem":
            "eMEC_busca_web",

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

        "data_primeiro_contato":
            None,

        "data_ultimo_contato":
            None,

        "proxima_acao":
            None,

        "funil_destino":
            None,

        "cidade":
            instituicao["cidade"],

        "estado":
            instituicao["estado"],

        "instituicao":
            instituicao[
                "instituicao"
            ],

        "pontuacao":
            pontos,

        "evidencia":
            evidencia,

        "fonte_url":
            evidencias_perfis[
                chave
            ]["url"],
    }

    return salvar_lead(
        lead
    )


# ============================================================
# PROCESSAR FACULDADE
# ============================================================

def processar_faculdade(
    ddgs,
    instituicao
):

    print("")
    print(
        "================================================="
    )

    print(
        "🏫 FACULDADE CONFIRMADA PELO e-MEC"
    )

    print(
        f"   {instituicao['instituicao']}"
    )

    print(
        f"📍 {instituicao['cidade']}/"
        f"{instituicao['estado']}"
    )

    print(
        "================================================="
    )

    atualizar_status_faculdade(
        instituicao["id"],
        "processando"
    )

    consultas = montar_consultas_leads(
        instituicao
    )

    total = len(
        consultas
    )

    checkpoint = obter_checkpoint_leads(
        instituicao
    )

    inicio = 0

    if checkpoint:

        status = (
            checkpoint.get("status")
            or ""
        )

        indice = (
            checkpoint.get(
                "indice_pesquisa"
            )
            or 0
        )

        if (
            status in [
                "processando",
                "erro",
                "pendente"
            ]
        ):

            inicio = max(
                0,
                indice
            )

            if inicio >= total:
                inicio = total - 1

            if inicio > 0:

                print(
                    f"♻️ Retomando pesquisa "
                    f"{inicio + 1}/{total}"
                )

    salvos_antes = (
        estatisticas["salvos"]
    )

    encontrados = 0

    for posicao in range(
        inicio,
        total
    ):

        numero = posicao + 1

        consulta = (
            consultas[
                posicao
            ]
        )

        print(
            f"   🔍 Pesquisa "
            f"{numero}/{total}"
        )

        salvar_checkpoint_leads(
            instituicao=instituicao,
            status="processando",
            indice=posicao,
            total=total,
            consulta=consulta,
            encontrados=encontrados,
            salvos=(
                estatisticas["salvos"]
                - salvos_antes
            )
        )

        resultados, ok, erro = (
            pesquisar_leads(
                ddgs,
                consulta
            )
        )

        if not ok:

            salvar_checkpoint_leads(
                instituicao=instituicao,
                status="erro",
                indice=posicao,
                total=total,
                consulta=consulta,
                encontrados=encontrados,
                salvos=(
                    estatisticas["salvos"]
                    - salvos_antes
                ),
                erro=erro
            )

            atualizar_status_faculdade(
                instituicao["id"],
                "pendente"
            )

            return False

        for resultado in resultados:

            encontrados += 1

            processar_resultado_lead(
                resultado,
                instituicao
            )

        salvar_checkpoint_leads(
            instituicao=instituicao,
            status="processando",
            indice=(
                posicao + 1
            ),
            total=total,
            consulta=consulta,
            encontrados=encontrados,
            salvos=(
                estatisticas["salvos"]
                - salvos_antes
            )
        )

        pausa_busca()

    salvos_local = (
        estatisticas["salvos"]
        - salvos_antes
    )

    salvar_checkpoint_leads(
        instituicao=instituicao,
        status="concluido",
        indice=total,
        total=total,
        consulta="concluido",
        encontrados=encontrados,
        salvos=salvos_local
    )

    atualizar_status_faculdade(
        instituicao["id"],
        "concluido"
    )

    estatisticas[
        "faculdades_processadas"
    ] += 1

    print(
        f"✅ FACULDADE CONCLUÍDA "
        f"| Leads salvos: "
        f"{salvos_local}"
    )

    return True


# ============================================================
# RECUPERAR FACULDADE INTERROMPIDA
# ============================================================

def recuperar_interrompidas():

    try:

        resposta = (
            supabase
            .table(
                "instituicoes_nutricao"
            )
            .select("id")
            .eq(
                "status",
                "processando"
            )
            .execute()
        )

        registros = (
            resposta.data
            or []
        )

        for registro in registros:

            (
                supabase
                .table(
                    "instituicoes_nutricao"
                )
                .update({
                    "status":
                        "pendente"
                })
                .eq(
                    "id",
                    registro["id"]
                )
                .execute()
            )

    except Exception as erro:

        print(
            f"⚠️ Erro recuperando fila: "
            f"{erro}"
        )


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def executar():

    recuperar_interrompidas()

    faculdades_processadas_execucao = 0

    with DDGS() as ddgs:

        for uf, estado_nome in ESTADOS:

            if (
                faculdades_processadas_execucao
                >= MAX_FACULDADES_POR_EXECUCAO
            ):
                break

            estatisticas[
                "estados_visitados"
            ] += 1

            print("")
            print(
                "#################################################"
            )

            print(
                f"🇧🇷 ESTADO: "
                f"{estado_nome}/{uf}"
            )

            print(
                "#################################################"
            )

            # ------------------------------------------------
            # PRIMEIRO:
            # usa faculdades já descobertas.
            # ------------------------------------------------

            restante = (
                MAX_FACULDADES_POR_EXECUCAO
                - faculdades_processadas_execucao
            )

            faculdades = (
                buscar_faculdades_pendentes(
                    uf,
                    restante
                )
            )

            # ------------------------------------------------
            # SE A FILA NÃO TEM FACULDADES SUFICIENTES:
            # abastece diretamente pelo e-MEC.
            # ------------------------------------------------

            if len(faculdades) < restante:

                descobrir_faculdades_emec(
                    uf,
                    estado_nome
                )

                restante = (
                    MAX_FACULDADES_POR_EXECUCAO
                    - faculdades_processadas_execucao
                )

                faculdades = (
                    buscar_faculdades_pendentes(
                        uf,
                        restante
                    )
                )

            # ------------------------------------------------
            # PESQUISA OS LEADS
            # ------------------------------------------------

            for faculdade in faculdades:

                if (
                    faculdades_processadas_execucao
                    >= MAX_FACULDADES_POR_EXECUCAO
                ):
                    break

                processar_faculdade(
                    ddgs,
                    faculdade
                )

                faculdades_processadas_execucao += 1

            # Mantemos foco no estado até completar
            # sua varredura oficial.
            checkpoint = obter_checkpoint_emec(
                uf
            )

            emec_finalizado = (
                checkpoint
                and checkpoint.get("status")
                == "concluido"
            )

            if not emec_finalizado:

                print("")
                print(
                    f"⏸️ A varredura oficial "
                    f"de {uf} ainda não acabou."
                )

                print(
                    "A próxima execução "
                    "continua neste estado."
                )

                break


# ============================================================
# INÍCIO
# ============================================================

print("")
print(
    "================================================="
)

print(
    "MÁQUINA NACIONAL DE LEADS"
)

print(
    "NICHO: NUTRIÇÃO"
)

print(
    "================================================="
)

print(
    "Descoberta: e-MEC oficial online"
)

print(
    "Sem download manual."
)

print(
    "Sem Google para descobrir faculdade."
)

print(
    "================================================="
)

print(
    "Fluxo:"
)

print(
    "e-MEC > Estado > Município > "
    "Faculdade > Campus > Nutrição"
)

print(
    "Depois:"
)

print(
    "Faculdade > Lead > Supabase"
)

print(
    "================================================="
)


executar()


# ============================================================
# RESUMO
# ============================================================

print("")
print(
    "================================================="
)

print(
    "RESUMO FINAL"
)

print(
    "================================================="
)

print(
    f"Estados visitados: "
    f"{estatisticas['estados_visitados']}"
)

print(
    f"Municípios oficiais analisados: "
    f"{estatisticas['municipios_emec']}"
)

print(
    f"IES oficiais analisadas: "
    f"{estatisticas['ies_emec_analisadas']}"
)

print(
    f"Campi analisados: "
    f"{estatisticas['campus_analisados']}"
)

print(
    f"Faculdades com Nutrição encontradas: "
    f"{estatisticas['instituicoes_nutricao_encontradas']}"
)

print(
    f"Novas faculdades salvas: "
    f"{estatisticas['instituicoes_novas']}"
)

print(
    f"Faculdades pesquisadas para leads: "
    f"{estatisticas['faculdades_processadas']}"
)

print(
    f"Pesquisas de leads: "
    f"{estatisticas['pesquisas_leads']}"
)

print(
    f"Resultados analisados: "
    f"{estatisticas['resultados_analisados']}"
)

print(
    f"Perfis únicos: "
    f"{estatisticas['perfis_unicos']}"
)

print(
    f"Institucionais rejeitados: "
    f"{estatisticas['institucionais']}"
)

print(
    f"Fora do nicho: "
    f"{estatisticas['fora_nicho']}"
)

print(
    f"Leads qualificados: "
    f"{estatisticas['qualificados']}"
)

print(
    f"Leads salvos: "
    f"{estatisticas['salvos']}"
)

print(
    f"Duplicados: "
    f"{estatisticas['duplicados']}"
)

print(
    f"Pesquisas sem resultado: "
    f"{estatisticas['sem_resultado']}"
)

print(
    f"Erros: "
    f"{estatisticas['erros']}"
)

print(
    "================================================="
)

print(
    "Execução encerrada."
)

print(
    "Todo progresso permanece no Supabase."
)

print(
    "================================================="
)
