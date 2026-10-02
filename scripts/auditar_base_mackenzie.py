"""Audita nomes, evidências e URLs sem alterar registros."""
import os,json
from supabase import create_client
c=create_client(os.environ["SUPABASE_URL"],os.environ["SUPABASE_KEY"])
rows=c.table("leds").select("nome,instituicao,fonte_url,evidencia,ano_alvo,periodo_alvo,nao_contatar").ilike("instituicao","%Mackenzie%").order("id").execute().data or []
print("AUDITORIA BASE:",json.dumps(rows,ensure_ascii=False),flush=True)
