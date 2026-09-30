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
# ============================================================
#
# NOVA ARQUITETURA
#
# BRASIL
#   ↓
# ESTADO
#   ↓
# DESCOBRE INSTITUIÇÕES COM CURSO DE NUTRIÇÃO
#   ↓
# IDENTIFICA A CIDADE
#   ↓
# VALIDA A INSTITUIÇÃO
#   ↓
# PESQUISA CANDIDATOS
#   ↓
# QUALIFICA
#   ↓
# SALVA O LEAD IMEDIATAMENTE
#   ↓
# ATUALIZA CHECKPOINT
#   ↓
# PRÓXIMA FACULDADE
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

MAX_RESULTADOS_DESCOBERTA = 40

MAX_RESULTADOS_LEADS = 25

MAX_TENTATIVAS_BUSCA = 3

PAUSA_MIN = 3.0
PAUSA_MAX = 5.0

PONTUACAO_MINIMA = 9


# ============================================================
# ESTATÍSTICAS
# ============================================================

estatisticas = {
    "estados_visitados": 0,
    "pesquisas_realizadas": 0,
    "instituicoes_descobertas": 0,
    "instituicoes_validadas": 0,
    "instituicoes_processadas": 0,
    "resultados_analisados": 0,
    "perfis_unicos": 0,
    "qualificados": 0,
    "salvos": 0,
    "duplicados": 0,
    "rejeitados": 0,
    "sem_resultado": 0,
    "erros": 0,
}


# ============================================================
# MEMÓRIA DA EXECUÇÃO
# ============================================================

evidencias_perfis = {}

salvos_execucao = set()

cache_municipios = {}


# ============================================================
# DATA / HORA
# ============================================================

def agora_iso():
    return datetime.now(
        timezone.utc
    ).isoformat()


# ============================================================
# NORMALIZAÇÃO
# ============================================================

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
# PESQUISA WEB
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
                f"⚠️ Erro de pesquisa "
                f"{tentativa}/"
                f"{MAX_TENTATIVAS_BUSCA}"
            )

            print(
                f"   {ultimo_erro}"
            )

            if (
                tentativa
                < MAX_TENTATIVAS_BUSCA
            ):

                espera = (
                    8 * tentativa
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
# IMPORTANTE:
# NÃO usamos mais município por município para pesquisar.
#
# O IBGE aqui serve APENAS para reconhecer a cidade
# dentro de um resultado encontrado no estado.
# ============================================================

def carregar_municipios(
    uf
):

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

            nome = item.get(
                "nome"
            )

            if nome:

                municipios.append(
                    nome
                )

        # Nomes maiores primeiro.
        # Isso reduz falsos encaixes.
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

        estatisticas[
            "erros"
        ] += 1

        return []


# ============================================================
# IDENTIFICAR CIDADE NO TEXTO
# ============================================================

def detectar_cidade(
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
            + re.escape(
                municipio_norm
            )
            + r"(?!\w)"
        )

        if re.search(
            padrao,
            texto_norm
        ):

            return municipio

    return None


# ============================================================
# CLASSIFICAÇÃO DE FONTE
# ============================================================

def classificar_fonte(
    url
):

    url_norm = (
        url or ""
    ).lower()

    dominio = ""

    try:

        dominio = (
            urlparse(
                url
            )
            .netloc
            .lower()
        )

    except Exception:
        pass

    if (
        "emec.mec.gov.br"
        in url_norm
        or "emec"
        in dominio
    ):

        return (
            "e_mec",
            True
        )

    if (
        "gov.br"
        in dominio
    ):

        return (
            "fonte_oficial",
            True
        )

    if (
        dominio.endswith(
            ".edu.br"
        )
        or ".edu.br"
        in dominio
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
# INSTITUIÇÃO - SINAIS
# ============================================================

PALAVRAS_INSTITUICAO = [
    "universidade",
    "faculdade",
    "centro universitario",
    "centro universitário",
    "instituto federal",
    "instituto de ensino",
    "university",
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
    "fatec",
    "unifesp",
    "usp",
    "unesp",
]


TERMOS_CURSO = [
    "curso de nutricao",
    "graduacao em nutricao",
    "bacharelado em nutricao",
    "nutricao bacharelado",
    "graduacao nutricao",
]


# ============================================================
# RESULTADO PARECE INSTITUIÇÃO COM NUTRIÇÃO?
# ============================================================

def resultado_parece_instituicao(
    texto
):

    texto_norm = normalizar_texto(
        texto
    )

    if (
        "nutricao"
        not in texto_norm
    ):
        return False

    sinais_ensino = [
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
        for sinal in sinais_ensino
    )


# ============================================================
# EXTRAIR NOME DA INSTITUIÇÃO
# ============================================================

def extrair_nome_instituicao(
    titulo
):

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

    # Primeiro procura uma parte que tenha
    # claramente nome de instituição.
    for parte in partes:

        parte_norm = (
            normalizar_texto(
                parte
            )
        )

        if any(
            normalizar_texto(
                palavra
            )
            in parte_norm
            for palavra
            in PALAVRAS_INSTITUICAO
        ):

            nome = (
                parte
                .strip()
                [:180]
            )

            if nome:
                return nome

    # Segunda tentativa:
    # elimina pedaços claramente de curso.
    partes_validas = []

    for parte in partes:

        parte_norm = normalizar_texto(
            parte
        )

        if (
            "nutricao"
            in parte_norm
            and len(partes) > 1
        ):
            continue

        if (
            "vestibular"
            in parte_norm
        ):
            continue

        if (
            "graduacao"
            in parte_norm
        ):
            continue

        if len(
            parte.strip()
        ) >= 4:

            partes_validas.append(
                parte.strip()
            )

    if partes_validas:

        return (
            partes_validas[-1]
            [:180]
        )

    return None


# ============================================================
# COMPARAÇÃO DE NOMES
# ============================================================

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

        menor = min(
            len(n1),
            len(n2)
        )

        if menor >= 6:
            return True

    return False


# ============================================================
# VERIFICAR INSTITUIÇÃO EXISTENTE
# ============================================================

def buscar_instituicao_existente(
    uf,
    cidade,
    instituicao
):

    try:

        resposta = (
            supabase
            .table(
                "instituicoes_nutricao"
            )
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

            if (
                nome_instituicao_equivalente(
                    registro.get(
                        "instituicao"
                    ),
                    instituicao
                )
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
# SALVAR INSTITUIÇÃO IMEDIATAMENTE
# ============================================================

def salvar_instituicao(
    uf,
    cidade,
    instituicao,
    origem,
    fonte_url,
    validada
):

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

        # Se já existia mas agora encontramos
        # uma fonte melhor, atualiza validação.
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
            origem
            if validada
            else None,

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
            .insert(
                dados
            )
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

        if validada:

            print(
                "      ✅ Fonte forte"
            )

        else:

            print(
                "      ⏳ Precisa validação"
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
# CHECKPOINT GENÉRICO
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
            .table(
                "controle_busca"
            )
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

        return True

    except Exception as erro:

        print(
            f"⚠️ Erro salvando "
            f"checkpoint: {erro}"
        )

        estatisticas[
            "erros"
        ] += 1

        return False


# ============================================================
# CONSULTAS DE DESCOBERTA POR ESTADO
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


# ============================================================
# DESCOBERTA DE INSTITUIÇÕES POR ESTADO
# ============================================================

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

    consultas = (
        montar_consultas_descoberta(
            uf,
            estado_nome
        )
    )

    total = len(
        consultas
    )

    checkpoint = (
        buscar_checkpoint(
            estado=uf,
            etapa="descoberta_instituicoes"
        )
    )

    inicio = 1

    if checkpoint:

        if (
            checkpoint.get(
                "status"
            )
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

        print(
            f"♻️ Retomando descoberta "
            f"de {uf} na pesquisa "
            f"{inicio}/{total}"
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

        consulta = (
            consultas[
                numero - 1
            ]
        )

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

        resultados, ok, erro = (
            pesquisar(
                ddgs,
                consulta,
                MAX_RESULTADOS_DESCOBERTA
            )
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

            print(
                "❌ Descoberta interrompida."
            )

            return False

        for resultado in resultados:

            titulo = (
                resultado.get(
                    "title"
                )
                or ""
            )

            corpo = (
                resultado.get(
                    "body"
                )
                or ""
            )

            url = (
                resultado.get(
                    "href"
                )
                or resultado.get(
                    "url"
                )
                or ""
            )

            texto = (
                f"{titulo} "
                f"{corpo} "
                f"{url}"
            )

            if not (
                resultado_parece_instituicao(
                    texto
                )
            ):
                continue

            cidade = detectar_cidade(
                texto,
                municipios
            )

            if not cidade:
                continue

            instituicao = (
                extrair_nome_instituicao(
                    titulo
                )
            )

            if not instituicao:
                continue

            origem, forte = (
                classificar_fonte(
                    url
                )
            )

            salvar_instituicao(
                uf=uf,
                cidade=cidade,
                instituicao=instituicao,
                origem=origem,
                fonte_url=url,
                validada=forte
            )

        # Próxima consulta
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
        f"✅ Descoberta de instituições "
        f"de {uf} concluída."
    )

    return True


# ============================================================
# PEGAR INSTITUIÇÕES PENDENTES
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
            .order(
                "cidade"
            )
            .limit(
                limite
            )
            .execute()
        )

        return (
            resposta.data
            or []
        )

    except Exception as erro:

        print(
            f"❌ Erro buscando "
            f"instituições pendentes: "
            f"{erro}"
        )

        estatisticas[
            "erros"
        ] += 1

        return []


# ============================================================
# ALTERAR STATUS DA INSTITUIÇÃO
# ============================================================

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
            .update(
                dados
            )
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
# VALIDAÇÃO DA INSTITUIÇÃO
# ============================================================

def validar_instituicao(
    ddgs,
    instituicao
):

    if instituicao.get(
        "validada"
    ):

        return True

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
        f"   🔎 Validando instituição:"
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

        resultados, ok, erro = (
            pesquisar(
                ddgs,
                consulta,
                15
            )
        )

        if not ok:
            continue

        for resultado in resultados:

            titulo = (
                resultado.get(
                    "title"
                )
                or ""
            )

            corpo = (
                resultado.get(
                    "body"
                )
                or ""
            )

            url = (
                resultado.get(
                    "href"
                )
                or resultado.get(
                    "url"
                )
                or ""
            )

            texto = normalizar_texto(
                f"{titulo} "
                f"{corpo} "
                f"{url}"
            )

            if (
                "nutricao"
                not in texto
            ):
                continue

            origem, forte = (
                classificar_fonte(
                    url
                )
            )

            nome_norm = (
                normalizar_texto(
                    nome
                )
            )

            cidade_norm = (
                normalizar_texto(
                    cidade
                )
            )

            confirma_nome = (
                nome_norm in texto
                or any(
                    palavra in texto
                    for palavra in
                    nome_norm.split()
                    if len(palavra) >= 5
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

    print(
        "      ⚠️ Não foi possível "
        "validar com segurança."
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

    return False


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

        if (
            "instagram.com"
            not in dominio
        ):
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

        return (
            normalizar_instagram(
                usuario
            )
        )

    except Exception:

        return None


# ============================================================
# EXCLUSÕES
# ============================================================

TERMOS_EXCLUSAO = [
    "psicologia",
    "psicologa",
    "psicologo",
    "maquiagem",
    "maquiadora",
    "makeup",
    "meme",
    "memes",
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


TERMOS_CONTA_INSTITUCIONAL = [
    "universidade",
    "faculdade",
    "centro universitario",
    "vestibular",
    "colegio",
    "instituto",
    "turma de nutricao",
    "atletica",
    "diretorio academico",
    "centro academico",
]


def e_excluido(
    texto
):

    texto_norm = (
        normalizar_texto(
            texto
        )
    )

    if any(
        termo in texto_norm
        for termo
        in TERMOS_EXCLUSAO
    ):
        return True

    return False


# ============================================================
# É CONTA PESSOAL?
# ============================================================

def parece_conta_pessoal(
    texto,
    instagram
):

    texto_norm = normalizar_texto(
        texto
    )

    instagram_norm = (
        normalizar_texto(
            instagram
        )
    )

    institucional = any(
        termo in texto_norm
        for termo
        in TERMOS_CONTA_INSTITUCIONAL
    )

    if institucional:

        sinais_pessoa = [
            "nutricionista",
            "graduanda",
            "graduando",
            "formanda",
            "formando",
            "crn",
            "atendimento",
            "consultas",
        ]

        if not any(
            sinal in texto_norm
            for sinal
            in sinais_pessoa
        ):

            return False

    # Handles que parecem puramente institucionais.
    handles_ruins = [
        "faculdade",
        "universidade",
        "vestibular",
        "colegio",
        "atletica",
    ]

    if any(
        termo in instagram_norm
        for termo
        in handles_ruins
    ):
        return False

    return True


# ============================================================
# PROVA DE NUTRIÇÃO
# ============================================================

def e_nutricao(
    texto,
    instagram
):

    texto_norm = (
        normalizar_texto(
            texto
        )
    )

    instagram_norm = (
        normalizar_texto(
            instagram
        )
    )

    fortes = [
        "nutricionista",
        "estudante de nutricao",
        "academica de nutricao",
        "academico de nutricao",
        "graduanda em nutricao",
        "graduando em nutricao",
        "bacharel em nutricao",
        "crn",
    ]

    if any(
        sinal in texto_norm
        for sinal
        in fortes
    ):

        return True

    if (
        "nutricao"
        in texto_norm
    ):

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
            "crn",
        ]

        if any(
            termo in texto_norm
            for termo
            in contexto_pessoal
        ):
            return True

    padroes_handle = [
        ".nutri",
        "nutri.",
        "_nutri",
        "nutri_",
        "nutricionista",
    ]

    if any(
        padrao in instagram_norm
        for padrao
        in padroes_handle
    ):

        contexto = [
            "formanda",
            "formando",
            "graduanda",
            "graduando",
            "crn",
            "atendimento",
            "consulta",
            "nutricao",
        ]

        if any(
            termo in texto_norm
            for termo
            in contexto
        ):

            return True

    return False


# ============================================================
# COORTE 2025 / 2026 / FINAL DO CURSO
# ============================================================

def e_coorte_alvo(
    texto
):

    texto_norm = (
        normalizar_texto(
            texto
        )
    )

    tem_2025 = (
        "2025"
        in texto_norm
    )

    tem_2026 = (
        "2026"
        in texto_norm
    )

    conclusao = [
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

    final_curso = [
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
        in conclusao
    )

    tem_final = any(
        termo in texto_norm
        for termo
        in final_curso
    )

    formado_recente = (
        tem_conclusao
        and (
            tem_2025
            or tem_2026
        )
    )

    estudante_final = (
        tem_final
    )

    return (
        formado_recente
        or estudante_final
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

    texto_norm = (
        normalizar_texto(
            texto
        )
    )

    instagram_norm = (
        normalizar_texto(
            instagram
        )
    )

    pontos = 0

    if (
        "nutricionista"
        in texto_norm
    ):
        pontos += 4

    if (
        "nutricao"
        in texto_norm
    ):
        pontos += 3

    if (
        "crn"
        in texto_norm
    ):
        pontos += 3

    if (
        "nutri"
        in instagram_norm
    ):
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

    if (
        "2026"
        in texto_norm
    ):
        pontos += 4

    if (
        "2025"
        in texto_norm
    ):
        pontos += 3

    cidade_norm = (
        normalizar_texto(
            cidade
        )
    )

    if (
        cidade_norm
        and cidade_norm
        in texto_norm
    ):
        pontos += 2

    instituicao_norm = (
        normalizar_texto(
            instituicao
        )
    )

    if (
        instituicao_norm
        and instituicao_norm
        in texto_norm
    ):
        pontos += 2

    comerciais = [
        "agenda aberta",
        "atendimentos",
        "consultas",
        "atendimento online",
        "atendimento presencial",
    ]

    if any(
        termo in texto_norm
        for termo
        in comerciais
    ):
        pontos += 1

    return pontos


# ============================================================
# EVIDÊNCIA
# ============================================================

def montar_evidencia(
    texto
):

    texto_norm = (
        normalizar_texto(
            texto
        )
    )

    itens = []

    verificacoes = [
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
            "tcc",
            "TCC"
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
            "formatura",
            "formatura"
        ),
        (
            "colacao",
            "colação"
        ),
    ]

    for termo, descricao in verificacoes:

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
# DUPLICIDADE DO LEAD
# ============================================================

def verificar_lead_existente(
    instagram
):

    for tentativa in range(
        1,
        4
    ):

        try:

            resposta = (
                supabase
                .table(
                    "leds"
                )
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
                f"{instagram} "
                f"({tentativa}/3): "
                f"{erro}"
            )

            if tentativa < 3:

                time.sleep(
                    3 * tentativa
                )

    # None:
    # Não arrisca inserir duplicado.
    return None


# ============================================================
# NOME DO CANDIDATO
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
        .replace(
            "@",
            ""
        )
        [:150]
    )


# ============================================================
# SALVAR LEAD
# ============================================================

def salvar_lead(
    lead
):

    instagram = (
        lead[
            "instagram"
        ]
    )

    if (
        instagram
        in salvos_execucao
    ):
        return False

    existente = (
        verificar_lead_existente(
            instagram
        )
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
            "         Não consegui "
            "confirmar duplicidade."
        )

        return False

    try:

        (
            supabase
            .table(
                "leds"
            )
            .insert(
                lead
            )
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
            f"      ❌ ERRO AO SALVAR "
            f"{instagram}: {erro}"
        )

        estatisticas[
            "erros"
        ] += 1

        return False


# ============================================================
# PROCESSAR RESULTADO DE LEAD
# ============================================================

def processar_resultado_lead(
    resultado,
    instituicao
):

    titulo = (
        resultado.get(
            "title"
        )
        or ""
    )

    corpo = (
        resultado.get(
            "body"
        )
        or ""
    )

    url = (
        resultado.get(
            "href"
        )
        or resultado.get(
            "url"
        )
        or ""
    )

    instagram = (
        extrair_instagram(
            url
        )
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

    # -----------------------------------------
    # Acumula evidências do mesmo perfil
    # -----------------------------------------

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

    # -----------------------------------------
    # Exclusões
    # -----------------------------------------

    if e_excluido(
        texto_completo
    ):

        print(
            f"      ❌ Fora do nicho: "
            f"{instagram}"
        )

        estatisticas[
            "rejeitados"
        ] += 1

        return False

    if not parece_conta_pessoal(
        texto_completo,
        instagram
    ):

        print(
            f"      ❌ Conta institucional: "
            f"{instagram}"
        )

        estatisticas[
            "rejeitados"
        ] += 1

        return False

    # -----------------------------------------
    # Nutrição obrigatória
    # -----------------------------------------

    if not e_nutricao(
        texto_completo,
        instagram
    ):

        print(
            f"      ⏳ Sem prova suficiente "
            f"de Nutrição: {instagram}"
        )

        return False

    # -----------------------------------------
    # Coorte obrigatória
    # -----------------------------------------

    if not e_coorte_alvo(
        texto_completo
    ):

        print(
            f"      ⏳ Nutrição encontrada, "
            f"mas sem prova de "
            f"2025/2026 ou final de curso: "
            f"{instagram}"
        )

        return False

    # -----------------------------------------
    # Pontuação
    # -----------------------------------------

    pontos = (
        calcular_pontuacao(
            texto_completo,
            instagram,
            instituicao[
                "cidade"
            ],
            instituicao[
                "instituicao"
            ]
        )
    )

    if (
        pontos
        < PONTUACAO_MINIMA
    ):

        print(
            f"      ⏳ Evidência fraca: "
            f"{instagram} | "
            f"{pontos} pontos"
        )

        return False

    # -----------------------------------------
    # QUALIFICADO
    # -----------------------------------------

    evidencia = (
        montar_evidencia(
            texto_completo
        )
    )

    estatisticas[
        "qualificados"
    ] += 1

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
            instituicao[
                "cidade"
            ],

        "estado":
            instituicao[
                "estado"
            ],

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
                instagram
            ]["url"],
    }

    return salvar_lead(
        lead
    )


# ============================================================
# CONSULTAS DE LEADS POR FACULDADE
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
        "-kumon"
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
            f'"2026" '
            f'"formatura" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{nome}" '
            f'"Nutrição" '
            f'"2025" '
            f'"formatura" '
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

        # Busca complementar da cidade

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

        (
            f'site:instagram.com '
            f'"{cidade}" '
            f'"Nutrição" '
            f'"formanda" '
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
        f"🏫 FACULDADE"
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

    # -----------------------------------------
    # Validação
    # -----------------------------------------

    if not validar_instituicao(
        ddgs,
        instituicao
    ):

        print(
            "⚠️ Faculdade enviada "
            "para revisão."
        )

        return False

    atualizar_instituicao(
        instituicao[
            "id"
        ],
        {
            "status":
                "processando"
        }
    )

    consultas = (
        montar_consultas_leads(
            instituicao
        )
    )

    total = len(
        consultas
    )

    checkpoint = (
        buscar_checkpoint(
            estado=uf,
            cidade=cidade,
            instituicao=nome,
            etapa="busca_leads"
        )
    )

    inicio = 1

    if checkpoint:

        if (
            checkpoint.get(
                "status"
            )
            == "concluido"
        ):

            atualizar_instituicao(
                instituicao[
                    "id"
                ],
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

    salvos_antes = (
        estatisticas[
            "salvos"
        ]
    )

    encontrados_local = 0

    for numero in range(
        inicio,
        total + 1
    ):

        consulta = (
            consultas[
                numero - 1
            ]
        )

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

        resultados, ok, erro = (
            pesquisar(
                ddgs,
                consulta,
                MAX_RESULTADOS_LEADS
            )
        )

        if not ok:

            print(
                "   ❌ Pesquisa falhou."
            )

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
                instituicao[
                    "id"
                ],
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

        # -------------------------------------
        # CHECKPOINT APÓS CONCLUIR ESTA BUSCA
        #
        # Guarda a PRÓXIMA busca.
        # -------------------------------------

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

    # -----------------------------------------
    # CONCLUÍDA
    # -----------------------------------------

    salvos_local = (
        estatisticas[
            "salvos"
        ]
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
        instituicao[
            "id"
        ],
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
# RECUPERAR FACULDADES INTERROMPIDAS
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
                    registro[
                        "id"
                    ]
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
# VERIFICAR SE A DESCOBERTA DO ESTADO TERMINOU
# ============================================================

def estado_descoberta_concluida(
    uf
):

    checkpoint = (
        buscar_checkpoint(
            estado=uf,
            etapa="descoberta_instituicoes"
        )
    )

    if not checkpoint:
        return False

    return (
        checkpoint.get(
            "status"
        )
        == "concluido"
    )


# ============================================================
# EXISTEM FACULDADES PENDENTES?
# ============================================================

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
# EXECUÇÃO PRINCIPAL
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

            # =============================================
            # 1. DESCOBERTA DAS FACULDADES DO ESTADO
            # =============================================

            if not estado_descoberta_concluida(
                uf
            ):

                sucesso = (
                    descobrir_instituicoes_estado(
                        ddgs,
                        uf,
                        estado_nome
                    )
                )

                if not sucesso:

                    print(
                        f"⚠️ A descoberta de "
                        f"{uf} não terminou."
                    )

                    print(
                        "A próxima execução "
                        "retoma deste ponto."
                    )

                    break

            # =============================================
            # 2. FILA DE FACULDADES
            # =============================================

            restante = (
                MAX_FACULDADES_POR_EXECUCAO
                - faculdades_tentadas
            )

            pendentes = (
                buscar_instituicoes_pendentes(
                    uf,
                    restante
                )
            )

            # =============================================
            # 3. PROCESSA UMA A UMA
            # =============================================

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

            # =============================================
            # 4. SE AINDA HÁ FACULDADES EM SP, NÃO PASSA
            # PARA MG AINDA.
            # =============================================

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
                    "continuaremos neste estado."
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
    "Nova arquitetura:"
)

print(
    "Estado > Faculdade > Cidade > Lead"
)

print(
    "Não pesquisa mais cidade por cidade."
)

print(
    "Cada instituição é salva imediatamente."
)

print(
    "Cada lead qualificado é salvo imediatamente."
)

print(
    "Cada pesquisa possui checkpoint."
)

print(
    "================================================="
)


# ============================================================
# EXECUTAR
# ============================================================

executar()


# ============================================================
# RESUMO FINAL
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
    f"Instituições processadas: "
    f"{estatisticas['instituicoes_processadas']}"
)

print(
    f"Resultados de leads analisados: "
    f"{estatisticas['resultados_analisados']}"
)

print(
    f"Perfis únicos: "
    f"{estatisticas['perfis_unicos']}"
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
    f"Rejeitados: "
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
