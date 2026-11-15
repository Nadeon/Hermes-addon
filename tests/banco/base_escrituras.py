"""Base de los tests de escrituras de Core en el banco (spec 028).

Extiende el patrón de `tests/banco/base_helpers.py` (010) sin modificarlo: un
`async with` por test con el lector independiente directo a Core y Hermes
conectado por el Supervisor simulado, como en producción. Hermes hace; el
lector comprueba en la HA real.

Lo que añade:

- **Configuración de Hermes por test**: `ha_fire_event` solo dispara tipos de
  evento de `fire_event_allowlist`, que se fija al registrar las tools. El
  `hermes_conectado` de la 010 usa la configuración por defecto (lista vacía),
  así que aquí se monta Hermes igual pero con los cambios que pida el test.
- **Limpiezas arbitrarias**: lo que se crea aquí no son solo helpers
  (automatizaciones, scripts y escenas por REST, dashboards y recursos por
  WebSocket). Cada test apunta una función de limpieza que el lector ejecuta
  al cerrar la sesión, pase lo que pase.
- **Ayudas para los dos pasos**: la vista previa tiene que traer token, y la
  confirmación no puede devolver un error.
- **Barrera del lector** (T031): para demostrar que una vista previa NO ha
  llamado a un servicio, no basta con contar llamadas al final (si la vista
  previa llamara y la confirmación no, se vería una sola). Tras la vista
  previa, el lector llama él mismo a un servicio inocuo y espera a verlo en el
  bus: los eventos llegan en orden por la misma WebSocket, así que lo que la
  vista previa hubiera llamado ya estaría en la lista.

Todo dentro de un único `async with` por test, por el mismo motivo que en la
010: el cliente MCP usa grupos de tareas de anyio, que tienen que abrirse y
cerrarse en la misma tarea.
"""

from __future__ import annotations

import logging
import secrets
import unittest
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

import pytest

from tests.banco.base_helpers import _cadena, _devolver, _unica, sin_error
from tests.banco.entorno import EntornoBanco, confirmar, exigir_banco, llamar
from tests.banco.lector import Lector

pytestmark = pytest.mark.banco

_log = logging.getLogger(__name__)


class RechazadoPorCore(Exception):
    """La tool falla porque Core rechaza con 400 la llamada que le hace Hermes:
    el fallo concreto de un hallazgo de la 028. Es su propia clase para que un
    `xfail` estricto no se trague cualquier `AssertionError`."""


def rechazado_por_core(excepciones: list[BaseException], dominio: str, servicio: str) -> bool:
    """El fallo de la tool, registrado por el servidor MCP, es un 400 de Core a
    `POST /services/<dominio>/<servicio>` (el mismo criterio que
    `es_servicio_inexistente` de la 010, sin exigir que el servicio falte)."""
    ruta = f"/services/{dominio}/{servicio}"
    return any(
        getattr(e, "status", None) == 400 and ruta in str(e)
        for exc in excepciones
        for e in _cadena(exc)
    )


def sufijo() -> str:
    """Hex aleatorio para nombres de prueba únicos (`banco_<x>_<hex>`, `banco-<hex>`)."""
    return secrets.token_hex(4)


@asynccontextmanager
async def hermes_con(entorno: EntornoBanco, **config: Any) -> AsyncIterator[Any]:
    """Hermes conectado a la HA del banco con `HermesConfig(**config)`.

    Igual que `tests.banco.entorno.hermes_conectado` (010): `HAClient` contra
    el Supervisor simulado con el token de add-on y el registro de tools de
    producción; solo cambia la configuración.
    """
    from mcp import Client

    from hermes.__main__ import _build_mcp
    from hermes.config import HermesConfig
    from hermes.ha import HAClient
    from hermes.health import HealthServer

    ha_client = HAClient(entorno.supervisor_url, entorno.token_addon, HealthServer())
    try:
        await ha_client.start(timeout_seconds=30)
        mcp = _build_mcp(HermesConfig(**config), ha_client)
        async with Client(mcp) as cliente:
            yield cliente
    finally:
        await ha_client.stop()


@dataclass
class SesionEscrituras:
    cliente: Any
    lector: Lector
    limpiezas: list[Callable[[], Awaitable[None]]] = field(default_factory=list)
    _barrera: str | None = None

    # ── Llamadas por Hermes ───────────────────────────────────────────────
    async def accion(self, tool: str, **args: Any) -> Any:
        """Una llamada sin confirmación; falla si la tool devuelve un error."""
        return sin_error(tool, await llamar(self.cliente, tool, **args))

    async def vista(self, tool: str, **args: Any) -> dict[str, Any]:
        """Primer paso: tiene que devolver vista previa y token, sin error."""
        respuesta = sin_error(tool, await llamar(self.cliente, tool, **args))
        if not isinstance(respuesta, dict) or not isinstance(
            respuesta.get("confirmation_token"), str
        ):
            raise AssertionError(f"{tool}: se esperaba una vista previa con token: {respuesta!r}")
        return respuesta

    async def confirmar(self, tool: str, vista: dict[str, Any], **args: Any) -> Any:
        """Segundo paso: la misma llamada con el token; falla si devuelve un error."""
        return sin_error(tool, await confirmar(self.cliente, tool, vista, **args))

    # ── Lecturas del lector ───────────────────────────────────────────────
    async def esperar_estado(
        self, entity_id: str, comprobar: Callable[[dict[str, Any] | None], bool], descripcion: str
    ) -> dict[str, Any] | None:
        return await self.lector.esperar(
            lambda: self.lector.estado(entity_id),
            comprobar,
            descripcion=f"{entity_id}: {descripcion}",
        )

    async def config_guardada(self, dominio: str, id_: str) -> tuple[int, Any]:
        """`GET /api/config/<dominio>/config/<id>` directo a Core."""
        return await self.lector.rest("GET", f"/api/config/{dominio}/config/{id_}")

    async def input_boolean(self, nombre: str) -> str:
        """Crea con el lector un `input_boolean` apagado; devuelve su entity_id."""
        creado = await self.lector.crear("input_boolean", {"name": nombre})
        self.limpiezas.append(lambda: self.lector.borrar("input_boolean", creado["id"]))
        entity_id = f"input_boolean.{creado['id']}"
        await self.esperar_estado(entity_id, lambda e: e is not None and e["state"] == "off", "apagado")
        return entity_id

    async def preparar_barrera(self) -> str:
        """El `input_boolean` del lector para las barreras (se crea una vez).

        Se prepara ANTES de abrir la ventana que cuenta las llamadas, para que
        crearlo no se mezcle con lo que se quiere ver.
        """
        if self._barrera is None:
            self._barrera = await self.input_boolean(f"banco_input_boolean_{sufijo()}")
        return self._barrera

    async def barrera(self, vistos: list[tuple[str, str]]) -> None:
        """Llamada propia del lector (`input_boolean.toggle`) vista en el bus.

        Al volver, todo lo que se llamó en HA antes de esta barrera está ya en
        `vistos`: los eventos `call_service` llegan en orden por la WebSocket
        del lector, y la vista previa de Hermes respondió antes de que el
        lector llamara.
        """
        entidad = await self.preparar_barrera()
        antes = vistos.count(("input_boolean", "toggle"))
        await self.lector.comando(
            {
                "type": "call_service",
                "domain": "input_boolean",
                "service": "toggle",
                "target": {"entity_id": entidad},
            }
        )
        await self.lector.esperar(
            lambda: _devolver(vistos),
            lambda v: v.count(("input_boolean", "toggle")) > antes,
            descripcion="barrera del lector (input_boolean.toggle) en el bus",
        )

    def limpiar_config(self, dominio: str, id_: str) -> None:
        """Apunta el borrado por REST de una automatización, script o escena."""

        async def borrar() -> None:
            await self.lector.rest("DELETE", f"/api/config/{dominio}/config/{id_}")

        self.limpiezas.append(borrar)

    async def recarga_vista_una_vez(self, tool: str, dominio: str) -> None:
        """`ha_reload_*` en dos pasos: la vista previa no llama (lo demuestra la
        barrera del lector) y `<dominio>.reload` se ve en el bus una sola vez,
        la de la confirmación.

        Control negativo (T031, en el CI): con `guarded_reload` llamando al
        servicio en la vista previa y no en la confirmación, cae aquí, en la
        comprobación de después de la barrera.
        """
        await self.preparar_barrera()
        async with self.lector.servicios_llamados() as vistos:
            vista = await self.vista(tool)
            if vista["preview"].get("service") != f"{dominio}.reload":
                raise AssertionError(f"{tool}: vista previa inesperada {vista['preview']!r}")
            await self.barrera(vistos)
            if (dominio, "reload") in vistos:
                raise AssertionError(
                    f"{tool}: la vista previa ha llamado a {dominio}.reload sin token"
                )
            await self.confirmar(tool, vista)
            await self.lector.esperar(
                lambda: _devolver(vistos),
                lambda v: (dominio, "reload") in v,
                descripcion=f"{dominio}.reload en el bus",
            )
        recargas = [v for v in vistos if v == (dominio, "reload")]
        if len(recargas) != 1:
            raise AssertionError(
                f"{tool}: se esperaba una sola llamada a {dominio}.reload (la de la "
                f"confirmación) y se vieron {len(recargas)}"
            )


class BancoEscrituras(unittest.IsolatedAsyncioTestCase):
    entorno: EntornoBanco

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.entorno = exigir_banco()

    @asynccontextmanager
    async def sesion(self, **config: Any) -> AsyncIterator[SesionEscrituras]:
        async with Lector(self.entorno.core_url, self.entorno.token_core) as lector:
            sesion = SesionEscrituras(cliente=None, lector=lector)
            try:
                async with hermes_con(self.entorno, **config) as cliente:
                    sesion.cliente = cliente
                    yield sesion
            except BaseExceptionGroup as grupo:
                # Como en la 010: se saca el único error del grupo de tareas del
                # cliente MCP para que el informe enseñe la causa y
                # `xfail(raises=…)` la vea.
                unica = _unica(grupo)
                if unica is None:
                    raise
                raise unica
            finally:
                # Limpieza independiente de Hermes y en orden inverso. Un fallo
                # aquí no puede tapar el del test: se registra y se sigue (los
                # nombres son únicos, un resto no interfiere con otro test).
                for limpiar in reversed(sesion.limpiezas):
                    try:
                        await limpiar()
                    except Exception as exc:  # noqa: BLE001 — cualquier fallo de limpieza
                        _log.warning("limpieza del banco fallida: %s", exc)
