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

import asyncio
import contextlib
import hashlib
import json
import os
import re
import time
import weakref
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml

from hermes.ha import HAConnectionError
from hermes.security import REDACTED_MARKER, redact_secrets
from hermes.tools._common import tam_json
from hermes.tools._validation import validate_slug
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


# `esquema://<lo que sea sin espacios ni barras>@`: la parte de usuario de
# una URL dentro de cualquier texto (un error del Supervisor, un nombre de
# repositorio). Sirve también para `https://<token>@servidor/…`, que la
# redacción general no reconoce porque no lleva `:`. Llega hasta la ÚLTIMA
# `@` antes del servidor, como `urlsplit`: con una `@` sin codificar en la
# contraseña (`https://u:p@ss@servidor/…`), parar en la primera dejaba `ss@`
# a la vista (convergencia de la 030, T034).
_RE_USUARIO_EN_TEXTO = re.compile(
    r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/'\"<>]+@")

# Por debajo de este largo, un trozo de las credenciales no se sustituye
# LITERALMENTE en un texto (sí dentro de una URL, siempre): un usuario como
# `git` o `x` aparecería en mitad de cualquier mensaje y lo dejaría ilegible,
# y nadie usa algo tan corto como secreto.
_LARGO_MIN_LITERAL = 4


def _partes_de_credenciales(url: str) -> tuple[str, str, str] | None:
    """(antes, credenciales, después) si la URL lleva `algo@` delante del
    servidor: `usuario:contraseña@`, `usuario@` o `token@`.

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
    if not usuario_info:
        return None
    inicio = url.find(partes.netloc)
    if inicio < 0:
        return None
    antes = url[:inicio]
    despues = url[inicio + len(usuario_info):]
    return antes, usuario_info, despues


def credenciales_de_url(url: Any) -> str | None:
    """La parte de usuario ENTERA de una URL (`usuario:contraseña`,
    `usuario` o `token`), o `None`."""
    partes = _partes_de_credenciales(url) if isinstance(url, str) else None
    return partes[1] if partes else None


def tapar_usuario_en_texto(texto: str) -> str:
    """`esquema://loquesea@` → `esquema://***REDACTED***@` en cualquier texto."""
    return _RE_USUARIO_EN_TEXTO.sub(lambda m: m.group(1) + REDACTED_MARKER + "@", texto)


def tapar_credenciales(url: Any) -> Any:
    """La URL con su parte de usuario ENTERA sustituida por `***REDACTED***`
    (`https://***REDACTED***@servidor/…`). Lo que no es texto se devuelve tal
    cual (`core`, `local` y valores raros del Supervisor).

    Se tapa entera y no solo la contraseña: en `https://<token>@servidor/…`
    (la forma de GitHub y GitLab para un repositorio privado) el secreto ES el
    usuario, y en `usuario:clave@` el usuario de una cuenta privada también
    identifica a alguien. Lo pidió el supervisor del programa al revisar el
    tramo 1 (extra b).

    Si la URL no se puede analizar, se tapa igualmente con el patrón de texto
    y la redacción general: nunca se devuelve sin revisar.
    """
    if not isinstance(url, str):
        return url
    partes = _partes_de_credenciales(url)
    if partes is None:
        return redact_secrets(tapar_usuario_en_texto(url))
    antes, _, despues = partes
    return antes + REDACTED_MARKER + despues


def _trozos_secretos(url: str | None) -> set[str]:
    """Lo que hay que sustituir literalmente en un texto que pudo repetir la
    parte de usuario de `url`: entera, usuario y contraseña, tal cual y
    descodificados."""
    credenciales = credenciales_de_url(url) if url else None
    if not credenciales:
        return set()
    usuario, _, clave = credenciales.partition(":")
    trozos: set[str] = set()
    for trozo in (credenciales, usuario, clave):
        for forma in (trozo, unquote(trozo)):
            if len(forma) >= _LARGO_MIN_LITERAL:
                trozos.add(forma)
    return trozos


def redactar_mensaje(texto: str, url: str | None = None) -> str:
    """Un mensaje del Supervisor listo para el cliente.

    El Supervisor repite la URL en sus errores («Can't retrieve data from
    <url> due to …»), a veces fuera de la forma `esquema://usuario@`. Por eso,
    si se conoce la URL, su parte de usuario (entera y por trozos, tal cual y
    descodificada) se sustituye LITERALMENTE; después se tapa la parte de
    usuario de cualquier URL del texto y se aplica la redacción general.
    Los trozos más largos van primero para no dejar restos de uno largo que
    contiene a uno corto.
    """
    for trozo in sorted(_trozos_secretos(url), key=len, reverse=True):
        texto = texto.replace(trozo, REDACTED_MARKER)
    return redact_secrets(tapar_usuario_en_texto(texto))


def tapar_en_estructura(valor: Any) -> Any:
    """Copia de `valor` con la parte de usuario de toda URL tapada en todos
    sus textos (claves no). La última capa de las tools de repositorios: lo
    que devuelven no lleva nunca `esquema://algo@`, salga de donde salga."""
    if isinstance(valor, str):
        return tapar_usuario_en_texto(valor)
    if isinstance(valor, dict):
        return {k: tapar_en_estructura(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [tapar_en_estructura(v) for v in valor]
    return valor


def texto_de_terceros(campos: list[str]) -> dict[str, Any]:
    """El marcador `_third_party_text` del Marketplace (`tools/marketplace.py`),
    con el mismo aviso, para los campos que escribe un tercero."""
    return {"fields": list(campos), "warning": _THIRD_PARTY_WARNING}


# ── Lecturas de una app de la tienda (tramo 2) ────────────────────────────────
#
# Las usan `tools/store_apps.py` y las vistas previas de `tools/addons.py`
# (instalar y actualizar). Reciben el cliente como argumento para no atar este
# módulo a ningún `register`.

# Textos EXACTOS que el Supervisor 2026.11.0 devuelve con un 200 cuando una app
# no tiene changelog o documentación (`api/store.py`: «Frontend can't handle
# error response here»). Sin reconocerlos, el error saldría como si fuera el
# texto de la app. Si una versión futura los cambia, el test lo fija y la
# ficha leída antes garantiza al menos que la app existe (plan, «Riesgos»).
TEXTO_NO_ENCONTRADO: dict[str, str] = {
    "changelog": "No changelog found for app {slug}!",
    "documentation": "No documentation found for app {slug}!",
}
# El de una app que no está en la tienda, también con 200
# (`StoreAppNotFoundError`): solo puede salir si la app desaparece entre la
# lectura de la ficha y la del texto.
_TEXTO_APP_INEXISTENTE = "App {slug} does not exist in the store"


def mensaje_del_supervisor(exc: HAConnectionError) -> str:
    """El `message` del cuerpo de un error del Supervisor (`{"result":
    "error", "message": …}`), o el texto entero del error si no lo trae. Sin
    redactar: lo hace quien lo devuelve."""
    texto = str(exc)
    if exc.status is None:
        return texto
    _, sep, cuerpo = texto.partition(f"failed {exc.status}: ")
    if not sep:
        return texto
    try:
        data = json.loads(cuerpo)
    except ValueError:
        return cuerpo.strip() or texto
    if isinstance(data, dict) and isinstance(data.get("message"), str):
        return data["message"]
    return cuerpo.strip() or texto


async def ficha_de_tienda(ha_client: Any, slug: str) -> dict[str, Any] | None:
    """La ficha de la app en la tienda (`GET /store/addons/{slug}`), o `None`
    si no está. El Supervisor 2026.11.0 responde 404
    (`StoreAppNotFoundError`); se acepta también 400, el código de un
    `APIError` genérico. Cualquier otro error se lanza: quien llama decide si
    eso impide seguir."""
    validate_slug(slug, field="slug")
    try:
        data = await ha_client.sv_request("GET", f"/store/addons/{slug}")
    except HAConnectionError as exc:
        if exc.status in (400, 404):
            return None
        raise
    if not isinstance(data, dict):
        raise HAConnectionError("Unexpected response from the Supervisor store.")
    return data


async def disponibilidad(ha_client: Any, slug: str) -> tuple[bool, str | None]:
    """(True, None) si la app se puede instalar en este sistema; (False,
    motivo redactado) si el Supervisor responde 400
    (`validate_availability`: arquitectura, tipo de máquina o versión de HA).
    Cualquier otro error se lanza."""
    validate_slug(slug, field="slug")
    try:
        await ha_client.sv_request("GET", f"/store/addons/{slug}/availability")
    except HAConnectionError as exc:
        if exc.status == 400:
            return False, redact_secrets(mensaje_del_supervisor(exc))
        raise
    return True, None


async def texto_de_la_app(ha_client: Any, slug: str, tipo: str) -> str | None:
    """El changelog o la documentación (`tipo`) de la versión de la TIENDA,
    sin redactar, o `None` si el Supervisor dice que no lo tiene.

    Si el texto es el de «la app no existe», se lanza un 404: la app
    desapareció entre la ficha y el texto, y no es su changelog.
    """
    # Quien llama ya validó el slug; se repite porque aquí se construye la
    # ruta (defensa en profundidad, como el resto de módulos que la arman).
    validate_slug(slug, field="slug")
    no_encontrado = TEXTO_NO_ENCONTRADO[tipo]
    texto = await ha_client.sv_request_text(f"/store/addons/{slug}/{tipo}")
    if not isinstance(texto, str):
        raise HAConnectionError("Unexpected response from the Supervisor store.")
    limpio = texto.strip()
    if limpio == no_encontrado.format(slug=slug):
        return None
    if limpio == _TEXTO_APP_INEXISTENTE.format(slug=slug):
        raise HAConnectionError(limpio, status=404)
    return texto


def trozo_de_texto(
    texto: str,
    offset: int,
    max_chars: int,
    base: dict[str, Any],
    max_bytes: int,
) -> dict[str, Any]:
    """`base` más el trozo pedido del texto REDACTADO y sus campos
    (data-model, «Trozo de texto»), acortado hasta que la respuesta quepa en
    `max_bytes`.

    Se redacta el texto ENTERO antes de cortar (research R-9): redactar cada
    trozo podría partir un secreto entre dos y dejar media clave en cada uno,
    que ninguna regla reconocería. `total_chars`, `offset` y `next_offset` se
    cuentan sobre el texto redactado, que es el que el cliente puede pedir.
    Un `offset` fuera del texto da un trozo vacío y `truncated: false`.
    """
    redactado = redact_secrets(texto)
    total = len(redactado)
    inicio = min(offset, total)

    def armar(n: int) -> dict[str, Any]:
        fin = inicio + n
        out: dict[str, Any] = {
            **base,
            "text": redactado[inicio:fin],
            "total_chars": total,
            "offset": offset,
            "truncated": fin < total,
        }
        if fin < total:
            out["next_offset"] = fin
        out["secrets_redacted"] = redactado != texto
        return out

    n = min(max_chars, total - inicio)
    out = armar(n)
    if tam_json(out) <= max_bytes:
        return out
    # Búsqueda binaria del trozo más largo que cabe (el tamaño en bytes crece
    # con n, pero no linealmente: acentos y escapes cuestan más de uno).
    bajo, alto = 0, n
    while bajo < alto:
        medio = (bajo + alto + 1) // 2
        if tam_json(armar(medio)) <= max_bytes:
            bajo = medio
        else:
            alto = medio - 1
    return armar(bajo)


# ── Privilegios de una app (spec 034, tramo 3; FR-021…FR-023) ─────────────────
#
# Con las tools de `/addons` un cliente puede escribir una app local y luego
# instalarla. La salvaguarda es que la vista previa de instalar y de
# reconstruir ENSEÑE qué privilegios pide la app y que el token se ate a lo
# enseñado (research R-7). Se eligen los campos uno a uno: nunca la ficha en
# crudo (lleva `long_description`, texto libre del autor, y la instalada,
# `options`, que puede llevar contraseñas).

#: Campos de privilegio de `GET /store/addons/{slug}` (`api/store.py`,
#: `_generate_app_information(extended=True)`), FR-021.
CAMPOS_PRIVILEGIO_TIENDA: tuple[str, ...] = (
    "apparmor", "auth_api", "docker_api", "full_access", "hassio_api",
    "hassio_role", "homeassistant_api", "host_network", "host_pid", "ingress",
    "rating", "signed",
)
#: Los de `GET /addons/{slug}/info` (`api/apps.py`, `info_data`): los mismos
#: más los que la tienda no da (FR-022).
CAMPOS_PRIVILEGIO_INSTALADA: tuple[str, ...] = CAMPOS_PRIVILEGIO_TIENDA + (
    "privileged", "devices", "host_ipc", "host_uts", "host_dbus",
    "kernel_modules", "udev", "usb", "uart", "gpio", "devicetree", "video",
    "audio",
)
#: Lo que se lee del `config.*` de una app local (FR-021). `map` y `ports` no
#: los da ninguna ruta del Supervisor: solo se ven en el fichero.
CAMPOS_DECLARADOS: tuple[str, ...] = (
    "privileged", "full_access", "docker_api", "host_network", "host_pid",
    "host_ipc", "host_uts", "host_dbus", "hassio_api", "hassio_role",
    "homeassistant_api", "auth_api", "apparmor", "devices", "map",
    "kernel_modules", "udev", "usb", "uart", "gpio", "video", "audio", "ports",
)

#: Booleanos que, a `true`, son un privilegio elevado (regla fija, R-7).
_BOOLEANOS_ELEVADOS: tuple[str, ...] = (
    "full_access", "docker_api", "host_network", "host_pid", "host_ipc",
    "host_uts", "host_dbus", "kernel_modules", "udev",
)
_ROLES_ELEVADOS: frozenset[str] = frozenset({"manager", "admin"})

NOTA_DECLARADO = (
    # Sin «token» delante de una palabra: la redacción de secretos lo
    # tomaría por uno y taparía el resto (convergencia 2, hallazgo).
    "This is what the app's config file in /addons declares now. The "
    "Supervisor installs, updates and rebuilds from its own copy, read at "
    "the last store reload; Hermes only lets you confirm when nothing in "
    "/addons has changed since the last reload it launched "
    "(sv_reload_store); otherwise the answer is store_copy_stale."
)

# Topes de lo que se ENSEÑA (no de lo que se ata al token, que va entero):
# un `config.yaml` de 1 MiB con miles de `devices` no puede llevarse la
# respuesta por delante del tope de bytes.
_MAX_ELEMENTOS = 50
_MAX_TEXTO = 200


def _limpio(valor: Any) -> Any:
    """Copia de un valor que escribió el autor de la app con cada texto
    (también las claves) pasado por `redact_secrets` (FR-023)."""
    if valor is None or isinstance(valor, (bool, int, float)):
        return valor
    if isinstance(valor, str):
        return redact_secrets(valor)
    if isinstance(valor, dict):
        return {redact_secrets(str(k)): _limpio(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_limpio(v) for v in valor]
    return redact_secrets(str(valor))


#: Textos que admite `vol.Boolean()` (voluptuous), con `lower()` y SIN
#: `strip()`: lo que el Supervisor hace con los booleanos del `config.*`
#: (`apps/validate.py`, `_SCHEMA_APP_CONFIG`).
_TEXTOS_VERDADEROS = frozenset({"1", "true", "yes", "on", "enable"})
_TEXTOS_FALSOS = frozenset({"0", "false", "no", "off", "disable"})
#: Roles que admite el Supervisor (`vol.In(ROLE_ALL)`).
_ROLES: frozenset[str] = frozenset({"default", "homeassistant", "backup",
                                    "manager", "admin"})
#: Un valor que el Supervisor no sabría interpretar (convergencia de la 034,
#: T046). Cuenta como elevado: Hermes no puede asegurar que no se aplique.
_SIN_INTERPRETAR = object()


def _booleano_del_fichero(valor: Any) -> Any:
    """Como `vol.Boolean()` del Supervisor: un texto, por su lista; cualquier
    otra cosa, `bool(valor)` (`host_dbus: 1` se aplica como `True` y
    `apparmor: 0` como `False`). Un texto fuera de las listas devuelve
    `_SIN_INTERPRETAR`."""
    if isinstance(valor, str):
        texto = valor.lower()
        if texto in _TEXTOS_VERDADEROS:
            return True
        if texto in _TEXTOS_FALSOS:
            return False
        return _SIN_INTERPRETAR
    return bool(valor)


def _elevados(fuente: dict[str, Any], *, fichero: bool = False) -> set[str]:
    """Nombres de los privilegios elevados de UNA fuente (regla de R-7).

    `fichero=True` para `declared_in_folder`: los valores se interpretan como
    el esquema del Supervisor (T046), porque es él quien los aplica. Lo que
    no sabría interpretar sale como `<campo>:unparsed` y cuenta como elevado
    (fail-closed). En la API (`store`, `installed`) los booleanos son JSON y
    `apparmor` es texto (`disable`, `default` o `profile`, `apps/model.py`).
    """
    out: set[str] = set()
    for c in _BOOLEANOS_ELEVADOS:
        if fichero:
            if c not in fuente:
                continue
            valor = _booleano_del_fichero(fuente[c])
            if valor is _SIN_INTERPRETAR:
                out.add(c + ":unparsed")
            elif valor:
                out.add(c)
        elif fuente.get(c) is True:
            out.add(c)
    for lista in ("privileged", "devices"):
        if fuente.get(lista):
            out.add(lista)
    rol = fuente.get("hassio_role")
    if isinstance(rol, str) and rol in _ROLES_ELEVADOS:
        out.add("hassio_role:" + rol)
    elif fichero and "hassio_role" in fuente and not (
            isinstance(rol, str) and rol in _ROLES):
        out.add("hassio_role:unparsed")
    if fichero:
        if "apparmor" in fuente:
            aa = _booleano_del_fichero(fuente["apparmor"])
            if aa is _SIN_INTERPRETAR:
                out.add("apparmor:unparsed")
            elif not aa:
                out.add("apparmor:disabled")
    elif fuente.get("apparmor") in ("disable", False):
        out.add("apparmor:disabled")
    mapa = fuente.get("map")
    for entrada in mapa if isinstance(mapa, list) else []:
        if not isinstance(entrada, dict):
            continue
        tipo = str(entrada.get("type"))[:_MAX_TEXTO]
        if "unparsed" in entrada:
            # Lo que el Supervisor descarta al migrar no se aplica.
            continue
        solo_lectura = entrada.get("read_only", True)
        # `read_only` es `bool` ESTRICTO en el esquema: otra cosa invalida
        # la app; Hermes no lo supone y lo cuenta como elevado.
        if solo_lectura is False:
            out.add(f"map:{tipo} (read-write)")
        elif solo_lectura is not True:
            out.add(f"map:{tipo} (unparsed)")
    return out


def _normalizar_map(valor: Any) -> list[Any]:
    """`map` como lo deja el Supervisor (`apps/validate.py`, `_migrate`):
    `"share:rw"` → `{"type": "share", "read_only": false}`, `"ssl"` →
    `read_only: true`, y un diccionario con `read_only` por defecto `true`.
    Lo que el Supervisor descartaría se enseña como `unparsed` y no cuenta
    como elevado (no se aplica)."""
    if not isinstance(valor, list):
        return [{"unparsed": valor}]
    out: list[Any] = []
    for entrada in valor:
        if isinstance(entrada, str):
            tipo, _, modo = entrada.partition(":")
            if tipo and modo in ("", "rw", "ro"):
                out.append({"type": tipo, "read_only": modo != "rw"})
            else:
                out.append({"unparsed": entrada})
        elif isinstance(entrada, dict) and "type" in entrada:
            normal = {"type": entrada["type"],
                      "read_only": entrada.get("read_only", True)}
            if "path" in entrada:
                normal["path"] = entrada["path"]
            out.append(normal)
        else:
            out.append({"unparsed": entrada})
    return out


class DeclaradoIlegible(Exception):
    """No se pudo mirar el `config.*` de una app local (carpeta sin montar o
    fichero ilegible). El mensaje es el motivo, sin rutas absolutas."""


_ILEGIBLE = "The app's config file in /addons could not be read."


def declarado_en_carpeta(slug: str) -> dict[str, Any] | None:
    """Lo que declara el `config.*` de la app local `slug` en `/addons`, o
    `None` si `slug` no es `local_*` o ningún `config.*` del índice
    (`folders.indice_de_apps_locales`, las reglas del Supervisor) declara
    ese slug. Solo `/addons`: el Supervisor no carga apps de otra carpeta.
    Solo los campos de `CAMPOS_DECLARADOS`, redactados, más `config` (la
    ruta relativa) y la nota. Síncrono (recorre la carpeta): quien llama lo
    manda a un hilo.

    Raises:
        DeclaradoIlegible: la carpeta no está montada o el fichero no se lee.
    """
    # Import aquí: `folders` solo hace falta para esto (y así la 030 no
    # depende de él al importar).
    from hermes import folders

    if not isinstance(slug, str) or not slug.startswith("local_"):
        return None
    try:
        base = folders.raiz("addons")
        datos = folders.indice_de_apps_locales(base).apps.get(slug)
    except folders.CarpetaError as exc:
        raise DeclaradoIlegible(str(exc)) from exc
    except OSError as exc:
        raise DeclaradoIlegible("The /addons folder could not be read.") from exc
    if datos is None:
        return None
    rel = datos["config"]
    try:
        bruto = (base / rel).read_bytes()
        if len(bruto) > folders.TAM_MAX_CONFIG:
            raise DeclaradoIlegible(_ILEGIBLE)
        texto = bruto.decode("utf-8")
        # Como `read_json_or_yaml_file` del Supervisor: JSON por sufijo.
        contenido = json.loads(texto) if rel.endswith(".json") else yaml.safe_load(texto)
    except DeclaradoIlegible:
        raise
    except Exception as exc:  # noqa: BLE001 — cualquier fallo es «ilegible»
        raise DeclaradoIlegible(_ILEGIBLE) from exc
    if not isinstance(contenido, dict):
        raise DeclaradoIlegible(_ILEGIBLE)
    out: dict[str, Any] = {"config": rel}
    for campo in CAMPOS_DECLARADOS:
        if campo in contenido:
            valor = contenido[campo]
            out[campo] = _limpio(_normalizar_map(valor) if campo == "map" else valor)
    out["note"] = NOTA_DECLARADO
    return out


#: Marca de «esta fuente no aplica» en `privilegios_de` (distinta de `None`,
#: que es «no se pudo leer»).
NO_APLICA: Any = object()


def privilegios_de(
    store: Any = NO_APLICA,
    installed: Any = NO_APLICA,
    declared: Any = NO_APLICA,
    motivos: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """El bloque `privileges` (data-model.md). Puro.

    Cada fuente es la respuesta leída (dict), `None` si no se pudo leer (con
    su motivo en `motivos`, por clave del bloque) o `NO_APLICA` (`installed`
    al instalar; `declared` si la app no es local o no tiene `config.*` en
    `/addons`). `store` e `installed` se reducen a sus campos de privilegio;
    `declared` ya viene reducido (`declarado_en_carpeta`). Si no se leyó
    ninguna fuente, `None`: quien llama dice `privileges_unavailable` y
    nunca se inventa nada.
    """
    bloque: dict[str, Any] = {}
    leidas: list[tuple[str, dict[str, Any]]] = []
    for clave, fuente, campos in (("store", store, CAMPOS_PRIVILEGIO_TIENDA),
                                  ("installed", installed, CAMPOS_PRIVILEGIO_INSTALADA),
                                  ("declared_in_folder", declared, None)):
        if fuente is NO_APLICA:
            continue
        if not isinstance(fuente, dict):
            bloque[clave] = None
            continue
        elegido = _limpio({c: fuente.get(c) for c in campos} if campos is not None
                          else fuente)
        bloque[clave] = elegido
        leidas.append((clave, elegido))
    if not leidas:
        return None
    elevados: set[str] = set()
    for clave, fuente in leidas:
        elevados |= _elevados(fuente, fichero=clave == "declared_in_folder")
    bloque["elevated"] = sorted(elevados)
    no_leidas = {k: redact_secrets(v) for k, v in (motivos or {}).items()
                 if bloque.get(k, False) is None}
    if no_leidas:
        bloque["unavailable"] = no_leidas
    return bloque


def estado_de_privilegios(bloque: dict[str, Any] | None) -> Any:
    """Lo que se ata al token (FR-023): el bloque ENTERO salvo la nota y los
    motivos de lo que no se leyó. Un motivo es el texto de un error, que
    puede variar entre dos lecturas sin que cambie nada de lo enseñado; que
    una fuente no se leyera sí cuenta (su clave vale `null`)."""
    if bloque is None:
        return None
    estado = {k: v for k, v in bloque.items() if k != "unavailable"}
    if isinstance(estado.get("declared_in_folder"), dict):
        estado["declared_in_folder"] = {
            k: v for k, v in estado["declared_in_folder"].items() if k != "note"}
    return estado


def _acotar(valor: Any) -> tuple[Any, bool]:
    if isinstance(valor, str):
        return (valor[:_MAX_TEXTO], True) if len(valor) > _MAX_TEXTO else (valor, False)
    if isinstance(valor, list):
        cortado = len(valor) > _MAX_ELEMENTOS
        out = []
        for v in valor[:_MAX_ELEMENTOS]:
            a, c = _acotar(v)
            out.append(a)
            cortado = cortado or c
        return out, cortado
    if isinstance(valor, dict):
        cortado = len(valor) > _MAX_ELEMENTOS
        outd: dict[str, Any] = {}
        for k, v in list(valor.items())[:_MAX_ELEMENTOS]:
            a, c = _acotar(v)
            outd[k[:_MAX_TEXTO]] = a
            cortado = cortado or c or len(k) > _MAX_TEXTO
        return outd, cortado
    return valor, False


def privilegios_para_mostrar(bloque: dict[str, Any] | None) -> dict[str, Any] | None:
    """El bloque con listas y textos acotados para la vista previa (el tope
    de respuesta sigue vigente). Al token se ata el bloque entero
    (`estado_de_privilegios`): un cambio en lo que no se ve también lo
    invalida. Si algo se acortó, `truncated: true`."""
    if bloque is None:
        return None
    out: dict[str, Any] = {}
    cortado = False
    for k, v in bloque.items():
        if k in ("store", "installed", "declared_in_folder") and isinstance(v, dict):
            a, c = _acotar({kk: vv for kk, vv in v.items() if kk != "note"})
            if "note" in v:
                a["note"] = v["note"]
            out[k] = a
            cortado = cortado or c
        elif k == "elevated":
            a, c = _acotar(v)
            out[k] = a
            cortado = cortado or c
        else:
            out[k] = v
    if cortado:
        out["truncated"] = True
    return out


async def leer_declarado(slug: str) -> tuple[Any, str | None]:
    """(`declared` para `privilegios_de`, motivo si no se pudo leer)."""
    try:
        declarado = await asyncio.to_thread(declarado_en_carpeta, slug)
    except DeclaradoIlegible as exc:
        return None, str(exc)
    return (NO_APLICA if declarado is None else declarado), None


# ── Copia de la tienda desfasada (convergencia T047 y convergencia 2) ─────────
#
# El Supervisor no instala, reconstruye ni actualiza una app local a partir
# del `config.*` que hay AHORA en /addons, sino de su propia copia, la que
# leyó en la última recarga de la tienda (`store/data.py`; `rebuild` y
# `update` copian esa ficha a la app, `apps/app.py`). Y la ficha de la tienda
# no trae `privileged`, `devices`, `host_dbus`, `kernel_modules`, `udev`,
# `map`…: esos privilegios solo se ven en el fichero (`declared_in_folder`).
# Si /addons cambió después de esa recarga, la vista previa enseñaría unos
# privilegios y el Supervisor aplicaría otros (escribir uno con `SYS_ADMIN`,
# recargar y volver a escribirlo inocuo; o dos `config.*` con el mismo slug
# en la recarga y borrar después el que ganó). Por eso, para una app
# `local_*`, Hermes exige lo mismo que mira el Supervisor para decidir si
# relee las apps locales (`utils.get_latest_mtime`): que NADA en /addons, a
# cualquier profundidad y con la raíz incluida, tenga una fecha posterior al
# inicio de la última recarga LANZADA POR ÉL (convergencia 2, T051; antes,
# T047, solo se miraba el camino del fichero, y un `config.*` borrado en
# otra carpeta no se veía). Si no, se rechaza sin token: `store_copy_stale`.
# Sin suponer nada: sin /addons, con un árbol demasiado grande para
# recorrerlo a tiempo, sin la app en el índice, con dos `config.*` válidos
# para el mismo slug o con alguno que Hermes no puede leer (el Supervisor
# podría leer otro), también se rechaza. Un `config.*` que el Supervisor
# descartaría no bloquea nada: sale como nota (T055).

#: Hora (`time.time()`) del INICIO de la última recarga de la tienda que lanzó
#: Hermes y que terminó bien. `None` desde que arranca: ninguna conocida.
_ULTIMA_RECARGA: float | None = None
#: Convergencia 3 (T057): la fecha EXACTA (`st_mtime_ns`, leída de vuelta)
#: que Hermes puso a la raíz de /addons en esa misma recarga para obligar al
#: Supervisor a releer las apps locales. Solo ese valor exacto deja de contar
#: como cambio; `None`: ninguno.
_MARCA_RAIZ_NS: int | None = None
#: Los jobs del Supervisor 2026.11.0 que releen las fichas de la tienda
#: (`store/__init__.py`): `reload`, añadir un repositorio y
#: `update_repositories`. Mientras uno no ha terminado, su copia está a medias
#: (convergencia 3, T058). Solo se ven los que lanza una API (la de Hermes,
#: cancelada o no, o la de otro cliente). NO se ven (convergencia 4, T061):
#: la recarga programada, porque `tasks_reload_store` es `internal=True`
#: (`misc/tasks.py`) y `APIJobs._list_jobs` (`api/jobs.py`) se salta los
#: internos y no llega a sus hijos, que cuelgan de él; ni quitar un
#: repositorio, que llama a `data.update()` sin ser un job. Riesgo residual,
#: documentado en el CHANGELOG de la 1.2.1.
JOBS_DE_RECARGA: frozenset[str] = frozenset({
    "store_manager_reload",
    "store_manager_add_repository",
    "store_manager_update_repositories",
})
#: Margen para las fechas de los ficheros (hay sistemas de ficheros con una
#: resolución de hasta 2 s): un fichero escrito justo antes de recargar
#: cuenta como posterior.
MARGEN_RECARGA_S = 2.0
#: Rutas de muestra en la nota de los `config.*` descartados.
_MAX_IGNORADOS = 20

_CANDADOS_DE_RECARGA: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = (
    weakref.WeakKeyDictionary())


def candado_de_recarga() -> asyncio.Lock:
    """El candado común a TODAS las vías de Hermes que recargan la tienda
    (`sv_reload_store`, `sv_check_for_updates`, añadir y quitar repositorio;
    convergencia 2, T052). Uno por bucle de eventos, como `folders.candado`.

    Por qué: el Supervisor relee las apps locales solo si la fecha más
    reciente de /addons cambió desde la última vez que la miró, y un `git
    pull` ocupado vuelve al instante (`store/repository.py`,
    `store/git.py`). Dos recargas de Hermes a la vez: la segunda vuelve bien
    sin releer nada mientras la primera aún no ha terminado, y anotar su
    inicio daría por buena una copia que todavía es la vieja. Con el
    candado, una recarga empieza (y anota su inicio) solo cuando la anterior
    ha terminado."""
    loop = asyncio.get_running_loop()
    lock = _CANDADOS_DE_RECARGA.get(loop)
    if lock is None:
        lock = _CANDADOS_DE_RECARGA[loop] = asyncio.Lock()
    return lock


def anotar_recarga_de_tienda(inicio: float, marca_raiz_ns: int | None = None) -> None:
    """Anota una recarga de la tienda que Hermes lanzó a las `inicio` (antes
    de mandar la petición, con `candado_de_recarga` cogido) y que el
    Supervisor completó. La llaman `sv_reload_store`, `sv_check_for_updates`
    (`/refresh_updates` recarga la tienda) y `sv_add_store_repository` /
    `sv_remove_store_repository` (que vuelven a leer todas las fichas), solo
    si `recarga_valida_para_apps_locales` lo dice (convergencia 3).
    `marca_raiz_ns` es la fecha que esa recarga puso a la raíz de /addons:
    se registra A LA VEZ que el inicio, para que una marca de una recarga
    que falló nunca deje de contar como cambio."""
    global _ULTIMA_RECARGA, _MARCA_RAIZ_NS
    if _ULTIMA_RECARGA is None or inicio > _ULTIMA_RECARGA:
        _ULTIMA_RECARGA = inicio
        _MARCA_RAIZ_NS = marca_raiz_ns


def ultima_recarga_de_tienda() -> float | None:
    return _ULTIMA_RECARGA


# ── Convergencia 3: obligar al Supervisor a releer (T057) y jobs (T058) ──────
#
# T057. El Supervisor solo relee las apps locales si la fecha más reciente de
# /addons (`utils.get_latest_mtime`: `stat().st_mtime` de la raíz y de todo
# lo que hay debajo, el máximo) es DISTINTA (`!=`) de la que guardó la vez
# anterior (`RepositoryLocal.update`, `store/repository.py`). Y la guarda
# ANTES de releer (`data.update()`, en `StoreManager.reload`): si releer
# revienta (un `config.*` que tumba la recarga), la recarga da error pero la
# fecha queda guardada, y la siguiente vuelve «bien» sin releer nada. Por
# eso, antes de cada recarga suya, Hermes cambia la fecha de la raíz de
# /addons a una MAYOR que la que tenía y que la hora actual: el máximo cambia
# y el Supervisor relee (o la recarga falla, y entonces no se anota). Basta
# la raíz: entra en el máximo (`directory.stat()`), y cambiarla no toca
# ningún fichero.
#
# T058. La API responde cuando su recarga termina (`api/store.py`), pero si
# Hermes deja de esperar (se cancela la llamada o vence el tiempo) la
# recarga sigue en el Supervisor (`asyncio.shield`), y una recarga de
# Hermes posterior puede volver al instante sin haber releído. Mientras haya
# un job de `JOBS_DE_RECARGA` sin terminar (`GET /jobs/info`), la copia de
# la tienda no es fiable: no se anota una recarga que lo encuentre, y
# `store_copy_stale` rechaza.


#: Lo mínimo que se adelanta la marca sobre la fecha que tenía la raíz: así
#: el `float` de `st_mtime` que compara el Supervisor también cambia (a esta
#: escala, un `float` distingue unos 0,24 µs).
_SALTO_MARCA_NS = 1_000_000


def marcar_raiz_de_addons() -> int | None:
    """Pone a la raíz de /addons una fecha nueva (T057) y devuelve la que
    ha quedado, leída de vuelta (el sistema de ficheros puede redondearla),
    o `None` si /addons no está o el cambio no se pudo hacer o no cambió
    nada. Síncrono: quien llama lo manda a un hilo."""
    from hermes import folders

    try:
        base = folders.raiz("addons")
        antes = os.lstat(base).st_mtime_ns
        marca = max(time.time_ns(), antes + _SALTO_MARCA_NS)
        # La raíz ya viene resuelta (`ADDONS_BASE`): no es un symlink.
        os.utime(base, ns=(marca, marca))
        despues = os.lstat(base).st_mtime_ns
    except (folders.CarpetaError, OSError, NotImplementedError):
        return None
    return despues if despues != antes else None


def _hay_job_de_recarga(datos: Any) -> list[str]:
    """Los jobs de `JOBS_DE_RECARGA` sin terminar en el árbol de `/jobs/info`
    (hijos incluidos; `done` es `None` en uno creado y aún no arrancado).
    Una forma inesperada lanza `ValueError` (quien llama no supone nada)."""
    if not isinstance(datos, dict) or not isinstance(datos.get("jobs"), list):
        raise ValueError("unexpected /jobs/info shape")
    en_curso: list[str] = []
    pendientes = list(datos["jobs"])
    while pendientes:
        job = pendientes.pop(0)
        if not isinstance(job, dict):
            raise ValueError("unexpected job shape")
        if job.get("name") in JOBS_DE_RECARGA and job.get("done") is not True:
            en_curso.append(job["name"])
        hijos = job.get("child_jobs") or []
        if not isinstance(hijos, list):
            raise ValueError("unexpected child_jobs shape")
        pendientes.extend(hijos)
    return en_curso


async def jobs_de_recarga_en_curso(ha_client: Any) -> list[str] | None:
    """Los nombres de los jobs de recarga de la tienda sin terminar, o `None`
    si `/jobs/info` no responde o responde algo que no se entiende (no se
    sabe: quien llama falla cerrado)."""
    try:
        datos = await ha_client.sv_request("GET", "/jobs/info")
        return _hay_job_de_recarga(datos)
    except Exception:  # noqa: BLE001 — caído, 4xx, forma rara: no se sabe
        return None


@dataclass
class RecargaDeTienda:
    """Una recarga de la tienda que Hermes va a lanzar (con
    `candado_de_recarga` cogido)."""

    inicio: float
    marca_raiz_ns: int | None
    limpia_al_empezar: bool


async def empezar_recarga_de_tienda(ha_client: Any) -> RecargaDeTienda:
    """Justo antes de mandar la petición de recarga: mira si hay otra recarga
    en curso en el Supervisor (T058), marca la raíz de /addons (T057) y toma
    la hora de inicio, en ese orden."""
    en_curso = await jobs_de_recarga_en_curso(ha_client)
    marca = await asyncio.to_thread(marcar_raiz_de_addons)
    return RecargaDeTienda(inicio=time.time(), marca_raiz_ns=marca,
                           limpia_al_empezar=en_curso == [])


async def recarga_valida_para_apps_locales(ha_client: Any, recarga: RecargaDeTienda) -> bool:
    """Tras una recarga que el Supervisor respondió bien: True si se puede
    anotar (`anotar_recarga_de_tienda`). No, si la marca de /addons no se
    pudo poner (el Supervisor quizá no releyó las apps locales), si al
    empezar había otra recarga en curso, o si ahora la hay o no se sabe
    (fail-closed)."""
    if recarga.marca_raiz_ns is None or not recarga.limpia_al_empezar:
        return False
    return await jobs_de_recarga_en_curso(ha_client) == []


def _desfasada(slug: str, motivo: str) -> dict[str, Any]:
    return {
        "error": "store_copy_stale",
        "slug": slug,
        "reason": motivo,
        "detail": (
            "The Supervisor installs, updates and rebuilds a local app from its "
            "own copy of the app's config file, read at the last store reload, "
            "which may not be the file in /addons now. The privileges in the "
            "preview come from the file, and several of them (privileged, "
            "devices, host_dbus, kernel_modules, udev, map…) are not in the "
            "store's data, so Hermes cannot show what would really be applied. "
            "Nothing was done."),
        "hint": ("Reload the store with sv_reload_store (after the last change "
                 "in /addons) and request a new preview."),
    }


def _lista_de_motivos(motivos: dict[str, str]) -> str:
    rutas = sorted(motivos)
    texto = "; ".join(f"{r}: {motivos[r]}" for r in rutas[:5])
    return texto + (f"; and {len(rutas) - 5} more" if len(rutas) > 5 else "")


def _nota_de_ignorados(indice: Any) -> dict[str, Any] | None:
    """La nota de los `config.*` que el Supervisor descartaría (T055). Solo
    los que de verdad salta (convergencia 3, T059): los que tumban la
    recarga no salen aquí, bloquean (`store_copy_stale`)."""
    if not indice.descartados:
        return None
    rutas = sorted(indice.descartados)
    return {
        "files": [{"path": r, "reason": indice.descartados[r]}
                  for r in rutas[:_MAX_IGNORADOS]],
        "count": len(rutas),
        "note": ("The Supervisor skips each of these config files when it "
                 "reloads the store (it logs a warning and goes on with the "
                 "rest), so they declare no app."),
    }


def copia_de_tienda_desfasada(slug: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`(rechazo, nota)` para la app local `slug`.

    `rechazo` es `store_copy_stale`, o `None` si nada en /addons ha cambiado
    desde el inicio de la última recarga lanzada por Hermes (o si `slug` no
    es `local_*`). `nota` es la de los `config.*` que el Supervisor
    descartaría (`ignored_config_files` en la vista previa), o `None`.
    Síncrono (recorre /addons): quien llama lo manda a un hilo.
    """
    from hermes import folders

    if not isinstance(slug, str) or not slug.startswith("local_"):
        return None, None
    try:
        base = folders.raiz("addons")
        indice = folders.indice_de_apps_locales(base)
    except folders.CarpetaError:
        return _desfasada(slug, "The /addons folder is not available, so the app's "
                                "config file cannot be checked."), None
    except OSError:
        return _desfasada(slug, "The /addons folder could not be read."), None
    nota = _nota_de_ignorados(indice)
    if indice.rompen_recarga:
        # Convergencia 3 (T059): con uno de estos, toda recarga de la tienda
        # falla en el Supervisor: su copia no se puede poner al día.
        rechazo = _desfasada(slug, "Some config files in /addons make every store "
                                   "reload fail in the Supervisor ("
                                   + _lista_de_motivos(indice.rompen_recarga)
                                   + "), so its copy of the apps cannot be "
                                   "brought up to date.")
        rechazo["hint"] = ("Fix or remove those config files, reload the store "
                           "with sv_reload_store and request a new preview.")
        return rechazo, nota
    declarantes = indice.declarantes(slug)
    if not declarantes:
        sueltos = {c: indice.descartados[c] for c, s in indice.configs.items()
                   if s == slug and c in indice.descartados}
        if sueltos:
            return _desfasada(slug, "The config files in /addons that declare this "
                                    "app would be skipped by the Supervisor ("
                                    + _lista_de_motivos(sueltos) + ")."), nota
        return _desfasada(slug, "No config file in /addons declares this app."), nota
    if len(declarantes) > 1:
        return _desfasada(slug, "Several config files in /addons declare this app ("
                                + ", ".join(declarantes[:5]) + "); it is unknown "
                                "which one the Supervisor read."), nota
    if indice.no_legibles:
        return _desfasada(slug, "Hermes cannot read some config files in /addons ("
                                + _lista_de_motivos(indice.no_legibles) + "); the "
                                "Supervisor may read them, and one of them could "
                                "declare this app."), nota
    ultima = _ULTIMA_RECARGA
    if ultima is None:
        return _desfasada(slug, "Hermes has not reloaded the store since it started, "
                                "so it does not know which copy the Supervisor has."), nota
    try:
        # Convergencia 3 (T057): la marca que puso Hermes en esa misma
        # recarga, con su valor exacto, no cuenta; cualquier otro, sí.
        fecha, ruta = folders.fecha_mas_reciente(base, marca_raiz_ns=_MARCA_RAIZ_NS)
    except folders.ArbolDemasiadoGrande as exc:
        return _desfasada(slug, "/addons is too large to check in time (" + exc.detail
                                + "), so it is unknown whether it changed after "
                                "the last store reload."), nota
    except folders.RecorridoNoFiable as exc:
        # Convergencia 4 (T060): lo mismo que haría fallar el recorrido del
        # Supervisor, que entonces responde a la recarga sin releer.
        rechazo = _desfasada(slug, "/addons cannot be checked the way the Supervisor "
                                   "checks it (" + exc.detail + "). With it, the "
                                   "Supervisor's check fails and a store reload "
                                   "silently stops re-reading the local apps."), nota
        rechazo[0]["hint"] = ("Fix or remove that entry, reload the store with "
                              "sv_reload_store and request a new preview.")
        return rechazo
    except OSError:
        return _desfasada(slug, "/addons could not be fully checked (it may be "
                                "changing right now)."), nota
    if fecha > ultima - MARGEN_RECARGA_S:
        donde = "/addons itself" if ruta == "." else repr(ruta)
        return _desfasada(slug, "Something in /addons changed after the last store "
                                "reload started (the most recent change: "
                                + donde + ")."), nota
    return None, nota


async def comprobar_copia_de_tienda(
    slug: str, ha_client: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`copia_de_tienda_desfasada` en un hilo y, para una app `local_*` que
    pasa, que no haya una recarga de la tienda en curso en el Supervisor
    (convergencia 3, T058): su copia estaría a medias. Si `/jobs/info` no
    responde, tampoco se supone nada."""
    rechazo, nota = await asyncio.to_thread(copia_de_tienda_desfasada, slug)
    if rechazo is not None or not (isinstance(slug, str) and slug.startswith("local_")):
        return rechazo, nota
    en_curso = await jobs_de_recarga_en_curso(ha_client)
    if en_curso is None:
        return _desfasada(slug, "The Supervisor's job list could not be read, so "
                                "it is unknown whether a store reload is still "
                                "running."), nota
    if en_curso:
        rechazo = _desfasada(slug, "A store reload is still running in the "
                                   "Supervisor (" + ", ".join(sorted(set(en_curso)))
                                   + "), so its copy of the apps may be half "
                                   "updated.")
        rechazo["hint"] = ("Wait until it finishes (sv_list_pending_jobs), reload "
                           "the store with sv_reload_store and request a new "
                           "preview.")
        return rechazo, nota
    return None, nota


def candado_de_app(slug: str) -> Any:
    """El candado de /addons para una app `local_*` (convergencia T047 y
    T048): la comprobación de `store_copy_stale` y la petición de instalar,
    actualizar (convergencia 2, T053) o reconstruir van bajo el mismo candado
    que las escrituras de Hermes en /addons, para que ninguna se cuele entre
    medias. Para otra app, nada."""
    from hermes import folders

    if isinstance(slug, str) and slug.startswith("local_"):
        # Convergencia 2 (T056): con tope de espera; si se pasa,
        # `folders.CarpetaOcupada` (quien llama responde `folder_busy` sin
        # haber tocado el token).
        return folders.candado_con_tope("addons")
    return contextlib.nullcontext()


async def bajo_candado_de_app(slug: str, confirmar: Any) -> Any:
    """`await confirmar()` bajo `candado_de_app(slug)`. Si el candado de
    /addons no se consigue a tiempo, `folder_busy` sin llamar a
    `confirmar`: ni se mira ni se gasta el token (convergencia 2, T056)."""
    from hermes import folders

    try:
        async with candado_de_app(slug):
            return await confirmar()
    except folders.CarpetaOcupada as exc:
        return exc.respuesta(slug=slug)
