import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'paperless_auto_metadata'))
from main import DEFAULTS, extract, process
from rules import extract_rules, validate_rules

RULE = {'name':'invoice','label':'Invoice','pattern':r'Invoice (\\d+)',
'target':'custom_field','field_id':8,'transform':'text','prefix':'','currency':'EUR',
'enabled':True,'required':True}

class Tests(unittest.TestCase):
    def test_no_defaults(self):
        self.assertEqual(DEFAULTS['rules'], [])
        self.assertIsNone(extract('Invoice 123'))
        self.assertEqual(validate_rules([]), [])
    def test_user_rule(self):
        self.assertEqual(extract_rules('Invoice 123',[RULE])[0]['value'],'123')
    def test_no_change_without_rules_or_translation(self):
        class NoNetwork:
            def __getattr__(self, name): raise AssertionError(name)
        self.assertEqual(process(NoNetwork(), {'id':1,'content':'Invoice 123'},DEFAULTS),'skipped')
    def test_custom_mapping(self):
        class Client:
            payload=None
            def request(self, method,path,payload): self.payload=payload
        client=Client()
        opts=dict(DEFAULTS,rules=[RULE],dry_run=False)
        doc={'id':1,'content':'Invoice 123','custom_fields':[{'field':4,'value':'keep'}]}
        self.assertEqual(process(client,doc,opts),'updated')
        values={x['field']:x['value'] for x in client.payload['custom_fields']}
        self.assertEqual(values[8],'123')
        self.assertEqual(values[4],'keep')
if __name__=='__main__': unittest.main()
