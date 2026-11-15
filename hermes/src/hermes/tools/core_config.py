"""Hermes — Tools MCP de la configuración del núcleo (spec 021, tramo a).

Dos tools de la familia `core_config` (CAP-053 de la 008):

- `ha_get_core_config`: la configuración general editable de HA (nombre,
  ubicación, unidades, zona horaria, moneda, país, idioma y URLs), de dónde
  viene y la versión, por `get_config`.
- `ha_update_core_config`: cambia solo los campos que se le pasan, en dos
  pasos, por `config/core/update`.

POR QUÉ DOS PASOS Y LOS AVISOS
------------------------------
Cambiar la zona horaria mueve los disparadores por hora y los horarios; las
unidades cambian cómo se leen los sensores (y `update_units`, las estadísticas
a largo plazo); la ubicación mueve `zone.home` y con ella la presencia; las
URLs rompen las apps y los enlaces. La vista previa lo dice campo a campo, con
el antes y el después, y el token se ata a los argumentos y a lo leído (spec
018): si alguien cambia la configuración entre los dos pasos, no se aplica.

POR QUÉ LA ZONA HORARIA VA SOLA Y PRIMERO
------------------------------------------
`Config._async_update` de HA aplica en memoria campo a campo y valida la zona
casi al final; si la zona no existe lanza `ValueError` con lo anterior ya
cambiado en memoria y sin guardar. Mandándola sola y primero, una zona
inválida no deja nada a medias; si la zona pasa y el resto falla, la respuesta
dice exactamente qué se aplicó (`partial`).

POR QUÉ EL AVISO DE YAML
------------------------
Si la configuración está en `configuration.yaml` (`homeassistant:`), HA
acepta el cambio y lo guarda en almacenamiento, pero al arrancar vuelve a
mandar el YAML: el cambio no sobrevive a un reinicio.

PRIVACIDAD (principio VIII)
---------------------------
Las coordenadas, la zona horaria, el país y las URLs dicen dónde está la casa.
El log solo lleva nombres de campos; el fichero del token solo guarda la
huella del estado y el resultado sin valores; y la respuesta de la
confirmación solo relee los campos pedidos.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

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
from hermes.tools._validation import es_numero_finito
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)

# Campos editables por `config/core/update`, en el orden de la respuesta.
CAMPOS = (
    "location_name", "latitude", "longitude", "elevation", "radius",
    "unit_system", "time_zone", "currency", "country", "language",
    "internal_url", "external_url",
)

_UNIDADES = ("metric", "us_customary")
_PAIS = re.compile(r"^[A-Z]{2}$")
_MONEDA = re.compile(r"^[A-Z]{3}$")
_IDIOMA = re.compile(r"^[a-z]{2,3}([-_][A-Za-z0-9]{2,8})*$")
_NOMBRE_MAX = 255
_ZONA_MAX = 64

# Avisos por grupo de campos (data-model). Código y texto en inglés: los lee
# el cliente y se los enseña al usuario.
_AVISOS = {
    "time_zone": "time_zone: time triggers, schedules, history and the logbook use the new zone",
    "unit_system": ("unit_system: sensors are shown in the new units; values already "
                    "recorded are not converted"),
    "update_units": ("update_units: also changes the suggested unit of sensors, which "
                     "changes how long-term statistics are recorded from now on"),
    "location": ("location: moves zone.home (latitude, longitude, radius, elevation): "
                 "presence, 'home' automations and sun events follow it"),
    "urls": ("urls: mobile apps, notification links and Home Assistant Cloud use these "
             "addresses; a wrong one breaks them"),
    "regional": ("regional: country, currency and language change defaults, formats and "
                 "what some integrations offer"),
    "yaml_source": ("yaml_source: this configuration comes from configuration.yaml "
                    "(homeassistant:); Home Assistant applies the change now but the "
                    "YAML wins again on the next restart"),
}
_GRUPO = {
    "time_zone": "time_zone",
    "unit_system": "unit_system",
    "latitude": "location", "longitude": "location", "radius": "location",
    "elevation": "location",
    "internal_url": "urls", "external_url": "urls",
    "country": "regional", "currency": "regional", "language": "regional",
}


def _invalido(campo: str, detalle: str) -> dict[str, Any]:
    logger.info("ha_update_core_config_failed", error="invalid_argument", field=campo)
    return {"error": "invalid_argument", "field": campo, "detail": detalle}


def _nombre_unidades(raw: Any) -> tuple[str | None, Any]:
    """`(nombre, detalle)` del `unit_system` de `get_config` (un dict).

    HA no devuelve el nombre del sistema de unidades, solo sus unidades. Se
    deduce de la temperatura y la longitud; si no cuadra con ninguno, el dict
    tal cual en el detalle y `None` como nombre (no se inventa uno).
    """
    if isinstance(raw, str) and raw in _UNIDADES:
        return raw, None
    if isinstance(raw, dict):
        temp, longitud = raw.get("temperature"), raw.get("length")
        if temp == "°C" and longitud == "km":
            return "metric", None
        if temp == "°F" and longitud == "mi":
            return "us_customary", None
    return None, raw


def editables(raw: Any) -> dict[str, Any]:
    """Los campos editables, `config_source` y `version` de `get_config`."""
    if not isinstance(raw, dict):
        raise HAConnectionError("unexpected response from get_config: not an object")
    out: dict[str, Any] = {c: raw.get(c) for c in CAMPOS}
    nombre, detalle = _nombre_unidades(raw.get("unit_system"))
    out["unit_system"] = nombre
    if detalle is not None:
        out["unit_system_detail"] = detalle
    out["config_source"] = raw.get("config_source")
    out["version"] = raw.get("version")
    return out


def _estado(config: dict[str, Any]) -> dict[str, Any]:
    """Lo que ata el token: los campos editables y la fuente leídos."""
    return {c: config.get(c) for c in (*CAMPOS, "unit_system_detail", "config_source")}


def _url_valida(valor: str) -> bool:
    try:
        partes = urlsplit(valor)
        partes.port  # noqa: B018 - valida el puerto (lanza si no es un número)
    except ValueError:
        return False
    return (
        partes.scheme in ("http", "https")
        and bool(partes.hostname)
        and partes.path in ("", "/")
        and not partes.query
        and not partes.fragment
        and not any(c.isspace() for c in valor)
    )


def _es_numero(valor: Any) -> bool:
    # Un entero enorme no es una coordenada: lanzaba `OverflowError` en vez de
    # dar `invalid_argument` (cierre de robustez de la 1.2.0).
    return es_numero_finito(valor)


def _es_entero(valor: Any) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _validar(pedidos: dict[str, Any], update_units: Any) -> dict[str, Any] | None:
    """`invalid_argument` del primer campo que no vale, o `None`."""
    if not isinstance(update_units, bool):
        return _invalido("update_units", "must be true or false")
    if update_units and "unit_system" not in pedidos:
        return _invalido("update_units", "only with unit_system")
    if not pedidos:
        return _invalido("fields", "give at least one field to change")
    for campo, valor in pedidos.items():
        if campo == "location_name":
            if not isinstance(valor, str) or not valor.strip() or len(valor) > _NOMBRE_MAX:
                return _invalido(campo, f"must be a non-empty text of at most {_NOMBRE_MAX} characters")
        elif campo == "latitude":
            if not _es_numero(valor) or not -90 <= valor <= 90:
                return _invalido(campo, "must be a number between -90 and 90")
        elif campo == "longitude":
            if not _es_numero(valor) or not -180 <= valor <= 180:
                return _invalido(campo, "must be a number between -180 and 180")
        elif campo == "elevation":
            if not _es_entero(valor):
                return _invalido(campo, "must be an integer (meters)")
        elif campo == "radius":
            if not _es_entero(valor) or valor < 0:
                return _invalido(campo, "must be an integer >= 0 (meters)")
        elif campo == "unit_system":
            if valor not in _UNIDADES:
                return _invalido(campo, "must be 'metric' or 'us_customary'")
        elif campo == "time_zone":
            if (not isinstance(valor, str) or not valor or len(valor) > _ZONA_MAX
                    or any(c.isspace() for c in valor)):
                return _invalido(campo, "must be an IANA time zone like 'Europe/Madrid'")
        elif campo == "currency":
            if not isinstance(valor, str) or not _MONEDA.match(valor):
                return _invalido(campo, "must be an ISO 4217 code in capitals, like 'EUR'")
        elif campo == "country":
            if not isinstance(valor, str) or not _PAIS.match(valor):
                return _invalido(campo, "must be an ISO 3166 two-letter code in capitals, like 'ES'")
        elif campo == "language":
            if not isinstance(valor, str) or not _IDIOMA.match(valor):
                return _invalido(campo, "must be a language code like 'es' or 'en-GB'")
        elif campo in ("internal_url", "external_url"):
            if not isinstance(valor, str) or (valor != "" and not _url_valida(valor)):
                return _invalido(
                    campo,
                    "must be http(s)://host[:port] without a path, or \"\" to remove it",
                )
    return None


def _valor_nuevo(campo: str, valor: Any) -> Any:
    # `""` quita la URL: HA la guarda como `None`.
    if campo in ("internal_url", "external_url") and valor == "":
        return None
    return valor


def _igual(campo: str, antes: Any, despues: Any) -> bool:
    if campo in ("latitude", "longitude") and _es_numero(antes) and _es_numero(despues):
        return float(antes) == float(despues)
    return antes == despues


def _error_ha(exc: HAConnectionError) -> dict[str, Any]:
    """Error de HA redactado y traducido (FR-020)."""
    detalle = redact_secrets(str(exc))
    if exc.code is None:
        return {"error": detalle}
    if exc.code == "unknown_command":
        from hermes.command_table import TABLE_HA_CORE
        return {
            "error": "unsupported_by_ha_version",
            "detail": ("The installed Home Assistant does not know this command; "
                       f"Hermes' table is for {TABLE_HA_CORE}."),
            "ha_code": exc.code,
            "table_ha_core": TABLE_HA_CORE,
        }
    return {"error": "ha_error", "ha_code": exc.code, "detail": detalle}


async def leer_config(ha_client: HAClient) -> dict[str, Any]:
    return editables(await ha_client.ws_send({"type": "get_config"}))


def register(mcp: object, ha_client: HAClient, *, response_max_bytes: int) -> None:
    """Registra las tools de la configuración del núcleo."""

    ready = requires_ready(ha_client)
    del response_max_bytes  # respuestas pequeñas y de tamaño fijo

    # ── ha_get_core_config ────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_get_core_config() -> object:
        """Read Home Assistant's general configuration (Settings > System > General).

        Returns the editable fields: location_name, latitude, longitude,
        elevation, radius, unit_system ("metric" or "us_customary"),
        time_zone, currency, country, language, internal_url and
        external_url; plus config_source ("storage", or "yaml" when it is set
        in configuration.yaml) and the Home Assistant version. Changes
        nothing. To change it, ha_update_core_config. To get suggested values
        from the public IP (unit system, coordinates, time zone, currency and
        country), ha_read_ws_command(type="config/core/detect"): that asks an
        external geolocation service on the internet and saves nothing.

        Returns:
            The fields above. If the units do not match metric or US
            customary, unit_system is null and unit_system_detail has Home
            Assistant's units.
        """
        try:
            config = await leer_config(ha_client)
        except HAConnectionError as exc:
            logger.warning("ha_get_core_config_failed", error=exc.code or "connection")
            return _error_ha(exc)
        logger.info("ha_get_core_config_ok", config_source=config.get("config_source"))
        return redact_structure(config)

    # ── ha_update_core_config ─────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_update_core_config(
        location_name: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        elevation: int | None = None,
        radius: int | None = None,
        unit_system: str | None = None,
        time_zone: str | None = None,
        currency: str | None = None,
        country: str | None = None,
        language: str | None = None,
        internal_url: str | None = None,
        external_url: str | None = None,
        update_units: bool = False,
        confirmation_token: str | None = None,
    ) -> object:
        """Change Home Assistant's general configuration (name, location, units, time zone...).

        Two steps: without confirmation_token returns a preview (before and
        after of each field you pass, and what each change drags along) and a
        token; repeat the same call with the token to apply. Only the fields
        you pass change. If nothing would change, {"result": "no_changes"}
        and no token. If the configuration comes from configuration.yaml
        (config_source "yaml"), the preview says so: Home Assistant applies
        the change, but the YAML wins again on the next restart. A time zone
        is applied alone and first, so an invalid one changes nothing.

        Args:
            location_name: Name of the home.
            latitude: -90 to 90. Moves zone.home.
            longitude: -180 to 180. Moves zone.home.
            elevation: Meters (integer).
            radius: Radius of zone.home in meters (integer >= 0).
            unit_system: "metric" or "us_customary".
            time_zone: IANA time zone, e.g. "Europe/Madrid".
            currency: ISO 4217 code, e.g. "EUR".
            country: ISO 3166 two-letter code, e.g. "ES".
            language: Language code, e.g. "es" or "en-GB".
            internal_url: http(s)://host[:port] without a path; "" removes it.
            external_url: http(s)://host[:port] without a path; "" removes it.
            update_units: Only with unit_system: also change the suggested
                unit of sensors (affects long-term statistics).
            confirmation_token: Token from the preview call.

        Returns:
            Preview + token; {"result": "ok", "applied": [fields], "config":
            {the fields you passed, read again, config_source, version}};
            {"result": "partial", "applied", "failed", "error", "detail",
            "config"} if the time zone was applied and the rest failed;
            {"result": "no_changes"}; or {"error": ...}.
        """
        crudos = {
            "location_name": location_name, "latitude": latitude,
            "longitude": longitude, "elevation": elevation, "radius": radius,
            "unit_system": unit_system, "time_zone": time_zone,
            "currency": currency, "country": country, "language": language,
            "internal_url": internal_url, "external_url": external_url,
        }
        pedidos = {c: v for c, v in crudos.items() if v is not None}
        error = _validar(pedidos, update_units)
        if error is not None:
            return error
        # El token ata todos los argumentos (también los `None`), como el resto
        # de tools en dos pasos: otra combinación es otra acción.
        args = {**crudos, "update_units": update_units}
        nombres = sorted(pedidos)

        try:
            actual = await leer_config(ha_client)
        except HAConnectionError as exc:
            logger.warning("ha_update_core_config_failed", error="preview_unavailable",
                           code=exc.code or "connection")
            if exc.code == "unknown_command":
                return _error_ha(exc)
            return {"error": "preview_unavailable", "detail": redact_secrets(str(exc))}

        cambios = {
            c: {"before": actual.get(c), "after": _valor_nuevo(c, v)}
            for c, v in pedidos.items()
            if not _igual(c, actual.get(c), _valor_nuevo(c, v))
        }

        if not confirmation_token:
            if not cambios and not update_units:
                logger.info("ha_update_core_config_ok", step="preview",
                            result="no_changes", fields=nombres)
                return {"result": "no_changes"}
            grupos = {_GRUPO[c] for c in cambios if c in _GRUPO}
            avisos = [_AVISOS[g] for g in
                      ("time_zone", "unit_system", "location", "urls", "regional")
                      if g in grupos]
            if update_units:
                avisos.append(_AVISOS["update_units"])
            if actual.get("config_source") == "yaml":
                avisos.append(_AVISOS["yaml_source"])
            # Solo se enseña el valor de lo que cambia: lo pedido que ya
            # estaba así sale por nombre (las coordenadas y la zona son datos
            # de la casa).
            preview = {
                "action": "update_core_config",
                "changes": redact_structure(cambios),
                "unchanged": sorted(c for c in pedidos if c not in cambios),
                "update_units": update_units,
                "warnings": avisos,
                "config_source": actual.get("config_source"),
            }
            logger.info("ha_update_core_config_ok", step="preview", fields=sorted(cambios))
            return await create_confirmation_token(
                "ha_update_core_config", args, preview=preview, estado=_estado(actual))

        valido, error_token, _ = await resolve_confirmation_token(
            confirmation_token, "ha_update_core_config", args, estado=_estado(actual))
        if not valido:
            logger.warning("ha_update_core_config_failed", step="confirm",
                           error="state_changed" if error_token == ESTADO_CAMBIADO
                           else "token_invalid")
            return {"error": error_token}

        # Se manda exactamente lo pedido (también lo que no cambia): es lo que
        # se previsualizó. La zona, sola y primero (ver el docstring).
        carga = {c: _valor_nuevo(c, v) for c, v in pedidos.items()}
        tandas: list[dict[str, Any]] = []
        if "time_zone" in carga and len(carga) > 1:
            tandas.append({"time_zone": carga.pop("time_zone")})
        if update_units:
            carga["update_units"] = True
        tandas.append(carga)

        aplicados: list[str] = []
        for i, tanda in enumerate(tandas):
            campos_tanda = sorted(k for k in tanda if k != "update_units")
            try:
                await ha_client.ws_send({"type": "config/core/update", **tanda})
            except HAConnectionError as exc:
                fallo = _error_ha(exc)
                await complete_confirmation_token(
                    confirmation_token, success=False, error=str(fallo.get("error")))
                logger.warning("ha_update_core_config_failed", step="confirm",
                               error=exc.code or "connection",
                               applied=aplicados, failed=campos_tanda)
                if i == 0:
                    return fallo
                return {
                    "result": "partial", "applied": aplicados, "failed": campos_tanda,
                    "error": fallo.get("ha_code", fallo["error"]),
                    "detail": fallo.get("detail", fallo["error"]),
                    "config": await _releer(ha_client, nombres),
                }
            aplicados.extend(campos_tanda)

        # Al fichero del token, solo nombres de campos: nada de valores.
        await complete_confirmation_token(
            confirmation_token, success=True, result={"result": "ok", "applied": aplicados})
        logger.info("ha_update_core_config_ok", step="confirm", fields=aplicados,
                    update_units=update_units)
        return {"result": "ok", "applied": aplicados,
                "config": await _releer(ha_client, nombres)}


async def _releer(ha_client: HAClient, nombres: list[str]) -> dict[str, Any] | None:
    """Los campos pedidos, releídos de HA (con la fuente y la versión).

    Solo los pedidos: la confirmación no tiene por qué devolver la ubicación
    de la casa si no se ha tocado (principio VIII). `None` si la relectura
    falla: lo escrito ya está escrito y no se vuelve a intentar.
    """
    try:
        config = await leer_config(ha_client)
    except HAConnectionError:
        return None
    out = {c: config.get(c) for c in nombres}
    if "unit_system" in nombres and "unit_system_detail" in config:
        out["unit_system_detail"] = config["unit_system_detail"]
    out["config_source"] = config.get("config_source")
    out["version"] = config.get("version")
    return redact_structure(out)
