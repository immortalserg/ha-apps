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


INPUTS = [
    ('paperless_url', 'Адрес Paperless-ngx'),
    ('api_token', 'API token (оставь пустым, чтобы сохранить действующий)'),
    ('poll_seconds', 'Проверять каждые N секунд'),
    ('scan_documents', 'Количество последних документов'),
    ('amount_field_id', 'ID поля «Сумма документа»'),
    ('iban_field_id', 'ID поля «IBAN корреспондента»'),
    ('purpose_field_id', 'ID поля «Назначение»'),
    ('title_prefix', 'Префикс названия'),
    ('beneficiary_regex', 'Регулярное выражение Bénéficiaire'),
    ('amount_regex', 'Регулярное выражение Montant'),
    ('iban_regex', 'Регулярное выражение IBAN'),
    ('purpose_regex', 'Регулярное выражение Communication'),
]


class Handler(BaseHTTPRequestHandler):
    def send_html(self, body, code=200):
        raw = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'self'; frame-ancestors 'self'")
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        opts = settings()
        esc = lambda x: html.escape(str(x), quote=True)
        rows = []
        for key, label in INPUTS:
            value = '' if key == 'api_token' else opts[key]
            typ = 'password' if key == 'api_token' else 'text'
            rows.append(f'<label>{esc(label)}<input name="{key}" type="{typ}" value="{esc(value)}" autocomplete="off"></label>')
        with lock:
            info = dict(status)
        options = ''.join(f'<option value="{val}" {"selected" if opts["amount_format"] == val else ""}>{val}</option>' for val in ('monetary', 'number', 'text'))
        checked = 'checked' if opts['dry_run'] else ''
        info_html = ''.join(f'<p><b>{esc(k)}:</b> {esc(v)}</p>' for k, v in info.items())
        self.send_html(f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Paperless Auto Metadata</title><style>
        body{{background:#f3f6fa;color:#162236;font:15px system-ui;margin:0;padding:20px}}main{{max-width:880px;margin:auto}}section{{background:white;border-radius:12px;padding:22px;margin:18px 0;box-shadow:0 2px 12px #0001}}h1{{margin:10px 0}}label{{display:block;margin:12px 0;font-weight:600}}input,select,textarea{{box-sizing:border-box;display:block;width:100%;padding:10px;margin-top:5px;border:1px solid #cbd5e1;border-radius:8px;font:inherit}}input[type=checkbox]{{display:inline;width:auto}}button{{background:#1473e6;color:white;border:0;padding:12px 18px;border-radius:8px;cursor:pointer}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}small{{color:#555}}</style></head><body><main>
        <h1>Paperless Auto Metadata</h1><p>Автоматическое извлечение банковских реквизитов из OCR. Настройки сохраняются внутри дополнения.</p>
        <section><h2>Статус</h2>{info_html}<form method="post"><input type="hidden" name="action" value="scan"><button>Проверить документы сейчас</button></form></section>
        <section><h2>Настройки</h2><form method="post"><input type="hidden" name="action" value="save">{''.join(rows)}
        <label>Формат суммы<select name="amount_format">{options}</select></label>
        <label><input type="checkbox" name="dry_run" value="yes" {checked}> Тестовый режим (не изменять документы)</label>
        <button>Сохранить настройки</button></form><small>API-токен не возвращается в браузер после сохранения. Для рабочей обработки выключи тестовый режим.</small></section>
        <section><h2>Проверить текст OCR</h2><form method="post"><input type="hidden" name="action" value="test"><textarea name="sample" rows="7" placeholder="Вставь OCR-текст"></textarea><button>Извлечь реквизиты</button></form></section></main></body></html>''')

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        if length > 100000:
            self.send_error(413)
            return
        form = urllib.parse.parse_qs(self.rfile.read(length).decode('utf-8'), keep_blank_values=True)
        get = lambda name, default='': form.get(name, [default])[0]
        action = get('action')
        if action == 'scan':
            run_now.set()
            message = 'Проверка запущена. Обнови страницу статуса через несколько секунд.'
        elif action == 'test':
            try:
                parsed = extract(get('sample'), settings())
                message = json.dumps(parsed, ensure_ascii=False, indent=2) if parsed else 'Нужные реквизиты не обнаружены'
            except re.error as exc:
                message = f'Ошибка регулярного выражения: {exc}'
        elif action == 'save':
            opts = settings()
            try:
                for key, _label in INPUTS:
                    value = get(key)
                    if key == 'api_token' and not value:
                        continue
                    if key in ('poll_seconds', 'scan_documents', 'amount_field_id', 'iban_field_id', 'purpose_field_id'):
                        value = int(value)
                    opts[key] = value
                if not 10 <= opts['poll_seconds'] <= 3600 or not 1 <= opts['scan_documents'] <= 1000:
                    raise ValueError('Неверный интервал или размер выборки')
                if any(opts[key] < 1 for key in ('amount_field_id', 'iban_field_id', 'purpose_field_id')):
                    raise ValueError('ID полей должны быть положительными')
                if len({opts[k] for k in ('amount_field_id', 'iban_field_id', 'purpose_field_id')}) != 3:
                    raise ValueError('ID пользовательских полей должны различаться')
                for key in ('beneficiary_regex', 'amount_regex', 'iban_regex', 'purpose_regex'):
                    if re.compile(opts[key]).groups < 1:
                        raise ValueError('Шаблон должен содержать захватывающую группу: ' + key)
                opts['amount_format'] = get('amount_format')
                if opts['amount_format'] not in ('monetary', 'number', 'text'):
                    raise ValueError('Недопустимый формат суммы')
                opts['dry_run'] = get('dry_run') == 'yes'
                Paperless(opts['paperless_url'], opts['api_token'])
                write_json(SETTINGS_FILE, opts)
                run_now.set()
                message = 'Настройки сохранены.'
            except (ValueError, re.error) as exc:
                message = 'Не удалось сохранить: ' + str(exc)
        else:
            self.send_error(400)
            return
        self.send_html('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><body style="font:16px system-ui;padding:24px"><pre>' + html.escape(message) + '</pre><a href="./">Вернуться к настройкам</a></body></html>')

    def log_message(self, format, *args):
        LOG.debug(format, *args)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    DATA.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=worker, daemon=True).start()
    LOG.info('Web interface on port 8099 (Home Assistant ingress)')
    ThreadingHTTPServer(('0.0.0.0', 8099), Handler).serve_forever()

if __name__ == '__main__':
    main()