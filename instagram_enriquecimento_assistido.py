"""Fila assistida para pesquisar perfis manualmente no Instagram.

Este módulo não acessa nem coleta dados do Instagram. Ele prepara consultas
para revisão humana e grava apenas os arrobas copiados e confirmados pelo
operador na tabela instagram_candidatos.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote_plus, urlparse

HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
SEARCH_BASE = "https://www.instagram.com/explore/search/keyword/?q="
QUEUE_TABLE = "instagram_buscas"
CANDIDATE_TABLE = "instagram_candidatos"
LEADS_TABLE = "leds"


def normalizar_handle(valor: str | None) -> str | None:
    if not valor:
        return None
    handle = valor.strip()
    if "instagram.com/" in handle.lower():
        parsed = urlparse(handle if "://" in handle else "https://" + handle)
        if parsed.hostname and (parsed.hostname == "instagram.com" or parsed.hostname.endswith(".instagram.com")):
            handle = parsed.path.strip("/").split("/", 1)[0]
    handle = handle.removeprefix("@").strip()
    if not HANDLE_RE.fullmatch(handle):
        raise ValueError(f"Arroba inválido: {valor!r}")
    return "@" + handle.lower()


def consulta_instagram(nome: str) -> str:
    nome = " ".join((nome or "").split())
    if not nome:
        raise ValueError("O lead precisa ter nome para gerar a pesquisa.")
    return f"{nome} nutrição"


def url_pesquisa_instagram(consulta: str) -> str:
    return SEARCH_BASE + quote_plus(consulta)


def elegivel(lead: dict) -> bool:
    """Não toca em leads já enriquecidos, não qualificados ou com opt-out."""
    if lead.get("instagram") or lead.get("instagram_url"):
        return False
    if lead.get("qualificado") is not True:
        return False
    if lead.get("nao_contatar") is True or lead.get("não_contatar") is True:
        return False
    return bool(str(lead.get("nome") or "").strip())


def linha_de_busca(lead: dict) -> dict:
    consulta = consulta_instagram(str(lead.get("nome") or ""))
    return {
        "busca_id": lead.get("busca_id", ""),
        "lead_id": lead.get("id", ""),
        "nome_pesquisado": lead.get("nome") or "",
        "instituicao": lead.get("instituicao") or "",
        "cidade": lead.get("cidade") or "",
        "estado": lead.get("estado") or "",
        "consulta": consulta,
        "instagram_search_url": url_pesquisa_instagram(consulta),
        "nome_perfil": "",
        "instagram": "",
        "instagram_url": "",
        "observacao": "",
    }


def gravar_csv(path: str | Path, linhas: list[dict]) -> None:
    campos = [
        "busca_id", "lead_id", "nome_pesquisado", "instituicao", "cidade",
        "estado", "consulta", "instagram_search_url", "nome_perfil",
        "instagram", "instagram_url", "observacao",
    ]
    with open(path, "w", newline="", encoding="utf-8-sig") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=campos)
        writer.writeheader()
        writer.writerows(linhas)


def ler_resultados(path: str | Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as arquivo:
        leitor = csv.DictReader(arquivo)
        necessarios = {"busca_id", "lead_id", "consulta", "instagram"}
        if not leitor.fieldnames or not necessarios.issubset(leitor.fieldnames):
            raise ValueError("CSV precisa conter busca_id, lead_id, consulta e instagram.")
        linhas = []
        for numero, row in enumerate(leitor, start=2):
            row["busca_id"] = str(row.get("busca_id") or "").strip()
            row["lead_id"] = str(row.get("lead_id") or "").strip()
            if not row["busca_id"] or not row["lead_id"]:
                raise ValueError(f"Linha {numero}: busca_id e lead_id são obrigatórios.")
            raw = str(row.get("instagram") or "").strip()
            row["instagram"] = normalizar_handle(raw) if raw else ""
            if row["instagram"] and not str(row.get("instagram_url") or "").strip():
                row["instagram_url"] = "https://www.instagram.com/" + row["instagram"][1:] + "/"
            linhas.append(row)
        return linhas


def agrupar_por_busca(linhas: list[dict]) -> dict[str, list[dict]]:
    grupos: dict[str, list[dict]] = {}
    for linha in linhas:
        grupos.setdefault(str(linha["busca_id"]), []).append(linha)
    return grupos


def handle_ja_no_cadastro(supabase, handle: str) -> bool:
    """Evita duplicar no destino um arroba já presente na tabela original."""
    resposta = (supabase.table(LEADS_TABLE).select("instagram")
               .ilike("instagram", handle).limit(20).execute())
    for row in resposta.data or []:
        try:
            if normalizar_handle(row.get("instagram")) == handle:
                return True
        except ValueError:
            continue
    return False


def conectar_supabase():
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def exportar(supabase, destino: str, limite: int = 25) -> int:
    """Cria buscas para leads pendentes, sem alterar a tabela original."""
    resposta = (
        supabase.table(LEADS_TABLE)
        .select("id,nome,instagram,instagram_url,qualificado,nao_contatar,não_contatar,instituicao,cidade,estado")
        .eq("qualificado", True)
        .is_("instagram", "null")
        .order("id")
        .limit(max(limite * 4, limite))
        .execute()
    )
    leads = [lead for lead in (resposta.data or []) if elegivel(lead)][:limite]
    if not leads:
        gravar_csv(destino, [])
        return 0

    ids = [int(lead["id"]) for lead in leads]
    buscas_existentes = (
        supabase.table(QUEUE_TABLE).select("id,lead_origem_id,status")
        .in_("lead_origem_id", ids).execute().data or []
    )
    por_lead = {str(row["lead_origem_id"]): row for row in buscas_existentes}
    novos = []
    for lead in leads:
        if str(lead["id"]) in por_lead:
            continue
        consulta = consulta_instagram(lead["nome"])
        novos.append({
            "lead_origem_id": lead["id"],
            "nome_pesquisado": lead["nome"],
            "consulta": consulta,
            "instagram_search_url": url_pesquisa_instagram(consulta),
            "status": "pendente",
        })
    if novos:
        supabase.table(QUEUE_TABLE).insert(novos).execute()

    pendentes = (
        supabase.table(QUEUE_TABLE)
        .select("id,lead_origem_id,nome_pesquisado,consulta")
        .eq("status", "pendente")
        .order("id")
        .limit(limite)
        .execute().data or []
    )
    linhas = []
    for busca in pendentes:
        linha = linha_de_busca({
            "busca_id": busca["id"], "id": busca["lead_origem_id"],
            "nome": busca["nome_pesquisado"],
        })
        linha["consulta"] = busca["consulta"]
        linha["instagram_search_url"] = url_pesquisa_instagram(busca["consulta"])
        linhas.append(linha)
    gravar_csv(destino, linhas)
    return len(linhas)


def importar(supabase, origem: str) -> dict[str, int]:
    """Grava perfis copiados pelo operador; mantém os dados originais intactos."""
    linhas = ler_resultados(origem)
    grupos = agrupar_por_busca(linhas)
    salvos = duplicados = sem_resultado = rejeitados = 0
    busca_ids = [int(v) for v in grupos]
    buscas = (
        supabase.table(QUEUE_TABLE)
        .select("id,lead_origem_id,nome_pesquisado,consulta,status")
        .in_("id", busca_ids).execute().data or []
    )
    busca_por_id = {str(row["id"]): row for row in buscas}

    for busca_id, resultados in grupos.items():
        busca = busca_por_id.get(busca_id)
        if not busca or busca.get("status") not in ("pendente", "em_pesquisa"):
            rejeitados += len([r for r in resultados if r.get("instagram")])
            continue
        lead_id = int(busca["lead_origem_id"])
        if any(int(r["lead_id"]) != lead_id for r in resultados):
            raise ValueError(f"A busca {busca_id} está vinculada a outro lead.")
        lead = (supabase.table(LEADS_TABLE).select("id,nome,instagram,instagram_url,qualificado,nao_contatar,não_contatar")
                .eq("id", lead_id).limit(1).execute().data or [])
        if not lead or not elegivel(lead[0]):
            rejeitados += len([r for r in resultados if r.get("instagram")])
            supabase.table(QUEUE_TABLE).update({"status": "descartada"}).eq("id", int(busca_id)).execute()
            continue

        for resultado in resultados:
            handle = resultado.get("instagram")
            if not handle:
                continue
            if handle_ja_no_cadastro(supabase, handle):
                duplicados += 1
                continue
            row = {
                "lead_origem_id": lead_id,
                "nome_pesquisado": busca["nome_pesquisado"],
                "nome_perfil": str(resultado.get("nome_perfil") or "").strip() or None,
                "instagram": handle,
                "instagram_url": str(resultado.get("instagram_url") or "").strip() or f"https://www.instagram.com/{handle[1:]}/",
                "consulta": busca["consulta"],
                "fonte_url": str(resultado.get("instagram_url") or "").strip() or f"https://www.instagram.com/{handle[1:]}/",
                "status": "revisar",
                "observacao": str(resultado.get("observacao") or "").strip() or None,
            }
            try:
                supabase.table(CANDIDATE_TABLE).insert(row).execute()
                salvos += 1
            except Exception as erro:
                mensagem = str(erro).lower()
                if "23505" in mensagem or "duplicate" in mensagem or "unique" in mensagem:
                    duplicados += 1
                else:
                    raise
        status = "resultados_salvos" if any(r.get("instagram") for r in resultados) else "sem_resultado"
        supabase.table(QUEUE_TABLE).update({"status": status}).eq("id", int(busca_id)).execute()
        if status == "sem_resultado":
            sem_resultado += 1
    return {"salvos": salvos, "duplicados": duplicados, "sem_resultado": sem_resultado, "rejeitados": rejeitados}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enriquecimento assistido de leads com pesquisa manual no Instagram.")
    sub = parser.add_subparsers(dest="acao", required=True)
    cmd_exportar = sub.add_parser("exportar", help="prepara CSV de buscas pendentes")
    cmd_exportar.add_argument("--saida", default="fila_instagram.csv")
    cmd_exportar.add_argument("--limite", type=int, default=25)
    cmd_importar = sub.add_parser("importar", help="salva perfis copiados do Instagram")
    cmd_importar.add_argument("csv", help="CSV preenchido pelo operador")
    args = parser.parse_args(argv)
    try:
        banco = conectar_supabase()
        if args.acao == "exportar":
            total = exportar(banco, args.saida, args.limite)
            print(f"Buscas exportadas: {total} — arquivo: {args.saida}")
        else:
            resumo = importar(banco, args.csv)
            print("Importação concluída: " + ", ".join(f"{k}={v}" for k, v in resumo.items()))
    except Exception as erro:
        print(f"Erro no enriquecimento assistido: {erro}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
