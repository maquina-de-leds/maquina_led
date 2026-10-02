"""Piloto com busca real e gravação. Não conclui a varredura nacional."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scraper as s

repo = s.SupabaseRepo.from_env()
# Correção reversível apenas dos rótulos indevidos gravados no primeiro piloto.
nomes_indevidos = ['Laboratório de Estudos Anatômicos', 'Laboratório de Estética Corporal', 'Laboratório de Comportamento Motor', 'Laboratório de Desenho', 'Laboratório de Estudos Cardiorrespiratórios', 'Laboratório de Imaginologia', 'Laboratório de Informática', 'Laboratório de Moda', 'Estilo Ii', 'Estilo I', 'Sou Aluno', 'Uno Medical e Office', 'Trabalhe Conosco', 'Pós-graduação Lato Sensu', 'Tipo Sanguíneo', 'Ensino Médio', 'Página de Privacidade', 'Uso de Cookies', 'Processos Seletivos', 'Pesquisa e Extensão', 'Regulamentos e Normas', 'Diretório Acadêmico', 'Empresa Júnior', 'Procedimentos de Matrícula', 'Calendário de Matrícula']
ruins=(repo.client.table('leds').select('id,nome').in_('nome',nomes_indevidos)
       .eq('origem','captacao_nacional_fila_v58').gte('created_at','2026-10-02T15:51:00Z')
       .in_('instituicao',['Centro Universitário Ateneu','Universidade Comunitária da Região de Chapecó',
                          'Universidade Federal do Rio Grande do Norte']).execute()).data or []
for registro in ruins:
    repo.client.table('leds').update(dict(qualificado=False,nao_contatar=True,
        proxima_acao='revisar_nome_extraido')).eq('id',registro['id']).execute()
    confirmado=(repo.client.table('leds').select('qualificado,nao_contatar,proxima_acao')
                .eq('id',registro['id']).execute()).data[0]
    assert confirmado['qualificado'] is False and confirmado['nao_contatar'] is True
print(f'REGISTROS INDEVIDOS SEPARADOS DA CAPTAÇÃO: {len(ruins)}; nenhum registro excluído.',flush=True)
from fontes_academicas import carregar_fonte
# Regressão nas páginas reais que produziram falsos nomes e nas listas legítimas.
for url,inst,alias,esperado in [
    ('https://uniateneu.edu.br/','Centro Universitário Ateneu','UniAteneu',0),
    ('https://nutrivital.ind.br/parceria-nutrivital-unochapeco-inovacao/',
     'Universidade Comunitária da Região de Chapecó','Unochapecó',0),
    ('https://uno.edu.br/noticias/colacao-de-grau',
     'Universidade Comunitária da Região de Chapecó','Unochapecó',15),
    ('https://uno.edu.br/noticias/outorga-de-grau-1',
     'Universidade Comunitária da Região de Chapecó','Unochapecó',13),
]:
    registros,_=carregar_fonte(url,inst,alias)
    assert len(registros)==esperado,(url,len(registros),esperado)
    print(f'REGRESSÃO REAL: {url} | candidatos: {len(registros)}',flush=True)
# Somente carregar fila já existente, sem reinstalar ou reabrir histórico.
dados=[]
for offset in range(0, 20000, 1000):
    lote=(repo.client.table('instituicoes_nutricao').select('*').eq('origem',s.ORIGEM_IES)
          .order('id').range(offset,offset+999).execute()).data or []
    dados.extend(lote)
    if len(lote)<1000: break
else: raise RuntimeError('Fila excedeu limite do piloto; conferir paginação')
fila=s.agrupar_faculdades(dados)
alvos=[]
for alias in ['UniAteneu','Unochapecó','UFRN']:
    item=next((x for x in fila if s.normalizar(s.alias_instituicao(x))==s.normalizar(alias)),None)
    if item is None: raise RuntimeError('Faculdade não encontrada na fila: '+alias)
    alvos.append(item)

class RepoPiloto:
    def __init__(self): self.salvos=[]
    def __getattr__(self,nome): return getattr(repo,nome)
    def atualizar_instituicao(self,*args,**kwargs):
        # Pesquisa limitada não encerra nem altera a fila nacional.
        pass
    def inserir_lead(self,dados):
        repo.inserir_lead(dados)
        assert repo.lead_existe(dados['nome'],dados['instituicao']), 'Gravação não confirmada'
        self.salvos.append(dados)
        print('BANCO CONFIRMADO: '+dados['nome'],flush=True)

piloto=RepoPiloto()
s.MAX_RESULTADOS=5
original=s.consultas_leads
falha_busca=False
for base in alvos:
    item=dict(base)
    item['id']='piloto_real_20261002_'+str(base['id'])
    termo=s.alias_instituicao(base) or base['instituicao']
    consultas=[f'"{termo}" Nutrição {criterio} {ano} -site:linkedin.com'
               for criterio,ano in [('"colação de grau"',2026),('"formandos"',2025),('"TCC"',2026),('"alunos"',2026)]]
    s.consultas_leads=lambda *args, consultas=consultas: consultas
    try:
        if not s.processar_instituicao(piloto,item):
            falha_busca=True
            break
    finally: s.consultas_leads=original
# Conferir duplicação com os mesmos leads recém gravados.
antes=s.stats['leads_salvos']
for lead in piloto.salvos:
    assert not s.salvar_lead(repo,lead['nome'],lead['instituicao'],lead['cidade'],lead['estado'],
        lead['evidencia'],lead['fonte_url'],instagram=lead['instagram'],
        ano_forcado=lead['ano_alvo'],periodo_forcado=lead['periodo_alvo'])
assert s.stats['leads_salvos']==antes
print(f'NOVOS CONFIRMADOS NO BANCO: {len(piloto.salvos)}',flush=True)
print('REPETIÇÃO DOS NOVOS: nenhuma inserção duplicada.',flush=True)
s.resumo()
print('PILOTO: 4 consultas por faculdade; fila nacional não foi marcada como concluída.',flush=True)
if falha_busca or s.stats['erros']: raise SystemExit(2)
