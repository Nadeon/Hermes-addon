"""Validación central de identificadores que se interpolan en URLs.

Defensa anti path-injection. Slugs de add-on/backup, entry_id, flow_id y
job_id provienen del cliente MCP y se interpolan en paths REST del Supervisor
o del core de HA (p. ej. ``/addons/{slug}/restart``). Estos validadores
garantizan que un valor malicioso (``../../core/restart``, ``foo/bar``, CRLF…)
no pueda escapar del endpoint previsto.

Es la primera de dos capas: la segunda es ``_assert_safe_request_path`` en
``hermes.ha``, que rechaza cualquier path con traversal aunque una tool
olvide validar aquí.
"""

from __future__ import annotations

import structlog as _structlog

# La definición vive en `hermes.identifiers`, un módulo neutral, porque
# `hermes.ha` también la necesita y no puede importar de este paquete
# (importar un submódulo ejecuta el `__init__`, que importa `hermes.ha`).
# Aquí se reexporta para no cambiar los sitios de llamada.
from hermes.identifiers import (  # noqa: F401
    InvalidIdentifier,
    _ID_RE,
    _SLUG_RE,
    validate_identifier,
    validate_path_segment,
    validate_slug,
)


def identifier_error(exc: InvalidIdentifier) -> dict[str, str]:
    """Construye la respuesta de error estándar para un identificador inválido."""
    return {"error": "invalid_identifier", "detail": str(exc)}


# ── Sobre de los comandos WebSocket ──────────────────────────────────────────


_ws_logger = _structlog.get_logger(__name__)

# Claves que definen QUÉ comando se ejecuta. Nunca pueden venir del cliente.
RESERVED_WS_FIELDS: frozenset[str] = frozenset({"type", "id"})


def build_ws_payload(
    command: str,
    envelope: dict,
    user_fields: dict | None = None,
) -> dict:
    """Construye un payload WS con el comando a prueba de sobrescritura.

    Los campos del cliente van PRIMERO y el sobre se afirma DESPUÉS. Montado al
    revés —sobre primero y `payload.update(<dict del cliente>)` después—, un
    argumento llamado `type` reemplazaría el comando entero y convertiría, por
    ejemplo, una tool de actualización en una de borrado, esquivando la tool
    dedicada y su confirmación. No se puede confiar en que los validadores lo
    frenen: los de registry_* acaban en `else: out[k] = v` ("HA ya validará") y
    en lovelace no hay validador.

    Las claves reservadas que vienen del cliente se descartan y se registran:
    descartar es más seguro que fallar (no da un oráculo al atacante) y no
    rompe una llamada por lo demás válida, pero el log deja constancia de que
    alguien lo intentó.

    `id` se incluye por simetría aunque hoy no sea explotable —`ws_send` lo
    reasigna tras copiar el payload—: depender de ese detalle de otra capa es
    justo el tipo de suposición que esta defensa existe para no hacer.
    """
    payload: dict = {}
    if user_fields:
        intruders = sorted(RESERVED_WS_FIELDS & set(user_fields))
        if intruders:
            _ws_logger.warning(
                "ws_reserved_field_dropped",
                command=command,
                fields=intruders,
                reason="client tried to redefine the websocket command",
            )
        payload.update(
            {k: v for k, v in user_fields.items() if k not in RESERVED_WS_FIELDS}
        )
    payload.update(envelope)
    payload["type"] = command
    return payload
