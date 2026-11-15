"""Hermes — preferencias del panel de energía (spec 020, CAP-054).

Dos tools, familia `energy`:

- `ha_get_energy_prefs`: lee las preferencias (`energy/get_prefs`). Solo lee.
- `ha_update_energy_prefs`: las guarda (`energy/save_prefs`) en dos pasos.

POR QUÉ TRES LISTAS Y NO UN DOCUMENTO (research R-5)
----------------------------------------------------
`EnergyManager.async_update` de HA reemplaza ENTERA cada lista de nivel
superior que recibe (`energy_sources`, `device_consumption`,
`device_consumption_water`) y conserva las que no llegan. La firma de la tool
dice esa misma semántica: tres argumentos opcionales; el que llega reemplaza
su lista, el que no, se conserva. Un `prefs` único escondería que mandar solo
los dispositivos no borra las fuentes, y que mandar una lista con un elemento
borra todos los demás de esa lista.

POR QUÉ LA VISTA PREVIA LEE ANTES Y EL TOKEN ATA LO LEÍDO (decisión del supervisor)
-------------------------------------------------------------------------------
Reemplazar una lista entera quita lo que no se reenvía. La vista previa lee
las preferencias actuales y enseña, por cada lista que llega, cómo está y
cómo quedará (`current` y `new`), qué entra, qué sale y qué cambia, y avisa
si se quitan fuentes o dispositivos. El token ata el documento que se
enviará (las tres listas, `None` las que no llegan) y el `estado`: las
preferencias leídas. Si alguien guarda desde la interfaz entre la vista
previa y la confirmación, la confirmación vuelve a leer, el estado no casa y
`resolve_confirmation_token` responde `ESTADO_CAMBIADO` sin enviar nada.
Sin preferencias guardadas el estado es `{"configured": false}`, nunca
`None` (con `None` el token no ataría nada). Si las preferencias no se pueden
leer, falla cerrado: sin token en la vista previa, y sin ejecutar (el token
sigue pendiente) en la confirmación.

`irreversible: false`: lo anterior se puede volver a guardar con esta misma
tool, y la vista previa lo trae en `current`.

LO QUE VALIDA HERMES Y LO QUE VALIDA HA
---------------------------------------
Hermes comprueba la forma básica (listas de objetos, `type` conocido en las
fuentes, `stat_consumption` en los dispositivos) y rechaza un valor tapado
(`***REDACTED***`) reenviado tal cual desde una lectura: guardarlo pisaría el
dato real. El esquema completo (límites por tipo, estadísticas de la red que
no se repiten…) lo valida HA al guardar: `invalid_format` →
`ha_command_failed` redactado, y no cambia nada. HA NO comprueba que las
estadísticas nombradas existan (el panel admite estadísticas que aún no
tienen datos): la vista previa las busca con
`recorder/get_statistics_metadata` y avisa en `warnings`, sin rechazar.

TAMAÑO
------
Las preferencias son un documento de configuración: recortar una de sus
listas para que quepa en la respuesta daría un documento falso que, guardado
de vuelta, borraría lo recortado. Si no caben, `response_too_large` (la red
central recortaría la lista más grande).

Log: nombre de la tool, paso, resultado y recuentos por lista. Nunca
estadísticas, nombres ni el documento (FR-018): dicen qué hay en la casa.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    ESTADO_CAMBIADO,
    REDACTED_MARKER,
    complete_confirmation_token,
    create_confirmation_token,
    redact_secrets,
    resolve_confirmation_token,
)
from hermes.tools._common import requires_ready, tam_json
from hermes.tools.system_status import _invalido, _limpio

logger = structlog.get_logger(__name__)

_LISTAS = ("energy_sources", "device_consumption", "device_consumption_water")
# Los seis `type` de `ENERGY_SOURCE_SCHEMA` en HA 2026.11 (`energy/data.py`).
_TIPOS_FUENTE = frozenset({"grid", "solar", "battery", "gas", "water", "home"})
# Tope de elementos por lista: un panel real tiene unas pocas fuentes y como
# mucho decenas de dispositivos. Es solo una cota contra documentos absurdos.
_ELEMENTOS_MAX = 500
# Tope de estadísticas que la vista previa comprueba (una sola lectura).
_ESTADISTICAS_MAX = 200
_ID_MAX = 255
# Campos que identifican un elemento en las diferencias: su tipo y sus
# estadísticas de energía (los nombres son opcionales y no identifican).
_IDENTIDAD = ("type", "stat_energy_from", "stat_energy_to", "stat_consumption")

_NO_CARGADA = (
    "The energy integration is not loaded in Home Assistant (it is part of "
    "default_config). Add `energy:` (or `default_config:`) to "
    "configuration.yaml to enable the energy dashboard."
)
_UNDO = (
    "Save the `current` lists of this preview back with ha_update_energy_prefs "
    "to restore them."
)


# ── Ayudantes ────────────────────────────────────────────────────────────────

def _error_ha(tool: str, exc: HAConnectionError) -> dict[str, Any]:
    """Traduce un error de un comando `energy/*` (FR-019)."""
    detalle = redact_secrets(str(exc))
    if exc.code is None:
        # Sin código de HA es un fallo de conexión: el error de siempre.
        logger.info(f"{tool}_failed", error="connection")
        return {"error": detalle}
    if exc.code == "unknown_command":
        logger.info(f"{tool}_failed", error="energy_not_loaded")
        return {"error": "energy_not_loaded", "detail": _NO_CARGADA, "ha_code": exc.code}
    from hermes.command_table import TABLE_HA_CORE
    logger.info(f"{tool}_failed", error=exc.code)
    return {"error": "ha_command_failed", "detail": detalle, "ha_code": exc.code,
            "table_ha_core": TABLE_HA_CORE}


async def _leer_prefs(ha_client: HAClient) -> dict[str, Any]:
    """Preferencias actuales: `{"configured": False}` o `{"configured": True,
    "prefs": <lo que dio HA>}`. Es el `estado` atado al token.

    `not_found` («No prefs») es que nunca se guardaron, no un error. Lanza
    `HAConnectionError` para cualquier otro fallo, y también si la respuesta
    no es un objeto: sin estado fiable no hay token (fail-closed).
    """
    try:
        bruto = await ha_client.ws_send({"type": "energy/get_prefs"})
    except HAConnectionError as exc:
        if exc.code == "not_found":
            return {"configured": False}
        raise
    if not isinstance(bruto, Mapping):
        raise HAConnectionError("energy/get_prefs returned an unexpected shape",
                                code="unexpected_response")
    return {"configured": True, "prefs": dict(bruto)}


def _listas(estado: Mapping[str, Any]) -> dict[str, list[Any]]:
    """Las tres listas del estado; las que falten (o no sean listas), vacías.

    HA no guarda `device_consumption_water` en preferencias antiguas
    (`NotRequired` en `EnergyPreferences`).
    """
    prefs = estado.get("prefs") or {}
    return {n: list(prefs.get(n)) if isinstance(prefs.get(n), list) else [] for n in _LISTAS}


def _tiene_tapado(valor: Any) -> bool:
    if isinstance(valor, str):
        return REDACTED_MARKER in valor
    if isinstance(valor, Mapping):
        return any(_tiene_tapado(v) for v in valor.values())
    if isinstance(valor, list):
        return any(_tiene_tapado(v) for v in valor)
    return False


def _validar(nombre: str, lista: Any) -> str:
    """Detalle del problema de forma de `lista`, o "" si vale."""
    if not isinstance(lista, list) or len(lista) > _ELEMENTOS_MAX:
        return f"{nombre} must be a list of up to {_ELEMENTOS_MAX} objects."
    for n, elemento in enumerate(lista):
        if not isinstance(elemento, Mapping):
            return f"{nombre}[{n}] must be an object."
        if nombre == "energy_sources":
            if elemento.get("type") not in _TIPOS_FUENTE:
                return (f"{nombre}[{n}].type must be one of: "
                        f"{', '.join(sorted(_TIPOS_FUENTE))}.")
        else:
            stat = elemento.get("stat_consumption")
            if not isinstance(stat, str) or not 0 < len(stat) <= _ID_MAX:
                return f"{nombre}[{n}].stat_consumption is required (a statistic id)."
    if _tiene_tapado(lista):
        return (f"{nombre} contains {REDACTED_MARKER}, a value Hermes hid when reading. "
                "Saving it would overwrite the real value: pass the real value or "
                "leave that field out.")
    return ""


def _resumen(elemento: Mapping[str, Any]) -> dict[str, Any]:
    """Lo que la vista previa enseña de un elemento: su `type` y sus `stat_*`."""
    return {k: v for k, v in elemento.items()
            if (k == "type" or k.startswith("stat_")) and v is not None}


def _clave(elemento: Mapping[str, Any]) -> str:
    """Identidad de un elemento: tipo y estadísticas de energía; si no tiene
    ninguna (una red solo con potencia), también `stat_rate`."""
    partes = {k: elemento.get(k) for k in _IDENTIDAD if elemento.get(k) is not None}
    if not any(k != "type" for k in partes):
        partes["stat_rate"] = elemento.get("stat_rate")
    return repr(sorted(partes.items()))


def _diferencias(antes: list[Any], despues: list[Any]) -> dict[str, Any]:
    """Recuentos y elementos que entran, salen y cambian entre dos listas.

    Se emparejan por identidad (`_clave`) y en orden; con la misma identidad y
    otro contenido (un precio, la potencia, el nombre), cuenta como cambiado.
    """
    pendientes: dict[str, list[Mapping[str, Any]]] = {}
    for e in antes:
        if isinstance(e, Mapping):
            pendientes.setdefault(_clave(e), []).append(e)
    anadidos, cambiados = [], []
    for e in despues:
        previos = pendientes.get(_clave(e))
        if not previos:
            anadidos.append(_resumen(e))
            continue
        previo = previos.pop(0)
        if dict(previo) != dict(e):
            cambiados.append(_resumen(e))
    quitados = [_resumen(e) for grupo in pendientes.values() for e in grupo]
    return {"before_count": len(antes), "after_count": len(despues),
            "added": anadidos, "removed": quitados, "changed": cambiados}


def _estadisticas(valor: Any, out: set[str]) -> None:
    """Ids de estadística nombrados en un documento (`stat_*` e
    `included_in_stat`, también dentro de `power_config`)."""
    if isinstance(valor, Mapping):
        for k, v in valor.items():
            if (isinstance(v, str) and 0 < len(v) <= _ID_MAX
                    and (str(k).startswith("stat_") or k == "included_in_stat")):
                out.add(v)
            else:
                _estadisticas(v, out)
    elif isinstance(valor, list):
        for v in valor:
            _estadisticas(v, out)


async def _avisos_de_estadisticas(ha_client: HAClient,
                                  nuevas: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Estadísticas nombradas que el recorder no conoce (HA no lo comprueba).

    Es un aviso, no un rechazo: el panel admite estadísticas que todavía no
    tienen datos. Si no se puede comprobar (recorder no cargado, error), se
    dice en vez de callarlo.
    """
    ids: set[str] = set()
    _estadisticas(list(nuevas.values()), ids)
    if not ids:
        return []
    pedidos = sorted(ids)[:_ESTADISTICAS_MAX]
    try:
        bruto = await ha_client.ws_send(
            {"type": "recorder/get_statistics_metadata", "statistic_ids": pedidos})
    except HAConnectionError as exc:
        return [{"problem": "statistics_not_checked", "ha_code": exc.code,
                 "detail": ("Could not check that the named statistics exist (is the "
                            "recorder loaded?). Home Assistant does not check it either.")}]
    conocidas = {m.get("statistic_id") for m in bruto
                 if isinstance(m, Mapping)} if isinstance(bruto, list) else set()
    avisos = [{"statistic_id": s, "problem": "unknown_statistic"}
              for s in pedidos if s not in conocidas]
    if len(ids) > _ESTADISTICAS_MAX:
        avisos.append({"problem": "statistics_not_checked",
                       "detail": f"Only the first {_ESTADISTICAS_MAX} statistics were checked."})
    return avisos


# ── Registro ─────────────────────────────────────────────────────────────────

def register(mcp: Any, ha_client: HAClient, *, response_max_bytes: int) -> None:
    """Registra las dos tools de la familia `energy`."""
    ready = requires_ready(ha_client)

    def demasiado_grande(tool: str, tam: int) -> dict[str, Any]:
        logger.info(f"{tool}_failed", error="response_too_large")
        return {"error": "response_too_large",
                "detail": (f"The energy preferences ({tam} bytes) exceed "
                           f"response_max_bytes ({response_max_bytes}) and a "
                           "configuration document cannot be cut without "
                           "misrepresenting it.")}

    def documento(estado: Mapping[str, Any]) -> dict[str, Any]:
        return _limpio({"configured": bool(estado.get("configured")), **_listas(estado)})

    @mcp.tool()
    @ready
    async def ha_get_energy_prefs() -> object:
        """Read the energy dashboard configuration: energy sources (grid, solar, battery, gas, water, home), individual electricity devices and water devices.

        Read only. Returns the three lists as Home Assistant stores them, so
        you can edit one and save it whole with ha_update_energy_prefs.
        `configured: false` (and empty lists) when the energy dashboard was
        never set up.

        Returns:
            {configured, energy_sources, device_consumption,
            device_consumption_water}. Errors: energy_not_loaded,
            response_too_large, ha_command_failed.
        """
        tool = "ha_get_energy_prefs"
        try:
            estado = await _leer_prefs(ha_client)
        except HAConnectionError as exc:
            return _error_ha(tool, exc)
        out = documento(estado)
        tam = tam_json(out)
        if tam > response_max_bytes:
            return demasiado_grande(tool, tam)
        logger.info(f"{tool}_ok", configured=out["configured"],
                    **{n: len(out[n]) for n in _LISTAS})
        return out

    @mcp.tool()
    @ready
    async def ha_update_energy_prefs(
        energy_sources: list | None = None,
        device_consumption: list | None = None,
        device_consumption_water: list | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Save the energy dashboard configuration. Each list you pass REPLACES that whole list in Home Assistant; lists you do not pass are kept.

        Read the current lists with ha_get_energy_prefs, edit them and pass
        them complete: an element you leave out of a list you pass is
        removed. Two steps: without confirmation_token it returns a preview
        (per list: current and new content, added, removed and changed
        elements, warnings for removals and for statistics Home Assistant
        does not know) and changes nothing; repeat the same call with
        confirmation_token to save. If the preferences change in between
        (e.g. saved from the UI), the confirmation is refused. Hermes checks
        the basic shape; Home Assistant validates the full schema when saving.

        Args:
            energy_sources: Energy sources, each an object with `type` (grid,
                solar, battery, gas, water, home) and its statistics, e.g.
                {"type": "solar", "stat_energy_from": "sensor.solar_energy"}.
            device_consumption: Electricity devices, each with
                `stat_consumption` (and optional `stat_rate`, `name`,
                `included_in_stat`).
            device_consumption_water: Water devices, same shape.
            confirmation_token: Token from the preview call.

        Returns:
            Preview: {confirmation_token, expires_in_seconds, preview}.
            Confirmed: {saved: true, prefs} with what Home Assistant stored.
            Errors: invalid_argument, energy_not_loaded, ha_command_failed
            (schema errors), energy_prefs_changed, token errors.
        """
        tool = "ha_update_energy_prefs"
        recibidas = {"energy_sources": energy_sources,
                     "device_consumption": device_consumption,
                     "device_consumption_water": device_consumption_water}
        nuevas = {n: v for n, v in recibidas.items() if v is not None}
        if not nuevas:
            return _invalido(tool, "energy_sources",
                             "Pass at least one of energy_sources, device_consumption "
                             "or device_consumption_water.")
        for nombre, lista in nuevas.items():
            detalle = _validar(nombre, lista)
            if detalle:
                return _invalido(tool, nombre, detalle)
        # El documento que se enviará, atado entero al token (las listas que
        # no llegan, `None`: mandarlas luego también cambia la acción).
        args = {n: recibidas[n] for n in _LISTAS}

        try:
            estado = await _leer_prefs(ha_client)
        except HAConnectionError as exc:
            # Fail-closed: sin estado no hay token, y uno pendiente sigue
            # pendiente (se puede reintentar dentro de su TTL).
            return _error_ha(tool, exc)
        actuales = _listas(estado)
        recuentos = {n: len(v) for n, v in nuevas.items()}

        if not confirmation_token:
            cambios = {n: _diferencias(actuales[n], v) for n, v in nuevas.items()}
            avisos: list[dict[str, Any]] = []
            quita_todas = (energy_sources is not None and not energy_sources
                           and bool(actuales["energy_sources"]))
            for n, c in cambios.items():
                if c["removed"]:
                    avisos.append({"list": n, "problem": "removes_items",
                                   "count": len(c["removed"]),
                                   "detail": (f"{len(c['removed'])} element(s) of {n} "
                                              "will be removed.")})
            avisos += await _avisos_de_estadisticas(ha_client, nuevas)
            preview: dict[str, Any] = {
                "action": "update_energy_prefs",
                "configured": bool(estado.get("configured")),
                "changes": cambios,
                "kept": [n for n in _LISTAS if n not in nuevas],
                "removes_all_sources": quita_todas,
                "warnings": avisos,
                "current": {n: actuales[n] for n in nuevas},
                "new": dict(nuevas),
                "effect": ("Each list in `new` replaces the whole list in Home "
                           "Assistant; the lists in `kept` stay as they are."),
                "irreversible": False,
                "undo": _UNDO,
            }
            logger.info(f"{tool}_preview", **recuentos)
            return await create_confirmation_token(tool, args, _limpio(preview),
                                                   estado=estado)

        valido, motivo, _ = await resolve_confirmation_token(
            confirmation_token, tool, args, estado=estado)
        if not valido:
            if motivo == ESTADO_CAMBIADO:
                logger.info(f"{tool}_failed", error="energy_prefs_changed")
                return {"error": "energy_prefs_changed", "detail": ESTADO_CAMBIADO}
            logger.info(f"{tool}_failed", error="token_invalid")
            return {"error": motivo}
        try:
            guardado = await ha_client.ws_send({"type": "energy/save_prefs", **nuevas})
        except HAConnectionError as exc:
            await complete_confirmation_token(
                confirmation_token, success=False, error=exc.code or "connection")
            return _error_ha(tool, exc)
        prefs = documento({"configured": True,
                           "prefs": guardado if isinstance(guardado, Mapping) else {}})
        prefs.pop("configured")
        resultado: dict[str, Any] = {"saved": True, "prefs": prefs}
        if tam_json(resultado) > response_max_bytes:
            # Guardado, pero el documento no cabe: se dice en vez de recortarlo.
            resultado = {"saved": True, "prefs_omitted": True,
                         "detail": ("Saved. The stored preferences exceed "
                                    "response_max_bytes; they are not shown.")}
        await complete_confirmation_token(confirmation_token, success=True,
                                          result={"saved": True})
        logger.info(f"{tool}_ok", **recuentos)
        return resultado
