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
from translation import translate_text

DATA = Path('/data')
OPTIONS_FILE = DATA / 'options.json'
SETTINGS_FILE = DATA / 'settings.json'
STATE_FILE = DATA / 'processed.json'
RULES_STATE_FILE = DATA / 'rules_processed.json'
TRANSLATION_STATE_FILE = DATA / 'translation_processed.json'
LOG = logging.getLogger('paperless-auto-metadata')
DEFAULTS = {
    'paperless_url': '', 'api_token': '',
    'poll_seconds': 30, 'scan_documents': 100, 'dry_run': True,
    'rules': [],
    'translate_enabled': False, 'translate_url': '',
    'translate_api_key': '', 'translate_source': 'auto',
    'translate_target': 'ru', 'translate_field_id': 0,
    'translate_max_chars': 12000,
    'translate_tag_ids': [], 'translate_tag_match': 'any',
    'translate_trigger': 'tag_or_field', 'ui_language': 'ru',
}

lock = threading.RLock()
status = {'last_scan': '—', 'updated': 0, 'dry_run': 0, 'skipped': 0, 'errors': 0, 'last_error': '', 'last_result': ''}
run_now = threading.Event()
full_translation_scan = threading.Event()


def read_json(path, fallback):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else fallback
    except (OSError, ValueError):
        return fallback


def is_legacy_bank_rules(rules):
    if not isinstance(rules, list) or len(rules) != 5:
        return False
    return ([r.get('name') for r in rules] ==
            ['beneficiary', 'amount', 'iban', 'purpose', 'title'] and
            [r.get('target') for r in rules] ==
            ['correspondent', 'custom_field', 'custom_field', 'custom_field', 'title'] and
            [r.get('field_id') for r in rules] == [0, 2, 3, 4, 0] and
            all(r.get('required') and r.get('enabled') for r in rules))


def settings():
    data = dict(DEFAULTS)
    data.update({k: v for k, v in read_json(OPTIONS_FILE, {}).items() if k in data})
    data.update({k: v for k, v in read_json(SETTINGS_FILE, {}).items() if k in data})
    # Remove the old built-in bank-specific rules when upgrading.
    # Preserve rules explicitly customized by the user.
    if is_legacy_bank_rules(data.get('rules')):
        data['rules'] = []
    return data


def save_settings(data):
    write_json(SETTINGS_FILE, data)


def migrate_settings():
    existing = read_json(SETTINGS_FILE, {})
    if is_legacy_bank_rules(existing.get('rules')):
        existing['rules'] = []
        write_json(SETTINGS_FILE, existing)


def write_json(path, data):
    DATA.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def extract(content, opts=None):
    o = opts if opts is not None else DEFAULTS
    matches = extract_rules(content, o.get('rules', []))
    return {r['name']: r['value'] for r in matches} if matches else None


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

    def document(self, document_id):
        return self.request('GET', f'/api/documents/{int(document_id)}/')

    def correspondent(self, name):
        name = str(name).strip()
        if not name:
            raise ValueError('Correspondent name cannot be empty')
        # Search all correspondents to avoid a filtered search missing an exact
        # match due to server-side filtering or pagination.
        for item in self.pages('/api/correspondents/?page_size=100'):
            if str(item.get('name', '')).strip().casefold() == name.casefold():
                return int(item['id'])
        # A new correspondent must be created before assigning it to a document.
        created = self.request('POST', '/api/correspondents/', {'name': name})
        if not created or 'id' not in created:
            raise ValueError('Paperless did not return an ID for the new correspondent')
        LOG.info('Created correspondent %s (ID %s)', name, created['id'])
        return int(created['id'])


def process(client, doc, opts):
    rules = opts.get('rules', [])
    matches = extract_rules(doc.get('content') or '', rules) if rules else None
    translation = None
    if opts.get('translate_enabled'):
        field_id = int(opts.get('translate_field_id') or 0)
        custom_before = {int(f['field']): f.get('value') for f in (doc.get('custom_fields') or [])}
        existing = custom_before.get(field_id)
        # Never overwrite an existing translation, even if tag filters match.
        field_empty = existing is None or (isinstance(existing, str) and not existing.strip())
        field_present = field_id in custom_before
        tags = set(int(t) for t in (doc.get('tags') or []))
        selected = set(int(t) for t in opts.get('translate_tag_ids', []))
        match_mode = opts.get('translate_tag_match', 'any')
        tag_match = not selected or (selected <= tags if match_mode == 'all' else bool(selected & tags))
        trigger = opts.get('translate_trigger', 'tag_or_field')
        tag_trigger = bool(selected) and tag_match
        field_trigger = field_present and field_empty
        eligible = ((tag_trigger or field_trigger) if trigger == 'tag_or_field' else
                    tag_trigger if trigger == 'tag_only' else field_trigger)
        if field_empty and eligible:
            translation = translate_text(doc.get('content') or '', opts)
    if matches is None and translation is None:
        return 'skipped'
    custom = {int(f['field']): f['value'] for f in (doc.get('custom_fields') or [])}
    original = dict(custom)
    payload = {}
    beneficiary = None
    for match in matches or []:
        if match['target'] == 'custom_field':
            custom[int(match['field_id'])] = match['value']
        elif match['target'] == 'title':
            payload['title'] = match['value']
        elif match['target'] == 'correspondent':
            beneficiary = match['value']
    if translation is not None:
        custom[int(opts['translate_field_id'])] = translation
    if opts.get('dry_run', True):
        LOG.info('DRY RUN #%s rules=%d translation=%s',
                 doc['id'], len(matches or []), bool(translation))
        return 'dry_run'
    if beneficiary is not None:
        payload['correspondent'] = client.correspondent(beneficiary)
    if custom != original:
        payload['custom_fields'] = [
            {'field': field, 'value': value} for field, value in sorted(custom.items())
        ]
    if not payload:
        return 'skipped'
    client.request('PATCH', f"/api/documents/{int(doc['id'])}/", payload)
    LOG.info('Updated document #%s (rules=%d, translated=%s)',
             doc['id'], len(matches or []), bool(translation))
    return 'updated'


def scan_once(full_translation=False):
    opts = settings()
    if not opts['api_token']:
        raise ValueError('Set API token using the web interface or Home Assistant Configuration tab')
    if not opts.get('rules') and not opts.get('translate_enabled'):
        return {'updated': 0, 'dry_run': 0, 'skipped': 0, 'errors': 0}
    client = Paperless(opts['paperless_url'], opts['api_token'])
    rules_state = read_json(RULES_STATE_FILE, {})
    translation_state = read_json(TRANSLATION_STATE_FILE, {})
    # Rules run only once for each document/content/rules combination. Translation
    # has an independent cache so adding a tag or an empty field can trigger it later.
    rules_opts = dict(opts, translate_enabled=False)
    translation_opts = dict(opts, rules=[])
    rules_config = hashlib.sha256(json.dumps(opts.get('rules', []), sort_keys=True).encode()).hexdigest()
    translation_config = hashlib.sha256(json.dumps({
        k: v for k, v in opts.items() if k.startswith('translate_')
    }, sort_keys=True).encode()).hexdigest()
    counts = {'updated': 0, 'dry_run': 0, 'skipped': 0, 'errors': 0}
    recent = client.documents(int(opts['scan_documents']))
    if full_translation and opts.get('translate_enabled'):
        summaries = list(client.pages('/api/documents/?page_size=100&ordering=-id'))
    else:
        # Include recently edited old documents so adding a translation tag or
        # destination field triggers translation without rerunning OCR rules.
        summaries = list(recent)
        if opts.get('translate_enabled'):
            modified = list(client.pages('/api/documents/?page_size=100&ordering=-modified'))
            seen = {str(item['id']) for item in summaries}
            for item in modified[:int(opts['scan_documents'])]:
                if str(item['id']) not in seen:
                    summaries.append(item)
                    seen.add(str(item['id']))
    recent_ids = {str(item['id']) for item in recent}
    for summary in reversed(summaries):
        doc_id = str(summary['id'])
        try:
            doc = client.document(doc_id)
            content = doc.get('content') or ''
            if not content.strip():
                counts['skipped'] += 1
                continue
            if opts.get('rules') and doc_id in recent_ids:
                rule_key = hashlib.sha256(('rules-v2:' + rules_config + content).encode()).hexdigest()
                if rules_state.get(doc_id) != rule_key:
                    outcome = process(client, doc, rules_opts)
                    counts[outcome] += 1
                    # A document with no matching rules is still marked as checked;
                    # edits to tags/translation fields must not rerun regex rules.
                    if outcome in ('updated', 'dry_run', 'skipped'):
                        rules_state[doc_id] = rule_key
                        write_json(RULES_STATE_FILE, rules_state)
                    if outcome == 'updated':
                        doc = client.document(doc_id)
            if opts.get('translate_enabled'):
                custom = {int(f['field']): f.get('value') for f in (doc.get('custom_fields') or [])}
                target_id = int(opts.get('translate_field_id') or 0)
                existing = custom.get(target_id)
                field_empty = existing is None or (isinstance(existing, str) and not existing.strip())
                # Never run translation again when the destination is filled.
                if field_empty:
                    key = hashlib.sha256(('translation-v2:' + translation_config +
                        json.dumps({'content': content, 'tags': doc.get('tags'),
                                    'field_present': target_id in custom,
                                    'field_value': existing}, sort_keys=True,
                                   ensure_ascii=False)).encode()).hexdigest()
                    if translation_state.get(doc_id) != key:
                        outcome = process(client, doc, translation_opts)
                        counts[outcome] += 1
                        if outcome in ('updated', 'dry_run'):
                            translation_state[doc_id] = key
                            write_json(TRANSLATION_STATE_FILE, translation_state)
                else:
                    counts['skipped'] += 1
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError, KeyError, TypeError) as exc:
            counts['errors'] += 1
            LOG.error('Document #%s failed: %s', doc_id, exc)
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
            scan_once(full_translation=full_translation_scan.is_set())
            full_translation_scan.clear()
        except Exception as exc:
            LOG.exception('Scan failed')
            with lock:
                status['errors'] += 1
                status['last_error'] = str(exc)
        run_now.wait(timeout=max(10, int(settings()['poll_seconds'])))
        run_now.clear()


from rule_web import make_handler
Handler = make_handler(settings, status, lock, run_now, Paperless, write_json, SETTINGS_FILE, full_translation_scan)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    DATA.mkdir(parents=True, exist_ok=True)
    migrate_settings()
    threading.Thread(target=worker, daemon=True).start()
    LOG.info('Web interface on port 8099 (Home Assistant ingress)')
    ThreadingHTTPServer(('0.0.0.0', 8099), Handler).serve_forever()

if __name__ == '__main__':
    main()