import unittest
from unittest.mock import patch
import scraper as s
class AlternativoTests(unittest.TestCase):
 @patch.object(s.time,'sleep')
 def test_bing_recupera_vazio_do_automatico(self,_):
  chamadas=[]
  def busca(q,b,n):
   chamadas.append((q,b));return [{'href':'https://example.edu/tcc'}] if b=='bing' else []
  self.assertEqual(len(s.buscar_web('TCC',fetch_fn=busca)),1)
  self.assertEqual([b for q,b in chamadas],['auto','auto','bing'])
 @patch.object(s.time,'sleep')
 def test_sem_resposta_nem_controle_e_indisponibilidade(self,_):
  def falha(*a):raise RuntimeError('No results found.')
  self.assertIsNone(s.buscar_web('TCC',fetch_fn=falha))
 @patch.object(s.time,'sleep')
 def test_consulta_vazia_com_controle_disponivel(self,_):
  def busca(q,b,n):
   if q=='Brasil':return [{'href':'https://example.org/brasil'}]
   raise RuntimeError('No results found.')
  self.assertEqual(s.buscar_web('TCC',fetch_fn=busca),[])
