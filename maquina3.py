"""Máquina 3: varredura em lote de listas públicas de formandos de Nutrição.
Usa checkpoint independente e a rotina central de deduplicação/salvamento da Máquina 1.
"""
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from fontes_academicas import (
    acesso_reservado_maquina2, carregar_fonte, extrair_resultado_busca,
    fase_final_comprovada, nomes_da_lista, periodo_academico, pessoa, url_permitida,
)
from scraper import (
    ESTADOS, SupabaseRepo, alias_instituicao, agrupar_faculdades,
    filtrar_instituicoes_lista_confirmada,
    buscar_web, ddgs_texto, formatar_nome_pessoa, limpar_espacos, normalizar,
    ordem_estado, salvar_lead, stats,
)

ETAPA = "captacao_maquina3_formandos_v3"

ORDEM_ESTADOS_M3 = ["SC", "SP", "PR"] + [
    sigla for sigla, _ in ESTADOS if sigla not in {"SC", "SP", "PR"}
]


def ordem_estado_maquina3(uf):
    try:
        return ORDEM_ESTADOS_M3.index((uf or "").upper())
    except ValueError:
        return len(ORDEM_ESTADOS_M3)
MAX_FACULDADES = 5
MAX_RESULTADOS_BUSCA = 6
MAX_FONTES_POR_CONSULTA = 2
MAX_BUSCAS_INSTAGRAM_POR_FACULDADE = 8
TOTAL_CONSULTAS = 6
instagram_stats = {"consultas": 0, "perfis_verificados": 0, "perfis_rejeitados": 0, "erros": 0}


def consultas_lote(item):
    nome = limpar_espacos(item.get("instituicao"))
    alias = limpar_espacos(alias_instituicao(item) or "")
    termos = list(dict.fromkeys(t for t in (alias, nome) if t))
    termo = '(' + ' OR '.join('"'+t.replace('"', '')+'"' for t in termos) + ')'
    uf = limpar_espacos(item.get("estado") or "")
    return [
        f'{termo} "Nutrição" (formandos OR concluintes OR graduandos) (2025 OR 2026) nomes',
        f'{termo} "Nutrição" (formatura OR "colação de grau") (2025 OR 2026)',
        f'{termo} "Nutrição" (TCC OR "trabalho de conclusão") (2025 OR 2026) autor',
        f'{termo} "Nutrição" (aluno OR estudante OR graduando) ("8º período" OR "último semestre") 2026',
        f'{termo} "Nutrição" ("recém-formado" OR "recém-formada" OR egresso OR egressa) (2025 OR 2026)',
        f'{termo} Nutrição turma formatura lista alunos 2025 2026 {uf}',
    ]

def candidatos_instagram_publico(resultado, item):
    """Usa somente título/trecho público indexado pelo Google; não abre o Instagram."""
    url = str(resultado.get("href") or resultado.get("url") or "")
    host = (urlparse(url).hostname or "").lower()
    path = urlparse(url).path.lower().strip("/")
    if host not in {"instagram.com", "www.instagram.com"} or not re.match(r"^(?:p|reel|reels|tv)/", path):
        return []

    campos = [limpar_espacos(resultado.get(k) or "") for k in ("title", "body", "snippet")]
    texto = limpar_espacos(" ".join(campos))
    n = normalizar(texto)
    if "nutricao" not in n or not re.search(r"2025|2026", n):
        return []
    if not re.search(r"formand|concluint|formatura|colacao|egress|ultimo semestre|ultimo periodo|8. semestre|8. periodo", n):
        return []

    nome_inst = normalizar(item.get("instituicao"))
    alias = normalizar(alias_instituicao(item) or "")
    texto_origem = normalizar(texto + " " + url)
    tokens = [t for t in re.findall(r"[a-z0-9]+", nome_inst)
              if len(t) >= 5 and t not in {"universidade", "faculdade", "instituto", "centro", "superior"}]
    if not any(x and x in texto_origem for x in (nome_inst, alias)) and not any(t in texto_origem for t in tokens):
        return []

    nomes = []
    for campo in campos:
        rotulo = re.search(
            r"\b(?:formand[oa]s?|concluintes?|egress[oa]s?|alun[oa]s?|estudantes?)\b"
            r"[^:;.!?]{0,70}[:\-–]\s*([^.!?]+)",
            campo, re.I,
        )
        if rotulo:
            lista = re.sub(r"^\s*(?:(?:do|da|de)\s+)?(?:curso\s+de\s+)?nutri[cç][aã]o\s*", "", rotulo.group(1), flags=re.I)
            lista = re.sub(r"^\s*(?:2025|2026)(?:[./-][12])?\s*[:\-–]?\s*", "", lista)
            nomes.extend(nomes_da_lista(lista))
        else:
            singular = re.search(
                r"(?i:\b(?:a\s+aluna|o\s+aluno|aluna|aluno|formanda|formando|estudante|egressa|egresso)\s+)"
                r"([A-ZÀ-Ý][A-Za-zÀ-ÿ'’-]+(?:\s+(?:(?:de|da|do|dos|das|e)\s+)?[A-ZÀ-Ý][A-Za-zÀ-ÿ'’-]+){1,6})\b",
                campo,
            )
            if singular:
                nomes.extend(nomes_da_lista(singular.group(1)))
    nomes = list({normalizar(nome): nome for nome in nomes}.values())
    if not nomes:
        return []

    anos = set(re.findall(r"\b202[56]\b", n))
    ano = 2026 if "2026" in anos else 2025
    _, periodo = periodo_academico(texto)
    if ano == 2026 and not re.search(r"ultimo semestre|ultimo periodo|8. semestre|8. periodo|formand|concluint|formatura|colacao", n):
        return []
    periodo = periodo or f"{ano} (semestre não informado)"
    candidato_indicio = not fase_final_comprovada(texto)
    return [{
        "nome": nome,
        "ano": ano,
        "periodo": periodo,
        "evidencia": f"Instagram público institucional | resultado indexado pelo Google | Nutrição | {periodo} | {texto}",
        "fonte_url": url,
        "candidato_indicio": candidato_indicio,
    } for nome in nomes]


def extrair_perfil_instagram_publico(resultados, registro):
    """Aceita perfil público direto com nome e sinal profissional compatíveis."""
    proibidos = {"p", "reel", "reels", "tv", "stories", "explore", "accounts", "about",
                 "directory", "web", "direct", "legal", "privacy", "developer", "challenge"}
    particulas = {"de", "da", "do", "dos", "das", "e"}
    nome_tokens = [t for t in re.findall(r"[a-z0-9]+", normalizar(registro.get("nome")))
                   if t not in particulas]
    if len(nome_tokens) < 2:
        return None
    minimo = max(2, (len(nome_tokens) * 2 + 2) // 3)
    for resultado in resultados or []:
        texto = limpar_espacos(" ".join(
            str(resultado.get(k) or "") for k in ("title", "body", "snippet")
        ))
        url = str(resultado.get("href") or resultado.get("url") or "")
        candidatos_url = [url]
        # Diretórios profissionais às vezes exibem o @ como link no trecho público.
        candidatos_url.extend(re.findall(
            r"(?:https?://)?(?:www\.)?instagram\.com/[A-Za-z0-9._]{1,30}/?",
            texto, flags=re.I,
        ))
        for candidato_url in candidatos_url:
            if candidato_url and not re.match(r"(?i)^https?://", candidato_url):
                candidato_url = "https://" + candidato_url
            parsed = urlparse(candidato_url)
            host = (parsed.hostname or "").lower()
            partes = [p for p in parsed.path.split("/") if p]
            if host not in {"instagram.com", "www.instagram.com"} or len(partes) != 1:
                continue
            handle = partes[0].lstrip("@")
            if handle.lower() in proibidos or not re.fullmatch(r"[A-Za-z0-9._]{1,30}", handle):
                continue
            texto_norm = normalizar(texto + " " + handle.replace("_", " ").replace(".", " "))
            encontrados = [token for token in nome_tokens if token in texto_norm]
            if (nome_tokens[0] not in encontrados or nome_tokens[-1] not in encontrados
                    or len(set(encontrados)) < minimo):
                continue
            if not re.search(r"nutri|nutrition|crn", texto_norm):
                continue
            return {
                "instagram": "@" + handle,
                "instagram_url": f"https://www.instagram.com/{handle}/",
                "evidencia": texto[:700],
            }
    return None


def lead_qualificado_maquina3(registro):
    """Exige nome de pessoa e evidência de Nutrição em fase final/recente."""
    nome = limpar_espacos(registro.get("nome") or "")
    nome_norm = normalizar(nome)
    tokens = re.findall(r"[a-z]+", nome_norm)
    termos_nao_pessoa = {
        "universidade", "faculdade", "instituto", "centro", "curso", "nutricao",
        "tcc", "trabalho", "conclusao", "formandos", "concluintes", "turma",
    }
    if len(tokens) < 2 or len(tokens) > 8 or any(t in termos_nao_pessoa for t in tokens):
        return False

    ano = registro.get("ano")
    if str(ano) not in {"2025", "2026"}:
        return False
    evidencia = limpar_espacos(registro.get("evidencia") or "")
    evidencia_norm = normalizar(evidencia)
    tem_nutricao = "nutricao" in evidencia_norm
    tem_fase = bool(re.search(
        r"formand|concluint|colacao|formatura|egress|recem formad|graduand|"
        r"ultimo semestre|ultimo periodo|8[oa]? semestre|8[oa]? periodo",
        evidencia_norm,
    ))
    return tem_nutricao and tem_fase


def filtrar_leads_qualificados(registros):
    """Mantém apenas nomes de pessoas com evidência acadêmica recente verificável."""
    return [registro for registro in registros if lead_qualificado_maquina3(registro)]


def extrair_perfil_relacionado(resultados, nome_alvo):
    """Fallback: aceita outra pessoa só com perfil direto e sinal público de Nutrição."""
    proibidos = {"p", "reel", "reels", "tv", "stories", "explore", "accounts", "about",
                 "directory", "web", "direct", "legal", "privacy", "developer", "challenge"}
    alvo = [t for t in re.findall(r"[a-z0-9]+", normalizar(nome_alvo))
            if t not in {"de", "da", "do", "dos", "das", "e"}]
    for resultado in resultados or []:
        url = str(resultado.get("href") or resultado.get("url") or "")
        parsed = urlparse(url)
        partes = [p for p in parsed.path.split("/") if p]
        if (parsed.hostname or "").lower() not in {"instagram.com", "www.instagram.com"} or len(partes) != 1:
            continue
        handle = partes[0].lstrip("@")
        if handle.lower() in proibidos or not re.fullmatch(r"[A-Za-z0-9._]{1,30}", handle):
            continue
        campos = [str(resultado.get(k) or "") for k in ("title", "body", "snippet")]
        texto = limpar_espacos(" ".join(campos))
        texto_norm = normalizar(texto + " " + handle.replace("_", " ").replace(".", " "))
        if not re.search(r"nutri|nutrition|crn", texto_norm):
            continue
        titulo = limpar_espacos(campos[0])
        titulo = re.split(r"\s*(?:\(@?[^)]{1,40}\)|[|•·])\s*", titulo, maxsplit=1)[0]
        titulo = re.sub(r"(?i)\s*instagram.*$", "", titulo).strip(" -–—:")
        nome = titulo
        if not pessoa(nome):
            continue
        nome = formatar_nome_pessoa(nome)
        tokens = [t for t in re.findall(r"[a-z0-9]+", normalizar(nome))
                  if t not in {"de", "da", "do", "dos", "das", "e"}]
        if len(tokens) < 2 or len(tokens) > 8 or any(t in {"nutricionista", "nutricao", "instagram"} for t in tokens):
            continue
        iguais = len(set(tokens) & set(alvo))
        if iguais >= max(2, (len(tokens) * 2 + 2) // 3):
            continue
        return {
            "nome": nome,
            "instagram": "@" + handle,
            "instagram_url": f"https://www.instagram.com/{handle}/",
            "evidencia": texto[:700],
            "fallback_relacionado": True,
        }
    return None


def salvar_profissional_relacionado(repo, registro, item, nome_alvo=None):
    """Salva um perfil relacionado como não qualificado para validar vínculo/recência."""
    nome = limpar_espacos(registro.get("nome") or "")
    instagram = limpar_espacos(registro.get("instagram") or "")
    if not pessoa(nome) or not instagram or not repo:
        return False
    nome = formatar_nome_pessoa(nome)
    if repo.instagram_usado(instagram):
        return False
    if repo.lead_existe(nome, None):
        if hasattr(repo, "completar_instagram"):
            repo.completar_instagram(nome, None, instagram)
        return False
    evidencia = limpar_espacos(
        "Perfil público de profissional relacionado encontrado ao pesquisar "
        + limpar_espacos(nome_alvo or "um formando de Nutrição")
        + " | Sinal de Nutrição: " + (registro.get("evidencia") or "")
    )[:1500]
    dados = {
        "nome": nome, "instagram": instagram, "linkedin": None, "whatsapp": None,
        "nicho": "nutricionista", "origem": "captacao_relacionada_nutricao",
        "status": "novo", "app_baixado": False, "nao_contatar": False,
        "qualificado": False, "data_primeiro_contato": None, "data_ultimo_contato": None,
        "proxima_acao": "validar_fase_academica", "tentativas_contato": 0,
        "cliente": False, "funil_destino": None, "cidade": item.get("cidade") or "Não identificado",
        "estado": item.get("estado"), "instituicao": None, "pontuacao": 10,
        "evidencia": evidencia, "fonte_url": registro.get("instagram_url"),
        "ano_alvo": None, "periodo_alvo": None, "origem_lead": "perfil_publico_nutricao_relacionado",
        "rede_processada": False, "nivel_rede": 0,
        "fonte_validacao": "perfil_publico_nutricao_relacionado",
    }
    if repo.inserir_lead(dados) is False:
        return False
    stats["leads_salvos"] += 1
    return True


def buscar_instagram_da_pessoa(registro, item):
    """Procura o perfil individual após identificar a pessoa em fonte pública."""
    nome = limpar_espacos(registro.get("nome"))
    instituicao = limpar_espacos(item.get("instituicao"))
    alias = limpar_espacos(alias_instituicao(item) or "")
    cidade = limpar_espacos(item.get("cidade") or "")
    contexto = [x for x in (instituicao, alias, cidade) if x and x.lower() != "nacional"]
    local = " OR ".join('"' + x.replace('"', '') + '"' for x in contexto)
    consulta = f'site:instagram.com "{nome}" (nutricionista OR nutri OR CRN)'
    if local:
        consulta += f" ({local})"
    instagram_stats["consultas"] += 1
    resultados = buscar_google(consulta, max_results=MAX_RESULTADOS_BUSCA)
    if resultados is None:
        instagram_stats["erros"] += 1
        return None
    perfil = extrair_perfil_instagram_publico(resultados, registro)
    if not perfil:
        # A busca reserva é nacional: um profissional relacionado pode estar fora
        # da faculdade ou da cidade pesquisada, desde que o perfil confirme Nutrição.
        consulta_reserva = f'"{nome}" nutricionista Instagram (CRN OR Nutrição)'
        instagram_stats["consultas"] += 1
        resultados_reserva = buscar_google(consulta_reserva, max_results=MAX_RESULTADOS_BUSCA)
        if resultados_reserva is None:
            instagram_stats["erros"] += 1
            resultados_reserva = []
        perfil = extrair_perfil_instagram_publico(resultados_reserva, registro)
        resultados = list(resultados or []) + list(resultados_reserva or [])
    if perfil:
        instagram_stats["perfis_verificados"] += 1
        print(f"      PERFIL PÚBLICO VINCULADO: {nome} | {perfil['instagram']}", flush=True)
    else:
        instagram_stats["perfis_rejeitados"] += 1
        relacionado = extrair_perfil_relacionado(resultados, nome)
        if relacionado:
            print(f"      PERFIL RELACIONADO: {relacionado['nome']} | {relacionado['instagram']}", flush=True)
            return {"fallback_lead": relacionado}
        print(f"      INSTAGRAM NÃO CONFIRMADO: {nome}", flush=True)
    return perfil


def enriquecer_com_instagram(registros, item, buscas_feitas=0, cache=None):
    """Enriquece pessoas únicas com @ público, reaproveitando buscas da faculdade."""
    cache = cache if cache is not None else {}
    saida = []
    for registro in registros:
        chave = normalizar(registro.get("nome") or "")
        if registro.get("instagram"):
            saida.append(registro)
            continue
        if chave in cache:
            perfil = cache[chave]
            if perfil and perfil.get("instagram"):
                registro = dict(registro)
                registro["instagram"] = perfil["instagram"]
                registro["evidencia"] = limpar_espacos(
                    (registro.get("evidencia") or "") + " | Perfil profissional público confirmado: "
                    + perfil["instagram_url"] + " | " + perfil["evidencia"]
                )[:1500]
            elif perfil and perfil.get("fallback_lead"):
                registro = dict(registro)
                registro["fallback_leads"] = [perfil["fallback_lead"]]
            saida.append(registro)
            continue
        if buscas_feitas >= MAX_BUSCAS_INSTAGRAM_POR_FACULDADE:
            saida.append(registro)
            continue
        buscas_feitas += 1
        perfil = buscar_instagram_da_pessoa(registro, item)
        cache[chave] = perfil
        if perfil and perfil.get("instagram"):
            registro = dict(registro)
            registro["instagram"] = perfil["instagram"]
            registro["evidencia"] = limpar_espacos(
                (registro.get("evidencia") or "") + " | Perfil profissional público confirmado: "
                + perfil["instagram_url"] + " | " + perfil["evidencia"]
            )[:1500]
        elif perfil and perfil.get("fallback_lead"):
            registro = dict(registro)
            registro["fallback_leads"] = [perfil["fallback_lead"]]
        saida.append(registro)
    return saida, buscas_feitas


def buscar_google(consulta, max_results=MAX_RESULTADOS_BUSCA):
    """Tenta Google primeiro e usa buscador alternativo apenas se o Google falhar."""
    falhou = False
    for tentativa in range(2):
        try:
            resultados = list(ddgs_texto(consulta, backend="google", max_results=max_results) or [])
            print(f"      GOOGLE: resultados: {len(resultados)}", flush=True)
            return resultados
        except Exception as exc:
            falhou = True
            detalhe = limpar_espacos(str(exc))[:180]
            print(f"      GOOGLE: erro {type(exc).__name__}: {detalhe} | tentativa {tentativa + 1}/2", flush=True)
    if falhou:
        print("      GOOGLE indisponível; usando busca alternativa para esta consulta.", flush=True)
        return buscar_web(consulta, max_results=max_results)
    return None


def etapa_item(item):
    return f"{ETAPA}_faculdade_{item['id']}"


def carregar_fila(repo):
    registros = []
    offset = 0
    while True:
        consulta = repo.client.table("instituicoes_nutricao").select("*").order("id")
        lote = filtrar_instituicoes_lista_confirmada(consulta).range(
            offset, offset + 999
        ).execute().data or []
        registros.extend(lote)
        if len(lote) < 1000:
            break
        offset += 1000
    faculdades = agrupar_faculdades(registros)
    checkpoints = {}
    offset = 0
    while True:
        lote = (repo.client.table("controle_busca")
                .select("etapa,status,atualizado_em,indice_pesquisa,total_pesquisas")
                .like("etapa", ETAPA + "_faculdade_%").order("id")
                .range(offset, offset + 999).execute()).data or []
        checkpoints.update({x["etapa"]: x for x in lote})
        if len(lote) < 1000:
            break
        offset += 1000
    pendentes = []
    for item in faculdades:
        cp = checkpoints.get(etapa_item(item))
        if cp and cp.get("status") == "concluido":
            continue
        item["_m3_cp"] = cp
        pendentes.append(item)
    return pendentes


def selecionar_lote(pendentes, limite=MAX_FACULDADES):
    """Mantém um estado por vez e retoma instituições interrompidas primeiro."""
    if not pendentes:
        return []
    uf = min(((x.get("estado") or "") for x in pendentes), key=ordem_estado_maquina3)
    do_estado = [x for x in pendentes if (x.get("estado") or "") == uf]
    return sorted(
        do_estado,
        key=lambda x: (
            0 if x.get("_m3_cp") else 1,
            (x.get("_m3_cp") or {}).get("atualizado_em") or "",
            normalizar(x.get("instituicao")),
        ),
    )[:limite]


def salvar_checkpoint(repo, item, status, indice, consulta=None, erro=None,
                      encontrados=0, salvos=0):
    repo.controle_salvar(etapa_item(item), {
        "estado": item.get("estado") or "BR",
        "cidade": "Nacional",
        "instituicao": item["instituicao"],
        "status": status,
        "indice_pesquisa": indice,
        "total_pesquisas": TOTAL_CONSULTAS,
        "consulta_atual": consulta,
        "ultimo_erro": erro,
        "leads_encontrados": encontrados,
        "leads_salvos": salvos,
        "finalizado_em": None,
    })


def processar_faculdade(repo, item):
    consultas = consultas_lote(item)
    cp = item.get("_m3_cp") or {}
    inicio = 0
    if cp.get("status") in {"processando", "erro"}:
        inicio = min(max(int(cp.get("indice_pesquisa") or 0), 0), len(consultas))
    encontrados = int(cp.get("leads_encontrados") or 0)
    salvos_antes = stats["leads_salvos"]
    alias = alias_instituicao(item)
    cidade = item.get("cidade") or "Não identificado"
    instagram_buscas = 0
    instagram_cache = {}

    for idx in range(inicio, len(consultas)):
        consulta = consultas[idx]
        salvar_checkpoint(repo, item, "processando", idx, consulta,
                          encontrados=encontrados,
                          salvos=int(cp.get("leads_salvos") or 0) + stats["leads_salvos"] - salvos_antes)
        resultados = buscar_google(consulta, max_results=MAX_RESULTADOS_BUSCA)
        if resultados is None:
            stats["erros"] += 1
            salvar_checkpoint(repo, item, "erro", idx, consulta,
                              "Buscador indisponível; consulta preservada",
                              encontrados, int(cp.get("leads_salvos") or 0) + stats["leads_salvos"] - salvos_antes)
            return False

        urls = []
        for resultado in resultados:
            url = str(resultado.get("href") or resultado.get("url") or "")
            if not url_permitida(url):
                continue

            # Aproveita também o título e o trecho público retornados pelo Google.
            # Só salva quando o próprio resultado vincula pessoa, Nutrição, ano e instituição.
            if acesso_reservado_maquina2(url):
                registros_busca = candidatos_instagram_publico(resultado, item)
            else:
                registros_busca = extrair_resultado_busca(resultado, item["instituicao"], alias)
                registros_busca = [
                    r for r in registros_busca
                    if r.get("instituicao") and r.get("nome") and r.get("ano") in {2025, 2026}
                    and fase_final_comprovada(r.get("evidencia") or "")
                ]
            registros_busca = filtrar_leads_qualificados(registros_busca)
            registros_busca, instagram_buscas = enriquecer_com_instagram(
                registros_busca, item, instagram_buscas, instagram_cache
            )
            for registro in registros_busca:
                encontrados += 1
                stats["leads_encontrados"] += 1
                salvar_lead(
                    repo, registro["nome"], registro.get("instituicao") or item["instituicao"],
                    cidade, item.get("estado"), registro.get("evidencia") or "",
                    registro.get("fonte_url") or url,
                    instagram=registro.get("instagram"),
                    ano_forcado=registro.get("ano"),
                    periodo_forcado=registro.get("periodo"),
                    instituicao_alias=alias,
                    candidato_indicio=registro.get("candidato_indicio", not fase_final_comprovada(registro.get("evidencia", ""))),
                )
                for relacionado in registro.get("fallback_leads", []):
                    salvar_profissional_relacionado(repo, relacionado, item, registro["nome"])

            if acesso_reservado_maquina2(url):
                continue
            if url not in urls:
                urls.append(url)
        for url in urls[:MAX_FONTES_POR_CONSULTA]:
            try:
                stats["fontes_visitadas"] += 1
                registros, links = carregar_fonte(url, item["instituicao"], alias)
            except Exception as exc:
                stats["erros"] += 1
                print(f"FONTE PENDENTE: {url} | {type(exc).__name__}", flush=True)
                continue
            registros = filtrar_leads_qualificados(registros)
            registros, instagram_buscas = enriquecer_com_instagram(
                registros, item, instagram_buscas, instagram_cache
            )
            for registro in registros:
                encontrados += 1
                stats["leads_encontrados"] += 1
                nome_instituicao = registro.get("instituicao") or item["instituicao"]
                salvou = salvar_lead(
                    repo, registro["nome"], nome_instituicao,
                    cidade, item.get("estado"), registro.get("evidencia") or "",
                    registro.get("fonte_url") or url,
                    instagram=registro.get("instagram"),
                    ano_forcado=registro.get("ano"),
                    periodo_forcado=registro.get("periodo"),
                    instituicao_alias=alias,
                    candidato_indicio=registro.get("candidato_indicio", False),
                )
                for relacionado in registro.get("fallback_leads", []):
                    salvar_profissional_relacionado(repo, relacionado, item, registro["nome"])
            # Até dois links da própria página de lista podem apontar para PDFs/artigos.
            host = urlparse(url).hostname
            for link in links[:2]:
                if (not url_permitida(link) or acesso_reservado_maquina2(link)
                        or urlparse(link).hostname != host):
                    continue
                try:
                    stats["fontes_visitadas"] += 1
                    subregistros, _ = carregar_fonte(link, item["instituicao"], alias)
                except Exception as exc:
                    stats["erros"] += 1
                    print(f"FONTE VINCULADA PENDENTE: {link} | {type(exc).__name__}", flush=True)
                    continue
                subregistros = filtrar_leads_qualificados(subregistros)
                subregistros, instagram_buscas = enriquecer_com_instagram(
                    subregistros, item, instagram_buscas, instagram_cache
                )
                for registro in subregistros:
                    encontrados += 1
                    stats["leads_encontrados"] += 1
                    salvou = salvar_lead(
                        repo, registro["nome"], registro.get("instituicao") or item["instituicao"],
                        cidade, item.get("estado"), registro.get("evidencia") or "",
                        registro.get("fonte_url") or link,
                        instagram=registro.get("instagram"),
                        ano_forcado=registro.get("ano"),
                        periodo_forcado=registro.get("periodo"),
                        instituicao_alias=alias,
                        candidato_indicio=registro.get("candidato_indicio", False),
                    )
                    for relacionado in registro.get("fallback_leads", []):
                        salvar_profissional_relacionado(repo, relacionado, item, registro["nome"])

        cp = {
            "leads_encontrados": encontrados,
            "leads_salvos": int(cp.get("leads_salvos") or 0) + stats["leads_salvos"] - salvos_antes,
        }
        salvar_checkpoint(repo, item, "processando", idx + 1,
                          consultas[idx + 1] if idx + 1 < len(consultas) else None,
                          encontrados=encontrados, salvos=cp["leads_salvos"])

    repo.controle_salvar(etapa_item(item), {
        "estado": item.get("estado") or "BR",
        "cidade": "Nacional",
        "instituicao": item["instituicao"],
        "status": "concluido",
        "indice_pesquisa": TOTAL_CONSULTAS,
        "total_pesquisas": TOTAL_CONSULTAS,
        "consulta_atual": consultas[-1],
        "ultimo_erro": None,
        "leads_encontrados": encontrados,
        "leads_salvos": int(cp.get("leads_salvos") or 0),
        "finalizado_em": datetime.now(timezone.utc).isoformat(),
    })
    print(f"M3 CONCLUÍDA | {item['estado']} | {item['instituicao']} | "
          f"encontrados={encontrados} | novos_salvos={stats['leads_salvos']-salvos_antes}", flush=True)
    return True


def executar():
    print("MÁQUINA 3 | BUSCA EM LOTE DE FORMANDOS DE NUTRIÇÃO", flush=True)
    repo = SupabaseRepo.from_env()
    pendentes = carregar_fila(repo)
    lote = selecionar_lote(pendentes)
    if not lote:
        print("M3: fila nacional concluída; nenhuma faculdade pendente.", flush=True)
        return
    print("M3: lote", json.dumps(
        [{"estado": x.get("estado"), "instituicao": x["instituicao"]} for x in lote],
        ensure_ascii=False), flush=True)
    for item in lote:
        try:
            processar_faculdade(repo, item)
        except Exception as exc:
            stats["erros"] += 1
            cp = repo.controle_get(etapa_item(item)) or item.get("_m3_cp") or {}
            salvar_checkpoint(repo, item, "erro", int(cp.get("indice_pesquisa") or 0),
                              cp.get("consulta_atual"),
                              f"{type(exc).__name__}: {str(exc)[:700]}",
                              int(cp.get("leads_encontrados") or 0),
                              int(cp.get("leads_salvos") or 0))
            print(f"M3 ERRO ISOLADO | {item['instituicao']} | {type(exc).__name__}", flush=True)
    print(f"M3 RESUMO | visitou={stats['fontes_visitadas']} "
          f"encontrados={stats['leads_encontrados']} salvos={stats['leads_salvos']} "
          f"duplicados={stats['duplicados']} erros={stats['erros']}", flush=True)
    print(f"M3 INSTAGRAM | consultas={instagram_stats['consultas']} "
          f"perfis_confirmados={instagram_stats['perfis_verificados']} "
          f"sem_confirmacao={instagram_stats['perfis_rejeitados']} "
          f"erros={instagram_stats['erros']}", flush=True)


if __name__ == "__main__":
    executar()

