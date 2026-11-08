"""Optional OCR translation through a user-configured LibreTranslate server."""
import json
import urllib.request

def translate_text(content, opts):
    if not opts.get('translate_enabled', False):
        return None
    field = int(opts.get('translate_field_id') or 0)
    if field <= 0:
        raise ValueError('Select a text custom field for translation')
    url = str(opts.get('translate_url') or '').strip().rstrip('/')
    if not url.startswith(('http://', 'https://')):
        raise ValueError('LibreTranslate URL must start with http:// or https://')
    language = str(opts.get('translate_target') or 'ru').strip()
    source = str(opts.get('translate_source') or 'auto').strip()
    if not language or len(language) > 20 or len(source) > 20:
        raise ValueError('Invalid translation language')
    if not content or not content.strip():
        return None
    # Avoid sending huge OCR documents to translation servers.
    max_chars = int(opts.get('translate_max_chars') or 12000)
    if not 1 <= max_chars <= 50000:
        raise ValueError('Translation size must be 1..50000 characters')
    payload = {'q': content[:max_chars], 'source': source,
               'target': language, 'format': 'text'}
    key = str(opts.get('translate_api_key') or '')
    if key:
        payload['api_key'] = key
    req = urllib.request.Request(
        url + '/translate', data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
        method='POST')
    with urllib.request.urlopen(req, timeout=90) as response:
        result = json.load(response)
    translated = result.get('translatedText')
    if not isinstance(translated, str) or not translated.strip():
        raise ValueError('Translation server returned no translatedText')
    return translated.strip()
