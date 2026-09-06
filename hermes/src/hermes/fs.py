"""Hermes — Módulo de seguridad para acceso al filesystem /config.

Toda la lógica de seguridad para lectura de /config está aquí. Las tools
de filesystem.py llaman a este módulo; nunca abren ficheros directamente.

Capas de seguridad:
1. URL-decode + Unicode NFC antes de cualquier operación de path.
2. Anti-traversal: Path.resolve() + verificación is_relative_to().
3. Blacklist por nombre exacto y por patrón glob.
4. Allowlist restrictiva para .storage/ (default-deny).
5. Blacklist de directorios sensibles (.cloud, .cache).
6. O_NOFOLLOW como defensa en profundidad contra symlinks (solo protege
   el último componente del path — la defensa real es el resolve() previo).
7. Detección de binarios: rechaza el contenido que traiga un byte nulo (0x00).
   `is_binary()` examina todo el buffer que reciba; cuánto leer lo decide quien
   llama.
8. Detección de encoding: UTF-8 BOM, UTF-8, latin-1 fallback.

CONFIG_BASE es mutable para facilitar tests con monkeypatch.
"""

from __future__ import annotations

import fnmatch
import os
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import structlog

logger = structlog.get_logger(__name__)

# ── Raíz del filesystem de configuración de HA ───────────────────────────────
# Mutable para que los tests puedan hacer monkeypatch.
# En HAOS el add-on monta homeassistant_config en /homeassistant (no /config).
# HERMES_CONFIG_BASE permite sobreescribir para desarrollo y tests externos.
_CONFIG_BASE_DEFAULT = os.environ.get("HERMES_CONFIG_BASE", "/homeassistant")
CONFIG_BASE: Path = Path(_CONFIG_BASE_DEFAULT).resolve()

# ── Excepciones ───────────────────────────────────────────────────────────────

class PathTraversalError(ValueError):
    """El path escapa de CONFIG_BASE."""


class BlacklistedPathError(PermissionError):
    """El path está en la blacklist de seguridad."""


# ── Blacklist: nombres relativos exactos ─────────────────────────────────────
# Rutas relativas a CONFIG_BASE, con forward-slash, sin barra inicial.

# NOTA: para los ficheros de credenciales que pueden existir en cualquier
# subdirectorio, la protección real está en BLACKLIST_BASENAMES (más abajo).
# Home Assistant resuelve `!secret` buscando el secrets.yaml más cercano hacia
# arriba, así que `esphome/secrets.yaml` es un fichero de credenciales tan real
# como el de la raíz, y una comparación por ruta exacta no lo alcanzaría.
BLACKLIST_NAMES: frozenset[str] = frozenset({
    # Credenciales directas de HA
    "secrets.yaml",
    "known_devices.yaml",
    "ip_bans.yaml",
    # .storage/: tokens de auth y sesiones
    ".storage/auth",
    ".storage/auth_provider.homeassistant",
    ".storage/onboarding",
    ".storage/http",
    ".storage/http.auth",
    ".storage/core.config_entries",   # tokens OAuth de todas las integraciones
    ".storage/core.uuid",             # identificador único, privacidad
    ".storage/cloud",                 # credenciales de Nabu Casa cloud
    ".storage/hassio",                # info de Supervisor
    # repairs puede contener info de auth de integraciones
    ".storage/repairs.issue_registry",
})

# ── Blacklist: nombres de fichero, en cualquier subdirectorio ────────────────
# Se comparan contra `path.name`, así que protegen el fichero esté donde esté.
BLACKLIST_BASENAMES: frozenset[str] = frozenset({
    "secrets.yaml",
    "secrets.yml",
    "known_devices.yaml",
    "ip_bans.yaml",
})

# ── Blacklist: patrones glob contra el nombre del fichero ────────────────────
# Se aplican contra path.name (solo el nombre, no la ruta completa).

BLACKLIST_PATTERNS: list[str] = [
    "*.key",
    "*.pem",
    "*.crt",
    "*.p12",
    "*.pfx",
    "*.env",
    "credentials*",
    "*token*",     # cualquier fichero con "token" en el nombre
    "*.db",        # bases de datos (home-assistant_v2.db)
    "*.db-shm",
    "*.db-wal",
]

# ── Directorios blacklisteados completos ─────────────────────────────────────
# Todo fichero cuyo primer componente relativo sea uno de estos queda bloqueado.

BLACKLIST_DIRECTORIES: frozenset[str] = frozenset({
    ".cloud",      # credenciales Nabu Casa / Google Assistant
    ".cache",      # cache (no sensible, pero grande y no útil)
    "deps",        # dependencias Python (no útil, potencialmente grande)
})

# ── Allowlist restrictiva para .storage/ ─────────────────────────────────────
# Por defecto todo .storage/ es denied salvo lo que aparece aquí.
# Cualquier fichero bajo .storage/ no presente aquí → tratado como blacklisted.

STORAGE_ALLOWLIST_EXACT: frozenset[str] = frozenset({
    "core.entity_registry",
    "core.device_registry",
    "core.area_registry",
    "core.floor_registry",    # puede no existir, pero si existe es seguro
    "core.label_registry",    # igual
    "core.config",            # opciones generales (location, unit system)
    "core.restore_state",     # útil para diagnosticar reinicios
    "core.analytics",         # estadísticas de uso anónimas
    "core.logger",            # configuración de nivel de log
    # Helpers: su contenido es la configuración que el usuario ve en la UI
    "counter",
    "input_boolean",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "person",
    "schedule",
    "timer",
    "zone",
    # Otros no sensibles
    "energy",
    "backup",
    "assist_pipeline.pipelines",
    "ai_task",
    "bluetooth.passive_update_processor",
    "frontend.system_data",
    "homeassistant.exposed_entities",
    "mobile_app",
    "trace.saved_traces",
})

STORAGE_ALLOWLIST_PATTERNS: list[str] = [
    "lovelace",           # lovelace exacto
    "lovelace.*",         # lovelace.map, lovelace.something
    "lovelace_*",         # lovelace_dashboards, lovelace_resources
    "core.lovelace*",     # futuras variantes
    "esphome.*",          # config entries de ESPHome (no tokens)
    "frontend.user_data_*",  # preferencias de usuario por ID
    "hacs.*",             # HACS data (repositorios, custom components)
]

# ── O_NOFOLLOW (solo POSIX) ───────────────────────────────────────────────────
# Defiende el ÚLTIMO componente del path contra race condition de symlink.
# Defensa PARCIAL: solo protege el archivo final, no los directorios
# intermedios. La defensa real es resolve() + is_relative_to() arriba.
# En Windows O_NOFOLLOW no existe, se usa 0 (sin efecto).
_O_NOFOLLOW: int = getattr(os, "O_NOFOLLOW", 0)
_O_RDONLY: int = os.O_RDONLY


# ── Path normalization ────────────────────────────────────────────────────────

def normalize_path(user_path: str) -> Path:
    """Normaliza y valida un path de usuario.

    Acepta rutas relativas ("automations.yaml") o absolutas bajo /config
    ("/config/automations.yaml"). Rechaza cualquier path que escape de
    CONFIG_BASE.

    Raises:
        PathTraversalError: si el path escapa de CONFIG_BASE.
    """
    if not user_path or not user_path.strip():
        raise PathTraversalError("Empty path is not allowed")

    # 1. URL-decode (%2e%2e → ..)
    user_path = unquote(user_path)

    # 2. Unicode NFC normalization (NFD "café" ≡ NFC "café")
    user_path = unicodedata.normalize("NFC", user_path)

    # 3. Strip leading/trailing whitespace
    user_path = user_path.strip()

    # 4. Si es absoluto, acepta CONFIG_BASE real y el alias /config.
    #    Cualquier otra ruta absoluta es rechazada.
    config_str = str(CONFIG_BASE)
    config_prefix = config_str.rstrip("/") + "/"
    config_exact = config_str.rstrip("/")
    if user_path == config_exact or user_path == "/config":
        return CONFIG_BASE
    if user_path.startswith(config_prefix):
        user_path = user_path[len(config_prefix):]
    elif user_path.startswith("/config/"):
        # Traditional /config alias → remap to CONFIG_BASE
        user_path = user_path[len("/config/"):]
    elif user_path.startswith("/"):
        raise PathTraversalError(
            f"Absolute paths outside /config are forbidden: {user_path!r}"
        )

    # 5. Construye el path absoluto y resuelve (sigue symlinks)
    candidate = (CONFIG_BASE / user_path).resolve()

    # 6. Verifica que sigue dentro de CONFIG_BASE
    try:
        candidate.relative_to(CONFIG_BASE)
    except ValueError:
        raise PathTraversalError(
            f"Path escapes /config boundary: {user_path!r} "
            f"→ {candidate}"
        )

    return candidate


# ── Blacklist / Allowlist checks ──────────────────────────────────────────────

def _rel_posix(path: Path) -> str:
    """Ruta relativa a CONFIG_BASE en formato posix (forward slashes)."""
    try:
        return path.relative_to(CONFIG_BASE).as_posix()
    except ValueError:
        return path.as_posix()


def check_blacklisted(path: Path) -> tuple[bool, str]:
    """Comprueba si un path normalizado está en la blacklist.

    Returns:
        (True, reason) si está bloqueado.
        (False, "") si está permitido.

    El path debe ser ya un path absoluto resuelto dentro de CONFIG_BASE.
    """
    # 0. Fail-closed: la función pide en su docstring un path ya resuelto
    #    dentro de CONFIG_BASE, pero no se fía y lo resuelve otra vez. Confiar
    #    en el llamador no basta: `pathlib` NO colapsa los `..` de un glob, así
    #    que un path construido con rglob() y un patrón del cliente puede llegar
    #    aquí como `sub/../secrets.yaml`, no casar con ninguna regla de abajo
    #    —todas comparan cadenas— y ser abierto igualmente por el sistema
    #    operativo. Resolviendo aquí, ningún llamador puede saltarse la
    #    comprobación por olvido.
    try:
        resolved = path.resolve()
    except (OSError, ValueError, RuntimeError):
        return True, "Path could not be resolved"

    try:
        resolved.relative_to(CONFIG_BASE.resolve())
    except ValueError:
        return True, "Path is outside the configuration directory"

    path = resolved
    rel_str = _rel_posix(path)
    name = path.name

    # 1. Blacklist por nombre relativo exacto
    if rel_str in BLACKLIST_NAMES:
        return True, "Contains potentially sensitive data"

    # 1b. Blacklist por nombre de fichero, en cualquier subdirectorio
    if name in BLACKLIST_BASENAMES:
        return True, "Contains potentially sensitive data"

    # 2. Blacklist por patrón (contra el nombre del fichero)
    for pat in BLACKLIST_PATTERNS:
        if fnmatch.fnmatch(name, pat):
            return True, f"Matches sensitive file pattern {pat!r}"

    # 3. Directorios blacklisteados (primer componente)
    parts = path.relative_to(CONFIG_BASE).parts if path != CONFIG_BASE else ()
    if parts and parts[0] in BLACKLIST_DIRECTORIES:
        return True, f"Directory {parts[0]!r} is restricted"

    # 4. Allowlist .storage/ (default-deny para todo lo no listado)
    if parts and parts[0] == ".storage":
        if len(parts) == 1:
            # El directorio .storage/ en sí es listable
            return False, ""
        filename = parts[1]
        # 4a. Allowlist exacta
        if filename in STORAGE_ALLOWLIST_EXACT:
            return False, ""
        # 4b. Allowlist por patrón
        for pat in STORAGE_ALLOWLIST_PATTERNS:
            if fnmatch.fnmatch(filename, pat):
                return False, ""
        # 4c. No encontrado en allowlist → bloqueado
        return True, f".storage/{filename!r} is not in the filesystem allowlist"

    return False, ""


def check_path_readable(user_path: str) -> Path:
    """Stack de seguridad completo. Devuelve el Path absoluto si es legible.

    Raises:
        PathTraversalError: traversal detectado.
        BlacklistedPathError: fichero en blacklist.
    """
    path = normalize_path(user_path)
    blacklisted, reason = check_blacklisted(path)
    if blacklisted:
        logger.warning(
            "fs_path_blacklisted",
            user_path=user_path,
            resolved=str(path),
            reason=reason,
        )
        raise BlacklistedPathError(
            f"Access denied to {_rel_posix(path)!r}: {reason}"
        )
    return path


# ── Apertura segura de ficheros ───────────────────────────────────────────────

def _open_file_nofollow(path: Path):
    """Abre el fichero con O_NOFOLLOW para defensa en profundidad.

    Nota: O_NOFOLLOW solo protege el ÚLTIMO componente del path contra
    que sea un symlink en el momento de la apertura. Los componentes
    intermedios no están protegidos por O_NOFOLLOW. La protección real
    contra traversal por symlinks en componentes intermedios la aporta
    el resolve() previo en normalize_path().

    Si O_NOFOLLOW no está disponible (Windows), abre sin flag especial.
    """
    flags = _O_RDONLY | _O_NOFOLLOW
    try:
        fd = os.open(str(path), flags)
        return os.fdopen(fd, "rb")
    except OSError as exc:
        # ELOOP en Linux cuando el fichero final es un symlink con O_NOFOLLOW
        # En Windows (O_NOFOLLOW=0) no debería ocurrir
        raise exc


# ── Lectura de bytes ──────────────────────────────────────────────────────────

def read_bytes(path: Path, max_bytes: int | None = None) -> bytes:
    """Lee hasta max_bytes del fichero con apertura O_NOFOLLOW.

    Reintenta UNA vez si el fichero desaparece entre resolve() y open()
    (mitigación TOCTOU — no es un vector de ataque, es robustez ante
    escrituras concurrentes del core de HA).
    """
    import time

    for attempt in range(2):
        try:
            with _open_file_nofollow(path) as f:
                if max_bytes is not None:
                    return f.read(max_bytes)
                return f.read()
        except FileNotFoundError:
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise


# ── Detección de binarios ─────────────────────────────────────────────────────

#: Tamaño de muestra de referencia para sondear si un fichero es binario.
#: `is_binary()` NO lo aplica: recortar el buffer es cosa del llamador.
_BINARY_PROBE_BYTES = 8192


def is_binary(data: bytes) -> bool:
    """Devuelve True si los datos contienen byte nulo (0x00) → binario.

    Examina TODO el buffer recibido. Para no cargar un fichero entero en
    memoria, el llamador le pasa solo los primeros KB.
    """
    return b"\x00" in data


# ── Detección de encoding ─────────────────────────────────────────────────────

_UTF8_BOM = b"\xef\xbb\xbf"


def detect_encoding(data: bytes) -> tuple[str, str]:
    """Detecta el encoding del contenido.

    Returns:
        (encoding_name, decoded_content)
        encoding_name: "utf-8-bom", "utf-8", "latin-1"

    Raises:
        UnicodeDecodeError-like: envuelto en ValueError si ambos fallan.
    """
    if data.startswith(_UTF8_BOM):
        try:
            return "utf-8-bom", data[3:].decode("utf-8")
        except UnicodeDecodeError:
            pass

    try:
        return "utf-8", data.decode("utf-8")
    except UnicodeDecodeError:
        pass

    try:
        return "latin-1", data.decode("latin-1")
    except UnicodeDecodeError:
        pass

    raise ValueError("Cannot decode file as text (tried utf-8-bom, utf-8, latin-1)")


# ── Metadata de un path ───────────────────────────────────────────────────────

def path_stat(path: Path) -> dict[str, Any]:
    """Retorna metadata de un path sin leer su contenido."""
    import datetime

    try:
        stat = path.lstat()
        if path.is_symlink():
            ptype = "symlink"
        elif path.is_dir():
            ptype = "dir"
        elif path.is_file():
            ptype = "file"
        else:
            ptype = "other"

        modified = datetime.datetime.fromtimestamp(
            stat.st_mtime, tz=datetime.timezone.utc
        ).isoformat()

        size_bytes = stat.st_size if ptype == "file" else None

    except OSError:
        ptype = "unknown"
        modified = None
        size_bytes = None

    blacklisted, _reason = check_blacklisted(path)
    rel_str = _rel_posix(path)
    parts = path.relative_to(CONFIG_BASE).parts if path != CONFIG_BASE else ()
    is_managed = bool(parts) and parts[0] == ".storage"

    return {
        "path": rel_str,
        "type": ptype,
        "size_bytes": size_bytes,
        "modified": modified,
        "is_blacklisted": blacklisted,
        "is_managed_path": is_managed,
    }
