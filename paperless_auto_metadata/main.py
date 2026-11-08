#!/usr/bin/env python3
"""Paperless-ngx OCR metadata extraction with an ingress web interface."""
import hashlib
import hmac
import secrets
import html
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from rules import DEFAULT_RULES, validate_rules, extract_rules, extraction_preview

DATA = Path('/data')
OPTIONS_FILE = DATA / 'options.json'
SETTINGS_FILE = DATA / 'settings.json'
STATE_FILE = DATA / 'processed.json'
LOG = logging.getLogger('paperless-auto-metadata')
DEFAULTS = {
    'paperless_url': 'http://192.168.20.10:8000', 'api_token': '',
    'poll_seconds': 30, 'scan_documents': 100, 'amount_field_id': 2,
    'iban_field_id': 3, 'purpose_field_id': 4, 'amount_format': 'monetary',
    'title_prefix': 'оплата ', 'dry_run': True,
    'beneficiary_regex': r'^\s*B[ée]n[ée]ficiaire\s*:\s*([^\r\n]+)',
    'amount_regex': r'^\s*Montant\s*:\s*([\d\s\u00a0\u202f.,]+)\s*EUR\b',
    'iban_regex': r'^\s*IBAN\s*:?\s*(LU(?:[ \t]*[A-Z0-9]){18})\b',
    'purpose_regex': r'^\s*Communication\s*:\s*([^\r\n]+)',
}
DEFAULTS['rules'] = DEFAULT_RULES
csrf_token = secrets.token_urlsafe(32)
lock = threading.RLock()
status = {'last_scan': '—', 'updated': 0, 'dry_run': 0, 'skipped': 0, 'errors': 0, 'last_error': '', 'last_result': ''}
run_now = threading.Event()


def read_json(path, fallback):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else fallback
    except (OSError, ValueError):
        return fallback


def settings():
    data = dict(DEFAULTS)
    data.update({k: v for k, v in read_json(OPTIONS_FILE, {}).items() if k in data})
    data.update({k: v for k, v in read_json(SETTINGS_FILE, {}).items() if k in data})
    return data


def write_json(path, data):
    DATA.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def capture(content, pattern):
    match = re.search(pattern, content, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip(' \t:;') if match else None


def extract(content, opts=None):
    """Legacy preview shape, backed by user-configurable rules."""
    o = opts or DEFAULTS
    matches = extract_rules(content, o.get('rules', DEFAULT_RULES))
    if matches is None:
        return None
    values = {r['name']: r['value'] for r in matches}
    if 'amount' in values and values['amount'].startswith(('EUR', 'USD')):
        values['amount'] = values['amount'][3:]
    return values


class Paperless:
    def __init__(self, url, token):
        if not url.startswith(('http://', 'https://')):
            raise ValueError('Paperless URL must start with http:// or https://')
        self.base = url.rstrip('/')
        self.token = token

    def request(self, method, path, payload=None):
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        req = urllib.request.Request(self.base + path, data=body, method=method,
            headers={'Authorization': 'Token ' + self.token, 'Accept': 'application/json',
                     'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=25) as response:
            data = response.read()
            return json.loads(data) if data else None

    def pages(self, path):
        while path:
            page = self.request('GET', path)
            yield from page.get('results', [])
            next_url = page.get('next')
            if not next_url:
                break
            parsed = urllib.parse.urlsplit(next_url)
            path = parsed.path + ('?' + parsed.query if parsed.query else '')

    def documents(self, max_count):
        path = '/api/documents/?' + urllib.parse.urlencode({'page_size': min(max_count, 100), 'ordering': '-id'})
        results = []
        for doc in self.pages(path):
            results.append(doc)
            if len(results) >= max_count:
                break
        return results

    def correspondent(self, name):
        # Search is advisory: always compare exact names to avoid near-match assignment.
        path = '/api/correspondents/?' + urllib.parse.urlencode({'name__icontains': name, 'page_size': 100})
        for item in self.pages(path):
            if item.get('name', '').strip().casefold() == name.strip().casefold():
                return item['id']
        return self.request('POST', '/api/correspondents/', {'name': name})['id']


def process(client, doc, opts):
    matches = extract_rules(doc.get('content') or '', opts.get('rules', DEFAULT_RULES))
    if matches is None:
        return 'skipped'
    custom = {int(f['field']): f['value'] for f in (doc.get('custom_fields') or [])}
    payload = {}
    beneficiary = None
    for match in matches:
        if match['target'] == 'custom_field':
            custom[int(match['field_id'])] = match['value']
        elif match['target'] == 'title':
            payload['title'] = match['value']
        elif match['target'] == 'correspondent':
            beneficiary = match['value']
    if opts.get('dry_run', True):
        LOG.info('DRY RUN #%s mappings=%s', doc['id'],
                 [(m['label'], m['target'], m['field_id'], m['value']) for m in matches])
        return 'dry_run'
    if beneficiary is not None:
        payload['correspondent'] = client.correspondent(beneficiary)
    if custom != {int(f['field']): f['value'] for f in (doc.get('custom_fields') or [])}:
        payload['custom_fields'] = [
            {'field': field, 'value': value} for field, value in sorted(custom.items())
        ]
    if not payload:
        return 'skipped'
    client.request('PATCH', f"/api/documents/{int(doc['id'])}/", payload)
    LOG.info('Updated document #%s (%s rules)', doc['id'], len(matches))
    return 'updated'


def scan_once():
    opts = settings()
    if not opts['api_token']:
        raise ValueError('Set API token using the web interface or Home Assistant Configuration tab')
    client = Paperless(opts['paperless_url'], opts['api_token'])
    state = read_json(STATE_FILE, {})
    documents = client.documents(int(opts['scan_documents']))
    counts = {'updated': 0, 'dry_run': 0, 'skipped': 0, 'errors': 0}
    opts_fingerprint = hashlib.sha256(json.dumps({k: v for k, v in opts.items() if k not in ('api_token', 'paperless_url', 'poll_seconds', 'scan_documents')}, sort_keys=True).encode()).hexdigest()
    for doc in reversed(documents):
        doc_id = str(doc['id'])
        text = doc.get('content') or ''
        fingerprint = hashlib.sha256((opts_fingerprint + text).encode()).hexdigest()
        if state.get(doc_id) == fingerprint:
            continue
        try:
            outcome = process(client, doc, opts)
            counts[outcome] += 1
            state[doc_id] = fingerprint
            write_json(STATE_FILE, state)
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError, KeyError, TypeError) as exc:
            counts['errors'] += 1
            LOG.error('Document #%s failed: %s', doc_id, exc)
    # Bound persistent cache to recent document window plus a small historical buffer.
    if len(state) > 10000:
        state = {str(d['id']): state[str(d['id'])] for d in documents if str(d['id']) in state}
        write_json(STATE_FILE, state)
    with lock:
        status['last_scan'] = time.strftime('%Y-%m-%d %H:%M:%S')
        for k, v in counts.items():
            status[k] += v
        status['last_result'] = ', '.join(f'{k}: {v}' for k, v in counts.items())
        status['last_error'] = ''
    return counts


def worker():
    while True:
        try:
            scan_once()
        except Exception as exc:
            LOG.exception('Scan failed')
            with lock:
                status['errors'] += 1
                status['last_error'] = str(exc)
        run_now.wait(timeout=max(10, int(settings()['poll_seconds'])))
        run_now.clear()


from rule_web import make_handler
Handler = make_handler(settings, status, lock, run_now, Paperless, write_json, SETTINGS_FILE)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    DATA.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=worker, daemon=True).start()
    LOG.info('Web interface on port 8099 (Home Assistant ingress)')
    ThreadingHTTPServer(('0.0.0.0', 8099), Handler).serve_forever()

if __name__ == '__main__':
    main()