import unittest
from unittest.mock import Mock, patch
import fontes_academicas as f

class DocumentosTests(unittest.TestCase):
    def test_titulos_e_sobrenome_isolado_nao_sao_nomes(self):
        for nome in ('Semana Acadêmica','Material e Métodos','Consentimento Livre e Esclarecido','Del Ré','Ana Silva Pdf'):
            self.assertIsNone(f.pessoa(nome), nome)
        self.assertEqual(f.pessoa('Ana Del Ré'), 'Ana Del Ré')
        self.assertEqual(f.pessoa('Ana Carolina Silva'), 'Ana Carolina Silva')

    def test_reutiliza_download_mas_preserva_contexto(self):
        response=Mock(status_code=200, headers={'Content-Type':'text/html'}, encoding='utf-8')
        response.iter_content.return_value=[b'<html>Nutri</html>']
        with patch.dict(f.CACHE_DOCUMENTOS, {}, clear=True), patch('requests.get',return_value=response) as get, patch.object(f,'ler_html',return_value=([],[])) as ler:
            f._carregar_url('https://example.org/doc','Faculdade A')
            f._carregar_url('https://example.org/doc','Faculdade B')
            self.assertEqual(get.call_count,1)
            self.assertEqual(ler.call_args_list[0].args[2],'Faculdade A')
            self.assertEqual(ler.call_args_list[1].args[2],'Faculdade B')

    def test_erro_http_nao_e_guardado_como_documento(self):
        response=Mock(status_code=403)
        response.raise_for_status.side_effect=RuntimeError('403')
        with patch.dict(f.CACHE_DOCUMENTOS, {}, clear=True), patch('requests.get',return_value=response) as get:
            for _ in range(2):
                with self.assertRaises(RuntimeError): f._carregar_url('https://example.org/doc','Faculdade A')
            self.assertEqual(get.call_count,2)
            self.assertNotIn('https://example.org/doc',f.CACHE_DOCUMENTOS)
