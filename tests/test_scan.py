import sys, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'paperless_auto_metadata'))
import main

RULE={'name':'invoice','label':'Invoice','pattern':r'Invoice (\d+)',
'target':'custom_field','field_id':8,'transform':'text','prefix':'','currency':'EUR',
'enabled':True,'required':True}

class Tests(unittest.TestCase):
    def test_fetch_detail(self):
        class Client:
            def __init__(self,url,token): pass
            def documents(self,count): return [{'id':7}]
            def document(self,id): return {'id':7,'content':'Invoice 123','custom_fields':[]}
        opts=dict(main.DEFAULTS,api_token='x',rules=[RULE])
        with patch.object(main,'settings',return_value=opts), patch.object(main,'Paperless',Client), patch.object(main,'read_json',return_value={}),patch.object(main,'write_json'):
            self.assertEqual(main.scan_once()['dry_run'],1)
    def test_no_rules_no_requests(self):
        opts=dict(main.DEFAULTS,api_token='x')
        with patch.object(main,'settings',return_value=opts):
            self.assertEqual(main.scan_once()['updated'],0)
if __name__=='__main__': unittest.main()
