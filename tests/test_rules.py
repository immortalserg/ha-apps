import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'paperless_auto_metadata'))
from rules import validate_rules, extract_rules, extraction_preview, DEFAULT_RULES
from rule_web import read_settings_form

RULE={'name':'number','label':'Number','pattern':r'Number (\\d+)',
'target':'custom_field','field_id':12,'transform':'text','prefix':'','currency':'EUR',
'enabled':True,'required':True}

class Tests(unittest.TestCase):
    def test_empty_default(self): self.assertEqual(DEFAULT_RULES,[])
    def test_empty_preview(self): self.assertFalse(extraction_preview('anything',[])['matched'])
    def test_generic(self):
        self.assertEqual(extract_rules('Number 42',[RULE])[0]['value'],'42')
    def test_invalid(self):
        with self.assertRaises(ValueError):
            validate_rules([dict(RULE,pattern='(')])
    def test_form_without_rules(self):
        form={'paperless_url':['http://localhost:8000'],'api_token':[''],
              'poll_seconds':['30'],'scan_documents':['100'],'dry_run':['1'],
              'translate_enabled':['0'],'translate_field_id':['0'],
              'translate_url':[''],'translate_source':['auto'],'translate_target':['ru'],
              'translate_max_chars':['12000']}
        class Paperless:
            def __init__(self,url,token): pass
        result=read_settings_form(form,{'api_token':'keep'},Paperless)
        self.assertEqual(result['rules'],[])
        self.assertEqual(result['api_token'],'keep')
if __name__=='__main__': unittest.main()
