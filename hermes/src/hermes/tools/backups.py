"""Hermes — Tools MCP para Backups del Supervisor.

Gestión de backups de HAOS vía Supervisor REST API.

Tools:
  sv_list_backups          — lista backups disponibles
  sv_get_backup            — info detallada de un backup
  sv_create_backup_full    — crea backup completo (async, sin token)
  sv_create_backup_partial — crea backup parcial (async, sin token)
  sv_create_safety_backup  — wrapper de create_backup_full con cooldown
  sv_delete_backup         — elimina un backup (siempre requiere token)
  sv_restore_backup_full   — restaura backup completo (token + advertencia)
  sv_restore_backup_partial— restaura backup parcial (token + advertencia)
  sv_get_job_status        — consulta estado de un job en curso
  sv_list_pending_jobs     — jobs lanzados por Hermes en la última hora

Modo async (MODE A): todas las operaciones largas usan background=True.
El Supervisor devuelve inmediatamente un job_id. El cliente debe pollear
con sv_get_job_status(job_id) hasta ver done=True.

Safety backup: sv_create_safety_backup respeta safety_backup_window_minutes.
Si el último safety backup fue hace menos del window, devuelve referencia
al existente sin crear uno nuevo. Límite duro: nunca <60s entre safety
backups consecutivos.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
import time
from pathlib import Path
from typing import Any

import aiohttp
import structlog

from hermes import safety_retention as _retencion
from hermes.backup_key import (
    CIFRADO_NO,
    CLAVE_NO_DISPONIBLE,
    HA_INALCANZABLE,
    SIN_CLAVE,
    clave_para_safety_backup,
    exige_cifrado,
    leer_clave_de_backups,
    por_que_sin_clave,
    sin_clave_bloquea,
    sin_secretos,
)
from hermes.supervisor_jobs import child_job_errors, job_errors, redact_child_jobs
from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    ESTADO_CAMBIADO,
    complete_confirmation_token,
    create_confirmation_token,
    redact_secrets,
    resolve_confirmation_token,
    validate_confirmation_token,
)
from hermes.tools.addons import _PENDING_JOBS_PATH, _jobs_lock, _load_jobs_sync, _track_job, _write_jobs_sync
from hermes.tools._eco_supervisor import sin_eco_del_supervisor
from hermes.tools._validation import (
    InvalidIdentifier,
    es_numero_finito,
    validate_identifier,
    validate_slug,
)

logger = structlog.get_logger(__name__)

_LONG_OP_TIMEOUT = 300.0  # 5 min
_SAFETY_BACKUP_STATE_PATH = Path("/data/last_safety_backup.json")
_SAFETY_BACKUP_MIN_INTERVAL_SECONDS = 60  # límite duro absoluto


# ── Ubicación del backup (spec 019, FR-014; research R-9) ────────────────────
# `.local` es el disco de Home Assistant OS; lo demás, el nombre de un montaje
# de uso `backup` (la forma de nombre del Supervisor, con el tope de 64 de
# Hermes). `.cloud_backup` es una ubicación interna de Home Assistant que el
# Supervisor rechaza a un add-on: decirlo antes evita un error opaco. Que el
# montaje exista y sea de backup lo comprueba el Supervisor (una lectura
# previa sería otra llamada y otra carrera).
_UBICACION = re.compile(r"^(\.local|[A-Za-z0-9_]{1,64})$")
_DETALLE_UBICACION = (
    "location must be '.local' (local storage), the name of a backup mount "
    "(letters, digits or '_') or a non-empty list of those without "
    "repetitions; '.cloud_backup' is not allowed."
)


def _ubicacion_invalida(location: Any) -> dict[str, Any] | None:
    """`None` si `location` es válida (o no se pasó); si no, el error."""
    if location is None:
        return None
    valores = location if isinstance(location, list) else [location]
    if (not valores or len(set(map(str, valores))) != len(valores)
            or not all(isinstance(v, str) and _UBICACION.match(v) for v in valores)):
        return {"error": "invalid_argument", "detail": _DETALLE_UBICACION}
    return None


def _load_safety_state() -> dict[str, Any]:
    try:
        return json.loads(_SAFETY_BACKUP_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# Clave canónica de la marca de tiempo del último safety backup, en segundos
# epoch. Hay DOS caminos que crean safety backups —la tool `sv_create_safety_
# backup` y el disparo automático antes de escribir en /config— y comparten
# este fichero de estado. Usar cada uno su propia clave, con un guardado que
# reemplazaba el documento entero, hacía que cada camino borrara la marca del
# otro: ambos veían "nunca se hizo ninguno" y disparaban un backup COMPLETO de
# varios GB, saltándose tanto la ventana configurable como el límite duro.
_MARCA = "last_safety_backup_at"

# Claves que usaron versiones anteriores. Se leen para no perder la marca de
# una instalación que ya venía funcionando.
_MARCAS_ANTIGUAS = ("last_created_at", "last_completed_at")


def _leer_marca(state: dict[str, Any]) -> float:
    """Momento del último safety backup, en epoch. 0 si no hay ninguno.

    Tolera los dos formatos que han existido: epoch numérico e ISO-8601.
    """
    for clave in (_MARCA, *_MARCAS_ANTIGUAS):
        valor = state.get(clave)
        # Un entero enorme no cabe en un float (`OverflowError`): se ignora.
        if es_numero_finito(valor) and valor > 0:
            return float(valor)
        if isinstance(valor, str) and valor:
            try:
                return datetime.fromisoformat(valor.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
    return 0.0


def _save_safety_state(state: dict[str, Any]) -> None:
    """Funde los campos nuevos con los que ya hubiera en disco.

    Reemplazar el documento entero es lo que permitía que un camino borrara la
    marca del otro.

    Un valor `None` borra la clave: el safety backup automático necesita
    quitar sus claves pendientes (`pending_*`) al resolver el job, y dejarlas
    a `null` haría que la escritura siguiente las tomara por un job en curso.
    """
    actual = _load_safety_state()
    for clave, valor in state.items():
        if valor is None:
            actual.pop(clave, None)
        else:
            actual[clave] = valor
    _SAFETY_BACKUP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _SAFETY_BACKUP_STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(actual, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_SAFETY_BACKUP_STATE_PATH)


# `_job_errors` vive en `hermes.supervisor_jobs` para romper el import
# circular con `safety_retention`; el alias mantiene el nombre de siempre.
_job_errors = job_errors


def _size_mb(backup: dict[str, Any]) -> float | None:
    """Tamaño del backup en MB a partir de lo que manda el Supervisor.

    El Supervisor envía dos campos: `size_bytes` (bytes, int) y `size`, que YA
    viene en MB (`round(self.size_bytes / 1048576, 2)` en backup/backup.py).
    Dividir `size` entre 1 MiB, como se hacía, convertía 500 MB en 0.0 y todos
    los backups aparecían con tamaño cero. Se prefiere `size_bytes` por
    precisión y se cae a `size` —interpretado como MB— si no viene.
    """
    size_bytes = backup.get("size_bytes")
    # `es_numero_finito`: un entero enorme lanzaba `OverflowError` al
    # dividir o pasar a float (cierre de robustez de la 1.2.0).
    if es_numero_finito(size_bytes):
        return round(size_bytes / (1024 * 1024), 2)
    size = backup.get("size")
    if es_numero_finito(size):
        return round(float(size), 2)
    return None


# ── Contraseña de las restauraciones (spec 031, FR-015) ─────────────────────
# Sin `password`, un backup protegido se restaura con la clave de los backups
# de HA (la del kit de emergencia, `backup_key.py`): es con la que la 031
# cifra los backups que crea Hermes. `password_source` dice en la vista previa
# de dónde sale, NUNCA el valor. `unknown` es cuando no se pudo leer el
# backup (`/backups/{slug}/info`): no se sabe si está protegido y se manda
# sin contraseña, como en la 1.1.2.
_FUENTE_PROVIDED = "provided"
_FUENTE_CLAVE = "backup_encryption_key"
_FUENTE_CLAVE_NO = "backup_encryption_key_unavailable"
_FUENTE_NO_HACE_FALTA = "not_needed"
_FUENTE_DESCONOCIDA = "unknown"
_PISTA_CLAVE_ANTERIOR = (
    "The password was Home Assistant's current backup encryption key; the "
    "backup may be encrypted with an older key. Pass that one as password."
)


# Lo que dice la respuesta de un safety backup cifrado (spec 031, FR-013): que
# restaurarlo necesita la clave de HA, y dónde está si Hermes no funciona.
NOTA_SAFETY_CIFRADO = (
    "Encrypted with Home Assistant's backup encryption key (the one in your "
    "emergency kit). sv_restore_backup_full uses that key when you pass no "
    "password; from the Home Assistant UI or CLI you need the emergency kit. "
    "If the key is changed later, this backup still needs the old one."
)
AVISO_SAFETY_SIN_CIFRAR = (
    "This safety backup is NOT encrypted: it holds secrets.yaml, integration "
    "tokens and app data in clear. Set up Home Assistant's automatic backups "
    "(that creates the encryption key) to have the next ones encrypted."
)


def aviso_safety_sin_cifrar(motivo: str | None) -> str:
    """El aviso de un safety backup sin cifrar, según por qué (T064).

    «Configura los backups automáticos» solo sirve si HA no tiene clave; si
    no se pudo leer, la clave puede existir y el consejo engañaría."""
    if motivo == SIN_CLAVE:
        return AVISO_SAFETY_SIN_CIFRAR
    return ("This safety backup is NOT encrypted: it holds secrets.yaml, "
            "integration tokens and app data in clear. "
            f"{por_que_sin_clave(motivo)}.")


# Estado del último safety backup: si iba cifrado (T062). Una ventana solo
# se reutiliza si el backup cumple el modo de cifrado ACTUAL: con `required`,
# uno sin cifrar (hecho antes con `auto` sin clave o con `off`; el estado
# vive en /data y sobrevive al reinicio que cambia la opción) no cubre la
# escritura. Sin la marca (estado de antes de la 031) cuenta como sin cifrar,
# que es lo que eran todos.
_CIFRADO_ULTIMO = "last_encrypted"


def ultimo_cifrado(state: dict[str, Any]) -> bool:
    """¿El último safety backup del estado iba cifrado?"""
    return state.get(_CIFRADO_ULTIMO) is True


def ventana_reutilizable(state: dict[str, Any], modo: str) -> bool:
    """¿El último safety backup vale para el modo de cifrado actual?"""
    return ultimo_cifrado(state) or not exige_cifrado(modo)


def register(
    mcp: object,
    ha_client: HAClient,
    safety_backup_window_minutes: int = 30,
    # `off` aquí y no `auto`: es el valor de quien registra las tools a mano
    # (tests, herramientas), que no siempre tiene WebSocket de HA. El
    # arranque pasa SIEMPRE la opción del add-on, que por defecto es `auto`
    # (`config.py`; lo comprueba `test_main_wiring`).
    safety_backup_encryption: str = CIFRADO_NO,
) -> None:
    """Registra las tools de backups en la instancia MCP."""

    async def _fuente_password(
        protegido: bool | None, password: str | None,
    ) -> tuple[str, str | None, str | None]:
        """(password_source, clave de HA o None, motivo si no hay clave).

        La clave solo se lee si hace falta, en cada llamada y sin caché; quien
        la recibe la manda al Supervisor y la descarta."""
        if password:
            return _FUENTE_PROVIDED, None, None
        if protegido is None:
            return _FUENTE_DESCONOCIDA, None, None
        if not protegido:
            return _FUENTE_NO_HACE_FALTA, None, None
        leida = await leer_clave_de_backups(ha_client)
        if leida.clave is None:
            return _FUENTE_CLAVE_NO, None, leida.motivo
        return _FUENTE_CLAVE, leida.clave, None

    async def _info_backup(slug: str) -> tuple[dict[str, Any] | None, bool | None]:
        """(info del backup o None, si está protegido o None si no se sabe)."""
        try:
            info = await ha_client.sv_request("GET", f"/backups/{slug}/info")
        except HAConnectionError:
            return None, None
        if not isinstance(info, dict):
            return None, None
        return info, info.get("protected") is True

    def _poner_fuente(preview: dict[str, Any], fuente: str, motivo: str | None) -> None:
        preview["password_source"] = fuente
        if fuente == _FUENTE_CLAVE_NO:
            preview["password_source_reason"] = motivo
            # Según el motivo (T064): «HA no tiene clave» solo si es verdad.
            preview["password_warning"] = (
                f"The backup is encrypted and {por_que_sin_clave(motivo)}: the "
                "restore will fail unless you pass password."
            )

    def _sin_respuesta_de_ha(fuente: str, motivo: str | None) -> dict[str, Any] | None:
        """Al confirmar, la clave no se pudo leer porque HA no respondió (T064).

        Es lo que pasó, no un «estado cambiado». No se restaura y el token no
        se consume: se puede reintentar cuando HA responda."""
        if fuente != _FUENTE_CLAVE_NO or motivo != HA_INALCANZABLE:
            return None
        return {"error": "ha_unreachable",
                "detail": "Home Assistant did not answer, so its backup encryption "
                          "key could not be read; nothing was restored. Retry with the "
                          "same token while it is valid, or pass password."}

    def _error_restaurar(exc: Exception, fuente: str,
                         carga: dict[str, Any]) -> dict[str, Any]:
        # `exc` ya viene sin la clave ni la contraseña (`sin_secretos`); el
        # eco del resto de la carga se quita igual que en todas las `sv_*`
        # (cierre de seguridad).
        out: dict[str, Any] = {"error": sin_eco_del_supervisor(str(exc), carga)}
        # «Invalid password for backup» del Supervisor (2026.11.0).
        if fuente == _FUENTE_CLAVE and "invalid password" in str(exc).lower():
            out["hint"] = _PISTA_CLAVE_ANTERIOR
        return out

    def _bad_slug(slug: str) -> dict[str, Any] | None:
        try:
            validate_slug(slug, field="slug")
            return None
        except InvalidIdentifier as exc:
            return {"error": "invalid_identifier", "detail": str(exc)}

    def _bad_job(job_id: str) -> dict[str, Any] | None:
        try:
            validate_identifier(job_id, field="job_id")
            return None
        except InvalidIdentifier as exc:
            return {"error": "invalid_identifier", "detail": str(exc)}

    @mcp.tool()
    async def sv_list_backups() -> object:
        """Lista los backups disponibles en HAOS.

        Returns:
            {"backups": [...], "count": N}
            Cada item: slug, name, date, type (full/partial),
            size_mb, protected, location.
            `location: null` significa almacenamiento local (el disco de
            HAOS); otro valor es el nombre de un montaje de red. Si el backup
            está en varias ubicaciones, `location` y `protected` son los de
            la primera.
        """
        try:
            data = await ha_client.sv_request("GET", "/backups")
            backups = data.get("backups", []) if isinstance(data, dict) else []
            summaries = [
                {
                    "slug": b.get("slug"),
                    "name": b.get("name"),
                    "date": b.get("date"),
                    "type": b.get("type"),
                    "size_mb": _size_mb(b),
                    "protected": b.get("protected", False),
                    "location": b.get("location"),
                }
                for b in backups
            ]
            return {"backups": summaries, "count": len(summaries)}
        except HAConnectionError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_get_backup(slug: str) -> object:
        """Devuelve información detallada de un backup.

        Args:
            slug: Identificador del backup (hash hexadecimal).

        Returns:
            Metadata completa: name, date, type, size, homeassistant
            version, add-ons incluidos, carpetas incluidas.
        """
        if (err := _bad_slug(slug)):
            return err
        try:
            data = await ha_client.sv_request("GET", f"/backups/{slug}/info")
            return data if isinstance(data, dict) else {"raw": data}
        except HAConnectionError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_create_backup_full(
        name: str,
        password: str | None = None,
        location: str | list[str] | None = None,
    ) -> object:
        """Crea un backup completo de HAOS.

        Operación larga — devuelve job_id inmediatamente.
        Usa sv_get_job_status(job_id) para consultar el progreso.
        No requiere confirmation_token — crear backups es defensivo.

        Args:
            name: Nombre descriptivo del backup.
            password: Contraseña opcional para cifrar el backup.
            location: Opcional. Dónde guardarlo: '.local' (disco local), el
                nombre de un montaje de uso backup (sv_list_mounts) o una
                lista de esos (el primero es el principal; el resto, copias).
                Sin ella, el Supervisor usa el montaje por defecto
                (sv_get_backup_settings). '.cloud_backup' no se admite.

        Returns:
            {"job_id": "...", "status": "running",
             "poll_with": "sv_get_job_status"} (más `location` si se pasó)
        """
        if (error := _ubicacion_invalida(location)) is not None:
            return error
        payload: dict[str, Any] = {"name": name, "background": True}
        if password:
            payload["password"] = password
        # Sin `location`, la carga es la de la 1.1.2 (FR-017 de la 019).
        if location is not None:
            payload["location"] = location
        con_ubicacion = {} if location is None else {"location": location}

        try:
            data = await ha_client.sv_request(
                "POST", "/backups/new/full",
                json_body=payload,
                timeout_seconds=_LONG_OP_TIMEOUT,
            )
            job_id = data.get("job_id") if isinstance(data, dict) else None
            if job_id:
                await _track_job(job_id, {"op": "create_backup_full", "name": name})
                logger.info("sv_create_backup_full_started", name=name, job_id=job_id,
                            **con_ubicacion)
                return {
                    "job_id": job_id,
                    "status": "running",
                    "poll_with": "sv_get_job_status",
                    **con_ubicacion,
                }
            # Backup completado sincrónicamente (no debería ocurrir con background=True)
            slug = data.get("slug") if isinstance(data, dict) else None
            return {"result": "ok", "slug": slug, **con_ubicacion}
        except HAConnectionError as exc:
            # Redactado (019): con `location`, el error puede venir del montaje
            # de un NAS y repetir sus opciones. Y sin el eco de la carga
            # (cierre de seguridad): un 400 de validación repite «Got
            # {'password': …}» con comillas simples, que `redact_secrets`
            # no reconoce.
            return {"error": sin_eco_del_supervisor(str(exc), payload)}

    @mcp.tool()
    async def sv_create_backup_partial(
        name: str,
        addons: str | None = None,
        folders: str | None = None,
        password: str | None = None,
        include_homeassistant: bool = True,
        location: str | list[str] | None = None,
    ) -> object:
        """Crea un backup parcial de HAOS.

        Operación larga — devuelve job_id inmediatamente.
        No requiere confirmation_token.

        Args:
            name: Nombre descriptivo del backup.
            addons: JSON array de slugs de add-ons a incluir,
                    ej. '["core_mosquitto", "local_hermes"]'.
                    Si null, no incluye add-ons.
            folders: JSON array de carpetas a incluir,
                     ej. '["homeassistant", "share", "ssl"]'.
                     Si null, no incluye carpetas extra.
            password: Contraseña opcional para cifrar el backup.
            include_homeassistant: Si incluir la configuración de HA
                                   core (default True).
            location: Opcional. Dónde guardarlo: '.local' (disco local), el
                nombre de un montaje de uso backup (sv_list_mounts) o una
                lista de esos (el primero es el principal; el resto, copias).
                Sin ella, el Supervisor usa el montaje por defecto
                (sv_get_backup_settings). '.cloud_backup' no se admite.

        Returns:
            {"job_id": "...", "status": "running",
             "poll_with": "sv_get_job_status"} (más `location` si se pasó)
        """
        if (error := _ubicacion_invalida(location)) is not None:
            return error
        payload: dict[str, Any] = {
            "name": name,
            "background": True,
            "homeassistant": include_homeassistant,
        }
        if password:
            payload["password"] = password
        if addons:
            try:
                payload["addons"] = json.loads(addons)
            except json.JSONDecodeError as exc:
                return {"error": f"addons must be a JSON array: {exc}"}
        if folders:
            try:
                payload["folders"] = json.loads(folders)
            except json.JSONDecodeError as exc:
                return {"error": f"folders must be a JSON array: {exc}"}
        # Sin `location`, la carga es la de la 1.1.2 (FR-017 de la 019).
        if location is not None:
            payload["location"] = location
        con_ubicacion = {} if location is None else {"location": location}

        try:
            data = await ha_client.sv_request(
                "POST", "/backups/new/partial",
                json_body=payload,
                timeout_seconds=_LONG_OP_TIMEOUT,
            )
            job_id = data.get("job_id") if isinstance(data, dict) else None
            if job_id:
                await _track_job(job_id, {"op": "create_backup_partial", "name": name})
                logger.info("sv_create_backup_partial_started", name=name,
                            job_id=job_id, **con_ubicacion)
                return {
                    "job_id": job_id,
                    "status": "running",
                    "poll_with": "sv_get_job_status",
                    **con_ubicacion,
                }
            slug = data.get("slug") if isinstance(data, dict) else None
            return {"result": "ok", "slug": slug, **con_ubicacion}
        except HAConnectionError as exc:
            return {"error": sin_eco_del_supervisor(str(exc), payload)}

    @mcp.tool()
    async def sv_create_safety_backup() -> object:
        """Crea un backup completo de seguridad antes de operaciones destructivas.

        Wrapper de sv_create_backup_full con nombre automático
        hermes-safety-<timestamp>. Operación larga: devuelve job_id.

        Cooldown: si el último safety backup fue hace menos de
        `safety_backup_window_minutes` (opción del add-on, 30 por defecto),
        devuelve una referencia al existente sin crear uno nuevo. Límite duro:
        nunca menos de 60 segundos entre safety backups consecutivos.

        No requiere confirmation_token — crear backups es defensivo.

        Cifrado (opción `safety_backup_encryption`, `auto` por defecto): con
        la clave de los backups de Home Assistant (la del kit de emergencia),
        que Hermes lee en el momento y no guarda ni devuelve. La respuesta
        dice siempre `encrypted`. Con `auto` y HA sin clave, el backup sale sin
        cifrar con `encryption_skipped_reason`; con `required` y sin clave no
        se crea (`encryption_key_unavailable`). Para restaurarlo,
        `sv_restore_backup_full` sin `password` usa la clave de HA.

        Retención: el backup se anota como safety backup de Hermes y entra en
        la retención `safety_backup_keep` (opción del add-on, 3 por defecto).
        Esta tool nunca borra nada: la poda se aplica tras cada safety backup
        automático correcto (el que se hace antes de escribir en /config) y
        solo toca safety backups que Hermes anotó y confirmó.

        Con `required`, un safety backup reciente SIN cifrar no se
        reutiliza: se hace uno nuevo cifrado (o `encryption_key_unavailable`
        si no hay clave; `safety_backup_rate_limited` si el anterior es de
        hace menos de 60 segundos).

        Returns:
            Si reutiliza uno reciente: {"reused": true, "encrypted": bool,
            "job_id"|"slug": ...}.
            Si crea uno nuevo: {"job_id": "...", "status": "running",
            "poll_with": "sv_get_job_status", "encrypted": bool}.
        """
        # El mismo lock que el safety backup automático de `fs_write`: sin él,
        # la tool reescribía el estado entero mientras el camino automático
        # sondeaba un job, y se perdía la referencia `pending_*` (revisión
        # 1.1.0, BAJO-11). Espera acotada, como las escrituras (BAJO-12).
        if not await _retencion.acquire_safety_backup_lock():
            return dict(_retencion.SAFETY_LOCK_BUSY)
        try:
            return await _crear_safety_backup()
        finally:
            _retencion.safety_backup_lock().release()

    async def _crear_safety_backup() -> object:
        """Cuerpo de `sv_create_safety_backup`, ya con el lock tomado."""
        now = time.time()
        state = _load_safety_state()
        last_ts = _leer_marca(state)
        last_job = state.get("last_job_id")
        last_slug = state.get("last_slug")
        # La respuesta dice SIEMPRE `encrypted`, también al reutilizar (FR-013,
        # T062); y solo se reutiliza un backup que cumpla el modo actual.
        reutilizable = ventana_reutilizable(state, safety_backup_encryption)
        cifrado_ultimo = {"encrypted": ultimo_cifrado(state)}

        # Límite duro: nunca <60s entre safety backups
        if now - last_ts < _SAFETY_BACKUP_MIN_INTERVAL_SECONDS:
            if not reutilizable:
                # `required` y el último va sin cifrar: no vale, y tampoco se
                # puede hacer otro antes del minuto. Nada se da por cubierto.
                return {
                    "error": "safety_backup_rate_limited",
                    "encrypted": False,
                    "detail": (
                        "safety_backup_encryption is 'required' and the last "
                        "safety backup is not encrypted, but it was made less "
                        f"than {_SAFETY_BACKUP_MIN_INTERVAL_SECONDS} s ago; retry "
                        "later and an encrypted one will be made."
                    ),
                }
            return {
                "reused": True,
                "reason": "hard_limit",
                "last_created_at": last_ts,
                "job_id": last_job,
                "slug": last_slug,
                **cifrado_ultimo,
            }

        # Cooldown por ventana configurable
        window_seconds = safety_backup_window_minutes * 60
        if now - last_ts < window_seconds and reutilizable:
            return {
                "reused": True,
                "reason": "within_window",
                "window_minutes": safety_backup_window_minutes,
                "last_created_at": last_ts,
                "job_id": last_job,
                "slug": last_slug,
                **cifrado_ultimo,
            }

        # La clave se lee DESPUÉS de la ventana y del límite duro (un backup
        # reutilizado no la necesita) y vive solo en esta llamada: va en el
        # POST y en nada más (ni estado, ni anotación, ni log, ni respuesta).
        leida = await clave_para_safety_backup(ha_client, safety_backup_encryption)
        clave = leida.clave if leida is not None else None
        motivo = leida.motivo if leida is not None else None
        if leida is not None and clave is None and sin_clave_bloquea(safety_backup_encryption):
            # `required`: sin clave no hay backup (FR-013). No se toca el
            # estado: no hubo intento, y la ventana sigue contando del último.
            logger.error("safety_backup_encryption_key_unavailable",
                         origin="tool", reason=motivo)
            return {
                "error": CLAVE_NO_DISPONIBLE,
                "reason": motivo,
                "detail": (
                    "safety_backup_encryption is 'required' and Home "
                    "Assistant's backup encryption key is not available, so "
                    "no safety backup was created."
                ),
            }
        if leida is not None and clave is None:
            # `auto` sin clave: sin cifrar, pero dicho (respuesta y log).
            logger.warning("safety_backup_unencrypted", origin="tool", reason=motivo)

        ts_label = time.strftime("%Y%m%d-%H%M%S", time.gmtime(now))
        backup_name = f"hermes-safety-{ts_label}"
        cuerpo: dict[str, Any] = {"name": backup_name, "background": True}
        if clave is not None:
            cuerpo["password"] = clave
        cifrado: dict[str, Any] = {"encrypted": clave is not None}
        if clave is not None:
            cifrado["restore_note"] = NOTA_SAFETY_CIFRADO
        elif leida is not None:
            cifrado["encryption_skipped_reason"] = motivo
            cifrado["warning"] = aviso_safety_sin_cifrar(motivo)

        try:
            # Único punto que tapa la clave (T061): ni el error ni la
            # respuesta del Supervisor la pueden sacar.
            data = await sin_secretos(ha_client.sv_request(
                "POST", "/backups/new/full",
                json_body=cuerpo,
                timeout_seconds=_LONG_OP_TIMEOUT,
            ), clave)
            job_id = data.get("job_id") if isinstance(data, dict) else None
            slug = data.get("slug") if isinstance(data, dict) else None

            new_state = {
                _MARCA: now,
                "last_job_id": job_id,
                "last_slug": slug,
                "backup_name": backup_name,
                _CIFRADO_ULTIMO: clave is not None,
            }
            _save_safety_state(new_state)
            # Se anota para la retención, pero aquí NO se poda: esta tool
            # «crea» y no lleva token; si borrara backups sería destructiva
            # sin confirmación. Sus backups se podan en la siguiente poda,
            # tras un safety backup automático correcto.
            try:
                await _retencion.record_launch(
                    backup_name, job_id if isinstance(job_id, str) else None,
                    origin="tool", slug=slug if isinstance(slug, str) else None,
                    encrypted=clave is not None)
            except Exception as exc:  # noqa: BLE001 — anotar no puede tumbar el backup
                logger.warning("safety_backup_ledger_error", error=str(exc))

            if job_id:
                await _track_job(job_id, {"op": "create_safety_backup", "name": backup_name})
                logger.info("sv_create_safety_backup_started", name=backup_name,
                            job_id=job_id, encrypted=clave is not None)
                return {
                    "reused": False,
                    "job_id": job_id,
                    "status": "running",
                    "backup_name": backup_name,
                    "poll_with": "sv_get_job_status",
                    **cifrado,
                }
            return {"reused": False, "result": "ok", "slug": slug,
                    "backup_name": backup_name, **cifrado}
        except (HAConnectionError, aiohttp.ClientError) as exc:
            # Ya sin la clave (`sin_secretos`), y sin el eco del resto de la
            # carga (cierre de seguridad). `aiohttp.ClientError`: el
            # Supervisor caído (conexión rechazada) no es `HAConnectionError`
            # y, sin capturarlo, salía el error genérico del SDK.
            return {"error": sin_eco_del_supervisor(str(exc), cuerpo)}

    @mcp.tool()
    async def sv_delete_backup(
        slug: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Elimina un backup de HAOS.

        Siempre requiere confirmation_token.

        Args:
            slug: Identificador del backup (hash hexadecimal).
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"result": "ok"}
        """
        if (err := _bad_slug(slug)):
            return err
        tool_name = "sv_delete_backup"
        args: dict[str, Any] = {"slug": slug}

        if not confirmation_token:
            try:
                info = await ha_client.sv_request("GET", f"/backups/{slug}/info")
                name = info.get("name") if isinstance(info, dict) else None
                bdate = info.get("date") if isinstance(info, dict) else None
                btype = info.get("type") if isinstance(info, dict) else None
            except HAConnectionError:
                name = bdate = btype = None
            preview: dict[str, Any] = {
                "slug": slug,
                "name": name,
                "date": bdate,
                "type": btype,
                "action": "delete",
            }
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}

        try:
            await ha_client.sv_request("DELETE", f"/backups/{slug}")
            result: dict[str, Any] = {"result": "ok", "slug": slug}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_delete_backup_ok", slug=slug)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_restore_backup_full(
        slug: str,
        confirmation_token: str | None = None,
        password: str | None = None,
    ) -> object:
        """Restaura un backup completo de HAOS.

        WARNING CRÍTICO: esto sobreescribe HA core, todos los add-ons y
        todos los datos. El estado actual se PIERDE. Hermes mismo será
        reemplazado por la versión del backup — si esa versión está rota,
        se necesitará intervención manual.

        Operación larga — devuelve job_id. Usa sv_get_job_status(job_id).

        Args:
            slug: Identificador del backup.
            confirmation_token: Token del preview anterior.
            password: Contraseña del backup si está cifrado. Sin ella, un
                backup protegido se restaura con la clave de cifrado de los
                backups de Home Assistant (la del kit de emergencia); la
                vista previa dice de dónde sale en `password_source`, nunca
                el valor.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"job_id": "...", "status": "running",
                        "poll_with": "sv_get_job_status"}
        """
        if (err := _bad_slug(slug)):
            return err
        tool_name = "sv_restore_backup_full"
        args: dict[str, Any] = {"slug": slug, "password": password}
        # La clave de HA no es un argumento: no entra en el token. Lo que ata
        # el token es de dónde sale la contraseña (estado de la 018).
        info, protegido = (None, None) if password else await _info_backup(slug)
        fuente, clave, motivo = await _fuente_password(protegido, password)
        estado = {"password_source": fuente}

        if not confirmation_token:
            if info is None and password:
                info, _ = await _info_backup(slug)
            name = info.get("name") if info else None
            bdate = info.get("date") if info else None
            ha_version = info.get("homeassistant") if info else None
            preview: dict[str, Any] = {
                "slug": slug,
                "name": name,
                "date": bdate,
                "homeassistant_version": ha_version,
                "action": "restore_full",
                "warning": (
                    "WARNING: this overwrites HA core, ALL add-ons, and ALL data. "
                    "The current state will be PERMANENTLY LOST. "
                    "Hermes itself will be replaced by the version in the backup. "
                    "Recovery requires manual intervention if the restored Hermes is broken."
                ),
            }
            _poner_fuente(preview, fuente, motivo)
            return await create_confirmation_token(tool_name, args, preview=preview,
                                                   estado=estado)

        if (sin_ha := _sin_respuesta_de_ha(fuente, motivo)):
            return sin_ha
        valid, error, _ = await resolve_confirmation_token(
            confirmation_token, tool_name, args, estado=estado)
        if not valid:
            if error == ESTADO_CAMBIADO:
                return {"error": "state_changed", "detail": error}
            return {"error": error}

        payload: dict[str, Any] = {"background": True}
        if password:
            payload["password"] = password
        elif clave is not None:
            payload["password"] = clave
        try:
            # Único punto que tapa la clave y la contraseña (T061).
            data = await sin_secretos(ha_client.sv_request(
                "POST", f"/backups/{slug}/restore/full",
                json_body=payload,
                timeout_seconds=_LONG_OP_TIMEOUT,
            ), password, clave)
            job_id = data.get("job_id") if isinstance(data, dict) else None
            if job_id:
                await _track_job(job_id, {"op": "restore_backup_full", "slug": slug})
                result: dict[str, Any] = {
                    "job_id": job_id,
                    "status": "running",
                    "poll_with": "sv_get_job_status",
                }
            else:
                result = {"result": "ok"}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_restore_backup_full_started", slug=slug, job_id=job_id,
                        password_source=fuente)
            return result
        except (HAConnectionError, aiohttp.ClientError) as exc:
            # `aiohttp.ClientError`: el Supervisor caído; sin capturarlo, el
            # error genérico del SDK y el token en `executing` hasta caducar.
            out = _error_restaurar(exc, fuente, payload)
            await complete_confirmation_token(confirmation_token, success=False,
                                              error=out["error"])
            return out
        finally:
            # La carga puede llevar la clave: no se queda más de lo necesario.
            payload.pop("password", None)

    @mcp.tool()
    async def sv_restore_backup_partial(
        slug: str,
        confirmation_token: str | None = None,
        addons: str | None = None,
        folders: str | None = None,
        password: str | None = None,
        include_homeassistant: bool = False,
    ) -> object:
        """Restaura un backup parcial de HAOS.

        Siempre requiere confirmation_token. Operación larga → job_id.

        Args:
            slug: Identificador del backup.
            confirmation_token: Token del preview anterior.
            addons: JSON array de slugs de add-ons a restaurar.
            folders: JSON array de carpetas a restaurar.
            password: Contraseña del backup si está cifrado. Sin ella, un
                backup protegido se restaura con la clave de cifrado de los
                backups de Home Assistant (la del kit de emergencia); la
                vista previa dice de dónde sale en `password_source`.
            include_homeassistant: Si restaurar la configuración de HA.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"job_id": "...", "status": "running",
                        "poll_with": "sv_get_job_status"}
        """
        if (err := _bad_slug(slug)):
            return err
        tool_name = "sv_restore_backup_partial"
        args: dict[str, Any] = {
            "slug": slug,
            "addons": addons,
            "folders": folders,
            "password": password,
            "include_homeassistant": include_homeassistant,
        }
        info, protegido = (None, None) if password else await _info_backup(slug)
        fuente, clave, motivo = await _fuente_password(protegido, password)
        estado = {"password_source": fuente}

        if not confirmation_token:
            if info is None and password:
                info, _ = await _info_backup(slug)
            name = info.get("name") if info else None
            preview: dict[str, Any] = {
                "slug": slug,
                "name": name,
                "addons_to_restore": addons,
                "folders_to_restore": folders,
                "include_homeassistant": include_homeassistant,
                "action": "restore_partial",
                "warning": (
                    "Selected components will be overwritten with the backup versions."
                ),
            }
            _poner_fuente(preview, fuente, motivo)
            return await create_confirmation_token(tool_name, args, preview=preview,
                                                   estado=estado)

        if (sin_ha := _sin_respuesta_de_ha(fuente, motivo)):
            return sin_ha
        valid, error, _ = await resolve_confirmation_token(
            confirmation_token, tool_name, args, estado=estado)
        if not valid:
            if error == ESTADO_CAMBIADO:
                return {"error": "state_changed", "detail": error}
            return {"error": error}

        payload: dict[str, Any] = {
            "background": True,
            "homeassistant": include_homeassistant,
        }
        if password:
            payload["password"] = password
        elif clave is not None:
            payload["password"] = clave
        if addons:
            try:
                payload["addons"] = json.loads(addons)
            except json.JSONDecodeError as exc:
                await complete_confirmation_token(
                    confirmation_token, success=False, error=str(exc)
                )
                return {"error": f"addons must be a JSON array: {exc}"}
        if folders:
            try:
                payload["folders"] = json.loads(folders)
            except json.JSONDecodeError as exc:
                await complete_confirmation_token(
                    confirmation_token, success=False, error=str(exc)
                )
                return {"error": f"folders must be a JSON array: {exc}"}

        try:
            # Único punto que tapa la clave y la contraseña (T061).
            data = await sin_secretos(ha_client.sv_request(
                "POST", f"/backups/{slug}/restore/partial",
                json_body=payload,
                timeout_seconds=_LONG_OP_TIMEOUT,
            ), password, clave)
            job_id = data.get("job_id") if isinstance(data, dict) else None
            if job_id:
                await _track_job(job_id, {"op": "restore_backup_partial", "slug": slug})
                result: dict[str, Any] = {
                    "job_id": job_id,
                    "status": "running",
                    "poll_with": "sv_get_job_status",
                }
            else:
                result = {"result": "ok"}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_restore_backup_partial_started", slug=slug, job_id=job_id,
                        password_source=fuente)
            return result
        except (HAConnectionError, aiohttp.ClientError) as exc:
            # `aiohttp.ClientError`: el Supervisor caído; sin capturarlo, el
            # error genérico del SDK y el token en `executing` hasta caducar.
            out = _error_restaurar(exc, fuente, payload)
            await complete_confirmation_token(confirmation_token, success=False,
                                              error=out["error"])
            return out
        finally:
            payload.pop("password", None)

    @mcp.tool()
    async def sv_get_job_status(job_id: str) -> object:
        """Consulta el estado de un job asíncrono del Supervisor.

        Útil para pollear el progreso de operaciones largas:
        install/update/uninstall de add-ons, create/restore backups.

        Args:
            job_id: Identificador del job (UUID hex).

        Returns:
            {"job_id": "...", "name": "...", "done": bool,
             "success": true|false|null, "errors": ["..."],
             "child_errors": [{"job": "...", "message": "..."}],
             "progress": 0-100, "stage": "...", "reference": "..."}
            `done` es True también cuando el job FALLA: mira `success`.
            success=true: terminado sin errores; false: terminado con
            errores; null: aún en curso.
            `success` es false si hay CUALQUIER entrada en `errors`: el
            Supervisor no distingue avisos de errores fatales.
            Los errores de los sub-jobs no suben al job en el Supervisor: van
            en `child_errors` y TAMBIÉN dan success=false aunque `errors`
            esté vacío (p. ej. una app que no se pudo guardar en un backup
            completo). `child_errors_truncated: true` si hubo más de los que
            se muestran o sub-jobs sin revisar; también da success=false.
            Con errores, `reference` puede apuntar a algo que sí se creó (un
            backup incompleto): compruébalo con sv_get_backup.
            Cuando success=true, reference puede contener el slug del backup
            creado u otro identificador del resultado.
        """
        if (err := _bad_job(job_id)):
            return err
        try:
            data = await ha_client.sv_request("GET", f"/jobs/{job_id}")
            if not isinstance(data, dict):
                return {"error": "unexpected_response"}

            # `done` no basta: el Supervisor lo pone a True también cuando el
            # job falla, y deja los motivos en `errors`. Sin mirarlos, un
            # backup fallido por falta de espacio se veía como correcto.
            done = data.get("done") is True
            errores = _job_errors(data)
            # Los errores de los sub-jobs se quedan en el sub-job y no suben
            # al padre: un backup completo con una app fallida terminaba con
            # `errors: []` y salía `success: true`, que mentía. Cuentan como
            # fallo, igual que cualquier error del propio job (spec 027,
            # D-1); un recorrido recortado también, porque no se miró todo.
            errores_hijos, hijos_recortados = child_job_errors(data)
            fallido = bool(errores or errores_hijos or hijos_recortados)
            success = (not fallido) if done else None

            result: dict[str, Any] = {
                "job_id": job_id,
                "name": data.get("name"),
                "done": data.get("done", False),
                "success": success,
                "errors": errores,
                "child_errors": errores_hijos,
                "progress": data.get("progress"),
                "stage": data.get("stage"),
                "reference": data.get("reference"),
                # Entero, pero redactado: los mensajes de los sub-jobs pueden
                # citar secretos, igual que los de `child_errors`.
                "child_jobs": redact_child_jobs(data.get("child_jobs")),
            }
            if hijos_recortados:
                result["child_errors_truncated"] = True

            # Si el job ha terminado, actualizar nuestro tracking local
            if data.get("done"):
                async with _jobs_lock:
                    jobs = _load_jobs_sync()
                    if job_id in jobs:
                        jobs[job_id]["status"] = "failed" if fallido else "done"
                        jobs[job_id]["reference"] = data.get("reference")
                        _write_jobs_sync(jobs)

            return result
        except HAConnectionError as exc:
            # El texto del error lleva el cuerpo de la respuesta del
            # Supervisor: se redacta como `errors` y `child_errors`, para que
            # ningún camino de esta tool devuelva su texto sin tapar
            # (revisión de la 027).
            return {"error": redact_secrets(str(exc))}

    @mcp.tool()
    async def sv_list_pending_jobs() -> object:
        """Lista los jobs asíncronos que Hermes ha iniciado en la última hora.

        Lee /data/pending_jobs.json, que persiste entre reinicios del add-on:
        la lista NO se limita a la sesión actual. El filtro es la antigüedad
        —menos de 1 h desde `started_at`—, no el estado, así que incluye
        también jobs ya terminados, cada uno con su `status`. Para el estado
        actual de uno concreto usa sv_get_job_status(job_id).

        Returns:
            {"jobs": [...], "count": N}
            Cada item: job_id, op, slug, started_at, status.
            `status` es `running`, `done` o `failed` (terminado con errores),
            según la última consulta con sv_get_job_status.
        """
        async with _jobs_lock:
            jobs = _load_jobs_sync()

        # Filtrar jobs muy viejos (>1h) para la respuesta
        cutoff = time.time() - 3600
        active = [
            {
                "job_id": jid,
                **{k: v for k, v in meta.items() if k != "status"},
                "status": meta.get("status", "running"),
            }
            for jid, meta in jobs.items()
            if meta.get("started_at", 0) > cutoff
        ]
        return {"jobs": active, "count": len(active)}
