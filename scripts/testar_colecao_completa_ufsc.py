"""Lê todas as páginas dos TCCs 2025/2026 e grava nomes com confirmação real."""
import json,signal,sys,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import requests
import scraper as s
from colecoes_academicas import ler_colecao
inicio=time.monotonic()
signal.signal(signal.SIGALRM,lambda *a:(_ for _ in ()).throw(TimeoutError('Limite de seis minutos de pesquisa')))
signal.alarm(360)
repo=s.SupabaseRepo.from_env(); documentos={}; paginas=[]; emails_publicos=set(); totais={}; nomes={}; novos=[]; existentes=[]
for ano in (2025,2026):
    url=f'https://repositorio.ufsc.br/handle/123456789/7441/discover?filtertype=dateIssued&filter_relational_operator=equals&filter={ano}&rpp=40'
    fila=[url]; vistas=set(); docs_ano=set()
    while fila:
        atual=fila.pop(0)
        if atual in vistas: continue
        assert urlparse(atual).hostname=='repositorio.ufsc.br'
        vistas.add(atual)
        origem_leitura='acesso_direto_github'; url_final=atual
        try:
            resposta=requests.get(atual,timeout=(10,25)); resposta.raise_for_status()
            from lxml import html
            dom=html.fromstring(resposta.content)
            emails_publicos.update(a[7:].split('?')[0] for a in dom.xpath('//a[starts-with(@href,"mailto:")]/@href'))
            resultado=ler_colecao(resposta.text,resposta.url,'Universidade Federal de Santa Catarina','UFSC')
            url_final=resposta.url
        except requests.RequestException as erro:
            copia=json.loads((Path(__file__).resolve().parents[1]/'fontes_publicas/ufsc_tcc_2025_2026.json').read_text())
            fonte=next(p for p in copia['paginas'] if p['ano']==ano and p['url']==atual)
            idade=(datetime.now(timezone.utc)-datetime.fromisoformat(fonte['coletado_em'])).total_seconds()
            assert 0<=idade<=86400,'Leitura pública expirada; coletar novamente'
            resultado=fonte['resultado']; origem_leitura='copia_de_leitura_publica_real_feita_no_ambiente_de_pesquisa'
            print('ACESSO DIRETO INDISPONIVEL',json.dumps(dict(url=atual,erro=type(erro).__name__,coletado_em=fonte['coletado_em'],alternativa=origem_leitura),ensure_ascii=False),flush=True)
        assert resultado['total'] is not None,'A página não confirmou total da coleção filtrada'
        if ano not in totais: totais[ano]=resultado['total']
        assert resultado['total']==totais[ano],'Total mudou durante a leitura'
        paginas.append(dict(ano=ano,url=url_final,origem_leitura=origem_leitura,documentos=len(resultado['documentos']),total=resultado['total']))
        print('PAGINA DA COLECAO',json.dumps(paginas[-1],ensure_ascii=False),flush=True)
        for doc in resultado['documentos']:
            assert all(r['ano']==ano for r in doc['registros']),'Filtro de ano não foi respeitado'
            docs_ano.add(doc['fonte']); documentos[doc['fonte']]=doc
            for r in doc['registros']:
                chave=s.normalizar(r['nome']); nomes[chave]=r
                salvo=s.salvar_lead(repo,r['nome'],r['instituicao'],None,None,r['evidencia'],r['fonte_url'],ano_forcado=r['ano'],periodo_forcado=r['periodo'],instituicao_alias='UFSC')
                assert repo.lead_existe(r['nome'],r['instituicao']), 'Lead não confirmado após gravação/deduplicação'
                row=repo.lead_da_fonte(r['nome'],r['fonte_url'])
                registro=dict(nome=r['nome'],ano=r['ano'],fonte=r['fonte_url'],id=row['id'] if row else None)
                (novos if salvo else existentes).append(registro)
        fila.extend(u for u in resultado['proximas'] if u not in vistas)
    assert len(docs_ano)==totais[ano],f'Coleção incompleta em {ano}: {len(docs_ano)}/{totais[ano]}'
# Repetir a gravação de todos os nomes sem criar novos registros.
releituras=0
for r in nomes.values():
    assert not s.salvar_lead(repo,r['nome'],r['instituicao'],None,None,r['evidencia'],r['fonte_url'],ano_forcado=r['ano'],periodo_forcado=r['periodo'],instituicao_alias='UFSC')
    assert repo.lead_existe(r['nome'],r['instituicao'])
    releituras+=1
print('RESULTADO COLECAO COMPLETA',json.dumps(dict(segundos=round(time.monotonic()-inicio,1),paginas=paginas,emails_publicos_nas_listagens=sorted(emails_publicos),emails_nao_associados_sem_evidencia=True,documentos_por_ano=totais,nomes_unicos=len(nomes),novos_confirmados=novos,existentes_confirmados=existentes,releituras_duplicadas_bloqueadas=releituras,autores_sem_nome_completo=[dict(fonte=d['fonte'],nomes=d['autores_sem_nome_completo']) for d in documentos.values() if d['autores_sem_nome_completo']],escopo='coleção de TCCs de Nutrição da UFSC 2025/2026; não representa total de formados'),ensure_ascii=False),flush=True)
