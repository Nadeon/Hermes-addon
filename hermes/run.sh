#!/bin/sh
# Hermes – MCP Home Assistant Add-on
# Script de arranque: lee options.json con jq, exporta env vars, lanza Python.
#
# No usamos bashio::config porque depende de la API del Supervisor y
# su acceso varía según hassio_role / versión de HA. Leer directamente
# /data/options.json (escrito por el Supervisor al arrancar el contenedor)
# es más fiable y no requiere permisos API.

set -e

OPTIONS="/data/options.json"

# ── Verificar que el fichero de opciones existe ───────────────
if [ ! -f "$OPTIONS" ]; then
    echo "[FATAL] No se encontró $OPTIONS. ¿El add-on se instaló correctamente?" >&2
    exit 1
fi

# Helper: leer un valor del JSON (devuelve "" si la clave no existe o es null)
cfg() {
    jq -r ".$1 // empty" "$OPTIONS"
}

# Helper con default
cfg_default() {
    val=$(jq -r ".$1 // empty" "$OPTIONS")
    echo "${val:-$2}"
}

# ── Opciones obligatorias ─────────────────────────────────────
export HERMES_AUTH_PASSWORD="$(cfg auth_password)"
export HERMES_PUBLIC_HOSTNAME="$(cfg public_hostname)"

# Validación temprana: sin password o hostname, no arrancamos.
if [ -z "${HERMES_AUTH_PASSWORD}" ]; then
    echo "[FATAL] auth_password no está configurado en las opciones del add-on." >&2
    echo "[FATAL] Configúralo en Ajustes → Add-ons → Hermes → Configuración." >&2
    exit 1
fi

if [ -z "${HERMES_PUBLIC_HOSTNAME}" ]; then
    echo "[FATAL] public_hostname no está configurado en las opciones del add-on." >&2
    echo "[FATAL] Debe ser el hostname de Funnel (ej. hermes.tail-xxxx.ts.net), sin esquema ni path." >&2
    exit 1
fi

# ── Opciones con defaults ─────────────────────────────────────
export HERMES_NETWORK_MODE="$(cfg_default network_mode tailscale)"
export HERMES_MCP_BIND="$(cfg_default mcp_bind 127.0.0.1)"
export HERMES_LOG_LEVEL="$(cfg_default log_level info)"
export HERMES_MCP_MAX_RPM="$(cfg_default mcp_max_requests_per_minute 120)"
export HERMES_PREAUTH_MAX_RPM_PER_IP="$(cfg_default mcp_preauth_max_requests_per_minute_per_ip 20)"
export HERMES_SAFETY_BACKUP_ENABLED="$(cfg_default safety_backup_enabled false)"
export HERMES_SAFETY_BACKUP_WINDOW="$(cfg_default safety_backup_window_minutes 30)"
export HERMES_FILE_BACKUP_MAX_PER_PATH="$(cfg_default file_backup_max_per_path 20)"
export HERMES_FILE_BACKUP_MAX_TOTAL_MB="$(cfg_default file_backup_max_total_mb 200)"
export HERMES_CONFIG_WRITE_MIN_INTERVAL="$(cfg_default config_write_min_interval_seconds 5)"
export HERMES_CONFIG_WRITE_MAX_PER_MINUTE="$(cfg_default config_write_max_per_minute 10)"
export HERMES_RESPONSE_MAX_BYTES="$(cfg_default response_max_bytes 1048576)"
export HERMES_WS_MAX_MSG_SIZE="$(cfg_default ha_ws_max_msg_size_bytes 4194304)"
export HERMES_MAX_REQUEST_BODY_BYTES="$(cfg_default max_request_body_bytes 4194304)"
export HERMES_MAX_CONCURRENT_REQUESTS="$(cfg_default max_concurrent_requests 64)"
export HERMES_WAIT_EVENT_MAX_SECONDS="$(cfg_default wait_for_event_max_seconds 90)"
export HERMES_WAIT_EVENT_MAX_CONCURRENT="$(cfg_default wait_for_event_max_concurrent 5)"
export HERMES_HEALTH_STARTUP_GRACE="$(cfg_default health_startup_grace_seconds 120)"
export HERMES_HEALTH_RECONNECT_TOLERANCE="$(cfg_default health_reconnect_tolerance_seconds 300)"

# ── Opciones de listas (JSON arrays) ──────────────────────────
export HERMES_CALL_SERVICE_DENYLIST_EXTRA="$(jq -c '.call_service_denylist_extra // []' "$OPTIONS")"
export HERMES_CALL_SERVICE_RESTRICTED_ENTITIES="$(jq -c '.call_service_restricted_entities // []' "$OPTIONS")"
export HERMES_CALL_SERVICE_AUTO_CLASSIFY="$(cfg_default call_service_auto_classify_dangerous true)"
export HERMES_FIRE_EVENT_ALLOWLIST="$(jq -c '.fire_event_allowlist // []' "$OPTIONS")"

# ── Token del Supervisor (inyectado por HAOS) ─────────────────
# SUPERVISOR_TOKEN ya está en el entorno del contenedor del add-on.

# ── Debug (solo con HERMES_DEV=1) ─────────────────────────────
# Si HERMES_DEV=1, debugpy escucha en 127.0.0.1 (nunca 0.0.0.0).

# ── Lanzar Python ─────────────────────────────────────────────
# s6-overlay no propaga Docker ENV a los servicios — forzar aquí.
export PYTHONPATH=/app/src
# s6-overlay v3 guarda las Docker env vars en /run/s6/container_environment/.
# SUPERVISOR_TOKEN es inyectado por el Supervisor como Docker env var pero
# s6 no lo propaga a legacy-services automáticamente.
S6_ENV="/run/s6/container_environment"
if [ -z "${SUPERVISOR_TOKEN:-}" ] && [ -f "${S6_ENV}/SUPERVISOR_TOKEN" ]; then
    export SUPERVISOR_TOKEN="$(cat "${S6_ENV}/SUPERVISOR_TOKEN")"
fi
# Compatibilidad: algunas instalaciones inyectan HASSIO_TOKEN en vez de SUPERVISOR_TOKEN
if [ -z "${SUPERVISOR_TOKEN:-}" ] && [ -n "${HASSIO_TOKEN:-}" ]; then
    export SUPERVISOR_TOKEN="${HASSIO_TOKEN}"
fi
if [ -z "${SUPERVISOR_TOKEN:-}" ] && [ -f "${S6_ENV}/HASSIO_TOKEN" ]; then
    export SUPERVISOR_TOKEN="$(cat "${S6_ENV}/HASSIO_TOKEN")"
fi

echo "[INFO] Arrancando Hermes MCP..."
exec python3 -m hermes
