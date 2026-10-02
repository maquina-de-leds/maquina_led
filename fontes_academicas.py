"""Captação pública de pessoas em fontes acadêmicas HTML/PDF, sem redes auxiliares."""
import io
import ipaddress
import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

ANOS = {2025, 2026}
OUTROS_CURSOS = r'educacao fisica|enfermagem|fisioterapia|psicologia|medicina|direito|engenharia|farmacia|pedagogia|letras|biomedicina'
FASE = r'tcc|trabalho de conclusao|formand[oa]s?|concluintes?|colacao|outorga|formatura|recem[- ]formad[oa]s?|ultimo (?:periodo|semestre)|estagio final|conclusao'
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
    if host == 'linkedin.com' or host.endswith('.linkedin.com'):
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
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in {'script', 'style', 'nav', 'footer'}:
            self.skip += 1
        if self.skip: return
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
        if self.skip: return
        if data.strip().lower() in {'instagram','ver instagram','perfil instagram'}: return
        self.textos.append(data)
        if self.bloco: self.partes.append(data)
        elif data.strip(): self.linhas.append((' '.join(data.split()), 'text'))
    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'nav', 'footer'} and self.skip:
            self.skip -= 1
            return
        if self.skip: return
        if self.bloco == tag:
            self.linhas.append((' '.join(''.join(self.partes).split()), tag))
            self.bloco, self.partes = None, []


def periodo_academico(text):
    """Prefere referência à turma ao ano de publicação da notícia."""
    n = norm(text)
    patterns = [
        r'(?:referente|turma|formandos|concluintes|nutricao)[^.\n]{0,70}?([12])o?\s*semestre(?:\s+letivo)?\s*(?:de|/)?\s*(202[56])',
        r'(?:referente|turma|formandos|concluintes|nutricao)[^.\n]{0,70}?(202[56])[./-]([12])\b',
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
    if re.search(r'\b(?:'+PAPEL+r'|curso|nutricao|universidade|faculdade|instituto|secretaria|trabalho|tema|titulo|mostra|sessao|avaliação|saude|alimentacao|nutricional|estudantes|formandos)\w*\b', n): return None
    primary = [w for w in words if norm(w) not in {'de','da','do','dos','das','e'}]
    if len(primary) < 2 or any(not w[0].isupper() for w in primary): return None
    if not all(re.fullmatch(r"[A-Za-zÀ-ÿ'’-]+", w) for w in words): return None
    return text


def nomes_da_lista(text):
    # Conjunção separa pessoas somente quando ambos os lados são nomes completos.
    out = []
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
    if not related: return []
    # Sem Nutrição + fase acadêmica não há extração de pessoas.
    if 'nutricao' not in norm(full) or not re.search(FASE, norm(full)): return []
    # Apenas texto editorial (sem rodapé) contribui para contexto acadêmico.
    context_lines = [t for t,tag in linhas if tag in {'title','h1','h2','h3','h4','p','meta'}]
    if not context_lines:
        context_lines = [t for t,tag in linhas[:20] if tag == 'pdf']
    context = ' '.join(context_lines)
    default_year, default_period = periodo_academico(context)
    single_course = not re.search(OUTROS_CURSOS, norm(context))
    active = single_course and 'nutricao' in norm(context)
    year, period = default_year, default_period
    mode = 'lista' if active and re.search(FASE,norm(context)) else None
    out = []
    def add(name, evidence, y, per):
        if name and y in ANOS:
            phase = 'TCC' if re.search(r'tcc|trabalho de conclusao', norm(evidence+' '+context)) else 'turma/conclusão'
            out.append(dict(nome=name, ano=y, periodo=per, instagram=instagram_associado(evidence,name),
                            evidencia=f'{instituicao} | Nutrição | {per} | {phase} | {evidence}'))
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
        # Notícias multicurso também publicam linhas como 'Nutrição: Nome'.
        course_list = re.match(r'^Nutrição\s*:\s*(.+)', line, re.I)
        if course_list and not re.search(PAPEL, n):
            previous = ' '.join(t for t, _ in linhas[max(0,i-2):i])
            if re.search(r'professor|docente|coordenador|banca|orientador', norm(previous)) and not re.search(r'formand|concluinte|outorga|colacao', norm(previous)):
                continue
            for name in nomes_da_lista(course_list.group(1)):
                add(name,line,default_year,default_period)
            continue
        # Pessoa explicitamente vinculada ao curso, na própria frase da notícia.
        for sentence in re.split(r'(?<=[.!?])\s+', line):
            if re.search(PAPEL,norm(sentence)) or not re.search(r'formand|concluinte|orador',norm(sentence)):
                continue
            match = re.search(r'\b(?:a|o|aluna|aluno|formanda|formando)\s+([A-ZÀ-Ý][^,.;:]{2,100}),?\s+d[oa]\s+[Cc]urso\s+de\s+Nutrição\b',sentence)
            if match:
                add(pessoa(match.group(1).strip()),sentence,default_year,default_period)
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
        label = re.search(r'(?:formand[oa]s?|concluintes?|alun[oa]s?|discentes?|autores?)[^:]{0,130}:\s*(.+)', line, re.I)
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
        if active and re.fullmatch(r'(?:autores?|alun[oa]s?|discentes?|formand[oa]s?)\s*:', n):
            mode = 'autores'; continue
        if active and mode == 'autores' and tag in {'dd','p','pdf'}:
            for name in nomes_da_lista(line): add(name,line,year,period)
            continue
        if active and re.search(FASE, n) and len(line) < 180:
            local_y, local_p = periodo_academico(line)
            year, period = local_y or year, local_p or period
            mode = 'lista'
        if not active or not mode: continue
        # Apenas itens de lista/tabela, ou linhas de PDF em seção acadêmica.
        if tag in {'li','tr','pdf','text'} or (tag=='p' and re.match(r'^\d+[.)\-–]?\s',line)):
            if tag == 'tr' and re.search(r'\b(?:nome|aluno|autor)\b', n):
                mode = 'tabela'; continue
            for name in nomes_da_lista(re.sub(r'https?://\S+|@[\w.]+','',line)):
                add(name, line, year, period)
    unique = {}
    for item in out:
        key = (norm(item['nome']),item['ano'],item['periodo'])
        if key not in unique or item['instagram']: unique[key] = item
    return list(unique.values())


def ler_html(html, url, instituicao, alias=None):
    page = Pagina(); page.feed(html)
    # Metadados podem completar uma data; não inferir ano a partir do URL.
    for key in ('article:published_time', 'citation_title', 'dc.title', 'dc.description'):
        for value in page.metas.get(key,[]): page.linhas.append((value, 'meta'))
    records = extrair_documento(page.linhas,instituicao,alias,' '.join(page.textos),page.metas)
    links = []
    for href in page.links:
        target=urljoin(url,href)
        n=norm(target)
        if url_permitida(target) and (urlparse(target).hostname==urlparse(url).hostname) and re.search(r'\.pdf(?:\?|$)|nutri|tcc|formand|colacao|concluint', n):
            if target not in links and target != url: links.append(target)
    return records, links[:6]


def ler_pdf(data, instituicao, alias=None):
    from pypdf import PdfReader
    reader=PdfReader(io.BytesIO(data))
    lines=[]
    for page in reader.pages[:40]:
        lines.extend((line.strip(),'pdf') for line in (page.extract_text() or '').splitlines())
    # Primeiro cabeçalho em PDF fornece contexto e data da seção.
    records=extrair_documento(lines,instituicao,alias,' '.join(x[0] for x in lines))
    return records, []


def carregar_fonte(url, instituicao, alias=None):
    import requests
    if not url_permitida(url): return [], []
    # Redirecionamentos são verificados antes de cada acesso.
    for _ in range(5):
        response=requests.get(url, timeout=(10,25), allow_redirects=False, stream=True,
                              headers={'User-Agent':'Mozilla/5.0 MaquinaLeads/5.8'})
        if response.status_code in {301,302,303,307,308}:
            target=urljoin(url,response.headers.get('Location',''))
            response.close()
            if not url_permitida(target): return [], []
            url=target; continue
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
