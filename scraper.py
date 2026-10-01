import os
import re
import time
import random
import unicodedata
from datetime import datetime, timezone

from ddgs import DDGS
from supabase import create_client


print("🚀 MÁQUINA 1 - MOTOR DE CAPTAÇÃO", flush=True)


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

# PRIMEIRO TESTE REAL.
# Depois que validarmos a passagem SP -> RJ,
# mudaremos somente isto para False.
MODO_TESTE = True


NICHO = "nutricao"

ETAPA = "motor_nacional_nutricao_v1"

MAX_RESULTADOS = 12

PAUSA_MIN = 2
PAUSA_MAX = 4

# Neste teste ele pode processar todas as 4.
MAX_INSTITUICOES_POR_EXECUCAO = 10


# ============================================================
# ORDEM OFICIAL DA NOSSA FILA
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
# FILA DO TESTE
# ============================================================

FILA_TESTE = {

    "SP": [
        {
            "instituicao":
                "Universidade Presbiteriana Mackenzie",

            "cidade":
                "São Paulo",
        },

        {
            "instituicao":
                "Centro Universitário São Camilo",

            "cidade":
                "São Paulo",
        },

        {
            "instituicao":
                "Universidade Paulista",

            "cidade":
                "São Paulo",
        },
    ],

    "RJ": [
        {
            "instituicao":
                "Universidade Federal do Rio de Janeiro",

            "cidade":
                "Rio de Janeiro",
        },
    ],
}


# ============================================================
# ESTATÍSTICAS
# ============================================================

stats = {
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
        caractere
        for caractere in texto
        if not unicodedata.combining(caractere)
    )

    texto = re.sub(
        r"\s+",
        " ",
        texto
    )

    return texto.strip()


# ============================================================
# VERIFICAÇÃO DE NOME
# ============================================================

def nome_parece_pessoa(nome):

    if not nome:
        return False

    nome = re.sub(
        r"\s+",
        " ",
        nome
    ).strip()

    partes = nome.split()

    if len(partes) < 2:
        return False

    if len(partes) > 8:
        return False

    if len(nome) < 7:
        return False

    if len(nome) > 90:
        return False

    texto = normalizar(
        nome
    )

    proibidos = [
        "universidade",
        "faculdade",
        "centro universitario",
        "vestibular",
        "curso",
        "nutricao",
        "campus",
        "evento",
        "congresso",
        "encontro cientifico",
        "pos graduacao",
        "programa",
        "secretaria",
        "reitoria",
        "turma",
        "coordenacao",
        "inscricoes",
        "processo seletivo",
    ]

    for termo in proibidos:

        if termo in texto:
            return False

    # nome de pessoa normalmente não contém vários números
    numeros = re.findall(
        r"\d",
        nome
    )

    if len(numeros) >= 2:
        return False

    return True


# ============================================================
# IDENTIFICAR ANO
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


# ============================================================
# IDENTIFICAR FASE
# ============================================================

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
            "estágio obrigatório",
            [
                "estagio obrigatorio",
                "estagio supervisionado",
                "estagio curricular",
            ]
        ),

        (
            "formanda/o",
            [
                "formanda",
                "formando",
                "formandos",
                "formandas",
            ]
        ),

        (
            "formada/o",
            [
                "formatura",
                "colacao de grau",
                "colacao",
                "graduada",
                "graduado",
                "recem-formada",
                "recem-formado",
            ]
        ),
    ]

    for periodo, termos in sinais:

        for termo in termos:

            if termo in t:
                return periodo

    return None


# ============================================================
# RESULTADO É DO NOSSO PÚBLICO?
# ============================================================

def resultado_valido(
    texto,
    instituicao
):

    t = normalizar(
        texto
    )

    instituicao_n = normalizar(
        instituicao
    )

    # precisa estar na área
    if (
        "nutricao"
        not in t
        and
        "nutricionista"
        not in t
    ):
        return False

    # instituição precisa aparecer de alguma forma.
    # também usamos palavras significativas do nome.
    palavras_inst = [
        palavra
        for palavra
        in instituicao_n.split()
        if len(palavra) >= 5
    ]

    bate_instituicao = any(
        palavra in t
        for palavra in palavras_inst
    )

    if not bate_instituicao:
        return False

    ano = identificar_ano(
        texto
    )

    periodo = identificar_periodo(
        texto
    )

    # nosso público atual
    if ano in [2025, 2026]:
        return True

    if periodo:
        return True

    return False


# ============================================================
# EXTRAIR NOME DE RESULTADO DE BUSCA
# ============================================================

def extrair_nome_resultado(resultado):

    titulo = str(
        resultado.get(
            "title",
            ""
        )
    ).strip()

    if not titulo:
        return None

    # remove sufixos conhecidos
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

    titulo = re.sub(
        r"\s*[-–]\s*(Nutricionista|Nutrição|Graduanda|Graduando).*$",
        "",
        titulo,
        flags=re.I
    )

    titulo = re.sub(
        r"\s+",
        " ",
        titulo
    ).strip()

    if not nome_parece_pessoa(
        titulo
    ):
        return None

    return titulo


# ============================================================
# DUPLICIDADE DE LEAD
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
# SALVAR LEAD
# ============================================================

def salvar_lead(
    nome,
    instituicao,
    cidade,
    estado,
    ano,
    periodo,
    evidencia,
    fonte_url
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
            f"      ♻️ Já existe: {nome}",
            flush=True
        )

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
            "motor_nacional_web",

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
            "buscar_instagram",

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

        print(
            f"      ✅ NOVO LEAD: {nome}",
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

def instituicao_na_fila(
    estado,
    instituicao
):

    try:

        resposta = (
            supabase
            .table(
                "instituicoes_nutricao"
            )
            .select(
                "id,status"
            )
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

    except Exception as erro:

        print(
            f"⚠️ Erro consultando fila: {erro}",
            flush=True
        )

        stats["erros"] += 1

        return None


# ============================================================
# CRIAR FILA DE TESTE
# ============================================================

def preparar_fila_teste():

    print("")
    print(
        "🧪 Preparando fila do teste...",
        flush=True
    )

    for estado in ["SP", "RJ"]:

        itens = FILA_TESTE.get(
            estado,
            []
        )

        for item in itens:

            existente = instituicao_na_fila(
                estado,
                item["instituicao"]
            )

            if existente:
                continue

            dados = {

                "estado":
                    estado,

                "cidade":
                    item["cidade"],

                "instituicao":
                    item["instituicao"],

                "curso":
                    "Nutrição",

                "origem":
                    "teste_motor_nacional",

                "fonte_validacao":
                    "fila_teste",

                "validada":
                    True,

                "status":
                    "pendente",

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

                print(
                    f"   ➕ {estado} | "
                    f"{item['instituicao']}",
                    flush=True
                )

            except Exception as erro:

                print(
                    f"   ⚠️ Não foi possível inserir "
                    f"{item['instituicao']}: {erro}",
                    flush=True
                )


# ============================================================
# ORDEM DOS ESTADOS NO TESTE
# ============================================================

def estados_da_execucao():

    if MODO_TESTE:

        return [
            "SP",
            "RJ",
        ]

    return UFS_BRASIL


# ============================================================
# PEGAR INSTITUIÇÕES DO ESTADO
# ============================================================

def buscar_fila_estado(estado):

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
            f"❌ Erro lendo fila de {estado}: {erro}",
            flush=True
        )

        stats["erros"] += 1

        return []


# ============================================================
# ATUALIZAR INSTITUIÇÃO
# ============================================================

def atualizar_instituicao(
    instituicao_id,
    status,
    erro=None
):

    dados = {

        "status":
            status,

        "ultima_verificacao":
            agora(),
    }

    if status == "erro":

        dados[
            "tentativa_descoberta"
        ] = 1

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

    except Exception as exc:

        print(
            f"⚠️ Falha atualizando instituição: {exc}",
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
            .select(
                "id,tentativas"
            )
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
                "iniciado_em"
            ] = agora()

            dados[
                "tentativas"
            ] = 0

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
# CONSULTAS DE UMA INSTITUIÇÃO
# ============================================================

def montar_consultas(
    instituicao,
    estado
):

    return [

        f'"{instituicao}" Nutrição 2026 estudante',

        f'"{instituicao}" Nutrição 2025 formada',

        f'"{instituicao}" Nutrição 2026 formando',

        f'"{instituicao}" Nutrição TCC',

        f'"{instituicao}" Nutrição "7º semestre"',

        f'"{instituicao}" Nutrição "8º semestre"',

        f'"{instituicao}" Nutrição estágio obrigatório',

        f'"{instituicao}" nutricionista 2025',

        f'"{instituicao}" nutricionista 2026',
    ]


# ============================================================
# PROCESSAR UMA INSTITUIÇÃO
# ============================================================

def processar_instituicao(item):

    instituicao = item[
        "instituicao"
    ]

    cidade = (
        item.get("cidade")
        or ""
    )

    estado = item[
        "estado"
    ]

    id_instituicao = item[
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
        id_instituicao,
        "processando"
    )

    salvar_checkpoint(
        estado,
        cidade,
        instituicao,
        "processando"
    )

    consultas = montar_consultas(
        instituicao,
        estado
    )

    candidatos = {}

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
                                MAX_RESULTADOS
                        )
                    )

                except Exception as erro:

                    print(
                        f"      ⚠️ Busca indisponível: {erro}",
                        flush=True
                    )

                    pausa()

                    continue

                for resultado in resultados:

                    titulo = str(
                        resultado.get(
                            "title",
                            ""
                        )
                    )

                    corpo = str(
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
                            texto,

                        "fonte_url":
                            url,
                    }

                pausa()

    except Exception as erro_geral:

        stats[
            "instituicoes_com_erro"
        ] += 1

        stats[
            "erros"
        ] += 1

        atualizar_instituicao(
            id_instituicao,
            "erro",
            str(erro_geral)
        )

        salvar_checkpoint(
            estado,
            cidade,
            instituicao,
            "erro",
            erro=str(
                erro_geral
            )
        )

        print(
            f"❌ Erro na instituição: {erro_geral}",
            flush=True
        )

        return False

    # ========================================================
    # SALVAR CANDIDATOS
    # ========================================================

    total_encontrados = len(
        candidatos
    )

    stats[
        "leads_encontrados"
    ] += total_encontrados

    salvos_antes = stats[
        "leads_salvos"
    ]

    print(
        f"   👥 Leads válidos encontrados: "
        f"{total_encontrados}",
        flush=True
    )

    for candidato in candidatos.values():

        salvar_lead(

            nome=
                candidato["nome"],

            instituicao=
                instituicao,

            cidade=
                cidade,

            estado=
                estado,

            ano=
                candidato["ano"],

            periodo=
                candidato["periodo"],

            evidencia=
                candidato["evidencia"],

            fonte_url=
                candidato["fonte_url"],
        )

    salvos_nesta = (
        stats["leads_salvos"]
        -
        salvos_antes
    )

    # ========================================================
    # CONCLUIR INSTITUIÇÃO
    # ========================================================

    atualizar_instituicao(
        id_instituicao,
        "concluido"
    )

    salvar_checkpoint(
        estado,
        cidade,
        instituicao,
        "concluido",
        leads_encontrados=
            total_encontrados,
        leads_salvos=
            salvos_nesta
    )

    stats[
        "instituicoes_processadas"
    ] += 1

    stats[
        "instituicoes_concluidas"
    ] += 1

    print(
        f"   ✅ INSTITUIÇÃO CONCLUÍDA | "
        f"Encontrados: {total_encontrados} | "
        f"Novos: {salvos_nesta}",
        flush=True
    )

    return True


# ============================================================
# ESTADO TERMINOU?
# ============================================================

def estado_tem_pendencia(
    estado
):

    fila = buscar_fila_estado(
        estado
    )

    return len(
        fila
    ) > 0


# ============================================================
# DESCOBERTA NACIONAL
#
# ESTÁ DESLIGADA NO PRIMEIRO TESTE.
# Depois do teste SP -> RJ, esta função será usada.
# ============================================================

def descobrir_instituicoes_estado(
    estado
):

    print(
        f"🌎 Descoberta automática de instituições: {estado}",
        flush=True
    )

    consultas = [

        f'"curso de Nutrição" "{estado}" universidade',

        f'"Nutrição" "{estado}" faculdade',

        f'"Nutrição" "{estado}" "em atividade" e-MEC',
    ]

    descobertas = {}

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

                    titulo = str(
                        resultado.get(
                            "title",
                            ""
                        )
                    ).strip()

                    corpo = str(
                        resultado.get(
                            "body",
                            ""
                        )
                    )

                    texto = normalizar(
                        titulo
                        + " "
                        + corpo
                    )

                    if "nutricao" not in texto:
                        continue

                    # Neste primeiro código nacional,
                    # descobertas web são candidatas.
                    # Não salvamos nomes de pessoas aqui.
                    if len(titulo) < 5:
                        continue

                    descobertas[
                        normalizar(titulo)
                    ] = titulo

                pausa()

    except Exception as erro:

        print(
            f"⚠️ Descoberta de {estado} falhou: {erro}",
            flush=True
        )

    print(
        f"   Instituições/fontes candidatas: "
        f"{len(descobertas)}",
        flush=True
    )

    return list(
        descobertas.values()
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

    if MODO_TESTE:

        print(
            "🧪 TESTE REAL DA FILA AUTOMÁTICA",
            flush=True
        )

    else:

        print(
            "🇧🇷 CAPTAÇÃO NACIONAL AUTOMÁTICA",
            flush=True
        )

    print(
        "=" * 70,
        flush=True
    )

    # ========================================================
    # PREPARA O TESTE
    # ========================================================

    if MODO_TESTE:

        preparar_fila_teste()

    estados = estados_da_execucao()

    quantidade_processada = 0

    # ========================================================
    # PERCORRER ESTADOS
    # ========================================================

    for estado in estados:

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

        # ====================================================
        # NO MODO NACIONAL:
        # se ainda não houver fila, descobrir instituições
        # ====================================================

        if (
            not fila
            and
            not MODO_TESTE
        ):

            descobrir_instituicoes_estado(
                estado
            )

            fila = buscar_fila_estado(
                estado
            )

        # ====================================================
        # ESTADO SEM PENDÊNCIAS
        # ====================================================

        if not fila:

            print(
                f"✅ {estado}: nenhuma instituição pendente.",
                flush=True
            )

            continue

        print(
            f"📚 Instituições pendentes: "
            f"{len(fila)}",
            flush=True
        )

        # ====================================================
        # PROCESSAR FACULDADE POR FACULDADE
        # ====================================================

        for item in fila:

            if (
                quantidade_processada
                >=
                MAX_INSTITUICOES_POR_EXECUCAO
            ):

                print("")
                print(
                    "⏸️ Limite desta execução atingido.",
                    flush=True
                )

                print(
                    "Na próxima execução continuará "
                    "da instituição pendente.",
                    flush=True
                )

                resumo()

                return

            processar_instituicao(
                item
            )

            quantidade_processada += 1

            pausa()

        # ====================================================
        # ACABOU O ESTADO
        # ====================================================

        if not estado_tem_pendencia(
            estado
        ):

            print("")
            print(
                f"🏁 ESTADO {estado} CONCLUÍDO",
                flush=True
            )

            print(
                "➡️ Indo automaticamente para o próximo estado...",
                flush=True
            )

    resumo()


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
# START
# ============================================================

if __name__ == "__main__":

    executar()

    print(
        "✅ MÁQUINA 1 FINALIZADA",
        flush=True
    )
