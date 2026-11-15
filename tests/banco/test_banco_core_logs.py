"""Banco de Core: logs de Core (spec 012, tramo A, T015).

Las cinco tools de `core_logs` contra HA Core real, con el lector
independiente comprobando cada efecto directamente en Core:

- **Log del sistema**: el lector siembra con `system_log.write` un mensaje con
  un centinela y una marca única; `ha_list_system_log` lo ve (con `count`) y
  el centinela sale tapado.
- **Log de errores**: el contenedor del banco no tiene Supervisor, así que HA
  sí escribe fichero de log y `ha_get_error_log` devuelve líneas.
- **Niveles**: `ha_get_log_levels` incluye `input_boolean` (cargada en el
  banco). `ha_set_log_level` por integración y por módulo, en dos pasos: la
  vista previa no cambia nada (lo comprueba el lector con `logger/log_info`),
  la confirmación sí, y se vuelve atrás con `NOTSET` por la propia tool (el
  lector lo deja en `NOTSET` también al cerrar, pase lo que pase).
- **Limpieza**: `ha_clear_system_log` en dos pasos; tras la vista previa el
  lector sigue viendo la entrada sembrada, tras confirmar ya no.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo

pytestmark = pytest.mark.banco

_CENTINELA = "centinela-012"
_LOGGER = "homeassistant.components.input_boolean"


async def _sembrar(s: SesionEscrituras, marca: str) -> None:
    """`system_log.write` con un secreto en el mensaje; espera a verlo."""
    await s.lector.comando({
        "type": "call_service",
        "domain": "system_log",
        "service": "write",
        "service_data": {
            "message": f"{marca} login fallido password={_CENTINELA}",
            "level": "error",
            "logger": _LOGGER,
        },
    })
    await s.lector.esperar(
        lambda: s.lector.comando({"type": "system_log/list"}),
        lambda entradas: _con_marca(entradas, marca),
        descripcion=f"entrada {marca} en system_log/list",
    )


def _con_marca(entradas: Any, marca: str) -> bool:
    return any(marca in m for e in entradas for m in e.get("message", []))


async def _nivel(s: SesionEscrituras, dominio: str) -> int | None:
    niveles = await s.lector.comando({"type": "logger/log_info"})
    return next((n["level"] for n in niveles if n["domain"] == dominio), None)


def _restaurar(s: SesionEscrituras, campo: str, nombre: str, tipo: str) -> None:
    """Limpieza independiente de Hermes: `NOTSET` (quita el ajuste guardado)."""

    async def limpiar() -> None:
        await s.lector.comando({"type": tipo, campo: nombre, "level": "NOTSET",
                                "persistence": "none"})

    s.limpiezas.append(limpiar)


class TestLogDelSistema(BancoEscrituras):
    async def test_lista_y_limpieza(self) -> None:
        marca = f"banco-012-{sufijo()}"
        async with self.sesion() as s:
            await _sembrar(s, marca)

            lista = await s.accion("ha_list_system_log", integration="input_boolean")
            texto = json.dumps(lista, ensure_ascii=False)
            self.assertNotIn(_CENTINELA, texto)
            entrada = next(e for e in lista["items"] if any(marca in m for m in e["messages"]))
            self.assertEqual(entrada["level"], "ERROR")
            self.assertEqual(entrada["logger"], _LOGGER)
            self.assertGreaterEqual(entrada["count"], 1)
            self.assertTrue(entrada["last_seen"])

            tool = "ha_clear_system_log"
            vista = await s.vista(tool)
            self.assertGreaterEqual(vista["preview"]["entries"], 1)
            self.assertGreaterEqual(vista["preview"]["by_level"].get("ERROR", 0), 1)
            # La vista previa no ha limpiado nada.
            self.assertTrue(_con_marca(await s.lector.comando({"type": "system_log/list"}), marca))
            self.assertEqual(await s.confirmar(tool, vista), {"result": "ok"})
            # Tras confirmar, la entrada sembrada ya no está. No se exige la
            # lista vacía: HA puede registrar otro aviso entre medias.
            await s.lector.esperar(
                lambda: s.lector.comando({"type": "system_log/list"}),
                lambda entradas: not _con_marca(entradas, marca),
                descripcion=f"entrada {marca} limpiada de system_log/list",
            )

    async def test_log_de_errores(self) -> None:
        marca = f"banco-012-{sufijo()}"
        async with self.sesion() as s:
            await _sembrar(s, marca)
            log = await s.accion("ha_get_error_log", lines=50)
            self.assertEqual(log["lines_requested"], 50)
            self.assertGreater(log["lines_returned"], 0)
            self.assertTrue(log["log"])
            self.assertNotIn(_CENTINELA, json.dumps(log, ensure_ascii=False))


class TestNivelesDeLog(BancoEscrituras):
    async def test_lectura(self) -> None:
        async with self.sesion() as s:
            niveles = await s.accion("ha_get_log_levels", domain="input_boolean")
            self.assertEqual([i["domain"] for i in niveles["items"]], ["input_boolean"])
            self.assertEqual(niveles["items"][0]["level_value"], await _nivel(s, "input_boolean"))

    async def test_nivel_de_integracion(self) -> None:
        tool = "ha_set_log_level"
        async with self.sesion() as s:
            _restaurar(s, "integration", "input_boolean", "logger/integration_log_level")
            antes = await _nivel(s, "input_boolean")
            self.assertNotEqual(antes, 10)

            args = {"integration": "input_boolean", "level": "debug"}
            vista = await s.vista(tool, **args)
            self.assertEqual(vista["preview"]["new_level"], "DEBUG")
            self.assertEqual(vista["preview"]["previous_level"],
                             {10: "DEBUG", 20: "INFO", 30: "WARNING", 40: "ERROR"}.get(antes))
            self.assertEqual(await _nivel(s, "input_boolean"), antes)
            await s.confirmar(tool, vista, **args)
            await s.lector.esperar(lambda: _nivel(s, "input_boolean"), lambda n: n == 10,
                                   descripcion="input_boolean en DEBUG")

            args = {"integration": "input_boolean", "level": "NOTSET"}
            vista = await s.vista(tool, **args)
            await s.confirmar(tool, vista, **args)
            await s.lector.esperar(lambda: _nivel(s, "input_boolean"), lambda n: n == antes,
                                   descripcion="input_boolean de vuelta a su nivel")

    async def test_nivel_de_modulo(self) -> None:
        tool = "ha_set_log_level"
        async with self.sesion() as s:
            _restaurar(s, "module", _LOGGER, "logger/log_level")
            antes = await _nivel(s, "input_boolean")
            self.assertNotEqual(antes, 10)

            args = {"module": _LOGGER, "level": "DEBUG", "persistence": "none"}
            vista = await s.vista(tool, **args)
            self.assertIsNone(vista["preview"]["previous_level"])
            self.assertEqual(await _nivel(s, "input_boolean"), antes)
            await s.confirmar(tool, vista, **args)
            # `logger/log_info` da el nivel efectivo de este mismo logger.
            await s.lector.esperar(lambda: _nivel(s, "input_boolean"), lambda n: n == 10,
                                   descripcion=f"{_LOGGER} en DEBUG")

            args["level"] = "NOTSET"
            vista = await s.vista(tool, **args)
            await s.confirmar(tool, vista, **args)
            await s.lector.esperar(lambda: _nivel(s, "input_boolean"), lambda n: n == antes,
                                   descripcion=f"{_LOGGER} de vuelta a su nivel")
