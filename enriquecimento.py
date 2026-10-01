import os
import re
import time
import random
import unicodedata
from urllib.parse import urlparse

from ddgs import DDGS
from supabase import create_client


print("🚀 MÁQUINA 2 - ENRIQUECIMENTO DE CONTATOS", flush=True)


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

LIMITE_POR_EXECUCAO = 25

PAUSA_MIN = 2
PAUSA_MAX = 4

MAX_RESULTADOS = 10


stats = {
    "pendentes": 0,
    "processados": 0,
    "instagram_encontrado": 0,
    "instagram_repetido": 0,
    "linkedin_encontrado": 0,
    "sem_contato": 0,
    "erros": 0,
}


# ============================================================
# UTILIDADES
# ============================================================

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


def pausa():

    time.sleep(
        random.uniform(
            PAUSA_MIN,
            PAUSA_MAX
        )
    )


# ============================================================
# PEGAR LEADS SEM INSTAGRAM
# ============================================================

def buscar_pendentes():

    print("")
    print(
        "📥 Buscando leads sem Instagram no Supabase...",
        flush=True
    )

    try:

        resposta = (
            supabase
            .table("leds")
            .select(
                "id,nome,instagram,linkedin,whatsapp,"
                "instituicao,cidade,estado,ano_alvo,"
                "periodo_alvo,proxima_acao,qualificado"
            )
            .eq(
                "qualificado",
                True
            )
            .is_(
                "instagram",
                "null"
            )
            .limit(
                LIMITE_POR_EXECUCAO
            )
            .execute()
        )

        leads = resposta.data or []

        stats["pendentes"] = len(
            leads
        )

        print(
            f"📋 Pendentes encontrados: {len(leads)}",
            flush=True
        )

        return leads

    except Exception as erro:

        print(
            f"❌ Erro lendo Supabase: {erro}",
            flush=True
        )

        stats["erros"] += 1

        return []


# ============================================================
# EXTRAIR INSTAGRAM DE URL
# ============================================================

def extrair_instagram_url(url):

    if not url:
        return None

    try:

        parsed = urlparse(
            url
        )

        host = (
            parsed
            .netloc
            .lower()
        )

        if "instagram.com" not in host:
            return None

        caminho = (
            parsed
            .path
            .strip("/")
        )

        if not caminho:
            return None

        usuario = (
            caminho
            .split("/")[0]
            .strip()
        )

        proibidos = [
            "p",
            "reel",
            "reels",
            "stories",
            "explore",
            "accounts",
            "about",
            "developer",
            "directory",
        ]

        if usuario.lower() in proibidos:
            return None

        if len(usuario) < 2:
            return None

        return f"@{usuario}"

    except Exception:

        return None


# ============================================================
# NORMALIZAR INSTAGRAM
# ============================================================

def normalizar_instagram(handle):

    if not handle:
        return None

    handle = handle.strip()

    if not handle.startswith("@"):
        handle = f"@{handle}"

    return handle.lower()


# ============================================================
# VERIFICAR INSTAGRAM REPETIDO
# ============================================================

def instagram_ja_usado(
    handle,
    lead_id
):

    handle = normalizar_instagram(
        handle
    )

    if not handle:
        return False

    try:

        resposta = (
            supabase
            .table("leds")
            .select(
                "id,nome,instagram"
            )
            .ilike(
                "instagram",
                handle
            )
            .limit(10)
            .execute()
        )

        registros = resposta.data or []

        for registro in registros:

            if registro["id"] == lead_id:
                continue

            print(
                f"      ⚠️ {handle} já está associado a "
                f"{registro.get('nome')}",
                flush=True
            )

            return True

        return False

    except Exception as erro:

        print(
            f"      ⚠️ Falha verificando Instagram repetido: {erro}",
            flush=True
        )

        stats["erros"] += 1

        return False


# ============================================================
# BUSCAS PARA INSTAGRAM
# ============================================================

def montar_consultas_instagram(lead):

    nome = (
        lead.get("nome")
        or ""
    ).strip()

    instituicao = (
        lead.get("instituicao")
        or ""
    ).strip()

    cidade = (
        lead.get("cidade")
        or ""
    ).strip()

    ano = lead.get(
        "ano_alvo"
    )

    consultas = [

        f'"{nome}" Instagram',

        f'"{nome}" Nutrição Instagram',

        f'"{nome}" nutricionista Instagram',

        f'"{nome}" site:instagram.com',
    ]

    if instituicao:

        consultas.append(
            f'"{nome}" "{instituicao}" Instagram'
        )

    if cidade:

        consultas.append(
            f'"{nome}" Nutrição "{cidade}" Instagram'
        )

    if ano:

        consultas.append(
            f'"{nome}" Nutrição "{ano}" Instagram'
        )

    return consultas


# ============================================================
# BUSCAR INSTAGRAM
# ============================================================

def buscar_instagram(
    ddgs,
    lead
):

    nome = lead["nome"]

    consultas = montar_consultas_instagram(
        lead
    )

    for consulta in consultas:

        print(
            f"      🔎 {consulta}",
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

            url = (
                resultado.get("href")
                or resultado.get("url")
                or ""
            )

            handle = extrair_instagram_url(
                url
            )

            if not handle:
                continue

            if instagram_ja_usado(
                handle,
                lead["id"]
            ):

                stats[
                    "instagram_repetido"
                ] += 1

                continue

            print(
                f"      📸 Instagram candidato para "
                f"{nome}: {handle}",
                flush=True
            )

            return handle

        pausa()

    return None


# ============================================================
# BUSCAR INSTAGRAM CITADO EM OUTRAS PÁGINAS
# ============================================================

def buscar_handle_em_texto(
    ddgs,
    lead
):

    nome = lead["nome"]

    consultas = [

        f'"{nome}" Instagram Nutrição',

        f'"{nome}" "instagram.com/" Nutrição',

        f'"{nome}" LinkedIn Instagram Nutrição',
    ]

    padroes = [

        r"instagram\.com/([A-Za-z0-9._]+)",

        r"@([A-Za-z0-9._]{3,30})",
    ]

    for consulta in consultas:

        try:

            resultados = list(
                ddgs.text(
                    consulta,
                    max_results=8
                )
            )

        except Exception:

            continue

        for resultado in resultados:

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
            )

            for padrao in padroes:

                encontrados = re.findall(
                    padrao,
                    texto,
                    flags=re.I
                )

                for usuario in encontrados:

                    handle = (
                        f"@{usuario}"
                        .replace("@@", "@")
                    )

                    if instagram_ja_usado(
                        handle,
                        lead["id"]
                    ):

                        stats[
                            "instagram_repetido"
                        ] += 1

                        continue

                    return handle

        pausa()

    return None


# ============================================================
# LINKEDIN COMO APOIO
# ============================================================

def buscar_linkedin(
    ddgs,
    lead
):

    nome = lead["nome"]

    instituicao = (
        lead.get("instituicao")
        or ""
    )

    consultas = [

        f'"{nome}" Nutrição LinkedIn',

        f'"{nome}" site:linkedin.com/in',
    ]

    if instituicao:

        consultas.insert(
            0,
            f'"{nome}" "{instituicao}" LinkedIn'
        )

    for consulta in consultas:

        try:

            resultados = list(
                ddgs.text(
                    consulta,
                    max_results=8
                )
            )

        except Exception:

            continue

        for resultado in resultados:

            url = (
                resultado.get("href")
                or resultado.get("url")
                or ""
            )

            if (
                "linkedin.com/in/"
                not in url.lower()
            ):
                continue

            print(
                f"      💼 LinkedIn encontrado: {url}",
                flush=True
            )

            return url

        pausa()

    return None


# ============================================================
# ATUALIZAR LEAD
# ============================================================

def atualizar_lead(
    lead_id,
    instagram=None,
    linkedin=None
):

    dados = {}

    if instagram:

        dados[
            "instagram"
        ] = normalizar_instagram(
            instagram
        )

        dados[
            "proxima_acao"
        ] = "primeiro_contato_instagram"

    if linkedin:

        dados[
            "linkedin"
        ] = linkedin

    if (
        not instagram
        and not linkedin
    ):

        dados[
            "proxima_acao"
        ] = "buscar_instagram"

    if not dados:
        return

    try:

        (
            supabase
            .table("leds")
            .update(
                dados
            )
            .eq(
                "id",
                lead_id
            )
            .execute()
        )

    except Exception as erro:

        print(
            f"      ❌ Erro atualizando Supabase: {erro}",
            flush=True
        )

        stats["erros"] += 1


# ============================================================
# PROCESSAR UM LEAD
# ============================================================

def processar_lead(
    ddgs,
    lead
):

    nome = lead.get(
        "nome",
        "Sem nome"
    )

    print("")
    print(
        "=" * 65,
        flush=True
    )

    print(
        f"👤 {nome}",
        flush=True
    )

    print(
        f"   Faculdade: "
        f"{lead.get('instituicao') or 'não informada'}",
        flush=True
    )

    print(
        f"   Ano: "
        f"{lead.get('ano_alvo') or 'não informado'}",
        flush=True
    )

    print(
        f"   Situação: "
        f"{lead.get('periodo_alvo') or 'não informada'}",
        flush=True
    )

    stats[
        "processados"
    ] += 1

    # ========================================================
    # 1 - INSTAGRAM DIRETO
    # ========================================================

    instagram = buscar_instagram(
        ddgs,
        lead
    )

    if instagram:

        stats[
            "instagram_encontrado"
        ] += 1

        atualizar_lead(
            lead["id"],
            instagram=instagram
        )

        print(
            f"   ✅ SALVO NO SUPABASE: {instagram}",
            flush=True
        )

        return

    # ========================================================
    # 2 - INSTAGRAM CITADO EM OUTRAS PÁGINAS
    # ========================================================

    instagram = buscar_handle_em_texto(
        ddgs,
        lead
    )

    if instagram:

        stats[
            "instagram_encontrado"
        ] += 1

        atualizar_lead(
            lead["id"],
            instagram=instagram
        )

        print(
            f"   ✅ SALVO NO SUPABASE: {instagram}",
            flush=True
        )

        return

    # ========================================================
    # 3 - LINKEDIN COMO APOIO
    # ========================================================

    linkedin = buscar_linkedin(
        ddgs,
        lead
    )

    if linkedin:

        stats[
            "linkedin_encontrado"
        ] += 1

        atualizar_lead(
            lead["id"],
            linkedin=linkedin
        )

        print(
            "   ✅ LinkedIn salvo como fonte auxiliar",
            flush=True
        )

    else:

        atualizar_lead(
            lead["id"]
        )

        stats[
            "sem_contato"
        ] += 1

        print(
            "   ⏳ Continua pendente de contato",
            flush=True
        )


# ============================================================
# EXECUÇÃO
# ============================================================

def executar():

    print("")
    print(
        "=" * 65,
        flush=True
    )

    print(
        "MÁQUINA 2 - ENRIQUECIMENTO",
        flush=True
    )

    print(
        "INSTAGRAM PRIORITÁRIO + LINKEDIN AUXILIAR",
        flush=True
    )

    print(
        "=" * 65,
        flush=True
    )

    leads = buscar_pendentes()

    if not leads:

        print("")
        print(
            "✅ Nenhum lead pendente de Instagram.",
            flush=True
        )

        return

    with DDGS() as ddgs:

        for lead in leads:

            processar_lead(
                ddgs,
                lead
            )

            pausa()

    print("")
    print(
        "=" * 65,
        flush=True
    )

    print(
        "RESUMO DO ENRIQUECIMENTO",
        flush=True
    )

    print(
        "=" * 65,
        flush=True
    )

    print(
        f"Pendentes carregados: "
        f"{stats['pendentes']}",
        flush=True
    )

    print(
        f"Processados: "
        f"{stats['processados']}",
        flush=True
    )

    print(
        f"Instagram encontrados: "
        f"{stats['instagram_encontrado']}",
        flush=True
    )

    print(
        f"Instagram repetidos descartados: "
        f"{stats['instagram_repetido']}",
        flush=True
    )

    print(
        f"LinkedIn encontrados: "
        f"{stats['linkedin_encontrado']}",
        flush=True
    )

    print(
        f"Continuam sem contato: "
        f"{stats['sem_contato']}",
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
        "✅ MÁQUINA 2 FINALIZADA",
        flush=True
    )
