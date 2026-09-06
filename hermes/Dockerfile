# Hermes — MCP Home Assistant Add-on
# Patrón estándar de add-ons de HA: ARG BUILD_FROM → FROM $BUILD_FROM

ARG BUILD_FROM
FROM $BUILD_FROM

ARG BUILD_ARCH
ARG BUILD_VERSION
LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="addon" \
      io.hass.arch="${BUILD_ARCH}"

# ── Layer caching: dependencias primero, código después ───────
# Rebuilds tras cambios en .py reutilizan la capa de pip install cacheada.
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# ── Código fuente ─────────────────────────────────────────────
# Solo entra lo que el add-on necesita para arrancar: ni tests ni
# documentación viajan en la imagen.
COPY src/ /app/src/
COPY run.sh /app/run.sh
RUN chmod a+x /app/run.sh

ENV PYTHONPATH=/app/src
WORKDIR /app
CMD ["/app/run.sh"]
