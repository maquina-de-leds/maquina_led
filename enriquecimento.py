import os
import re
import time
import random
import signal
from datetime import datetime, timezone, timedelta
import unicodedata
from urllib.parse import urlparse
from fontes_academicas import url_permitida



# ============================================================
# SUPABASE
# ============================================================

class JanelaEncerrada(BaseException):
    """Prazo do lote; não pode ser absorvido pelos retries de rede."""


supabase = None


def conectar_banco():
    from supabase import create_client
    return create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])


# ============================================================
# CONFIGURAÇÃO
# ============================================================

LIMITE_CANDIDATOS_POR_EXECUCAO = 50
LIMITE_LEADS_POR_EXECUCAO = 50
# Sem espera de dias entre execuções: o cursor mantém a ordem da fila.
# Pausas de rede, deduplicação e limites por execução continuam ativos.
INTERVALO_REBUSCA_DIAS = 0

PAUSA_MIN = 2
PAUSA_MAX = 4

MAX_RESULTADOS = 10
ETAPA_CURSOR_M2 = "m2_enriquecimento_cursor_v1"
ETAPA_VERIFICACAO_M2_PREFIX = "m2-verificado-lead:"


stats = {
    "pendentes": 0,
    "processados": 0,
    "ignorados_nao_pessoa": 0,
    "instagram_encontrado": 0,
    "instagram_repetido": 0,
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
# VERIFICAR SE PARECE NOME DE PESSOA
# ============================================================

def parece_pessoa(nome):

    if not nome:
        return False

    nome = re.sub(
        r"\s+",
        " ",
        nome
    ).strip()

    if len(nome) < 7:
        return False

    if len(nome) > 90:
        return False

    partes = nome.split()

    if len(partes) < 2:
        return False

    texto = normalizar(
        nome
    )

    termos_institucionais = [
        "vestibular",
        "encontro cientifico",
        "universidade",
        "faculdade",
        "campus",
        "ead",
        "evento",
        "palestra",
        "congresso",
        "seminario",
        "curso",
        "turma",
        "colegio",
        "instituto",
        "centro universitario",
        "programa",
        "pos graduacao",
        "pos-graduacao",
        "secretaria",
        "reitoria",
        "qnn ",
        "lote ",
        "conjunto ",
    ]

    for termo in termos_institucionais:

        if termo in texto:
            return False

    # muitos números = provavelmente não é pessoa
    quantidade_numeros = len(
        re.findall(
            r"\d",
            nome
        )
    )

    if quantidade_numeros >= 2:
        return False

    return True


# ============================================================
# PRESERVAR REGISTROS EXISTENTES
# ============================================================

def marcar_como_b2b(lead):
    """Ignora registros que não parecem pessoas sem editar a tabela leds."""
    print("   Registro ignorado para revisão; lead de origem preservado", flush=True)
    return False


# ============================================================
# FILTRO DE ENRIQUECIMENTO
# ============================================================

def lead_apto_para_enriquecimento(lead):
    """Impede que a Máquina 2 pesquise instituições, cursos ou outros nichos."""
    nome = str(lead.get("nome") or "")
    # Instituição, cidade, estado e fonte descrevem o vínculo do lead;
    # não devem fazê-lo parecer uma instituição em vez de uma pessoa.
    contexto = normalizar(" ".join(
        str(lead.get(campo) or "")
        for campo in ("nome", "nicho")
    ))
    bloqueados = (
        "engenheiro agronomo", "engenharia agronomica", "agronomo",
        "fisioterapia", "fisioterapeuta", "psicologia", "psicologo",
        "odontologia", "dentista", "farmacia", "veterinaria",
        "teste automacao", "teste crm", "google docs", "vestibular",
        "encontro cientifico", "vaga emprego", "pos ead",
        "centro universitario", "universidade", "faculdade", "unilehu",
        "jupiterweb", "portalservicos", "portal", "usp.br", ".com", ".br"
    )
    if re.search(r"[.@]|https?://|www\\.", nome, flags=re.I):
        return False
    if not parece_pessoa(nome):
        return False
    if any(termo in contexto for termo in bloqueados):
        return False
    return True


# ============================================================
# PEGAR LEADS SEM INSTAGRAM
# ============================================================

def obter_cursor_m2():
    resposta = (supabase.table("controle_busca").select("indice_pesquisa")
                .eq("etapa", ETAPA_CURSOR_M2).limit(1).execute())
    if not resposta.data:
        return 0
    return max(0, int(resposta.data[0].get("indice_pesquisa") or 0))


def salvar_cursor_m2(lead_id):
    agora_iso = datetime.now(timezone.utc).isoformat()
    resposta = (supabase.table("controle_busca").select("id")
                .eq("etapa", ETAPA_CURSOR_M2).limit(1).execute())
    dados = {
        "estado": "BR", "cidade": "Nacional",
        "instituicao": "Checkpoint da Máquina 2",
        "etapa": ETAPA_CURSOR_M2, "status": "checkpoint",
        "indice_pesquisa": max(0, int(lead_id)),
        "atualizado_em": agora_iso, "ultimo_erro": None,
    }
    if resposta.data:
        (supabase.table("controle_busca").update(dados)
         .eq("id", resposta.data[0]["id"]).execute())
    else:
        dados["iniciado_em"] = agora_iso
        supabase.table("controle_busca").insert(dados).execute()


def ids_verificados_recentemente_m2(agora=None):
    agora = agora or datetime.now(timezone.utc)
    limite = (agora - timedelta(days=INTERVALO_REBUSCA_DIAS)).isoformat()
    resposta = (
        supabase.table("controle_busca")
        .select("etapa")
        .like("etapa", ETAPA_VERIFICACAO_M2_PREFIX + "%")
        .gte("atualizado_em", limite)
        .limit(10000)
        .execute()
    )
    ids = set()
    for registro in resposta.data or []:
        etapa = str(registro.get("etapa") or "")
        sufixo = etapa.removeprefix(ETAPA_VERIFICACAO_M2_PREFIX)
        if sufixo.isdigit():
            ids.add(int(sufixo))
    return ids


def registrar_verificacao_m2(lead):
    """Registra o cooldown da Máquina 2 sem editar o registro original do lead."""
    etapa = f"{ETAPA_VERIFICACAO_M2_PREFIX}{int(lead['id'])}"
    existente = (
        supabase.table("controle_busca")
        .select("id,tentativas")
        .eq("etapa", etapa)
        .limit(1)
        .execute()
    )
    atual = (existente.data or [None])[0]
    agora_iso = datetime.now(timezone.utc).isoformat()
    dados = {
        "estado": "BR",
        "cidade": "Nacional",
        "instituicao": str(lead.get("nome") or f"Lead {lead['id']}")[:250],
        "etapa": etapa,
        "status": "verificado",
        "tentativas": int((atual or {}).get("tentativas") or 0) + 1,
        "atualizado_em": agora_iso,
        "ultimo_erro": None,
    }
    if atual:
        return (
            supabase.table("controle_busca")
            .update(dados)
            .eq("id", atual["id"])
            .execute()
        )
    dados["iniciado_em"] = agora_iso
    return supabase.table("controle_busca").insert(dados).execute()


def filtrar_pendentes_rebusca(consulta, agora=None):
    agora = agora or datetime.now(timezone.utc)
    limite = (agora - timedelta(days=INTERVALO_REBUSCA_DIAS)).isoformat()
    return consulta.or_(f"maquina2_verificado_em.is.null,maquina2_verificado_em.lt.{limite}")


def buscar_pendentes():

    print("")
    print(
        "📥 Buscando leads sem Instagram no Supabase...",
        flush=True
    )

    try:

        cursor = obter_cursor_m2()

        ids_verificados = ids_verificados_recentemente_m2()

        def carregar(cursor_id):
            encontrados = []
            ultimo_id = cursor_id
            while len(encontrados) < LIMITE_LEADS_POR_EXECUCAO:
                consulta = (
                    supabase.table("leds")
                    .select("id,nome,instagram,linkedin,whatsapp,instituicao,cidade,estado,ano_alvo,"
                            "periodo_alvo,proxima_acao,qualificado,nao_contatar,não_contatar,evidencia,fonte_url,"
                            "maquina2_tentativas,maquina2_verificado_em")
                    .eq('nao_contatar', False)
                    .eq('qualificado', True)
                    .is_('instagram', 'null')
                    .order('id')
                )
                consulta = filtrar_pendentes_rebusca(consulta)
                if ultimo_id:
                    consulta = consulta.gt('id', ultimo_id)
                pagina = consulta.limit(100).execute().data or []
                if not pagina:
                    return encontrados, ultimo_id, False
                ultimo_id = int(pagina[-1]['id'])
                encontrados.extend(
                    lead for lead in pagina
                    if int(lead['id']) not in ids_verificados
                    and lead_apto_para_enriquecimento(lead)
                )
                if len(pagina) < 100:
                    return encontrados, ultimo_id, False
            return encontrados[:LIMITE_LEADS_POR_EXECUCAO], ultimo_id, True

        leads, ultimo_id, mais_paginas = carregar(cursor)
        if not leads and cursor:
            print("🔁 Fila M2 chegou ao fim; retomando do primeiro lead", flush=True)
            salvar_cursor_m2(0)
            leads, ultimo_id, mais_paginas = carregar(0)

        if not leads and not mais_paginas and ultimo_id:
            salvar_cursor_m2(0)

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
        raise RuntimeError('Não foi possível carregar a fila de enriquecimento') from erro


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

        if host != "instagram.com" and not host.endswith(".instagram.com"):
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

        candidatos = (
            supabase.table("instagram_candidatos")
            .select("instagram")
            .ilike("instagram", handle)
            .limit(1)
            .execute()
        ).data or []
        if candidatos:
            return True

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

        raise RuntimeError('Não foi possível verificar Instagram duplicado') from erro


# ============================================================
# SALVAR PERFIL COMO CANDIDATO, SEM ALTERAR O LEAD ORIGINAL
# ============================================================
def salvar_candidato(lead, candidato):
    handle = normalizar_instagram(candidato.get("instagram"))
    if not handle or instagram_ja_usado(handle, lead["id"]):
        return False
    perfil = str(candidato.get("nome_perfil") or handle).strip()[:200]
    consulta = str(candidato.get("consulta") or "")[:500]
    fonte_url = str(candidato.get("fonte_url") or "")[:1000]
    resposta = supabase.table("instagram_candidatos").insert({
        "lead_origem_id": lead["id"],
        "nome_pesquisado": lead.get("nome"),
        "nome_perfil": perfil,
        "instagram": handle,
        "instagram_url": f"https://www.instagram.com/{handle.lstrip('@')}/",
        "consulta": consulta,
        "fonte_url": fonte_url,
        "status": "novo",
        "observacao": (
            f"Perfil ligado à Nutrição encontrado ao pesquisar "
            f"'{lead.get('nome')}'. Não confirmado como a mesma pessoa."
        )
    }).execute()
    return bool(resposta.data)


# ============================================================
# MONTAR BUSCAS DO INSTAGRAM
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

def resultado_compativel(resultado, lead=None):
    """Aceita perfil com sinal de Nutrição, nome correspondente ou @ nutricional."""
    texto_original = str(resultado.get("title") or "") + " " + str(resultado.get("body") or "")
    texto = normalizar(texto_original)
    if re.search(r"\b(?:nutricao|nutricionista|nutricional|nutritivo|nutritiva|crn)\b", texto):
        return True

    url = str(resultado.get("href") or resultado.get("url") or "")
    handle = extrair_instagram_url(url)
    if handle and re.search(r"(?:nutri|nutricion|crn)", handle, flags=re.I):
        return True
    if lead and handle:
        nome = normalizar(str(lead.get("nome") or ""))
        alvo = [parte for parte in nome.split() if len(parte) >= 3]
        perfil = normalizar(texto_original + " " + handle.lstrip("@").replace(".", " ").replace("_", " "))
        if len(alvo) >= 2 and all(parte in perfil for parte in alvo):
            return True
    return False


def _perfil_do_resultado(resultado):
    url = str(resultado.get("href") or resultado.get("url") or "")
    handle = extrair_instagram_url(url)
    if not handle:
        texto = str(resultado.get("title") or "") + " " + str(resultado.get("body") or "")
        for usuario in re.findall(
            r"(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9._]+)",
            texto,
            flags=re.I
        ):
            handle = extrair_instagram_url(f"https://www.instagram.com/{usuario}/")
            if handle:
                break
    if not handle:
        return None
    titulo = " ".join(str(resultado.get("title") or "").split()).strip()
    return {
        "instagram": normalizar_instagram(handle),
        "nome_perfil": titulo or handle,
        "fonte_url": url,
    }


def buscar_instagram(ddgs, lead, limite=None):
    """Busca vários perfis de Nutrição; não exige que sejam o lead consultado."""
    if limite is None:
        limite = LIMITE_CANDIDATOS_POR_EXECUCAO
    if limite <= 0:
        return []

    candidatos = []
    vistos = set()
    for consulta in montar_consultas_instagram(lead):
        print(f"      🔎 {consulta}", flush=True)
        try:
            resultados = list(ddgs.text(
                consulta + " -site:linkedin.com",
                max_results=MAX_RESULTADOS
            ))
        except Exception as erro:
            stats["erros"] += 1
            print(f"      ⚠️ Busca indisponível: {erro}", flush=True)
            pausa()
            continue

        for resultado in resultados:
            if not resultado_compativel(resultado, lead):
                continue
            url = str(resultado.get("href") or resultado.get("url") or "")
            if not url_permitida(url):
                continue
            candidato = _perfil_do_resultado(resultado)
            if not candidato:
                continue
            handle = candidato["instagram"]
            if handle in vistos:
                continue
            vistos.add(handle)
            if instagram_ja_usado(handle, lead["id"]):
                stats["instagram_repetido"] += 1
                continue
            candidato["consulta"] = consulta
            candidatos.append(candidato)
            print(f"      📸 Perfil de Nutrição encontrado: {handle}", flush=True)
            if len(candidatos) >= limite:
                return candidatos
        pausa()
    return candidatos


# ============================================================
# ============================================================
# PRESERVAR REGISTROS EXISTENTES
# ============================================================

def atualizar_lead(lead_id, instagram=None, linkedin=None):
    """Compatibilidade legada: a Máquina 2 não edita leads existentes."""
    print("      Lead de origem preservado; candidato fica separado para revisão", flush=True)
    return False


# ============================================================
# PROCESSAR LEAD
# ============================================================

def validar_candidato(ddgs, lead):
    """Só promove após evidência pública de nome, curso e fase final."""
    from fontes_academicas import extrair_resultado_busca, fase_final_comprovada, norm
    from scraper import buscar_web
    for fase in ('TCC', 'formandos', 'último semestre'):
        consulta = f'"{lead["nome"]}" Nutrição "{lead.get("instituicao") or ""}" {fase}'
        resultados = buscar_web(consulta, fetch_fn=lambda q, backend, limite: list(ddgs.text(q, backend=backend, max_results=limite)))
        if resultados is None:
            return False
        for resultado in resultados:
            url = str(resultado.get('href') or resultado.get('url') or '')
            if not url_permitida(url):
                continue
            for registro in extrair_resultado_busca(resultado, lead.get('instituicao')):
                if norm(registro['nome']) != norm(lead['nome']) or not fase_final_comprovada(registro['evidencia']):
                    continue
                if registro.get('candidato_indicio'):
                    continue
                if lead.get('instituicao') and registro.get('instituicao') != lead['instituicao']:
                    continue
                print("Evidência acadêmica encontrada; lead preservado para revisão manual", flush=True)
                return True
        pausa()
    return False

def processar_lead(ddgs, lead):
    if lead.get("nao_contatar") or lead.get("não_contatar"):
        return
    nome = lead.get("nome", "Sem nome")
    print("")
    print("=" * 65, flush=True)
    print(f"👤 {nome}", flush=True)

    if not parece_pessoa(nome):
        stats["ignorados_nao_pessoa"] += 1
        print("   🏢 Não parece pessoa física", flush=True)
        marcar_como_b2b(lead)
        return

    print(f"   Faculdade: {lead.get('instituicao') or 'não informada'}", flush=True)
    print(f"   Ano: {lead.get('ano_alvo') or 'não informado'}", flush=True)
    print(f"   Situação: {lead.get('periodo_alvo') or 'não informada'}", flush=True)
    stats["processados"] += 1

    restante = LIMITE_CANDIDATOS_POR_EXECUCAO - stats["instagram_encontrado"]
    candidatos = buscar_instagram(ddgs, lead, limite=restante)
    salvos = 0
    for candidato in candidatos:
        if stats["instagram_encontrado"] >= LIMITE_CANDIDATOS_POR_EXECUCAO:
            break
        if salvar_candidato(lead, candidato):
            stats["instagram_encontrado"] += 1
            salvos += 1
            print(
                f"   ✅ CANDIDATO SALVO: {candidato['instagram']} "
                f"({candidato['nome_perfil']}); lead pesquisado preservado",
                flush=True
            )
        else:
            stats["instagram_repetido"] += 1
            print(f"   Arroba já cadastrado: {candidato['instagram']}", flush=True)

    if salvos:
        return

    stats["sem_contato"] += 1
    print("   ⏳ Sem candidato; lead de origem preservado", flush=True)



def executar():

    global supabase
    from ddgs import DDGS
    supabase = conectar_banco()

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
        "INSTAGRAM — ENRIQUECIMENTO DOS NOMES CAPTADOS",
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

        prazo = time.monotonic() + 3000
        anterior = signal.getsignal(signal.SIGALRM)
        def esgotado(*args):
            raise JanelaEncerrada('Janela da Máquina 2 encerrada; lead preservado')
        signal.signal(signal.SIGALRM, esgotado)
        try:
            for lead in leads:
                if stats['instagram_encontrado'] >= LIMITE_CANDIDATOS_POR_EXECUCAO:
                    print('LIMITE DE 50 ARROBAS ÚNICAS ATINGIDO', flush=True)
                    break
                restante = prazo - time.monotonic()
                if restante <= 0:
                    break
                erros_antes = stats["erros"]
                busca_concluida = True
                signal.setitimer(signal.ITIMER_REAL, min(45, restante))
                try:
                    processar_lead(ddgs, lead)
                except JanelaEncerrada:
                    busca_concluida = False
                    print('LEAD ADIADO: prazo de busca encerrado', flush=True)
                except Exception as exc:
                    busca_concluida = False
                    stats['erros'] += 1
                    print(f'FALHA NO ENRIQUECIMENTO: {type(exc).__name__}; lead preservado', flush=True)
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    if busca_concluida and stats["erros"] == erros_antes:
                        try:
                            registrar_verificacao_m2(lead)
                        except Exception as exc:
                            stats["erros"] += 1
                            print(f'AVISO: não registrou prazo de nova busca: {type(exc).__name__}', flush=True)
                    salvar_cursor_m2(lead["id"])
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, anterior)

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
        f"Processados como pessoa: "
        f"{stats['processados']}",
        flush=True
    )

    print(
        f"Separados para B2B: "
        f"{stats['ignorados_nao_pessoa']}",
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

    if stats['erros']:
        raise RuntimeError('Máquina 2 concluiu com falhas operacionais; consulte o resumo')

if __name__ == "__main__":

    executar()

    print(
        "✅ MÁQUINA 2 FINALIZADA",
        flush=True
    )

