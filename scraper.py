import os
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

lead = {
    "nome": "teste automacao github",
    "instagram": "@teste_automacao",
    "nicho": "teste"
}

resultado = supabase.table("leads").insert(lead).execute()

print("Lead inserido com sucesso!")
print(resultado.data)
