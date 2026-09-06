"""Validación de los valores que se interpolan dentro de una ruta de la API.

Vive aquí, y no en `hermes.tools._validation`, porque `hermes.ha` también los
necesita y no puede importar de `hermes.tools`: importar un submódulo ejecuta
el `__init__` del paquete, que a su vez importa `hermes.ha`. Es el mismo motivo
por el que `service_policy` es un módulo neutral. `tools/_validation` reexporta
lo de aquí, así que sigue habiendo una sola definición.

Son la primera de dos capas. La segunda es `_assert_safe_request_path` en
`hermes.ha`, que rechaza traversal aunque una tool olvide validar. Esa segunda
capa ya impide lo grave —salir del endpoint previsto—, pero no impide que un
valor con `/` aterrice en un endpoint vecino, y sobre todo no comprueba nada
donde el valor no parece una ruta. De ahí que se valide también en el punto de
uso, que es donde se sabe qué forma debe tener cada cosa.
"""

from __future__ import annotations

import re

# Slugs de add-on / backup: letras, dígitos, '.', '_' y '-'. Sin '/', sin '..'.
# Debe empezar por alfanumérico. Máx 127 chars (los slugs reales son cortos).
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,126}$")

# IDs opacos (entry_id, flow_id, job_id): hex/alfanumérico con '_' y '-'.
# Más estricto que slug: no se permite '.'.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,126}$")

# Caracteres que convierten un valor en algo más que un tramo de ruta: abren
# un tramo nuevo, una query, un fragmento, o meten codificación que se
# resuelve más tarde. Ninguno aparece en un entity_id, un dominio o un
# servicio de Home Assistant.
_PELIGROSOS = ("/", "\\", "?", "#", "%", "..")


class InvalidIdentifier(ValueError):
    """Un identificador no supera la validación anti-inyección."""


def validate_slug(value: str, *, field: str = "slug") -> str:
    """Valida un slug de add-on o backup. Devuelve el valor o lanza."""
    if not isinstance(value, str) or ".." in value or not _SLUG_RE.match(value):
        raise InvalidIdentifier(
            f"Invalid {field!r}: only letters, digits, '.', '_' and '-' are "
            "allowed, must start alphanumeric, no '/' or '..' (max 127 chars)."
        )
    return value


def validate_identifier(value: str, *, field: str = "id") -> str:
    """Valida un id opaco (entry_id, flow_id, job_id). Devuelve el valor o lanza."""
    if not isinstance(value, str) or ".." in value or not _ID_RE.match(value):
        raise InvalidIdentifier(
            f"Invalid {field!r}: only letters, digits, '_' and '-' are allowed, "
            "must start alphanumeric, no '.', '/' or '..' (max 127 chars)."
        )
    return value


def validate_path_segment(value: str, *, field: str) -> str:
    """Valida algo que va a ocupar UN tramo de la ruta y nada más.

    Se usa para entity_id, dominio y servicio: valores con forma propia de
    Home Assistant que no conviene encajar en `_ID_RE` (un entity_id lleva
    punto, un dominio puede ser cualquier integración), pero de los que sí se
    sabe con certeza que no contienen separadores de ruta.

    Deliberadamente NO impone un formato: solo prohíbe lo que cambiaría la
    ruta de destino. Así no puede rechazar un entity_id legítimo raro.
    """
    if not isinstance(value, str) or not value:
        raise InvalidIdentifier(f"Invalid {field!r}: must be a non-empty string.")
    if len(value) > 255:
        raise InvalidIdentifier(f"Invalid {field!r}: too long (max 255 chars).")
    for malo in _PELIGROSOS:
        if malo in value:
            raise InvalidIdentifier(
                f"Invalid {field!r}: must not contain {malo!r}."
            )
    if any(c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        raise InvalidIdentifier(
            f"Invalid {field!r}: must not contain whitespace or control characters."
        )
    return value
