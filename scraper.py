import os
import re
from urllib.parse import urlparse

from ddgs import DDGS
from supabase import create_client


SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

salvos = 0
duplicados = 0
ignorados = 0
erros = 0


def normalizar_instagram(instagram):
    if not instagram:
        return None

    instagram = instagram.strip().lower()

    if not instagram.startswith("@"):
        instagram = f"@{instagram}"

    return instagram


def extrair_usuario_instagram(url):
    try:
        parsed = urlparse(url)

        if "instagram.com" not in parsed.netloc.lower():
            return None

        partes = [p for p in parsed.path.split("/") if p]

        if not partes:
            return None

        bloqueados = {
            "p",
            "reel",
            "reels",
            "explore",
            "stories",
            "accounts",
            "direct"
        }

        usuario = partes[0].lower()

        if usuario in bloqueados:
            return None

        if not re.match(r"^[a-zA-Z0-9._]+$", usuario):
            return None

        return normalizar_instagram(usuario)

    except Exception:
        return None


def lead_ja_existe(instagram):
    try:
        resposta = (
            supabase
            .table("leds")
            .select("id, instagram")
            .eq("instagram", instagram)
            .limit(1)
            .execute()
        )

        return len(resposta.data) > 0

    except Exception as e:
        print(f"Erro ao verificar {instagram}: {e}")
        return False


def salvar_lead(lead):
    global salvos, duplicados, ignorados, erros

    instagram = normalizar_instagram(lead.get("instagram"))

    if not instagram:
        print("Lead ignorado: sem Instagram.")
        ignorados += 1
        return

    lead["instagram"] = instagram

    try:
        if lead_ja_existe(instagram):
            print(f"Duplicado ignorado: {instagram}")
            duplicados += 1
            return

        supabase.table("leds").insert(lead).execute()

        print(f"Lead salvo: {instagram}")
        salvos += 1

    except Exception as e:
        print(f"Erro ao salvar {instagram}: {e}")
        erros += 1


def buscar_leads():
    pesquisas = [
        'site:instagram.com nutricionista "recém formada"',
        'site:instagram.com nutricionista "recém formado"',
        'site:instagram.com nutricionista "formanda"',
        'site:instagram.com nutricionista "formando"',
        'site:instagram.com nutricionista "2026"',
        'site:instagram.com nutricionista "2025"',
        'site:instagram.com "nutrição" "Itu"',
        'site:instagram.com "nutrição" "Salto"',
        'site:instagram.com "nutrição" "Indaiatuba"',
        'site:instagram.com "nutrição" "Sorocaba"'
    ]

    encontrados = {}

    with DDGS() as ddgs:
        for pesquisa in pesquisas:
            print(f"Pesquisando: {pesquisa}")

            try:
                resultados = ddgs.text(
                    pesquisa,
                    max_results=20
                )

                for resultado in resultados:
                    url = resultado.get("href") or resultado.get("url")
                    titulo = resultado.get("title", "")
                    descricao = resultado.get("body", "")

                    instagram = extrair_usuario_instagram(url)

                    if not instagram:
                        continue

                    if instagram in encontrados:
                        continue

                    nome = titulo.strip()

                    if not nome:
                        nome = instagram.replace("@", "")

                    encontrados[instagram] = {
                        "nome": nome[:150],
                        "instagram": instagram,
                        "whatsapp": None,
                        "nicho": "nutricionista",
                        "origem": "busca_web",
                        "status": "novo",
                        "app_baixado": False
                    }

            except Exception as e:
                print(f"Erro na pesquisa '{pesquisa}': {e}")

    return list(encontrados.values())


print("Iniciando busca de leads...")

leads_encontrados = buscar_leads()

print(f"Perfis encontrados nesta execução: {len(leads_encontrados)}")

for lead in leads_encontrados:
    salvar_lead(lead)

print("")
print("===== RESUMO =====")
print(f"Encontrados: {len(leads_encontrados)}")
print(f"Leads salvos: {salvos}")
print(f"Duplicados ignorados: {duplicados}")
print(f"Ignorados: {ignorados}")
print(f"Erros: {erros}")
print("==================")
print("Processamento concluido.")
