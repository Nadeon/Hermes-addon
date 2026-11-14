"""Base común de los tests de helpers del banco de Core (spec 010, US2).

Cada test abre una sesión: el lector independiente directo a Core y Hermes
conectado por el Supervisor simulado, como en producción. Hermes hace; el
lector comprueba en la HA real (FR-008). Lo que se crea se apunta y se borra
con el lector al cerrar la sesión, pase lo que pase en el test.

Todo vive dentro de un único `async with` por test, y no en `asyncSetUp` /
`asyncTearDown`: el cliente MCP usa grupos de tareas de anyio, que tienen que
abrirse y cerrarse en la misma tarea, y unittest ejecuta el montaje, el test y
el desmontaje en tareas distintas.

Comprobación de la vista previa: el lector consulta HA en el momento (no hay
caché), así que si tras la vista previa el elemento no existe o no ha cambiado,
la vista previa no tocó HA. Para las recargas, los eventos `call_service`
llegan en orden por la WebSocket: cuando se ve el de la confirmación, uno de la
vista previa ya habría llegado antes; por eso se exige que haya exactamente uno.
"""

from __future__ import annotations

import logging
import secrets
import unittest
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator

import pytest

from tests.banco.entorno import (
    EntornoBanco,
    confirmar,
    exigir_banco,
    hermes_conectado,
    llamar,
)
from tests.banco.lector import Lector

pytestmark = pytest.mark.banco


def nombre_de_prueba(dominio: str) -> str:
    """`banco_<dominio>_<hex>`: genérico y su slug es él mismo (id predecible)."""
    return f"banco_{dominio}_{secrets.token_hex(4)}"


def sin_error(tool: str, respuesta: Any) -> Any:
    """Falla si la tool devolvió `{"error": …}`; devuelve la respuesta."""
    if isinstance(respuesta, dict) and "error" in respuesta:
        raise AssertionError(f"{tool} devolvió un error: {respuesta!r}")
    return respuesta


class ServicioInexistente(Exception):
    """La tool llama a un servicio que Core no tiene: el fallo concreto de un
    hallazgo de `FALLAN_EN_BANCO`. Es su propia clase para que el `xfail` no
    se trague cualquier `AssertionError`."""


class _Errores(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.excepciones: list[BaseException] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.exc_info and record.exc_info[1] is not None:
            self.excepciones.append(record.exc_info[1])


@contextmanager
def errores_de_tools() -> Iterator[list[BaseException]]:
    """Las excepciones con las que fallan las tools dentro del servidor MCP.

    Al cliente solo le llega «Error executing tool <nombre>»: el SDK no deja
    salir el texto de una excepción inesperada. El servidor corre en este
    mismo proceso y la registra con su traza en el logger `mcp`, así que se
    recoge de ahí para ver el fallo concreto que dio HA.
    """
    manejador = _Errores()
    logger = logging.getLogger("mcp")
    logger.addHandler(manejador)
    try:
        yield manejador.excepciones
    finally:
        logger.removeHandler(manejador)


def _cadena(exc: BaseException) -> Iterator[BaseException]:
    vistas: set[int] = set()
    actual: BaseException | None = exc
    while actual is not None and id(actual) not in vistas:
        vistas.add(id(actual))
        yield actual
        actual = actual.__cause__ or actual.__context__


def es_servicio_inexistente(
    excepciones: list[BaseException], servicios: dict[str, Any], dominio: str, servicio: str
) -> bool:
    """El fallo de la tool es el 400 de Core a `POST /services/<dominio>/<servicio>`
    y Core, leído por el lector, no tiene ese servicio. Las dos cosas a la vez."""
    if servicio in (servicios.get(dominio) or {}):
        return False
    ruta = f"/services/{dominio}/{servicio}"
    return any(
        getattr(e, "status", None) == 400 and ruta in str(e)
        for exc in excepciones
        for e in _cadena(exc)
    )


@dataclass
class Sesion:
    cliente: Any
    lector: Lector
    creados: list[tuple[str, str]] = field(default_factory=list)

    # ── Lecturas del lector ───────────────────────────────────────────────
    async def items(self, dominio: str) -> list[dict[str, Any]]:
        """`<dominio>/list`; de `person/list` solo los editables (`storage`)."""
        resultado = await self.lector.listar(dominio)
        if isinstance(resultado, dict):
            return list(resultado.get("storage") or [])
        return list(resultado or [])

    async def item(self, dominio: str, id_: str) -> dict[str, Any] | None:
        for elemento in await self.items(dominio):
            if elemento.get("id") == id_:
                return elemento
        return None

    async def esperar_estado(
        self, entity_id: str, comprobar: Any, descripcion: str
    ) -> dict[str, Any]:
        return await self.lector.esperar(
            lambda: self.lector.estado(entity_id),
            lambda e: e is not None and comprobar(e),
            descripcion=f"{entity_id}: {descripcion}",
        )

    # ── Flujos en dos pasos por Hermes ────────────────────────────────────
    async def crear(
        self, tool: str, dominio: str, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Crea por Hermes en dos pasos; devuelve el elemento visto por el lector."""
        id_ = config["name"]
        entity_id = f"{dominio}.{id_}"
        vista = sin_error(tool, await llamar(self.cliente, tool, entity_id=entity_id, config=config))
        if vista["preview"]["current"] is not None:
            raise AssertionError(f"{tool}: la vista previa ve un elemento que no existe")
        if await self.item(dominio, id_) is not None:
            raise AssertionError(f"{tool}: la vista previa creó {entity_id} sin token")
        # Se apunta antes de confirmar: si la confirmación crea y luego falla
        # algo, la limpieza lo borra igual.
        self.creados.append((dominio, id_))
        resultado = sin_error(
            tool, await confirmar(self.cliente, tool, vista, entity_id=entity_id, config=config)
        )
        if resultado != {"result": "ok"}:
            raise AssertionError(f"{tool}: confirmación inesperada {resultado!r}")
        elemento = await self.lector.esperar(
            lambda: self.item(dominio, id_),
            lambda e: e is not None,
            descripcion=f"{entity_id} en {dominio}/list",
        )
        await self.esperar_estado(entity_id, lambda e: True, "entidad creada")
        return elemento

    async def editar(
        self, tool: str, dominio: str, id_: str, cambios: dict[str, Any]
    ) -> dict[str, Any]:
        """Edita por Hermes en dos pasos; devuelve el elemento tras el cambio."""
        entity_id = f"{dominio}.{id_}"
        antes = await self.item(dominio, id_)
        if antes is None:
            raise AssertionError(f"{tool}: {entity_id} no existe antes de editar")
        vista = sin_error(tool, await llamar(self.cliente, tool, entity_id=entity_id, config=cambios))
        if vista["preview"]["current"] != antes:
            raise AssertionError(
                f"{tool}: la vista previa no enseña el elemento actual: {vista['preview']!r}"
            )
        if await self.item(dominio, id_) != antes:
            raise AssertionError(f"{tool}: la vista previa cambió {entity_id} sin token")
        resultado = sin_error(
            tool, await confirmar(self.cliente, tool, vista, entity_id=entity_id, config=cambios)
        )
        if resultado != {"result": "ok"}:
            raise AssertionError(f"{tool}: confirmación inesperada {resultado!r}")
        return await self.lector.esperar(
            lambda: self.item(dominio, id_),
            lambda e: e is not None and all(e.get(k) == v for k, v in cambios.items()),
            descripcion=f"{entity_id} editado con {cambios!r}",
        )

    async def borrar(self, tool: str, dominio: str, id_: str) -> None:
        """Borra por Hermes en dos pasos y espera a que el lector no lo vea."""
        entity_id = f"{dominio}.{id_}"
        vista = sin_error(tool, await llamar(self.cliente, tool, entity_id=entity_id))
        if (vista["preview"]["current"] or {}).get("id") != id_:
            raise AssertionError(f"{tool}: la vista previa no enseña {entity_id}")
        if await self.item(dominio, id_) is None:
            raise AssertionError(f"{tool}: la vista previa borró {entity_id} sin token")
        resultado = sin_error(
            tool, await confirmar(self.cliente, tool, vista, entity_id=entity_id)
        )
        if resultado != {"result": "ok"}:
            raise AssertionError(f"{tool}: confirmación inesperada {resultado!r}")
        await self.lector.esperar(
            lambda: self.item(dominio, id_),
            lambda e: e is None,
            descripcion=f"{entity_id} fuera de {dominio}/list",
        )
        await self.lector.esperar(
            lambda: self.lector.estado(entity_id),
            lambda e: e is None,
            descripcion=f"{entity_id} sin estado",
        )

    async def recargar(self, tool: str, dominio: str, id_: str) -> None:
        """Recarga por Hermes en dos pasos: `<dominio>.reload` una sola vez y el
        helper de almacenamiento sigue ahí."""
        async with self.lector.servicios_llamados() as vistos:
            vista = sin_error(tool, await llamar(self.cliente, tool))
            if vista["preview"]["service"] != f"{dominio}.reload":
                raise AssertionError(f"{tool}: vista previa inesperada {vista['preview']!r}")
            sin_error(tool, await confirmar(self.cliente, tool, vista))
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
        if await self.item(dominio, id_) is None:
            raise AssertionError(f"{tool}: {dominio}.{id_} desapareció al recargar")
        await self.esperar_estado(f"{dominio}.{id_}", lambda e: True, "sigue tras recargar")

    async def accion(self, tool: str, **args: Any) -> Any:
        """Una acción sin confirmación (llamada a servicio)."""
        return sin_error(tool, await llamar(self.cliente, tool, **args))


async def _devolver(valor: Any) -> Any:
    return valor


def _unica(grupo: BaseExceptionGroup) -> BaseException | None:
    """La única excepción hoja de un grupo (anidado), o None si hay varias."""
    hojas: list[BaseException] = []
    pendientes: list[BaseException] = [grupo]
    while pendientes:
        exc = pendientes.pop()
        if isinstance(exc, BaseExceptionGroup):
            pendientes.extend(exc.exceptions)
        else:
            hojas.append(exc)
    return hojas[0] if len(hojas) == 1 else None


class BancoHelpers(unittest.IsolatedAsyncioTestCase):
    entorno: EntornoBanco

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.entorno = exigir_banco()

    @asynccontextmanager
    async def sesion(self) -> AsyncIterator[Sesion]:
        async with Lector(self.entorno.core_url, self.entorno.token_core) as lector:
            sesion = Sesion(cliente=None, lector=lector)
            try:
                async with hermes_conectado(self.entorno) as hermes:
                    sesion.cliente = hermes.cliente
                    yield sesion
            except BaseExceptionGroup as grupo:
                # El grupo de tareas del cliente MCP envuelve el fallo del test
                # en un ExceptionGroup; se saca el único error de dentro para
                # que el informe muestre la causa y `xfail(raises=…)` la vea.
                unica = _unica(grupo)
                if unica is None:
                    raise
                raise unica
            finally:
                # Limpieza independiente de Hermes: si el test cayó a medias,
                # la HA del banco queda limpia para los siguientes.
                for dominio, id_ in reversed(sesion.creados):
                    await lector.borrar(dominio, id_)
