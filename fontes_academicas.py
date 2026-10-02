"""Captação pública de pessoas em fontes acadêmicas HTML/PDF, sem redes auxiliares."""
import io
import ipaddress
import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

ANOS = {2025, 2026}
OUTROS_CURSOS = r'educacao fisica|enfermagem|fisioterapia|psicologia|medicina|direito|engenharia|farmacia|pedagogia|letras|biomedicina'
FASE = r'graduand[oa]s?|tcc|trabalho de conclusao|formand[oa]s?|concluintes?|colacao|outorga|formatura|recem[- ]formad[oa]s?|ultimo (?:periodo|semestre)|estagio final|conclusao|alun[oa]s?|discentes?|estudantes?|academic[oa]s?|apresentacao de trabalho|jornada academica|grupo de (?:alunos|estudantes|estudos)|liga academica|centro academico'
PAPEL = r'orientador|coorientador|professor|docente|coordenador|paraninf|patron|reitor|banca'


def norm(text):
    text = unicodedata.normalize('NFKD', str(text or '').lower())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', re.sub('[‐‑‒–—−]', '-', text)).strip()


def url_permitida(url):
    p = urlparse(url)
    host = (p.hostname or '').lower()
    if p.scheme not in {'http', 'https'} or not host or p.username or p.password:
        return False
    if host in {'localhost', 'metadata.google.internal'} or host.endswith('.local'):
        return False
    try:
        if not ipaddress.ip_address(host).is_global: return False
    except ValueError:
        pass
    return True


class Pagina(HTMLParser):
    def __init__(self):
        super().__init__()
        self.linhas, self.links, self.metas = [], [], {}
        self.bloco, self.partes, self.skip = None, [], 0
        self.textos = []
        self.skip_stack = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        void = {'img','br','hr','input','meta','link','source','wbr','area','base','embed','param','track','col'}
        if self.skip_stack:
            if tag not in void: self.skip_stack.append(tag)
            return
        region = ' '.join([a.get('class') or '',a.get('id') or '',a.get('role') or '']).lower()
        if tag in {'script','style','nav','footer'} or re.search(r'(?:^|[\s_-])(?:menu|navbar|sidebar|cookie|navigation|rodape)(?:$|[\s_-])',region):
            if tag not in void: self.skip_stack.append(tag)
            return
        if tag == 'meta':
            self.metas.setdefault(a.get('name', a.get('property', '')).lower(), []).append(a.get('content', ''))
        if tag == 'img' and a.get('alt'): self.textos.append(a['alt'])
        if tag == 'a' and a.get('href'):
            self.links.append(a['href'])
            if self.bloco and 'instagram.com/' in a['href']:
                self.partes.append(' ' + a['href'] + ' ')
        if tag in {'p', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'title', 'dt', 'dd'} and self.bloco is None:
            self.bloco, self.partes = tag, []
        if tag in {'br', 'td', 'th'} and self.bloco: self.partes.append(' | ')
    def handle_data(self, data):
        if self.skip_stack: return
        if data.strip().lower() in {'instagram','ver instagram','perfil instagram'}: return
        self.textos.append(data)
        if self.bloco: self.partes.append(data)
        elif data.strip(): self.linhas.append((' '.join(data.split()), 'text'))
    def handle_endtag(self, tag):
        if self.skip_stack:
            if tag in self.skip_stack:
                while self.skip_stack:
                    if self.skip_stack.pop() == tag: break
            return
        if self.bloco == tag:
            self.linhas.append((' '.join(''.join(self.partes).split()), tag))
            self.bloco, self.partes = None, []


def periodo_academico(text):
    """Prefere referência à turma ao ano de publicação da notícia."""
    n = norm(text)
    patterns = [
        r'(?:referente|turma|formandos|concluintes|nutricao)[^.\n]{0,70}?([12])o?\s*semestre(?:\s+letivo)?\s*(?:de|/)?\s*(202[56])',
        r'(?:referente|turma|formandos|concluintes|nutricao)[^.\n]{0,70}?(202[56])[./-]([12])\b',
        r'\bsemestre\s+(202[56])[./-]([12])\b',
    ]
    for i, pattern in enumerate(patterns):
        m = re.search(pattern, n)
        if m:
            semester, year = (m.group(1), m.group(2)) if i == 0 else (m.group(2), m.group(1))
            return int(year), f'{year}/{semester}'
    years = set(re.findall(r'\b(20\d{2})\b', n))
    if len(years) == 1 and int(next(iter(years))) in ANOS:
        year = int(next(iter(years)))
        return year, f'{year} (semestre não informado)'
    return None, None


def pessoa(text):
    text = re.sub(r'^\s*(?:\d+[.)\-–]?\s*|e\s+)', '', text).strip(' |:;,.–-')
    if ',' in text:
        parts = text.split(',')
        if len(parts) == 2: text = parts[1].strip() + ' ' + parts[0].strip()
    words = text.split()
    if not 2 <= len(words) <= 9 or re.search(r'[\d@/:()]', text): return None
    n = norm(text)
    if re.search(r'\b(?:industria|alimentos|mercado|clinica|esportiva|coletiva|avaliacoes|premiacoes|curriculo|lattes|centro|universitario|assuntos|relacionados|laboratorio|estilo|sou|medical|office|trabalhe|conosco|graduacao|sanguineo|ensino|pagina|privacidade|cookies?|processos|seletivos|pesquisa|extensao|regulamentos|normas|diretorio|empresa|grupo|liga|turma|membros|integrantes|participantes|procedimentos|matricula|calendario|acesso|contato|inicio|inscricao)\b',n): return None
    if re.search(r'\b(?:'+PAPEL+r'|curso|nutricao|universidade|faculdade|instituto|secretaria|trabalho|tema|titulo|mostra|sessao|avaliação|saude|alimentacao|nutricional|estudantes|formandos)\w*\b', n): return None
    primary = [w for w in words if norm(w) not in {'de','da','do','dos','das','e'}]
    if len(primary) < 2 or any(not w[0].isupper() for w in primary): return None
    if not all(re.fullmatch(r"[A-Za-zÀ-ÿ'’-]+", w) for w in words): return None
    return text


def nomes_da_lista(text):
    # Conjunção separa pessoas somente quando ambos os lados são nomes completos.
    out = []
    role_section = False
    for part in re.split(r';|\s*\|\s*|,', text):
        part = re.sub(r'^\s*e\s+', '', part).strip()
        pair = re.split(r'\s+e\s+', part)
        if len(pair) > 1 and all(pessoa(x) for x in pair): out.extend(pessoa(x) for x in pair)
        elif pessoa(part): out.append(pessoa(part))
    return out


def instagram_associado(text, nome):
    # Nunca atribui o Instagram institucional ou o de outra pessoa da lista.
    cleaned = re.sub(r'https?://\S+|@[\w.]+', '', text)
    candidates = nomes_da_lista(re.sub(r'^(?:autores?|alun[oa]s?|formand[oa]s?|discentes?)\s*:\s*', '', cleaned, flags=re.I))
    if len(candidates) != 1 or norm(candidates[0]) != norm(nome): return None
    handles = re.findall(r'(?:instagram\.com/|(?<![\w.])@)([A-Za-z0-9._]{1,30})', text)
    handles = [h.lower().rstrip('.') for h in handles if h.lower() not in {'p','reel','reels','stories','explore','accounts'}]
    return '@'+handles[0] if len(set(handles)) == 1 else None


def extrair_documento(linhas, instituicao, alias=None, texto_vinculo='', metas=None):
    metas = metas or {}
    full = '\n'.join(x[0] for x in linhas)
    branded = norm(texto_vinculo + ' ' + full)
    inst = norm(instituicao)
    if inst == 'universidade federal de mato grosso':
        branded = branded.replace('universidade federal de mato grosso do sul', '')
    related = bool(inst and re.search(r'(?<!\w)'+re.escape(inst)+r'(?!\w)', branded))
    if alias:
        related = related or bool(re.search(r'(?<!\w)'+re.escape(norm(alias))+r'(?!\w)', branded))
    if not related and inst: return []
    instituicao = instituicao or 'Faculdade não informada'
    # Sem Nutrição + fase acadêmica não há extração de pessoas.
    if 'nutricao' not in norm(full) or not re.search(FASE, norm(full)): return []
    # Apenas texto editorial (sem rodapé) contribui para contexto acadêmico.
    context_lines = [t for t,tag in linhas if tag in {'title','h1','h2','h3','h4','p','meta'}
                     and not re.match(r'^(?:publicado|atualizado|postado)\b',norm(t))]
    if not context_lines:
        context_lines = [t for t,tag in linhas[:20] if tag == 'pdf']
    context = ' '.join(context_lines)
    default_year, default_period = periodo_academico(context)
    publication_year, publication_period = periodo_academico(' '.join(metas.get('article:published_time', []) + metas.get('date', []) + metas.get('citation_publication_date', []) + metas.get('citation_date', [])))
    if not publication_year:
        publication_year, publication_period = periodo_academico(' '.join(t for t,tag in linhas[:30]))
    if not publication_year:
        # Datas editoriais isoladas podem aparecer depois do menu da página.
        # Nunca usa copyright, referências ou uma data arbitrária do texto.
        for texto,_ in linhas:
            if re.fullmatch(r'\s*\d{1,2}\s+(?:de\s+)?(?:jan(?:eiro)?|fev(?:ereiro)?|feb(?:ruary)?|mar(?:ço|ch)?|abr(?:il)?|apr(?:il)?|mai(?:o)?|may|jun(?:ho|e)?|jul(?:ho|y)?|ago(?:sto)?|aug(?:ust)?|set(?:embro)?|sep(?:tember)?|out(?:ubro)?|oct(?:ober)?|nov(?:embro|ember)?|dez(?:embro)?|dec(?:ember)?)\s*(?:de\s*|[•,/-]\s*)?202[56]\s*',texto,re.I):
                publication_year,publication_period=periodo_academico(texto)
                break
    edition=re.search(r'\bv\.?\s*\d+\s*n\.?\s*\d+\s*\((20\d{2})\)',norm(full))
    if edition and int(edition.group(1)) not in ANOS:
        publication_year, publication_period = None, None
    single_course = not re.search(OUTROS_CURSOS, norm(context))
    active = single_course and 'nutricao' in norm(context)
    year, period = default_year, default_period
    mode = 'lista' if active and re.search(r'tcc|trabalho de conclusao|formand|concluint|colacao|outorga|formatura|grupo de (?:alunos|estudantes|estudos)|liga academica|centro academico',norm(' '.join(t for t,tag in linhas if tag in {'title','h1'}))) else None
    out = []
    role_section = False
    def add(name, evidence, y, per):
        if name and y in ANOS:
            phase = 'TCC' if re.search(r'tcc|trabalho de conclusao', norm(evidence+' '+context)) else 'vínculo acadêmico'
            out.append(dict(nome=name, ano=y, periodo=per, instagram=instagram_associado(evidence,name),
                            evidencia=f'{instituicao} | Nutrição | {per} | {phase} | {evidence}',
                            contexto_academico=context))
    if re.search(r'nome completo do aluno.*curso.*nome do orientador',norm(full)):
        table_year, table_period = periodo_academico(' '.join(t for t,tag in linhas[:20]))
        for line,tag in linhas:
            match=re.match(r'^(.+?)\s+CCBS\s+Higienópolis\s+Nutrição\b',line,re.I)
            if match: add(pessoa(match.group(1)),line,table_year,table_period)
        return list({norm(r['nome']):r for r in out}.values())
    # Repositórios institucionais com metadados de autor/data acadêmica.
    meta_text = ' '.join(metas.get('citation_title', []) + metas.get('dc.title', []) + metas.get('dc.description', []))
    dates = metas.get('dc.date.issued', []) + metas.get('citation_date', []) + metas.get('citation_publication_date', [])
    if 'nutricao' in norm(full) and re.search(r'tcc|trabalho de conclusao', norm(full)):
        my, mp = periodo_academico(' '.join(dates))
        for name in metas.get('citation_author', []) + metas.get('dc.contributor.author', []):
            add(pessoa(name), meta_text + ' Autor: ' + name, my, mp)
    for i, (line, tag) in enumerate(linhas):
        n = norm(line)
        if not line: continue
        # Notícias com alunos e orientadores na mesma frase: delimitar os alunos.
        inline = re.search(r'\bas alunas\s+(.+?)\s+e as professoras',line,re.I)
        if inline and 'nutricao' in n:
            for name in nomes_da_lista(inline.group(1)):
                add(name,line,default_year or publication_year,default_period or publication_period)
        # Biografia de autor explicitamente aluno, sem incluir coautores docentes.
        if re.match(r'^(?:graduand[oa]s?|estudante|alun[oa]|academic[oa]|discente)\b',n) and 'nutricao' in n and i:
            previous = linhas[i-1][0].split(instituicao)[0].strip(' ,|-')
            add(pessoa(previous),previous+' | '+line,default_year or publication_year,default_period or publication_period)
        if tag == 'pdf' and pessoa(line):
            seguinte = norm(' '.join(t for t, _ in linhas[i+1:i+4]))
            if re.match(r'(?:'+PAPEL+r')\b',seguinte):
                continue
        if tag in {'h1','h2','h3','h4','dt'}:
            role_section = bool(re.search(PAPEL,n))
        elif len(line)<100 and re.match(r'^(?:professores|docentes|orientadores|coordenadores|banca)\b',n):
            role_section = True
        elif len(line)<100 and re.match(r'^(?:formandos|concluintes|autores|alunos|discentes)\b',n):
            role_section = False
        # Notícias multicurso também publicam linhas como 'Nutrição: Nome'.
        course_list = re.match(r'^Nutrição\s*:\s*(.+)', line, re.I)
        if course_list and not re.search(PAPEL, n):
            if role_section:
                continue
            for name in nomes_da_lista(course_list.group(1)):
                add(name,line,default_year,default_period)
            continue
        # Pessoa explicitamente vinculada ao curso, na própria frase da notícia.
        for sentence in re.split(r'(?<=[.!?])\s+', line):
            if re.search(PAPEL,norm(sentence)) or not re.search(r'formand|concluinte|orador|alun[oa]|estudante|discente|academic[oa]',norm(sentence)):
                continue
            match = re.search(r'\b(?:a|o|aluna|aluno|formanda|formando|estudante|discente|acadêmica|acadêmico)\s+([A-ZÀ-Ý][^,.;:]{2,100}),?\s+d[oa]\s+[Cc]urso\s+de\s+Nutrição\b',sentence)
            if match:
                add(pessoa(match.group(1).strip()),sentence,default_year,default_period)
        if not role_section and not re.search(PAPEL, n):
            recente=re.search(r'\b[Rr]ecém[- ]formad[oa]\s+em\s+Nutrição(?:\s+pel[ao]\s+[^,.;]{1,100})?,\s*([A-ZÀ-Ý][^,.;]{2,100})[,.;]',line)
            if recente:
                y,per=periodo_academico(line)
                y=y or publication_year
                per=per or (f'{y} (notícia de recém-formado; semestre da conclusão não informado)' if y else None)
                add(pessoa(recente.group(1)),line,y,per)
            # Evidência direta individual; não depende de uma lista de turma.
            for sentence in re.split(r'(?<=[.!?])\s+', line):
                match = re.search(r'\b(?:alun[oa]|estudante|discente|acadêmic[oa])\s+([A-ZÀ-Ý][^,.;:]{2,100}?),?\s+(?:d[eoa]\s+(?:curso\s+de\s+)?Nutrição)\b', sentence)
                if match:
                    y, per = periodo_academico(sentence)
                    add(pessoa(match.group(1).strip()), sentence, y or default_year, per or default_period)
        if re.match(r'^(?:referencias|bibliografia|leia tambem|siga-nos|compartilhe)\b',n):
            active, mode = False, None
            continue
        # Mudança explícita de seção/curso impede reaproveitar nomes de outra turma.
        if tag.startswith('h') or (tag in {'pdf','text'} and len(line)<100):
            if re.search(OUTROS_CURSOS, n) and 'nutricao' not in n:
                active, mode = False, None
            if 'nutricao' in n:
                active = True
                local_y, local_p = periodo_academico(line)
                if re.search(r'\b20\d{2}\b', n):
                    year, period = local_y, local_p
                else:
                    year, period = default_year, default_period
                mode = 'lista' if re.search(FASE, n+' '+norm(context)) else None
        # Listas em notícia: o rótulo pode explicitar o curso mesmo numa página multicurso.
        label = re.search(r'(?:formand[oa]s?|concluintes?|alun[oa]s?|discentes?|autores?|integrantes?|membros?|participantes?)[^:]{0,130}:\s*(.+)', line, re.I)
        if label:
            leadin = norm(line[:label.start(1)])
            is_nutrition = 'nutricao' in leadin or (active and not re.search(OUTROS_CURSOS, leadin))
            if is_nutrition and not re.search(PAPEL, leadin):
                local_y, local_p = periodo_academico(line[:label.start(1)])
                y, per = local_y or year, local_p or period
                for name in nomes_da_lista(re.sub(r'https?://\S+|@[\w.]+','',label.group(1))):
                    add(name, line, y, per)
                mode = 'lista'
            continue
        if re.search(PAPEL, n):
            if tag.startswith('h') or (tag in {'pdf','text','dt'} and len(line)<80):
                mode = None
            if n.rstrip(' :') in {'orientador','orientadora','coorientador','coorientadora','banca'}: mode = None
            continue
        if active and re.fullmatch(r'(?:autores?|alun[oa]s?|discentes?|formand[oa]s?|integrantes?|membros?|participantes?)\s*:', n):
            mode = 'autores'; continue
        if active and mode == 'autores' and tag in {'dd','p','pdf'}:
            for name in nomes_da_lista(line): add(name,line,year,period)
            continue
        if active and re.search(FASE, n) and len(line) < 180 and (tag.startswith('h') or (tag in {'pdf','text'} and re.search(r'\b202[56]\b',n))):
            local_y, local_p = periodo_academico(line)
            year, period = local_y or year, local_p or period
            mode = 'lista'
        if not active or not mode: continue
        # Apenas itens de lista/tabela, ou linhas de PDF em seção acadêmica.
        if tag in {'li','tr','pdf'} or (tag in {'p','text'} and re.match(r'^\d+[.)\-–]?\s',line)):
            if tag == 'tr' and re.search(r'\b(?:nome|aluno|autor)\b', n):
                mode = 'tabela'; continue
            for name in nomes_da_lista(re.sub(r'https?://\S+|@[\w.]+','',line)):
                add(name, line, year, period)
    unique = {}
    for item in out:
        key = (norm(item['nome']),item['ano'],item['periodo'])
        if key not in unique or item['instagram']: unique[key] = item
    return list(unique.values())


def extrair_resultado_busca(resultado, instituicao, alias=None):
    """Trecho público deve conter vínculo; nunca usa o ano digitado na consulta."""
    titulo=str(resultado.get('title') or '')
    trecho=str(resultado.get('body') or resultado.get('snippet') or '')
    texto=titulo+' | '+trecho
    n=norm(texto)
    if 'nutricao' not in n:
        return []
    if re.search(r'exemplos? de curriculo|modelos? de curriculo|personagem fictici|caso hipotetic',n):
        return []
    if re.search(r'\b(?:morre|morreu|falecimento|obito)\b',norm(titulo)):
        return []
    vinculada=bool(any(t and norm(t) in n for t in (instituicao,alias)))
    if re.search(PAPEL,n) or re.search(r'\b(?:20[01]\d|202[0-4])\b',n):
        return []
    ano,periodo=periodo_academico(texto)
    fase=re.search(r'\b([78])\s*(?:º|o)?\s*(?:periodo|semestre)\b',n)
    if ano not in ANOS and not fase: return []
    nome=pessoa(re.split(r'\s*[|–—]\s*|\s+-\s+',titulo)[0])
    aluno_citado=re.search(r'\b(?:alun[oa]|estudante)\s+d[oa]\s+[Cc]urso\s+de\s+Nutrição[^.!?]{0,160}?,\s*([A-ZÀ-Ý][^,.;]{2,80}),',trecho)
    if aluno_citado: nome=pessoa(aluno_citado.group(1))
    formada_citada=re.search(r'\b[Rr]ecém[- ]formad[oa]\s+em\s+Nutrição(?:\s+pel[ao]\s+[^,.;]{1,100})?,\s*([A-ZÀ-Ý][^,.;]{2,90}?)(?=,|\s+(?:foi|celebra|compartilha|conquistou)\b)',trecho)
    if formada_citada: nome=pessoa(formada_citada.group(1))
    if not nome:
        m=re.search(r'\b(?:alun[oa]|estudante|graduand[oa]|academic[oa])\s+([A-ZÀ-Ý][^,;|.]{2,90}?)\s+(?:d[oa] curso de|de|d[oa])\s+Nutrição',trecho)
        nome=pessoa(m.group(1)) if m else None
    if not nome or not re.search(r'estud|curs|graduand|formand|formad|academic|discente',n): return []
    if not periodo: periodo=f'{fase.group(1)}º período/semestre (ano não informado)'
    return [dict(nome=nome,ano=ano,periodo=periodo,instagram=None,instituicao=instituicao if vinculada else None,
                 evidencia=(instituicao if vinculada else 'Faculdade não informada')+' | Nutrição | Evidência no resultado de busca: '+texto+' | Conclusão pendente de confirmação',
                 contexto_academico=texto)]


def ler_html(html, url, instituicao, alias=None):
    from lxml import html as html_dom
    raiz = html_dom.fromstring(html)
    page = Pagina()
    # DOM tolerante a HTML mal formado; não propaga estado de um menu ao artigo.
    for node in list(raiz.iter()):
        if not isinstance(node.tag,str): continue
        region = ' '.join(node.get(k) or '' for k in ('class','id','role')).lower()
        navigation = re.search(r'(?:^|[\s_-])(?:menu|navbar|sidebar|cookie|navigation|rodape)(?:$|[\s_-])',region)
        if node.tag in {'script','style','nav','footer'} or (navigation and not node.xpath('.//article|.//main')):
            if node.getparent() is not None: node.drop_tree()
    blocos={'p','li','tr','h1','h2','h3','h4','title','dt','dd'}
    for node in raiz.iter():
        if not isinstance(node.tag,str): continue
        if node.tag=='meta':
            key=(node.get('name') or node.get('property') or '').lower()
            page.metas.setdefault(key,[]).append(node.get('content') or '')
        if node.tag=='a' and node.get('href'): page.links.append(node.get('href'))
        if node.tag=='img' and node.get('alt'): page.textos.append(node.get('alt'))
        if node.tag in blocos:
            text=' '.join(' '.join(node.itertext()).split())
            handles=[a.get('href') for a in node.xpath('.//a[@href]') if 'instagram.com/' in a.get('href')]
            if handles: text += ' '+' '.join(handles)
            if text: page.linhas.append((text,node.tag))
        elif node.tag in {'div','span','strong','b'} and not node.xpath('.//p|.//li|.//tr|.//h1|.//h2|.//h3|.//h4|.//div|.//span'):
            text=' '.join(' '.join(node.itertext()).split())
            if text: page.linhas.append((text,'text'))
    page.textos.extend(t for t,tag in page.linhas)
    # Metadados podem completar uma data; não inferir ano a partir do URL.
    for key in ('citation_title', 'dc.title', 'dc.description'):
        for value in page.metas.get(key,[]): page.linhas.append((value, 'meta'))
    records = extrair_documento(page.linhas,instituicao,alias,' '.join(page.textos),page.metas)
    if not records:
        records=extrair_documento(page.linhas,None,None,' '.join(page.textos),page.metas)
        for registro in records: registro['instituicao']=None
    links = []
    for href in page.links:
        target=urljoin(url,href).split('#',1)[0]
        n=norm(target)
        if url_permitida(target) and (urlparse(target).hostname==urlparse(url).hostname) and re.search(r'\.pdf(?:\?|$)|nutri|tcc|formand|colacao|concluint', n):
            if target not in links and target != url: links.append(target)
    return records, links[:6]


def extrair_autores_alunos_pdf(linhas, instituicao, alias=None):
    """Identificação explícita de aluno no cabeçalho de artigo recente."""
    textos=[t.strip() for t,tag in linhas if t.strip()][:45]
    cabecalho=norm(' '.join(textos[:10]))
    datas=re.findall(r'(?:received|accepted|recebido|aceito|publicado)\s*:\s*\d{1,2}[/.-]\d{1,2}[/.-](20\d{2})',cabecalho)
    anos=[int(a) for a in datas]
    if not anos or max(anos) not in ANOS: return []
    ano=max(anos)
    out=[]
    for i,line in enumerate(textos[:-1]):
        nome=pessoa(line)
        if not nome: continue
        vinculo=' '.join(textos[i+1:i+4])
        n=norm(vinculo)
        if not re.match(r'(?:academic[oa]|alun[oa]|estudante|discente)\b',n): continue
        if 'nutricao' not in n: continue
        termos=[norm(instituicao),norm(alias)]
        if instituicao and not any(t and re.search(r'(?<!\w)'+re.escape(t)+r'(?!\w)',n) for t in termos): continue
        periodo=f'{ano} (semestre não informado)'
        out.append(dict(nome=nome,ano=ano,periodo=periodo,instagram=None,
            evidencia=f'{instituicao or "Faculdade não informada"} | Nutrição | vínculo acadêmico em {ano} | {nome} | {vinculo} | Fase do curso pendente de confirmação',
            contexto_academico=vinculo))
    return out


def ler_pdf(data, instituicao, alias=None):
    from pypdf import PdfReader
    reader=PdfReader(io.BytesIO(data))
    lines=[]
    for page in reader.pages[:40]:
        lines.extend((line.strip(),'pdf') for line in (page.extract_text() or '').splitlines())
    # Primeiro cabeçalho em PDF fornece contexto e data da seção.
    records=extrair_documento(lines,instituicao,alias,' '.join(x[0] for x in lines))
    records += extrair_autores_alunos_pdf(lines,instituicao,alias)
    if not records:
        records=extrair_documento(lines,None,None,' '.join(x[0] for x in lines))
        records+=extrair_autores_alunos_pdf(lines,None,None)
        for registro in records: registro['instituicao']=None
    records = list({(norm(r["nome"]),r["ano"]):r for r in records}.values())
    return records, []


def _carregar_url(url, instituicao, alias=None):
    import requests
    if not url_permitida(url): return [], []
    # Redirecionamentos são verificados antes de cada acesso.
    for _ in range(5):
        response=requests.get(url, timeout=(10,25), allow_redirects=False, stream=True,
                              headers={'User-Agent':'Mozilla/5.0','Accept':'text/html,application/pdf;q=0.9,*/*;q=0.8'})
        if response.status_code in {301,302,303,307,308}:
            target=urljoin(url,response.headers.get('Location',''))
            response.close()
            if not url_permitida(target): return [], []
            url=target; continue
        if response.status_code in {429,500,502,503,504} and _ < 2:
            response.close()
            import time
            time.sleep(2 * (_ + 1))
            continue
        response.raise_for_status()
        chunks=[]; size=0
        for chunk in response.iter_content(65536):
            size+=len(chunk)
            if size > 8*1024*1024:
                response.close(); raise ValueError('Fonte acima de 8 MB')
            chunks.append(chunk)
        data=b''.join(chunks)
        content_type=response.headers.get('Content-Type','').lower()
        response.close()
        if data.startswith(b'%PDF') or 'application/pdf' in content_type:
            return ler_pdf(data,instituicao,alias)
        if 'text/html' not in content_type and not data.lstrip().startswith((b'<!',b'<html',b'<HTML')):
            return [],[]
        encoding=response.encoding if response.encoding and response.encoding.lower()!='iso-8859-1' else 'utf-8'
        return ler_html(data.decode(encoding,errors='replace'),url,instituicao,alias)
    raise ValueError('Excesso de redirecionamentos')



def carregar_fonte(url, instituicao, alias=None):
    """Reabre cópias públicas oficiais; nunca contorna login ou paywall."""
    alternativas=[url]
    p=urlparse(url)
    if (p.hostname or '') in {'www.mackenzie.br','portal.mackenzie.br'} and p.path.startswith('/en/'):
        alternativas.insert(0,url.replace('/en/','/',1))
    if (p.hostname or '') == 'eventoscopq.mackenzie.br' and '/jornada/en/article/view/' in p.path:
        alternativas.insert(0,url.replace('/jornada/en/','/jornada/pt_BR/',1))
    if (p.hostname or '') in {'www.mackenzie.br','portal.mackenzie.br'} and '/n/a/i/' in p.path:
        slug=p.path.split('/n/a/i/',1)[1]
        alternativas += ['https://portal.mackenzie.br/noticias/artigo/n/a/i/'+slug,
                         'https://www.mackenzie.br/noticias/artigo/n/a/i/'+slug,
                         'https://www.mackenzie.br/memorias/150-anos/acontece/arquivo/n/a/i/'+slug,
                         'https://www.mackenzie.br/colegios/agnes-recife/noticias/arquivo/n/a/i/'+slug]
    ultimo=None
    resposta=None
    for alternativa in dict.fromkeys(alternativas):
        try:
            resposta=_carregar_url(alternativa,instituicao,alias)
            if resposta[0]: return resposta
        except Exception as exc: ultimo=exc
    if resposta is not None: return resposta
    if ultimo: raise ultimo
    return [],[]
