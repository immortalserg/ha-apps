FROM libretranslate/libretranslate:latest
LABEL io.hass.type="app" io.hass.version="1.0.0" io.hass.arch="amd64|aarch64"
USER root
COPY start.py /app/ha-start.py
ENTRYPOINT ["/app/venv/bin/python", "/app/ha-start.py"]
CMD []
