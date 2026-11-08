FROM python:3.12-alpine
LABEL io.hass.type="addon" io.hass.version="1.1.0" io.hass.arch="amd64|aarch64|armv7"
WORKDIR /app
COPY main.py /app/main.py
CMD ["python3", "-u", "/app/main.py"]