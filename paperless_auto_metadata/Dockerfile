FROM python:3.12-alpine
LABEL io.hass.type="addon" io.hass.version="1.6.0" io.hass.arch="amd64|aarch64|armv7"
WORKDIR /app
COPY main.py rules.py rule_web.py translation.py /app/
CMD ["python3", "-u", "/app/main.py"]
