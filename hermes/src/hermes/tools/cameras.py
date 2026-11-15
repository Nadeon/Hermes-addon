"""Hermes — Cámaras e imágenes (spec 024, tramo 1, CAP-059).

Familia `cameras`. Dos tools de solo lectura que devuelven una IMAGEN (un
bloque `ImageContent` del protocolo MCP) y sus metadatos:

- `ha_get_camera_snapshot`: la instantánea de una entidad `camera.*`
  (`GET /api/camera_proxy/{entity_id}`).
- `ha_get_image_entity`: la imagen de una entidad `image.*`
  (`GET /api/image_proxy/{entity_id}`).

POR QUÉ ASÍ (research R-2)
--------------------------
- Privacidad: una cámara enseña el interior de la casa y la imagen viaja al
  cliente MCP. Las descripciones lo dicen y la familia se puede apagar sola.
- La imagen va por REST de Core con el token de Hermes: no hace falta el
  `access_token` de la entidad (que es un secreto: el atributo
  `access_token` y el `entity_picture?token=…`). Estas tools no leen el
  estado de la entidad, así que ninguna URL firmada puede salir en la
  respuesta.
- Hermes no reduce imágenes (no añade Pillow). La cámara se pide reducida a
  Core (`width`/`height`), que solo escala JPEG; `image_proxy` no escala. Un
  tope fijo de 2 MiB, que no es argumento, evita que una imagen enorme se
  lleve el contexto del cliente: si se pasa, error y ninguna imagen (cortada
  no se podría decodificar).
- Solo se devuelve algo cuyo `Content-Type` sea `image/*`: una página de
  error con 200 no es una imagen.
- El `entity_id` se valida con el patrón de su dominio antes de pedir nada:
  se interpola en la ruta.
- El log lleva `tool`, `entity_id`, `bytes` y el resultado; nunca la URL, los
  parámetros ni la imagen.
- El guardián central de `response_max_bytes` (`mcp_server._limitar`) solo
  actúa sobre respuestas de texto: una respuesta con imagen pasa intacta, y
  el tope de bytes de aquí es el que la limita.
"""

from __future__ import annotations

import asyncio
import math
import re
import struct
from typing import Any

import aiohttp
import structlog
from mcp.server.mcpserver.utilities.types import Image

from hermes.ha import HAClient, HAConnectionError, ImageTooLargeError
from hermes.identifiers import InvalidIdentifier, validate_path_segment
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)

# Tope fijo de bytes crudos de la imagen (research R-2). En base64 son unos
# 2,7 MB, por debajo del límite habitual de imagen de los clientes MCP. No es
# argumento: un cliente no debe poder pedir 50 MB.
_MAX_IMAGE_BYTES = 2 * 1024 * 1024

_MIN_WIDTH = 64
_MAX_WIDTH = 1920

# Patrones de `entity_id` por dominio. Más estrictos que el de HA (que admite
# mayúsculas en algunos caminos): basta para lo que Core crea y deja fuera
# cualquier `/`, `.` o `?` que cambiaría la ruta.
_PATRONES = {
    "camera": re.compile(r"^camera\.[a-z0-9_]+$"),
    "image": re.compile(r"^image\.[a-z0-9_]+$"),
}

_ESCALADO_CAMARA = "requested from Home Assistant; it only scales JPEG"
_ESCALADO_IMAGEN = "not scaled: Home Assistant serves the original"


def _invalido(campo: str, detalle: str) -> dict[str, Any]:
    return {"error": "invalid_argument", "field": campo, "detail": detalle}


def _validar_entity_id(entity_id: Any, dominio: str) -> dict[str, Any] | None:
    detalle = (f"must be a {dominio} entity id like '{dominio}.name' "
               "(lowercase letters, digits and underscores)")
    if not isinstance(entity_id, str) or not _PATRONES[dominio].match(entity_id):
        return _invalido("entity_id", detalle)
    # Cinturón y tirantes: la comprobación común de un tramo de ruta, la
    # misma que usan el resto de módulos que interpolan un valor del cliente.
    try:
        validate_path_segment(entity_id, field="entity_id")
    except InvalidIdentifier:
        return _invalido("entity_id", detalle)
    return None


def _validar_max_width(max_width: Any) -> dict[str, Any] | None:
    # `bool` es subclase de `int`: `True` no es un ancho.
    if (
        isinstance(max_width, bool)
        or not isinstance(max_width, int)
        or not _MIN_WIDTH <= max_width <= _MAX_WIDTH
    ):
        return _invalido(
            "max_width", f"must be an integer between {_MIN_WIDTH} and {_MAX_WIDTH}")
    return None


# Marcadores SOFn de JPEG con las dimensiones (todos los C0…CF salvo DHT,
# JPG y DAC, que no son cabeceras de fotograma).
_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def _dimensiones(datos: bytes) -> tuple[int | None, int | None]:
    """Ancho y alto de la cabecera PNG (IHDR) o JPEG (primer SOFn).

    Solo para informar: si la cabecera no se entiende, `(None, None)` y la
    imagen se devuelve igual. Nunca lanza.
    """
    try:
        if datos[:8] == b"\x89PNG\r\n\x1a\n" and datos[12:16] == b"IHDR":
            ancho, alto = struct.unpack(">II", datos[16:24])
            return ancho, alto
        if datos[:2] == b"\xff\xd8":
            i = 2
            while i + 4 <= len(datos):
                if datos[i] != 0xFF:
                    return None, None
                marcador = datos[i + 1]
                if marcador == 0xFF:  # relleno entre marcadores
                    i += 1
                    continue
                if marcador in (0xD8, 0x01) or 0xD0 <= marcador <= 0xD7:
                    i += 2
                    continue
                largo = struct.unpack(">H", datos[i + 2:i + 4])[0]
                if marcador in _SOF:
                    alto, ancho = struct.unpack(">HH", datos[i + 5:i + 9])
                    return ancho, alto
                if marcador == 0xDA or largo < 2:  # empieza la imagen o basura
                    return None, None
                i += 2 + largo
    except (struct.error, IndexError):
        # JPEG truncado o corrupto: sin dimensiones, como si no tuviera SOF.
        pass
    return None, None


def _formato(content_type: str) -> str:
    """`image/jpeg` → `jpeg`: el `Image` del SDK rehace el MIME con esto."""
    return content_type.split("/", 1)[1]


def register(
    mcp: object,
    ha_client: HAClient,
    *,
    response_max_bytes: int,
) -> None:
    """Registra las tools de cámaras e imágenes.

    `response_max_bytes` se recibe por uniformidad con el resto de módulos,
    pero no aplica: mide el JSON de texto, y estas respuestas son una imagen
    con su propio tope (`_MAX_IMAGE_BYTES`) y unos metadatos de pocos bytes.
    """
    del response_max_bytes
    ready = requires_ready(ha_client)

    async def _leer(
        tool: str,
        entity_id: str,
        ruta: str,
        params: dict[str, str] | None,
        no_disponible: str,
        extra: dict[str, Any],
    ) -> object:
        def rechazo(error: dict[str, Any]) -> dict[str, Any]:
            logger.info("camera_image_read", tool=tool, entity_id=entity_id,
                        bytes=0, outcome=f"rejected:{error['error']}")
            return error

        try:
            tipo, datos = await ha_client.rest_get_image(
                ruta, params=params, max_bytes=_MAX_IMAGE_BYTES)
        except ImageTooLargeError:
            return rechazo({
                "error": "image_too_large", "max_bytes": _MAX_IMAGE_BYTES,
                "detail": "the image is larger than the limit and is not returned",
            })
        except HAConnectionError as exc:
            if exc.status == 404:
                return rechazo({"error": "not_found", "entity_id": entity_id})
            if exc.status == 503:
                return rechazo({"error": no_disponible, "entity_id": entity_id})
            if exc.status is not None:
                return rechazo({"error": "snapshot_failed", "status": exc.status,
                                "entity_id": entity_id})
            return rechazo({"error": "ha_unavailable"})
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return rechazo({"error": "ha_unavailable"})

        if not tipo.startswith("image/") or len(tipo) <= len("image/"):
            return rechazo({"error": "unsupported_content_type",
                            "content_type": tipo or None})

        ancho, alto = _dimensiones(datos)
        meta: dict[str, Any] = {
            "entity_id": entity_id,
            "content_type": tipo,
            "bytes": len(datos),
            "width": ancho,
            "height": alto,
            **extra,
        }
        logger.info("camera_image_read", tool=tool, entity_id=entity_id,
                    bytes=len(datos), outcome="ok")
        return [meta, Image(data=datos, format=_formato(tipo))]

    @mcp.tool()
    @ready
    async def ha_get_camera_snapshot(entity_id: str, max_width: int = 640) -> object:
        """Return a still image of what a camera sees right now.

        PRIVACY: this is the live view of the camera; it may show the inside
        of the home, and the image is sent to this MCP client. Read-only.
        Returns two blocks: metadata ({entity_id, content_type, bytes, width,
        height, requested_max_width, scaling}) and the image itself.

        Home Assistant is asked for an image about `max_width` pixels wide
        (and 9/16 of that high); it only scales JPEG, so the image may be
        larger. Images over 2 MiB are not returned (`image_too_large`).
        Cloud cameras fetch the image from the internet. Stream preferences
        (preload, orientation) go through
        `ha_read_ws_command("camera/get_prefs")` /
        `ha_call_ws_command("camera/update_prefs")`.

        Args:
            entity_id: The camera, for example "camera.front_door".
            max_width: Width to ask Home Assistant for, 64 to 1920
                (default 640).

        Returns:
            [metadata, image], or {"error": ...}: invalid_argument,
            not_found, camera_unavailable (camera off), snapshot_failed
            (with status), unsupported_content_type, image_too_large (with
            max_bytes) or ha_unavailable.
        """
        tool = "ha_get_camera_snapshot"
        error = _validar_entity_id(entity_id, "camera") or _validar_max_width(max_width)
        if error:
            logger.info("camera_image_read", tool=tool, entity_id=None,
                        bytes=0, outcome="rejected:invalid_argument")
            return error
        alto = math.ceil(max_width * 9 / 16)
        return await _leer(
            tool, entity_id, f"/camera_proxy/{entity_id}",
            {"width": str(max_width), "height": str(alto)},
            "camera_unavailable",
            {"requested_max_width": max_width, "scaling": _ESCALADO_CAMARA},
        )

    @mcp.tool()
    @ready
    async def ha_get_image_entity(entity_id: str) -> object:
        """Return the current image of an `image.*` entity.

        PRIVACY: the image is sent to this MCP client. Read-only. Returns two
        blocks: metadata ({entity_id, content_type, bytes, width, height,
        scaling}) and the image itself. Home Assistant serves it unscaled;
        images over 2 MiB are not returned (`image_too_large`). Some image
        entities download it from the internet.

        Args:
            entity_id: The image entity, for example "image.qr_code".

        Returns:
            [metadata, image], or {"error": ...}: invalid_argument,
            not_found, image_unavailable, snapshot_failed (with status),
            unsupported_content_type, image_too_large (with max_bytes) or
            ha_unavailable.
        """
        tool = "ha_get_image_entity"
        error = _validar_entity_id(entity_id, "image")
        if error:
            logger.info("camera_image_read", tool=tool, entity_id=None,
                        bytes=0, outcome="rejected:invalid_argument")
            return error
        return await _leer(
            tool, entity_id, f"/image_proxy/{entity_id}", None,
            "image_unavailable", {"scaling": _ESCALADO_IMAGEN},
        )
