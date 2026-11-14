"""Hermes — Carga de configuración desde variables de entorno.

run.sh lee options.json con bashio y exporta env vars.
Este módulo las recoge y las expone como un objeto tipado.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
from dataclasses import dataclass, field

from .password_policy import (
    MIN_AUTH_PASSWORD_LENGTH as _MIN_AUTH_PASSWORD_LENGTH,
    motivo_debil,
)


# ── Constantes del proyecto ───────────────────────────────────
# Bump HA_CORE_MIN_SUPPORTED solo cuando se use un endpoint que no
# existía antes.
# Topologías de red admitidas (ver `network_mode`).
NETWORK_MODES = frozenset({"tailscale", "reverse_proxy"})

# 2024.10: Hermes guarda las automatizaciones con las claves en plural
# (`triggers`, `conditions`, `actions`), que HA solo entiende desde esa
# versión. Con la 2024.1 declarada antes, una HA 2024.1–2024.9 arrancaba sin
# aviso y luego no podía guardar ninguna automatización.
HA_CORE_MIN_SUPPORTED = "2024.10.0"

# Última versión de Home Assistant contra la que se comprobó Hermes de
# verdad, con el conector real y no solo con la suite. Con una más nueva, el
# arranque avisa con `ha_core_version_untested`.
#
# Va en pareja con la versión de Hermes en la que se revisó. La regla de
# subirla "en cada release" estaba solo en un comentario, y la 1.0.10 salió
# sin tocarla: todas las instalaciones al día avisaban en cada arranque de
# una versión "no probada" que sí funcionaba. Un test exige ahora que la
# pareja coincida con la versión de Hermes, así que cada release obliga a
# decidir: o se comprueba contra la HA actual y se sube, o se deja a
# sabiendas y solo se actualiza la pareja.
HA_CORE_LAST_TESTED = "2026.11.1"
HA_CORE_LAST_TESTED_IN_HERMES = "1.1.2"

MCP_PORT = 8765
HEALTH_PORT = 8766

# Calidad de auth_password. Es el único secreto que protege el acceso a Home
# Assistant desde internet, así que se exige al arranque (fail-closed). Las
# reglas y su porqué están en password_policy; se reexporta la longitud mínima
# porque es el número que sale en la documentación y en el schema del add-on.
MIN_AUTH_PASSWORD_LENGTH = _MIN_AUTH_PASSWORD_LENGTH

# Límites de tamaño y de espera (FR-032…FR-035). Con 1 MB por respuesta, quien
# recortaba era el cliente, por su cuenta y sin avisar; el truncado de Hermes
# es controlado y lo dice. Y claude.ai corta las llamadas a los 240 s, así que
# una espera más larga pierde el resultado sin que nadie se entere.
#
# Los máximos se aplican al CARGAR y no en el esquema de config.yaml porque el
# Supervisor valida las opciones guardadas al arrancar: estrechar el rango
# dejaría sin arrancar a quien ya tenga guardado un valor mayor (spec S-03).
RESPONSE_MAX_BYTES_DEFAULT = 131_072
RESPONSE_MAX_BYTES_CAP = 524_288
# El valor por defecto anterior. La interfaz del Supervisor guarda TODAS las
# opciones al pulsar «Guardar», así que 1 048 576 está en las opciones de casi
# todo el mundo sin que nadie lo eligiera: se trata como «no personalizado».
RESPONSE_MAX_BYTES_LEGACY_DEFAULT = 1_048_576
# Tope del mensaje WebSocket con HA. Con 4 MiB, un único resultado grande
# (el catálogo del Marketplace, un registro de entidades de miles, un
# historial amplio) cerraba la conexión entera y fallaban TODAS las llamadas en
# curso. El Supervisor reenvía desde Core hasta 64 MiB y su ingress admite
# 16 MiB, así que el único tope efectivo era el de Hermes (revisión de 1.1.1,
# M-3). 16 MiB es el máximo que ya admite el esquema; el coste es un pico de
# memoria transitorio solo cuando llega un mensaje así. Los 4 MiB guardados se
# tratan como «no personalizado», por el mismo motivo que `response_max_bytes`.
WS_MAX_MSG_SIZE_DEFAULT = 16_777_216
WS_MAX_MSG_SIZE_LEGACY_DEFAULT = 4_194_304
WAIT_FOR_EVENT_MAX_SECONDS_CAP = 220


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


def _env_host_list(key: str) -> list[str]:
    """Lista JSON de hosts; si no se puede leer, devuelve el texto tal cual.

    A diferencia de `_env_list`, un valor ilegible NO se convierte en lista
    vacía: en `oauth_cimd_allowed_hosts` vacía significa «cualquier host», y
    un error de formato abriría en vez de cerrar. El texto crudo no pasa la
    validación y Hermes no arranca.
    """
    raw = os.environ.get(key, "")
    if not raw or raw == "null":
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return [raw]
    if not isinstance(parsed, list):
        return [raw]
    return [str(item) for item in parsed if item]


def _es_ip_o_red(valor: str) -> bool:
    """True si `valor` es una IP suelta o una red en CIDR.

    `strict=False` a propósito: "172.30.32.1/23" tiene bits de host puestos y
    `ip_network` lo rechazaría en modo estricto, pero es justo lo que escribe
    quien copia la IP del gateway y le añade la máscara. Interpretarlo como la
    red que lo contiene es lo que hace el propio uvicorn.
    """
    texto = valor.strip()
    if not texto:
        return False
    try:
        if "/" in texto:
            ipaddress.ip_network(texto, strict=False)
        else:
            ipaddress.ip_address(texto)
    except ValueError:
        return False
    return True


def _sugerencia_hostname(valor: str) -> str:
    """Propone el valor corregido, si limpiarlo da algo válido.

    El error más común es pegar la URL del conector MCP entera —esquema
    delante, `/mcp` detrás— porque es la cadena que el usuario acaba de copiar
    en Claude. Decirle "sin esquema ni path" es correcto pero le deja el
    trabajo de deducir cuál era; enseñarle el valor exacto no.

    El hostname no es un secreto: ya sale en la línea `config_loaded` del log.
    """
    limpio = valor.strip()
    for esquema in ("https://", "http://"):
        if limpio.lower().startswith(esquema):
            limpio = limpio[len(esquema):]
    limpio = limpio.split("/")[0].split("?")[0].split("#")[0].rstrip(".")
    if limpio and limpio != valor and _HOSTNAME_RE.match(limpio):
        return f" Con lo que has puesto, seguramente querías: {limpio!r}."
    return ""


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

    # Proxies cuyo X-Forwarded-For se cree. uvicorn solo hace caso a esa
    # cabecera si la conexión viene de una IP de confianza, y de fábrica esa
    # lista es solo 127.0.0.1: en `reverse_proxy` con `mcp_bind` en la red
    # puente, todas las peticiones llegan con la IP del proxy y los tres
    # límites por IP (pre-auth, fallos de auth y freno del login) colapsan en
    # un único cubo global. Vacía por defecto porque confiar de más es peor
    # que no confiar: quien esté dentro del rango puede falsificar la IP del
    # cliente. El daño está acotado a los límites y a los logs — la IP no
    # autoriza nada.
    trusted_proxy_ips: list[str] = field(default_factory=list)

    # ── Backups ───────────────────────────────────────────────
    # safety_backup_enabled: backup FULL de HAOS (varios GB) automático antes
    # de escribir en /config. DESACTIVADO por defecto — inviable en producción.
    # El backup por-fichero (ligero) se hace siempre, independiente de esto.
    safety_backup_enabled: bool = False
    safety_backup_window_minutes: int = 30
    file_backup_max_per_path: int = 20
    file_backup_max_total_mb: int = 200
    # Cuántos safety backups automáticos conserva la retención (0 la apaga).
    # Solo actúa con safety_backup_enabled: cada uno pesa varios GB y, sin
    # poda, llenaban el disco de quien activaba la opción.
    safety_backup_keep: int = 3

    # ── Escritura en /config ──────────────────────────────────
    config_write_min_interval_seconds: int = 5
    config_write_max_per_minute: int = 10

    # ── Respuestas ────────────────────────────────────────────
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT  # 128 KiB

    # ── WebSocket HA ──────────────────────────────────────────
    ha_ws_max_msg_size_bytes: int = WS_MAX_MSG_SIZE_DEFAULT  # 16 MiB

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

    # ── OAuth ─────────────────────────────────────────────────
    # Interruptor de los clientes CIMD (`client_id` con URL https://). Existe
    # para poder volver solo a DCR si CIMD rompe a un cliente real (FR-023).
    oauth_cimd_enabled: bool = True
    # Hosts cuyos documentos CIMD se aceptan. Vacía = cualquier host público.
    # Cada descarga sale de la IP de casa hacia el host del `client_id`, que
    # elige quien abre /oauth/authorize sin contraseña: con la lista, Hermes
    # solo contacta con los hosts que el dueño ha decidido (revisión 1.1.0,
    # MEDIO-1).
    oauth_cimd_allowed_hosts: list[str] = field(default_factory=list)

    # ── Log ───────────────────────────────────────────────────
    # Seudonimiza IPs y hostnames en el log, que la gente pega en foros al
    # pedir ayuda (FR-044). Se puede desactivar para diagnosticar la red.
    log_redact_network: bool = True

    # ── Runtime (no configurables por usuario) ────────────────
    supervisor_token: str = ""

    # Ajustes que `load_config` aplicó a valores guardados, como
    # `{option, configured, applied, reason}`. No se registran al cargar porque
    # el log aún no está configurado; los registra el arranque después.
    adjustments: list[dict[str, object]] = field(default_factory=list)

    def validate(self) -> None:
        """Validación de campos obligatorios. Llamar al arranque."""
        if not self.auth_password:
            raise ValueError(
                "auth_password no está configurado. "
                "Configúralo en Ajustes → Add-ons → Hermes → Configuración."
            )
        # El motivo describe la REGLA que falla, nunca el valor: este mensaje
        # acaba en el log del add-on, que se ve desde la interfaz de Home
        # Assistant y que la gente pega en los foros al pedir ayuda.
        motivo = motivo_debil(
            self.auth_password, public_hostname=self.public_hostname
        )
        if motivo is not None:
            raise ValueError(
                f"auth_password no es lo bastante fuerte: {motivo}. Es el "
                "único secreto que protege el acceso a Home Assistant desde "
                "internet, así que Hermes no arranca con una que se pueda "
                "adivinar. Genera una con el gestor de contraseñas que uses, o "
                "en un terminal con:  openssl rand -base64 18"
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
                + _sugerencia_hostname(self.public_hostname)
            )
        if self.network_mode not in NETWORK_MODES:
            raise ValueError(
                f"network_mode inválido: {self.network_mode!r}. "
                f"Valores admitidos: {', '.join(sorted(NETWORK_MODES))}."
            )
        if not self.mcp_bind:
            raise ValueError("mcp_bind no puede estar vacío.")
        # Se valida aquí y no en uvicorn porque uvicorn NO avisa: lo que no
        # parsea como IP o como red lo guarda como "literal" y simplemente no
        # casa nunca con nadie. Un typo ("172.30.32.0/32.1", "172.30.32,1")
        # dejaría los límites por IP colapsados exactamente igual que sin la
        # opción, sin una sola línea en el log.
        for entrada in self.trusted_proxy_ips:
            if not _es_ip_o_red(entrada):
                raise ValueError(
                    f"trusted_proxy_ips contiene un valor que no es una IP ni "
                    f"una red: {entrada!r}. Escribe una IP suelta "
                    f"(ej. 172.30.32.2) o un rango en notación CIDR "
                    f"(ej. 172.30.32.0/23, la red puente de HAOS)."
                )
        # El esquema del add-on ya la limita a 0–50, pero la variable se
        # puede poner a mano: un negativo dejaría la retención sin sentido y
        # uno enorme equivale a no podar nunca sin decirlo.
        if not 0 <= self.safety_backup_keep <= 50:
            raise ValueError(
                f"safety_backup_keep fuera de rango: {self.safety_backup_keep}. "
                "Debe estar entre 0 (sin retención) y 50."
            )
        # Un host mal escrito no se descarta en silencio: si la lista
        # quedara vacía, Hermes aceptaría cualquier host (fail-closed).
        from hermes.cimd import normalize_allowed_hosts

        try:
            normalize_allowed_hosts(self.oauth_cimd_allowed_hosts)
        except ValueError as exc:
            raise ValueError(
                f"{exc}. Escribe solo nombres DNS, sin esquema, puerto ni "
                "path (ej. claude.ai). Una IP no vale: un cliente CIMD nunca "
                "se identifica con una IP."
            ) from exc
        if not self.supervisor_token:
            raise ValueError(
                "SUPERVISOR_TOKEN no está disponible en el entorno. "
                "¿El add-on se está ejecutando dentro de HAOS?"
            )


def _ajustar(
    opcion: str,
    configurado: int,
    aplicado: int,
    motivo: str,
    ajustes: list[dict[str, object]],
) -> int:
    ajustes.append({
        "option": opcion,
        "configured": configurado,
        "applied": aplicado,
        "reason": motivo,
    })
    return aplicado


def load_config() -> HermesConfig:
    """Carga la configuración desde variables de entorno."""
    ajustes: list[dict[str, object]] = []

    response_max_bytes = _env_int(
        "HERMES_RESPONSE_MAX_BYTES", RESPONSE_MAX_BYTES_DEFAULT
    )
    if response_max_bytes == RESPONSE_MAX_BYTES_LEGACY_DEFAULT:
        response_max_bytes = _ajustar(
            "response_max_bytes", response_max_bytes,
            RESPONSE_MAX_BYTES_DEFAULT, "legacy_default", ajustes,
        )
    elif response_max_bytes > RESPONSE_MAX_BYTES_CAP:
        response_max_bytes = _ajustar(
            "response_max_bytes", response_max_bytes,
            RESPONSE_MAX_BYTES_CAP, "above_cap", ajustes,
        )

    ha_ws_max_msg_size_bytes = _env_int(
        "HERMES_WS_MAX_MSG_SIZE", WS_MAX_MSG_SIZE_DEFAULT
    )
    if ha_ws_max_msg_size_bytes == WS_MAX_MSG_SIZE_LEGACY_DEFAULT:
        ha_ws_max_msg_size_bytes = _ajustar(
            "ha_ws_max_msg_size_bytes", ha_ws_max_msg_size_bytes,
            WS_MAX_MSG_SIZE_DEFAULT, "legacy_default", ajustes,
        )

    wait_for_event_max_seconds = _env_int("HERMES_WAIT_EVENT_MAX_SECONDS", 90)
    if wait_for_event_max_seconds > WAIT_FOR_EVENT_MAX_SECONDS_CAP:
        wait_for_event_max_seconds = _ajustar(
            "wait_for_event_max_seconds", wait_for_event_max_seconds,
            WAIT_FOR_EVENT_MAX_SECONDS_CAP, "above_cap", ajustes,
        )

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
        trusted_proxy_ips=_env_list("HERMES_TRUSTED_PROXY_IPS"),
        safety_backup_enabled=_env_bool("HERMES_SAFETY_BACKUP_ENABLED", False),
        safety_backup_window_minutes=_env_int("HERMES_SAFETY_BACKUP_WINDOW", 30),
        file_backup_max_per_path=_env_int("HERMES_FILE_BACKUP_MAX_PER_PATH", 20),
        file_backup_max_total_mb=_env_int("HERMES_FILE_BACKUP_MAX_TOTAL_MB", 200),
        safety_backup_keep=_env_int("HERMES_SAFETY_BACKUP_KEEP", 3),
        config_write_min_interval_seconds=_env_int(
            "HERMES_CONFIG_WRITE_MIN_INTERVAL", 5
        ),
        config_write_max_per_minute=_env_int("HERMES_CONFIG_WRITE_MAX_PER_MINUTE", 10),
        response_max_bytes=response_max_bytes,
        ha_ws_max_msg_size_bytes=ha_ws_max_msg_size_bytes,
        wait_for_event_max_seconds=wait_for_event_max_seconds,
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
        oauth_cimd_enabled=_env_bool("HERMES_OAUTH_CIMD_ENABLED", True),
        oauth_cimd_allowed_hosts=_env_host_list("HERMES_OAUTH_CIMD_ALLOWED_HOSTS"),
        log_redact_network=_env_bool("HERMES_LOG_REDACT_NETWORK", True),
        supervisor_token=_env_str("SUPERVISOR_TOKEN"),
        adjustments=ajustes,
    )
