# Hermes — MCP Home Assistant Add-on
#
# La imagen base va aquí, con valor por defecto, y no en build.yaml: el flujo de
# compilación nuevo de Home Assistant (BuildKit, actions de home-assistant/
# builder) no lee build.yaml, y el Supervisor solo lo lee ya por compatibilidad
# y avisando de que está deprecado. Sin build.yaml, el Supervisor no pasa
# BUILD_FROM, así que sin este valor por defecto la compilación local fallaría.
#
# Es una imagen multi-arquitectura: el mismo nombre sirve en amd64 y en aarch64.
# Python 3.13 sobre Alpine 3.24 (la Alpine por defecto de las bases de HA). La
# etiqueta sin fecha recibe los parches de esa combinación; las fechadas
# (`…-2026.10.3`) existen si alguna vez hace falta congelarla.
ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.13-alpine3.24
FROM ${BUILD_FROM}

# Los pasa la action build-image (y el Supervisor al compilar en local). Solo
# alimentan labels: compilar sin ellos funciona.
ARG BUILD_ARCH
ARG BUILD_VERSION
# "app" es el valor vigente; "addon" queda como legado y el Supervisor acepta
# los dos. Nombre, descripción y URL se ponen desde el manifiesto en el
# workflow de publicación, para no duplicarlos aquí.
LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
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
