"""Audita nomes, evidências e URLs sem alterar registros."""
import os,json
from supabase import create_client
c=create_client(os.environ["SUPABASE_URL"],os.environ["SUPABASE_KEY"])
rows=c.table("leds").select("nome,instituicao,fonte_url,evidencia,ano_alvo,periodo_alvo,nao_contatar").ilike("instituicao","%Mackenzie%").order("id").execute().data or []
print("AUDITORIA BASE:",json.dumps(rows,ensure_ascii=False),flush=True)

cp=c.table("controle_busca").select("etapa,status,indice_pesquisa,total_pesquisas,consulta_atual,ultimo_erro,leads_encontrados,leads_salvos,atualizado_em").ilike("etapa","%mackenzie_completo_37054476838%").execute().data or []
print("PROGRESSO DA BUSCA:",json.dumps(cp,ensure_ascii=False),flush=True)
