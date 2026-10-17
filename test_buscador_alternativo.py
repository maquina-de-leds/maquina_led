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
  self.assertEqual([b for q,b in chamadas],['google','google','bing'])
 @patch.object(s.time,'sleep')
 def test_sem_resposta_nem_controle_e_indisponibilidade(self,_):
  def falha(*a):raise RuntimeError('Temporary network error')
  self.assertIsNone(s.buscar_web('TCC',fetch_fn=falha))
 @patch.object(s.time,'sleep')
 def test_busca_indisponivel_preserva_consulta_para_retry(self,_):
  chamadas=[]
  def busca(q,b,n):
   chamadas.append((q,b))
   raise RuntimeError('Temporary network error')
  self.assertIsNone(s.buscar_web('TCC',fetch_fn=busca))
  self.assertEqual(chamadas,[('TCC','google'),('TCC','google'),('TCC','bing')])
 @patch.object(s.time,'sleep')
 def test_no_results_found_e_vazio_confirmado(self,_):
  chamadas=[]
  def busca(q,b,n):
   chamadas.append(b)
   raise RuntimeError('No results found.')
  self.assertEqual(s.buscar_web('TCC',fetch_fn=busca),[])
  self.assertEqual(chamadas,['google','google','bing'])
