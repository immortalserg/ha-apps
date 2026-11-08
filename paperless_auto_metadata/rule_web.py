"""Home Assistant Ingress UI for configurable Paperless OCR rules."""
import html
import hmac
import json
import re
import secrets
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler
from rules import DEFAULT_RULES, validate_rules, extraction_preview

CSRF = secrets.token_urlsafe(24)
FIELDS = [
    ("paperless_url", "Адрес Paperless-ngx", "url"),
    ("api_token", "API-токен (пустое поле — оставить действующий)", "password"),
    ("poll_seconds", "Проверять каждые N секунд", "number"),
    ("scan_documents", "Сколько последних документов проверять", "number"),
]
STYLES = """
:root{font-family:system-ui,sans-serif}body{margin:0;padding:20px;background:#eff3f8;color:#16243a}
main{max-width:1040px;margin:auto}section{background:white;border-radius:12px;padding:20px;margin:17px 0;
box-shadow:0 1px 9px #0001}h1{font-size:25px;margin:5px 0}h2{font-size:18px;margin:0 0 15px}
label{font-size:13px;font-weight:600;display:block;margin:10px 0;min-width:0}
input,textarea,select{display:block;box-sizing:border-box;width:100%;border:1px solid #c6d0e0;
padding:10px;background:white;border-radius:7px;font:14px system-ui;margin-top:5px;color:#16243a}
textarea{font-family:ui-monospace,monospace;line-height:1.4}
.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:12px;align-items:end}
.rule{background:#f6f8fb;border:1px solid #d7e0ed;border-radius:10px;padding:14px;margin:12px 0}
.rule-head{display:flex;align-items:center;justify-content:space-between}
button{background:#1267da;border:0;padding:11px 15px;border-radius:8px;color:white;cursor:pointer}
button.secondary{background:#dbe6f6;color:#122748}button.remove{background:#fce1e3;color:#8d1831;padding:6px 11px}
.actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:18px}
.muted,small{color:#53677f}pre{background:#10203a;color:white;border-radius:9px;padding:14px;white-space:pre-wrap;overflow-wrap:anywhere}
.notice{background:#e5f0ff;padding:13px;border-radius:8px;white-space:pre-wrap}
.metrics{display:flex;flex-wrap:wrap;gap:12px}.metric{background:#eaf0f8;border-radius:8px;padding:10px;flex:1 1 140px;overflow-wrap:anywhere}
@media(prefers-color-scheme:dark){body{background:#101827;color:#e5edf8}section{background:#1d293b}
.rule{background:#18243a;border-color:#46536b}input,select,textarea{background:#121e30;color:white;border-color:#46536b}
.muted,small{color:#bac8d8}.metric{background:#14243b}.notice{background:#193759}}
"""
SCRIPT = """
const rules=document.getElementById('rules');
document.getElementById('add-rule').addEventListener('click',()=>{
rules.appendChild(document.getElementById('new-rule').content.cloneNode(true));
});
rules.addEventListener('click',(event)=>{
if(event.target.matches('[data-delete]'))event.target.closest('.rule').remove();
});
"""


def esc(value):
    return html.escape(str(value), quote=True)


def select(name, current, values):
    return '<select name="' + esc(name) + '">' + ''.join(
        '<option value="' + esc(value) + '"' +
        (' selected' if str(value) == str(current) else '') + '>' +
        esc(label) + '</option>' for value, label in values) + '</select>'


def rule_card(rule, fields):
    targets = [('custom_field', 'Пользовательское поле'), ('correspondent', 'Корреспондент'),
               ('title', 'Название документа')]
    transformations = [('text', 'Без изменений'), ('uppercase', 'Верхний регистр'),
                       ('lowercase', 'Нижний регистр'), ('compact', 'Убрать пробелы + ВЕРХНИЙ'),
                       ('decimal', 'Число, 190.30'), ('monetary', 'Денежное, EUR190.30')]
    boolean = [('1', 'Да'), ('0', 'Нет')]
    fid = int(rule.get('field_id', 0) or 0)
    field_choices = [(0, '— Не выбрано —')]
    for item in fields:
        field_choices.append((int(item['id']),
             f"{item['name']} (ID {item['id']}, {item.get('data_type','?')})"))
    if fid and fid not in [int(x[0]) for x in field_choices]:
        field_choices.append((fid, f"ID {fid}"))
    field = select('rule_field[]', fid, field_choices) if fields else (
        f'<input name="rule_field[]" type="number" min="0" value="{fid}">')
    return f"""<div class="rule">
    <div class="rule-head"><strong>Правило</strong>
    <button class="remove" type="button" data-delete>Удалить</button></div>
    <div class="row">
      <label>Название правила<input name="rule_label[]" maxlength="120" required
          value="{esc(rule.get('label',''))}"></label>
      <label>Включено{select('rule_enabled[]', '1' if rule.get('enabled',True) else '0', boolean)}</label>
      <label>Обязательно{select('rule_required[]', '1' if rule.get('required',False) else '0', boolean)}</label>
    </div>
    <label>Регулярное выражение (первая группа в скобках — извлекаемое значение)
    <textarea name="rule_pattern[]" rows="2" spellcheck="false" maxlength="800" required>{esc(rule.get('pattern',''))}</textarea></label>
    <div class="row">
      <label>Назначение{select('rule_target[]',rule.get('target','custom_field'),targets)}</label>
      <label>Поле Paperless{field}</label>
      <label>Преобразование{select('rule_transform[]',rule.get('transform','text'),transformations)}</label>
    </div>
    <div class="row">
      <label>Префикс<input name="rule_prefix[]" maxlength="200" value="{esc(rule.get('prefix',''))}"></label>
      <label>Валюта для денежного поля<input name="rule_currency[]" maxlength="3"
          value="{esc(rule.get('currency','EUR'))}"></label>
    </div>
    </div>"""


def read_settings_form(form, old, paperless_class):
    opts = dict(old)
    for key, _label, _type in FIELDS:
        val = form.get(key, [''])[0]
        if key == 'api_token' and not val:
            continue
        if key in ('poll_seconds', 'scan_documents'):
            val = int(val)
        opts[key] = val
    if not 10 <= opts['poll_seconds'] <= 3600:
        raise ValueError('Интервал должен быть от 10 до 3600 секунд')
    if not 1 <= opts['scan_documents'] <= 1000:
        raise ValueError('Количество документов должно быть от 1 до 1000')
    paperless_class(opts['paperless_url'], opts['api_token'])
    opts['dry_run'] = form.get('dry_run', ['0'])[0] == '1'
    names = ('rule_label[]', 'rule_enabled[]', 'rule_required[]', 'rule_pattern[]',
             'rule_target[]', 'rule_field[]', 'rule_transform[]', 'rule_prefix[]',
             'rule_currency[]')
    columns = [form.get(name, []) for name in names]
    if not all(len(column) == len(columns[0]) for column in columns):
        raise ValueError('Некорректная таблица сопоставления полей')
    rules = []
    for index, row in enumerate(zip(*columns), start=1):
        label, enabled, required, pattern, target, field, transform, prefix, currency = row
        rules.append({
            'name': f'rule_{index}', 'label': label,
            'enabled': enabled == '1', 'required': required == '1', 'pattern': pattern,
            'target': target, 'field_id': field, 'transform': transform,
            'prefix': prefix, 'currency': currency
        })
    opts['rules'] = validate_rules(rules)
    return opts


def make_handler(settings, status, lock, run_now, paperless_class, write_json, settings_file):
    class Handler(BaseHTTPRequestHandler):
        def permitted(self):
            # Home Assistant ingress proxy; localhost is allowed for tests.
            if self.client_address[0] not in ('172.30.32.2', '127.0.0.1', '::1'):
                self.send_error(403, 'Use Home Assistant ingress')
                return False
            return True

        def send_html(self, content):
            data = content.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy',
                f"default-src 'none'; script-src 'nonce-{CSRF}'; "
                "style-src 'unsafe-inline'; form-action 'self'; base-uri 'self'; frame-ancestors 'self'")
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def page(self, message='', sample='', preview=None, candidate=None):
            opts = candidate if candidate is not None else settings()
            fields, field_error = [], ''
            if opts.get('api_token'):
                try:
                    paperless = paperless_class(opts['paperless_url'], opts['api_token'])
                    fields = list(paperless.pages('/api/custom_fields/?page_size=100'))[:1000]
                except (urllib.error.HTTPError, urllib.error.URLError, ValueError, KeyError) as error:
                    field_error = str(error)
            inputs = []
            for name, label, type_name in FIELDS:
                val = '' if name == 'api_token' else opts.get(name, '')
                required = '' if name == 'api_token' else ' required'
                inputs.append(f'<label>{esc(label)}<input name="{name}" type="{type_name}" '
                              f'value="{esc(val)}" autocomplete="off"{required}></label>')
            with lock:
                current = dict(status)
            metrics = ''.join(f'<div class="metric"><small>{esc(key)}</small>'
                              f'<div>{esc(value)}</div></div>' for key,value in current.items())
            notice = '<p class="notice">' + esc(message) + '</p>' if message else ''
            if field_error:
                notice += '<p class="notice">Не удалось загрузить список полей: ' + esc(field_error) + (
                    '. Укажи ID поля вручную.</p>')
            cards = ''.join(rule_card(rule, fields) for rule in opts.get('rules', DEFAULT_RULES))
            blank = rule_card({'label':'','pattern':'','target':'custom_field','field_id':0,
                               'transform':'text','prefix':'','currency':'EUR',
                               'enabled':True,'required':False}, fields)
            checked = ' checked' if opts.get('dry_run', True) else ''
            preview_html = ('<h3>Результат проверки</h3><pre>' +
                            esc(json.dumps(preview,ensure_ascii=False,indent=2)) +
                            '</pre>') if preview is not None else ''
            self.send_html(f"""<!doctype html><html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Paperless Auto Metadata</title><style>{STYLES}</style></head><body><main>
<h1>Paperless Auto Metadata</h1>
<p class="muted">Гибкие правила поиска в OCR и сопоставления с полями Paperless-ngx</p>
{notice}
<section><h2>Статус</h2><div class="metrics">{metrics}</div>
<form method="post"><input type="hidden" name="csrf" value="{CSRF}">
<button name="action" value="scan">Проверить документы сейчас</button></form></section>
<form method="post"><input type="hidden" name="csrf" value="{CSRF}">
<section><h2>Подключение</h2><div class="row">{''.join(inputs)}</div>
<label><input style="display:inline;width:auto" name="dry_run" type="checkbox"
 value="1"{checked}> Тестовый режим: не изменять документы</label></section>
<section><h2>Правила</h2>
<p class="muted">Добавляй любые регулярные выражения и выбирай назначение.
У каждого выражения должна быть захватывающая группа в круглых скобках.
Если обязательное правило не совпало, документ пропускается.</p>
<div id="rules">{cards}</div><button id="add-rule" type="button" class="secondary">+ Добавить правило</button>
<template id="new-rule">{blank}</template></section>
<section><h2>Проверить OCR-текст</h2>
<p class="muted">Можно проверить изменения до сохранения; данные Paperless не изменятся.</p>
<textarea name="sample" rows="8" placeholder="Вставь OCR-текст">{esc(sample)}</textarea>
{preview_html}
<div class="actions"><button name="action" value="preview" class="secondary">Проверить выражения</button>
<button name="action" value="save">Сохранить настройки</button></div>
</section></form><script nonce="{CSRF}">{SCRIPT}</script></main></body></html>""")

        def do_GET(self):
            if self.permitted():
                self.page()

        def do_POST(self):
            if not self.permitted():
                return
            form = {}
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 250000:
                    self.send_error(413)
                    return
                form = urllib.parse.parse_qs(self.rfile.read(length).decode('utf-8'),
                                             keep_blank_values=True)
                if not hmac.compare_digest(form.get('csrf',[''])[0], CSRF):
                    self.send_error(403, 'Invalid form token')
                    return
                action = form.get('action', [''])[0]
                if action == 'scan':
                    run_now.set()
                    self.page('Проверка запущена.')
                    return
                if action not in ('save', 'preview'):
                    self.send_error(400)
                    return
                opts = read_settings_form(form, settings(), paperless_class)
                sample = form.get('sample', [''])[0][:150000]
                if action == 'preview':
                    result = extraction_preview(sample, opts['rules'])
                    self.page('Предварительный просмотр (без изменения Paperless).',
                              sample, result, opts)
                else:
                    write_json(settings_file, opts)
                    run_now.set()
                    self.page('Настройки сохранены. Новые правила активны.', sample)
            except (ValueError, TypeError, KeyError, re.error) as error:
                self.page('Ошибка: ' + str(error), form.get('sample', [''])[0][:150000])

        def log_message(self, format, *args):
            return
    return Handler
