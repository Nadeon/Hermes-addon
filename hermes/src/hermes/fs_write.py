"""Hermes — Infraestructura de escritura segura en /config.

Proporciona:
- safe_write_file          : escribe atómicamente preservando modo, encoding,
                             line endings y BOM del original.
- backup_before_write      : backup atómico en /data/backups/{normal,sensitive}/
                             antes de cualquier escritura o borrado.
- reserve_write_slot       : doble freno persistente (min_interval +
                             max_per_minute) que comprueba Y reserva la plaza
                             bajo un mismo asyncio.Lock.
- record_config_write,
  record_check_config_ok,
  check_restart_allowed_sync
                           : reloj lógico en /data/check_config_state.json que
                             impide reiniciar el core con cambios en /config sin
                             validar (sv_restart_core / sv_check_core_config).
- is_managed_path,
  MANAGED_PATHS_PATTERNS   : paths que NUNCA se pueden escribir por filesystem,
                             ni con confirmation_token.
- maybe_trigger_safety_backup
                           : backup FULL de HAOS previo a escribir, opt-in.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes.identifiers import validate_identifier
import structlog

import hermes.fs as _fs

logger = structlog.get_logger(__name__)

# ── Rutas de estado persistente ───────────────────────────────────────────────

DATA_DIR = Path("/data")
BACKUPS_NORMAL_DIR = DATA_DIR / "backups" / "normal"
BACKUPS_SENSITIVE_DIR = DATA_DIR / "backups" / "sensitive"
WRITE_RATE_LIMIT_PATH = DATA_DIR / "write_rate_limit.json"
CHECK_CONFIG_STATE_PATH = DATA_DIR / "check_config_state.json"

# ── Managed paths (nunca escribibles, ni con token) ───────────────────────────

MANAGED_PATHS_PATTERNS: list[str] = [
    ".storage/**",
]

MANAGED_PATH_ERROR = (
    "This path is managed internally by Hermes and Home Assistant. "
    "Use the corresponding WS-based tool (e.g. ha_update_* for entities) "
    "instead of direct filesystem write."
)


def is_managed_path(path: Path) -> bool:
    """Devuelve True si el path es un managed path (no escribible nunca)."""
    config_base = _fs.CONFIG_BASE
    try:
        rel = path.relative_to(config_base)
    except ValueError:
        return False
    import fnmatch
    rel_str = rel.as_posix()
    for pat in MANAGED_PATHS_PATTERNS:
        if fnmatch.fnmatch(rel_str, pat):
            return True
    # El directorio .storage en sí también está gestionado
    parts = rel.parts
    if parts and parts[0] == ".storage":
        return True
    return False


# ── Backup antes de escritura ─────────────────────────────────────────────────

async def backup_before_write(
    path: Path,
    *,
    file_backup_max_per_path: int = 20,
    file_backup_max_total_mb: int = 100,
) -> str | None:
    """Crea backup atómico de un fichero antes de modificarlo.

    - Backups de paths blacklisteados → /data/backups/sensitive/
    - Backups de paths normales → /data/backups/normal/
    - Los de /sensitive/ NUNCA se exponen en fs_list_file_backups.
    - Respeta límite por path y total.

    Returns:
        str: path del backup creado.
        None: el fichero no existía (no hay qué hacer backup).
    """
    if not path.exists():
        return None

    blacklisted, _ = _fs.check_blacklisted(path)
    subdir = BACKUPS_SENSITIVE_DIR if blacklisted else BACKUPS_NORMAL_DIR

    return await asyncio.to_thread(
        _backup_sync,
        path,
        subdir,
        file_backup_max_per_path,
        file_backup_max_total_mb,
    )


def _backup_sync(
    path: Path,
    backup_dir: Path,
    max_per_path: int,
    max_total_mb: int,
) -> str:
    """Síncrona: crea el backup y aplica rotación de límites."""
    backup_dir.mkdir(parents=True, exist_ok=True)

    config_base = _fs.CONFIG_BASE
    try:
        relative = path.relative_to(config_base)
    except ValueError:
        relative = Path(path.name)

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_rel = str(relative).replace("/", "__").replace("\\", "__")
    backup_name = f"{timestamp}_{safe_rel}"
    backup_path = backup_dir / backup_name

    shutil.copy2(str(path), str(backup_path))
    logger.info("fs_backup_created", source=str(path), backup=str(backup_path))

    # Rotación: limitar backups por path
    prefix = f"__{safe_rel}"
    same_file_backups = sorted(
        [f for f in backup_dir.iterdir() if f.name.endswith(f"_{safe_rel}")],
        key=lambda f: f.name,
    )
    while len(same_file_backups) > max_per_path:
        oldest = same_file_backups.pop(0)
        try:
            oldest.unlink(missing_ok=True)
            logger.info("fs_backup_rotated_per_path", removed=str(oldest))
        except OSError:
            pass

    # Rotación: limitar tamaño total
    max_bytes = max_total_mb * 1024 * 1024
    all_backups = sorted(
        [f for f in backup_dir.iterdir() if f.is_file()],
        key=lambda f: f.stat().st_mtime,
    )
    total_size = sum(f.stat().st_size for f in all_backups)
    while total_size > max_bytes and len(all_backups) > 1:
        oldest = all_backups.pop(0)
        try:
            removed_size = oldest.stat().st_size
            oldest.unlink(missing_ok=True)
            total_size -= removed_size
            logger.info("fs_backup_rotated_total_mb", removed=str(oldest))
        except OSError:
            pass

    return str(backup_path)


# ── safe_write_file ───────────────────────────────────────────────────────────

def safe_write_file(path: Path, content: str) -> None:
    """Escribe preservando modo, encoding, line endings, BOM y trailing newline.

    Escritura atómica: escribe a .mcp_tmp y luego os.replace().

    Para ficheros nuevos:
    - UTF-8 sin BOM
    - line endings \\n
    - trailing newline presente
    """
    # Detecta metadata del original (si existe)
    if path.exists():
        try:
            original_mode = path.stat().st_mode
        except OSError:
            original_mode = 0o644
        try:
            raw = path.read_bytes()
        except OSError:
            raw = b""
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        line_ending = "\r\n" if b"\r\n" in raw else "\n"
        had_trailing_newline = raw.endswith(b"\n") or raw.endswith(b"\r\n")
    else:
        original_mode = 0o644
        has_bom = False
        line_ending = "\n"
        had_trailing_newline = True

    # Normaliza content: \r\n → \n primero
    content = content.replace("\r\n", "\n")
    if line_ending == "\r\n":
        content = content.replace("\n", "\r\n")

    # Ajusta trailing newline
    if had_trailing_newline and not content.endswith(line_ending):
        content += line_ending
    elif not had_trailing_newline and content.endswith(line_ending):
        # Quitar trailing: restrip en el ending específico
        if line_ending == "\r\n":
            content = content.rstrip("\r").rstrip("\n")
        else:
            content = content.rstrip("\n")

    # Construye payload
    payload = (b"\xef\xbb\xbf" if has_bom else b"") + content.encode("utf-8")

    # Escritura atómica
    tmp_path = path.with_suffix(path.suffix + ".mcp_tmp")
    try:
        tmp_path.write_bytes(payload)
        try:
            tmp_path.chmod(stat.S_IMODE(original_mode))
        except OSError:
            pass
        os.replace(str(tmp_path), str(path))
    except BaseException:
        # Limpia fichero temporal si algo falla
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


# ── Rate Limit ────────────────────────────────────────────────────────────────

_rate_lock = asyncio.Lock()


class RateLimitError(Exception):
    """Excepción raised cuando se viola el rate limit de escritura."""

    def __init__(
        self,
        *,
        reason: str,
        min_interval_seconds: int,
        max_per_minute: int,
        next_allowed_at: str,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.min_interval_seconds = min_interval_seconds
        self.max_per_minute = max_per_minute
        self.next_allowed_at = next_allowed_at


def _load_rate_state() -> dict[str, Any]:
    try:
        data = json.loads(WRITE_RATE_LIMIT_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"timestamps": []}


def _save_rate_state(state: dict[str, Any]) -> None:
    WRITE_RATE_LIMIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = WRITE_RATE_LIMIT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(WRITE_RATE_LIMIT_PATH)


async def reserve_write_slot(
    min_interval_seconds: int,
    max_per_minute: int,
) -> None:
    """Comprueba el rate limit Y APUNTA la escritura, en la misma toma del lock.

    Las dos cosas van juntas a propósito. Comprobar primero y apuntar al
    terminar la escritura deja una ventana en la que otra llamada pasa el mismo
    control con el mismo estado: una carrera clásica de check-then-act. Y no es
    teórica, porque el cliente MCP lanza ráfagas de llamadas en paralelo como
    modo normal de trabajo: con la comprobación y el apunte separados, una
    ráfaga entera pasa el filtro y el límite deja de existir en la práctica.

    El freno es lo que impide que un bucle del cliente, o una instrucción
    envenenada colada en cualquier dato que el modelo lea, reescriba la
    configuración de Home Assistant decenas de veces seguidas. Reservar bajo el
    mismo lock hace que la segunda llamada concurrente ya vea la plaza ocupada.

    CONTRAPARTIDA, deliberada: si la escritura falla después de reservar, la
    plaza se gasta igualmente. Un control de seguridad debe fallar cerrado, y el
    coste de equivocarse por este lado es esperar el intervalo mínimo; el coste
    de equivocarse por el otro es el fallo que se acaba de describir.
    """
    async with _rate_lock:
        state = await asyncio.to_thread(_load_rate_state)
        now = time.time()
        timestamps: list[float] = [
            t for t in state.get("timestamps", []) if isinstance(t, (int, float))
        ]

        # Ventana deslizante de 60s
        window_start = now - 60.0
        recent = [t for t in timestamps if t > window_start]

        # 1. Mínimo interval
        if recent:
            last_write = max(recent)
            elapsed = now - last_write
            if elapsed < min_interval_seconds:
                wait_until = last_write + min_interval_seconds
                next_at = datetime.fromtimestamp(wait_until, tz=timezone.utc).isoformat()
                raise RateLimitError(
                    reason=(
                        f"Minimum write interval not met: "
                        f"{elapsed:.1f}s since last write, "
                        f"minimum is {min_interval_seconds}s"
                    ),
                    min_interval_seconds=min_interval_seconds,
                    max_per_minute=max_per_minute,
                    next_allowed_at=next_at,
                )

        # 2. Máximo por minuto
        if len(recent) >= max_per_minute:
            # Próxima escritura permitida: cuando el más antiguo salga de la ventana
            oldest = min(recent)
            wait_until = oldest + 60.0
            next_at = datetime.fromtimestamp(wait_until, tz=timezone.utc).isoformat()
            raise RateLimitError(
                reason=(
                    f"Write rate limit exceeded: "
                    f"{len(recent)} writes in last 60s, "
                    f"maximum is {max_per_minute}"
                ),
                min_interval_seconds=min_interval_seconds,
                max_per_minute=max_per_minute,
                next_allowed_at=next_at,
            )

        # Pasa: se apunta AQUÍ, sin soltar el lock, para que no quede ventana.
        timestamps = [t for t in timestamps if t > now - 120.0]
        timestamps.append(now)
        state["timestamps"] = timestamps
        await asyncio.to_thread(_save_rate_state, state)


# ── Check config state ────────────────────────────────────────────────────────

_config_state_lock = asyncio.Lock()

# Versión del formato de check_config_state.json.
#   v1: guardaba time.monotonic() en _last_write_ts/_last_check_ok_ts.
#   v2: reloj lógico (_seq) + marcas ISO de reloj de pared.
# Los estados en disco pueden ser de cualquiera de las dos: el lector
# (`check_restart_allowed_sync`) admite ambas y el escritor migra a v2.
_CHECK_STATE_VERSION = 2


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_seq(state: dict[str, Any]) -> int:
    """Devuelve el siguiente valor del reloj lógico y lo deja en el estado.

    Un contador entero persistido, no un reloj. Ordena eventos de forma exacta
    y es inmune a la resolución del reloj (15.6 ms en Windows), a los saltos de
    NTP y —sobre todo— al reinicio del proceso, que es lo que invalida un
    `time.monotonic()` guardado en disco: al arrancar de nuevo, el origen es
    otro y los valores anteriores dejan de ser comparables.
    """
    seq = state.get("_seq")
    if not isinstance(seq, int) or seq < 0:
        seq = 0
    seq += 1
    state["_seq"] = seq
    state["_v"] = _CHECK_STATE_VERSION
    # Limpiar el formato v1: esos floats eran monotonic y no significan nada
    # una vez reiniciado el proceso.
    state.pop("_last_write_ts", None)
    state.pop("_last_check_ok_ts", None)
    return seq


def _load_check_config_state() -> dict[str, Any]:
    try:
        data = json.loads(CHECK_CONFIG_STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_check_config_state(state: dict[str, Any]) -> None:
    CHECK_CONFIG_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHECK_CONFIG_STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CHECK_CONFIG_STATE_PATH)


async def record_config_write() -> None:
    """Registra una escritura en /config (avanza el reloj lógico)."""
    async with _config_state_lock:
        state = await asyncio.to_thread(_load_check_config_state)
        seq = _next_seq(state)
        now_iso = _now_iso()
        state["last_write_at"] = now_iso
        state["_last_write_seq"] = seq
        await asyncio.to_thread(_save_check_config_state, state)
        logger.debug("check_config_state_write_recorded", at=now_iso, seq=seq)


async def record_check_config_ok() -> None:
    """Registra un check de configuración correcto (avanza el reloj lógico)."""
    async with _config_state_lock:
        state = await asyncio.to_thread(_load_check_config_state)
        seq = _next_seq(state)
        now_iso = _now_iso()
        state["last_check_ok_at"] = now_iso
        state["_last_check_ok_seq"] = seq
        state["last_check_result"] = "ok"
        await asyncio.to_thread(_save_check_config_state, state)
        logger.debug("check_config_state_check_ok_recorded", at=now_iso, seq=seq)


def check_restart_allowed_sync() -> tuple[bool, str]:
    """Versión síncrona del check de restart (para supervisor.py).

    Bloquea el restart si hay escrituras en /config posteriores al último
    `sv_check_core_config` correcto. Devuelve (allowed, reason). Solo lee.

    Ordena los eventos con el reloj lógico `_seq` (v2). Para estados escritos
    por versiones anteriores (v1, que guardaban `time.monotonic()` — inservible
    tras un reinicio) cae a comparar las marcas ISO, que sí son de reloj de
    pared: formato fijo `%Y-%m-%dT%H:%M:%SZ` en UTC, así que el orden
    lexicográfico coincide con el cronológico. En caso de empate dentro del
    mismo segundo se bloquea (fail-closed): es recuperable llamando a
    `sv_check_core_config`, que reescribe el estado ya en v2.
    """
    if not CHECK_CONFIG_STATE_PATH.exists():
        return True, ""

    try:
        state = json.loads(CHECK_CONFIG_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True, ""
    if not isinstance(state, dict):
        return True, ""

    write_seq = state.get("_last_write_seq")
    check_seq = state.get("_last_check_ok_seq")

    if isinstance(write_seq, int) or isinstance(check_seq, int):
        # Formato v2: comparación exacta por reloj lógico.
        blocked = (write_seq if isinstance(write_seq, int) else 0) > (
            check_seq if isinstance(check_seq, int) else 0
        )
    else:
        # Formato v1 o anterior: ordenar por las marcas ISO de reloj de pared.
        write_iso = state.get("last_write_at")
        check_iso = state.get("last_check_ok_at")
        if not isinstance(write_iso, str) or not write_iso:
            return True, ""  # nunca se escribió
        # Sin check previo, o escritura igual/posterior al check → bloquear.
        blocked = not isinstance(check_iso, str) or not check_iso or write_iso >= check_iso

    if blocked:
        return False, (
            f"Pending /config changes have not been validated. "
            f"last_write_at={state.get('last_write_at')!r}, "
            f"last_check_ok_at={state.get('last_check_ok_at')!r}. "
            f"Call sv_check_core_config first, then retry."
        )
    return True, ""


# ── Safety backup trigger ─────────────────────────────────────────────────────

async def maybe_trigger_safety_backup(
    ha_client: Any,
    safety_backup_window_minutes: int,
    *,
    enabled: bool = False,
    ctx: Any = None,
) -> dict[str, Any] | None:
    """Dispara un safety backup (FULL de HAOS) antes de escribir en /config.

    DESACTIVADO por defecto (enabled=False): un backup completo automático
    antes de cada escritura genera varios GB y no es viable en producción. El
    backup por-fichero (backup_before_write) se mantiene SIEMPRE y cubre la
    reversibilidad de la escritura concreta. Actívalo con la opción del add-on
    `safety_backup_enabled` si quieres además un backup completo periódico.

    Returns:
        None si está desactivado, si no fue necesario, o si el backup completó.
        dict con "error" si el backup falló (la escritura debe abortarse).
    """
    if not enabled:
        return None

    from hermes.tools.backups import (
        _SAFETY_BACKUP_MIN_INTERVAL_SECONDS,
        _SAFETY_BACKUP_STATE_PATH,
        _MARCA,
        _leer_marca,
        _load_safety_state,
        _save_safety_state,
    )

    now = time.time()
    state = _load_safety_state()
    last_completed = _leer_marca(state)

    window_seconds = safety_backup_window_minutes * 60
    elapsed = now - last_completed

    # Barrera dura: nunca menos de 60s entre safety backups
    if elapsed < _SAFETY_BACKUP_MIN_INTERVAL_SECONDS:
        logger.debug(
            "safety_backup_skipped_hard_limit",
            elapsed=elapsed,
            min_interval=_SAFETY_BACKUP_MIN_INTERVAL_SECONDS,
        )
        return None

    # Comprobar si ha pasado el window
    if elapsed < window_seconds:
        return None

    # Disparar safety backup
    logger.info(
        "safety_backup_auto_trigger",
        elapsed_minutes=elapsed / 60,
        window_minutes=safety_backup_window_minutes,
    )

    timestamp_str = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_name = f"hermes-safety-{timestamp_str}"

    try:
        resp = await ha_client.sv_request(
            "POST",
            "/backups/new/full",
            json_body={"name": backup_name, "background": True},
            timeout_seconds=30.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("safety_backup_trigger_failed", error=str(exc))
        return {"error": f"safety_backup_failed: {exc}"}

    if not isinstance(resp, dict):
        return {"error": "safety_backup_unexpected_response"}

    job_id = resp.get("job_id")
    if not job_id:
        # Respuesta síncrona sin job_id (puede tener slug) — backup ya completado
        logger.info("safety_backup_auto_done_sync", name=backup_name)
        _save_safety_state({
            _MARCA: time.time(),
            "last_backup_name": backup_name,
        })
        return None

    # Pollear hasta que el job esté done
    import asyncio as _asyncio
    deadline = time.time() + 300.0  # 5 min max
    poll_interval = 15.0

    while time.time() < deadline:
        if ctx is not None:
            try:
                ctx.report_progress(
                    f"Waiting for safety backup to complete (job {job_id})...",
                    0,
                )
            except Exception:  # noqa: BLE001
                pass

        await _asyncio.sleep(poll_interval)

        try:
            validate_identifier(str(job_id), field="job_id")
            job_data = await ha_client.sv_request("GET", f"/jobs/{job_id}/info")
        except Exception as exc:  # noqa: BLE001
            logger.warning("safety_backup_poll_error", job_id=job_id, error=str(exc))
            continue

        if not isinstance(job_data, dict):
            continue

        done = job_data.get("done", False)
        job_state = job_data.get("state", "")

        if done or job_state in ("finish", "done"):
            logger.info("safety_backup_auto_done", job_id=job_id, name=backup_name)
            _save_safety_state({
                _MARCA: time.time(),
                "last_backup_name": backup_name,
                "job_id": job_id,
            })
            return None

        if job_state in ("fail", "error", "failed"):
            error_msg = job_data.get("error", "unknown")
            logger.error("safety_backup_job_failed", job_id=job_id, error=error_msg)
            return {"error": f"safety_backup_job_failed: {error_msg}"}

    return {"error": "safety_backup_timeout: job did not complete within 5 minutes"}
