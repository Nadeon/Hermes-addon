"""Humo del banco de Core: Hermes contra HA Core real como en producción (spec 010).

Solo corre en el job `banco-core` del CI (FR-007): fuera de él se salta con el
motivo de `tests/banco/entorno.py`, y dentro, un salto es un fallo.

Cubre FR-004 y FR-005 (Hermes llega a Core por el Supervisor simulado con las
funciones de arranque, `HAClient` y el registro de tools de producción), la
parte de humo de FR-008 (el efecto lo ve el lector independiente, no Hermes) y
FR-012 (ninguna credencial en el log).

Control negativo en el CI (T021): con el simulado sin reenviar al add-on los
mensajes de la WebSocket de Core, este fichero tiene que caer en rojo en el job
`banco de Core` (anotado en el commit del tramo A).
"""

from __future__ import annotations

import json
import logging
import secrets
import unittest

import aiohttp
import pytest
import structlog

from hermes.config import HA_CORE_LAST_TESTED, HA_CORE_MIN_SUPPORTED
from hermes.network import _ping_supervisor, smoke_check_ha_core_version
from tests.banco.entorno import (
    EntornoBanco,
    exigir_banco,
    hermes_conectado,
    llamar,
    obtener_entorno,
)
from tests.banco.lector import Lector

pytestmark = pytest.mark.banco


class _Banco(unittest.IsolatedAsyncioTestCase):
    entorno: EntornoBanco

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.entorno = exigir_banco()

    def _ws_url(self) -> str:
        return self.entorno.supervisor_url.replace("http://", "ws://") + "/core/api/websocket"


class TestArranqueComoEnProduccion(_Banco):
    async def test_ping_al_supervisor(self) -> None:
        self.assertTrue(await _ping_supervisor(self.entorno.supervisor_url, self.entorno.token_addon))

    async def test_version_de_core(self) -> None:
        version = await smoke_check_ha_core_version(
            self.entorno.supervisor_url,
            self.entorno.token_addon,
            HA_CORE_MIN_SUPPORTED,
            HA_CORE_LAST_TESTED,
            grace_seconds=30,
        )
        self.assertEqual(version, HA_CORE_LAST_TESTED)
        self.assertEqual(self.entorno.version_core, HA_CORE_LAST_TESTED)


class TestHermesConectado(_Banco):
    async def test_estados_por_mcp(self) -> None:
        async with hermes_conectado(self.entorno) as hermes:
            self.assertTrue(hermes.ha_client.ready)
            estados = await llamar(hermes.cliente, "ha_get_states", domain="person")
        # Al menos la persona del usuario del onboarding.
        self.assertIsInstance(estados, list)
        self.assertTrue(estados, "ha_get_states no devolvió ninguna persona")
        self.assertTrue(all(e["entity_id"].startswith("person.") for e in estados))

    async def test_servicios_por_mcp(self) -> None:
        async with hermes_conectado(self.entorno) as hermes:
            servicios = await llamar(hermes.cliente, "ha_list_services", domain="input_boolean")
        texto = json.dumps(servicios)
        self.assertIn("input_boolean", texto)
        self.assertIn("turn_on", texto)

    async def test_llamada_a_servicio_con_efecto_visto_por_el_lector(self) -> None:
        nombre = f"banco_input_boolean_{secrets.token_hex(4)}"
        async with Lector(self.entorno.core_url, self.entorno.token_core) as lector:
            creado = await lector.crear("input_boolean", {"name": nombre})
            entity_id = f"input_boolean.{creado['id']}"
            try:
                await lector.esperar(
                    lambda: lector.estado(entity_id),
                    lambda e: e is not None and e["state"] == "off",
                    descripcion=f"{entity_id} creado y apagado",
                )
                async with hermes_conectado(self.entorno) as hermes:
                    await llamar(
                        hermes.cliente,
                        "ha_call_service",
                        domain="input_boolean",
                        service="turn_on",
                        service_data={"entity_id": entity_id},
                    )
                await lector.esperar(
                    lambda: lector.estado(entity_id),
                    lambda e: e is not None and e["state"] == "on",
                    descripcion=f"{entity_id} encendido por Hermes",
                )
            finally:
                await lector.borrar("input_boolean", creado["id"])


class TestFiltrosDelSimulado(_Banco):
    async def test_token_de_addon_erroneo(self) -> None:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{self.entorno.supervisor_url}/core/api/states",
                headers={"Authorization": "Bearer token-que-no-es"},
            ) as r:
                self.assertEqual(r.status, 401)
            async with s.ws_connect(self._ws_url()) as ws:
                self.assertEqual((await ws.receive_json(timeout=10))["type"], "auth_required")
                await ws.send_json({"type": "auth", "access_token": "token-que-no-es"})
                self.assertEqual((await ws.receive_json(timeout=10))["type"], "auth_invalid")

    async def test_comando_supervisor_rechazado(self) -> None:
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(self._ws_url()) as ws:
                await ws.receive_json(timeout=10)
                await ws.send_json({"type": "auth", "access_token": self.entorno.token_addon})
                self.assertEqual((await ws.receive_json(timeout=10))["type"], "auth_ok")
                await ws.send_json({"id": 1, "type": "supervisor/info"})
                respuesta = await ws.receive_json(timeout=10)
        self.assertEqual(respuesta["id"], 1)
        self.assertFalse(respuesta["success"])
        self.assertEqual(respuesta["error"]["code"], "unauthorized")


class TestSinCredencialesEnElLog(_Banco):
    """FR-012, SC-005: ni el token de add-on ni el de Core salen en el log."""

    async def test_arranque_y_llamada_sin_tokens_en_el_log(self) -> None:
        with self.assertLogs(level=logging.DEBUG) as caplog, structlog.testing.capture_logs() as eventos:
            logging.getLogger("banco-centinela").debug("inicio")
            async with hermes_conectado(self.entorno) as hermes:
                await llamar(hermes.cliente, "ha_get_states", domain="person")
        texto = "\n".join(caplog.output) + "\n" + repr(eventos)
        for token in (self.entorno.token_addon, self.entorno.token_core):
            self.assertNotIn(token, texto)
        self.assertTrue(eventos, "Hermes debería haber registrado la conexión")

    def test_repr_del_entorno_sin_tokens(self) -> None:
        entorno = obtener_entorno()
        for texto in (repr(entorno), str(entorno)):
            self.assertNotIn(entorno.token_addon, texto)
            self.assertNotIn(entorno.token_core, texto)
