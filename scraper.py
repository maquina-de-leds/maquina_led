import osimport os
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
# FACULDADES
# ============================================================

FACULDADES = [

    {
        "nome": "Universidade Presbiteriana Mackenzie",
        "sigla": "Mackenzie",
        "cidade": "São Paulo",
        "estado": "SP",
        "dominio": "mackenzie.br",

        "fontes_oficiais": [

            {
                "tipo": "tcc_2026_1",

                "url": (
                    "https://www.mackenzie.br/"
                    "universidade/unidades-academicas/"
                    "ccbs/tcc-e-pesquisa/mostra-de-tcc"
                ),

                "ano": 2026,

                "fase": "TCC 2026.1",
            }

        ],
    },

    {
        "nome": "Universidade Paulista",
        "sigla": "UNIP",
        "cidade": "São Paulo",
        "estado": "SP",
        "dominio": "unip.br",
        "fontes_oficiais": [],
    },

    {
        "nome": "PUC-Campinas",
        "sigla": "PUC Campinas",
        "cidade": "Campinas",
        "estado": "SP",
        "dominio": "puc-campinas.edu.br",
        "fontes_oficiais": [],
    },

    {
        "nome": "Universidade Anhembi Morumbi",
        "sigla": "Anhembi Morumbi",
        "cidade": "São Paulo",
        "estado": "SP",
        "dominio": "anhembi.br",
        "fontes_oficiais": [],
    },

    {
        "nome": "Universidade Nove de Julho",
        "sigla": "UNINOVE",
        "cidade": "São Paulo",
        "estado": "SP",
        "dominio": "uninove.br",
        "fontes_oficiais": [],
    },

]


# ============================================================
# CONFIGURAÇÃO
# ============================================================

MAX_RESULTADOS = 25
MAX_TENTATIVAS = 2

PAUSA_MIN = 5
PAUSA_MAX = 8

ETAPA_CHECKPOINT = "captacao_faculdades_2025_2026"


# ============================================================
# ESTATÍSTICAS
# ============================================================

stats = {
    "fontes_oficiais": 0,
    "nomes_oficiais": 0,
    "buscas": 0,
    "resultados": 0,
    "validos": 0,
    "salvos": 0,
    "duplicados": 0,
    "rejeitados": 0,
    "erros": 0,
}


vistos = set()


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


def nome_formatado(nome):

    nome = re.sub(
        r"\s+",
        " ",
        nome
    ).strip()

    return nome


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

    palavras = nome.split()

    if len(palavras) < 2:
        return False

    if len(palavras) > 8:
        return False

    n = normalizar(nome)

    proibidos = [
        "universidade",
        "faculdade",
        "centro universitario",
        "curso de nutricao",
        "departamento",
        "turma",
        "formatura",
        "comissao",
        "atletica",
        "instituto",
        "escola",
        "limited",
        "company",
        "ltda",
        "anhanguera",
    ]

    if any(
        termo in n
        for termo in proibidos
    ):
        return False

    caracteres_invalidos = re.sub(
        r"[A-Za-zÀ-ÿ'´`\-\s.]",
        "",
        nome
    )

    if len(caracteres_invalidos) > 2:
        return False

    return True


# ============================================================
# CHECKPOINT
# ============================================================

def buscar_checkpoint():

    try:

        resposta = (
            supabase
            .table("controle_busca")
            .select("*")
            .eq(
                "etapa",
                ETAPA_CHECKPOINT
            )
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


def obter_indice():

    checkpoint = buscar_checkpoint()

    if not checkpoint:
        return 0

    indice = checkpoint.get(
        "indice_pesquisa"
    )

    if indice is None:
        return 0

    return int(indice)


def salvar_checkpoint(
    indice,
    faculdade,
    status
):

    atual = buscar_checkpoint()

    dados = {
        "estado": faculdade["estado"],
        "cidade": faculdade["cidade"],
        "instituicao": faculdade["nome"],
        "etapa": ETAPA_CHECKPOINT,
        "status": status,
        "indice_pesquisa": indice,
        "total_pesquisas": len(FACULDADES),
        "consulta_atual": faculdade["nome"],
        "fonte_atual": "academica_web",
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

            dados["iniciado_em"] = agora()

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

        stats["erros"] += 1

        return False


# ============================================================
# DUPLICIDADE
# ============================================================

def existe(
    nome,
    faculdade,
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
                faculdade["nome"]
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
            f"⚠️ Erro duplicidade: {erro}"
        )

        return None


# ============================================================
# SALVAR IMEDIATAMENTE
# ============================================================

def salvar_lead(
    nome,
    faculdade,
    ano,
    fase,
    fonte_url,
    fonte_validacao,
    origem,
    linkedin=None,
    instagram=None
):

    duplicado = existe(
        nome,
        faculdade,
        linkedin,
        instagram
    )

    if duplicado is True:

        stats["duplicados"] += 1

        print(
            f"♻️ Duplicado: {nome}"
        )

        return False

    if duplicado is None:
        return False

    dados = {

        "nome": nome[:150],

        "instagram": instagram,

        "linkedin": linkedin,

        "whatsapp": None,

        "nicho": "nutricionista",

        "origem": origem,

        "origem_lead": "busca_principal",

        "lead_origem": None,

        "nivel_rede": 0,

        "rede_processada": False,

        "status": "novo",

        "app_baixado": False,

        "nao_contatar": False,

        "qualificado": True,

        "cliente": False,

        "tentativas_contato": 0,

        "cidade": faculdade["cidade"],

        "estado": faculdade["estado"],

        "instituicao": faculdade["nome"],

        "ano_alvo": ano,

        "periodo_alvo": fase,

        "pontuacao": 10,

        "evidencia": (
            f"Nutrição | "
            f"{faculdade['sigla']} | "
            f"{ano} | "
            f"{fase}"
        ),

        "fonte_url": fonte_url,

        "fonte_validacao":
            fonte_validacao,
    }

    try:

        (
            supabase
            .table("leds")
            .insert(dados)
            .execute()
        )

        stats["salvos"] += 1

        print(
            f"✅ SALVO: "
            f"{nome} | "
            f"{ano} | "
            f"{fase}"
        )

        return True

    except Exception as erro:

        print(
            f"❌ Erro salvando {nome}: "
            f"{erro}"
        )

        stats["erros"] += 1

        return False


# ============================================================
# FONTE OFICIAL MACKENZIE
# ============================================================

def extrair_tcc_mackenzie(
    url
):

    resposta = requests.get(
        url,
        timeout=40,
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

    linhas = [
        linha.strip()

        for linha in soup.get_text(
            "\n"
        ).splitlines()

        if linha.strip()
    ]

    nomes = []

    dentro_nutricao = False

    for linha in linhas:

        linha_norm = normalizar(
            linha
        )

        if (
            "nutricao 2026.1"
            in linha_norm
        ):

            dentro_nutricao = True
            continue

        if (
            dentro_nutricao
            and
            (
                "fisioterapia"
                in linha_norm
                or
                "psicologia"
                in linha_norm
                or
                "farmacia"
                in linha_norm
            )
        ):

            break

        if not dentro_nutricao:
            continue

        match = re.match(
            r"^\d{1,2}\s*-\s*(.+)$",
            linha
        )

        if not match:
            continue

        texto_nomes = (
            match
            .group(1)
            .strip()
        )

        partes = re.split(
            r"\s+e\s+",
            texto_nomes,
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
                    nome_formatado(
                        nome
                    )
                )

    return list(
        dict.fromkeys(
            nomes
        )
    )


# ============================================================
# FONTES OFICIAIS
# ============================================================

def processar_fontes_oficiais(
    faculdade
):

    for fonte in faculdade.get(
        "fontes_oficiais",
        []
    ):

        try:

            print("")
            print(
                f"📚 Fonte oficial: "
                f"{fonte['tipo']}"
            )

            if fonte["tipo"] == "tcc_2026_1":

                nomes = (
                    extrair_tcc_mackenzie(
                        fonte["url"]
                    )
                )

                stats[
                    "fontes_oficiais"
                ] += 1

                stats[
                    "nomes_oficiais"
                ] += len(nomes)

                print(
                    f"👥 Nomes oficiais: "
                    f"{len(nomes)}"
                )

                for nome in nomes:

                    salvar_lead(
                        nome=nome,
                        faculdade=faculdade,
                        ano=2026,
                        fase="TCC 2026.1",
                        fonte_url=
                            fonte["url"],
                        fonte_validacao=
                            "site oficial Mackenzie",
                        origem=
                            "fonte_academica_oficial"
                    )

        except Exception as erro:

            print(
                f"⚠️ Erro fonte oficial: "
                f"{erro}"
            )

            stats["erros"] += 1


# ============================================================
# BUSCA WEB
# ============================================================

def pesquisar(
    ddgs,
    consulta
):

    stats["buscas"] += 1

    print("")
    print(
        f"🔎 {consulta}"
    )

    for tentativa in range(
        1,
        MAX_TENTATIVAS + 1
    ):

        try:

            return list(
                ddgs.text(
                    consulta,
                    max_results=
                        MAX_RESULTADOS
                )
            )

        except Exception as erro:

            mensagem = str(erro)

            if (
                "No results found"
                in mensagem
            ):
                return []

            print(
                f"⚠️ Tentativa "
                f"{tentativa}/"
                f"{MAX_TENTATIVAS}: "
                f"{mensagem}"
            )

            if tentativa < MAX_TENTATIVAS:

                time.sleep(12)

    stats["erros"] += 1

    return []


# ============================================================
# BLOCOS DA VARREDURA
# ============================================================

def consultas_complementares(
    faculdade
):

    nome = faculdade["nome"]

    return [

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"7º semestre" 2026',

            "ano": 2026,

            "fase": "7º semestre",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"7º período" 2026',

            "ano": 2026,

            "fase": "7º período",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"8º semestre" 2026',

            "ano": 2026,

            "fase": "8º semestre",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"8º período" 2026',

            "ano": 2026,

            "fase": "8º período",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"TCC" 2026',

            "ano": 2026,

            "fase": "TCC",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"estágio obrigatório" 2026',

            "ano": 2026,

            "fase":
                "estágio obrigatório",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"estágio curricular" 2026',

            "ano": 2026,

            "fase":
                "estágio curricular",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"formanda" 2026',

            "ano": 2026,

            "fase": "formando",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"formando" 2026',

            "ano": 2026,

            "fase": "formando",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"formatura" 2026',

            "ano": 2026,

            "fase":
                "formatura 2026",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"formatura" 2025',

            "ano": 2025,

            "fase":
                "formado em 2025",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"colação" 2025',

            "ano": 2025,

            "fase":
                "formado em 2025",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"recém-formada" 2025',

            "ano": 2025,

            "fase":
                "recém-formado",
        },

        {
            "q":
                f'"{nome}" '
                f'"Nutrição" '
                f'"recém-formado" 2025',

            "ano": 2025,

            "fase":
                "recém-formado",
        },
    ]


# ============================================================
# REDES SOCIAIS
# ============================================================

def identificar_perfil(
    url
):

    if not url:
        return None, None

    try:

        parsed = urlparse(url)

        host = (
            parsed.netloc
            .lower()
            .replace(
                "www.",
                ""
            )
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

            return None, None

        if "instagram.com" in host:

            partes = [
                p
                for p in parsed.path.split("/")
                if p
            ]

            if not partes:
                return None, None

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
                return None, None

            if re.match(
                r"^[A-Za-z0-9._]+$",
                usuario
            ):

                return (
                    "instagram",
                    "@"
                    + usuario
                )

    except Exception:
        pass

    return None, None


# ============================================================
# NOME DO RESULTADO
# ============================================================

def extrair_nome_resultado(
    titulo
):

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

    # remove cargo após hífen
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
# EVIDÊNCIAS DO RESULTADO
# ============================================================

def tem_nutricao(
    texto
):

    t = normalizar(texto)

    return (
        "nutricao"
        in t
        or
        "nutricionista"
        in t
    )


def tem_mackenzie(
    texto
):

    t = normalizar(texto)

    return (
        "universidade presbiteriana mackenzie"
        in t
        or
        (
            "mackenzie"
            in t
            and
            "sao paulo"
            in t
        )
    )


def tem_fase_final(
    texto
):

    t = normalizar(texto)

    sinais = [
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
        "conclusao",
    ]

    return any(
        sinal in t
        for sinal in sinais
    )


def tem_ano_alvo(
    texto
):

    t = normalizar(texto)

    return (
        "2025" in t
        or
        "2026" in t
    )


# ============================================================
# PROCESSAR RESULTADO COMPLEMENTAR
# ============================================================

def processar_resultado_web(
    resultado,
    faculdade,
    contexto
):

    stats["resultados"] += 1

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

    tipo, perfil = identificar_perfil(
        url
    )

    if not tipo:
        return False

    texto = (
        f"{titulo} "
        f"{corpo}"
    )

    # ---------------------------------------
    # PRECISA SER NUTRIÇÃO
    # ---------------------------------------

    if not tem_nutricao(
        texto
    ):

        stats["rejeitados"] += 1

        return False

    # ---------------------------------------
    # PRECISA SER MACKENZIE
    # ---------------------------------------

    if not tem_mackenzie(
        texto
    ):

        stats["rejeitados"] += 1

        return False

    # ---------------------------------------
    # PRECISA PROVAR 2025/2026
    # OU ETAPA FINAL DO CURSO
    # ---------------------------------------

    if not (
        tem_ano_alvo(texto)
        or
        tem_fase_final(texto)
    ):

        stats["rejeitados"] += 1

        return False

    nome = extrair_nome_resultado(
        titulo
    )

    if not nome_parece_pessoa(
        nome
    ):

        stats["rejeitados"] += 1

        return False

    chave = (
        normalizar(nome)
        + "|"
        + faculdade["sigla"]
    )

    if chave in vistos:
        return False

    vistos.add(chave)

    linkedin = None
    instagram = None

    if tipo == "linkedin":
        linkedin = perfil

    elif tipo == "instagram":
        instagram = perfil

    stats["validos"] += 1

    return salvar_lead(

        nome=nome,

        faculdade=faculdade,

        ano=contexto["ano"],

        fase=contexto["fase"],

        fonte_url=url,

        fonte_validacao=
            contexto["q"],

        origem=
            "busca_web_complementar",

        linkedin=
            linkedin,

        instagram=
            instagram
    )


# ============================================================
# EXECUÇÃO
# ============================================================

def executar():

    indice = obter_indice()

    if indice >= len(FACULDADES):

        print(
            "✅ Lista concluída."
        )

        return

    faculdade = FACULDADES[
        indice
    ]

    print("")
    print(
        "=" * 60
    )

    print(
        f"🏫 {faculdade['nome']}"
    )

    print(
        f"📍 {faculdade['cidade']}/"
        f"{faculdade['estado']}"
    )

    print("")
    print(
        "VARREDURA:"
    )

    print(
        "1. Fonte oficial"
    )

    print(
        "2. 7º semestre/período"
    )

    print(
        "3. 8º semestre/período"
    )

    print(
        "4. TCC"
    )

    print(
        "5. Estágio"
    )

    print(
        "6. Formandos 2026"
    )

    print(
        "7. Formados 2025"
    )

    print("")
    print(
        "💾 Achou lead válido = salva na hora"
    )

    print(
        "=" * 60
    )

    salvar_checkpoint(
        indice,
        faculdade,
        "processando"
    )

    # ========================================================
    # FONTE OFICIAL
    # ========================================================

    processar_fontes_oficiais(
        faculdade
    )

    # ========================================================
    # COMPLEMENTAÇÃO
    # ========================================================

    novos_antes = stats["salvos"]

    with DDGS() as ddgs:

        for contexto in (
            consultas_complementares(
                faculdade
            )
        ):

            resultados = pesquisar(
                ddgs,
                contexto["q"]
            )

            for resultado in resultados:

                processar_resultado_web(
                    resultado,
                    faculdade,
                    contexto
                )

            pausa()

    novos_complementares = (
        stats["salvos"]
        - novos_antes
    )

    print("")
    print(
        "=" * 60
    )

    print(
        "✅ VARREDURA DA FACULDADE CONCLUÍDA"
    )

    print(
        f"Novos leads complementares: "
        f"{novos_complementares}"
    )

    print(
        "=" * 60
    )

    # ========================================================
    # PRÓXIMA FACULDADE
    # ========================================================

    proximo = indice + 1

    salvar_checkpoint(
        proximo,
        faculdade,
        "pendente"
    )

    if proximo < len(FACULDADES):

        print(
            f"Próxima execução: "
            f"{FACULDADES[proximo]['nome']}"
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    executar()

    print("")
    print(
        "=" * 60
    )

    print(
        "RESUMO"
    )

    print(
        "=" * 60
    )

    print(
        f"Fontes oficiais: "
        f"{stats['fontes_oficiais']}"
    )

    print(
        f"Nomes oficiais encontrados: "
        f"{stats['nomes_oficiais']}"
    )

    print(
        f"Buscas complementares: "
        f"{stats['buscas']}"
    )

    print(
        f"Resultados analisados: "
        f"{stats['resultados']}"
    )

    print(
        f"Leads web válidos: "
        f"{stats['validos']}"
    )

    print(
        f"Novos leads salvos: "
        f"{stats['salvos']}"
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
        "=" * 60
    )
