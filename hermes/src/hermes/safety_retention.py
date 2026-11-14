"""Retención de los safety backups de Hermes (opción `safety_backup_keep`).

Cada safety backup es un backup COMPLETO de varios GB. Con
`safety_backup_enabled` se crea uno cada `safety_backup_window_minutes` y,
sin poda, acaban llenando el disco de HAOS. La retención propia de Home
Assistant no los toca: solo poda los backups que HA crea con sus ajustes
automáticos.

Lo delicado es decidir QUÉ backups son de Hermes. El nombre no sirve:
cualquiera (el usuario, otra integración, un script) puede crear un backup
llamado `hermes-safety-…`, y borrarlo sería destruir un backup ajeno. Por eso
Hermes lleva su propia anotación en `/data/safety_backups.json`: cada
lanzamiento se apunta ahí y solo cuenta cuando su slug se ha CONFIRMADO por
una vía inequívoca (respuesta del Supervisor, referencia del job o, en último
término, el único backup con ese nombre y fecha a menos de 10 minutos). Ante
cualquier duda —anotación ilegible, listado raro, incoherencias— no se borra
nada (fail-closed).

Este módulo nunca lanza excepciones hacia quien lo llama: la retención va
detrás de la escritura en `/config` y no puede bloquearla.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from hermes.identifiers import InvalidIdentifier, validate_identifier, validate_slug

logger = structlog.get_logger(__name__)

# `None` = `<DATA_DIR>/safety_backups.json`, con el `DATA_DIR` de `fs_write`
# leído en cada uso (en producción, `/data`). Así la suite, que redirige
# `DATA_DIR` a un temporal, no escribe nunca en el `/data` real aunque un test
# dispare un safety backup sin saber nada de la anotación.
LEDGER_PATH: Path | None = None

# Formatos EXACTOS que genera Hermes: el automático (`fs_write`) y el de la
# tool `sv_create_safety_backup`. Cualquier otro nombre no se toca, aunque
# empiece por `hermes-safety-` (p. ej. `hermes-safety-manual`).
_NOMBRE_RE = re.compile(r"hermes-safety-(?:\d{8}T\d{6}Z|\d{8}-\d{6})")

# Tope de borrados por ejecución: si algo se descontrola (fechas absurdas, un
# fallo de lógica), el daño queda acotado a unos pocos backups.
_MAX_BORRADOS = 5
# Ventana para confirmar por nombre y fecha cuando no hay referencia del job.
_VENTANA_NOMBRE_S = 600
# Una entrada sin confirmar en una semana ya no se confirmará: sale de la
# anotación y su backup queda fuera de la retención para siempre.
_CADUCIDAD_SIN_CONFIRMAR_S = 7 * 86400
_MAX_ENTRADAS = 100
# Cuántos jobs se consultan como mucho en una ejecución para confirmar
# entradas pendientes; el resto espera a la siguiente.
_MAX_CONSULTAS_JOB = 10

_LOCK: tuple[Any, asyncio.Lock] | None = None


def _lock() -> asyncio.Lock:
    """Lock de la anotación, recreado si cambia el bucle de eventos.

    Serializa leer-modificar-guardar: el camino automático y la tool pueden
    anotar a la vez, y sin lock uno pisaría la entrada del otro. Un
    `asyncio.Lock` con espera queda atado a su bucle; en producción hay uno
    solo, pero se recrea si cambia para no romper.
    """
    global _LOCK
    bucle = asyncio.get_running_loop()
    if _LOCK is None or _LOCK[0] is not bucle:
        _LOCK = (bucle, asyncio.Lock())
    return _LOCK[1]


def _ruta() -> Path:
    if LEDGER_PATH is not None:
        return LEDGER_PATH
    from hermes import fs_write

    return fs_write.DATA_DIR / "safety_backups.json"


def _cargar() -> tuple[list[dict[str, Any]], bool]:
    """Lee la anotación. Devuelve (entradas, legible).

    Un fichero corrupto se trata como anotación vacía —sin candidatos no se
    borra nada— y NO se reescribe al leer: podría ser un fallo pasajero y
    reescribirlo perdería lo que hubiera. Solo un lanzamiento nuevo lo rehace.
    """
    ruta = _ruta()
    try:
        texto = ruta.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], True
    except OSError as exc:
        logger.warning("safety_backup_ledger_unreadable", error=str(exc))
        return [], False
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError:
        logger.warning("safety_backup_ledger_unreadable", error="invalid_json")
        return [], False
    entradas = datos.get("entries") if isinstance(datos, dict) else None
    if not isinstance(entradas, list) or not all(isinstance(e, dict) for e in entradas):
        logger.warning("safety_backup_ledger_unreadable", error="unexpected_shape")
        return [], False
    return entradas, True


def _recortar(entradas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deja como mucho `_MAX_ENTRADAS`, quitando antes las no confirmadas.

    Una no confirmada nunca se poda, así que perderla no cuesta nada; una
    confirmada perdida es un backup que ya no se podará solo.
    """
    sobran = len(entradas) - _MAX_ENTRADAS
    if sobran <= 0:
        return entradas
    orden = sorted(
        range(len(entradas)),
        key=lambda i: (entradas[i].get("slug") is not None,
                       _numero(entradas[i].get("launched_at"))),
    )
    fuera = set(orden[:sobran])
    return [e for i, e in enumerate(entradas) if i not in fuera]


def _guardar(entradas: list[dict[str, Any]]) -> None:
    """Escritura atómica (`.tmp` + `replace`), como el estado del safety backup."""
    ruta = _ruta()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_text(
        json.dumps({"version": 1, "entries": _recortar(entradas)}, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(ruta)


def _numero(valor: Any) -> float:
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return float(valor)
    return 0.0


def _slug_valido(valor: Any) -> str | None:
    """El slug solo vale si se puede interpolar sin riesgo en `/backups/{slug}`."""
    if not isinstance(valor, str):
        return None
    try:
        return validate_slug(valor, field="slug")
    except InvalidIdentifier:
        return None


def _job_valido(valor: Any) -> str | None:
    if not isinstance(valor, str):
        return None
    try:
        return validate_identifier(valor, field="job_id")
    except InvalidIdentifier:
        return None


async def record_launch(name: str, job_id: str | None, origin: str,
                        slug: str | None = None) -> None:
    """Anota un safety backup recién lanzado por Hermes.

    Si el Supervisor ya devolvió el slug (respuesta síncrona), la entrada
    queda confirmada en el acto. Si no, se confirma más tarde.
    """
    slug_ok = _slug_valido(slug)
    entrada = {
        "name": str(name),
        "job_id": _job_valido(job_id),
        "launched_at": time.time(),
        "origin": origin,
        "slug": slug_ok,
        "confirmed_by": "sync_response" if slug_ok else None,
    }
    async with _lock():
        entradas, _legible = _cargar()
        entradas.append(entrada)
        _guardar(entradas)


def _clasificar_job(job_data: Any) -> tuple[str, str | None]:
    """("ok", slug), ("fallo", None) o ("indeterminado", None)."""
    from hermes.tools.backups import _job_errors

    if not isinstance(job_data, dict) or job_data.get("done") is not True:
        return "indeterminado", None
    if not isinstance(job_data.get("errors"), list) or _job_errors(job_data):
        return "fallo", None
    slug = _slug_valido(job_data.get("reference"))
    return ("ok", slug) if slug else ("indeterminado", None)


async def confirm_from_job(job_id: str, job_data: Any) -> None:
    """Confirma (o descarta) la entrada de un job con su respuesta de `/jobs/{id}`.

    Solo confirma con `done is True`, `errors` vacío y `reference` de texto;
    un job terminado con errores no dejó un backup válido y su entrada sale.
    """
    resultado, slug = _clasificar_job(job_data)
    if resultado == "indeterminado":
        return
    async with _lock():
        entradas, legible = _cargar()
        if not legible:
            return
        nuevas = []
        for e in entradas:
            if e.get("job_id") == job_id and e.get("slug") is None:
                if resultado == "fallo":
                    continue
                e = {**e, "slug": slug, "confirmed_by": "job_reference"}
            nuevas.append(e)
        _guardar(nuevas)


def _fecha(valor: Any) -> float | None:
    """Fecha ISO del Supervisor a epoch; None si no se puede leer sin adivinar.

    Una fecha sin zona horaria no se interpreta: suponerle una podría ordenar
    mal los backups y borrar el que no toca.
    """
    if not isinstance(valor, str):
        return None
    try:
        fecha = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
    if fecha.tzinfo is None:
        return None
    return fecha.timestamp()


def _una_ubicacion(backup: dict[str, Any]) -> bool:
    """¿Está el backup en una sola ubicación?

    Si alguien lo copió a un NAS, ese backup ya no es «el safety backup
    efímero de Hermes»: es una copia que el usuario quiso conservar.
    """
    if "locations" in backup:
        locs = backup["locations"]
        return isinstance(locs, list) and len(locs) <= 1
    return not isinstance(backup.get("location"), (list, dict))


def _motivo_exclusion(entrada: dict[str, Any], backup: dict[str, Any]) -> str | None:
    """Motivo por el que un backup confirmado NO es candidato, o None si lo es."""
    nombre = entrada.get("name")
    if backup.get("name") != nombre:
        return "name_mismatch"
    if not isinstance(nombre, str) or not _NOMBRE_RE.fullmatch(nombre):
        return "name_format"
    if backup.get("type") != "full":
        return "not_full"
    if backup.get("protected") is not False:
        return "protected"
    if not _una_ubicacion(backup):
        return "multiple_locations"
    if _fecha(backup.get("date")) is None:
        return "unreadable_date"
    return None


async def _confirmar_pendientes(
    ha_client: Any, entradas: list[dict[str, Any]], backups: list[dict[str, Any]],
    ahora: float,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Intenta confirmar las entradas sin slug. Devuelve (entradas, descartadas).

    Primero por la referencia del job; si el job ya no existe o no la trae,
    por el ÚNICO backup con exactamente ese nombre y fecha cercana al
    lanzamiento. Dos candidatos, o uno con la fecha lejos, no confirman nada.
    """
    resultado: list[dict[str, Any]] = []
    descartadas: set[str] = set()
    consultas = 0
    for e in entradas:
        if e.get("slug") is not None:
            resultado.append(e)
            continue
        job_id = _job_valido(e.get("job_id"))
        if job_id and consultas < _MAX_CONSULTAS_JOB:
            consultas += 1
            try:
                job = await ha_client.sv_request("GET", f"/jobs/{job_id}")
            except Exception:  # noqa: BLE001 — 404 o caída: se prueba por nombre
                job = None
            estado, slug = _clasificar_job(job)
            if estado == "fallo":
                descartadas.add(str(e.get("name")))
                continue
            if estado == "ok":
                resultado.append({**e, "slug": slug, "confirmed_by": "job_reference"})
                continue
        mismos = [b for b in backups if b.get("name") == e.get("name")]
        if len(mismos) == 1:
            fecha = _fecha(mismos[0].get("date"))
            slug = _slug_valido(mismos[0].get("slug"))
            lanzado = _numero(e.get("launched_at"))
            if fecha is not None and slug and abs(fecha - lanzado) <= _VENTANA_NOMBRE_S:
                resultado.append({**e, "slug": slug, "confirmed_by": "unique_name_date"})
                continue
        if ahora - _numero(e.get("launched_at")) > _CADUCIDAD_SIN_CONFIRMAR_S:
            descartadas.add(str(e.get("name")))
            continue
        resultado.append(e)
    return resultado, descartadas


async def apply_retention(ha_client: Any, keep: int, *,
                          recien_creado: str | None = None) -> dict[str, Any]:
    """Borra los safety backups de Hermes que sobran respecto a `keep`.

    Se llama tras cada safety backup AUTOMÁTICO correcto. `recien_creado` es
    el nombre del backup que acaba de terminar: se conserva siempre, aunque
    su fecha lo pusiera entre los más antiguos.

    Nunca lanza: cualquier fallo se registra y se devuelve en el resumen.
    """
    resumen: dict[str, Any] = {"deleted": [], "kept": [], "excluded": []}
    try:
        return await _aplicar(ha_client, keep, recien_creado, resumen)
    except Exception as exc:  # noqa: BLE001 — la escritura en curso no puede caer por esto
        logger.error("safety_backup_retention_error", error=str(exc))
        resumen["error"] = str(exc)
        return resumen


async def _aplicar(ha_client: Any, keep: int, recien_creado: str | None,
                   resumen: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(keep, int) or isinstance(keep, bool) or keep <= 0:
        return resumen

    async with _lock():
        entradas, legible = _cargar()
    if not legible:
        resumen["skipped"] = "ledger_unreadable"
        logger.warning("safety_backup_retention_skipped", reason="ledger_unreadable")
        return resumen
    if not entradas:
        return resumen

    try:
        datos = await ha_client.sv_request("GET", "/backups")
    except Exception as exc:  # noqa: BLE001
        resumen["skipped"] = "backups_unreadable"
        logger.warning("safety_backup_retention_skipped", reason="backups_unreadable",
                       error=str(exc))
        return resumen
    backups = datos.get("backups") if isinstance(datos, dict) else None
    if not isinstance(backups, list) or not all(isinstance(b, dict) for b in backups):
        # Un listado con forma rara no dice qué existe: ni se poda ni se
        # limpia la anotación (sería tomar «no lo veo» por «ya no existe»).
        resumen["skipped"] = "backups_unreadable"
        logger.warning("safety_backup_retention_skipped", reason="backups_unreadable")
        return resumen

    ahora = time.time()
    entradas, descartadas = await _confirmar_pendientes(ha_client, entradas, backups, ahora)

    por_slug: dict[str, list[dict[str, Any]]] = {}
    for b in backups:
        if isinstance(b.get("slug"), str):
            por_slug.setdefault(b["slug"], []).append(b)

    candidatos: list[tuple[float, float, dict[str, Any]]] = []
    for e in entradas:
        slug = e.get("slug")
        if slug is None:
            continue
        presentes = por_slug.get(slug, [])
        if not presentes:
            # Ya no existe (lo borró el usuario o se podó): fuera de la anotación.
            descartadas.add(str(e.get("name")))
            continue
        if len(presentes) > 1:
            resumen["excluded"].append({"name": e.get("name"), "reason": "duplicated_slug"})
            continue
        motivo = _motivo_exclusion(e, presentes[0])
        if motivo:
            resumen["excluded"].append({"name": e.get("name"), "reason": motivo})
            continue
        fecha = _fecha(presentes[0].get("date")) or 0.0
        candidatos.append((fecha, _numero(e.get("launched_at")), e))

    # Del más reciente al más antiguo; el recién creado va delante siempre.
    candidatos.sort(key=lambda c: (c[2].get("name") == recien_creado, c[0], c[1]),
                    reverse=True)
    conservar = candidatos[:keep]
    sobrantes = list(reversed(candidatos[keep:]))[:_MAX_BORRADOS]
    resumen["kept"] = [c[2].get("name") for c in conservar]

    borrados: set[str] = set()
    for _fecha_c, _lanzado, e in sobrantes:
        slug = _slug_valido(e.get("slug"))
        if slug is None or e.get("name") == recien_creado:
            break
        try:
            await ha_client.sv_request("DELETE", f"/backups/{slug}")
        except Exception as exc:  # noqa: BLE001 — se para en el primer fallo
            resumen["failed"] = {"name": e.get("name"), "error": str(exc)}
            logger.warning("safety_backup_retention_delete_failed",
                           name=e.get("name"), error=str(exc))
            break
        borrados.add(slug)
        resumen["deleted"].append(e.get("name"))

    # Se vuelve a leer con el lock: mientras se hablaba con el Supervisor otro
    # camino pudo anotar un lanzamiento, y guardar la copia vieja lo perdería.
    confirmadas = {e.get("name"): e for e in entradas}
    async with _lock():
        actuales, legible = _cargar()
        if legible:
            nuevas = []
            for e in actuales:
                nombre = e.get("name")
                if nombre in descartadas or (e.get("slug") in borrados
                                             and e.get("slug") is not None):
                    continue
                previa = confirmadas.get(nombre)
                if (e.get("slug") is None and previa is not None
                        and previa.get("slug") is not None):
                    e = previa
                nuevas.append(e)
            _guardar(nuevas)

    logger.info("safety_backup_retention_done", deleted=resumen["deleted"],
                kept=resumen["kept"], excluded=resumen["excluded"], keep=keep)
    return resumen
