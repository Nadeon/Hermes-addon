"""Hermes — Carga de configuración desde variables de entorno.

run.sh lee options.json con bashio y exporta env vars.
Este módulo las recoge y las expone como un objeto tipado.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field


# ── Constantes del proyecto ───────────────────────────────────
# Bump HA_CORE_MIN_SUPPORTED solo cuando se use un endpoint que no
# existía antes. Bump HA_CORE_LAST_TESTED en cada release que pase CI.
# Topologías de red admitidas (ver `network_mode`).
NETWORK_MODES = frozenset({"tailscale", "reverse_proxy"})

HA_CORE_MIN_SUPPORTED = "2024.1.0"
HA_CORE_LAST_TESTED = "2026.9.0"

MCP_PORT = 8765
HEALTH_PORT = 8766

# Longitud mínima de auth_password. Es el único secreto que protege el acceso
# a Home Assistant desde internet, así que se exige al arranque (fail-closed).
MIN_AUTH_PASSWORD_LENGTH = 12


def _env_str(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.lower() in ("true", "1", "yes")


def _env_list(key: str) -> list[str]:
    """Parse a JSON array from env var, returning empty list on failure."""
    raw = os.environ.get(key, "")
    if not raw or raw == "null":
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item]
        return []
    except (json.JSONDecodeError, TypeError):
        return []


# Hostname público: etiquetas DNS separadas por puntos, con puerto opcional.
# Sin esquema, sin barras, sin credenciales, sin path.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*(:[0-9]{1,5})?$"
)


@dataclass(frozen=True)
class HermesConfig:
    """Configuración inmutable del add-on, leída una vez al arranque."""

    # ── Obligatorias ──────────────────────────────────────────
    auth_password: str = ""
    public_hostname: str = ""

    # ── Logging ───────────────────────────────────────────────
    log_level: str = "info"

    # ── Rate limits ───────────────────────────────────────────
    mcp_max_requests_per_minute: int = 120
    mcp_preauth_max_requests_per_minute_per_ip: int = 20

    # Tamaño máximo del CUERPO de una petición HTTP entrante. Coincide en valor
    # con `ha_ws_max_msg_size_bytes`, pero no es lo mismo y por eso son dos
    # opciones: aquella capa el mensaje WebSocket que Hermes intercambia con HA,
    # que es tráfico de salida y ni siquiera pasa por este stack.
    max_request_body_bytes: int = 4_194_304

    # Peticiones simultáneas que uvicorn acepta a la vez. Sin tope, cada
    # conexión en vuelo puede retener hasta `max_request_body_bytes` en memoria.
    # 64 deja holgura de sobra: el cliente MCP lanza ráfagas de ~24 llamadas.
    max_concurrent_requests: int = 64

    # ── Topología de red ──────────────────────────────────────
    # tailscale     : el add-on de Tailscale publica el Funnel y Hermes
    #                 espera a que exista la interfaz antes de arrancar.
    # reverse_proxy : cualquier otro proxy inverso (Cloudflare Tunnel,
    #                 Nginx Proxy Manager, Caddy…) termina el TLS y hace
    #                 proxy a mcp_bind:8765. No se espera a Tailscale.
    network_mode: str = "tailscale"
    mcp_bind: str = "127.0.0.1"

    # ── Backups ───────────────────────────────────────────────
    # safety_backup_enabled: backup FULL de HAOS (varios GB) automático antes
    # de escribir en /config. DESACTIVADO por defecto — inviable en producción.
    # El backup por-fichero (ligero) se hace siempre, independiente de esto.
    safety_backup_enabled: bool = False
    safety_backup_window_minutes: int = 30
    file_backup_max_per_path: int = 20
    file_backup_max_total_mb: int = 200

    # ── Escritura en /config ──────────────────────────────────
    config_write_min_interval_seconds: int = 5
    config_write_max_per_minute: int = 10

    # ── Respuestas ────────────────────────────────────────────
    response_max_bytes: int = 1_048_576  # 1 MB

    # ── WebSocket HA ──────────────────────────────────────────
    ha_ws_max_msg_size_bytes: int = 4_194_304  # 4 MB

    # ── wait_for_event ────────────────────────────────────────
    wait_for_event_max_seconds: int = 90
    wait_for_event_max_concurrent: int = 5

    # ── Health ────────────────────────────────────────────────
    health_startup_grace_seconds: int = 120
    health_reconnect_tolerance_seconds: int = 300

    # ── Seguridad ─────────────────────────────────────────────
    call_service_denylist_extra: list[str] = field(default_factory=list)
    call_service_restricted_entities: list[str] = field(default_factory=list)
    call_service_auto_classify_dangerous: bool = True
    fire_event_allowlist: list[str] = field(default_factory=list)

    # ── Runtime (no configurables por usuario) ────────────────
    supervisor_token: str = ""

    def validate(self) -> None:
        """Validación de campos obligatorios. Llamar al arranque."""
        if not self.auth_password:
            raise ValueError(
                "auth_password no está configurado. "
                "Configúralo en Ajustes → Add-ons → Hermes → Configuración."
            )
        if len(self.auth_password) < MIN_AUTH_PASSWORD_LENGTH:
            raise ValueError(
                f"auth_password es demasiado corta "
                f"({len(self.auth_password)} caracteres). Debe tener al menos "
                f"{MIN_AUTH_PASSWORD_LENGTH} caracteres y ser aleatoria. Es el "
                "único secreto que protege el acceso a Home Assistant desde "
                "internet: genera una larga y aleatoria (p. ej. con un gestor "
                "de contraseñas)."
            )
        if not self.public_hostname:
            raise ValueError(
                "public_hostname no está configurado. Es el hostname público "
                "por el que se llega a Hermes, sin esquema ni path: el de "
                "Tailscale Funnel (ej. hermes.tail-xxxx.ts.net) o el dominio "
                "que sirva tu proxy inverso (ej. hermes.midominio.com)."
            )
        # Se valida la FORMA, no solo que no esté vacío: el hostname acaba
        # dentro de las URLs de descubrimiento OAuth que se sirven al cliente,
        # así que un `https://` delante o un path detrás producen URLs
        # malformadas y el fallo aparece mucho más tarde, como un flujo OAuth
        # roto y sin explicación. Mejor negarse al arrancar.
        if not _HOSTNAME_RE.match(self.public_hostname):
            raise ValueError(
                f"public_hostname inválido: {self.public_hostname!r}. Debe ser "
                "solo el hostname, sin esquema ni path ni barras "
                "(ej. hermes.tail-xxxx.ts.net), opcionalmente con :puerto."
            )
        if self.network_mode not in NETWORK_MODES:
            raise ValueError(
                f"network_mode inválido: {self.network_mode!r}. "
                f"Valores admitidos: {', '.join(sorted(NETWORK_MODES))}."
            )
        if not self.mcp_bind:
            raise ValueError("mcp_bind no puede estar vacío.")
        if not self.supervisor_token:
            raise ValueError(
                "SUPERVISOR_TOKEN no está disponible en el entorno. "
                "¿El add-on se está ejecutando dentro de HAOS?"
            )


def load_config() -> HermesConfig:
    """Carga la configuración desde variables de entorno."""
    return HermesConfig(
        auth_password=_env_str("HERMES_AUTH_PASSWORD"),
        public_hostname=_env_str("HERMES_PUBLIC_HOSTNAME"),
        log_level=_env_str("HERMES_LOG_LEVEL", "info"),
        mcp_max_requests_per_minute=_env_int("HERMES_MCP_MAX_RPM", 120),
        mcp_preauth_max_requests_per_minute_per_ip=_env_int(
            "HERMES_PREAUTH_MAX_RPM_PER_IP", 20
        ),
        max_request_body_bytes=_env_int("HERMES_MAX_REQUEST_BODY_BYTES", 4_194_304),
        max_concurrent_requests=_env_int("HERMES_MAX_CONCURRENT_REQUESTS", 64),
        network_mode=os.environ.get("HERMES_NETWORK_MODE", "tailscale").strip()
        or "tailscale",
        mcp_bind=os.environ.get("HERMES_MCP_BIND", "127.0.0.1").strip()
        or "127.0.0.1",
        safety_backup_enabled=_env_bool("HERMES_SAFETY_BACKUP_ENABLED", False),
        safety_backup_window_minutes=_env_int("HERMES_SAFETY_BACKUP_WINDOW", 30),
        file_backup_max_per_path=_env_int("HERMES_FILE_BACKUP_MAX_PER_PATH", 20),
        file_backup_max_total_mb=_env_int("HERMES_FILE_BACKUP_MAX_TOTAL_MB", 200),
        config_write_min_interval_seconds=_env_int(
            "HERMES_CONFIG_WRITE_MIN_INTERVAL", 5
        ),
        config_write_max_per_minute=_env_int("HERMES_CONFIG_WRITE_MAX_PER_MINUTE", 10),
        response_max_bytes=_env_int("HERMES_RESPONSE_MAX_BYTES", 1_048_576),
        ha_ws_max_msg_size_bytes=_env_int("HERMES_WS_MAX_MSG_SIZE", 4_194_304),
        wait_for_event_max_seconds=_env_int("HERMES_WAIT_EVENT_MAX_SECONDS", 90),
        wait_for_event_max_concurrent=_env_int("HERMES_WAIT_EVENT_MAX_CONCURRENT", 5),
        health_startup_grace_seconds=_env_int("HERMES_HEALTH_STARTUP_GRACE", 120),
        health_reconnect_tolerance_seconds=_env_int(
            "HERMES_HEALTH_RECONNECT_TOLERANCE", 300
        ),
        call_service_denylist_extra=_env_list("HERMES_CALL_SERVICE_DENYLIST_EXTRA"),
        call_service_restricted_entities=_env_list(
            "HERMES_CALL_SERVICE_RESTRICTED_ENTITIES"
        ),
        call_service_auto_classify_dangerous=_env_bool(
            "HERMES_CALL_SERVICE_AUTO_CLASSIFY", True
        ),
        fire_event_allowlist=_env_list("HERMES_FIRE_EVENT_ALLOWLIST"),
        supervisor_token=_env_str("SUPERVISOR_TOKEN"),
    )
