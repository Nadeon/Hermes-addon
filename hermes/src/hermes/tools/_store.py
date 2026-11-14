"""Hermes — piezas comunes de la tienda de apps del Supervisor (spec 030).

Módulo SIN tools (como `tools/_logs.py` de la 013): funciones puras que
comparten `store_repositories` (tramo 1), `store_apps` (tramo 2) y las vistas
previas de `tools/addons.py` (tramo 2). Existe aparte para que esos módulos no
se importen entre sí (`addons` ↔ `store_apps` sería un ciclo).

POR QUÉ
-------
- La lista de repositorios integrados decide si quitar uno se rechaza sin
  token: el Supervisor 2026.11.0 los rechaza («Can't remove built-in
  repositories!») y dar un token para algo imposible sería mentir.
- La URL de un repositorio privado puede llevar credenciales
  (`https://usuario:clave@servidor/…`). Es un secreto que el usuario dio
  para que el Supervisor clone; no puede salir en vistas previas, respuestas,
  errores ni en el log (principio II).
- El nombre, la URL y el mantenedor de un repositorio los escribe un tercero:
  se marcan con el mismo formato y el mismo aviso que el Marketplace para que
  el cliente los trate como datos y no como instrucciones.
"""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import unquote, urlsplit

from hermes.security import REDACTED_MARKER, redact_secrets
from hermes.tools.marketplace import _THIRD_PARTY_WARNING

# `slug` fijos de los repositorios integrados del Supervisor 2026.11.0
# (`supervisor/store/const.py`, `BuiltinRepository`): `core` y `local`, y los
# de la comunidad, ESPHome y Music Assistant, cuyo slug no sale del hash de la
# URL. Si una versión futura añade otro, el Supervisor seguirá rechazando
# quitarlo y Hermes devolverá su error (plan, «Riesgos»).
REPOSITORIOS_INTEGRADOS: frozenset[str] = frozenset({
    "core", "local", "a0d7b954", "5c53de3b", "d5369777",
})

# El Supervisor traduce estas dos URL a `core` antes de añadirlas
# (`store/__init__.py`, `_add_repository`): añadirlas es «ya añadido».
URLS_DE_CORE: frozenset[str] = frozenset({
    "https://github.com/home-assistant/apps",
    "https://github.com/home-assistant/addons",
})


def es_integrado(slug: str) -> bool:
    """True si el repositorio es uno de los integrados del Supervisor."""
    return slug in REPOSITORIOS_INTEGRADOS


def slug_de_repositorio(url: str) -> str:
    """El `slug` que el Supervisor da a un repositorio propio:
    `sha1(url.lower())[:8]` sobre la cadena entera, `#rama` incluida
    (`store/utils.py`, `get_hash_from_repository`).

    SHA-1 aquí no protege nada: es el identificador que calcula el
    Supervisor, y solo sirve si se calcula igual. Por eso la supresión de
    Semgrep (revisada) y `usedforsecurity=False`.
    """
    clave = url.lower().encode()
    return hashlib.sha1(clave, usedforsecurity=False).hexdigest()[:8]  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1


def _partes_de_credenciales(url: str) -> tuple[str, str, str] | None:
    """(antes, contraseña, después) si la URL lleva `usuario:contraseña@`.

    Se trabaja sobre el texto del `netloc` y no se reconstruye la URL con
    `urlunsplit`: así todo lo demás (puerto, ruta, `#rama`) sale byte a byte
    como estaba.
    """
    try:
        partes = urlsplit(url)
    except ValueError:
        return None
    if not partes.netloc or "@" not in partes.netloc:
        return None
    usuario_info, _, _ = partes.netloc.rpartition("@")
    if ":" not in usuario_info:
        return None
    usuario, _, clave = usuario_info.partition(":")
    if not clave:
        return None
    inicio = url.find(partes.netloc)
    if inicio < 0:
        return None
    antes = url[:inicio] + usuario + ":"
    despues = url[inicio + len(usuario_info):]
    return antes, clave, despues


def contrasena_de_url(url: str) -> str | None:
    """La contraseña de las credenciales de una URL, o `None`."""
    partes = _partes_de_credenciales(url) if isinstance(url, str) else None
    return partes[1] if partes else None


def tapar_credenciales(url: Any) -> Any:
    """La URL con la contraseña sustituida por `***REDACTED***`; el usuario
    se conserva (data-model, «Tapado de credenciales»). Lo que no es texto se
    devuelve tal cual (`core`, `local` y valores raros del Supervisor).

    Si la URL no se puede analizar, se pasa por `redact_secrets`, que tapa
    igualmente la forma `esquema://usuario:clave@`: nunca se devuelve sin
    revisar.
    """
    if not isinstance(url, str):
        return url
    partes = _partes_de_credenciales(url)
    if partes is None:
        return redact_secrets(url)
    antes, _, despues = partes
    return antes + REDACTED_MARKER + despues


def redactar_mensaje(texto: str, url: str | None = None) -> str:
    """Un mensaje del Supervisor listo para el cliente.

    El Supervisor repite la URL en sus errores («Can't retrieve data from
    <url> due to …»), a veces fuera de la forma `esquema://usuario:clave@` que
    reconoce `redact_secrets`. Por eso, si se conoce la URL, su contraseña se
    sustituye LITERALMENTE (tal cual y descodificada) antes de la redacción
    general.
    """
    if url:
        clave = contrasena_de_url(url)
        if clave:
            for forma in {clave, unquote(clave)}:
                if forma:
                    texto = texto.replace(forma, REDACTED_MARKER)
    return redact_secrets(texto)


def texto_de_terceros(campos: list[str]) -> dict[str, Any]:
    """El marcador `_third_party_text` del Marketplace (`tools/marketplace.py`),
    con el mismo aviso, para los campos que escribe un tercero."""
    return {"fields": list(campos), "warning": _THIRD_PARTY_WARNING}
