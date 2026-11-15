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
import hashlib
import json
import re
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
    "This is what the app's config file in /addons declares now. The "
    "Supervisor uses its own copy until the store is reloaded "
    "(sv_reload_store), so it may differ from 'store'."
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
