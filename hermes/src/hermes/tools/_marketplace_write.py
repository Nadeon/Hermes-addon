"""Hermes — piezas comunes de las tools que escriben en el Marketplace (spec
026). Sin tools: las usan `tools/marketplace_manage.py` y el test de contrato
del banco (`tests/banco/test_banco_marketplace.py`), que envía a HA real las
mismas cargas que construyen las funciones `carga_*`.

POR QUÉ UN MÓDULO APARTE
------------------------
`tools/marketplace.py` es de solo lectura y su lista cerrada
(`_ALLOWED_SUFFIXES`) lo hace comprobable: no se amplía. La escritura tiene
aquí su propia lista cerrada (`_WRITE_SUFFIXES`) con su guarda, y una lista
de lecturas (`_READ_SUFFIXES`) para las vistas previas.

Las lecturas de aquí NO caen a HACS como las de `tools/marketplace.py`: si HA
no conoce `marketplace/*` (HA <= 2026.10 con HACS 2.x, o modo de
recuperación), las tools de escritura responden
`marketplace_write_unsupported` sin probar `hacs/*`, cuyos comandos de
escritura no están en las fuentes de HA y no se pueden comprobar (research
R-1). Por eso no se reutiliza `_list_catalog`, que cae a HACS: se lee por
categorías igual (nunca el catálogo entero de una vez: hallazgo R-1 de la
006), pero solo de `marketplace/*`.

ALCANCE (DESVIACIÓN DV-1 de la 026)
-----------------------------------
HA 2026.11.1 exige que el usuario de HA que manda el comando haya aceptado el
aviso de riesgos del Marketplace para instalar, fijar versión, mostrar betas,
detectar y añadir repositorios (`marketplace_command(requires_accepted_warning=
True)`). El usuario de Hermes es el del Supervisor: nadie puede aceptarlo en
la interfaz por él y Hermes no lo acepta nunca. Esas operaciones no tienen
tool (no se publican tools que no pueden funcionar) y sus comandos quedan en
`deny` en la tabla. Los cinco de esta lista NO exigen el aviso (comprobado en
`websocket/repository.py`, `websocket/repositories.py` y
`websocket/critical.py` de HA Core 2026.11.1).

DESINSTALAR (tramo 2)
---------------------
Es la única que borra ficheros de /config, así que antes pide al Supervisor
un backup parcial de la configuración de HA sin la base de datos y solo si
termina bien envía el comando (FR-014, FR-017 de la 026). El backup no se
cifra: Hermes no manda contraseña (los safety backups cifrados de la 031 no
están integrados en esta rama, y no se promete lo que no se hace).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import aiohttp

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.tools._logs import ArgumentoInvalido
from hermes.tools._store import redactar_mensaje
from hermes.tools.marketplace import (
    _REPOSITORY_ID_RE,
    MARKETPLACE_CATEGORIES,
    _trim,
)

logger = structlog.get_logger(__name__)

EVENTO = "marketplace_write"

# Lista cerrada de comandos que ESCRIBEN (data-model «Comandos»). Ninguno es
# `warning/accept` ni `github/connect` (clase D, FR-091), ninguno exige el
# aviso de riesgos, y ninguno lleva `hassio/` ni `supervisor/` (el proxy WS
# del Supervisor los rechaza a las apps).
_WRITE_SUFFIXES = frozenset({
    "critical/acknowledge",
    "repository/ignore",
    "repositories/remove",
    "repository/refresh",
    # Tramo 2: no exige el aviso (`marketplace_command()` sin argumentos).
    "repository/uninstall",
})

# Lecturas de las vistas previas: las mismas que ya son `dedicated` hacia las
# tools de lectura de la 004.
_READ_SUFFIXES = frozenset({
    "repositories/list",
    "repositories/removed",
    "critical/list",
})

# `integration` primero, como en `tools/marketplace.py`: es la que más
# probablemente tiene el repositorio y ahorra mensajes.
_ORDEN_CATEGORIAS = ("integration", *sorted(MARKETPLACE_CATEGORIES - {"integration"}))

# `owner/repo` de GitHub, la forma de `repository` en `critical/list`.
_FULL_NAME_RE = re.compile(r"^[A-Za-z0-9-]{1,39}/[\w.-]{1,100}$")
_FULL_NAME_MAX = 140

AVISO_TERCEROS = (
    "Third-party repository: its code is not reviewed by Home Assistant nor "
    "by Hermes, and an installed one runs inside Home Assistant. This action "
    "installs, updates and runs no code."
)

SIN_BACKUP = {
    "will_create": False,
    "reason": "this action changes no files under /config",
}


class ErrorMarketplace(Exception):
    """Error ya traducido a la respuesta que verá el cliente MCP."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(payload.get("error"))
        self.payload = payload


# ── Cargas (data-model «Comandos») ────────────────────────────────────────────
#
# Públicas: el test de contrato del banco envía exactamente esto a HA real con
# un repositorio inexistente, para que una clave mal escrita se vea contra HA
# y no solo contra el simulador.


def carga_reconocer(full_name: str) -> dict[str, Any]:
    """`marketplace/critical/acknowledge`: el `full_name` TAL COMO lo guarda
    HA (lo compara con `==`, sin pasar a minúsculas)."""
    return {"repository": full_name}


def carga_ignorar(repository_id: str) -> dict[str, Any]:
    return {"repository": repository_id}


def carga_quitar(repository_id: str) -> dict[str, Any]:
    return {"repository": repository_id}


def carga_refrescar(repository_id: str) -> dict[str, Any]:
    return {"repository": repository_id}


def carga_desinstalar(repository_id: str) -> dict[str, Any]:
    return {"repository": repository_id}


# ── Backup previo de desinstalar (FR-017, research R-6) ──────────────────────

# La espera de `tools/addons.py` y `tools/backups.py` para operaciones largas.
ESPERA_BACKUP = 300.0
# El comando de HA puede preguntar antes a GitHub (si está conectado): más
# margen que los 30 s por defecto del WebSocket.
ESPERA_DESINSTALAR = 120
_JOB_EN_ERROR_RE = re.compile(r"check job '([0-9a-f]{6,64})'")


def nombre_backup(accion: str, ahora: datetime | None = None) -> str:
    """`hermes_marketplace_<acción>_<AAAAMMDDTHHMMSSZ>` en UTC. Sin el
    repositorio: los backups se listan en sitios que se comparten."""
    momento = (ahora or datetime.now(UTC)).astimezone(UTC)
    return f"hermes_marketplace_{accion}_{momento.strftime('%Y%m%dT%H%M%SZ')}"


def carga_backup(nombre: str) -> dict[str, Any]:
    """`POST /backups/new/partial`: solo la configuración de HA, sin apps,
    sin carpetas y sin la base de datos (es lo que hace lento un backup y el
    Marketplace no la toca), esperando a que termine. Sin `password`: no se
    cifra."""
    return {
        "name": nombre,
        "homeassistant": True,
        "homeassistant_exclude_database": True,
        "background": False,
    }


async def backup_previo(ha_client: HAClient, nombre: str) -> dict[str, Any]:
    """Pide el backup y espera a que termine. Devuelve `{"slug", "name"}`
    (y `job_id` si lo hay) o lanza `ErrorMarketplace` con `backup_failed`:
    con un error, un plazo agotado o una respuesta sin `slug` no consta que
    haya terminado, y quien llama NO envía el comando de HA."""
    try:
        datos = await ha_client.sv_request(
            "POST", "/backups/new/partial",
            json_body=carga_backup(nombre),
            timeout_seconds=ESPERA_BACKUP,
        )
    except (HAConnectionError, TimeoutError, aiohttp.ClientError) as exc:
        texto = str(exc) or type(exc).__name__
        fallo: dict[str, Any] = {
            "error": "backup_failed",
            "detail": redactar_mensaje(texto),
        }
        # El Supervisor da el job en el texto del error («check job '…'»).
        if (m := _JOB_EN_ERROR_RE.search(texto)) is not None:
            fallo["job_id"] = m.group(1)
        raise ErrorMarketplace(fallo) from exc
    slug = datos.get("slug") if isinstance(datos, dict) else None
    job_id = datos.get("job_id") if isinstance(datos, dict) else None
    if not isinstance(slug, str) or not slug:
        fallo = {
            "error": "backup_failed",
            "detail": "The Supervisor did not report a finished backup.",
        }
        if isinstance(job_id, str) and job_id:
            fallo["job_id"] = job_id
        raise ErrorMarketplace(fallo)
    hecho: dict[str, Any] = {"slug": slug, "name": nombre}
    if isinstance(job_id, str) and job_id:
        hecho["job_id"] = job_id
    return hecho


# ── Reinicio y lo que se quita al desinstalar (research R-7) ─────────────────


def reinicio_probable(repo: dict[str, Any]) -> dict[str, Any]:
    """Si HA pedirá reiniciar Core tras desinstalar, con su regla
    (`async_post_uninstall` de cada categoría en HA 2026.11.1). En una
    integración, HA lo pide si esta ejecución ya la cargó o si no tiene
    `config_flow` (solo YAML): lo segundo se sabe; lo primero no se ve desde
    fuera, y entonces `likely` es `None` en vez de adivinar."""
    despues = "restart Core with sv_restart_core; Hermes does not restart it"
    categoria = repo.get("category")
    if categoria == "integration":
        if repo.get("config_flow") is not True:
            return {
                "likely": True,
                "reason": (
                    "It has no config flow (set up from YAML): its code keeps "
                    "running until Core restarts, and Home Assistant asks for "
                    "a restart in Repairs."
                ),
                "after": despues,
            }
        return {
            "likely": None,
            "reason": (
                "Home Assistant asks for a restart (in Repairs) only if this "
                "run of Core already loaded the integration, which Hermes "
                "cannot see. restart_required in the answer says it."
            ),
            "after": despues,
        }
    if categoria == "plugin":
        return {
            "likely": False,
            "reason": "Home Assistant removes the card's dashboard resource; "
                      "browsers drop it when they reload.",
        }
    if categoria == "theme":
        return {"likely": False,
                "reason": "Home Assistant reloads the themes by itself."}
    if categoria == "template":
        return {"likely": False,
                "reason": "Home Assistant reloads the custom templates by itself."}
    return {"likely": None, "reason": "Unknown category."}


_QUITA = {
    "integration": "its folder under /config/custom_components",
    "plugin": "its folder under /config/www/community and its Lovelace "
              "(dashboard) resource",
    "theme": "its theme file under /config/themes",
    "template": "its template file under /config/custom_templates",
}

# HA no dice qué entidades, tarjetas o plantillas usan un repositorio: esto
# es lo que se deduce de lo que hace cada categoría, y se presenta como tal.
_PUEDE_ROMPER = {
    "integration": (
        "Its config entries are already gone (otherwise repository_in_use). "
        "Anything still configured in YAML with this domain (platforms, "
        "entities) fails to set up after the restart."
    ),
    "plugin": (
        "Dashboard cards of this resource stop rendering (custom element "
        "not found) once browsers reload."
    ),
    "theme": "Users and dashboards that select this theme fall back to the "
             "default one.",
    "template": "Templates that import macros from this file fail to render.",
}


def lo_que_quita(repo: dict[str, Any]) -> dict[str, Any]:
    """Qué borra HA al desinstalar (`remove_local_directory` y
    `async_post_uninstall` de cada categoría, y `async_remove_entity_device`
    para todas)."""
    categoria = repo.get("category")
    ruta = repo.get("local_path")
    quita: dict[str, Any] = {
        "files": _QUITA.get(categoria, "the repository files under /config"),
        # El nombre de la carpeta sale del repositorio (texto de terceros):
        # recortado y marcado en la vista previa.
        "path": _trim(ruta) if isinstance(ruta, str) else None,
        "update_entity": "the Marketplace update entity and device of this repository",
        "lovelace_resource": categoria == "plugin",
    }
    return quita


def lo_que_puede_romper(repo: dict[str, Any]) -> dict[str, Any]:
    return {
        "listed_by_home_assistant": False,
        "note": (
            "Home Assistant does not say which entities, cards or templates "
            "use this repository; this is what its category implies."
        ),
        "detail": _PUEDE_ROMPER.get(repo.get("category")),
    }


# ── Validación (sin llamar a HA) ─────────────────────────────────────────────


def validar_repository_id(valor: Any) -> str:
    """El id como texto. HACS daba ids numéricos y un cliente puede mandar el
    entero: se acepta, salvo un `bool` (que es un `int` en Python)."""
    if isinstance(valor, int) and not isinstance(valor, bool):
        valor = str(valor)
    if isinstance(valor, str) and _REPOSITORY_ID_RE.match(valor):
        return valor
    raise ArgumentoInvalido(
        "repository_id",
        "repository_id must be 1 to 64 characters of A-Z, a-z, 0-9, _ or -, "
        "as returned by ha_marketplace_list_repositories.",
    )


def validar_full_name(valor: Any) -> str:
    """`owner/repo` de GitHub (la forma de `ha_marketplace_list_critical`)."""
    if (
        isinstance(valor, str)
        and len(valor) <= _FULL_NAME_MAX
        and _FULL_NAME_RE.match(valor)
        and not valor.split("/", 1)[1].startswith(".")
    ):
        return valor
    raise ArgumentoInvalido(
        "repository",
        "repository must be the owner/repo full name shown by "
        "ha_marketplace_list_critical.",
    )


# ── Comandos ─────────────────────────────────────────────────────────────────


def traducir(exc: Exception) -> dict[str, Any]:
    """Error de HA → respuesta estable (data-model «Errores»). Se decide por
    el `code`, nunca por el texto; el texto va redactado (secretos y la parte
    de usuario de cualquier URL)."""
    code = getattr(exc, "code", None)
    detalle = redactar_mensaje(str(exc) or type(exc).__name__)
    if code == "unknown_command":
        return {
            "error": "marketplace_write_unsupported",
            "detail": (
                "Home Assistant does not know the marketplace/* commands (it is "
                "older than 2026.11, with HACS 2.x, or runs in recovery mode). "
                "Hermes only writes through the built-in Marketplace; it never "
                "sends hacs/* write commands."
            ),
        }
    if code == "not_loaded":
        return {
            "error": "marketplace_not_loaded",
            "detail": (
                "The Marketplace integration is not set up or failed to load. "
                "Check Settings > Devices & services."
            ),
        }
    if code == "github_rate_limited":
        return {
            "error": "github_rate_limited",
            "detail": (
                "GitHub is rate limiting the requests Home Assistant makes. "
                "Nothing changed; try again later."
            ),
        }
    if code in ("repository_not_found", "repository_installed",
                "repository_not_installed", "repository_in_use",
                "repository_busy", "uninstall_failed"):
        return {"error": code, "detail": detalle}
    out: dict[str, Any] = {"error": "ha_error", "detail": detalle}
    if code:
        out["ha_code"] = code
    return out


async def _ws(
    ha_client: HAClient, sufijo: str, carga: dict[str, Any], espera: int | None = None
) -> Any:
    mensaje = {"type": f"marketplace/{sufijo}", **carga}
    try:
        if espera is None:
            return await ha_client.ws_send(mensaje)
        return await ha_client.ws_send(mensaje, timeout_seconds=espera)
    except (HAConnectionError, TimeoutError) as exc:
        raise ErrorMarketplace(traducir(exc)) from exc


async def ws_lectura(
    ha_client: HAClient, sufijo: str, carga: dict[str, Any] | None = None
) -> Any:
    if sufijo not in _READ_SUFFIXES:
        # Guarda de la lista cerrada: nunca debería ocurrir.
        raise RuntimeError(f"marketplace read command not allowed here: {sufijo}")
    return await _ws(ha_client, sufijo, carga or {})


async def ws_escritura(
    ha_client: HAClient, sufijo: str, carga: dict[str, Any], espera: int | None = None
) -> Any:
    if sufijo not in _WRITE_SUFFIXES:
        # Guarda de la lista cerrada (FR-001): un sufijo fuera de la lista no
        # se envía nunca, ni siquiera por error de programación.
        raise RuntimeError(f"marketplace write command not allowed: {sufijo}")
    return await _ws(ha_client, sufijo, carga, espera)


async def entradas_del_dominio(ha_client: HAClient, domain: str) -> list[dict[str, Any]]:
    """Las entradas de configuración del `domain` (`config_entries/get`, que
    devuelve también las ignoradas, como `async_entries` en el manejador de
    desinstalar de HA). Es la única lectura fuera de `marketplace/*`
    (FR-001). Si no se puede leer, error: no se adivina que no hay."""
    try:
        datos = await ha_client.ws_send({"type": "config_entries/get", "domain": domain})
    except (HAConnectionError, TimeoutError) as exc:
        raise ErrorMarketplace({
            "error": "ha_error",
            "detail": redactar_mensaje(str(exc) or type(exc).__name__),
        }) from exc
    return _lista(datos)


def _lista(valor: Any) -> list[dict[str, Any]]:
    if not isinstance(valor, list):
        raise ErrorMarketplace({
            "error": "unexpected_response",
            "detail": f"Expected a list from Home Assistant, got {type(valor).__name__}.",
        })
    return [v for v in valor if isinstance(v, dict)]


async def repositorio_por_id(ha_client: HAClient, repository_id: str) -> dict[str, Any] | None:
    """El objeto de HA del repositorio con ese `id`, o `None`. Una categoría
    por mensaje, y se para en cuanto aparece."""
    for categoria in _ORDEN_CATEGORIAS:
        repos = _lista(await ws_lectura(
            ha_client, "repositories/list", {"categories": [categoria]}))
        for repo in repos:
            if repo.get("id") is not None and str(repo["id"]) == repository_id:
                return repo
    return None


async def retirados(ha_client: HAClient) -> list[dict[str, Any]]:
    return _lista(await ws_lectura(ha_client, "repositories/removed"))


async def criticos(ha_client: HAClient) -> list[dict[str, Any]]:
    return _lista(await ws_lectura(ha_client, "critical/list"))


def buscar_por_nombre(entradas: list[dict[str, Any]], full_name: Any) -> dict[str, Any] | None:
    """La entrada cuyo `repository` es `full_name` sin distinguir mayúsculas
    (GitHub no las distingue; HA guarda el que le dio el catálogo)."""
    if not isinstance(full_name, str):
        return None
    clave = full_name.casefold()
    for entrada in entradas:
        nombre = entrada.get("repository")
        if isinstance(nombre, str) and nombre.casefold() == clave:
            return entrada
    return None


# ── Formas de respuesta ──────────────────────────────────────────────────────


def resumen(repo: dict[str, Any]) -> dict[str, Any]:
    """Lo que la vista previa enseña del repositorio (data-model «Vistas
    previas»). `name` es texto de terceros: recortado."""
    return {
        "id": str(repo.get("id")),
        "full_name": repo.get("full_name"),
        "name": _trim(repo.get("name")),
        "category": repo.get("category"),
        "custom": repo.get("custom"),
        "installed": repo.get("installed"),
        "installed_version": repo.get("installed_version"),
        "available_version": repo.get("available_version"),
    }


def terceros(custom: Any) -> dict[str, Any]:
    """Si el repositorio es de terceros y si alguien lo revisó (decisión del
    supervisor al validar la spec). Todos son de terceros: ni Home Assistant
    ni Hermes revisan su código. `in_default_catalog` dice si al menos está en
    el catálogo por defecto del Marketplace o lo añadió alguien a mano."""
    return {
        "third_party": True,
        "reviewed_by_home_assistant": False,
        "in_default_catalog": None if not isinstance(custom, bool) else not custom,
        "warning": AVISO_TERCEROS,
    }


def entrada_retirada(entrada: dict[str, Any]) -> dict[str, Any]:
    return {
        "repository": entrada.get("repository"),
        "reason": _trim(entrada.get("reason")),
        "removal_type": _trim(entrada.get("removal_type")),
        "link": _trim(entrada.get("link")),
    }


def entrada_critica(entrada: dict[str, Any]) -> dict[str, Any]:
    return {
        "repository": entrada.get("repository"),
        "reason": _trim(entrada.get("reason")),
        "link": _trim(entrada.get("link")),
        "acknowledged": entrada.get("acknowledged"),
    }


def registrar(tool: str, outcome: str, category: Any = None) -> None:
    """Evento `marketplace_write` (FR-007): `tool`, `outcome` y `category`.
    Nunca nombres de repositorio, ids, URLs ni textos de terceros: el log se
    pega en issues públicos (principio VIII)."""
    logger.info(
        EVENTO, tool=tool, outcome=outcome,
        category=category if category in MARKETPLACE_CATEGORIES else None,
    )
