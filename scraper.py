import os
import re
import time
import random
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from ddgs import DDGS
from supabase import create_client


# ============================================================
# MÁQUINA NACIONAL DE LEADS - NUTRIÇÃO
# VERSÃO COM FILTRO MAIS RÍGIDO
# ============================================================

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
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
# CONFIGURAÇÕES
# ============================================================

MAX_FACULDADES_POR_EXECUCAO = 5

MAX_RESULTADOS_DESCOBERTA = 35
MAX_RESULTADOS_LEADS = 25

MAX_TENTATIVAS_BUSCA = 3
MAX_TENTATIVAS_SUPABASE = 3

PAUSA_MIN = 4.0
PAUSA_MAX = 7.0

PONTUACAO_MINIMA = 9


# ============================================================
# ESTATÍSTICAS
# ============================================================

estatisticas = {
    "estados_visitados": 0,
    "pesquisas_realizadas": 0,
    "instituicoes_descobertas": 0,
    "instituicoes_validadas": 0,
    "instituicoes_revisar": 0,
    "instituicoes_processadas": 0,
    "resultados_analisados": 0,
    "perfis_unicos": 0,
    "qualificados": 0,
    "salvos": 0,
    "duplicados": 0,
    "institucionais": 0,
    "rejeitados": 0,
    "sem_resultado": 0,
    "erros": 0,
}


# ============================================================
# MEMÓRIA DA EXECUÇÃO
# ============================================================

evidencias_perfis = {}

salvos_execucao = set()

qualificados_execucao = set()

bloqueados_execucao = set()

cache_municipios = {}


# ============================================================
# UTILIDADES
# ============================================================

def agora_iso():
    return datetime.now(
        timezone.utc
    ).isoformat()


def normalizar_texto(texto):

    if not texto:
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


def normalizar_instagram(instagram):

    if not instagram:
        return None

    instagram = (
        instagram
        .strip()
        .lower()
    )

    if not instagram.startswith("@"):
        instagram = "@" + instagram

    return instagram


def pausa():

    time.sleep(
        random.uniform(
            PAUSA_MIN,
            PAUSA_MAX
        )
    )


# ============================================================
# BUSCA WEB
# ============================================================

def pesquisar(
    ddgs,
    consulta,
    max_results
):

    estatisticas[
        "pesquisas_realizadas"
    ] += 1

    ultimo_erro = None

    for tentativa in range(
        1,
        MAX_TENTATIVAS_BUSCA + 1
    ):

        try:

            resultados = list(
                ddgs.text(
                    consulta,
                    max_results=max_results
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
                f"⚠️ Falha na busca "
                f"{tentativa}/"
                f"{MAX_TENTATIVAS_BUSCA}"
            )

            print(
                f"   {ultimo_erro}"
            )

            if tentativa < MAX_TENTATIVAS_BUSCA:

                espera = (
                    10 * tentativa
                )

                print(
                    f"   Nova tentativa "
                    f"em {espera}s..."
                )

                time.sleep(
                    espera
                )

    estatisticas[
        "erros"
    ] += 1

    return (
        [],
        False,
        ultimo_erro
    )


# ============================================================
# MUNICÍPIOS DO IBGE
#
# Serve somente para IDENTIFICAR a cidade
# encontrada no resultado.
# Não fazemos busca cidade por cidade.
# ============================================================

def carregar_municipios(uf):

    if uf in cache_municipios:
        return cache_municipios[uf]

    url = (
        "https://servicodados.ibge.gov.br/"
        f"api/v1/localidades/estados/"
        f"{uf}/municipios"
    )

    try:

        resposta = requests.get(
            url,
            timeout=30
        )

        resposta.raise_for_status()

        dados = resposta.json()

        municipios = []

        for item in dados:

            nome = item.get("nome")

            if nome:
                municipios.append(nome)

        municipios.sort(
            key=len,
            reverse=True
        )

        cache_municipios[
            uf
        ] = municipios

        return municipios

    except Exception as erro:

        print(
            f"❌ Erro carregando "
            f"municípios de {uf}: "
            f"{erro}"
        )

        estatisticas["erros"] += 1

        return []


def detectar_cidade_em_texto(
    texto,
    municipios
):

    texto_norm = normalizar_texto(
        texto
    )

    for municipio in municipios:

        municipio_norm = (
            normalizar_texto(
                municipio
            )
        )

        padrao = (
            r"(?<!\w)"
            + re.escape(municipio_norm)
            + r"(?!\w)"
        )

        if re.search(
            padrao,
            texto_norm
        ):
            return municipio

    return None


def detectar_cidade_resultado(
    titulo,
    corpo,
    municipios
):

    # Primeiro tenta título.
    cidade = detectar_cidade_em_texto(
        titulo,
        municipios
    )

    if cidade:
        return cidade

    # Depois descrição.
    cidade = detectar_cidade_em_texto(
        corpo,
        municipios
    )

    return cidade


# ============================================================
# FONTES
# ============================================================

def classificar_fonte(url):

    url_norm = (
        url or ""
    ).lower()

    dominio = ""

    try:

        dominio = (
            urlparse(url)
            .netloc
            .lower()
        )

    except Exception:
        pass

    if "emec.mec.gov.br" in url_norm:

        return (
            "e_mec",
            True
        )

    if "gov.br" in dominio:

        return (
            "fonte_oficial",
            True
        )

    if (
        ".edu.br" in dominio
        or dominio.endswith("edu.br")
    ):

        return (
            "site_educacional",
            True
        )

    return (
        "busca_web",
        False
    )


# ============================================================
# DOMÍNIOS QUE NÃO SERVEM PARA DESCOBRIR FACULDADE
# ============================================================

DOMINIOS_RUINS_INSTITUICAO = [
    "instagram.com",
    "facebook.com",
    "linkedin.com",
    "youtube.com",
    "tiktok.com",
    "rocketreach.co",
    "zoominfo.com",
    "signalhire.com",
    "apollo.io",
    "contactout.com",
    "lusha.com",
]


def dominio_ruim_instituicao(url):

    try:

        dominio = (
            urlparse(url)
            .netloc
            .lower()
        )

        return any(
            ruim in dominio
            for ruim in DOMINIOS_RUINS_INSTITUICAO
        )

    except Exception:

        return True


# ============================================================
# INSTITUIÇÕES
# ============================================================

PALAVRAS_INSTITUICAO = [
    "universidade",
    "faculdade",
    "centro universitario",
    "centro universitário",
    "instituto federal",
    "instituto de ensino",
    "ceunsp",
    "uniso",
    "unip",
    "uninove",
    "unicesumar",
    "uninter",
    "anhanguera",
    "estacio",
    "estácio",
    "cruzeiro do sul",
    "uniesp",
    "unifesp",
    "usp",
    "unesp",
]


NOMES_GENERICOS_INSTITUICAO = [
    "faculdade de nutricao em",
    "faculdade de nutrição em",
    "curso de nutricao em",
    "curso de nutrição em",
    "graduacao em nutricao em",
    "graduação em nutrição em",
    "nutricao em sao paulo",
    "nutrição em são paulo",
    "email & phone number",
    "email and phone number",
    "phone number",
    "contato telefone",
    "salario",
    "salary",
    "vagas",
    "empregos",
]


def nome_instituicao_suspeito(nome):

    nome_norm = normalizar_texto(
        nome
    )

    if not nome_norm:
        return True

    if len(nome_norm) < 4:
        return True

    if any(
        normalizar_texto(termo)
        in nome_norm
        for termo
        in NOMES_GENERICOS_INSTITUICAO
    ):
        return True

    # Não queremos título que seja claramente pessoa.
    if (
        "email" in nome_norm
        and "phone" in nome_norm
    ):
        return True

    return False


def resultado_parece_instituicao(texto):

    texto_norm = normalizar_texto(
        texto
    )

    if "nutricao" not in texto_norm:
        return False

    sinais = [
        "universidade",
        "faculdade",
        "centro universitario",
        "instituto",
        "graduacao",
        "bacharelado",
        "curso",
    ]

    return any(
        sinal in texto_norm
        for sinal in sinais
    )


def extrair_nome_instituicao(titulo):

    if not titulo:
        return None

    titulo = re.sub(
        r"\s+",
        " ",
        titulo
    ).strip()

    partes = re.split(
        r"\s[\|\-–—:]\s",
        titulo
    )

    candidatos = []

    for parte in partes:

        parte = parte.strip()

        parte_norm = normalizar_texto(
            parte
        )

        if any(
            normalizar_texto(palavra)
            in parte_norm
            for palavra
            in PALAVRAS_INSTITUICAO
        ):

            candidatos.append(
                parte
            )

    # Preferência por uma parte que pareça
    # realmente nome de instituição.
    for candidato in candidatos:

        if not nome_instituicao_suspeito(
            candidato
        ):

            return candidato[:180]

    # Tentativa complementar
    for parte in reversed(partes):

        parte = parte.strip()

        if len(parte) < 4:
            continue

        if nome_instituicao_suspeito(
            parte
        ):
            continue

        parte_norm = normalizar_texto(
            parte
        )

        if "nutricao" in parte_norm:
            continue

        if "graduacao" in parte_norm:
            continue

        if "vestibular" in parte_norm:
            continue

        return parte[:180]

    return None


def nome_instituicao_equivalente(
    nome1,
    nome2
):

    n1 = normalizar_texto(
        nome1
    )

    n2 = normalizar_texto(
        nome2
    )

    if not n1 or not n2:
        return False

    if n1 == n2:
        return True

    if (
        n1 in n2
        or n2 in n1
    ):

        if min(
            len(n1),
            len(n2)
        ) >= 7:
            return True

    return False


# ============================================================
# BUSCAR INSTITUIÇÃO EXISTENTE
# ============================================================

def buscar_instituicao_existente(
    uf,
    cidade,
    instituicao
):

    try:

        resposta = (
            supabase
            .table("instituicoes_nutricao")
            .select(
                "id,instituicao,"
                "validada,status"
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

        for registro in registros:

            if nome_instituicao_equivalente(
                registro.get("instituicao"),
                instituicao
            ):

                return registro

        return None

    except Exception as erro:

        print(
            f"⚠️ Erro verificando "
            f"instituição existente: "
            f"{erro}"
        )

        return "ERRO"


# ============================================================
# SALVAR INSTITUIÇÃO
# ============================================================

def salvar_instituicao(
    uf,
    cidade,
    instituicao,
    origem,
    fonte_url,
    validada
):

    if nome_instituicao_suspeito(
        instituicao
    ):

        print(
            f"   ❌ Nome de instituição "
            f"suspeito ignorado: "
            f"{instituicao}"
        )

        return False

    existente = (
        buscar_instituicao_existente(
            uf,
            cidade,
            instituicao
        )
    )

    if existente == "ERRO":
        return False

    if existente:

        if (
            validada
            and not existente.get(
                "validada"
            )
        ):

            try:

                (
                    supabase
                    .table(
                        "instituicoes_nutricao"
                    )
                    .update({
                        "validada":
                            True,

                        "fonte_validacao":
                            origem,

                        "fonte_url":
                            fonte_url,

                        "ultima_verificacao":
                            agora_iso(),
                    })
                    .eq(
                        "id",
                        existente["id"]
                    )
                    .execute()
                )

            except Exception:
                pass

        return False

    dados = {
        "estado":
            uf,

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

        "ultima_verificacao":
            agora_iso(),

        "fonte_validacao":
            origem if validada else None,

        "validada":
            validada,

        "tentativa_descoberta":
            1,
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
            "instituicoes_descobertas"
        ] += 1

        print("")
        print(
            "   🏫 INSTITUIÇÃO ENCONTRADA"
        )

        print(
            f"      {instituicao}"
        )

        print(
            f"      {cidade}/{uf}"
        )

        print(
            f"      Fonte: {origem}"
        )

        return True

    except Exception as erro:

        print(
            f"⚠️ Erro salvando "
            f"instituição: {erro}"
        )

        estatisticas[
            "erros"
        ] += 1

        return False


# ============================================================
# CHECKPOINT
# ============================================================

def buscar_checkpoint(
    estado,
    etapa,
    cidade=None,
    instituicao=None
):

    try:

        consulta = (
            supabase
            .table("controle_busca")
            .select("*")
            .eq(
                "estado",
                estado
            )
            .eq(
                "etapa",
                etapa
            )
        )

        if cidade is None:

            consulta = (
                consulta
                .is_(
                    "cidade",
                    "null"
                )
            )

        else:

            consulta = (
                consulta
                .eq(
                    "cidade",
                    cidade
                )
            )

        if instituicao is None:

            consulta = (
                consulta
                .is_(
                    "instituicao",
                    "null"
                )
            )

        else:

            consulta = (
                consulta
                .eq(
                    "instituicao",
                    instituicao
                )
            )

        resposta = (
            consulta
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


def salvar_checkpoint(
    estado,
    etapa,
    status,
    indice_pesquisa,
    total_pesquisas,
    consulta_atual=None,
    fonte_atual=None,
    cidade=None,
    instituicao=None,
    leads_encontrados=0,
    leads_salvos=0,
    ultimo_erro=None
):

    atual = buscar_checkpoint(
        estado=estado,
        etapa=etapa,
        cidade=cidade,
        instituicao=instituicao
    )

    dados = {
        "estado":
            estado,

        "cidade":
            cidade,

        "instituicao":
            instituicao,

        "etapa":
            etapa,

        "status":
            status,

        "indice_pesquisa":
            indice_pesquisa,

        "total_pesquisas":
            total_pesquisas,

        "consulta_atual":
            consulta_atual,

        "fonte_atual":
            fonte_atual,

        "leads_encontrados":
            leads_encontrados,

        "leads_salvos":
            leads_salvos,

        "ultimo_erro":
            ultimo_erro,

        "atualizado_em":
            agora_iso(),
    }

    if (
        not atual
        and status == "processando"
    ):

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
            f"⚠️ Erro salvando "
            f"checkpoint: {erro}"
        )

        estatisticas["erros"] += 1

        return False


# ============================================================
# DESCOBERTA DE INSTITUIÇÕES
# ============================================================

def montar_consultas_descoberta(
    uf,
    estado_nome
):

    return [

        (
            f'"curso de Nutrição" '
            f'"{estado_nome}" '
            f'faculdade universidade'
        ),

        (
            f'"graduação em Nutrição" '
            f'"{estado_nome}" '
            f'universidade faculdade'
        ),

        (
            f'"bacharelado em Nutrição" '
            f'"{estado_nome}"'
        ),

        (
            f'site:edu.br '
            f'"Nutrição" '
            f'"{estado_nome}"'
        ),

        (
            f'site:gov.br '
            f'"Nutrição" '
            f'"{estado_nome}" '
            f'universidade'
        ),

        (
            f'site:emec.mec.gov.br '
            f'"Nutrição" '
            f'"{uf}"'
        ),

        (
            f'"Nutrição" '
            f'"{uf}" '
            f'"Centro Universitário"'
        ),

        (
            f'"Nutrição" '
            f'"{uf}" '
            f'"Faculdade"'
        ),
    ]


def descobrir_instituicoes_estado(
    ddgs,
    uf,
    estado_nome
):

    municipios = carregar_municipios(
        uf
    )

    if not municipios:
        return False

    consultas = montar_consultas_descoberta(
        uf,
        estado_nome
    )

    total = len(consultas)

    checkpoint = buscar_checkpoint(
        estado=uf,
        etapa="descoberta_instituicoes"
    )

    inicio = 1

    if checkpoint:

        if (
            checkpoint.get("status")
            == "concluido"
        ):

            print(
                f"✅ Descoberta de "
                f"{uf} já concluída."
            )

            return True

        indice = (
            checkpoint.get(
                "indice_pesquisa"
            )
            or 1
        )

        inicio = max(
            1,
            indice
        )

    print("")
    print(
        "================================================="
    )

    print(
        f"🔎 DESCOBERTA DE INSTITUIÇÕES "
        f"- {estado_nome}/{uf}"
    )

    print(
        "================================================="
    )

    for numero in range(
        inicio,
        total + 1
    ):

        consulta = consultas[
            numero - 1
        ]

        print("")
        print(
            f"🔍 Descoberta "
            f"{numero}/{total}"
        )

        salvar_checkpoint(
            estado=uf,
            etapa="descoberta_instituicoes",
            status="processando",
            indice_pesquisa=numero,
            total_pesquisas=total,
            consulta_atual=consulta,
            fonte_atual="web"
        )

        resultados, ok, erro = pesquisar(
            ddgs,
            consulta,
            MAX_RESULTADOS_DESCOBERTA
        )

        if not ok:

            salvar_checkpoint(
                estado=uf,
                etapa="descoberta_instituicoes",
                status="erro",
                indice_pesquisa=numero,
                total_pesquisas=total,
                consulta_atual=consulta,
                fonte_atual="web",
                ultimo_erro=erro
            )

            return False

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
                or resultado.get("url")
                or ""
            )

            if dominio_ruim_instituicao(
                url
            ):
                continue

            texto = (
                f"{titulo} "
                f"{corpo} "
                f"{url}"
            )

            if not resultado_parece_instituicao(
                texto
            ):
                continue

            cidade = detectar_cidade_resultado(
                titulo,
                corpo,
                municipios
            )

            if not cidade:
                continue

            instituicao = extrair_nome_instituicao(
                titulo
            )

            if not instituicao:
                continue

            if nome_instituicao_suspeito(
                instituicao
            ):
                continue

            origem, forte = classificar_fonte(
                url
            )

            salvar_instituicao(
                uf=uf,
                cidade=cidade,
                instituicao=instituicao,
                origem=origem,
                fonte_url=url,
                validada=forte
            )

        salvar_checkpoint(
            estado=uf,
            etapa="descoberta_instituicoes",
            status="processando",
            indice_pesquisa=
                numero + 1,
            total_pesquisas=total,
            consulta_atual=consulta,
            fonte_atual="web"
        )

        pausa()

    salvar_checkpoint(
        estado=uf,
        etapa="descoberta_instituicoes",
        status="concluido",
        indice_pesquisa=total,
        total_pesquisas=total,
        consulta_atual="concluido",
        fonte_atual="web"
    )

    print("")
    print(
        f"✅ Descoberta de "
        f"{uf} concluída."
    )

    return True


# ============================================================
# FILA DE FACULDADES
# ============================================================

def buscar_instituicoes_pendentes(
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
            .order("cidade")
            .limit(limite)
            .execute()
        )

        return (
            resposta.data
            or []
        )

    except Exception as erro:

        print(
            f"❌ Erro buscando "
            f"faculdades pendentes: "
            f"{erro}"
        )

        estatisticas["erros"] += 1

        return []


def atualizar_instituicao(
    instituicao_id,
    dados
):

    dados[
        "ultima_verificacao"
    ] = agora_iso()

    try:

        (
            supabase
            .table(
                "instituicoes_nutricao"
            )
            .update(dados)
            .eq(
                "id",
                instituicao_id
            )
            .execute()
        )

        return True

    except Exception as erro:

        print(
            f"⚠️ Erro atualizando "
            f"instituição: {erro}"
        )

        return False


# ============================================================
# VALIDAR FACULDADE
# ============================================================

def validar_instituicao(
    ddgs,
    instituicao
):

    nome = instituicao[
        "instituicao"
    ]

    cidade = instituicao[
        "cidade"
    ]

    # Mesmo que uma instituição antiga esteja
    # validada, nomes claramente ruins são rejeitados.
    if nome_instituicao_suspeito(
        nome
    ):

        print(
            f"   ❌ Instituição suspeita: "
            f"{nome}"
        )

        atualizar_instituicao(
            instituicao["id"],
            {
                "status":
                    "revisar",

                "validada":
                    False,
            }
        )

        estatisticas[
            "instituicoes_revisar"
        ] += 1

        return False

    if instituicao.get(
        "validada"
    ):

        return True

    print("")
    print(
        "   🔎 Validando instituição:"
    )

    print(
        f"      {nome}"
    )

    consultas = [

        (
            f'"{nome}" '
            f'"{cidade}" '
            f'"Nutrição"'
        ),

        (
            f'site:edu.br '
            f'"{nome}" '
            f'"Nutrição"'
        ),

        (
            f'site:gov.br '
            f'"{nome}" '
            f'"Nutrição"'
        ),

        (
            f'site:emec.mec.gov.br '
            f'"{nome}" '
            f'"Nutrição"'
        ),
    ]

    for consulta in consultas:

        resultados, ok, erro = pesquisar(
            ddgs,
            consulta,
            15
        )

        if not ok:
            continue

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
                or resultado.get("url")
                or ""
            )

            if dominio_ruim_instituicao(
                url
            ):
                continue

            texto = normalizar_texto(
                f"{titulo} "
                f"{corpo} "
                f"{url}"
            )

            if "nutricao" not in texto:
                continue

            origem, forte = classificar_fonte(
                url
            )

            nome_norm = normalizar_texto(
                nome
            )

            cidade_norm = normalizar_texto(
                cidade
            )

            palavras_nome = [
                palavra
                for palavra
                in nome_norm.split()
                if len(palavra) >= 5
            ]

            confirma_nome = (
                nome_norm in texto
                or any(
                    palavra in texto
                    for palavra
                    in palavras_nome
                )
            )

            confirma_cidade = (
                cidade_norm
                in texto
            )

            if (
                confirma_nome
                and (
                    forte
                    or confirma_cidade
                )
            ):

                atualizar_instituicao(
                    instituicao["id"],
                    {
                        "validada":
                            True,

                        "fonte_validacao":
                            origem,

                        "fonte_url":
                            url,
                    }
                )

                estatisticas[
                    "instituicoes_validadas"
                ] += 1

                print(
                    "      ✅ Instituição "
                    "validada."
                )

                return True

        pausa()

    atualizar_instituicao(
        instituicao["id"],
        {
            "status":
                "revisar",

            "validada":
                False,
        }
    )

    estatisticas[
        "instituicoes_revisar"
    ] += 1

    print(
        "      ⚠️ Instituição enviada "
        "para revisão."
    )

    return False


# ============================================================
# INSTAGRAM
# ============================================================

def extrair_instagram(url):

    if not url:
        return None

    try:

        parsed = urlparse(url)

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
            r"^[a-zA-Z0-9._]+$",
            usuario
        ):
            return None

        return normalizar_instagram(
            usuario
        )

    except Exception:

        return None


# ============================================================
# FILTRO DE CONTAS
# ============================================================

HANDLES_BLOQUEADOS = {
    "@popular",
    "@tcc_nutricao",
    "@nutricaocomportamental",
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
    "pet shop",
    "odontologia",
    "dentista",
    "fonoaudiologia",
    "fisioterapia",
    "fotografia",
    "fotografa",
    "fotografo",
    "advogada",
    "advogado",
    "engenharia",
    "arquitetura",
    "kumon",
]


TERMOS_INSTITUCIONAIS = [
    "turma de nutricao",
    "turma nutricao",
    "comissao de formatura",
    "comissao formatura",
    "centro academico",
    "diretorio academico",
    "atletica",
    "liga academica",
    "projeto de extensao",
    "evento academico",
    "semana academica",
    "congresso",
    "faculdade",
    "universidade",
    "centro universitario",
    "instituto de ensino",
]


PADROES_HANDLE_INSTITUCIONAL = [
    "formatura",
    "formandos",
    "formandas",
    "comissao",
    "atletica",
    "centroacademico",
    "centro_academico",
    "diretorio",
    "turmanutri",
    "turma_nutri",
    "nutriturma",
    "evento",
    "congresso",
    "faculdade",
    "universidade",
    "vestibular",
]


def fora_do_nicho(
    texto
):

    texto_norm = normalizar_texto(
        texto
    )

    return any(
        termo in texto_norm
        for termo in TERMOS_FORA_NICHO
    )


def tem_sinal_pessoal(
    texto
):

    texto_norm = normalizar_texto(
        texto
    )

    sinais = [
        "nutricionista",
        "graduanda em nutricao",
        "graduando em nutricao",
        "estudante de nutricao",
        "academica de nutricao",
        "academico de nutricao",
        "formanda em nutricao",
        "formando em nutricao",
        "crn",
        "me chamo",
        "sou nutricionista",
        "sou estudante",
        "atendimento online",
        "atendimento presencial",
        "agenda aberta",
        "consultas",
    ]

    return any(
        sinal in texto_norm
        for sinal in sinais
    )


def handle_institucional(
    instagram,
    texto
):

    instagram_norm = normalizar_texto(
        instagram
    )

    texto_norm = normalizar_texto(
        texto
    )

    if instagram in HANDLES_BLOQUEADOS:
        return True

    if any(
        termo in instagram_norm
        for termo
        in PADROES_HANDLE_INSTITUCIONAL
    ):
        return True

    # Contas no formato nutricao + universidade/faculdade.
    padroes_curso_institucional = [
        r"^@?nutricao[._-]?uf",
        r"^@?nutricao[._-]?uni",
        r"^@?nutricao[._-]?fac",
        r"^@?nutricao[._-]?fai",
        r"^@?nutricao[._-]?ies",
        r"^@?nutricao[._-]?unes",
        r"^@?nutricao[._-]?unif",
        r"^@?nutricao[._-]?centro",
        r"^@?nutricao[._-]?curso",
    ]

    for padrao in padroes_curso_institucional:

        if re.search(
            padrao,
            instagram_norm
        ):
            return True

    institucional_texto = any(
        termo in texto_norm
        for termo
        in TERMOS_INSTITUCIONAIS
    )

    if (
        institucional_texto
        and not tem_sinal_pessoal(
            texto
        )
    ):
        return True

    return False


# ============================================================
# PROVA DE NUTRIÇÃO
# ============================================================

def e_nutricao(
    texto,
    instagram
):

    texto_norm = normalizar_texto(
        texto
    )

    instagram_norm = normalizar_texto(
        instagram
    )

    sinais_fortes = [
        "nutricionista",
        "graduanda em nutricao",
        "graduando em nutricao",
        "estudante de nutricao",
        "academica de nutricao",
        "academico de nutricao",
        "formanda em nutricao",
        "formando em nutricao",
        "bacharel em nutricao",
        "crn",
    ]

    if any(
        sinal in texto_norm
        for sinal
        in sinais_fortes
    ):

        return True

    # Nutrição sozinha não basta.
    # Precisa contexto pessoal.
    if "nutricao" in texto_norm:

        contexto_pessoal = [
            "formanda",
            "formando",
            "graduanda",
            "graduando",
            "estudante",
            "academica",
            "academico",
            "atendimento",
            "consulta",
            "agenda aberta",
            "crn",
        ]

        if any(
            termo in texto_norm
            for termo
            in contexto_pessoal
        ):
            return True

    # Handle com "nutri" ajuda,
    # mas não aprova sozinho.
    if "nutri" in instagram_norm:

        contexto = [
            "formanda",
            "formando",
            "graduanda",
            "graduando",
            "estudante",
            "crn",
            "nutricionista",
            "atendimento",
            "consulta",
        ]

        if any(
            termo in texto_norm
            for termo
            in contexto
        ):
            return True

    return False


# ============================================================
# COORTE ALVO
# ============================================================

def e_coorte_alvo(
    texto
):

    texto_norm = normalizar_texto(
        texto
    )

    tem_2025 = (
        "2025" in texto_norm
    )

    tem_2026 = (
        "2026" in texto_norm
    )

    termos_conclusao = [
        "formatura",
        "formou",
        "formada",
        "formado",
        "colacao de grau",
        "colacao",
        "conclusao do curso",
        "concluiu",
        "bacharel",
    ]

    termos_final = [
        "formanda",
        "formando",
        "concluinte",
        "ultimo periodo",
        "ultimo semestre",
        "ultimo ano",
        "8/8",
        "7/8",
        "8 de 8",
        "7 de 8",
        "8 periodo",
        "7 periodo",
        "8o periodo",
        "7o periodo",
        "tcc",
        "trabalho de conclusao",
    ]

    tem_conclusao = any(
        termo in texto_norm
        for termo
        in termos_conclusao
    )

    tem_final = any(
        termo in texto_norm
        for termo
        in termos_final
    )

    formado_recente = (
        (
            tem_2025
            or tem_2026
        )
        and tem_conclusao
    )

    aluno_final = tem_final

    return (
        formado_recente
        or aluno_final
    )


# ============================================================
# PONTUAÇÃO
# ============================================================

def calcular_pontuacao(
    texto,
    instagram,
    cidade,
    instituicao
):

    texto_norm = normalizar_texto(
        texto
    )

    instagram_norm = normalizar_texto(
        instagram
    )

    pontos = 0

    if "nutricionista" in texto_norm:
        pontos += 4

    if "nutricao" in texto_norm:
        pontos += 3

    if "crn" in texto_norm:
        pontos += 3

    if "nutri" in instagram_norm:
        pontos += 2

    sinais_final = [
        "formanda",
        "formando",
        "concluinte",
        "ultimo periodo",
        "ultimo semestre",
        "8/8",
        "7/8",
        "tcc",
    ]

    if any(
        termo in texto_norm
        for termo
        in sinais_final
    ):
        pontos += 5

    if "2026" in texto_norm:
        pontos += 4

    if "2025" in texto_norm:
        pontos += 3

    cidade_norm = normalizar_texto(
        cidade
    )

    if (
        cidade_norm
        and cidade_norm
        in texto_norm
    ):
        pontos += 2

    instituicao_norm = normalizar_texto(
        instituicao
    )

    if (
        instituicao_norm
        and instituicao_norm
        in texto_norm
    ):
        pontos += 2

    termos_comerciais = [
        "agenda aberta",
        "consultas",
        "atendimentos",
        "atendimento online",
        "atendimento presencial",
    ]

    if any(
        termo in texto_norm
        for termo
        in termos_comerciais
    ):
        pontos += 1

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
        (
            "nutricionista",
            "nutricionista"
        ),
        (
            "nutricao",
            "Nutrição"
        ),
        (
            "crn",
            "CRN"
        ),
        (
            "2025",
            "2025"
        ),
        (
            "2026",
            "2026"
        ),
        (
            "formanda",
            "formanda"
        ),
        (
            "formando",
            "formando"
        ),
        (
            "concluinte",
            "concluinte"
        ),
        (
            "ultimo periodo",
            "último período"
        ),
        (
            "ultimo semestre",
            "último semestre"
        ),
        (
            "8/8",
            "8/8"
        ),
        (
            "7/8",
            "7/8"
        ),
        (
            "tcc",
            "TCC"
        ),
        (
            "formatura",
            "formatura"
        ),
        (
            "colacao",
            "colação"
        ),
    ]

    for termo, descricao in mapa:

        if termo in texto_norm:

            itens.append(
                descricao
            )

    if not itens:

        return (
            "evidência pública "
            "encontrada"
        )

    return " | ".join(
        dict.fromkeys(
            itens
        )
    )


# ============================================================
# DUPLICIDADE
# ============================================================

def verificar_lead_existente(
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
                f"duplicidade "
                f"{instagram} "
                f"({tentativa}/"
                f"{MAX_TENTATIVAS_SUPABASE}): "
                f"{erro}"
            )

            if (
                tentativa
                < MAX_TENTATIVAS_SUPABASE
            ):

                time.sleep(
                    4 * tentativa
                )

    return None


# ============================================================
# NOME
# ============================================================

def limpar_nome(
    titulo,
    instagram
):

    if titulo:

        nome = re.sub(
            r"\s[\|\-–—].*$",
            "",
            titulo
        ).strip()

        nome = re.sub(
            r"\(@?[A-Za-z0-9._]+\)",
            "",
            nome
        ).strip()

        if nome:
            return nome[:150]

    return (
        instagram
        .replace("@", "")
        [:150]
    )


# ============================================================
# SALVAR LEAD
# ============================================================

def salvar_lead(
    lead
):

    instagram = lead[
        "instagram"
    ]

    if instagram in salvos_execucao:
        return False

    existente = verificar_lead_existente(
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

        print(
            f"      ⚠️ NÃO SALVO: "
            f"{instagram}"
        )

        print(
            "         Não foi possível "
            "confirmar duplicidade."
        )

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
                f"      ⚠️ Tentativa "
                f"{tentativa}/"
                f"{MAX_TENTATIVAS_SUPABASE} "
                f"ao salvar {instagram}: "
                f"{erro}"
            )

            if (
                tentativa
                < MAX_TENTATIVAS_SUPABASE
            ):

                time.sleep(
                    4 * tentativa
                )

    estatisticas[
        "erros"
    ] += 1

    print(
        f"      ❌ NÃO CONSEGUI SALVAR: "
        f"{instagram}"
    )

    return False


# ============================================================
# PROCESSAR RESULTADO
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

    texto_novo = (
        f"{titulo} "
        f"{corpo} "
        f"{url}"
    )

    # ----------------------------------------------
    # BLOQUEIOS
    # ----------------------------------------------

    if instagram in bloqueados_execucao:
        return False

    if fora_do_nicho(
        texto_novo
    ):

        bloqueados_execucao.add(
            instagram
        )

        estatisticas[
            "rejeitados"
        ] += 1

        print(
            f"      ❌ Fora do nicho: "
            f"{instagram}"
        )

        return False

    if handle_institucional(
        instagram,
        texto_novo
    ):

        bloqueados_execucao.add(
            instagram
        )

        estatisticas[
            "institucionais"
        ] += 1

        print(
            f"      🏢 Conta institucional: "
            f"{instagram}"
        )

        return False

    # ----------------------------------------------
    # ACUMULAR EVIDÊNCIAS
    # ----------------------------------------------

    if (
        instagram
        not in evidencias_perfis
    ):

        evidencias_perfis[
            instagram
        ] = {
            "textos": [],
            "titulo": titulo,
            "url": url,
        }

        estatisticas[
            "perfis_unicos"
        ] += 1

    evidencias_perfis[
        instagram
    ]["textos"].append(
        texto_novo
    )

    texto_completo = " ".join(
        evidencias_perfis[
            instagram
        ]["textos"]
    )

    # Se depois de acumular evidência
    # ficar claramente institucional,
    # rejeita.
    if handle_institucional(
        instagram,
        texto_completo
    ):

        bloqueados_execucao.add(
            instagram
        )

        estatisticas[
            "institucionais"
        ] += 1

        print(
            f"      🏢 Conta institucional: "
            f"{instagram}"
        )

        return False

    # ----------------------------------------------
    # NUTRIÇÃO
    # ----------------------------------------------

    if not e_nutricao(
        texto_completo,
        instagram
    ):

        print(
            f"      ⏳ Sem prova pessoal "
            f"de Nutrição: "
            f"{instagram}"
        )

        return False

    # ----------------------------------------------
    # COORTE
    # ----------------------------------------------

    if not e_coorte_alvo(
        texto_completo
    ):

        print(
            f"      ⏳ Nutrição confirmada, "
            f"mas sem prova de 2025/2026 "
            f"ou final de curso: "
            f"{instagram}"
        )

        return False

    # ----------------------------------------------
    # PONTUAÇÃO
    # ----------------------------------------------

    pontos = calcular_pontuacao(
        texto_completo,
        instagram,
        instituicao["cidade"],
        instituicao["instituicao"]
    )

    if pontos < PONTUACAO_MINIMA:

        print(
            f"      ⏳ Evidência fraca: "
            f"{instagram} | "
            f"{pontos} pontos"
        )

        return False

    # Evita contar/mostrar o mesmo perfil
    # como qualificado várias vezes.
    if (
        instagram
        in qualificados_execucao
    ):

        # Caso ainda não tenha sido salvo,
        # tenta salvar novamente.
        if (
            instagram
            not in salvos_execucao
        ):

            pass

        else:
            return False

    else:

        qualificados_execucao.add(
            instagram
        )

        estatisticas[
            "qualificados"
        ] += 1

    evidencia = montar_evidencia(
        texto_completo
    )

    print("")
    print(
        f"      🎯 QUALIFICADO: "
        f"{instagram}"
    )

    print(
        f"         Pontuação: "
        f"{pontos}"
    )

    print(
        f"         Evidência: "
        f"{evidencia}"
    )

    lead = {
        "nome":
            limpar_nome(
                evidencias_perfis[
                    instagram
                ]["titulo"],
                instagram
            ),

        "instagram":
            instagram,

        "whatsapp":
            None,

        "nicho":
            "nutricionista",

        "origem":
            "maquina_nacional_web",

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
            instituicao["instituicao"],

        "pontuacao":
            pontos,

        "evidencia":
            evidencia,

        "fonte_url":
            evidencias_perfis[
                instagram
            ]["url"],
    }

    return salvar_lead(
        lead
    )


# ============================================================
# CONSULTAS DE LEADS
# ============================================================

def montar_consultas_leads(
    instituicao
):

    nome = instituicao[
        "instituicao"
    ]

    cidade = instituicao[
        "cidade"
    ]

    uf = instituicao[
        "estado"
    ]

    exclusoes = (
        "-psicologia "
        "-maquiagem "
        "-makeup "
        "-veterinária "
        "-odontologia "
        "-memes "
        "-kumon "
        "-atletica "
        "-formatura "
        "-comissao"
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
            f'"graduanda" '
            f'"2026" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{nome}" '
            f'"Nutrição" '
            f'"graduando" '
            f'"2026" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{nome}" '
            f'"Nutrição" '
            f'"2026" '
            f'"colação" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{nome}" '
            f'"Nutrição" '
            f'"2025" '
            f'"colação" '
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
            f'"7/8" '
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
            f'"{nome}" '
            f'"Nutrição" '
            f'"último semestre" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{nome}" '
            f'"Nutrição" '
            f'"TCC" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{cidade}" '
            f'"{uf}" '
            f'"nutricionista" '
            f'"formanda" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{cidade}" '
            f'"{uf}" '
            f'"nutricionista" '
            f'"2026" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{cidade}" '
            f'"{uf}" '
            f'"nutricionista" '
            f'"2025" '
            f'{exclusoes}'
        ),
    ]


# ============================================================
# PROCESSAR FACULDADE
# ============================================================

def processar_faculdade(
    ddgs,
    instituicao
):

    nome = instituicao[
        "instituicao"
    ]

    cidade = instituicao[
        "cidade"
    ]

    uf = instituicao[
        "estado"
    ]

    print("")
    print(
        "================================================="
    )

    print(
        "🏫 FACULDADE"
    )

    print(
        f"   {nome}"
    )

    print(
        f"📍 {cidade}/{uf}"
    )

    print(
        "================================================="
    )

    if not validar_instituicao(
        ddgs,
        instituicao
    ):

        return False

    atualizar_instituicao(
        instituicao["id"],
        {
            "status":
                "processando"
        }
    )

    consultas = montar_consultas_leads(
        instituicao
    )

    total = len(consultas)

    checkpoint = buscar_checkpoint(
        estado=uf,
        cidade=cidade,
        instituicao=nome,
        etapa="busca_leads"
    )

    inicio = 1

    if checkpoint:

        if (
            checkpoint.get("status")
            == "concluido"
        ):

            atualizar_instituicao(
                instituicao["id"],
                {
                    "status":
                        "concluido"
                }
            )

            return True

        indice = (
            checkpoint.get(
                "indice_pesquisa"
            )
            or 1
        )

        inicio = max(
            1,
            indice
        )

        print(
            f"♻️ Retomando da pesquisa "
            f"{inicio}/{total}"
        )

    salvos_antes = estatisticas[
        "salvos"
    ]

    encontrados_local = 0

    for numero in range(
        inicio,
        total + 1
    ):

        consulta = consultas[
            numero - 1
        ]

        print("")
        print(
            f"   🔍 Pesquisa "
            f"{numero}/{total}"
        )

        salvar_checkpoint(
            estado=uf,
            cidade=cidade,
            instituicao=nome,
            etapa="busca_leads",
            status="processando",
            indice_pesquisa=numero,
            total_pesquisas=total,
            consulta_atual=consulta,
            fonte_atual="instagram_web",
            leads_encontrados=
                encontrados_local,
            leads_salvos=
                estatisticas["salvos"]
                - salvos_antes
        )

        resultados, ok, erro = pesquisar(
            ddgs,
            consulta,
            MAX_RESULTADOS_LEADS
        )

        if not ok:

            salvar_checkpoint(
                estado=uf,
                cidade=cidade,
                instituicao=nome,
                etapa="busca_leads",
                status="erro",
                indice_pesquisa=numero,
                total_pesquisas=total,
                consulta_atual=consulta,
                fonte_atual="instagram_web",
                leads_encontrados=
                    encontrados_local,
                leads_salvos=
                    estatisticas["salvos"]
                    - salvos_antes,
                ultimo_erro=erro
            )

            atualizar_instituicao(
                instituicao["id"],
                {
                    "status":
                        "pendente"
                }
            )

            return False

        for resultado in resultados:

            encontrados_local += 1

            processar_resultado_lead(
                resultado,
                instituicao
            )

        # Checkpoint aponta para a PRÓXIMA pesquisa.
        salvar_checkpoint(
            estado=uf,
            cidade=cidade,
            instituicao=nome,
            etapa="busca_leads",
            status="processando",
            indice_pesquisa=
                numero + 1,
            total_pesquisas=total,
            consulta_atual=consulta,
            fonte_atual="instagram_web",
            leads_encontrados=
                encontrados_local,
            leads_salvos=
                estatisticas["salvos"]
                - salvos_antes
        )

        pausa()

    salvos_local = (
        estatisticas["salvos"]
        - salvos_antes
    )

    salvar_checkpoint(
        estado=uf,
        cidade=cidade,
        instituicao=nome,
        etapa="busca_leads",
        status="concluido",
        indice_pesquisa=total,
        total_pesquisas=total,
        consulta_atual="concluido",
        fonte_atual="instagram_web",
        leads_encontrados=
            encontrados_local,
        leads_salvos=
            salvos_local
    )

    atualizar_instituicao(
        instituicao["id"],
        {
            "status":
                "concluido",

            "validada":
                True,
        }
    )

    estatisticas[
        "instituicoes_processadas"
    ] += 1

    print("")
    print(
        "✅ FACULDADE CONCLUÍDA"
    )

    print(
        f"   Leads salvos: "
        f"{salvos_local}"
    )

    return True


# ============================================================
# RECUPERAR PROCESSAMENTOS INTERROMPIDOS
# ============================================================

def recuperar_interrompidas():

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

        if registros:

            print(
                f"♻️ {len(registros)} "
                f"faculdade(s) interrompida(s) "
                f"voltaram para a fila."
            )

    except Exception as erro:

        print(
            f"⚠️ Erro recuperando "
            f"faculdades: {erro}"
        )


# ============================================================
# ESTADO
# ============================================================

def estado_descoberta_concluida(
    uf
):

    checkpoint = buscar_checkpoint(
        estado=uf,
        etapa="descoberta_instituicoes"
    )

    if not checkpoint:
        return False

    return (
        checkpoint.get("status")
        == "concluido"
    )


def existem_pendentes(
    uf
):

    try:

        resposta = (
            supabase
            .table(
                "instituicoes_nutricao"
            )
            .select("id")
            .eq(
                "estado",
                uf
            )
            .eq(
                "status",
                "pendente"
            )
            .limit(1)
            .execute()
        )

        return bool(
            resposta.data
        )

    except Exception:

        return True


# ============================================================
# EXECUÇÃO
# ============================================================

def executar():

    recuperar_interrompidas()

    faculdades_tentadas = 0

    with DDGS() as ddgs:

        for uf, estado_nome in ESTADOS:

            if (
                faculdades_tentadas
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

            # ----------------------------------------------
            # Descoberta
            # ----------------------------------------------

            if not estado_descoberta_concluida(
                uf
            ):

                sucesso = descobrir_instituicoes_estado(
                    ddgs,
                    uf,
                    estado_nome
                )

                if not sucesso:

                    print(
                        f"⚠️ Descoberta de "
                        f"{uf} interrompida."
                    )

                    break

            # ----------------------------------------------
            # Processamento das faculdades
            # ----------------------------------------------

            restante = (
                MAX_FACULDADES_POR_EXECUCAO
                - faculdades_tentadas
            )

            pendentes = buscar_instituicoes_pendentes(
                uf,
                restante
            )

            for instituicao in pendentes:

                if (
                    faculdades_tentadas
                    >= MAX_FACULDADES_POR_EXECUCAO
                ):
                    break

                faculdades_tentadas += 1

                processar_faculdade(
                    ddgs,
                    instituicao
                )

            if existem_pendentes(
                uf
            ):

                print("")
                print(
                    f"⏸️ {uf} ainda possui "
                    f"faculdades pendentes."
                )

                print(
                    "Na próxima execução "
                    "continuaremos nele."
                )

                break

            print("")
            print(
                f"✅ Estado {uf} sem "
                f"faculdades pendentes."
            )


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
    "Estado > Faculdade > Cidade > Lead"
)

print(
    "Filtro reforçado para pessoa real."
)

print(
    "Contas institucionais são rejeitadas."
)

print(
    "Lead qualificado é salvo imediatamente."
)

print(
    "Checkpoint após cada pesquisa."
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
    f"Pesquisas realizadas: "
    f"{estatisticas['pesquisas_realizadas']}"
)

print(
    f"Instituições descobertas: "
    f"{estatisticas['instituicoes_descobertas']}"
)

print(
    f"Instituições validadas: "
    f"{estatisticas['instituicoes_validadas']}"
)

print(
    f"Instituições enviadas para revisão: "
    f"{estatisticas['instituicoes_revisar']}"
)

print(
    f"Instituições processadas: "
    f"{estatisticas['instituicoes_processadas']}"
)

print(
    f"Resultados analisados: "
    f"{estatisticas['resultados_analisados']}"
)

print(
    f"Perfis únicos analisados: "
    f"{estatisticas['perfis_unicos']}"
)

print(
    f"Contas institucionais rejeitadas: "
    f"{estatisticas['institucionais']}"
)

print(
    f"Leads qualificados: "
    f"{estatisticas['qualificados']}"
)

print(
    f"Leads salvos no Supabase: "
    f"{estatisticas['salvos']}"
)

print(
    f"Duplicados ignorados: "
    f"{estatisticas['duplicados']}"
)

print(
    f"Outros rejeitados: "
    f"{estatisticas['rejeitados']}"
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
    "Todo progresso foi preservado "
    "no Supabase."
)

print(
    "================================================="
)
