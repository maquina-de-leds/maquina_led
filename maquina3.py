"""Máquina 3: varredura em lote de listas públicas de formandos de Nutrição.
Usa checkpoint independente e a rotina central de deduplicação/salvamento da Máquina 1.
"""
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from fontes_academicas import acesso_reservado_maquina2, carregar_fonte, url_permitida
from scraper import (
    ESTADOS, ORIGEM_IES, SupabaseRepo, alias_instituicao, agrupar_faculdades,
    buscar_web, limpar_espacos, normalizar, ordem_estado, salvar_lead, stats,
)

ETAPA = "captacao_maquina3_formandos_v1"
MAX_FACULDADES = 5
MAX_RESULTADOS_BUSCA = 6
MAX_FONTES_POR_CONSULTA = 2
TOTAL_CONSULTAS = 4


def consultas_lote(item):
    nome = limpar_espacos(item.get("instituicao"))
    alias = limpar_espacos(alias_instituicao(item) or "")
    termos = list(dict.fromkeys(t for t in (alias, nome) if t))
    termo = ' OR '.join('"'+t.replace('"', '')+'"' for t in termos)
    uf = limpar_espacos(item.get("estado") or "")
    return [
        f'{termo} Nutrição formandos 2025 lista nomes',
        f'{termo} Nutrição "colação de grau" 2025 formandos',
        f'{termo} Nutrição concluintes 2026 formatura nomes',
        f'{termo} Nutrição "2026/1" formandos OR concluintes {uf}',
    ]


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
    uf = min((x.get("estado") or "") for x in pendentes, key=ordem_estado)
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
            if not url_permitida(url) or acesso_reservado_maquina2(url):
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
            cp = item.get("_m3_cp") or {}
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
