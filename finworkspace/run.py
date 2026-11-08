#!/usr/bin/env python3

import json
import os
from pathlib import Path
import secrets
import sys

DATA = Path("/data")
OPTIONS_FILE = DATA / "options.json"


def read_options():
    try:
        value = json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        print(f"[FinWorkspace] Cannot read options: {exc}", file=sys.stderr)
        return {}


def persistent_secret(option_name, filename):
    configured = str(options.get(option_name, "") or "").strip()
    if configured:
        return configured

    path = DATA / filename
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value

    value = secrets.token_hex(32)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(value + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return value


def set_option(option_name, env_name, transform=None):
    value = options.get(option_name)
    if value is None or value == "":
        return
    if transform:
        value = transform(value)
    os.environ[env_name] = str(value)


def as_bool(value):
    return "true" if bool(value) else "false"


DATA.mkdir(parents=True, exist_ok=True)
for name in ("uploads", "documents", "logs"):
    (DATA / name).mkdir(parents=True, exist_ok=True)

options = read_options()

# Секреты создаются один раз и переживают обновления приложения.
os.environ["SECRET_KEY"] = persistent_secret(
    "secret_key", ".secret_key"
)
os.environ["NOTIFICATION_ENCRYPTION_KEY"] = persistent_secret(
    "notification_encryption_key", ".notification_encryption_key"
)

# Постоянное хранилище Home Assistant.
os.environ.update({
    # The 1.4.x settings store, encrypted secrets and uploaded bank key
    # must live on Home Assistant's persistent data volume.
    "APP_DATA_DIR": "/data",
    "DATABASE_URL": "sqlite:////data/finance.db",
    "UPLOAD_DIR": "/data/uploads",
    "DOCUMENTS_DIR": "/data/documents",
    "LOG_DIR": "/data/logs",
    "BACKEND_PORT": "8223",
    "DEBUG": "false",
    "TRUST_PROXY_HEADERS": "false",
    "NOTIFICATIONS_ENABLED": as_bool(
        options.get("notifications_enabled", True)
    ),
})

set_option("openrouter_api_key", "OPENROUTER_API_KEY")
set_option("ai_monthly_cap_usd", "AI_MONTHLY_CAP_USD")
set_option("admin_emails", "ADMIN_EMAILS",
           lambda value: json.dumps([
               item.strip()
               for item in str(value).split(",")
               if item.strip()
           ]))
set_option("initial_admin_email", "INITIAL_ADMIN_EMAIL")
set_option("initial_admin_name", "INITIAL_ADMIN_NAME")
set_option("initial_admin_password", "INITIAL_ADMIN_PASSWORD")
set_option("public_base_url", "PUBLIC_BASE_URL")
set_option("frontend_base_url", "FRONTEND_BASE_URL")
set_option("legal_operator_name", "LEGAL_OPERATOR_NAME")
set_option("legal_contact_email", "LEGAL_CONTACT_EMAIL")
set_option("legal_jurisdiction", "LEGAL_JURISDICTION")
set_option("smtp_host", "SMTP_HOST")
set_option("smtp_port", "SMTP_PORT")
set_option("smtp_user", "SMTP_USER")
set_option("smtp_password", "SMTP_PASSWORD")
set_option("smtp_from", "SMTP_FROM")
set_option("smtp_use_tls", "SMTP_USE_TLS", as_bool)

print("[FinWorkspace] Starting; persistent data directory: /data",
      flush=True)

os.chdir("/app")
os.execv(
    "/app/docker-entrypoint.sh",
    ["/app/docker-entrypoint.sh"]
)
