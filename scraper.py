import os
import re
import io
import csv
import time
import random
import zipfile
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from ddgs import DDGS
from supabase import create_client


# ============================================================
# MÁQUINA NACIONAL DE LEADS - NUTRIÇÃO
#
# BASE OFICIAL:
# INEP - CENSO DA EDUCAÇÃO SUPERIOR 2024
#
# FLUXO:
#
# INEP/e-MEC
#     ↓
# Curso de Nutrição
#     ↓
# Instituição + Cidade + Estado
#     ↓
# Supabase
#     ↓
# Até 5 faculdades por execução
#     ↓
# Busca de pessoas/formandos
#     ↓
# Filtro rígido
#     ↓
# Salva lead imediatamente
#     ↓
# Checkpoint
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
# FONTE OFICIAL INEP
# ============================================================

INEP_ZIP_URL = (
    "https://download.inep.gov.br/"
    "microdados/"
    "microdados_censo_da_educacao_superior_2024.zip"
)

INEP_FONTE_URL = (
    "https://www.gov.br/inep/pt-br/"
    "acesso-a-informacao/dados-abertos/"
    "microdados/censo-da-educacao-superior"
)

ANO_BASE_INEP = "2024"


# ============================================================
# ORDEM DOS ESTADOS
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

MAX_FACULDADES_POR_EXECUCAO = 5

MAX_RESULTADOS_LEADS = 20

MAX_TENTATIVAS_BUSCA = 3
MAX_TENTATIVAS_SUPABASE = 3

PAUSA_MIN = 5.0
PAUSA_MAX = 8.0

PONTUACAO_MINIMA = 9


# ============================================================
# ESTATÍSTICAS
# ============================================================

estatisticas = {
    "base_oficial_importada": 0,
    "instituicoes_importadas": 0,
    "estados_visitados": 0,
    "faculdades_processadas": 0,
    "pesquisas_realizadas": 0,
    "resultados_analisados": 0,
    "perfis_unicos": 0,
    "contas_institucionais": 0,
    "fora_nicho": 0,
    "qualificados": 0,
    "salvos": 0,
    "duplicados": 0,
    "sem_resultado": 0,
    "erros": 0,
}


# ============================================================
# MEMÓRIA TEMPORÁRIA DA EXECUÇÃO
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


def normalizar_codigo(valor):

    if valor is None:
        return ""

    valor = str(valor).strip()

    if valor.endswith(".0"):
        valor = valor[:-2]

    return valor


def normalizar_instagram(usuario):

    if not usuario:
        return None

    usuario = (
        usuario
        .strip()
        .lower()
        .lstrip("@")
    )

    return "@" + usuario


def pausa():

    time.sleep(
        random.uniform(
            PAUSA_MIN,
            PAUSA_MAX
        )
    )


# ============================================================
# VERIFICAR SE BASE OFICIAL JÁ ESTÁ NO SUPABASE
# ============================================================

def base_oficial_ja_carregada():

    try:

        resposta = (
            supabase
            .table("instituicoes_nutricao")
            .select("id")
            .eq(
                "origem",
                "INEP_CENSO_SUPERIOR_2024"
            )
            .limit(1)
            .execute()
        )

        return bool(
            resposta.data
        )

    except Exception as erro:

        print(
            f"❌ Erro verificando base oficial: "
            f"{erro}"
        )

        estatisticas["erros"] += 1

        return False


# ============================================================
# DOWNLOAD OFICIAL DO INEP
#
# SOMENTE NA PRIMEIRA CARGA.
# Depois as instituições ficam no Supabase.
# ============================================================

def baixar_microdados_inep():

    print("")
    print(
        "================================================="
    )
    print(
        "📥 BAIXANDO BASE OFICIAL DO INEP"
    )
    print(
        "Censo da Educação Superior 2024"
    )
    print(
        "================================================="
    )

    for tentativa in range(1, 4):

        try:

            resposta = requests.get(
                INEP_ZIP_URL,
                stream=True,
                timeout=(30, 300)
            )

            resposta.raise_for_status()

            conteudo = io.BytesIO()

            total_bytes = 0

            for bloco in resposta.iter_content(
                chunk_size=1024 * 1024
            ):

                if not bloco:
                    continue

                conteudo.write(bloco)

                total_bytes += len(bloco)

                # Mostra progresso aproximadamente
                # a cada 50 MB.
                if (
                    total_bytes
                    % (50 * 1024 * 1024)
                    < len(bloco)
                ):

                    mb = (
                        total_bytes
                        / 1024
                        / 1024
                    )

                    print(
                        f"   Baixados aproximadamente "
                        f"{mb:.0f} MB..."
                    )

            conteudo.seek(0)

            # Confere se realmente é ZIP.
            if not zipfile.is_zipfile(
                conteudo
            ):

                raise RuntimeError(
                    "O arquivo recebido do INEP "
                    "não é um ZIP válido."
                )

            print(
                "✅ Download oficial concluído."
            )

            return conteudo

        except Exception as erro:

            print(
                f"⚠️ Falha no download "
                f"{tentativa}/3: {erro}"
            )

            if tentativa < 3:

                espera = 20 * tentativa

                print(
                    f"   Nova tentativa em "
                    f"{espera}s..."
                )

                time.sleep(espera)

    estatisticas["erros"] += 1

    return None


# ============================================================
# LOCALIZAR ARQUIVOS DENTRO DO ZIP
# ============================================================

def localizar_arquivo_zip(
    zip_ref,
    trecho_nome
):

    trecho_norm = (
        trecho_nome
        .upper()
    )

    for nome in zip_ref.namelist():

        if (
            trecho_norm
            in nome.upper()
        ):

            return nome

    return None


# ============================================================
# LER MAPA DE INSTITUIÇÕES OFICIAIS
# ============================================================

def carregar_mapa_ies(
    zip_ref,
    arquivo_ies
):

    print(
        "📚 Lendo cadastro oficial de IES..."
    )

    mapa = {}

    with zip_ref.open(
        arquivo_ies
    ) as arquivo_binario:

        texto = io.TextIOWrapper(
            arquivo_binario,
            encoding="cp1252",
            errors="replace",
            newline=""
        )

        leitor = csv.DictReader(
            texto,
            delimiter=";"
        )

        for linha in leitor:

            codigo = normalizar_codigo(
                linha.get("CO_IES")
            )

            nome = (
                linha.get("NO_IES")
                or ""
            ).strip()

            sigla = (
                linha.get("SG_IES")
                or ""
            ).strip()

            if not codigo or not nome:
                continue

            mapa[codigo] = {
                "nome": nome,
                "sigla": sigla,
            }

    print(
        f"✅ {len(mapa)} instituições "
        f"identificadas no cadastro."
    )

    return mapa


# ============================================================
# CURSO É NUTRIÇÃO?
# ============================================================

def curso_e_nutricao(
    linha
):

    nome_curso = normalizar_texto(
        linha.get("NO_CURSO")
    )

    cine = normalizar_texto(
        linha.get("NO_CINE_ROTULO")
    )

    # Curso diretamente chamado Nutrição.
    if nome_curso == "nutricao":
        return True

    # Proteção para pequenas variações cadastrais.
    if (
        "nutricao" in nome_curso
        and len(nome_curso) <= 40
    ):
        return True

    # Segunda confirmação pela classificação CINE.
    if (
        "nutricao" in cine
        and "nutricao" in nome_curso
    ):
        return True

    return False


# ============================================================
# FORMATAR NOME OFICIAL DA IES
# ============================================================

def formatar_nome_ies(
    nome,
    sigla
):

    nome = (
        nome or ""
    ).strip()

    sigla = (
        sigla or ""
    ).strip()

    if not sigla:
        return nome

    if (
        normalizar_texto(sigla)
        in normalizar_texto(nome)
    ):
        return nome

    return (
        f"{nome} ({sigla})"
    )


# ============================================================
# EXTRAIR FACULDADES DE NUTRIÇÃO DA BASE OFICIAL
# ============================================================

def extrair_instituicoes_nutricao(
    zip_ref,
    arquivo_cursos,
    mapa_ies
):

    print("")
    print(
        "🥗 Filtrando somente cursos "
        "de Nutrição..."
    )

    instituicoes = {}

    total_linhas = 0
    total_nutricao = 0

    with zip_ref.open(
        arquivo_cursos
    ) as arquivo_binario:

        texto = io.TextIOWrapper(
            arquivo_binario,
            encoding="cp1252",
            errors="replace",
            newline=""
        )

        leitor = csv.DictReader(
            texto,
            delimiter=";"
        )

        for linha in leitor:

            total_linhas += 1

            if not curso_e_nutricao(
                linha
            ):
                continue

            # Nesta primeira etapa nacional,
            # usamos ofertas presenciais.
            # Isso mantém município/campus preciso.
            modalidade = normalizar_codigo(
                linha.get(
                    "TP_MODALIDADE_ENSINO"
                )
            )

            if modalidade not in (
                "",
                "1"
            ):
                continue

            uf = (
                linha.get("SG_UF")
                or ""
            ).strip().upper()

            cidade = (
                linha.get("NO_MUNICIPIO")
                or ""
            ).strip()

            codigo_ies = normalizar_codigo(
                linha.get("CO_IES")
            )

            if (
                not uf
                or not cidade
                or cidade == "."
                or not codigo_ies
            ):
                continue

            dados_ies = mapa_ies.get(
                codigo_ies
            )

            if not dados_ies:
                continue

            nome_ies = formatar_nome_ies(
                dados_ies["nome"],
                dados_ies["sigla"]
            )

            if not nome_ies:
                continue

            total_nutricao += 1

            chave = (
                uf,
                normalizar_texto(
                    cidade
                ),
                normalizar_texto(
                    nome_ies
                ),
            )

            instituicoes[chave] = {
                "estado": uf,
                "cidade": cidade,
                "instituicao": nome_ies,
                "curso": "Nutrição",
                "origem":
                    "INEP_CENSO_SUPERIOR_2024",
                "fonte_url":
                    INEP_FONTE_URL,
                "status":
                    "pendente",
                "ultima_verificacao":
                    agora_iso(),
                "fonte_validacao":
                    "INEP/e-MEC",
                "validada":
                    True,
                "tentativa_descoberta":
                    0,
            }

            if (
                total_linhas
                % 100000
                == 0
            ):

                print(
                    f"   {total_linhas:,} "
                    f"registros analisados..."
                )

    print("")
    print(
        f"✅ Ofertas de Nutrição analisadas: "
        f"{total_nutricao}"
    )

    print(
        f"✅ Instituições/cidades únicas: "
        f"{len(instituicoes)}"
    )

    return list(
        instituicoes.values()
    )


# ============================================================
# SALVAR BASE OFICIAL EM LOTES
# ============================================================

def salvar_base_oficial(
    registros
):

    print("")
    print(
        "💾 Salvando instituições oficiais "
        "no Supabase..."
    )

    tamanho_lote = 100

    total_salvo = 0

    for inicio in range(
        0,
        len(registros),
        tamanho_lote
    ):

        lote = registros[
            inicio:
            inicio + tamanho_lote
        ]

        sucesso = False

        for tentativa in range(
            1,
            MAX_TENTATIVAS_SUPABASE + 1
        ):

            try:

                (
                    supabase
                    .table(
                        "instituicoes_nutricao"
                    )
                    .upsert(
                        lote,
                        on_conflict=(
                            "estado,"
                            "cidade,"
                            "instituicao"
                        )
                    )
                    .execute()
                )

                total_salvo += len(
                    lote
                )

                sucesso = True

                print(
                    f"   ✅ {total_salvo}/"
                    f"{len(registros)} "
                    f"registros gravados"
                )

                break

            except Exception as erro:

                print(
                    f"⚠️ Erro salvando lote "
                    f"{tentativa}/"
                    f"{MAX_TENTATIVAS_SUPABASE}: "
                    f"{erro}"
                )

                if (
                    tentativa
                    < MAX_TENTATIVAS_SUPABASE
                ):

                    time.sleep(
                        5 * tentativa
                    )

        if not sucesso:

            estatisticas[
                "erros"
            ] += 1

            return False

    estatisticas[
        "instituicoes_importadas"
    ] = total_salvo

    return True


# ============================================================
# PREPARAR BASE OFICIAL
# ============================================================

def preparar_base_oficial():

    if base_oficial_ja_carregada():

        print(
            "✅ Base oficial do INEP "
            "já está no Supabase."
        )

        print(
            "   Não será baixada novamente."
        )

        return True

    arquivo_zip_memoria = (
        baixar_microdados_inep()
    )

    if not arquivo_zip_memoria:
        return False

    try:

        with zipfile.ZipFile(
            arquivo_zip_memoria
        ) as zip_ref:

            arquivo_ies = (
                localizar_arquivo_zip(
                    zip_ref,
                    "MICRODADOS_ED_SUP_IES_2024.CSV"
                )
            )

            if not arquivo_ies:

                arquivo_ies = (
                    localizar_arquivo_zip(
                        zip_ref,
                        "CADASTRO_IES_2024.CSV"
                    )
                )

            arquivo_cursos = (
                localizar_arquivo_zip(
                    zip_ref,
                    "MICRODADOS_CADASTRO_CURSOS_2024.CSV"
                )
            )

            if not arquivo_ies:

                raise RuntimeError(
                    "Arquivo oficial de IES "
                    "não encontrado no pacote."
                )

            if not arquivo_cursos:

                raise RuntimeError(
                    "Arquivo oficial de cursos "
                    "não encontrado no pacote."
                )

            mapa_ies = carregar_mapa_ies(
                zip_ref,
                arquivo_ies
            )

            registros = (
                extrair_instituicoes_nutricao(
                    zip_ref,
                    arquivo_cursos,
                    mapa_ies
                )
            )

            if not registros:

                raise RuntimeError(
                    "Nenhuma instituição de "
                    "Nutrição foi encontrada."
                )

            if not salvar_base_oficial(
                registros
            ):

                return False

            estatisticas[
                "base_oficial_importada"
            ] = 1

            print("")
            print(
                "================================================="
            )

            print(
                "✅ BASE OFICIAL CARREGADA"
            )

            print(
                "A partir das próximas execuções "
                "o download não será repetido."
            )

            print(
                "================================================="
            )

            return True

    except Exception as erro:

        print(
            f"❌ Erro preparando base "
            f"oficial: {erro}"
        )

        estatisticas["erros"] += 1

        return False


# ============================================================
# BUSCAR FACULDADES PENDENTES
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
            f"❌ Erro carregando fila: "
            f"{erro}"
        )

        estatisticas["erros"] += 1

        return []


def existem_pendentes_estado(
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
            .eq(
                "validada",
                True
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
# ATUALIZAR FACULDADE
# ============================================================

def atualizar_faculdade(
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
# CHECKPOINT
# ============================================================

def buscar_checkpoint(
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
            f"⚠️ Erro lendo checkpoint: "
            f"{erro}"
        )

        return None


def salvar_checkpoint(
    instituicao,
    status,
    indice_pesquisa,
    total_pesquisas,
    consulta_atual=None,
    leads_encontrados=0,
    leads_salvos=0,
    ultimo_erro=None
):

    atual = buscar_checkpoint(
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
            indice_pesquisa,

        "total_pesquisas":
            total_pesquisas,

        "consulta_atual":
            consulta_atual,

        "fonte_atual":
            "instagram_web",

        "leads_encontrados":
            leads_encontrados,

        "leads_salvos":
            leads_salvos,

        "ultimo_erro":
            ultimo_erro,

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

    except Exception as erro:

        print(
            f"⚠️ Erro salvando "
            f"checkpoint: {erro}"
        )

        estatisticas["erros"] += 1

        return False


# ============================================================
# BUSCA WEB COM RETRY
# ============================================================

def pesquisar(
    ddgs,
    consulta
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
                f"⚠️ Falha na busca "
                f"{tentativa}/"
                f"{MAX_TENTATIVAS_BUSCA}"
            )

            print(
                f"   {ultimo_erro}"
            )

            if tentativa < MAX_TENTATIVAS_BUSCA:

                espera = (
                    15 * tentativa
                )

                print(
                    f"   Aguardando "
                    f"{espera}s..."
                )

                time.sleep(espera)

    estatisticas["erros"] += 1

    return (
        [],
        False,
        ultimo_erro
    )


# ============================================================
# NOME E SIGLA DA FACULDADE
# ============================================================

def separar_nome_sigla(
    instituicao
):

    instituicao = (
        instituicao
        or ""
    ).strip()

    match = re.search(
        r"\(([A-Za-z0-9.\-_]{2,20})\)\s*$",
        instituicao
    )

    if match:

        sigla = match.group(1)

        nome = re.sub(
            r"\s*\([A-Za-z0-9.\-_]{2,20}\)\s*$",
            "",
            instituicao
        ).strip()

        return (
            nome,
            sigla
        )

    return (
        instituicao,
        None
    )


# ============================================================
# CONSULTAS DOS LEADS
#
# SOMENTE 8.
# Reduz carga e mantém precisão.
# ============================================================

def montar_consultas(
    instituicao
):

    nome_completo = (
        instituicao["instituicao"]
    )

    cidade = (
        instituicao["cidade"]
    )

    nome, sigla = (
        separar_nome_sigla(
            nome_completo
        )
    )

    referencia = (
        sigla
        if sigla
        else nome
    )

    exclusoes = (
        "-psicologia "
        "-maquiagem "
        "-veterinária "
        "-odontologia "
        "-atletica "
        "-comissao "
        "-turma "
        "-evento"
    )

    return [

        (
            f'site:instagram.com '
            f'"{referencia}" '
            f'"Nutrição" '
            f'("formanda" OR "formando" '
            f'OR "concluinte") '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{referencia}" '
            f'"Nutrição" '
            f'("graduanda" OR "graduando") '
            f'"2026" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{referencia}" '
            f'"Nutrição" '
            f'("7/8" OR "8/8") '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{referencia}" '
            f'"Nutrição" '
            f'("último período" '
            f'OR "último semestre") '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{referencia}" '
            f'"Nutrição" '
            f'"TCC" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{referencia}" '
            f'"Nutrição" '
            f'"formatura" '
            f'"2026" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{referencia}" '
            f'"Nutrição" '
            f'"formatura" '
            f'"2025" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{cidade}" '
            f'"{referencia}" '
            f'"nutricionista" '
            f'("2025" OR "2026") '
            f'{exclusoes}'
        ),
    ]


# ============================================================
# EXTRAIR INSTAGRAM
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
# FILTROS
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
    "pet shop",
    "odontologia",
    "dentista",
    "fonoaudiologia",
    "fisioterapia",
    "fotografia",
    "fotografa",
    "fotografo",
    "engenharia",
    "arquitetura",
    "kumon",
]


TERMOS_INSTITUCIONAIS = [
    "turma de nutricao",
    "comissao de formatura",
    "centro academico",
    "diretorio academico",
    "atletica",
    "liga academica",
    "projeto de extensao",
    "evento academico",
    "semana academica",
    "universidade",
    "faculdade",
]


PADROES_HANDLE_INSTITUCIONAL = [
    r"^@?nutricao[._-]?uf",
    r"^@?nutricao[._-]?uni",
    r"^@?nutricao[._-]?fac",
    r"^@?nutricao[._-]?fai",
    r"^@?nutricao[._-]?ies",
    r"^@?nutricao[._-]?unes",
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

    if (
        instagram
        in HANDLES_BLOQUEADOS
    ):
        return True

    handle = normalizar_texto(
        instagram
    )

    for padrao in (
        PADROES_HANDLE_INSTITUCIONAL
    ):

        if re.search(
            padrao,
            handle
        ):
            return True

    texto_norm = normalizar_texto(
        texto
    )

    institucional = any(
        termo in texto_norm
        for termo
        in TERMOS_INSTITUCIONAIS
    )

    sinais_pessoa = [
        "sou nutricionista",
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
        "consultas",
    ]

    pessoa = any(
        sinal in texto_norm
        for sinal
        in sinais_pessoa
    )

    if (
        institucional
        and not pessoa
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

    sinais_fortes = [
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
        sinal in texto_norm
        for sinal
        in sinais_fortes
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

    anos = (
        "2025" in texto_norm
        or
        "2026" in texto_norm
    )

    conclusao = [
        "formatura",
        "formou",
        "formada",
        "formado",
        "colacao de grau",
        "colacao",
        "concluiu",
        "bacharel",
    ]

    etapa_final = [
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
        "7 periodo",
        "8 periodo",
        "7o periodo",
        "8o periodo",
        "tcc",
        "trabalho de conclusao",
    ]

    conclusao_ok = any(
        termo in texto_norm
        for termo
        in conclusao
    )

    final_ok = any(
        termo in texto_norm
        for termo
        in etapa_final
    )

    return (
        (
            anos
            and conclusao_ok
        )
        or final_ok
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

    if (
        cidade
        and cidade in texto_norm
    ):
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

    if not itens:

        return (
            "evidência pública encontrada"
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

            if (
                tentativa
                < MAX_TENTATIVAS_SUPABASE
            ):

                time.sleep(
                    4 * tentativa
                )

    return None


# ============================================================
# SALVAR LEAD IMEDIATAMENTE
# ============================================================

def salvar_lead(
    lead
):

    instagram = (
        lead["instagram"]
    )

    if (
        instagram
        in salvos_execucao
    ):
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

        print(
            f"      ⚠️ Não foi possível "
            f"confirmar duplicidade: "
            f"{instagram}"
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
                f"      ⚠️ Erro ao salvar "
                f"{instagram}: {erro}"
            )

            if tentativa < (
                MAX_TENTATIVAS_SUPABASE
            ):

                time.sleep(
                    4 * tentativa
                )

    estatisticas["erros"] += 1

    return False


# ============================================================
# PROCESSAR RESULTADO
# ============================================================

def processar_resultado(
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

    if instagram in (
        bloqueados_execucao
    ):
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

        print(
            f"      ❌ Fora do nicho: "
            f"{instagram}"
        )

        return False

    if conta_institucional(
        instagram,
        texto_novo
    ):

        bloqueados_execucao.add(
            instagram
        )

        estatisticas[
            "contas_institucionais"
        ] += 1

        print(
            f"      🏢 Institucional: "
            f"{instagram}"
        )

        return False

    # A evidência fica vinculada à
    # faculdade atual.
    chave = (
        instituicao["id"],
        instagram
    )

    if chave not in evidencias_perfis:

        evidencias_perfis[chave] = {
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

    if conta_institucional(
        instagram,
        texto_completo
    ):

        bloqueados_execucao.add(
            instagram
        )

        estatisticas[
            "contas_institucionais"
        ] += 1

        return False

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

    if not e_coorte_alvo(
        texto_completo
    ):

        print(
            f"      ⏳ Nutrição confirmada, "
            f"mas fora do filtro "
            f"2025/2026/final: "
            f"{instagram}"
        )

        return False

    pontos = calcular_pontuacao(
        texto_completo,
        instagram,
        instituicao
    )

    if pontos < PONTUACAO_MINIMA:

        print(
            f"      ⏳ Evidência fraca: "
            f"{instagram} | "
            f"{pontos}"
        )

        return False

    if instagram not in (
        qualificados_execucao
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
        f"         Evidência: "
        f"{evidencia}"
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
            "INEP_Instagram_web",

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
# PROCESSAR UMA FACULDADE
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
        "🏫 FACULDADE OFICIAL"
    )

    print(
        f"   {instituicao['instituicao']}"
    )

    print(
        f"📍 {instituicao['cidade']}/"
        f"{instituicao['estado']}"
    )

    print(
        "📚 Fonte: INEP/e-MEC"
    )

    print(
        "================================================="
    )

    atualizar_faculdade(
        instituicao["id"],
        "processando"
    )

    consultas = montar_consultas(
        instituicao
    )

    total = len(
        consultas
    )

    checkpoint = buscar_checkpoint(
        instituicao
    )

    inicio = 1

    if checkpoint:

        status = (
            checkpoint.get("status")
            or ""
        )

        indice = (
            checkpoint.get(
                "indice_pesquisa"
            )
            or 1
        )

        if (
            status in (
                "processando",
                "erro",
                "pendente"
            )
            and indice > 0
        ):

            inicio = min(
                indice,
                total
            )

            print(
                f"♻️ Retomando na "
                f"pesquisa "
                f"{inicio}/{total}"
            )

    salvos_antes = (
        estatisticas["salvos"]
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
            instituicao=
                instituicao,

            status=
                "processando",

            indice_pesquisa=
                numero,

            total_pesquisas=
                total,

            consulta_atual=
                consulta,

            leads_encontrados=
                encontrados_local,

            leads_salvos=
                estatisticas["salvos"]
                - salvos_antes
        )

        resultados, ok, erro = (
            pesquisar(
                ddgs,
                consulta
            )
        )

        if not ok:

            salvar_checkpoint(
                instituicao=
                    instituicao,

                status=
                    "erro",

                indice_pesquisa=
                    numero,

                total_pesquisas=
                    total,

                consulta_atual=
                    consulta,

                leads_encontrados=
                    encontrados_local,

                leads_salvos=
                    estatisticas["salvos"]
                    - salvos_antes,

                ultimo_erro=
                    erro
            )

            atualizar_faculdade(
                instituicao["id"],
                "pendente"
            )

            print(
                "   ⚠️ Faculdade ficou "
                "pendente para retomar."
            )

            return False

        for resultado in resultados:

            encontrados_local += 1

            processar_resultado(
                resultado,
                instituicao
            )

        # Pesquisa terminou.
        # Salva a próxima posição.
        salvar_checkpoint(
            instituicao=
                instituicao,

            status=
                "processando",

            indice_pesquisa=
                numero + 1,

            total_pesquisas=
                total,

            consulta_atual=
                consulta,

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
        instituicao=
            instituicao,

        status=
            "concluido",

        indice_pesquisa=
            total,

        total_pesquisas=
            total,

        consulta_atual=
            "concluido",

        leads_encontrados=
            encontrados_local,

        leads_salvos=
            salvos_local
    )

    atualizar_faculdade(
        instituicao["id"],
        "concluido"
    )

    estatisticas[
        "faculdades_processadas"
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
# RECUPERAR FACULDADE QUE TRAVOU
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

        if registros:

            print(
                f"♻️ {len(registros)} "
                f"faculdade(s) "
                f"interrompida(s) "
                f"retornaram à fila."
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

    # --------------------------------------------------------
    # 1. BASE OFICIAL
    # --------------------------------------------------------

    if not preparar_base_oficial():

        print("")
        print(
            "❌ Não foi possível preparar "
            "a base oficial."
        )

        print(
            "A execução foi encerrada "
            "sem pesquisar leads."
        )

        return

    # --------------------------------------------------------
    # 2. RECUPERA INTERRUPÇÕES
    # --------------------------------------------------------

    recuperar_interrompidas()

    processadas = 0

    # --------------------------------------------------------
    # 3. ESTADO POR ESTADO
    # --------------------------------------------------------

    with DDGS() as ddgs:

        for uf, estado_nome in ESTADOS:

            if (
                processadas
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

            restante = (
                MAX_FACULDADES_POR_EXECUCAO
                - processadas
            )

            faculdades = (
                buscar_faculdades_pendentes(
                    uf,
                    restante
                )
            )

            for faculdade in faculdades:

                if (
                    processadas
                    >= MAX_FACULDADES_POR_EXECUCAO
                ):
                    break

                processar_faculdade(
                    ddgs,
                    faculdade
                )

                processadas += 1

            if existem_pendentes_estado(
                uf
            ):

                print("")
                print(
                    f"⏸️ {uf} ainda possui "
                    f"faculdades pendentes."
                )

                print(
                    "A próxima execução "
                    "continuará neste estado."
                )

                break

            print("")
            print(
                f"✅ {uf} concluído."
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
    "Base de faculdades:"
)

print(
    "INEP / Censo da Educação Superior 2024"
)

print(
    "Dados cadastrais originados do e-MEC."
)

print(
    "================================================="
)

print(
    "Fluxo:"
)

print(
    "Base oficial > Estado > Faculdade "
    "> Pessoa > Lead"
)

print(
    "Máximo: 5 faculdades por execução."
)

print(
    "Lead aprovado é salvo imediatamente."
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
    f"Base oficial importada nesta execução: "
    f"{estatisticas['base_oficial_importada']}"
)

print(
    f"Instituições/cidades importadas: "
    f"{estatisticas['instituicoes_importadas']}"
)

print(
    f"Estados visitados: "
    f"{estatisticas['estados_visitados']}"
)

print(
    f"Faculdades processadas: "
    f"{estatisticas['faculdades_processadas']}"
)

print(
    f"Pesquisas realizadas: "
    f"{estatisticas['pesquisas_realizadas']}"
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
    f"Contas institucionais rejeitadas: "
    f"{estatisticas['contas_institucionais']}"
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
    f"Leads salvos no Supabase: "
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
    "================================================="
)

