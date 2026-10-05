import os
import re
import time
import random
import signal
from datetime import datetime, timezone
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

LIMITE_POR_EXECUCAO = 25

PAUSA_MIN = 2
PAUSA_MAX = 4

MAX_RESULTADOS = 10


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
# MARCAR REGISTRO NÃO-PESSOA
# ============================================================

def marcar_como_b2b(lead):

    try:

        (
            supabase
            .table("leds")
            .update({
                "qualificado":
                    False,

                "proxima_acao":
                    "revisao_b2b"
            })
            .eq(
                "id",
                lead["id"]
            )
            .execute()
        )

        print(
            "   🏢 Registro separado para possível B2B",
            flush=True
        )

    except Exception as erro:

        print(
            f"   ⚠️ Erro marcando B2B: {erro}",
            flush=True
        )

        stats["erros"] += 1


# ============================================================
# FILTRO DE ENRIQUECIMENTO
# ============================================================

def lead_apto_para_enriquecimento(lead):
    """Impede que a Máquina 2 pesquise instituições, cursos ou outros nichos."""
    nome = str(lead.get("nome") or "")
    contexto = normalizar(" ".join(
        str(lead.get(campo) or "")
        for campo in ("nome", "nicho", "instituicao", "cidade", "estado",
                      "periodo_alvo", "evidencia", "fonte_url")
    ))
    bloqueados = (
        "engenheiro agronomo", "engenharia agronomica", "agronomo",
        "fisioterapia", "fisioterapeuta", "psicologia", "psicologo",
        "odontologia", "dentista", "farmacia", "veterinaria",
        "teste automacao", "teste crm", "google docs", "vestibular",
        "encontro cientifico", "vaga emprego", "pos ead",
        "centro universitario", "universidade", "faculdade", "unilehu"
    )
    if not parece_pessoa(nome):
        return False
    if any(termo in contexto for termo in bloqueados):
        return False
    return True


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
                "periodo_alvo,proxima_acao,qualificado,nao_contatar,não_contatar,evidencia,fonte_url,maquina2_tentativas"
            )
            .eq('nao_contatar', False)
            .eq('qualificado', True)\n            .is_('instagram', 'null')
            .order('maquina2_verificado_em', nullsfirst=True)
            .order('id')
            .limit(
                LIMITE_POR_EXECUCAO
            )
            .execute()
        )

        leads = [lead for lead in (resposta.data or []) if lead_apto_para_enriquecimento(lead)]

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

def resultado_compativel(resultado, lead):
    """O handle só é aceito com evidência pública da identidade e do curso."""
    texto = normalizar(str(resultado.get('title') or '') + ' ' + str(resultado.get('body') or ''))
    nome = normalizar(lead.get('nome'))
    if not nome or not re.search(r'(?<!\w)' + re.escape(nome) + r'(?!\w)', texto):
        return False
    if not re.search(r'nutri(?:cao|cionista)', texto):
        return False
    vinculos = [normalizar(lead.get(k)) for k in ('instituicao', 'cidade') if lead.get(k)]
    return not vinculos or any(v in texto for v in vinculos)


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
                    consulta + " -site:linkedin.com",
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
            if not resultado_compativel(resultado, lead):
                continue
            if not url_permitida(str(resultado.get("href") or resultado.get("url") or "")):
                continue

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
# BUSCAR INSTAGRAM EM TEXTO
# ============================================================

def buscar_handle_em_texto(
    ddgs,
    lead
):

    nome = lead["nome"]

    consultas = [
        f'"{nome}" Instagram Nutrição',
        f'"{nome}" "instagram.com/" Nutrição',
    ]

    padroes = [
        r"instagram\.com/([A-Za-z0-9._]+)",
        r"@([A-Za-z0-9._]{3,30})",
    ]

    for consulta in consultas:

        try:

            resultados = list(
                ddgs.text(
                    consulta + " -site:linkedin.com",
                    max_results=8
                )
            )

        except Exception:

            continue

        for resultado in resultados:
            if not resultado_compativel(resultado, lead):
                continue
            if not url_permitida(str(resultado.get("href") or resultado.get("url") or "")):
                continue

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
# ATUALIZAR CONTATO DO LEAD
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

        resposta = (
            supabase
            .table("leds")
            .update(
                dados
            )
            .eq(
                "id",
                lead_id
            )
            .eq('nao_contatar', False)
            .or_('não_contatar.is.null,não_contatar.eq.false')
            .eq('qualificado', True)
            .execute()
        )
        return bool(resposta.data)

    except Exception as erro:

        print(
            f"      ❌ Erro atualizando Supabase: {erro}",
            flush=True
        )

        stats["erros"] += 1
        raise RuntimeError('Não foi possível confirmar atualização do lead') from erro


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
                dados = {'qualificado': True, 'proxima_acao': 'primeiro_contato_instagram' if lead.get('instagram') else 'buscar_instagram',
                         'ano_alvo': registro['ano'], 'periodo_alvo': registro['periodo'],
                         'evidencia': registro['evidencia'], 'fonte_url': url,
                         'fonte_validacao': 'fase_academica_validada_maquina2'}
                resposta = (supabase.table('leds').update(dados).eq('id', lead['id'])
                            .eq('nao_contatar', False).or_('não_contatar.is.null,não_contatar.eq.false').eq('qualificado', False).execute())
                if not resposta.data:
                    return False
                lead.update(dados)
                return True
        pausa()
    return False

def processar_lead(
    ddgs,
    lead
):

    if lead.get('nao_contatar') or lead.get('não_contatar'):
        return
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

    # ========================================================
    # VERIFICA SE É PESSOA
    # ========================================================

    if not parece_pessoa(
        nome
    ):

        stats[
            "ignorados_nao_pessoa"
        ] += 1

        print(
            "   🏢 Não parece pessoa física",
            flush=True
        )

        marcar_como_b2b(
            lead
        )

        return

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
    # INSTAGRAM DIRETO
    # ========================================================

    instagram = buscar_instagram(
        ddgs,
        lead
    )

    if instagram:

        stats[
            "instagram_encontrado"
        ] += 1

        confirmado = atualizar_lead(
            lead["id"],
            instagram=instagram
        )
        if not confirmado:
            print('   Atualização não aplicada; estado atual do lead preservado', flush=True)
            return

        print(
            f"   ✅ SALVO NO SUPABASE: {instagram}",
            flush=True
        )

        return

    # ========================================================
    # INSTAGRAM EM OUTRAS PÁGINAS
    # ========================================================

    instagram = buscar_handle_em_texto(
        ddgs,
        lead
    )

    if instagram:

        stats[
            "instagram_encontrado"
        ] += 1

        confirmado = atualizar_lead(
            lead["id"],
            instagram=instagram
        )
        if not confirmado:
            print('   Atualização não aplicada; estado atual do lead preservado', flush=True)
            return

        print(
            f"   ✅ SALVO NO SUPABASE: {instagram}",
            flush=True
        )

        return

    atualizar_lead(lead["id"])
    stats["sem_contato"] += 1
    print("   ⏳ Continua pendente de Instagram", flush=True)


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

        prazo = time.monotonic() + 300
        anterior = signal.getsignal(signal.SIGALRM)
        def esgotado(*args):
            raise JanelaEncerrada('Janela da Máquina 2 encerrada; lead preservado')
        signal.signal(signal.SIGALRM, esgotado)
        try:
            for lead in leads:
                restante = prazo - time.monotonic()
                if restante <= 0:
                    break
                signal.setitimer(signal.ITIMER_REAL, min(45, restante))
                try:
                    processar_lead(ddgs, lead)
                except JanelaEncerrada:
                    print('LEAD ADIADO: prazo de busca encerrado', flush=True)
                except Exception as exc:
                    stats['erros'] += 1
                    print(f'FALHA NO ENRIQUECIMENTO: {type(exc).__name__}; lead preservado', flush=True)
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    (supabase.table('leds').update({
                        'maquina2_verificado_em': datetime.now(timezone.utc).isoformat(),
                        'maquina2_tentativas': int(lead.get('maquina2_tentativas') or 0) + 1,
                    }).eq('id', lead['id']).execute())
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

