import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'paperless_auto_metadata'))
from translation import translate_text
from main import DEFAULTS, process
from rule_web import is_long_text_field

class Tests(unittest.TestCase):
    def test_paperless_longtext_api_type(self):
        self.assertTrue(is_long_text_field({'id': 1, 'data_type': 'longtext'}))
        self.assertFalse(is_long_text_field({'id': 2, 'data_type': 'string'}))
        self.assertFalse(is_long_text_field({'id': 3, 'data_type': 'long_text'}))

    def test_rules_mode_does_not_translate(self):
        opts = dict(DEFAULTS, translate_enabled=False, rules=[])
        with patch('translation.urllib.request.urlopen') as request:
            self.assertEqual(process(None, {'id': 1, 'content': 'Bonjour',
                'custom_fields': [{'field': 67, 'value': ''}], 'tags': [4]}, opts), 'skipped')
            request.assert_not_called()

    def test_translation_mode_ignores_rules(self):
        opts = dict(DEFAULTS, translate_enabled=True, translate_url='http://localhost:5000',
                    translate_field_id=67, translate_trigger='field_only', rules=[])
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"translatedText":"Hello"}'
        with patch('translation.urllib.request.urlopen', return_value=Response()) as request:
            self.assertEqual(process(None, {'id': 1, 'content': 'Bonjour',
                'custom_fields': [{'field': 67, 'value': ''}], 'tags': []}, opts), 'dry_run')
            request.assert_called_once()

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
                  translate_field_id=67,translate_target='en',dry_run=False,
                  translate_tag_ids=[4])
        with patch('translation.urllib.request.urlopen',return_value=Response()) as request:
            result=process(client,{'id':1,'content':'Bonjour le monde',
                'custom_fields':[{'field':8,'value':'keep'}], 'tags':[4]},opts)
        self.assertEqual(result,'updated')
        self.assertEqual({x['field']:x['value'] for x in client.payload['custom_fields']},
                         {8:'keep',67:'Hello world'})
        self.assertIn('/translate',request.call_args.args[0].full_url)
    def test_existing_translation_is_not_overwritten(self):
        opts=dict(DEFAULTS, translate_enabled=True, translate_url='http://localhost:5000',
                  translate_field_id=67, dry_run=False)
        class Client:
            def request(self,*args): raise AssertionError('Unexpected PATCH')
        with patch('translation.urllib.request.urlopen') as request:
            result=process(Client(),{'id':1,'content':'Bonjour',
                'custom_fields':[{'field':67,'value':'Already translated'}],
                'tags':[4]},opts)
        self.assertEqual(result,'skipped')
        request.assert_not_called()

    def test_tag_filter(self):
        opts=dict(DEFAULTS, translate_enabled=True, translate_url='http://localhost:5000',
                  translate_field_id=67, translate_tag_ids=[4,5], translate_tag_match='all')
        class Client:
            def request(self,*args): raise AssertionError('Unexpected PATCH')
        with patch('translation.urllib.request.urlopen') as request:
            self.assertEqual(process(Client(),{'id':1,'content':'Bonjour',
                'custom_fields':[], 'tags':[4]},opts),'skipped')
            request.assert_not_called()

    def test_tag_filter_any_matches(self):
        opts=dict(DEFAULTS, translate_enabled=True, translate_url='http://localhost:5000',
                  translate_field_id=67, translate_tag_ids=[4,5], translate_tag_match='any')
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return b'{"translatedText":"Hello"}'
        with patch('translation.urllib.request.urlopen',return_value=Response()) as request:
            self.assertEqual(process(None,{'id':1,'content':'Bonjour',
                'custom_fields':[], 'tags':[5]},opts),'dry_run')
            request.assert_called_once()

    def test_present_empty_field_triggers_without_tags(self):
        opts=dict(DEFAULTS,translate_enabled=True,translate_url='http://localhost:5000',
                  translate_field_id=67,translate_trigger='tag_or_field')
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return b'{"translatedText":"Hello"}'
        with patch('translation.urllib.request.urlopen',return_value=Response()) as request:
            self.assertEqual(process(None,{'id':1,'content':'Bonjour',
                'custom_fields':[{'field':67,'value':''}],'tags':[]},opts),'dry_run')
            request.assert_called_once()

    def test_absent_field_without_tags_is_skipped(self):
        opts=dict(DEFAULTS,translate_enabled=True,translate_url='http://localhost:5000',
                  translate_field_id=67,translate_trigger='tag_or_field')
        with patch('translation.urllib.request.urlopen') as request:
            self.assertEqual(process(None,{'id':1,'content':'Bonjour',
                'custom_fields':[],'tags':[]},opts),'skipped')
            request.assert_not_called()

    def test_tag_triggers_even_if_field_absent(self):
        opts=dict(DEFAULTS,translate_enabled=True,translate_url='http://localhost:5000',
                  translate_field_id=67,translate_tag_ids=[4],translate_trigger='tag_or_field')
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return b'{"translatedText":"Hello"}'
        with patch('translation.urllib.request.urlopen',return_value=Response()):
            self.assertEqual(process(None,{'id':1,'content':'Bonjour',
                'custom_fields':[],'tags':[4]},opts),'dry_run')

    def test_invalid_field(self):
        with self.assertRaises(ValueError):
            translate_text('Bonjour',dict(DEFAULTS,translate_enabled=True,
                           translate_url='http://localhost:5000',translate_field_id=0))
if __name__=='__main__': unittest.main()
