"""Hermes — Control del host y del OS (spec 032, tramo 1; CAP-086).

Familia `host_control` (1.2.0), módulo `host_control`.

Tools:
  sv_shutdown_host  — apaga el host entero (nadie lo enciende a distancia)
  sv_set_hostname   — cambia el hostname (y el nombre mDNS `<nombre>.local`)
  sv_set_swap       — cambia el tamaño o la swappiness de la swap (OS ≥ 15)
  sv_set_boot_slot  — arranca en la otra ranura de Home Assistant OS, YA

POR QUÉ
-------
Las cuatro rutas eran `deny` «pendiente de tool dedicada»: por la genérica
solo se ve un método y una ruta, y ninguna de ellas se puede deshacer a
distancia si sale mal (un host apagado no se enciende por la red; la ranura
reinicia en otro OS). Una tool dedicada enseña, antes de nada, lo que va a
pasar con los datos reales (el hostname actual, la swap y el disco libre, las
ranuras y sus versiones) y avisa de lo que no se ve en la ruta.

Las cuatro confirman en dos pasos. El token ata los argumentos, ya
normalizados (`boot_slot` en mayúsculas), y la HUELLA del estado que describe
la vista previa (`estado=` de la 018): si el hostname, la swap o las ranuras
cambian en los 60 s del token, no se ejecuta nada. El disco libre NO entra en
la huella porque cambia solo (cualquier escritura de Core lo mueve) y haría
caer casi cualquier token; en su lugar, `insufficient_disk` se vuelve a
comprobar al confirmar (decisión del supervisor al validar la spec).

`force` de apagar no se expone (research R-5): se salta la comprobación de una
migración de la base de datos de Core en curso, y apagar a mitad puede
corromperla. `sv_reboot_host` (1.1.2) tampoco lo expone. Con el cuerpo `{}`
el propio Supervisor hace esa comprobación (`_check_ha_offline_migration` en
`api/host.py`), así que apagar no necesita repetirla (T029).

La RANURA sí: `POST /os/boot-slot` (`os/manager.py::set_boot_slot`) marca la
ranura y llama a `host.control.reboot()` directamente, sin esa comprobación.
Por eso `sv_set_boot_slot` lee el estado de Core (`/api/core/state`, el mismo
que lee el Supervisor) antes de dar token y otra vez antes de enviar, y con
una migración que no es en vivo se niega (`db_migration_in_progress`). Si el
estado no se puede leer, también se niega (fail-closed): el Supervisor deja
seguir en ese caso, pero aquí no hay `force` ni forma de saber si migra.

La swap no puede comerse el disco: tras crearla tienen que quedar libres al
menos 1 GiB o el 10 % del disco, lo que sea mayor (`_MARGEN_*`, T033).

Apagar y la ranura tumban el host: el Supervisor puede no llegar a contestar.
Un corte DESPUÉS de enviar no es un fallo seguro ni un éxito, así que la
respuesta dice `outcome: "unknown"` con cómo comprobarlo (research R-10).

El log (eventos `host_control`) lleva la tool, el resultado y los nombres de
lo que cambia, nunca el hostname, la swap ni las versiones: el log se pega en
issues públicos (principio VIII, FR-012).
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import aiohttp
import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    ESTADO_CAMBIADO,
    complete_confirmation_token,
    create_confirmation_token,
    redact_secrets,
    redact_structure,
    resolve_confirmation_token,
)
from hermes.tools._logs import ArgumentoInvalido

logger = structlog.get_logger(__name__)

_EVENTO = "host_control"

# Una etiqueta DNS de RFC 1123 en minúsculas (research R-7). systemd admite
# más (mayúsculas, puntos), pero un nombre así da sorpresas con mDNS y con
# los certificados; se pide lo que funciona en todas partes.
_HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
DETALLE_HOSTNAME = (
    "hostname must be one DNS label: 1-63 lowercase letters, digits or '-', "
    "not starting or ending with '-' (no dots, spaces or uppercase)."
)

# La misma expresión que el Supervisor (`RE_SWAP_SIZE` en `api/os.py`):
# lo que Hermes acepta, el Supervisor lo acepta.
_SWAP_SIZE = re.compile(r"^(\d+)([KMG](?:i?B)?|B)?$", re.IGNORECASE)
_SWAPPINESS_MAX = 200
DETALLE_SWAP_SIZE = (
    "swap_size must be a size like '2G', '512M', '1024K' or a number of bytes "
    "('0' disables swap)."
)
DETALLE_SWAPPINESS = "swappiness must be an integer from 0 to 200."
DETALLE_NADA = "Pass swap_size, swappiness or both: there is nothing to change."
DETALLE_RANURA = "boot_slot must be 'A' or 'B'."

# Bytes por unidad. Binarios en todos los casos: la swap de HAOS es un fichero
# que se crea con `fallocate`, y `disk_free` del Supervisor está en GiB.
_UNIDADES = {"": 1, "B": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}

_PISTA_OS = "Requires Home Assistant OS (swap needs OS 15 or newer)."

# Lo que la swap tiene que dejar libre en el disco de datos (T033): Core, la
# base de datos, los backups y las apps siguen escribiendo ahí. 1 GiB como
# suelo para discos pequeños y el 10 % del total para los grandes.
_MARGEN_MIN_GIB = 1.0
_MARGEN_FRACCION = 0.10
_PISTA_TOKEN = "Request a new preview and confirm with the token it returns."


def _validar_hostname(hostname: Any) -> str:
    if isinstance(hostname, str) and _HOSTNAME.fullmatch(hostname):
        return hostname
    raise ArgumentoInvalido("hostname", DETALLE_HOSTNAME)


def _bytes_de_swap(texto: str) -> int:
    """Bytes de un `swap_size` ya validado (`2G` → 2 GiB)."""
    m = _SWAP_SIZE.fullmatch(texto)
    assert m is not None  # validado antes
    unidad = (m.group(2) or "")[:1].upper()
    return int(m.group(1)) * _UNIDADES[unidad]


def _validar_swap(swap_size: Any, swappiness: Any) -> None:
    if swap_size is None and swappiness is None:
        # Un POST vacío no cambia nada y el Supervisor contestaría «ok».
        raise ArgumentoInvalido("swap_size", DETALLE_NADA)
    if swap_size is not None and not (
        isinstance(swap_size, str) and _SWAP_SIZE.fullmatch(swap_size)
    ):
        raise ArgumentoInvalido("swap_size", DETALLE_SWAP_SIZE)
    # `bool` es un `int` en Python: `True` llegaría como 1 al Supervisor.
    if swappiness is not None and (
        isinstance(swappiness, bool) or not isinstance(swappiness, int)
        or not 0 <= swappiness <= _SWAPPINESS_MAX
    ):
        raise ArgumentoInvalido("swappiness", DETALLE_SWAPPINESS)


def _validar_ranura(boot_slot: Any) -> str:
    """`"A"` o `"B"`; una minúscula vale lo mismo y se normaliza ANTES del
    hash, para que la vista previa y la confirmación sean la misma acción."""
    if isinstance(boot_slot, str) and boot_slot.upper() in ("A", "B"):
        return boot_slot.upper()
    raise ArgumentoInvalido("boot_slot", DETALLE_RANURA)


class _Rechazo(Exception):
    """Una regla de negocio dice que no (sin token). Va tal cual al cliente."""

    def __init__(self, respuesta: dict[str, Any], motivo: str) -> None:
        super().__init__(motivo)
        self.respuesta = respuesta
        self.motivo = motivo


def _es_respuesta_del_supervisor(exc: Exception) -> bool:
    """True si el Supervisor CONTESTÓ con un error (la orden no se aplicó).

    Un error HTTP lleva `status`; un `{"result": "error"}` con 200 llega como
    «Supervisor error: …». Todo lo demás (conexión cortada, tiempo agotado,
    respuesta ilegible) no dice si la orden se aplicó: es «unknown».
    """
    if isinstance(exc, HAConnectionError):
        return exc.status is not None or str(exc).startswith("Supervisor error:")
    return False


def _no_salio(exc: BaseException) -> bool:
    """True si la petición NO llegó a salir hacia el Supervisor.

    Contrato de tres valores de `HAConnectionError.sent` (spec 022): `False`
    es «seguro que no salió» (cliente HTTP sin inicializar); `True` y `None`
    no lo aseguran. Una conexión que ni se estableció
    (`ClientConnectorError`: rechazada, sin ruta, DNS) tampoco pudo hacer
    nada. Decir entonces `outcome: "unknown"` sería mentir: se sabe que no
    se hizo (principio V); lo mismo decide `system_control._no_enviada`.
    """
    return (getattr(exc, "sent", None) is False
            or isinstance(exc, aiohttp.ClientConnectorError))


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de control del host y del OS en la instancia MCP."""

    def _log(tool: str, outcome: str, **campos: Any) -> None:
        # Solo nombres: nunca hostname, tamaños ni versiones (FR-012).
        logger.info(_EVENTO, tool=tool, outcome=outcome, **campos)

    async def _leer(tool: str, ruta: str, *, os_404: bool = False) -> Any:
        """GET; un error lanza `_Rechazo` con el mensaje redactado. Antes de
        enviar nada, un fallo es un fallo: no hay token ni vista previa a
        medias."""
        try:
            return await ha_client.sv_request("GET", ruta)
        except HAConnectionError as exc:
            if os_404 and exc.status == 404:
                # Sin HAOS (o la swap antes de OS 15) el Supervisor da 404: la
                # pista evita que el agente reintente lo que no puede funcionar.
                raise _Rechazo({"error": "not_supported", "detail": redact_secrets(str(exc)),
                                "hint": _PISTA_OS}, "not_supported") from None
            raise _Rechazo({"error": redact_secrets(str(exc))}, "read_failed") from None

    def _forma(ruta: str) -> _Rechazo:
        # Nunca se inventa una vista previa con una respuesta de otra forma.
        return _Rechazo({"error": f"Unexpected Supervisor response for GET {ruta}."},
                        "unexpected_shape")

    async def _hostname_actual(tool: str) -> str:
        datos = await _leer(tool, "/host/info")
        actual = datos.get("hostname") if isinstance(datos, dict) else None
        if not isinstance(actual, str):
            raise _forma("/host/info")
        return actual

    async def _confirmar(tool: str, token: str, args: dict[str, Any],
                         huella: Any) -> dict[str, Any] | None:
        """None si el token vale para estos argumentos y este estado."""
        ok, error, _ = await resolve_confirmation_token(token, tool, args, estado=huella)
        if ok:
            return None
        _log(tool, "rejected", reason="token")
        if error == ESTADO_CAMBIADO:
            return {"error": "state_changed", "detail": error}
        return {"error": error, "hint": _PISTA_TOKEN}

    async def _enviar(
        tool: str, ruta: str, carga: dict[str, Any], token: str, *,
        changed: list[str], verify_with: str, hint_unknown: str,
    ) -> dict[str, Any] | None:
        """POST con la carga exacta. None si fue bien; si no, la respuesta.

        Distingue un error del Supervisor (la orden no se aplicó: `error`),
        una petición que ni salió (`sent: false`: no se hizo nada) y un corte
        después de enviar o sin saber si salió (`outcome: "unknown"`). En los
        tres casos el token queda completado como fallido y no se reintenta.
        """
        try:
            await ha_client.sv_request("POST", ruta, json_body=carga)
        except (HAConnectionError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
            if _es_respuesta_del_supervisor(exc):
                texto = redact_secrets(str(exc))
                await complete_confirmation_token(token, success=False, error=texto)
                _log(tool, "error", changed=changed, reason="supervisor")
                return {"error": texto}
            if _no_salio(exc):
                await complete_confirmation_token(
                    token, success=False, error="request not sent; nothing was done")
                _log(tool, "error", changed=changed, reason="not_sent")
                return {"error": "supervisor_request_failed", "sent": False,
                        "detail": redact_secrets(str(exc)),
                        "note": "The request never reached the Supervisor: nothing was done. Ask for a new preview when Hermes is connected."}
            await complete_confirmation_token(
                token, success=False, error="connection lost after sending; outcome unknown")
            _log(tool, "unknown", changed=changed, reason="connection_lost")
            return {"outcome": "unknown", "hint": hint_unknown, "verify_with": verify_with}
        return None

    async def _hecho(tool: str, token: str, result: dict[str, Any],
                     changed: list[str]) -> dict[str, Any]:
        result = redact_structure(result)
        await complete_confirmation_token(token, success=True, result=result)
        _log(tool, "ok", changed=changed)
        return result

    # ── Apagar ────────────────────────────────────────────────────────────

    @mcp.tool()
    async def sv_shutdown_host(confirmation_token: str | None = None) -> object:
        """Power off the whole Home Assistant OS machine: the host, Home
        Assistant Core, every app (add-on) and Hermes itself stop, and this
        connection is lost. Nobody can power it back on remotely: someone
        needs physical access (or a smart plug / Wake-on-LAN that does not
        depend on this machine). To restart instead, use sv_reboot_host.

        Two steps: the first call returns a preview and a confirmation_token;
        repeat the call with confirmation_token to power off. There is no
        `force`: if Home Assistant is migrating its database, the Supervisor
        refuses and the error says to wait. If the connection drops after
        the order was sent, the answer is outcome "unknown".
        """
        tool = "sv_shutdown_host"
        # Sin argumentos ni estado que describir, como `sv_reboot_host`.
        args: dict[str, Any] = {}
        if not confirmation_token:
            preview = {
                "action": "shutdown_host",
                "stops": ["host", "home_assistant_core", "all_apps", "hermes"],
                "warning": (
                    "Nobody can power this machine on remotely after this: "
                    "someone needs physical access to its power button, or a "
                    "smart plug or Wake-on-LAN that does not depend on this "
                    "machine. Home Assistant, every app and Hermes stay off "
                    "until then."
                ),
                "connection": "This connection to Hermes will be lost.",
            }
            _log(tool, "preview")
            return await create_confirmation_token(tool, args, preview=preview)
        if (fallo := await _confirmar(tool, confirmation_token, args, None)):
            return fallo
        # `{}` y no `{"force": …}`: la comprobación de la migración sigue.
        if (fallo := await _enviar(
                tool, "/host/shutdown", {}, confirmation_token, changed=[],
                verify_with="sv_get_host_info",
                hint_unknown=("The connection dropped after the shutdown order was "
                              "sent. If the host is powering off it will stop "
                              "answering; if sv_get_host_info still answers in a "
                              "minute, it did not shut down."))):
            return fallo
        return await _hecho(tool, confirmation_token, {
            "result": "ok",
            "note": ("Host shutdown initiated. Hermes will stop answering; nobody "
                     "can power the machine back on remotely."),
        }, [])

    # ── Hostname ──────────────────────────────────────────────────────────

    @mcp.tool()
    async def sv_set_hostname(hostname: str, confirmation_token: str | None = None) -> object:
        """Change the host's hostname, which is also its mDNS name
        (<hostname>.local): links, bookmarks, certificates and integrations
        that use the old name stop working. hostname must be one DNS label
        (1-63 lowercase letters, digits or '-', not starting or ending with
        '-'); the same name as now is refused (no_change).

        Two steps: the preview shows the current and the new name and returns
        a confirmation_token; repeat the call with it to apply. If the
        hostname changes in between, nothing is done (state_changed).
        """
        tool = "sv_set_hostname"
        try:
            hostname = _validar_hostname(hostname)
        except ArgumentoInvalido as exc:
            _log(tool, "invalid_argument", field=exc.campo)
            return exc.respuesta()
        args = {"hostname": hostname}
        try:
            actual = await _hostname_actual(tool)
            if actual == hostname:
                raise _Rechazo({"error": "no_change",
                                "detail": "That is already the hostname."}, "no_change")
        except _Rechazo as r:
            _log(tool, "rejected", reason=r.motivo)
            return r.respuesta
        huella = {"hostname": actual}
        if not confirmation_token:
            preview = {
                "action": "set_hostname", "from": actual, "to": hostname,
                "warning": (
                    f"The mDNS name changes too: {actual}.local stops working and "
                    f"{hostname}.local takes its place. Links, bookmarks, "
                    "certificates and integrations that use the old name stop "
                    "working."
                ),
            }
            _log(tool, "preview", changed=["hostname"])
            return await create_confirmation_token(tool, args, preview=preview, estado=huella)
        if (fallo := await _confirmar(tool, confirmation_token, args, huella)):
            return fallo
        if (fallo := await _enviar(
                tool, "/host/options", {"hostname": hostname}, confirmation_token,
                changed=["hostname"], verify_with="sv_get_host_info",
                hint_unknown="The connection dropped after the change was sent; "
                             "check the hostname with sv_get_host_info.")):
            return fallo
        try:
            releido: str | None = await _hostname_actual(tool)
        except _Rechazo:
            releido = None
        result: dict[str, Any] = {"result": "ok", "hostname": releido}
        if releido is None:
            result["verify_with"] = "sv_get_host_info"
        return await _hecho(tool, confirmation_token, result, ["hostname"])

    # ── Swap ──────────────────────────────────────────────────────────────

    async def _leer_swap(tool: str) -> dict[str, Any]:
        datos = await _leer(tool, "/os/config/swap", os_404=True)
        if (not isinstance(datos, dict) or not isinstance(datos.get("swap_size"), str)
                or isinstance(datos.get("swappiness"), bool)
                or not isinstance(datos.get("swappiness"), int)):
            raise _forma("/os/config/swap")
        return {"swap_size": datos["swap_size"], "swappiness": datos["swappiness"]}

    async def _disco(tool: str) -> tuple[float, float]:
        """`(disk_free, disk_total)` en GiB."""
        datos = await _leer(tool, "/host/info")
        valores = []
        for clave in ("disk_free", "disk_total"):
            v = datos.get(clave) if isinstance(datos, dict) else None
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise _forma("/host/info")
            valores.append(float(v))
        return valores[0], valores[1]

    def _mismo_tamano(a: str, b: str) -> bool:
        # `1G` y `1024M` son la misma swap; lo que no se pueda leer, por texto.
        if _SWAP_SIZE.fullmatch(a) and _SWAP_SIZE.fullmatch(b):
            return _bytes_de_swap(a) == _bytes_de_swap(b)
        return a == b

    @mcp.tool()
    async def sv_set_swap(
        swap_size: str | None = None,
        swappiness: int | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Change Home Assistant OS swap: swap_size (like '2G', '512M' or a
        number of bytes; '0' disables swap) and/or swappiness (0-200). Only
        what you pass is sent. Requires Home Assistant OS 15 or newer
        (not_supported otherwise). A size that would leave less than 1 GiB
        or 10% of the disk free (whichever is larger) is refused
        (insufficient_disk); the same values as now, no_change. The
        Supervisor raises a 'reboot required' issue: the change applies after
        sv_reboot_host.

        Two steps: the preview shows current and new values and the free
        disk space and returns a confirmation_token; repeat the call with it
        to apply. If the swap settings change in between, nothing is done.
        """
        tool = "sv_set_swap"
        try:
            _validar_swap(swap_size, swappiness)
        except ArgumentoInvalido as exc:
            _log(tool, "invalid_argument", field=exc.campo)
            return exc.respuesta()
        # Los dos en el hash, también el que no se pasa: `None` es «no
        # tocar» y no puede confirmarse como «cambiarlo».
        args = {"swap_size": swap_size, "swappiness": swappiness}
        carga = {k: v for k, v in (("swap_size", swap_size), ("swappiness", swappiness))
                 if v is not None}
        try:
            actual = await _leer_swap(tool)
            libre, total = await _disco(tool)
            margen = max(_MARGEN_MIN_GIB, round(total * _MARGEN_FRACCION, 1))
            cambios = {
                k: {"from": actual[k], "to": v} for k, v in carga.items()
                if not (_mismo_tamano(actual[k], v) if k == "swap_size" else actual[k] == v)
            }
            if not cambios:
                raise _Rechazo({"error": "no_change",
                                "detail": "The swap already has those values."}, "no_change")
            # Se repite al confirmar: el disco libre no entra en la huella.
            # Se compara contra lo que queda libre MENOS el margen, sin
            # descontar la swap actual: no se sabe si su fichero existe ya,
            # y suponerlo sería optimista (fail-closed).
            if (swap_size is not None
                    and _bytes_de_swap(swap_size) > (libre - margen) * 1024 ** 3):
                raise _Rechazo({
                    "error": "insufficient_disk",
                    "detail": (f"swap_size must leave at least {margen} GiB free "
                               "(1 GiB or 10% of the disk, whichever is larger) "
                               f"and only {libre} GiB are free; the swap file "
                               "would fill the data disk that Home Assistant "
                               "needs."),
                }, "insufficient_disk")
        except _Rechazo as r:
            _log(tool, "rejected", reason=r.motivo)
            return r.respuesta
        changed = sorted(cambios)
        huella = actual
        if not confirmation_token:
            preview: dict[str, Any] = {
                "action": "set_swap", "changes": cambios, "disk_free_gib": libre,
                "disk_reserve_gib": margen, "reboot_required": True,
            }
            if swap_size is not None and _bytes_de_swap(swap_size) == 0:
                preview["warning"] = ("swap_size 0 disables swap: with little "
                                      "RAM, Home Assistant may run out of memory.")
            _log(tool, "preview", changed=changed)
            return await create_confirmation_token(tool, args, preview=preview, estado=huella)
        if (fallo := await _confirmar(tool, confirmation_token, args, huella)):
            return fallo
        if (fallo := await _enviar(
                tool, "/os/config/swap", carga, confirmation_token, changed=changed,
                verify_with="sv_get_swap",
                hint_unknown="The connection dropped after the change was sent; "
                             "check the swap with sv_get_swap.")):
            return fallo
        try:
            releida: dict[str, Any] | None = await _leer_swap(tool)
        except _Rechazo:
            releida = None
        return await _hecho(tool, confirmation_token, {
            "result": "ok", "swap": releida, "reboot_required": True,
            "hint": ("The Supervisor reports a reboot_required issue (see "
                     "sv_get_resolution); the new swap applies after "
                     "sv_reboot_host."),
        }, changed)

    # ── Ranura de arranque ────────────────────────────────────────────────

    async def _leer_ranuras(tool: str) -> dict[str, Any]:
        datos = await _leer(tool, "/os/info", os_404=True)
        if not isinstance(datos, dict):
            raise _forma("/os/info")
        boot, ranuras = datos.get("boot"), datos.get("boot_slots")
        if boot is None and isinstance(ranuras, dict) and not ranuras:
            # Sin HAOS, `api/os.py::info` NO da 404: contesta `boot: null` y
            # `boot_slots: {}` (no hay RAUC ni ranuras). Es «no soportado», no
            # una respuesta rara (T032).
            raise _Rechazo({"error": "not_supported",
                            "detail": "This system has no Home Assistant OS boot slots.",
                            "hint": _PISTA_OS}, "not_supported")
        if (not isinstance(boot, str) or not isinstance(ranuras, dict)
                or not all(isinstance(v, dict) for v in ranuras.values())):
            raise _forma("/os/info")
        return {"boot": boot, "boot_slots": ranuras}

    async def _sin_migracion() -> None:
        """Rechaza si Core migra su base de datos fuera de línea (T029).

        El mismo criterio que `get_api_state` del Supervisor:
        `recorder_state.migration_in_progress` y no `migration_is_live`; un
        Core sin `recorder_state` (anterior a 2024.8) no migra. A diferencia
        del Supervisor, si el estado no se puede leer se rechaza: reiniciar a
        mitad de una migración puede corromper la base de datos.
        """
        try:
            estado = await ha_client._request_json("GET", "/core/state")  # noqa: SLF001
        except (HAConnectionError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise _Rechazo({
                "error": "core_state_unknown",
                "detail": ("Cannot read Home Assistant's state to check that it "
                           "is not migrating its database "
                           f"({redact_secrets(str(exc))}); changing the boot slot "
                           "reboots at once and could corrupt it. Try again when "
                           "Home Assistant answers."),
            }, "core_state_unknown") from None
        recorder = estado.get("recorder_state", {}) if isinstance(estado, dict) else None
        if not isinstance(recorder, dict):
            raise _Rechazo({
                "error": "core_state_unknown",
                "detail": ("Unexpected answer from Home Assistant's /api/core/state; "
                           "cannot tell whether it is migrating its database."),
            }, "core_state_unknown")
        if recorder.get("migration_in_progress") is True and \
                recorder.get("migration_is_live") is not True:
            raise _Rechazo({
                "error": "db_migration_in_progress",
                "detail": ("Home Assistant is migrating its database offline. "
                           "Changing the boot slot reboots the machine at once "
                           "and could corrupt the database; the Supervisor does "
                           "not check this for boot slots. Wait until the "
                           "migration finishes (ha_get_recorder_info)."),
            }, "db_migration_in_progress")

    @mcp.tool()
    async def sv_set_boot_slot(boot_slot: str, confirmation_token: str | None = None) -> object:
        """Boot Home Assistant OS from the other slot ('A' or 'B'), for
        example to go back to the previous OS version after a bad update.
        WARNING: the machine reboots IMMEDIATELY into the OS installed in
        that slot (Home Assistant, every app and Hermes go down for several
        minutes), and it keeps booting from it until changed back. Requires
        Home Assistant OS. The slot already booted is refused
        (already_booted); a missing slot or one without an OS version,
        slot_unusable; a slot marked 'bad' is allowed with a warning. While
        Home Assistant migrates its database offline it is refused
        (db_migration_in_progress), and also when that cannot be checked
        (core_state_unknown), before the preview and again before sending.

        Two steps: the preview shows the current and the target slot with
        their versions and how to go back, and returns a confirmation_token;
        repeat the call with it to reboot. If the connection drops after the
        order was sent (it usually does), the answer is outcome "unknown":
        check with sv_get_os_info once it is back.
        """
        tool = "sv_set_boot_slot"
        try:
            boot_slot = _validar_ranura(boot_slot)
        except ArgumentoInvalido as exc:
            _log(tool, "invalid_argument", field=exc.campo)
            return exc.respuesta()
        args = {"boot_slot": boot_slot}
        try:
            huella = await _leer_ranuras(tool)
            actual, ranuras = huella["boot"], huella["boot_slots"]
            if boot_slot == actual:
                raise _Rechazo({"error": "already_booted",
                                "detail": f"Slot {boot_slot} is the one booted now."},
                               "already_booted")
            destino = ranuras.get(boot_slot)
            if not destino or not destino.get("version"):
                raise _Rechazo({"error": "slot_unusable",
                                "detail": (f"Slot {boot_slot} has no OS version the "
                                           "Supervisor can boot.")}, "slot_unusable")
            # Antes de dar token y otra vez antes de enviar (este código
            # corre en las dos llamadas): la migración puede empezar en los
            # 60 s del token.
            await _sin_migracion()
        except _Rechazo as r:
            _log(tool, "rejected", reason=r.motivo)
            return r.respuesta
        if not confirmation_token:
            preview: dict[str, Any] = {
                "action": "set_boot_slot",
                "current": {"slot": actual,
                            "version": (ranuras.get(actual) or {}).get("version")},
                "target": {"slot": boot_slot, "version": destino.get("version"),
                           "state": destino.get("state"), "status": destino.get("status")},
                "reboots_now": True,
                "warning": (
                    f"The machine reboots immediately into Home Assistant OS "
                    f"{destino.get('version')} from slot {boot_slot}, and keeps "
                    "booting from it until changed back. Home Assistant, every "
                    "app and Hermes go down for several minutes."
                ),
                "rollback": f'sv_set_boot_slot("{actual}")',
            }
            if destino.get("status") == "bad":
                preview["slot_warning"] = (
                    f"Slot {boot_slot} is marked 'bad': its last boot failed. It "
                    "may not start; if it does not, the bootloader may fall back "
                    f"to slot {actual} on its own after failed attempts.")
            _log(tool, "preview", changed=["boot_slot"])
            return await create_confirmation_token(tool, args, preview=preview, estado=huella)
        if (fallo := await _confirmar(tool, confirmation_token, args, huella)):
            return fallo
        if (fallo := await _enviar(
                tool, "/os/boot-slot", {"boot_slot": boot_slot}, confirmation_token,
                changed=["boot_slot"], verify_with="sv_get_os_info",
                hint_unknown=("The connection dropped after the order was sent: the "
                              "machine is probably rebooting. When Hermes answers "
                              "again, sv_get_os_info says which slot booted."))):
            return fallo
        return await _hecho(tool, confirmation_token, {
            "result": "ok",
            "note": (f"Rebooting into slot {boot_slot} now. Hermes will stop "
                     "answering for several minutes."),
            "verify_with": "sv_get_os_info",
        }, ["boot_slot"])
