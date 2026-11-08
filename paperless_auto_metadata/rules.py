"""Safe, configurable OCR capture rules for Paperless-ngx."""
import re
from decimal import Decimal, InvalidOperation

TARGETS = {"custom_field", "title", "correspondent"}
TRANSFORMS = {"text", "uppercase", "lowercase", "compact", "decimal", "monetary"}
DEFAULT_RULES = [
    {"name": "beneficiary", "label": "Bénéficiaire", "enabled": True, "required": True,
     "pattern": r"^\s*B[ée]n[ée]ficiaire\s*:\s*([^\r\n]+)", "target": "correspondent",
     "field_id": 0, "transform": "text", "prefix": "", "currency": "EUR"},
    {"name": "amount", "label": "Montant", "enabled": True, "required": True,
     "pattern": r"^\s*Montant\s*:\s*([\d\s\u00a0\u202f.,]+)\s*EUR\b",
     "target": "custom_field", "field_id": 2, "transform": "monetary",
     "prefix": "", "currency": "EUR"},
    {"name": "iban", "label": "IBAN", "enabled": True, "required": True,
     "pattern": r"^\s*IBAN\s*:?\s*(LU(?:[ \t]*[A-Z0-9]){18})\b",
     "target": "custom_field", "field_id": 3, "transform": "compact",
     "prefix": "", "currency": "EUR"},
    {"name": "purpose", "label": "Communication", "enabled": True, "required": True,
     "pattern": r"^\s*Communication\s*:\s*([^\r\n]+)", "target": "custom_field",
     "field_id": 4, "transform": "text", "prefix": "", "currency": "EUR"},
    {"name": "title", "label": "Document title", "enabled": True, "required": True,
     "pattern": r"^\s*Communication\s*:\s*([^\r\n]+)", "target": "title",
     "field_id": 0, "transform": "text", "prefix": "оплата ", "currency": "EUR"},
]


def validate_rules(rules):
    if not isinstance(rules, list) or len(rules) > 100:
        raise ValueError("Rules must be a list of no more than 100 items")
    result = []
    for index, raw in enumerate(rules):
        if not isinstance(raw, dict):
            raise ValueError(f"Rule {index + 1} must be an object")
        name = str(raw.get("name", f"rule_{index + 1}")).strip()[:80]
        label = str(raw.get("label", name)).strip()[:120]
        pattern = str(raw.get("pattern", ""))
        target = str(raw.get("target", ""))
        transform = str(raw.get("transform", "text"))
        prefix = str(raw.get("prefix", ""))[:200]
        currency = str(raw.get("currency", "EUR")).strip().upper()
        enabled = bool(raw.get("enabled", True))
        required = bool(raw.get("required", False))
        if not name or not label:
            raise ValueError(f"Rule {index + 1}: name and label are required")
        if len(pattern) > 800 or (enabled and not pattern):
            raise ValueError(f"Rule {index + 1}: invalid regex length")
        if target not in TARGETS:
            raise ValueError(f"Rule {index + 1}: invalid target")
        if transform not in TRANSFORMS:
            raise ValueError(f"Rule {index + 1}: invalid transform")
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError(f"Rule {index + 1}: invalid ISO currency")
        try:
            field_id = int(raw.get("field_id") or 0)
            compiled = re.compile(pattern, re.IGNORECASE | re.MULTILINE) if pattern else None
        except (TypeError, ValueError, re.error) as exc:
            raise ValueError(f"Rule {index + 1}: regex/field error: {exc}") from exc
        if enabled and compiled and compiled.groups < 1:
            raise ValueError(f"Rule {index + 1}: regex must have a capture group (...)")
        if enabled and target == "custom_field" and field_id <= 0:
            raise ValueError(f"Rule {index + 1}: choose a Paperless field")
        if field_id < 0:
            raise ValueError(f"Rule {index + 1}: invalid field ID")
        result.append(dict(name=name, label=label, pattern=pattern, target=target,
                           field_id=field_id, transform=transform, prefix=prefix,
                           currency=currency, enabled=enabled, required=required))
    if not any(rule["enabled"] for rule in result):
        raise ValueError("Enable at least one rule")
    return result


def decimal_value(text):
    value = re.sub(r"[\s\u00a0\u202f]", "", text)
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")
    try:
        amount = Decimal(value).quantize(Decimal("0.01"))
        if not amount.is_finite() or amount < 0:
            raise ValueError("amount must be finite and non-negative")
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {text!r}") from exc
    return str(amount)


def transform_value(raw, rule):
    value = raw.strip(" \t:;")
    transform = rule["transform"]
    if transform == "uppercase":
        value = value.upper()
    elif transform == "lowercase":
        value = value.lower()
    elif transform == "compact":
        value = re.sub(r"\s+", "", value).upper()
    elif transform == "decimal":
        value = decimal_value(value)
    elif transform == "monetary":
        value = rule["currency"] + decimal_value(value)
    return rule["prefix"] + value


def extract_rules(content, rules):
    """Return None when required rules do not match; otherwise captured mappings."""
    rules = validate_rules(rules)
    if not isinstance(content, str):
        content = ""
    # OCR is limited to avoid scanning unexpectedly huge documents.
    text = content[:150000]
    results = []
    for rule in rules:
        if not rule["enabled"]:
            continue
        match = re.search(rule["pattern"], text, re.IGNORECASE | re.MULTILINE)
        value = match.group(1) if match else ""
        if value is None or not str(value).strip():
            if rule["required"]:
                return None
            continue
        try:
            value = transform_value(value, rule)
        except ValueError:
            if rule["required"]:
                return None
            continue
        results.append({**rule, "value": value})
    return results or None


def extraction_preview(content, rules):
    mappings = extract_rules(content, rules)
    if mappings is None:
        return {"matched": False, "mappings": []}
    return {"matched": True, "mappings": [
        {"rule": r["label"], "target": r["target"], "field_id": r["field_id"],
         "value": r["value"]} for r in mappings
    ]}
