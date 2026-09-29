import os
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

salvos = 0
duplicados = 0
erros = 0


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
        print(f"Erro ao verificar {instagram}: {e}")
        return False


def salvar_lead(lead):
    global salvos, duplicados, erros

    instagram = lead.get("instagram")

    if not instagram:
        print("Lead ignorado: sem Instagram.")
        erros += 1
        return

    try:
        if lead_ja_existe(instagram):
            print(f"Duplicado ignorado: {instagram}")
            duplicados += 1
            return

        supabase.table("leds").insert(lead).execute()

        print(f"Lead salvo: {instagram}")
        salvos += 1

    except Exception as e:
        print(f"Erro ao salvar {instagram}: {e}")
        erros += 1


leads_encontrados = [
    {
        "nome": "Nutricionista Teste 1",
        "instagram": "@nutri_teste_1",
        "whatsapp": None,
        "nicho": "nutricionista",
        "origem": "teste_automacao",
        "status": "novo",
        "app_baixado": False
    },
    {
        "nome": "Nutricionista Teste 2",
        "instagram": "@nutri_teste_2",
        "whatsapp": None,
        "nicho": "nutricionista",
        "origem": "teste_automacao",
        "status": "novo",
        "app_baixado": False
    }
]

for lead in leads_encontrados:
    salvar_lead(lead)

print("")
print("===== RESUMO =====")
print(f"Leads salvos: {salvos}")
print(f"Duplicados ignorados: {duplicados}")
print(f"Erros: {erros}")
print("==================")
print("Processamento concluido.")
