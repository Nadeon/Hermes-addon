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

# Margen que da s6-overlay entre el SIGTERM y el SIGKILL al parar el add-on.
# El valor por defecto son 3000 ms, y el apagado ordenado de Hermes necesita
# más: uvicorn cierra las conexiones MCP en vuelo (timeout_graceful_shutdown=3),
# __main__ espera a esa task y después borra los ficheros temporales. Con 3 s
# s6 mataba el proceso a mitad y los .tmp se quedaban en /data.
ENV S6_KILL_GRACETIME=10000

ENV PYTHONPATH=/app/src
WORKDIR /app
CMD ["/app/run.sh"]
