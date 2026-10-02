"""Bloqueio reversível de rótulos confirmados e variação repetida, sem excluir pessoas."""
import os
from supabase import create_client
c=create_client(os.environ["SUPABASE_URL"],os.environ["SUPABASE_KEY"])
ies="Universidade Presbiteriana Mackenzie"
casos=[("Avaliações e Premiações","https://www.mackenzie.br/graduacao/sao-paulo-higienopolis/nutricao"),("Currículo Lattes","https://www.mackenzie.br/graduacao/sao-paulo-higienopolis/nutricao"),("Victoria Barbosa D Avila C","https://www.mackenzie.br/universidade/unidades-academicas/ccbs/tcc-e-pesquisa/mostra-de-tcc")]
for nome,url in casos:
    if nome=="Victoria Barbosa D Avila C":
        canonical=c.table("leds").select("id").eq("instituicao",ies).ilike("nome","Victoria Barbosa d Avila").execute().data
        assert canonical,"Nome correto deve existir antes do bloqueio da variação"
    rows=c.table("leds").select("id,nome").eq("instituicao",ies).eq("nome",nome).eq("fonte_url",url).execute().data or []
    for row in rows:
        c.table("leds").update({"nao_contatar":True,"qualificado":False,"proxima_acao":"revisar_nome_extraido"}).eq("id",row["id"]).execute()
        check=c.table("leds").select("nao_contatar,qualificado").eq("id",row["id"]).execute().data[0]
        assert check["nao_contatar"] and not check["qualificado"]
        print("BLOQUEIO CONFIRMADO:",nome,flush=True)
