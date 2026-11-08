import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'paperless_auto_metadata'))
import main

SAMPLE = """Bénéficiaire : GROUPE RADIOLOGIQUE HRS
IBAN LU16 0019 8155 4289 6000
Montant : 190,30 EUR
Communication : 8997-211661 au 27.08.2026
"""

class TestScan(unittest.TestCase):
    def test_full_document_loaded_when_list_has_no_content(self):
        class Client:
            def __init__(self, url, token): pass
            def documents(self, count): return [{'id': 7}]
            def document(self, doc_id):
                return {'id': 7, 'content': SAMPLE, 'custom_fields': []}
        opts = dict(main.DEFAULTS, api_token='test', dry_run=True)
        with patch.object(main, 'settings', return_value=opts), \
             patch.object(main, 'Paperless', Client), \
             patch.object(main, 'read_json', return_value={}), \
             patch.object(main, 'write_json') as save:
            result = main.scan_once()
        self.assertEqual(result['dry_run'], 1)
        self.assertEqual(result['errors'], 0)
        self.assertTrue(save.called)

    def test_empty_content_is_not_cached(self):
        class Client:
            def __init__(self, url, token): pass
            def documents(self, count): return [{'id': 7}]
            def document(self, doc_id):
                return {'id': 7, 'content': '', 'custom_fields': []}
        opts = dict(main.DEFAULTS, api_token='test', dry_run=True)
        with patch.object(main, 'settings', return_value=opts), \
             patch.object(main, 'Paperless', Client), \
             patch.object(main, 'read_json', return_value={}), \
             patch.object(main, 'write_json') as save:
            result = main.scan_once()
        self.assertEqual(result['skipped'], 1)
        save.assert_not_called()

if __name__ == '__main__':
    unittest.main()
