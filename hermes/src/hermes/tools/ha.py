"""Hermes — Tools MCP para acceso a estados y servicios de HA."""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import structlog

import hermes.fs as _fs
from hermes import service_policy as _policy
from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    validate_confirmation_token,
)
from hermes.tools._common import requires_ready
from hermes.tools._validation import InvalidIdentifier, identifier_error

logger = structlog.get_logger(__name__)

_FILTERED_ATTRIBUTES = {
    "entity_picture",
    "icon",
    "supported_features",
    "supported_color_modes",
    "effect_list",
    "min_color_temp_kelvin",
    "max_color_temp_kelvin",
}


def _compact_state(state: dict[str, Any]) -> dict[str, Any]:
    """Compacta un estado de HA eliminando campos redundantes o pesados."""
    if not isinstance(state, dict):
        return state

    compacted: dict[str, Any] = dict(state)
    compacted.pop("context", None)

    if compacted.get("last_reported") == compacted.get("last_updated"):
        compacted.pop("last_reported", None)

    attrs = compacted.get("attributes")
    if isinstance(attrs, dict):
        compact_attrs: dict[str, Any] = {}
        for key, value in attrs.items():
            if key in _FILTERED_ATTRIBUTES:
                continue
            if value is None:
                continue
            compact_attrs[key] = value
        compacted["attributes"] = compact_attrs

    return compacted


# ── Call-service denylist ─────────────────────────────────────────────────────

# Servicios que siempre exigen confirmation_token.
# Formato: "domain.service" o "domain.*" (wildcard solo en service).
# La denylist vive en hermes.service_policy, para que la apliquen a la vez la
# tool y el cliente. Se re-exporta aquí porque es el nombre por el que la
# conocen los tests y el resto del paquete.
CALL_SERVICE_DENYLIST = _policy.CALL_SERVICE_DENYLIST

# Claves en service_data que podrían contener paths a ficheros
_SUSPICIOUS_KEYS: frozenset[str] = frozenset({
    "file", "attachment", "attachments", "url", "path",
    "filename", "source", "media_content_id", "image", "photo",
})

_PATH_LIKE_RE = re.compile(
    r"^(\.?\.?/|/|[A-Za-z]:\\|\\\\|~/).*"
    r"|.*\.(yaml|yml|json|txt|log|conf|ini|env|key|pem|crt|pfx|p12|db)$"
)


def _looks_like_path(value: str) -> bool:
    """Heurístico: ¿parece este string un path de fichero?"""
    return bool(_PATH_LIKE_RE.match(value))


def _is_in_denylist(domain: str, service: str, denylist: frozenset[str]) -> bool:
    """Delega en hermes.service_policy (ver allí el porqué de la mudanza)."""
    return _policy.is_in_denylist(domain, service, denylist)


def sanitize_service_data(
    data: Any,
    depth: int = 0,
) -> tuple[bool, str | None]:
    """Recorre service_data buscando paths a ficheros blacklisteados.

    Returns:
        (True, None) si es seguro.
        (False, error_message) si detecta un path sospechoso.
    """
    if depth > 10:
        return False, "service_data too deeply nested"

    if isinstance(data, dict):
        items: Any = data.items()
    elif isinstance(data, list):
        items = enumerate(data)
    else:
        return True, None

    for key, value in items:
        if isinstance(value, str) and str(key).lower() in _SUSPICIOUS_KEYS:
            if _looks_like_path(value):
                # Intentar resolver contra bases conocidas
                for base in ["/homeassistant", "/share", "/ssl"]:
                    try:
                        base_path = Path(base)
                        if value.startswith("/"):
                            candidate = Path(value).resolve()
                        else:
                            candidate = (base_path / value).resolve()
                        bl, _ = _fs.check_blacklisted(candidate)
                        if bl:
                            return False, (
                                f"service_data references blacklisted path: {value!r}"
                            )
                    except (ValueError, OSError):
                        pass
                # También verificar directamente si el nombre está en la blacklist
                try:
                    candidate = Path(value)
                    if candidate.name:
                        import hermes.fs as _fsmod
                        for name in _fsmod.BLACKLIST_NAMES:
                            if candidate.name == Path(name).name:
                                return False, (
                                    f"service_data references sensitive file: {value!r}"
                                )
                except (ValueError, TypeError):
                    pass

        elif isinstance(value, (dict, list)):
            ok, err = sanitize_service_data(value, depth + 1)
            if not ok:
                return False, err

    return True, None


# ── Auto-clasificación de scripts/automations peligrosos ─────────────────────

# El set vive en hermes.service_policy para que el cliente pueda consultarlo.
# Se re-exporta el nombre porque los tests lo importan de aquí.
_auto_restricted = _policy._auto_restricted


# Claves con las que un paso de script/automatización nombra el servicio a
# ejecutar. `service` es la forma histórica; `action` es la estándar desde HA
# 2024.8 y la que escribe la propia interfaz, y `perform_action` es el alias que
# introdujo la misma versión. Hay que mirar las tres: escanear solo `service`
# deja que un script escrito con la sintaxis moderna —la normal hoy— cuele un
# `shell_command.*` sin que se clasifique como peligroso.
_SERVICE_CALL_KEYS: frozenset[str] = frozenset({"service", "action", "perform_action"})

# Variantes con plantilla: no se pueden analizar estáticamente, se marcan siempre.
_SERVICE_TEMPLATE_KEYS: frozenset[str] = frozenset(
    {"service_template", "action_template"}
)


def _scan_for_dangerous_services(
    data: Any,
    denylist: frozenset[str],
    depth: int = 0,
) -> bool:
    """Recursivamente busca calls a servicios peligrosos en una estructura YAML.

    Returns True si encontró algún servicio peligroso.
    """
    if depth > 20:
        return False
    if isinstance(data, dict):
        for key, value in data.items():
            if key in _SERVICE_CALL_KEYS and isinstance(value, str):
                # Una plantilla no se puede analizar estáticamente: se marca.
                if "{{" in value or "{%" in value:
                    return True
                if "." in value:
                    domain, svc = value.split(".", 1)
                    if _is_in_denylist(domain, svc, denylist):
                        return True
            elif key in _SERVICE_TEMPLATE_KEYS:
                # Esquiva pattern matching estático → marcar siempre
                return True
            elif isinstance(value, (dict, list)):
                if _scan_for_dangerous_services(value, denylist, depth + 1):
                    return True
    elif isinstance(data, list):
        for item in data:
            if _scan_for_dangerous_services(item, denylist, depth + 1):
                return True
    return False


def _slugify(text: str) -> str:
    """Convierte un alias a un slug de entity_id, como hace HA."""
    slug = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\s-]", "", slug).lower()
    slug = re.sub(r"[-\s]+", "_", slug).strip("_")
    return slug


def _classify_scripts_file(
    scripts_data: Any,
    denylist: frozenset[str],
) -> list[str]:
    """Extrae entity_ids de scripts peligrosos de scripts.yaml parseado."""
    restricted: list[str] = []
    if not isinstance(scripts_data, dict):
        return restricted
    for key, value in scripts_data.items():
        if not isinstance(value, dict):
            continue
        if _scan_for_dangerous_services(value, denylist):
            restricted.append(f"script.{key}")
    return restricted


def _classify_automations_file(
    automations_data: Any,
    denylist: frozenset[str],
) -> list[str]:
    """Extrae entity_ids de automations peligrosas de automations.yaml parseado."""
    restricted: list[str] = []
    if not isinstance(automations_data, list):
        return restricted
    for item in automations_data:
        if not isinstance(item, dict):
            continue
        if _scan_for_dangerous_services(item, denylist):
            # Intentar obtener entity_id
            alias = item.get("alias", "")
            item_id = item.get("id", "")
            if alias:
                slug = _slugify(str(alias))
                if slug:
                    restricted.append(f"automation.{slug}")
            elif item_id:
                restricted.append(f"automation.{item_id}")
    return restricted


def _auto_classify_sync(denylist: frozenset[str]) -> list[str]:
    """Escanea scripts.yaml y automations.yaml buscando calls peligrosos.

    Returns lista de entity_ids auto-restringidos.
    """
    config_base = _fs.CONFIG_BASE
    restricted: list[str] = []

    import yaml

    for filename, classifier in [
        ("scripts.yaml", _classify_scripts_file),
        ("automations.yaml", _classify_automations_file),
    ]:
        filepath = config_base / filename
        if not filepath.exists():
            continue
        try:
            with open(filepath, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            results = classifier(data, denylist)
            restricted.extend(results)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "auto_classify_scan_error",
                file=filename,
                error=str(exc),
            )

    return restricted


def classify_saved_config(entity_id: str, config: dict) -> bool:
    """Clasifica AL VUELO la config que se acaba de guardar.

    La re-clasificación general solo ocurre al arrancar y tras un `reload` hecho
    a través de `ha_call_service`. Los caminos normales de creación
    —`ha_create_or_update_script` y `ha_create_or_update_automation`, que usan
    `config_save` y hacen que HA recargue sola— no pasan por ninguno de los dos,
    así que sin esta llamada un script recién creado con `shell_command.*`
    quedaría SIN restringir hasta el siguiente reinicio del add-on.

    Se clasifica el dict recibido en vez de releer el YAML del disco: es
    inmediato y no depende de cuándo escriba HA el fichero.

    Devuelve True si la entidad ha quedado marcada como restringida.
    """
    if not isinstance(config, dict) or not entity_id:
        return False
    if _scan_for_dangerous_services(config, CALL_SERVICE_DENYLIST):
        _policy.add_auto_restricted_entity(entity_id)
        logger.info("auto_classify_on_save", entity_id=entity_id, restricted=True)
        return True
    return False


async def auto_classify_dangerous(denylist: frozenset[str]) -> list[str]:
    """Async: escanea y actualiza el set de entity_ids auto-restringidos."""
    global _auto_restricted
    restricted = await asyncio.to_thread(_auto_classify_sync, denylist)
    new_entities = [e for e in restricted if e not in _auto_restricted]
    _auto_restricted.update(restricted)
    if new_entities:
        logger.info(
            "auto_classify_restricted",
            count=len(restricted),
            new=new_entities,
        )
    return restricted


def get_auto_restricted_entities() -> frozenset[str]:
    """Devuelve snapshot del set de entidades auto-restringidas."""
    return _policy.get_auto_restricted_entities()


# ══════════════════════════════════════════════════════════════════════════════
# Registro de tools
# ══════════════════════════════════════════════════════════════════════════════

def register(
    mcp: object,
    ha_client: HAClient,
    call_service_denylist_extra: list[str] | None = None,
    call_service_restricted_entities: list[str] | None = None,
    call_service_auto_classify: bool = True,
) -> None:
    """Registra las tools que exponen estados y servicios."""

    ready = requires_ready(ha_client)

    # Construir denylist efectiva
    effective_denylist: frozenset[str] = CALL_SERVICE_DENYLIST
    if call_service_denylist_extra:
        effective_denylist = effective_denylist | frozenset(call_service_denylist_extra)

    # Añadir entidades restringidas por config
    if call_service_restricted_entities:
        _auto_restricted.update(call_service_restricted_entities)

    # Auto-clasificación al boot (no bloquea el arranque)
    if call_service_auto_classify:
        async def _boot_classify() -> None:
            try:
                await auto_classify_dangerous(effective_denylist)
            except Exception as exc:  # noqa: BLE001
                logger.warning("auto_classify_boot_error", error=str(exc))

        asyncio.ensure_future(_boot_classify())

    @mcp.tool()
    @ready
    async def ha_get_states(
        domain: str | None = None,
        compact: bool = True,
    ) -> object:
        """Lista estados de entidades. Filtra SIEMPRE por domain si puedes.

        Sin `domain` devuelve la instalación entera y la respuesta se trunca.
        Para una sola entidad usa ha_get_state; para contar o agregar sobre
        muchas, ha_render_template resuelve en el lado de HA y gasta mucho menos.

        Args:
            domain (str, opcional): Dominio HA para filtrar. Ej: 'sensor', 'light', 'climate'.
            compact (bool, opcional): Si es True, elimina campos redundantes y nulos.

        Nota:
            Si no se pasa domain, la lista completa puede ser muy grande.
            Usa `domain='light'` para limitar el resultado.
        """
        states = await ha_client.get_states()
        if domain:
            normalized = domain.strip().lower()
            states = [
                state
                for state in states
                if isinstance(state, dict)
                and isinstance(state.get("entity_id"), str)
                and state["entity_id"].startswith(f"{normalized}.")
            ]

        result = [_compact_state(state) for state in states] if compact else states
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))

    @mcp.tool()
    @ready
    async def ha_get_state(entity_id: str, compact: bool = True) -> object:
        """Devuelve el estado de una entidad específica de Home Assistant.

        Args:
            entity_id (str): Identificador de entidad. Ej: 'sensor.temperatura' o 'light.cocina'.
            compact (bool, opcional): Si es True, elimina campos redundantes y nulos.

        Returns:
            dict: El estado de la entidad o un objeto vacío si no existe.

        Nota:
            Usa un entity_id completo como 'light.cocina' para evitar coincidencias ambiguas.
        """
        try:
            state = await ha_client.get_state(entity_id)
        except InvalidIdentifier as exc:
            # Sin esto, un entity_id con '/' o '%' sale como excepción cruda
            # y el cliente solo ve «Error executing tool», sin saber qué
            # corregir.
            return identifier_error(exc)
        if not state:
            return {}
        if compact:
            return _compact_state(state)
        return state

    @mcp.tool()
    @ready
    async def ha_list_services() -> object:
        """Lista los servicios disponibles en Home Assistant.

        Nota:
            El resultado puede ser extenso porque incluye todos los dominios y servicios.
        """
        return json.dumps(await ha_client.get_services(), ensure_ascii=False, separators=(",", ":"))

    @mcp.tool()
    @ready
    async def ha_call_service(
        domain: str,
        service: str,
        service_data: dict[str, object] | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Llama un servicio de Home Assistant.

        Algunos servicios peligrosos (shell_command, reloads, backups, etc.)
        requieren confirmation_token. Si se pasa sin token, devuelve un preview
        con el confirmation_token necesario.

        Servicios que requieren token: shell_command.*, python_script.*,
        homeassistant.reload_*, homeassistant.restart, mqtt.publish,
        lock.unlock, alarm_control_panel.alarm_disarm, y más.

        Args:
            domain (str): Dominio del servicio. Ej: 'light', 'switch'.
            service (str): Nombre del servicio. Ej: 'turn_on', 'set_temperature'.
            service_data (dict, opcional): Parámetros del servicio.
            confirmation_token (str, opcional): Token para servicios peligrosos.

        Nota:
            Esta tool ejecuta el servicio y no devuelve datos adicionales.
        """
        data = service_data or {}
        domain_lower = domain.strip().lower()
        service_lower = service.strip().lower()

        # Sanitización de service_data
        safe, san_err = sanitize_service_data(data)
        if not safe:
            return {"error": "unsafe_service_data", "detail": san_err}

        # Check denylist
        in_denylist = _is_in_denylist(domain_lower, service_lower, effective_denylist)

        # Check entidades restringidas. La comparación vive en service_policy
        # porque comparar el campo `entity_id` tal cual deja seis elusiones
        # abiertas —lista separada por comas, comodín `all`, `target` anidado,
        # mayúsculas y los targets indirectos por área o dispositivo— que HA sí
        # resuelve.
        entity_is_restricted = _policy.targets_restricted_entity(
            domain_lower, data, get_auto_restricted_entities()
        )

        needs_token = in_denylist or entity_is_restricted

        if needs_token:
            tool_name_cs = "ha_call_service"
            args_cs: dict[str, Any] = {
                "domain": domain_lower,
                "service": service_lower,
                "service_data": data,
            }

            if not confirmation_token:
                reason = (
                    f"Service '{domain_lower}.{service_lower}' requires confirmation "
                    f"({'denylist match' if in_denylist else 'auto-restricted entity'})."
                )
                preview: dict[str, Any] = {
                    "action": "call_service",
                    "domain": domain_lower,
                    "service": service_lower,
                    "service_data": data,
                    "reason": reason,
                }
                if entity_is_restricted:
                    # Los entity_id se re-extraen con la misma normalización que
                    # usó la comprobación, para que el preview enseñe justo lo
                    # que la disparó (incluidas listas separadas por comas).
                    restricted_auto = get_auto_restricted_entities()
                    preview["restricted_entities"] = sorted(
                        _policy._collect_entity_ids(data) & restricted_auto
                    ) or ["(objetivo indirecto: área, dispositivo o comodín)"]
                return await create_confirmation_token(tool_name_cs, args_cs, preview=preview)

            valid, error = await validate_confirmation_token(
                confirmation_token, tool_name_cs, args_cs
            )
            if not valid:
                return {"error": error}

            try:
                # Único punto que autoriza explícitamente un servicio vetado: se
                # llega aquí solo con un confirmation_token ya validado.
                result = await ha_client.call_service(
                    domain_lower, service_lower, data, allow_dangerous=True
                )
                await complete_confirmation_token(
                    confirmation_token, success=True, result={"called": True}
                )
                # Re-clasificar si fue un reload de scripts/automations
                if call_service_auto_classify and service_lower == "reload" and domain_lower in (
                    "automation", "script"
                ):
                    asyncio.ensure_future(auto_classify_dangerous(effective_denylist))
                return result
            except Exception as exc:  # noqa: BLE001
                await complete_confirmation_token(
                    confirmation_token, success=False, error=str(exc)
                )
                return {"error": str(exc)}

        return await ha_client.call_service(domain_lower, service_lower, data)

    @mcp.tool()
    @ready
    async def ha_call_service_response(
        domain: str,
        service: str,
        service_data: dict[str, object] | None = None,
    ) -> object:
        """Llama un servicio de Home Assistant y devuelve su respuesta si está soportado.

        Es la vía para servicios de consulta. NO acepta confirmation_token, así
        que los servicios de la denylist se rechazan sin llegar a ejecutarse,
        con {"error": "service_in_denylist"}. Para esos usa ha_call_service,
        que sí tiene el flujo de confirmación en dos pasos.

        Args:
            domain (str): Dominio del servicio. Ej: 'weather', 'calendar'.
            service (str): Nombre del servicio. Ej: 'get_forecasts', 'get_events'.
            service_data (dict, opcional): Parámetros del servicio. Ej: {'entity_id': 'weather.home'}.

        Nota:
            Muchos servicios no soportan `return_response=1`. Si no es
            soportado, se devuelve un bloque con la razón de fallo.
        """
        data = service_data or {}
        domain_lower = domain.strip().lower()
        service_lower = service.strip().lower()

        # Sanitización
        safe, san_err = sanitize_service_data(data)
        if not safe:
            return {"error": "unsafe_service_data", "detail": san_err}

        # ha_call_service_response no acepta confirmation_token (es para read-like ops).
        # Si el servicio está en la denylist, rechazar con hint.
        if _is_in_denylist(domain_lower, service_lower, effective_denylist):
            return {
                "error": "service_in_denylist",
                "hint": (
                    f"'{domain_lower}.{service_lower}' is in the service denylist. "
                    "Use ha_call_service with confirmation_token instead."
                ),
            }

        try:
            return await ha_client.call_service_response(domain_lower, service_lower, data)
        except HAConnectionError as exc:
            return {"error": "ha_call_service_response_failed", "details": str(exc)}
