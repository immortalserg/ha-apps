import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'paperless_auto_metadata'))
from translation import translate_text
from main import DEFAULTS, process

class Tests(unittest.TestCase):
    def test_disabled(self):
        self.assertIsNone(translate_text('Bonjour',DEFAULTS))
    def test_translation_to_selected_field(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return b'{"translatedText":"Hello world"}'
        class Client:
            payload=None
            def request(self,method,path,payload): self.payload=payload
        client=Client()
        opts=dict(DEFAULTS,translate_enabled=True,translate_url='http://localhost:5000',
                  translate_field_id=67,translate_target='en',dry_run=False)
        with patch('translation.urllib.request.urlopen',return_value=Response()) as request:
            result=process(client,{'id':1,'content':'Bonjour le monde',
                'custom_fields':[{'field':8,'value':'keep'}]},opts)
        self.assertEqual(result,'updated')
        self.assertEqual({x['field']:x['value'] for x in client.payload['custom_fields']},
                         {8:'keep',67:'Hello world'})
        self.assertIn('/translate',request.call_args.args[0].full_url)
    def test_invalid_field(self):
        with self.assertRaises(ValueError):
            translate_text('Bonjour',dict(DEFAULTS,translate_enabled=True,
                           translate_url='http://localhost:5000',translate_field_id=0))
if __name__=='__main__': unittest.main()
