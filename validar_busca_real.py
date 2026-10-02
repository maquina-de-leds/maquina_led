from scraper import buscar_web
queries=['"Unochapecó" Nutrição "formandos" 2025 -site:linkedin.com','"UniAteneu" Nutrição "formandos" 2026 -site:linkedin.com']
for query in queries:
    results=buscar_web(query,max_results=5)
    print("BUSCA REAL:",query,flush=True)
    if results is None:raise RuntimeError("buscador indisponível")
    print("RESULTADOS:",len(results),[(x.get("title"),x.get("href") or x.get("url")) for x in results],flush=True)
