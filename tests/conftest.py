"""Configuración compartida de la suite.

Contiene dos cosas: el adaptador que permite ejecutar los tests contra la misma
versión de aiohttp que ejecuta el add-on, y el aislamiento del directorio de
datos para que la suite no escriba fuera del árbol del proyecto.

Contexto: `aioresponses` —el doble que intercepta las llamadas HTTP en
107 puntos de 15 ficheros— construye a mano un `aiohttp.ClientResponse`. En
aiohttp 3.14 ese constructor pasó a exigir un argumento nuevo, `stream_writer`,
y `aioresponses` 0.7.9 todavía no lo pasa: 86 tests reventaban con
`TypeError: ClientResponse.__init__() missing 1 required keyword-only argument`,
íntegramente dentro de la librería de test — nada que ver con Hermes.

La solución anterior era fijar `aiohttp==3.11.18` solo en el entorno de test.
Eso escondía el problema pero abría otro peor: la suite validaba una versión de
aiohttp que el add-on NO ejecuta (producción instala `aiohttp>=3.9,<4`, hoy
3.14.3), así que los tests dejaban de ser una prueba de lo que se despliega.

Aquí se hace lo contrario: se adapta el doble de test y se corre contra la
versión real. El parche es condicional —solo actúa si el constructor exige
`stream_writer`—, así que el día que `aioresponses` se ponga al día deja de
aplicarse solo, sin quedarse enmascarando nada.
"""

from __future__ import annotations

import inspect


def _client_response_requires_stream_writer() -> bool:
    """True si esta versión de aiohttp exige `stream_writer` en el constructor."""
    try:
        from aiohttp import ClientResponse
    except ImportError:  # pragma: no cover
        return False
    param = inspect.signature(ClientResponse.__init__).parameters.get("stream_writer")
    return param is not None and param.default is inspect.Parameter.empty


def _install_aioresponses_compat() -> None:
    """Hace que `aioresponses` sepa construir respuestas de aiohttp >= 3.14."""
    try:
        import aioresponses.core as _core
    except ImportError:  # pragma: no cover — la suite no siempre lo necesita
        return

    from aiohttp import ClientResponse

    class _StreamWriterStub:
        """Lo mínimo que mira `ClientResponse` en una respuesta simulada.

        En una respuesta real este objeto contabiliza los bytes enviados; en un
        doble de test nunca se escribe nada, así que basta con el contador a 0.
        """

        output_size = 0

    class _CompatClientResponse(ClientResponse):
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs.setdefault("stream_writer", _StreamWriterStub())
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    # aioresponses resuelve la clase por su global de módulo (core.py:168),
    # así que sustituirla ahí basta y no toca aiohttp para el resto del proceso.
    _core.ClientResponse = _CompatClientResponse


if _client_response_requires_stream_writer():
    _install_aioresponses_compat()

# ── Aislamiento del directorio /data ────────────────────────────────────────
#
# Hermes guarda su estado en `/data`, que dentro del add-on es un volumen del
# contenedor. Fuera de él es una ruta real del sistema: los tests que ejercitan
# tokens de confirmación, backups o cola de jobs escribían miles de ficheros
# fuera del árbol del proyecto.
#
# Además de ensuciar, acopla los tests entre sí —un test lee el estado que dejó
# otro— y en un CI de Linux escribir en `/data` falla o requiere privilegios.
#
# Este fixture redirige TODAS las rutas de datos a un directorio temporal por
# sesión. Los tests que ya se aíslan por su cuenta siguen funcionando: su patch
# se aplica encima.

import pytest as _pytest


@_pytest.fixture(autouse=True, scope="session")
def _aislar_directorio_de_datos(tmp_path_factory):
    import hermes.crash_loop as _crash
    import hermes.fs_write as _fsw
    import hermes.oauth as _oauth
    import hermes.security as _sec
    import hermes.tools.addons as _addons
    import hermes.tools.backups as _backups

    base = tmp_path_factory.mktemp("hermes_data")

    originales = {
        (_sec, "CONFIRMATIONS_DIR"): base / "pending_confirmations",
        (_fsw, "DATA_DIR"): base,
        (_fsw, "BACKUPS_NORMAL_DIR"): base / "backups" / "normal",
        (_fsw, "BACKUPS_SENSITIVE_DIR"): base / "backups" / "sensitive",
        (_fsw, "WRITE_RATE_LIMIT_PATH"): base / "write_rate_limit.json",
        (_fsw, "CHECK_CONFIG_STATE_PATH"): base / "check_config_state.json",
        (_oauth, "_OAUTH_DIR"): base / "oauth",
        (_oauth, "_CLIENTS_DIR"): base / "oauth" / "clients",
        (_oauth, "_CODES_DIR"): base / "oauth" / "codes",
        (_oauth, "_TOKENS_DIR"): base / "oauth" / "tokens",
        (_addons, "_PENDING_JOBS_PATH"): base / "pending_jobs.json",
        (_backups, "_SAFETY_BACKUP_STATE_PATH"): base / "last_safety_backup.json",
        (_crash, "STARTUP_LOG_PATH"): base / "startup_log.json",
    }

    previos = {}
    for (modulo, nombre), destino in originales.items():
        previos[(modulo, nombre)] = getattr(modulo, nombre)
        setattr(modulo, nombre, destino)

    yield base

    for (modulo, nombre), valor in previos.items():
        setattr(modulo, nombre, valor)
