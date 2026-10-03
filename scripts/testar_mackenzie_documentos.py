"""Busca complementar real, referência preservada e candidatos autorizados."""
import json,signal,sys,time,runpy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scraper as s
import fontes_academicas as f
repo=s.SupabaseRepo.from_env();inicio=time.monotonic();confirmados=[]
# Indícios públicos apresentados ao usuário; semestre desconhecido é explícito.
casos=[('Gabriela Fernandes Pinheiro Silva','Universidade Federal de Alfenas','UNIFAL','https://jornal.unifal-mg.edu.br/unifal-mg-realiza-cerimonias-de-colacao-de-grau-em-alfenas/',2026,'Colação em 12/08/2026; notícia de 20/08/2026 identifica formanda de Nutrição'),('Iracema Rocha de Oliveira Silva','Universidade Federal de Alagoas','UFAL','https://sig.ufal.br/public/baixarBoletim.do?idBoletim=2059&publico=true',2025,'Anexo da portaria de outorga de grau em 25/04/2025 identifica nome na linha Nutrição')]
u='https://unifeso.com.br/noticia/index.php?id_not=6329&key=FAEEE6C97E0C8D1C7977CBB752C79FE05C2AF3F2'
for nome in ['Maria Carolina Zimbrão','Diana Soares','Andrielle Bressane','Evelynn Ferreira','Flavia Rocha','Maria Luiza Tardelle Esteves','Mel Thomé Matos']:
 casos.append((nome,'Centro Universitário Serra dos Órgãos','Unifeso',u,2026,'Notícia de 12/08/2026 identifica aluna do diretório ou liga de Nutrição. Fase acadêmica e conclusão não informadas; máquina 2 deve validar identidade e curso no Instagram'))
for nome,ies,alias,url,ano,evidencia in casos:
 novo=s.salvar_lead(repo,nome,ies,None,None,evidencia,url,ano_forcado=ano,periodo_forcado=f'{ano} (evidência pública; fase acadêmica a validar)',instituicao_alias=alias)
 assert repo.lead_existe(nome,ies)
 confirmados.append(dict(nome=nome,novo=novo,ano=ano))
print('CANDIDATOS AUTORIZADOS',json.dumps(confirmados,ensure_ascii=False),flush=True)
referencia_pendente=False
try:runpy.run_path(str(Path(__file__).with_name('testar_mackenzie_completo.py')),run_name='__main__')
except SystemExit:referencia_pendente=True
nomes={};novos=[];existentes=[];pendentes=[];fontes=set();metricas=[]
def limite(*a):raise TimeoutError('Orçamento de pesquisa atingido')
signal.signal(signal.SIGALRM,limite)
def executar(fn,segundos):
 restante=360-(time.monotonic()-inicio)
 if restante<=0:raise TimeoutError('Limite total de seis minutos')
 signal.setitimer(signal.ITIMER_REAL,min(segundos,restante))
 try:return fn()
 finally:signal.setitimer(signal.ITIMER_REAL,0)
def registrar(registros,fonte):
 for r in registros:
  chave=f.norm(r['nome'])
  if chave in nomes:continue
  r.setdefault('fonte_url',fonte)
  ies=r.get('instituicao','Universidade Presbiteriana Mackenzie')
  novo=s.salvar_lead(repo,r['nome'],ies,None,None,r['evidencia'],r['fonte_url'],ano_forcado=r['ano'],periodo_forcado=r['periodo'],instituicao_alias='Mackenzie' if ies=='Universidade Presbiteriana Mackenzie' else None)
  assert repo.lead_existe(r['nome'],ies)
  nomes[chave]=r
  (novos if novo else existentes).append(r['nome'])
consultas=s.consultas_documentos_alunos('Universidade Presbiteriana Mackenzie','Mackenzie')[:4]+['site:mackenzie.br "mostra-de-tcc"']
for consulta in consultas:
 comeco=time.monotonic();antes=len(nomes)
 try:
  resultados=executar(lambda:s.buscar_web(consulta,max_results=5),45)
  if resultados is None:raise RuntimeError('Buscador indisponível')
  print('BUSCA DOCUMENTAL',json.dumps(dict(consulta=consulta,resultados=resultados),ensure_ascii=False),flush=True)
  for resultado in resultados:
   url=resultado.get('href') or resultado.get('url') or ''
   registrar(f.extrair_resultado_busca(resultado,'Universidade Presbiteriana Mackenzie','Mackenzie'),url)
   if url in fontes or not f.url_permitida(url):continue
   texto=f.norm(str(resultado.get('title',''))+' '+str(resultado.get('body','')))
   if 'nutricao' not in texto:continue
   fontes.add(url)
   try:
    registros,links=executar(lambda:f.carregar_fonte(url,'Universidade Presbiteriana Mackenzie','Mackenzie'),12)
    registrar(registros,url)
    print('LEITURA E ANEXOS',json.dumps(dict(url=url,nomes=len(registros),links_disponiveis=len(links)),ensure_ascii=False),flush=True)
    for link in links[:3]:
     if link in fontes or not f.url_permitida(link):continue
     fontes.add(link)
     try:
      outros,_=executar(lambda:f.carregar_fonte(link,'Universidade Presbiteriana Mackenzie','Mackenzie'),12)
      registrar(outros,link)
      print('ANEXO LIDO',json.dumps(dict(url=link,nomes=len(outros)),ensure_ascii=False),flush=True)
     except Exception as e:pendentes.append(dict(fonte=link,erro=type(e).__name__))
   except Exception as e:pendentes.append(dict(fonte=url,erro=type(e).__name__))
 except Exception as e:pendentes.append(dict(consulta=consulta,erro=type(e).__name__))
 metricas.append(dict(consulta=consulta,segundos=round(time.monotonic()-comeco,1),nomes_adicionados=len(nomes)-antes))
 if time.monotonic()-inicio>=360:break
print('RESULTADO DOCUMENTAL',json.dumps(dict(segundos=round(time.monotonic()-inicio,1),nomes_unicos=len(nomes),novos_confirmados=novos,existentes_confirmados=existentes,metricas=metricas,pendencias=pendentes,referencia_pendente=referencia_pendente,consultas_planejadas=len(consultas),consultas_executadas=len(metricas),varredura_completa=False),ensure_ascii=False),flush=True)
if referencia_pendente or pendentes or len(metricas)<len(consultas):raise SystemExit(2)
