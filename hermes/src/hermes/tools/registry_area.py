"""Hermes — Tools MCP para Area Registry.

Usa los comandos WS `config/area_registry/*` de HA.

Campos clave de una entry del area registry:
  area_id (slug generado por HA), name, icon, picture, aliases (list),
  floor_id, labels (list), humidity_entity_id, temperature_entity_id.

aliases y labels son listas de strings, nunca strings sueltos.
floor_id es el id del floor (planta) asignado al área, o null.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    validate_confirmation_token,
)
from hermes.tools._validation import build_ws_payload
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)


def _validate_area_fields(fields: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Valida y normaliza campos de área."""
    out: dict[str, Any] = {}
    for k, v in fields.items():
        if k == "aliases":
            if v is not None and not isinstance(v, list):
                return {}, "aliases must be a list of strings"
            out[k] = [str(a).strip() for a in v if str(a).strip()] if v else []
        elif k == "labels":
            if not isinstance(v, list):
                return {}, "labels must be a list of strings"
            out[k] = [str(lbl) for lbl in v]
        elif k == "name":
            if not isinstance(v, str) or not v.strip():
                return {}, "name must be a non-empty string"
            out[k] = v
        elif k in ("icon", "picture", "floor_id",
                   "humidity_entity_id", "temperature_entity_id"):
            out[k] = v  # str or None
        else:
            out[k] = v
    return out, None


async def _count_area_dependents(
    ha_client: HAClient, area_id: str
) -> dict[str, int]:
    """Cuenta entities y devices asociados al área."""
    entities_count = 0
    devices_count = 0
    try:
        raw_ents: Any = await ha_client.ws_send(
            {"type": "config/entity_registry/list"}
        )
        if isinstance(raw_ents, list):
            entities_count = sum(
                1 for e in raw_ents if e.get("area_id") == area_id
            )
    except HAConnectionError:
        pass
    try:
        raw_devs: Any = await ha_client.ws_send(
            {"type": "config/device_registry/list"}
        )
        if isinstance(raw_devs, list):
            devices_count = sum(
                1 for d in raw_devs if d.get("area_id") == area_id
            )
    except HAConnectionError:
        pass
    return {"entities_orphaned": entities_count, "devices_orphaned": devices_count}


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de area registry."""

    ready = requires_ready(ha_client)

    # ── ha_list_areas ─────────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_areas() -> object:
        """Lista todas las áreas del area registry.

        Las áreas suelen ser pocas (decenas como máximo), no se aplica
        truncado.

        Returns:
            JSON con {
              "count": int,
              "areas": [
                {
                  "area_id": "salon",
                  "name": "Salón",
                  "icon": "mdi:sofa",
                  "picture": null,
                  "aliases": [],
                  "floor_id": "planta_baja",
                  "labels": []
                }, ...
              ]
            }
        """
        try:
            raw: Any = await ha_client.ws_send(
                {"type": "config/area_registry/list"}
            )
        except HAConnectionError as exc:
            logger.error("ha_list_areas_ws_error", error=str(exc))
            return json.dumps({"error": str(exc)})

        items: list[dict] = raw if isinstance(raw, list) else []
        logger.info("ha_list_areas_ok", count=len(items))
        return json.dumps({"count": len(items), "areas": items}, ensure_ascii=False)

    # ── ha_get_area ───────────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_get_area(area_id: str) -> object:
        """Devuelve la entry del area registry para un área.

        Args:
            area_id: ID del área (slug generado por HA, ej. "salon",
                     "dormitorio_principal").

        Returns:
            JSON con la entry del área, o {"error": "not_found"}.
        """
        try:
            raw: Any = await ha_client.ws_send(
                {"type": "config/area_registry/list"}
            )
        except HAConnectionError as exc:
            logger.error(
                "ha_get_area_ws_error", area_id=area_id, error=str(exc)
            )
            return json.dumps({"error": str(exc)})

        items: list[dict] = raw if isinstance(raw, list) else []
        entry = next((a for a in items if a.get("area_id") == area_id), None)
        if entry is None:
            return json.dumps({"error": "not_found", "area_id": area_id})

        logger.info("ha_get_area_ok", area_id=area_id)
        return json.dumps(entry, ensure_ascii=False)

    # ── ha_create_area ────────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_create_area(
        name: str,
        icon: str | None = None,
        floor_id: str | None = None,
        aliases: list[str] | None = None,
        labels: list[str] | None = None,
        picture: str | None = None,
    ) -> object:
        """Crea una nueva área en el area registry.

        No requiere confirmation_token (creación no destructiva). HA genera
        el area_id automáticamente desde slugify(name).

        Args:
            name:     Nombre del área (ej. "Salón", "Dormitorio Principal").
            icon:     Icono MDI (ej. "mdi:sofa"). Opcional.
            floor_id: ID del floor/planta al que pertenece. Opcional.
            aliases:  Lista de nombres alternativos para el área. Opcional.
            labels:   Lista de labels. Opcional.
            picture:  Ruta a imagen del área. Opcional.

        Returns:
            JSON con la entry creada, incluyendo el area_id generado por HA.
            {"area_id": "salon", "name": "Salón", ...}
        """
        if not name or not name.strip():
            return json.dumps({"error": "name must be a non-empty string"})

        payload: dict[str, Any] = {
            "type": "config/area_registry/create",
            "name": name,
        }
        if icon is not None:
            payload["icon"] = icon
        if floor_id is not None:
            payload["floor_id"] = floor_id
        if aliases is not None:
            payload["aliases"] = [
                str(a).strip() for a in aliases if str(a).strip()
            ]
        if labels is not None:
            payload["labels"] = [str(lbl) for lbl in labels]
        if picture is not None:
            payload["picture"] = picture

        try:
            raw: Any = await ha_client.ws_send(payload)
        except HAConnectionError as exc:
            logger.error("ha_create_area_ws_error", name=name, error=str(exc))
            return json.dumps({"error": str(exc)})

        logger.info(
            "ha_create_area_ok",
            name=name,
            area_id=raw.get("area_id") if isinstance(raw, dict) else None,
        )
        return json.dumps(raw, ensure_ascii=False)

    # ── ha_update_area ────────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_update_area(
        area_id: str,
        updates: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Actualiza parcialmente un área del area registry.

        Campos soportados en `updates`:
          name (str)              — Nuevo nombre del área.
          icon (str|null)         — Icono MDI. null = sin icono.
          picture (str|null)      — Ruta a imagen. null = sin imagen.
          floor_id (str|null)     — Asignar a planta. null = desasignar.
          aliases (list[str])     — Lista de nombres alternativos. [] = limpiar.
          labels (list[str])      — Lista de labels. [] = limpiar.
          humidity_entity_id (str|null)     — Entidad de humedad del área.
          temperature_entity_id (str|null)  — Entidad de temperatura del área.

        Si no se pasa confirmation_token, devuelve preview + token.

        Args:
            area_id:            ID del área a actualizar.
            updates:            Dict con los campos a cambiar.
            confirmation_token: Token obtenido en llamada previa sin token.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token válido: {"result": "ok", ...entry actualizada...}
            Error: {"error": "..."}
        """
        normalized, err = _validate_area_fields(updates)
        if err:
            return json.dumps({"error": err})
        if not normalized:
            return json.dumps({"error": "updates is empty"})

        args = {"area_id": area_id, "updates": normalized}

        if not confirmation_token:
            try:
                raw_list: Any = await ha_client.ws_send(
                    {"type": "config/area_registry/list"}
                )
                all_areas: list[dict] = raw_list if isinstance(raw_list, list) else []
                current = next(
                    (a for a in all_areas if a.get("area_id") == area_id), None
                )
            except HAConnectionError as exc:
                current = None
                logger.warning(
                    "ha_update_area_preview_read_failed",
                    area_id=area_id,
                    error=str(exc),
                )

            preview = {
                "area_id": area_id,
                "current": current,
                "proposed_changes": normalized,
                "requires_confirmation": True,
            }
            token_data = await create_confirmation_token(
                "ha_update_area", args, preview=preview
            )
            return json.dumps(token_data, ensure_ascii=False)

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_update_area", args
        )
        if not valid:
            logger.warning(
                "ha_update_area_token_invalid", area_id=area_id, reason=error
            )
            return json.dumps({"error": error})

        payload = build_ws_payload(
            "config/area_registry/update",
            {"area_id": area_id},
            normalized,
        )

        try:
            raw: Any = await ha_client.ws_send(payload)
        except HAConnectionError as exc:
            logger.error(
                "ha_update_area_ws_error", area_id=area_id, error=str(exc)
            )
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return json.dumps({"error": str(exc)})

        await complete_confirmation_token(
            confirmation_token, success=True, result=raw
        )
        logger.info("ha_update_area_ok", area_id=area_id)
        result: dict[str, Any] = {"result": "ok"}
        if isinstance(raw, dict):
            result.update(raw)
        return json.dumps(result, ensure_ascii=False)

    # ── ha_delete_area ────────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_delete_area(
        area_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Elimina un área del area registry.

        IMPORTANTE: cuando se elimina un área, HA desasocia automáticamente
        todas las entities y devices que la tenían asignada (su area_id queda
        a null). El preview incluye el número de entities y devices afectados.

        Siempre requiere confirmation_token.

        Args:
            area_id:            ID del área a eliminar.
            confirmation_token: Token obtenido en llamada previa sin token.

        Returns:
            Sin token: {
              "confirmation_token": "...",
              "preview": {
                "area_id": "...",
                "current": {...},
                "impact": {"entities_orphaned": N, "devices_orphaned": M}
              }
            }
            Con token válido: {"result": "ok"}
            Error: {"error": "..."}
        """
        args = {"area_id": area_id}

        if not confirmation_token:
            # Fetch current area
            try:
                raw_list: Any = await ha_client.ws_send(
                    {"type": "config/area_registry/list"}
                )
                all_areas: list[dict] = raw_list if isinstance(raw_list, list) else []
                current = next(
                    (a for a in all_areas if a.get("area_id") == area_id), None
                )
            except HAConnectionError as exc:
                current = None
                logger.warning(
                    "ha_delete_area_preview_read_failed",
                    area_id=area_id,
                    error=str(exc),
                )

            # Count dependents
            impact = await _count_area_dependents(ha_client, area_id)

            preview = {
                "area_id": area_id,
                "current": current,
                "impact": impact,
                "warning": (
                    f"Deleting this area will orphan {impact['entities_orphaned']} "
                    f"entities and {impact['devices_orphaned']} devices "
                    "(their area_id will be set to null automatically by HA)."
                ),
            }
            token_data = await create_confirmation_token(
                "ha_delete_area", args, preview=preview
            )
            return json.dumps(token_data, ensure_ascii=False)

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_delete_area", args
        )
        if not valid:
            logger.warning(
                "ha_delete_area_token_invalid", area_id=area_id, reason=error
            )
            return json.dumps({"error": error})

        try:
            await ha_client.ws_send(
                {"type": "config/area_registry/delete", "area_id": area_id}
            )
        except HAConnectionError as exc:
            logger.error(
                "ha_delete_area_ws_error", area_id=area_id, error=str(exc)
            )
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return json.dumps({"error": str(exc)})

        await complete_confirmation_token(
            confirmation_token, success=True, result={"result": "ok"}
        )
        logger.info("ha_delete_area_ok", area_id=area_id)
        return json.dumps({"result": "ok"})
