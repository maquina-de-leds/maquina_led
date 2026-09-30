import os
import re
import time
from urllib.parse import urlparse

from ddgs import DDGS
from supabase import create_client


# =========================================================
# CONFIGURAÇÃO
# =========================================================

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

CIDADES = [
    "Itu",
    "Sorocaba",
    "Indaiatuba",
    "Salto",
]

ESTADO = "SP"

# Pontuação mínima para o candidato entrar no banco
PONTUACAO_MINIMA_PARA_SALVAR = 5

# Pontuação mínima para já entrar como qualificado
PONTUACAO_PARA_QUALIFICAR = 8


salvos = 0
duplicados = 0
ignorados = 0
erros = 0
qualificados = 0


# =========================================================
# FUNÇÕES BÁSICAS
# =========================================================

def normalizar_instagram(instagram):
    if not instagram:
        return None

    instagram = instagram.strip().lower()

    if not instagram.startswith("@"):
        instagram = f"@{instagram}"

    return instagram


def extrair_usuario_instagram(url):
    try:
        if not url:
            return None

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
            "direct",
            "tv",
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
        print(f"Erro ao verificar duplicidade de {instagram}: {e}")
        return False


# =========================================================
# QUALIFICAÇÃO
# =========================================================

def calcular_pontuacao(texto, cidade):
    if not texto:
        return 0

    texto = texto.lower()
    pontos = 0

    # -----------------------------------------------------
    # PROFISSÃO / CURSO
    # -----------------------------------------------------

    if "nutricionista" in texto:
        pontos += 3

    if "nutrição" in texto or "nutricao" in texto:
        pontos += 2

    # -----------------------------------------------------
    # FORMAÇÃO RECENTE
    # -----------------------------------------------------

    termos_formacao_recente = [
        "recém formada",
        "recem formada",
        "recém formado",
        "recem formado",
        "recém-formada",
        "recem-formada",
        "recém-formado",
        "recem-formado",
        "formanda",
        "formando",
        "concluinte",
    ]

    for termo in termos_formacao_recente:
        if termo in texto:
            pontos += 4
            break

    # -----------------------------------------------------
    # ÚLTIMOS PERÍODOS
    # -----------------------------------------------------

    termos_ultimo_periodo = [
        "8/8",
        "7/8",
        "8 de 8",
        "7 de 8",
        "8º período",
        "8° período",
        "8 periodo",
        "8º periodo",
        "7º período",
        "7° período",
        "7 periodo",
        "7º periodo",
        "último período",
        "ultimo periodo",
        "último semestre",
        "ultimo semestre",
        "último ano",
        "ultimo ano",
    ]

    for termo in termos_ultimo_periodo:
        if termo in texto:
            pontos += 4
            break

    # -----------------------------------------------------
    # SINAIS DE CONCLUSÃO
    # -----------------------------------------------------

    termos_conclusao = [
        "tcc",
        "trabalho de conclusão",
        "trabalho de conclusao",
        "colação",
        "colacao",
        "colação de grau",
        "colacao de grau",
        "formatura",
    ]

    for termo in termos_conclusao:
        if termo in texto:
            pontos += 2
            break

    # -----------------------------------------------------
    # ANO
    # -----------------------------------------------------

    if "2025" in texto:
        pontos += 3

    if "2026" in texto:
        pontos += 3

    # -----------------------------------------------------
    # REGISTRO PROFISSIONAL
    # -----------------------------------------------------

    if "crn" in texto:
        pontos += 2

    # -----------------------------------------------------
    # SINAIS DE INÍCIO DE ATENDIMENTO
    # -----------------------------------------------------

    termos_atendimento = [
        "agenda aberta",
        "agenda disponível",
        "agenda disponivel",
        "atendimentos",
        "consultas",
        "atendimento online",
        "atendimento presencial",
        "começando os atendimentos",
        "iniciando atendimentos",
    ]

    for termo in termos_atendimento:
        if termo in texto:
            pontos += 1
            break

    # -----------------------------------------------------
    # CIDADE
    # -----------------------------------------------------

    if cidade.lower() in texto:
        pontos += 2

    # -----------------------------------------------------
    # PENALIZAÇÕES
    # -----------------------------------------------------

    termos_institucionais = [
        "faculdade",
        "universidade",
        "centro universitário",
        "centro universitario",
        "clínica",
        "clinica",
        "hospital",
        "empresa",
        "oficial",
        "fotografia",
        "agência",
        "agencia",
        "vestibular",
        "curso técnico",
        "curso tecnico",
    ]

    for termo in termos_institucionais:
        if termo in texto:
            pontos -= 5

    return pontos


# =========================================================
# EXTRAÇÃO DE NOME
# =========================================================

def limpar_nome(titulo, instagram):
    if titulo:
        nome = titulo.strip()

        nome = re.sub(
            r"\s*[\|\-–]\s*Instagram.*$",
            "",
            nome,
            flags=re.IGNORECASE
        )

        nome = nome.strip()

        if nome:
            return nome[:150]

    if instagram:
        return instagram.replace("@", "")[:150]

    return "Sem nome"


# =========================================================
# SALVAR NO SUPABASE
# =========================================================

def salvar_lead(lead):
    global salvos
    global duplicados
    global ignorados
    global erros
    global qualificados

    instagram = normalizar_instagram(lead.get("instagram"))

    if not instagram:
        ignorados += 1
        return

    lead["instagram"] = instagram

    try:
        if lead_ja_existe(instagram):
            print(f"Duplicado ignorado: {instagram}")
            duplicados += 1
            return

        supabase.table("leds").insert(lead).execute()

        print(
            f"Lead salvo: {instagram} | "
            f"qualificado={lead.get('qualificado')}"
        )

        salvos += 1

        if lead.get("qualificado"):
            qualificados += 1

    except Exception as e:
        print(f"Erro ao salvar {instagram}: {e}")
        erros += 1


# =========================================================
# PESQUISAS
# =========================================================

def montar_pesquisas(cidade):
    return [
        # -------------------------------------------------
        # INSTAGRAM
        # -------------------------------------------------

        f'site:instagram.com nutricionista "{cidade}" "2026"',
        f'site:instagram.com nutricionista "{cidade}" "2025"',
        f'site:instagram.com nutricionista "{cidade}" "formanda"',
        f'site:instagram.com nutricionista "{cidade}" "concluinte"',
        f'site:instagram.com nutricionista "{cidade}" "recém formada"',
        f'site:instagram.com "nutrição" "{cidade}" "formanda"',
        f'site:instagram.com "nutrição" "{cidade}" "CRN"',

        # Últimos períodos
        f'site:instagram.com "nutrição" "{cidade}" "8/8"',
        f'site:instagram.com "nutrição" "{cidade}" "7/8"',
        f'site:instagram.com "nutrição" "{cidade}" "8º período"',
        f'site:instagram.com "nutrição" "{cidade}" "7º período"',
        f'site:instagram.com "nutrição" "{cidade}" "último período"',
        f'site:instagram.com "nutrição" "{cidade}" "último semestre"',

        # Conclusão
        f'site:instagram.com "nutrição" "{cidade}" "TCC"',
        f'site:instagram.com "nutrição" "{cidade}" "formatura 2026"',
        f'site:instagram.com "nutrição" "{cidade}" "formatura 2025"',

        # -------------------------------------------------
        # LINKEDIN
        # -------------------------------------------------

        f'site:linkedin.com/in nutricionista "{cidade}" "2026"',
        f'site:linkedin.com/in nutricionista "{cidade}" "2025"',
        f'site:linkedin.com/in "nutrição" "{cidade}" "formanda"',
        f'site:linkedin.com/in "nutrição" "{cidade}" "concluinte"',
        f'site:linkedin.com/in "nutrição" "{cidade}" "último período"',
        f'site:linkedin.com/in "nutrição" "{cidade}" "último semestre"',
        f'site:linkedin.com/in "nutrição" "{cidade}" "TCC"',

        # -------------------------------------------------
        # FACULDADES / FORMATURAS
        # -------------------------------------------------

        f'"nutrição" "{cidade}" "formandos 2026"',
        f'"nutrição" "{cidade}" "formandos 2025"',
        f'"nutrição" "{cidade}" "colação de grau"',
        f'"nutrição" "{cidade}" "formatura 2026"',
        f'"nutrição" "{cidade}" "formatura 2025"',
        f'"curso de nutrição" "{cidade}" "formandos"',
        f'"curso de nutrição" "{cidade}" "concluintes"',

        # -------------------------------------------------
        # BUSCAS ABERTAS
        # -------------------------------------------------

        f'nutricionista recém formada "{cidade}"',
        f'nutricionista formanda "{cidade}"',
        f'nutricionista concluinte "{cidade}"',
        f'nutricionista "8/8" "{cidade}"',
        f'nutricionista "7/8" "{cidade}"',
        f'nutricionista "último período" "{cidade}"',
        f'nutricionista "último semestre" "{cidade}"',
        f'nutricionista 2026 "{cidade}" Instagram',
        f'nutricionista 2025 "{cidade}" Instagram',
    ]


# =========================================================
# BUSCAR INSTAGRAM PELO NOME
# =========================================================

def buscar_instagram_por_nome(ddgs, nome, cidade):
    if not nome:
        return None

    consulta = (
        f'site:instagram.com "{nome}" '
        f'nutricionista "{cidade}"'
    )

    try:
        resultados = ddgs.text(
            consulta,
            max_results=8
        )

        for resultado in resultados:
            url = resultado.get("href") or resultado.get("url")

            instagram = extrair_usuario_instagram(url)

            if instagram:
                return instagram

    except Exception:
        return None

    return None


# =========================================================
# BUSCA PRINCIPAL
# =========================================================

def buscar_leads():
    encontrados = {}

    with DDGS() as ddgs:

        for cidade in CIDADES:

            print("")
            print("==========================================")
            print(f"INICIANDO CIDADE: {cidade} - {ESTADO}")
            print("==========================================")

            pesquisas = montar_pesquisas(cidade)

            for numero, pesquisa in enumerate(pesquisas, start=1):

                print(
                    f"[{cidade}] Pesquisa "
                    f"{numero}/{len(pesquisas)}: {pesquisa}"
                )

                try:
                    resultados = ddgs.text(
                        pesquisa,
                        max_results=25
                    )

                    for resultado in resultados:

                        url = (
                            resultado.get("href")
                            or resultado.get("url")
                            or ""
                        )

                        titulo = resultado.get("title", "") or ""
                        descricao = resultado.get("body", "") or ""

                        texto_completo = (
                            f"{titulo} {descricao} {url}"
                        )

                        pontuacao = calcular_pontuacao(
                            texto_completo,
                            cidade
                        )

                        # Resultado fraco não entra
                        if pontuacao < PONTUACAO_MINIMA_PARA_SALVAR:
                            continue

                        instagram = extrair_usuario_instagram(url)

                        # Se veio de LinkedIn, faculdade ou outro site,
                        # tenta encontrar o Instagram dessa pessoa.
                        if not instagram:

                            nome_para_busca = titulo

                            if nome_para_busca:
                                nome_para_busca = re.sub(
                                    r"\s*[\|\-–].*$",
                                    "",
                                    nome_para_busca
                                ).strip()

                            instagram = buscar_instagram_por_nome(
                                ddgs,
                                nome_para_busca,
                                cidade
                            )

                        if not instagram:
                            continue

                        if instagram in encontrados:
                            continue

                        nome = limpar_nome(
                            titulo,
                            instagram
                        )

                        qualificado = (
                            pontuacao >= PONTUACAO_PARA_QUALIFICAR
                        )

                        origem = "busca_web"

                        if "linkedin.com" in url.lower():
                            origem = "linkedin_busca_web"

                        elif "instagram.com" in url.lower():
                            origem = "instagram_busca_web"

                        elif (
                            "faculdade" in texto_completo.lower()
                            or "universidade" in texto_completo.lower()
                            or "formandos" in texto_completo.lower()
                            or "formatura" in texto_completo.lower()
                            or "colação" in texto_completo.lower()
                        ):
                            origem = "faculdade_formandos_web"

                        encontrados[instagram] = {
                            "nome": nome,
                            "instagram": instagram,
                            "whatsapp": None,
                            "nicho": "nutricionista",
                            "origem": origem,
                            "status": "novo",

                            "app_baixado": False,
                            "nao_contatar": False,
                            "qualificado": qualificado,
                            "cliente": False,

                            "tentativas_contato": 0,

                            "data_primeiro_contato": None,
                            "data_ultimo_contato": None,
                            "proxima_acao": None,
                            "funil_destino": None,
                        }

                        print(
                            f"  Candidato: {instagram} | "
                            f"pontos={pontuacao} | "
                            f"qualificado={qualificado}"
                        )

                except Exception as e:
                    print(
                        f"Erro na pesquisa "
                        f"'{pesquisa}': {e}"
                    )

                time.sleep(1)

            print(f"Busca de {cidade} concluída.")

    return list(encontrados.values())


# =========================================================
# EXECUÇÃO
# =========================================================

print("")
print("==========================================")
print("MÁQUINA DE LEADS - INICIANDO")
print("==========================================")

leads_encontrados = buscar_leads()

print("")
print(
    f"Perfis candidatos encontrados nesta execução: "
    f"{len(leads_encontrados)}"
)

for lead in leads_encontrados:
    salvar_lead(lead)


print("")
print("==========================================")
print("RESUMO FINAL")
print("==========================================")
print(f"Candidatos encontrados: {len(leads_encontrados)}")
print(f"Leads novos salvos: {salvos}")
print(f"Novos qualificados: {qualificados}")
print(f"Duplicados ignorados: {duplicados}")
print(f"Ignorados: {ignorados}")
print(f"Erros: {erros}")
print("==========================================")
print("Processamento concluído.")
