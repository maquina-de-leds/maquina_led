"""Autores de coleções públicas DSpace de TCC de Nutrição, com data por item."""
import re
from urllib.parse import urljoin,urlparse
from lxml import html
from fontes_academicas import norm,pessoa,periodo_academico,url_permitida

def ler_colecao(pagina,url,instituicao,alias=None):
    pagina=re.sub(r'^\s*<\?xml\b[^?]*\?>','',pagina,count=1,flags=re.I)
    raiz=html.fromstring(pagina)
    texto=norm(raiz.text_content())
    titulos=[norm(t) for t in raiz.xpath('//h1/text()')]
    if 'tcc nutricao' not in titulos and not re.search(r'results for collection:\s*tcc nutricao',texto):
        return dict(documentos=[],proximas=[],total=None)
    host=(urlparse(url).hostname or '').lower()
    vinculada=norm(instituicao) in texto or bool(alias and norm(alias) in host.split('.'))
    documentos=[]
    for node in raiz.xpath('//div[contains(concat(" ",normalize-space(@class)," ")," artifact-description ")]'):
        hrefs=node.xpath('.//div[contains(concat(" ",normalize-space(@class)," ")," artifact-title ")]//a/@href')
        if not hrefs: continue
        fonte=urljoin(url,hrefs[0])
        if not url_permitida(fonte) or urlparse(fonte).hostname!=host: continue
        titulo=' '.join(node.xpath('.//div[contains(concat(" ",normalize-space(@class)," ")," artifact-title ")]//a//text()')).strip()
        data=' '.join(node.xpath('.//span[contains(concat(" ",normalize-space(@class)," ")," date ")]//text()')).strip()
        ano,periodo=periodo_academico(data)
        if ano not in {2025,2026}: continue
        autores=node.xpath('.//span[contains(concat(" ",normalize-space(@class)," ")," author ")]/span/text()')
        if not autores:
            autores=[a.strip() for a in ';'.join(node.xpath('.//span[@class="author"]/text()')).split(';') if a.strip()]
        nomes=[pessoa(a.strip()) for a in autores]
        registros=[dict(nome=n,ano=ano,periodo=periodo,instagram=None,instituicao=instituicao if vinculada else None,
                        fonte_url=fonte,evidencia=f'Coleção TCC Nutrição | Autor do TCC de graduação | {titulo} | Data do item: {data} | {url}',
                        contexto_academico=f'TCC Nutrição | {titulo} | {data}') for n in nomes if n]
        documentos.append(dict(fonte=fonte,titulo=titulo,data=data,registros=registros,autores_sem_nome_completo=[a for a,n in zip(autores,nomes) if not n]))
    total=re.search(r'showing\s+\d+\s+out of a total of\s+(\d+)\s+results for collection:\s*tcc nutricao',texto)
    proximas=[]
    for a in raiz.xpath('//a[@href]'):
        if norm(a.text_content()) not in {'next page','proxima pagina','próxima página'}: continue
        alvo=urljoin(url,a.get('href'))
        if url_permitida(alvo) and urlparse(alvo).hostname==host and alvo not in proximas: proximas.append(alvo)
    return dict(documentos=documentos,proximas=proximas,total=int(total.group(1)) if total else None)
