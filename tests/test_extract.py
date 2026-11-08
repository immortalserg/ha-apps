import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'paperless_auto_metadata'))
from main import extract, process, DEFAULTS

SAMPLE = '''Bénéficiaire : GROUPE RADIOLOGIQUE HRS
IBAN LU16 0019 8155 4289 6000
Banque du bénéficiaire : BCEELULLXXX
Montant : 190,30 EUR
Date valeur débit : 17.09.2026
Communication : 8997-211661 au 27.08.2026
'''

class TestExtract(unittest.TestCase):
    def test_example(self):
        data = extract(SAMPLE)
        self.assertEqual(data['beneficiary'], 'GROUPE RADIOLOGIQUE HRS')
        self.assertEqual(data['iban'], 'LU160019815542896000')
        self.assertEqual(data['amount'], '190.30')
        self.assertEqual(data['purpose'], '8997-211661 au 27.08.2026')
        self.assertEqual(data['title'], 'оплата 8997-211661 au 27.08.2026')

    def test_skip(self):
        self.assertIsNone(extract('Montant: 190,30 EUR'))

    def test_dry_run(self):
        class FailClient:
            def __getattr__(self, name):
                raise AssertionError('network call ' + name)
        opts = dict(DEFAULTS)
        self.assertEqual(process(FailClient(), {'id': 1, 'content': SAMPLE}, opts), 'dry_run')

    def test_write_preserves_custom_fields(self):
        class FakeClient:
            payload = None
            def correspondent(self, name): return 7
            def request(self, method, path, payload):
                self.payload = payload
        client = FakeClient()
        opts = dict(DEFAULTS, dry_run=False)
        doc = {'id': 1, 'content': SAMPLE, 'custom_fields': [{'field': 15, 'value': 'keep'}]}
        self.assertEqual(process(client, doc, opts), 'updated')
        fields = {f['field']: f['value'] for f in client.payload['custom_fields']}
        self.assertEqual(fields[15], 'keep')
        self.assertEqual(fields[2], 'EUR190.30')
        self.assertEqual(fields[3], 'LU160019815542896000')
        self.assertEqual(fields[4], '8997-211661 au 27.08.2026')
        self.assertEqual(client.payload['correspondent'], 7)

if __name__ == '__main__': unittest.main()