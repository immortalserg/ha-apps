import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'paperless_auto_metadata'))

from rules import DEFAULT_RULES, validate_rules, extract_rules, extraction_preview
from main import process
from rule_web import read_settings_form

SAMPLE = """Bénéficiaire : GROUPE RADIOLOGIQUE HRS
IBAN LU16 0019 8155 4289 6000
Montant : 190,30 EUR
Communication : 8997-211661 au 27.08.2026
"""


class Tests(unittest.TestCase):
    def test_original_defaults(self):
        result = extract_rules(SAMPLE, DEFAULT_RULES)
        by_name = {x['name']: x['value'] for x in result}
        self.assertEqual(by_name['beneficiary'], 'GROUPE RADIOLOGIQUE HRS')
        self.assertEqual(by_name['amount'], 'EUR190.30')
        self.assertEqual(by_name['iban'], 'LU160019815542896000')
        self.assertEqual(by_name['title'], 'оплата 8997-211661 au 27.08.2026')

    def test_custom_field_choice(self):
        rules = [
            {'name': 'invoice', 'label': 'Invoice ID', 'pattern': r'Invoice #(\d+)',
             'target': 'custom_field', 'field_id': 89, 'transform': 'text',
             'prefix': '', 'currency': 'EUR', 'required': True, 'enabled': True},
            {'name': 'heading', 'label': 'Title', 'pattern': r'Invoice #(\d+)',
             'target': 'title', 'field_id': 0, 'transform': 'text',
             'prefix': 'Invoice ', 'currency': 'EUR', 'required': True, 'enabled': True},
        ]
        class Fake:
            payload = None
            def request(self, method, path, payload):
                self.payload = payload
        fake = Fake()
        doc = {'id': 3, 'content': 'Invoice #8542', 'custom_fields': [
            {'field': 22, 'value': 'preserved'}
        ]}
        self.assertEqual(process(fake, doc, {'rules': rules, 'dry_run': False}), 'updated')
        values = {x['field']: x['value'] for x in fake.payload['custom_fields']}
        self.assertEqual(values[89], '8542')
        self.assertEqual(values[22], 'preserved')
        self.assertEqual(fake.payload['title'], 'Invoice 8542')

    def test_optional_and_required(self):
        r = [dict(DEFAULT_RULES[0], required=True),
             dict(DEFAULT_RULES[1], required=False)]
        self.assertIsNone(extract_rules('Montant : 12,00 EUR', r))
        matched = extract_rules('Bénéficiaire : Test', r)
        self.assertEqual(len(matched), 1)

    def test_invalid_regex(self):
        with self.assertRaises(ValueError):
            validate_rules([dict(DEFAULT_RULES[0], pattern='(')])
        with self.assertRaises(ValueError):
            validate_rules([dict(DEFAULT_RULES[0], pattern=r'foo')])

    def test_preview(self):
        preview = extraction_preview(SAMPLE, DEFAULT_RULES)
        self.assertTrue(preview['matched'])
        self.assertEqual(len(preview['mappings']), 5)
        self.assertFalse(extraction_preview('No OCR', DEFAULT_RULES)['matched'])

    def test_generic_regex(self):
        rule = dict(DEFAULT_RULES[0], pattern=r'Order[: ]+([A-Z]+)',
                    target='title', prefix='Order ', required=True)
        found = extract_rules('Order ABCD', [rule])
        self.assertEqual(found[0]['value'], 'Order ABCD')

    def test_form_mapping(self):
        form = {'paperless_url': ['http://localhost:8000'], 'api_token': [''],
                'poll_seconds': ['30'], 'scan_documents': ['100'], 'dry_run': ['1'],
                'rule_label[]': ['Custom'], 'rule_enabled[]': ['1'],
                'rule_required[]': ['1'], 'rule_pattern[]': [r'Doc (\d+)'],
                'rule_target[]': ['custom_field'], 'rule_field[]': ['42'],
                'rule_transform[]': ['text'], 'rule_prefix[]': [''],
                'rule_currency[]': ['EUR']}
        class FakePaperless:
            def __init__(self, url, token): pass
        result = read_settings_form(form, {'api_token': 'existing'}, FakePaperless)
        self.assertEqual(result['rules'][0]['field_id'], 42)
        self.assertEqual(result['api_token'], 'existing')
        self.assertTrue(result['dry_run'])


if __name__ == '__main__':
    unittest.main()
