FROM ghcr.io/immortalserg/finworkspace:1.6.2

LABEL io.hass.type="app" \
      io.hass.version="1.1.7" \
      io.hass.arch="amd64|aarch64" \
      org.opencontainers.image.source="https://github.com/immortalserg/ha-apps"

COPY run.py /app/ha-run.py
CMD ["python", "/app/ha-run.py"]
