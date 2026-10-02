"""Validação real somente leitura: fila, fontes públicas e deduplicação."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scraper as s
from fontes_academicas import carregar_fonte

repo = s.SupabaseRepo.from_env()
dados = []
offset = 0
while True:
    lote = (repo.client.table('instituicoes_nutricao').select('*')
            .eq('origem', s.ORIGEM_IES).order('id').range(offset, offset+999).execute()).data or []
    dados.extend(lote)
    if len(lote) < 1000:
        break
    offset += 1000
fila = s.agrupar_faculdades(dados)
assert len(fila) == 620, f'Conferir alteração da base: {len(fila)} faculdades'
assert all(x['cidade'] is None and x['estado'] is None for x in fila)
assert len({s.normalizar(x['instituicao']) for x in fila}) == len(fila)
print(f'FILA REAL: {len(fila)} faculdades únicas; polos não repetem pesquisas.', flush=True)

class SomenteLeitura:
    def __init__(self):
        self.preparados = []
        self.checkpoints = {}
    def controle_get(self, etapa): return self.checkpoints.get(etapa)
    def controle_salvar(self, etapa, dados): self.checkpoints[etapa] = dados
    def atualizar_instituicao(self, *args, **kwargs): pass
    def lead_existe(self, *args): return repo.lead_existe(*args)
    def instituicao_de_lead_por_alias(self, *args): return repo.instituicao_de_lead_por_alias(*args)
    def instagram_usado(self, *args): return repo.instagram_usado(*args)
    def inserir_lead(self, dados): self.preparados.append(dados)
    def completar_instagram(self, *args): return False

casos = [
    ('Unochapecó', 'https://uno.edu.br/noticias/outorga-de-grau-1', 13),
    ('UniAteneu', 'https://uniateneu.edu.br/uniateneu-realizou-colacao-de-grau-para-celebrar-a-formatura-de-alunos-de-diferentes-cursos-de-graduacao/', 1),
]
s.PAUSA_ENTRE_BUSCAS = 0
for alias, url, esperado in casos:
    item = next(x for x in fila if s.normalizar(s.alias_instituicao(x) or '') == s.normalizar(alias))
    registros, links = carregar_fonte(url, item['instituicao'], alias)
    assert len(registros) == esperado, (alias, len(registros), esperado)
    assert all(x['ano'] in (2025, 2026) and x['nome'] for x in registros)
    dry = SomenteLeitura()
    consultas_antes = s.consultas_leads
    try:
        s.consultas_leads = lambda *args: ['fonte oficial controlada']
        ok = s.processar_instituicao(dry, item,
            search_fn=lambda *args: [{'href': url}],
            source_fn=lambda *args: (registros, []))
    finally:
        s.consultas_leads = consultas_antes
    assert ok
    assert all(x['proxima_acao'] == 'buscar_instagram' for x in dry.preparados if not x['instagram'])
    print(f'FONTE REAL {alias}: {len(registros)} candidatos; {len(dry.preparados)} novos preparados em memória; nenhuma escrita no banco.', flush=True)
s.resumo()
print('VALIDAÇÃO SOMENTE LEITURA CONCLUÍDA. Busca externa por palavras não foi exercitada neste teste.', flush=True)
