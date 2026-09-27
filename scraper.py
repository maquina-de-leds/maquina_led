import os
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def lead_ja_existe(instagram):
    resposta = (
        supabase
        .table("leds")
        .select("id, instagram")
        .eq("instagram", instagram)
        .limit(1)
        .execute()
    )

    return len(resposta.data) > 0


def salvar_lead(lead):
    instagram = lead.get("instagram")

    if not instagram:
        print("Lead ignorado: sem Instagram.")
        return

    if lead_ja_existe(instagram):
        print(f"Duplicado ignorado: {instagram}")
        return

    resultado = (
        supabase
        .table("leds")
        .insert(lead)
        .execute()
    )

    print(f"Lead salvo: {instagram}")
    print(resultado.data)


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

print("Processamento concluido.")
