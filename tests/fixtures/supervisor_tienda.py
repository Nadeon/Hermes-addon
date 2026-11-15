"""Supervisor simulado de la tienda de apps (spec 030).

Forma de las respuestas del Supervisor 2026.11.0 (`supervisor/api/store.py`):
`GET /store/repositories` devuelve una LISTA de `{slug, name, source, url,
maintainer}` (`sv_request` ya extrae `data`); `GET /store/repositories/{r}`,
uno de esos objetos o 404 («Repository … does not exist in the store»);
`GET /store/addons` (v1), `{"addons": [...]}` con `slug`, `name`,
`repository`, `installed`… Las escrituras responden `{}` (`api_process` sin
datos).

Datos ficticios (principio VIII): `example.com`, `abcd1234`, centinelas de
texto. Los `slug` integrados (`core`, `local`, `a0d7b954`) son constantes
públicas del Supervisor.
"""

from __future__ import annotations

import copy
from typing import Any

from hermes.ha import HAConnectionError

CENTINELA_CLAVE = "centinela-clave-1"
URL_CON_CLAVE = f"https://usuario:{CENTINELA_CLAVE}@example.com/repo-ficticio"
URL_FICTICIA = "https://example.com/repo-ficticio"

REPOSITORIOS: list[dict[str, Any]] = [
    {"slug": "core", "name": "Official apps", "source": "core",
     "url": "https://home-assistant.io/apps", "maintainer": "HomeAssistant"},
    {"slug": "local", "name": "Local apps", "source": "local",
     "url": "local", "maintainer": "you"},
    {"slug": "a0d7b954", "name": "Community apps",
     "source": "https://github.com/hassio-addons/repository",
     "url": "https://addons.community", "maintainer": "Community"},
    # Repositorio privado: el Supervisor devuelve `source` tal como se añadió
    # (con las credenciales) y, si `repository.yaml` no trae `url`, la misma.
    {"slug": "abcd1234", "name": "Repo ficticio", "source": URL_CON_CLAVE,
     "url": URL_CON_CLAVE, "maintainer": "Nadie <nadie@example.com>"},
]

APPS: list[dict[str, Any]] = [
    {"slug": "core_ejemplo", "name": "Ejemplo oficial", "repository": "core",
     "installed": True, "version": "1.0.0", "version_latest": "1.0.0"},
    {"slug": "core_otro", "name": "Otro oficial", "repository": "core",
     "installed": False, "version": None, "version_latest": "2.0.0"},
    {"slug": "local_ejemplo", "name": "Ejemplo local", "repository": "local",
     "installed": True, "version": "0.1.0", "version_latest": "0.1.0"},
    {"slug": "a0d7b954_ejemplo", "name": "Ejemplo de la comunidad",
     "repository": "a0d7b954", "installed": False, "version": None,
     "version_latest": "3.0.0"},
    {"slug": "abcd1234_ejemplo", "name": "Ejemplo", "repository": "abcd1234",
     "installed": False, "version": None, "version_latest": "2.0.0"},
    {"slug": "abcd1234_otra", "name": "Otra", "repository": "abcd1234",
     "installed": False, "version": None, "version_latest": "1.0.0"},
]


def no_encontrado(metodo: str, ruta: str, mensaje: str = "not found") -> HAConnectionError:
    return HAConnectionError(
        f"Supervisor REST {metodo} http://supervisor{ruta} failed 404: {mensaje}",
        status=404)


class SupervisorSimulado:
    """Apunta cada petición (método, ruta, `json_body`, tiempo de espera) y
    responde con lo configurado por (método, ruta exacta). Una ruta sin
    respuesta da el mismo error que un 404 del Supervisor. Un valor que es una
    excepción se lanza; una lista de valores se consume en orden (para
    simular que algo cambia entre la vista previa y la confirmación).
    """

    def __init__(self) -> None:
        self.json: dict[tuple[str, str], Any] = {}
        self.textos: dict[str, Any] = {}
        self.llamadas: list[dict[str, Any]] = []
        # Convergencia 3 de la 034 (T058): `store_copy_stale` y las recargas
        # miran si hay una recarga de la tienda en curso. Por defecto, la
        # lista de jobs vacía, con la forma de `GET /jobs/info` del
        # Supervisor 2026.11.0 (`api/jobs.py`, `info`); un test la cambia.
        self.json[("GET", "/jobs/info")] = {"ignore_conditions": [], "jobs": []}

    def respuesta(self, metodo: str, ruta: str, valor: Any) -> None:
        self.json[(metodo.upper(), ruta)] = valor

    def texto(self, ruta: str, valor: Any) -> None:
        """Respuesta de `sv_request_text` (texto o excepción) para `ruta`."""
        self.textos[ruta] = valor

    def secuencia(self, metodo: str, ruta: str, valores: list[Any]) -> None:
        self.json[(metodo.upper(), ruta)] = _Secuencia(valores)

    async def sv_request(
        self,
        method: str,
        sv_path: str,
        json_body: Any = None,
        params: Any = None,
        timeout_seconds: float = 60.0,
    ) -> Any:
        metodo = method.upper()
        self.llamadas.append({
            "metodo": metodo, "ruta": sv_path, "json": copy.deepcopy(json_body),
            "params": copy.deepcopy(params), "timeout": timeout_seconds,
        })
        valor = self.json.get((metodo, sv_path))
        if isinstance(valor, _Secuencia):
            valor = valor.siguiente()
        if valor is None:
            raise no_encontrado(metodo, sv_path)
        if isinstance(valor, Exception):
            raise valor
        return copy.deepcopy(valor)

    async def sv_request_text(self, sv_path: str, params: Any = None,
                              timeout_seconds: float = 60.0) -> str:
        self.llamadas.append({"metodo": "GET", "ruta": sv_path, "texto": True,
                              "timeout": timeout_seconds})
        valor = self.textos.get(sv_path)
        if valor is None:
            raise no_encontrado("GET", sv_path)
        if isinstance(valor, Exception):
            raise valor
        return valor

    # ── Ayudas para los tests ──

    def escrituras(self) -> list[dict[str, Any]]:
        return [c for c in self.llamadas if c["metodo"] != "GET"]

    def rutas(self) -> list[tuple[str, str]]:
        return [(c["metodo"], c["ruta"]) for c in self.llamadas]

    def textos_pedidos(self) -> list[str]:
        return [c["ruta"] for c in self.llamadas if c.get("texto")]


class _Secuencia:
    def __init__(self, valores: list[Any]) -> None:
        self.valores = list(valores)

    def siguiente(self) -> Any:
        return self.valores.pop(0) if len(self.valores) > 1 else self.valores[0]


def tienda_normal(sv: SupervisorSimulado, *, apps: list[dict[str, Any]] | None = None) -> None:
    """La tienda de la fixture: cuatro repositorios y sus apps."""
    sv.respuesta("GET", "/store/repositories", REPOSITORIOS)
    for repo in REPOSITORIOS:
        sv.respuesta("GET", f"/store/repositories/{repo['slug']}", repo)
    sv.respuesta("GET", "/store/addons", {"addons": APPS if apps is None else apps})


def apps_con_instalada(slug: str) -> list[dict[str, Any]]:
    """Las apps de la fixture con `slug` instalada."""
    out = copy.deepcopy(APPS)
    for app in out:
        if app["slug"] == slug:
            app["installed"] = True
            app["version"] = app["version_latest"]
    return out


# ── Fichas y textos de una app (tramo 2) ──────────────────────────────────────
#
# `GET /store/addons/{slug}` (`_generate_app_information`), `…/changelog` y
# `…/documentation` (texto plano con 200 SIEMPRE, también para «no tiene» y
# «no existe»: `api/store.py`), `…/availability` (`api_process`: `{}` o 400
# con el mensaje de `validate_availability`), `GET /addons/{slug}/info` y
# `POST /addons/{slug}/options/validate` (`{message, valid, pwned}`).

CENTINELA_DOC = "centinela-clave-2"
CENTINELA_OPCION = "centinela-clave-3"
LARGO_TEXTO = 50_000
# El centinela, escrito como lo redacta `redact_secrets` (`password: …`),
# cruzando el corte por defecto de 20 000 caracteres: si se redactara por
# trozos, cada uno llevaría media clave que ninguna regla reconoce.
_POS_CENTINELA = 19_990


def texto_largo() -> str:
    """50 000 caracteres de texto de una app con un secreto cerca del corte."""
    secreto = f"\npassword: {CENTINELA_DOC}\n"
    relleno = ("## 1.0.0\n- Linea de cambios de ejemplo.\n" * 2000)
    texto = relleno[:_POS_CENTINELA] + secreto
    texto += relleno[: LARGO_TEXTO - len(texto)]
    return texto[:LARGO_TEXTO]


def ficha(slug: str, **campos: Any) -> dict[str, Any]:
    """Ficha de una app en la tienda, forma del Supervisor 2026.11.0."""
    base: dict[str, Any] = {
        "slug": slug, "name": "Ejemplo", "repository": slug.split("_", 1)[0],
        "available": True, "arch": ["amd64", "aarch64"], "homeassistant": None,
        "stage": "stable", "advanced": False, "build": False,
        "installed": False, "version": None, "version_latest": "2.0.0",
        "documentation": True, "changelog": True, "state": "unknown",
        "detached": False,
    }
    base.update(campos)
    return base


def error_400(ruta: str, mensaje: str) -> HAConnectionError:
    """Un `APIError` del Supervisor (`api_process`): 400 con `message`."""
    import json as _json
    cuerpo = _json.dumps({"result": "error", "message": mensaje})
    return HAConnectionError(
        f"Supervisor REST GET http://supervisor{ruta} failed 400: {cuerpo}", status=400)


def no_changelog(slug: str) -> str:
    return f"No changelog found for app {slug}!"


def no_documentacion(slug: str) -> str:
    return f"No documentation found for app {slug}!"


def app_inexistente(slug: str) -> str:
    return f"App {slug} does not exist in the store"
