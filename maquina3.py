"""Máquina 3: varredura em lote de listas públicas de formandos de Nutrição.
Usa checkpoint independente e a rotina central de deduplicação/salvamento da Máquina 1.
"""
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from fontes_academicas import (
    acesso_reservado_maquina2, carregar_fonte, fase_final_comprovada,
    nomes_da_lista, periodo_academico, url_permitida,
)
from scraper import (
    ESTADOS, ORIGEM_IES, SupabaseRepo, alias_instituicao, agrupar_faculdades,
    buscar_web, limpar_espacos, normalizar, ordem_estado, salvar_lead, stats,
)

ETAPA = "captacao_maquina3_formandos_v2"
MAX_FACULDADES = 5
MAX_RESULTADOS_BUSCA = 6
MAX_FONTES_POR_CONSULTA = 2
TOTAL_CONSULTAS = 6


def consultas_lote(item):
    nome = limpar_espacos(item.get("instituicao"))
    alias = limpar_espacos(alias_instituicao(item) or "")
    termos = list(dict.fromkeys(t for t in (alias, nome) if t))
    termo = ' OR '.join('"'+t.replace('"', '')+'"' for t in termos)
    uf = limpar_espacos(item.get("estado") or "")
    return [
        f'{termo} Nutrição formandos OR concluintes 2025 lista nomes formatura',
        f'{termo} Nutrição "colação de grau" OR formatura 2025 2026 concluintes nomes',
        f'{termo} Nutrição alunos "último semestre" OR "último período" 2026 {uf}',
        f'{termo} Nutrição "8º semestre" OR "8º período" "2026/1" formandos concluintes {uf}',
        f'site:instagram.com ("{nome}" OR "{alias}") Nutrição formandos OR formatura 2025 2026',
        f'site:instagram.com ("{nome}" OR "{alias}") Nutrição alunos concluintes "último semestre" OR "2026/1"',
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
                r"\b(?:a\s+aluna|o\s+aluno|aluna|aluno|formanda|formando|estudante|egressa|egresso)\s+"
                r"([A-ZÀ-Ý][A-Za-zÀ-ÿ'’-]+(?:\s+(?:de|da|do|dos|das|e)?\s*[A-ZÀ-Ý][A-Za-zÀ-ÿ'’-]+){1,6})\b",
                campo, re.I,
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


def etapa_item(item):
    return f"{ETAPA}_faculdade_{item['id']}"


def carregar_fila(repo):
    registros = []
    offset = 0
    while True:
        lote = (repo.client.table("instituicoes_nutricao").select("*")
                .eq("origem", ORIGEM_IES).order("id")
                .range(offset, offset + 999).execute()).data or []
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
    uf = min(((x.get("estado") or "") for x in pendentes), key=ordem_estado)
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

    for idx in range(inicio, len(consultas)):
        consulta = consultas[idx]
        salvar_checkpoint(repo, item, "processando", idx, consulta,
                          encontrados=encontrados,
                          salvos=int(cp.get("leads_salvos") or 0) + stats["leads_salvos"] - salvos_antes)
        resultados = buscar_web(consulta, max_results=MAX_RESULTADOS_BUSCA)
        if resultados is None:
            salvar_checkpoint(repo, item, "erro", idx, consulta,
                              "Buscador indisponível; consulta preservada",
                              encontrados, int(cp.get("leads_salvos") or 0) + stats["leads_salvos"] - salvos_antes)
            return False

        urls = []
        for resultado in resultados:
            url = str(resultado.get("href") or resultado.get("url") or "")
            if acesso_reservado_maquina2(url):
                for registro in candidatos_instagram_publico(resultado, item):
                    encontrados += 1
                    stats["leads_encontrados"] += 1
                    salvar_lead(
                        repo, registro["nome"], item["instituicao"], cidade,
                        item.get("estado"), registro["evidencia"], registro["fonte_url"],
                        ano_forcado=registro["ano"], periodo_forcado=registro["periodo"],
                        instituicao_alias=alias,
                        candidato_indicio=registro["candidato_indicio"],
                    )
                continue
            if not url_permitida(url):
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


if __name__ == "__main__":
    executar()
