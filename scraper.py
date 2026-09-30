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
# FLUXO:
#
# BRASIL
#   ↓
# ESTADO
#   ↓
# CIDADE
#   ↓
# DESCOBRE FACULDADES COM NUTRIÇÃO
#   ↓
# SALVA FACULDADE NA FILA
#   ↓
# FACULDADE
#   ↓
# PESQUISA CANDIDATOS
#   ↓
# QUALIFICAÇÃO RÍGIDA
#   ↓
# SALVA O LEAD IMEDIATAMENTE
#   ↓
# CHECKPOINT DE CADA PESQUISA
#   ↓
# PRÓXIMA FACULDADE
#
# Se travar:
# - leads já salvos permanecem salvos
# - faculdade continua pendente
# - pesquisa continua do checkpoint
#
# ============================================================


# ============================================================
# CONFIGURAÇÃO SUPABASE
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

UFS = [
    "SP",
    "MG",
    "RJ",
    "PR",
    "SC",
    "RS",
    "BA",
    "PE",
    "CE",
    "GO",
    "DF",
    "ES",
    "MT",
    "MS",
    "PA",
    "MA",
    "PB",
    "RN",
    "AL",
    "SE",
    "PI",
    "RO",
    "TO",
    "AC",
    "AP",
    "AM",
    "RR",
]


# ============================================================
# LIMITES
# ============================================================

# Máximo de faculdades pesquisadas por execução.
# Pode ser:
# 1 faculdade em Itu
# 3 em Sorocaba
# 1 em Indaiatuba
# = total de 5
MAX_FACULDADES_POR_EXECUCAO = 5

# Quantas cidades podemos verificar para descobrir
# faculdades durante uma execução.
MAX_CIDADES_DESCOBERTA_POR_EXECUCAO = 15

MAX_RESULTADOS_BUSCA = 20

MAX_TENTATIVAS_BUSCA = 3

PAUSA_MIN = 3.0
PAUSA_MAX = 5.0

PONTUACAO_MINIMA = 9


# ============================================================
# ESTATÍSTICAS
# ============================================================

estatisticas = {
    "estados_visitados": 0,
    "cidades_verificadas": 0,
    "instituicoes_descobertas": 0,
    "instituicoes_processadas": 0,
    "pesquisas_realizadas": 0,
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
# CACHE / EVIDÊNCIAS DURANTE EXECUÇÃO
# ============================================================

# Não descartamos definitivamente um perfil na primeira aparição.
# Vamos acumulando as evidências que aparecem em pesquisas diferentes.
evidencias_perfis = {}

# Perfis que já foram salvos nesta execução.
salvos_execucao = set()


# ============================================================
# DATA/HORA
# ============================================================

def agora_iso():
    return datetime.now(timezone.utc).isoformat()


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


def normalizar_instagram(instagram):
    if not instagram:
        return None

    instagram = instagram.strip().lower()

    if instagram.startswith("@"):
        return instagram

    return "@" + instagram


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

def pesquisar(ddgs, consulta, max_results=MAX_RESULTADOS_BUSCA):

    estatisticas["pesquisas_realizadas"] += 1

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
                estatisticas["sem_resultado"] += 1

            return resultados, True, None

        except Exception as erro:

            mensagem = str(erro)

            if "No results found" in mensagem:
                estatisticas["sem_resultado"] += 1
                return [], True, None

            print(
                f"⚠️ Falha na pesquisa "
                f"{tentativa}/{MAX_TENTATIVAS_BUSCA}"
            )

            print(
                f"   Erro: {mensagem}"
            )

            # Espera progressivamente mais.
            if tentativa < MAX_TENTATIVAS_BUSCA:

                espera = 8 * tentativa

                print(
                    f"   Nova tentativa em "
                    f"{espera} segundos..."
                )

                time.sleep(espera)

    estatisticas["erros"] += 1

    return [], False, mensagem


# ============================================================
# IBGE - MUNICÍPIOS
# ============================================================

def buscar_municipios_ibge(uf):

    url = (
        "https://servicodados.ibge.gov.br/"
        f"api/v1/localidades/estados/{uf}/municipios"
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

        # Ordem alfabética para manter sequência previsível.
        municipios.sort()

        return municipios

    except Exception as erro:

        print(
            f"❌ Erro obtendo municípios "
            f"de {uf}: {erro}"
        )

        estatisticas["erros"] += 1

        return []


# ============================================================
# CONTROLE DE DESCOBERTA DA CIDADE
# ============================================================

def cidade_ja_verificada(uf, cidade):

    try:

        resposta = (
            supabase
            .table("controle_busca")
            .select("id,status")
            .eq("estado", uf)
            .eq("cidade", cidade)
            .eq("etapa", "descoberta_cidade")
            .eq("status", "concluido")
            .limit(1)
            .execute()
        )

        return bool(resposta.data)

    except Exception as erro:

        print(
            f"⚠️ Erro verificando checkpoint "
            f"da cidade {cidade}: {erro}"
        )

        return False


def registrar_cidade_concluida(
    uf,
    cidade,
    consulta=None,
    fonte="web"
):

    try:

        resposta = (
            supabase
            .table("controle_busca")
            .select("id")
            .eq("estado", uf)
            .eq("cidade", cidade)
            .eq("etapa", "descoberta_cidade")
            .limit(1)
            .execute()
        )

        dados = {
            "estado": uf,
            "cidade": cidade,
            "instituicao": None,
            "etapa": "descoberta_cidade",
            "status": "concluido",
            "indice_pesquisa": 1,
            "total_pesquisas": 1,
            "consulta_atual": consulta,
            "fonte_atual": fonte,
            "atualizado_em": agora_iso(),
            "finalizado_em": agora_iso(),
        }

        if resposta.data:

            (
                supabase
                .table("controle_busca")
                .update(dados)
                .eq("id", resposta.data[0]["id"])
                .execute()
            )

        else:

            dados["iniciado_em"] = agora_iso()

            (
                supabase
                .table("controle_busca")
                .insert(dados)
                .execute()
            )

        return True

    except Exception as erro:

        print(
            f"⚠️ Erro salvando checkpoint "
            f"da cidade: {erro}"
        )

        estatisticas["erros"] += 1

        return False


# ============================================================
# IDENTIFICAÇÃO DE INSTITUIÇÃO
# ============================================================

PALAVRAS_INSTITUICAO = [
    "universidade",
    "faculdade",
    "centro universitario",
    "centro universitário",
    "instituto federal",
    "instituto de ensino",
    "university",
    "unip",
    "uniesp",
    "uninove",
    "unicesumar",
    "anhanguera",
    "estacio",
    "estácio",
    "cruzeiro do sul",
    "uninter",
    "ceunsp",
    "uniso",
]


def resultado_parece_curso_nutricao(texto):

    texto_norm = normalizar_texto(texto)

    if "nutricao" not in texto_norm:
        return False

    sinais_ensino = [
        "curso",
        "graduacao",
        "bacharelado",
        "faculdade",
        "universidade",
        "centro universitario",
        "instituto",
        "vestibular",
    ]

    return any(
        sinal in texto_norm
        for sinal in sinais_ensino
    )


def limpar_nome_instituicao(titulo):

    if not titulo:
        return None

    titulo = re.sub(
        r"\s+",
        " ",
        titulo
    ).strip()

    partes = re.split(
        r"\s[\|\-–—]\s",
        titulo
    )

    for parte in partes:

        parte_norm = normalizar_texto(parte)

        if any(
            normalizar_texto(palavra) in parte_norm
            for palavra in PALAVRAS_INSTITUICAO
        ):

            # Evita salvar título enorme.
            return parte.strip()[:180]

    return None


# ============================================================
# INSTITUIÇÃO JÁ EXISTE?
# ============================================================

def verificar_instituicao_existente(
    uf,
    cidade,
    instituicao
):

    try:

        resposta = (
            supabase
            .table("instituicoes_nutricao")
            .select("id")
            .eq("estado", uf)
            .eq("cidade", cidade)
            .eq("instituicao", instituicao)
            .limit(1)
            .execute()
        )

        return bool(resposta.data)

    except Exception as erro:

        print(
            f"⚠️ Erro verificando instituição: "
            f"{erro}"
        )

        # Em caso de dúvida não inserimos duplicado.
        return None


# ============================================================
# SALVAR INSTITUIÇÃO
# ============================================================

def salvar_instituicao(
    uf,
    cidade,
    instituicao,
    fonte_url,
    origem
):

    existente = verificar_instituicao_existente(
        uf,
        cidade,
        instituicao
    )

    if existente is True:
        return False

    if existente is None:
        return False

    dados = {
        "estado": uf,
        "cidade": cidade,
        "instituicao": instituicao,
        "curso": "Nutrição",
        "origem": origem,
        "fonte_url": fonte_url,
        "status": "pendente",
        "ultima_verificacao": agora_iso(),
    }

    try:

        (
            supabase
            .table("instituicoes_nutricao")
            .insert(dados)
            .execute()
        )

        estatisticas["instituicoes_descobertas"] += 1

        print(
            f"   🏫 NOVA FACULDADE:"
        )

        print(
            f"      {instituicao}"
        )

        print(
            f"      {cidade}/{uf}"
        )

        return True

    except Exception as erro:

        print(
            f"⚠️ Erro salvando instituição: "
            f"{erro}"
        )

        estatisticas["erros"] += 1

        return False


# ============================================================
# DESCOBERTA DE FACULDADES POR CIDADE
# ============================================================

def descobrir_faculdades_cidade(
    ddgs,
    uf,
    cidade
):

    print("")
    print(
        f"🔎 Procurando faculdades de Nutrição:"
    )

    print(
        f"   📍 {cidade}/{uf}"
    )

    # Uma busca mais ampla.
    # As fontes oficiais/institucionais são privilegiadas
    # no filtro, mas não dependemos de uma única fonte.
    consulta = (
        f'"Nutrição" "{cidade}" "{uf}" '
        f'("faculdade" OR "universidade" '
        f'OR "centro universitário" '
        f'OR "graduação")'
    )

    resultados, busca_ok, erro = pesquisar(
        ddgs,
        consulta,
        max_results=25
    )

    if not busca_ok:

        print(
            f"   ⚠️ Cidade NÃO marcada como concluída."
        )

        return False

    encontradas = 0

    for resultado in resultados:

        titulo = resultado.get("title") or ""
        corpo = resultado.get("body") or ""

        url = (
            resultado.get("href")
            or resultado.get("url")
            or ""
        )

        texto = (
            f"{titulo} "
            f"{corpo} "
            f"{url}"
        )

        # O resultado precisa realmente parecer
        # oferta de curso superior de Nutrição.
        if not resultado_parece_curso_nutricao(
            texto
        ):
            continue

        # Cidade também deve aparecer no resultado.
        if (
            normalizar_texto(cidade)
            not in normalizar_texto(texto)
        ):
            continue

        instituicao = limpar_nome_instituicao(
            titulo
        )

        if not instituicao:
            continue

        dominio = ""

        try:

            dominio = urlparse(
                url
            ).netloc.lower()

        except Exception:
            pass

        if "gov.br" in dominio:
            origem = "fonte_oficial"

        elif "edu.br" in dominio:
            origem = "site_educacional"

        elif "emec" in dominio:
            origem = "e_mec"

        else:
            origem = "busca_web"

        salvo = salvar_instituicao(
            uf,
            cidade,
            instituicao,
            url,
            origem
        )

        if salvo:
            encontradas += 1

    registrar_cidade_concluida(
        uf,
        cidade,
        consulta=consulta,
        fonte="descoberta_faculdades"
    )

    estatisticas["cidades_verificadas"] += 1

    print(
        f"   ✅ Cidade verificada. "
        f"Novas instituições: {encontradas}"
    )

    pausa()

    return True


# ============================================================
# PEGAR FACULDADES PENDENTES
# ============================================================

def buscar_faculdades_pendentes(
    uf=None,
    limite=5
):

    try:

        consulta = (
            supabase
            .table("instituicoes_nutricao")
            .select("*")
            .eq("status", "pendente")
        )

        if uf:
            consulta = consulta.eq(
                "estado",
                uf
            )

        resposta = (
            consulta
            .order("estado")
            .order("cidade")
            .limit(limite)
            .execute()
        )

        return resposta.data or []

    except Exception as erro:

        print(
            f"❌ Erro carregando faculdades "
            f"pendentes: {erro}"
        )

        estatisticas["erros"] += 1

        return []


# ============================================================
# STATUS DA FACULDADE
# ============================================================

def atualizar_status_faculdade(
    instituicao_id,
    status
):

    try:

        (
            supabase
            .table("instituicoes_nutricao")
            .update({
                "status": status,
                "ultima_verificacao": agora_iso(),
            })
            .eq("id", instituicao_id)
            .execute()
        )

        return True

    except Exception as erro:

        print(
            f"⚠️ Erro atualizando faculdade: "
            f"{erro}"
        )

        return False


# ============================================================
# CHECKPOINT DA FACULDADE
# ============================================================

def obter_checkpoint_faculdade(
    instituicao
):

    try:

        resposta = (
            supabase
            .table("controle_busca")
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


def atualizar_checkpoint_faculdade(
    instituicao,
    status,
    indice_pesquisa,
    total_pesquisas,
    consulta_atual=None,
    fonte_atual="web",
    leads_encontrados=0,
    leads_salvos=0,
    ultimo_erro=None
):

    try:

        atual = obter_checkpoint_faculdade(
            instituicao
        )

        dados = {
            "estado": instituicao["estado"],
            "cidade": instituicao["cidade"],
            "instituicao":
                instituicao["instituicao"],
            "etapa": "busca_leads",
            "status": status,
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

        if status == "processando":

            if not atual:
                dados["iniciado_em"] = agora_iso()

        if status == "concluido":
            dados["finalizado_em"] = agora_iso()

        if atual:

            (
                supabase
                .table("controle_busca")
                .update(dados)
                .eq("id", atual["id"])
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
            f"⚠️ Erro salvando checkpoint: "
            f"{erro}"
        )

        estatisticas["erros"] += 1

        return False


# ============================================================
# INSTAGRAM
# ============================================================

def extrair_instagram(url):

    if not url:
        return None

    try:

        parsed = urlparse(url)

        dominio = parsed.netloc.lower()

        if (
            "instagram.com" not in dominio
            and "www.instagram.com" not in dominio
        ):
            return None

        partes = [
            p
            for p in parsed.path.split("/")
            if p
        ]

        if not partes:
            return None

        usuario = partes[0].lower()

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
# EXCLUSÕES
# ============================================================

TERMOS_EXCLUSAO = [
    "psicologa",
    "psicologo",
    "psicologia",
    "maquiadora",
    "maquiagem",
    "makeup",
    "meme",
    "memes",
    "veterinaria",
    "veterinario",
    "medicina veterinaria",
    "pet shop",
    "odontologia",
    "dentista",
    "fotografia",
    "fotografa",
    "fotografo",
    "fonoaudiologia",
    "fisioterapia",
    "advogada",
    "advogado",
    "engenharia",
    "arquitetura",
    "kumon",
]


def e_excluido(texto):

    texto_norm = normalizar_texto(
        texto
    )

    return any(
        termo in texto_norm
        for termo in TERMOS_EXCLUSAO
    )


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
        "estudante de nutricao",
        "academica de nutricao",
        "academico de nutricao",
        "graduanda em nutricao",
        "graduando em nutricao",
        "bacharel em nutricao",
        "curso de nutricao",
        "crn",
    ]

    if any(
        sinal in texto_norm
        for sinal in sinais_fortes
    ):
        return True

    # "Nutrição" no texto também conta,
    # desde que não seja perfil excluído.
    if "nutricao" in texto_norm:
        return True

    # Handle pode ajudar, mas apenas padrões fortes.
    padroes_handle = [
        ".nutri",
        "nutri.",
        "_nutri",
        "nutri_",
        "nutricionista",
    ]

    if any(
        padrao in instagram_norm
        for padrao in padroes_handle
    ):

        # Ainda exigimos algum contexto educacional/profissional.
        contexto = [
            "formanda",
            "formando",
            "graduanda",
            "graduando",
            "crn",
            "atendimento",
            "consulta",
        ]

        if any(
            termo in texto_norm
            for termo in contexto
        ):
            return True

    return False


# ============================================================
# COORTE ALVO
# ============================================================

def e_coorte_alvo(texto):

    texto_norm = normalizar_texto(
        texto
    )

    anos_alvo = (
        "2025" in texto_norm
        or "2026" in texto_norm
    )

    conclusao = [
        "formatura",
        "formou",
        "formada",
        "formado",
        "colacao",
        "colacao de grau",
        "conclusao",
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
        for termo in conclusao
    )

    tem_final = any(
        termo in texto_norm
        for termo in etapa_final
    )

    # Formado recente:
    # precisa haver ano + conclusão.
    formado_recente = (
        anos_alvo
        and tem_conclusao
    )

    # Aluno no final do curso:
    # não depende obrigatoriamente do ano.
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

    finais = [
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
        for termo in finais
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
        and cidade_norm in texto_norm
    ):
        pontos += 2

    instituicao_norm = normalizar_texto(
        instituicao
    )

    if (
        instituicao_norm
        and instituicao_norm in texto_norm
    ):
        pontos += 2

    comerciais = [
        "agenda aberta",
        "consultas",
        "atendimento online",
        "atendimento presencial",
        "atendimentos",
    ]

    if any(
        termo in texto_norm
        for termo in comerciais
    ):
        pontos += 1

    return pontos


# ============================================================
# EVIDÊNCIA
# ============================================================

def montar_evidencia(texto):

    texto_norm = normalizar_texto(
        texto
    )

    evidencias = []

    if "nutricionista" in texto_norm:
        evidencias.append("nutricionista")

    if "nutricao" in texto_norm:
        evidencias.append("Nutrição")

    if "crn" in texto_norm:
        evidencias.append("CRN")

    if "2025" in texto_norm:
        evidencias.append("2025")

    if "2026" in texto_norm:
        evidencias.append("2026")

    if (
        "formanda" in texto_norm
        or "formando" in texto_norm
    ):
        evidencias.append("formando(a)")

    if "concluinte" in texto_norm:
        evidencias.append("concluinte")

    if "tcc" in texto_norm:
        evidencias.append("TCC")

    if (
        "ultimo periodo" in texto_norm
        or "ultimo semestre" in texto_norm
    ):
        evidencias.append("final do curso")

    if (
        "7/8" in texto_norm
        or "8/8" in texto_norm
    ):
        evidencias.append("7/8 ou 8/8")

    if (
        "formatura" in texto_norm
        or "colacao" in texto_norm
    ):
        evidencias.append("formatura/colação")

    if not evidencias:
        return "evidência pública encontrada"

    return " | ".join(
        dict.fromkeys(evidencias)
    )


# ============================================================
# LEAD JÁ EXISTE?
# ============================================================

def verificar_lead_existente(
    instagram
):

    for tentativa in range(1, 4):

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

            return bool(resposta.data)

        except Exception as erro:

            print(
                f"⚠️ Erro verificando duplicidade "
                f"{instagram} "
                f"({tentativa}/3): {erro}"
            )

            if tentativa < 3:
                time.sleep(3 * tentativa)

    # None = não foi possível confirmar.
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
# SALVAR LEAD IMEDIATAMENTE
# ============================================================

def salvar_lead(lead):

    instagram = lead["instagram"]

    if instagram in salvos_execucao:
        return False

    existente = verificar_lead_existente(
        instagram
    )

    if existente is True:

        estatisticas["duplicados"] += 1

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

        estatisticas["salvos"] += 1

        print(
            f"      ✅ SALVO NO SUPABASE: "
            f"{instagram}"
        )

        return True

    except Exception as erro:

        estatisticas["erros"] += 1

        print(
            f"      ❌ ERRO AO SALVAR "
            f"{instagram}: {erro}"
        )

        return False


# ============================================================
# PROCESSAMENTO DE PERFIL
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

    estatisticas["resultados_analisados"] += 1

    texto_novo = (
        f"{titulo} "
        f"{corpo} "
        f"{url}"
    )

    # --------------------------------------------------------
    # ACUMULA EVIDÊNCIAS DO MESMO PERFIL
    # --------------------------------------------------------

    if instagram not in evidencias_perfis:

        evidencias_perfis[instagram] = {
            "textos": [],
            "titulo": titulo,
            "url": url,
        }

        estatisticas["perfis_unicos"] += 1

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

    # --------------------------------------------------------
    # EXCLUSÕES
    # --------------------------------------------------------

    if e_excluido(
        texto_completo
    ):

        print(
            f"      ❌ Fora do nicho: "
            f"{instagram}"
        )

        estatisticas["rejeitados"] += 1

        return False

    # --------------------------------------------------------
    # REGRA 1 - NUTRIÇÃO
    # --------------------------------------------------------

    if not e_nutricao(
        texto_completo,
        instagram
    ):

        print(
            f"      ⏳ Ainda sem prova suficiente "
            f"de Nutrição: {instagram}"
        )

        return False

    # --------------------------------------------------------
    # REGRA 2 - COORTE
    # --------------------------------------------------------

    if not e_coorte_alvo(
        texto_completo
    ):

        print(
            f"      ⏳ Nutrição encontrada, "
            f"mas sem prova de 2025/2026 "
            f"ou fase final: {instagram}"
        )

        return False

    # --------------------------------------------------------
    # PONTUAÇÃO
    # --------------------------------------------------------

    pontos = calcular_pontuacao(
        texto_completo,
        instagram,
        instituicao["cidade"],
        instituicao["instituicao"],
    )

    if pontos < PONTUACAO_MINIMA:

        print(
            f"      ⏳ Evidência ainda fraca: "
            f"{instagram} | {pontos} pontos"
        )

        return False

    # --------------------------------------------------------
    # QUALIFICADO
    # --------------------------------------------------------

    estatisticas["qualificados"] += 1

    evidencia = montar_evidencia(
        texto_completo
    )

    print(
        f"      🎯 QUALIFICADO: "
        f"{instagram}"
    )

    print(
        f"         Pontuação: {pontos}"
    )

    print(
        f"         Evidência: {evidencia}"
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
# CONSULTAS PARA CADA FACULDADE
# ============================================================

def montar_consultas_faculdade(
    instituicao
):

    nome = instituicao["instituicao"]
    cidade = instituicao["cidade"]
    uf = instituicao["estado"]

    exclusoes = (
        "-psicologia "
        "-maquiagem "
        "-makeup "
        "-veterinária "
        "-odontologia "
        "-memes "
        "-kumon"
    )

    consultas = [

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

        # Busca complementar da cidade.
        (
            f'site:instagram.com '
            f'"{cidade}" '
            f'"{uf}" '
            f'"Nutricionista" '
            f'"2026" '
            f'{exclusoes}'
        ),

        (
            f'site:instagram.com '
            f'"{cidade}" '
            f'"{uf}" '
            f'"Nutricionista" '
            f'"2025" '
            f'{exclusoes}'
        ),
    ]

    return consultas


# ============================================================
# PROCESSAR UMA FACULDADE
# ============================================================

def processar_faculdade(
    ddgs,
    instituicao
):

    nome = instituicao["instituicao"]
    cidade = instituicao["cidade"]
    uf = instituicao["estado"]

    print("")
    print(
        "================================================="
    )

    print(
        f"🏫 FACULDADE: {nome}"
    )

    print(
        f"📍 {cidade}/{uf}"
    )

    print(
        "================================================="
    )

    consultas = montar_consultas_faculdade(
        instituicao
    )

    total = len(consultas)

    checkpoint = obter_checkpoint_faculdade(
        instituicao
    )

    # --------------------------------------------------------
    # RETOMAR DO PONTO EXATO
    # --------------------------------------------------------

    inicio = 0

    if checkpoint:

        indice_salvo = (
            checkpoint.get(
                "indice_pesquisa"
            )
            or 0
        )

        status_checkpoint = (
            checkpoint.get("status")
            or ""
        )

        if (
            status_checkpoint
            in ["processando", "erro"]
            and indice_salvo > 0
        ):

            inicio = indice_salvo - 1

            print(
                f"♻️ Retomando do checkpoint:"
            )

            print(
                f"   Pesquisa "
                f"{indice_salvo}/{total}"
            )

    atualizar_status_faculdade(
        instituicao["id"],
        "processando"
    )

    salvos_antes = estatisticas["salvos"]

    resultados_local = 0

    # --------------------------------------------------------
    # PESQUISAS
    # --------------------------------------------------------

    for posicao in range(
        inicio,
        total
    ):

        consulta = consultas[posicao]

        numero = posicao + 1

        print("")
        print(
            f"   🔍 Pesquisa "
            f"{numero}/{total}"
        )

        # Primeiro grava:
        # "vou começar esta pesquisa".
        atualizar_checkpoint_faculdade(
            instituicao=instituicao,
            status="processando",
            indice_pesquisa=numero,
            total_pesquisas=total,
            consulta_atual=consulta,
            fonte_atual="instagram_web",
            leads_encontrados=
                resultados_local,
            leads_salvos=
                estatisticas["salvos"]
                - salvos_antes,
        )

        resultados, busca_ok, erro = pesquisar(
            ddgs,
            consulta,
            max_results=MAX_RESULTADOS_BUSCA
        )

        # ----------------------------------------------------
        # ERRO
        # ----------------------------------------------------

        if not busca_ok:

            print(
                f"   ❌ Erro nesta pesquisa."
            )

            print(
                "   Faculdade ficará pendente "
                "para continuar depois."
            )

            atualizar_checkpoint_faculdade(
                instituicao=instituicao,
                status="erro",
                indice_pesquisa=numero,
                total_pesquisas=total,
                consulta_atual=consulta,
                fonte_atual="instagram_web",
                leads_encontrados=
                    resultados_local,
                leads_salvos=
                    estatisticas["salvos"]
                    - salvos_antes,
                ultimo_erro=erro,
            )

            atualizar_status_faculdade(
                instituicao["id"],
                "pendente"
            )

            return False

        # ----------------------------------------------------
        # PROCESSA RESULTADOS
        # ----------------------------------------------------

        for resultado in resultados:

            resultados_local += 1

            processar_resultado_lead(
                resultado,
                instituicao
            )

        # ----------------------------------------------------
        # CHECKPOINT APÓS PESQUISA CONCLUÍDA
        #
        # Guardamos a próxima pesquisa que deverá iniciar.
        # ----------------------------------------------------

        proxima_pesquisa = numero + 1

        atualizar_checkpoint_faculdade(
            instituicao=instituicao,
            status="processando",
            indice_pesquisa=proxima_pesquisa,
            total_pesquisas=total,
            consulta_atual=consulta,
            fonte_atual="instagram_web",
            leads_encontrados=
                resultados_local,
            leads_salvos=
                estatisticas["salvos"]
                - salvos_antes,
        )

        pausa()

    # --------------------------------------------------------
    # FACULDADE CONCLUÍDA
    # --------------------------------------------------------

    salvos_local = (
        estatisticas["salvos"]
        - salvos_antes
    )

    atualizar_checkpoint_faculdade(
        instituicao=instituicao,
        status="concluido",
        indice_pesquisa=total,
        total_pesquisas=total,
        consulta_atual="concluido",
        fonte_atual="instagram_web",
        leads_encontrados=
            resultados_local,
        leads_salvos=
            salvos_local,
    )

    atualizar_status_faculdade(
        instituicao["id"],
        "concluido"
    )

    estatisticas[
        "instituicoes_processadas"
    ] += 1

    print("")
    print(
        f"✅ FACULDADE CONCLUÍDA"
    )

    print(
        f"   Leads salvos nesta faculdade: "
        f"{salvos_local}"
    )

    return True


# ============================================================
# RECUPERAR FACULDADES QUE TRAVARAM
# ============================================================

def recuperar_faculdades_interrompidas():

    try:

        resposta = (
            supabase
            .table("instituicoes_nutricao")
            .select("id,instituicao,cidade,estado")
            .eq(
                "status",
                "processando"
            )
            .execute()
        )

        registros = resposta.data or []

        for registro in registros:

            (
                supabase
                .table("instituicoes_nutricao")
                .update({
                    "status": "pendente"
                })
                .eq(
                    "id",
                    registro["id"]
                )
                .execute()
            )

        if registros:

            print(
                f"♻️ {len(registros)} faculdade(s) "
                f"interrompida(s) retornaram "
                f"para a fila."
            )

    except Exception as erro:

        print(
            f"⚠️ Erro recuperando fila: "
            f"{erro}"
        )


# ============================================================
# DESCOBRIR NOVAS FACULDADES
# ============================================================

def abastecer_fila_faculdades(
    ddgs,
    uf
):

    municipios = buscar_municipios_ibge(
        uf
    )

    if not municipios:
        return False

    cidades_feitas = 0

    for cidade in municipios:

        if (
            cidades_feitas
            >= MAX_CIDADES_DESCOBERTA_POR_EXECUCAO
        ):
            break

        if cidade_ja_verificada(
            uf,
            cidade
        ):
            continue

        sucesso = descobrir_faculdades_cidade(
            ddgs,
            uf,
            cidade
        )

        if not sucesso:

            # Paramos porque pode haver
            # bloqueio/problema de busca.
            break

        cidades_feitas += 1

    return True


# ============================================================
# ESTADO POSSUI CIDADES NÃO VERIFICADAS?
# ============================================================

def estado_tem_cidades_pendentes(uf):

    municipios = buscar_municipios_ibge(
        uf
    )

    if not municipios:
        return False

    for cidade in municipios:

        if not cidade_ja_verificada(
            uf,
            cidade
        ):
            return True

    return False


# ============================================================
# EXECUÇÃO NACIONAL
# ============================================================

def executar_maquina():

    recuperar_faculdades_interrompidas()

    faculdades_processadas_execucao = 0

    with DDGS() as ddgs:

        for uf in UFS:

            if (
                faculdades_processadas_execucao
                >= MAX_FACULDADES_POR_EXECUCAO
            ):
                break

            estatisticas["estados_visitados"] += 1

            print("")
            print(
                "#################################################"
            )

            print(
                f"🇧🇷 ESTADO: {uf}"
            )

            print(
                "#################################################"
            )

            # =================================================
            # 1. PRIMEIRO VÊ SE JÁ TEM FACULDADE NA FILA
            # =================================================

            restante = (
                MAX_FACULDADES_POR_EXECUCAO
                - faculdades_processadas_execucao
            )

            pendentes = buscar_faculdades_pendentes(
                uf=uf,
                limite=restante
            )

            # =================================================
            # 2. SE NÃO TIVER O SUFICIENTE,
            #    DESCOBRE MAIS CIDADES/FACULDADES
            # =================================================

            if len(pendentes) < restante:

                abastecer_fila_faculdades(
                    ddgs,
                    uf
                )

                restante = (
                    MAX_FACULDADES_POR_EXECUCAO
                    - faculdades_processadas_execucao
                )

                pendentes = buscar_faculdades_pendentes(
                    uf=uf,
                    limite=restante
                )

            # =================================================
            # 3. PROCESSA FACULDADES
            # =================================================

            for instituicao in pendentes:

                if (
                    faculdades_processadas_execucao
                    >= MAX_FACULDADES_POR_EXECUCAO
                ):
                    break

                processar_faculdade(
                    ddgs,
                    instituicao
                )

                faculdades_processadas_execucao += 1

            # =================================================
            # 4. SE AINDA TEM FACULDADES OU CIDADES NO ESTADO,
            #    NÃO PASSA PARA OUTRO ESTADO NESTA LÓGICA.
            # =================================================

            ainda_tem_faculdade = bool(
                buscar_faculdades_pendentes(
                    uf=uf,
                    limite=1
                )
            )

            ainda_tem_cidade = (
                estado_tem_cidades_pendentes(
                    uf
                )
            )

            if (
                ainda_tem_faculdade
                or ainda_tem_cidade
            ):

                print("")
                print(
                    f"⏸️ {uf} ainda não terminou."
                )

                print(
                    "Na próxima execução "
                    "a máquina continuará nele."
                )

                break

            print("")
            print(
                f"✅ Estado {uf} concluído."
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
    "Fluxo:"
)

print(
    "Estado > Cidade > Faculdade > Lead"
)

print(
    "Cada lead qualificado é salvo imediatamente."
)

print(
    "Cada pesquisa gera checkpoint."
)

print(
    "================================================="
)


# ============================================================
# EXECUTAR
# ============================================================

executar_maquina()


# ============================================================
# RESUMO FINAL
# ============================================================

print("")
print(
    "================================================="
)

print(
    "RESUMO FINAL DA EXECUÇÃO"
)

print(
    "================================================="
)

print(
    f"Estados visitados: "
    f"{estatisticas['estados_visitados']}"
)

print(
    f"Cidades verificadas: "
    f"{estatisticas['cidades_verificadas']}"
)

print(
    f"Instituições descobertas: "
    f"{estatisticas['instituicoes_descobertas']}"
)

print(
    f"Instituições processadas: "
    f"{estatisticas['instituicoes_processadas']}"
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
    f"Perfis únicos analisados: "
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
    "O progresso foi preservado no Supabase."
)

print(
    "================================================="
)
