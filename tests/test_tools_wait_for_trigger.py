"""Tests de `ha_wait_for_trigger` (spec 017, tramo D, T040, FR-009).

Cola simulada en vez de la WebSocket: `ws_subscribe_queue` devuelve una cola
que el test rellena; `manifest/get` responde por integración. Datos
ficticios (`input_boolean.prueba`, `light.salon`, el centinela).

Controles negativos, comprobados y restaurados:
- aceptar una integración sin mirar `is_built_in` → caen
  `test_integracion_personalizada` y `test_trigger_de_dispositivo_personalizado`;
- quitar la cancelación del `finally` → cae `test_siempre_cancela_la_suscripcion`
  (y los que miran `desuscritas`);
- sin `redact_structure` en el disparo → cae `test_disparo_redactado`;
- gestor no compartido (cada registro con el suyo) → cae
  `test_cupo_compartido_con_la_espera_de_evento`.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any

from hermes.ha import HAConnectionError, _WS_CLOSED_SENTINEL
import hermes.tools.wait_for_event as wfe_mod
import hermes.tools.wait_for_trigger as wft_mod

CENTINELA = "centinela-017"


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


class FakeHA:
    """`HAClient` mínimo para la espera de trigger."""

    def __init__(self, manifiestos: dict[str, Any] | None = None) -> None:
        self.ready = True
        self.manifiestos = manifiestos or {}
        self.eventos: list[Any] = []
        self.suscripciones: list[dict] = []
        self.desuscritas: list[int] = []
        self.manifest_pedidos: list[str] = []
        self.error_al_suscribir: HAConnectionError | None = None
        self.cola: asyncio.Queue | None = None
        self.eventos_para_evento: list[Any] = []

    async def wait_ready(self, timeout: float = 5.0) -> bool:
        return self.ready

    async def ws_send(self, payload: dict) -> Any:
        assert payload["type"] == "manifest/get", payload
        dominio = payload["integration"]
        self.manifest_pedidos.append(dominio)
        valor = self.manifiestos.get(dominio)
        if isinstance(valor, Exception):
            raise valor
        if valor is None:
            raise HAConnectionError("HA WS command failed: Integration not found",
                                    code="not_found")
        return valor

    async def ws_subscribe_queue(self, payload: dict):
        self.suscripciones.append(payload)
        if self.error_al_suscribir is not None:
            raise self.error_al_suscribir
        self.cola = asyncio.Queue()
        for ev in self.eventos:
            self.cola.put_nowait(ev)
        return 7, self.cola, 0

    async def ws_subscribe_events_queue(self, event_type: str):
        cola: asyncio.Queue = asyncio.Queue()
        for ev in self.eventos_para_evento:
            cola.put_nowait(ev)
        return 9, cola, 0

    async def ws_unsubscribe_events_queue(self, sub_id: int) -> None:
        self.desuscritas.append(sub_id)


def _disparo(**extra: Any) -> dict:
    trigger = {"platform": "state", "entity_id": "input_boolean.prueba",
               "from_state": {"state": "off"}, "to_state": {"state": "on"}, **extra}
    return {"variables": {"trigger": trigger}, "context": {"id": "x"}}


class _Base(unittest.IsolatedAsyncioTestCase):
    MAX_BYTES = 65536

    def _registrar(self, fake: FakeHA, *, max_concurrent: int = 5,
                   gestor: wfe_mod._WaitManager | None = None) -> DummyMCP:
        self.fake = fake
        self.gestor = gestor or wfe_mod._WaitManager(max_concurrent=max_concurrent)
        self.mcp = DummyMCP()
        wft_mod.register(self.mcp, fake, manager=self.gestor,
                         wait_for_event_max_seconds=30,
                         response_max_bytes=self.MAX_BYTES)
        return self.mcp

    async def esperar(self, trigger: Any, **kw: Any) -> dict:
        return await self.mcp.tools["ha_wait_for_trigger"](None, trigger, **kw)


class TestResultados(_Base):
    async def test_disparo(self) -> None:
        fake = FakeHA()
        fake.eventos = [_disparo()]
        self._registrar(fake)
        r = await self.esperar({"trigger": "state", "entity_id": "input_boolean.prueba"})
        self.assertIs(r["matched"], True)
        self.assertEqual(r["trigger"]["to_state"]["state"], "on")
        self.assertIn("waited_seconds", r)
        self.assertNotIn("truncated", r)
        self.assertEqual(fake.suscripciones[0]["type"], "subscribe_trigger")
        self.assertEqual(fake.desuscritas, [7])
        self.assertEqual(self.gestor.active_count, 0)

    async def test_plazo(self) -> None:
        self._registrar(FakeHA())
        r = await self.esperar({"trigger": "state", "entity_id": "x.y"}, timeout_seconds=1)
        self.assertEqual((r["matched"], r["reason"]), (False, "timeout"))
        self.assertEqual(self.fake.desuscritas, [7])

    async def test_cancelada_sin_esperar_al_keepalive(self) -> None:
        self._registrar(FakeHA())
        tarea = asyncio.ensure_future(
            self.esperar({"trigger": "state", "entity_id": "x.y"}, timeout_seconds=20))
        for _ in range(50):
            await asyncio.sleep(0.01)
            if self.gestor.active_count:
                break
        espera = self.gestor.list_active()[0]
        self.assertEqual(espera["kind"], "trigger")
        self.assertEqual(espera["trigger_platform"], "state")
        inicio = asyncio.get_running_loop().time()
        self.assertTrue(self.gestor.cancel(espera["wait_id"]))
        r = await asyncio.wait_for(tarea, timeout=2)
        self.assertLess(asyncio.get_running_loop().time() - inicio, 2)
        self.assertEqual(r["reason"], "cancelled")
        self.assertEqual(self.fake.desuscritas, [7])

    async def test_reconexion(self) -> None:
        fake = FakeHA()
        fake.eventos = [_WS_CLOSED_SENTINEL]
        self._registrar(fake)
        r = await self.esperar({"trigger": "state", "entity_id": "x.y"})
        self.assertEqual(r["reason"], "ws_reconnect")
        self.assertIn("note", r)

    async def test_plazos_fuera_de_rango(self) -> None:
        self._registrar(FakeHA())
        r = await self.esperar({"trigger": "state"}, timeout_seconds=31)
        self.assertIn("exceeds max allowed", r["error"])
        r = await self.esperar({"trigger": "state"}, timeout_seconds=0)
        self.assertEqual(r["error"], "timeout_seconds must be >= 1")
        self.assertEqual(self.fake.suscripciones, [])

    async def test_variables_en_el_payload(self) -> None:
        fake = FakeHA()
        fake.eventos = [_disparo()]
        self._registrar(fake)
        await self.esperar({"trigger": "template", "value_template": "{{ x }}"},
                           variables={"x": True})
        self.assertEqual(fake.suscripciones[0]["variables"], {"x": True})

    async def test_sin_variables_no_van_en_el_payload(self) -> None:
        fake = FakeHA()
        fake.eventos = [_disparo()]
        self._registrar(fake)
        await self.esperar({"trigger": "state", "entity_id": "x.y"})
        self.assertNotIn("variables", fake.suscripciones[0])

    async def test_keepalive_avisa_y_un_fallo_no_corta(self) -> None:
        class _Ctx:
            def __init__(self) -> None:
                self.avisos = 0

            async def report_progress(self, **kw):
                self.avisos += 1
                raise ValueError("sin petición")

        self._registrar(FakeHA())
        ctx = _Ctx()
        original = wft_mod._KEEPALIVE_INTERVAL
        wft_mod._KEEPALIVE_INTERVAL = 0.05
        try:
            r = await self.mcp.tools["ha_wait_for_trigger"](
                ctx, {"trigger": "state", "entity_id": "x.y"}, timeout_seconds=1)
        finally:
            wft_mod._KEEPALIVE_INTERVAL = original
        self.assertEqual(r["reason"], "timeout")
        self.assertGreater(ctx.avisos, 0)


class TestCupo(_Base):
    async def test_cupo_compartido_con_la_espera_de_evento(self) -> None:
        gestor = wfe_mod._WaitManager(max_concurrent=1)
        fake = FakeHA()
        self._registrar(fake, gestor=gestor)
        mcp_evento = DummyMCP()
        wfe_mod.register(mcp_evento, fake, wait_for_event_max_seconds=30, manager=gestor)
        tarea = asyncio.ensure_future(
            mcp_evento.tools["ha_wait_for_event"](None, "state_changed", timeout_seconds=5))
        for _ in range(50):
            await asyncio.sleep(0.01)
            if gestor.active_count:
                break
        try:
            r = await self.esperar({"trigger": "state", "entity_id": "x.y"})
            self.assertEqual(r["error"], "too_many_waits")
            self.assertEqual(fake.suscripciones, [])
        finally:
            for w in list(gestor._active):
                gestor.cancel(w)
            await tarea


class TestListaCerrada(_Base):
    MANIFIESTOS = {
        "light": {"domain": "light", "is_built_in": True},
        "zwave_js": {"domain": "zwave_js", "is_built_in": True},
        "mi_custom": {"domain": "mi_custom", "is_built_in": False},
        "samsungtv": {"domain": "samsungtv", "is_built_in": True},
        "webostv": {"domain": "webostv", "is_built_in": True},
        "falla": HAConnectionError("HA WS command failed: boom password=" + CENTINELA,
                                   code="unknown_error"),
    }

    def _fake(self) -> FakeHA:
        fake = FakeHA(dict(self.MANIFIESTOS))
        fake.eventos = [_disparo()]
        return fake

    async def _admitido(self, trigger: Any) -> None:
        self._registrar(self._fake())
        r = await self.esperar(trigger)
        self.assertIs(r.get("matched"), True, r)
        self.assertEqual(len(self.fake.suscripciones), 1)

    async def _rechazado(self, trigger: Any) -> dict:
        self._registrar(self._fake())
        r = await self.esperar(trigger)
        self.assertEqual(r.get("error"), "trigger_not_allowed", r)
        self.assertIn("hint", r)
        self.assertEqual(self.fake.suscripciones, [], "se suscribió a algo no admitido")
        self.assertEqual(self.gestor.active_count, 0)
        return r

    async def test_estado(self) -> None:
        await self._admitido({"trigger": "state", "entity_id": "input_boolean.prueba"})
        self.assertEqual(self.fake.manifest_pedidos, [])

    async def test_clave_antigua_platform(self) -> None:
        await self._admitido({"platform": "numeric_state", "entity_id": "sensor.t",
                              "above": 1})

    async def test_de_proposito_de_ha(self) -> None:
        await self._admitido({"trigger": "light.turned_on",
                              "target": {"entity_id": "light.salon"}})
        self.assertEqual(self.fake.manifest_pedidos, ["light"])

    async def test_dispositivo_de_ha(self) -> None:
        await self._admitido({"trigger": "device", "domain": "zwave_js",
                              "device_id": "<device_id>", "type": "event"})

    async def test_webhook(self) -> None:
        await self._rechazado({"trigger": "webhook", "webhook_id": "x"})

    async def test_conversation(self) -> None:
        await self._rechazado({"trigger": "conversation", "command": "hola"})

    async def test_tele_samsung(self) -> None:
        await self._rechazado({"trigger": "samsungtv.turn_on", "entity_id": "media_player.tv"})

    async def test_dispositivo_webostv(self) -> None:
        await self._rechazado({"trigger": "device", "domain": "webostv",
                               "device_id": "<device_id>", "type": "webostv.turn_on"})

    async def test_sin_punto_fuera_de_la_lista(self) -> None:
        await self._rechazado({"trigger": "plataforma_nueva"})

    async def test_integracion_personalizada(self) -> None:
        r = await self._rechazado({"trigger": "mi_custom.algo"})
        self.assertIn("mi_custom", r["detail"])

    async def test_trigger_de_dispositivo_personalizado(self) -> None:
        await self._rechazado({"trigger": "device", "domain": "mi_custom",
                               "device_id": "<device_id>", "type": "x"})

    async def test_dispositivo_sin_dominio(self) -> None:
        await self._rechazado({"trigger": "device", "device_id": "<device_id>"})

    async def test_manifest_que_falla(self) -> None:
        r = await self._rechazado({"trigger": "falla.algo"})
        self.assertNotIn(CENTINELA, json.dumps(r))

    async def test_integracion_desconocida(self) -> None:
        await self._rechazado({"trigger": "nadie.algo"})

    async def test_cada_elemento_de_una_lista(self) -> None:
        await self._rechazado([
            {"trigger": "state", "entity_id": "input_boolean.prueba"},
            {"trigger": "webhook", "webhook_id": "x"},
        ])

    async def test_platform_tambien_se_comprueba(self) -> None:
        await self._rechazado({"platform": "webhook", "webhook_id": "x"})

    async def test_lista_admitida(self) -> None:
        await self._admitido([
            {"trigger": "state", "entity_id": "input_boolean.prueba"},
            {"trigger": "light.turned_on", "target": {"entity_id": "light.salon"}},
        ])
        self.assertEqual(self.gestor.active_count, 0)

    async def test_forma_invalida_sin_suscribir(self) -> None:
        self._registrar(self._fake())
        for malo in ([], ["state"], {"entity_id": "x.y"},
                     {"trigger": "state", "platform": "state"}, {"trigger": 3}):
            r = await self.esperar(malo)
            self.assertEqual(r.get("error"), "invalid_argument", (malo, r))
        r = await self.esperar({"trigger": "state"}, variables=["x"])
        self.assertEqual(r.get("error"), "invalid_argument")
        self.assertEqual(self.fake.suscripciones, [])


class TestErroresYRedaccion(_Base):
    async def test_trigger_que_ha_rechaza(self) -> None:
        fake = FakeHA()
        fake.error_al_suscribir = HAConnectionError(
            f"HA WS command failed: invalid entity_id {CENTINELA}", code="invalid_format")
        self._registrar(fake)
        r = await self.esperar({"trigger": "state", "entity_id": "token=" + CENTINELA})
        self.assertEqual(r["error"], "invalid_trigger")
        self.assertEqual(self.gestor.active_count, 0)
        self.assertEqual(fake.desuscritas, [])

    async def test_mensaje_de_ha_redactado(self) -> None:
        fake = FakeHA()
        fake.error_al_suscribir = HAConnectionError(
            "HA WS command failed: bad value password=" + CENTINELA,
            code="home_assistant_error")
        self._registrar(fake)
        r = await self.esperar({"trigger": "state", "entity_id": "x.y"})
        self.assertEqual(r["error"], "invalid_trigger")
        self.assertNotIn(CENTINELA, json.dumps(r))

    async def test_siempre_cancela_la_suscripcion(self) -> None:
        class _Rota(asyncio.Queue):
            async def get(self):
                raise RuntimeError("se rompe la cola")

        fake = FakeHA()
        self._registrar(fake)

        async def suscribir(payload):
            fake.suscripciones.append(payload)
            return 7, _Rota(), 0

        fake.ws_subscribe_queue = suscribir
        r = await self.esperar({"trigger": "state", "entity_id": "x.y"})
        self.assertIn("error", r)
        self.assertEqual(fake.desuscritas, [7])
        self.assertEqual(self.gestor.active_count, 0)

    async def test_disparo_redactado(self) -> None:
        fake = FakeHA()
        fake.eventos = [_disparo(to_state={
            "state": "idle", "attributes": {"access_token": CENTINELA}})]
        self._registrar(fake)
        r = await self.esperar({"trigger": "state", "entity_id": "camera.x"})
        self.assertIs(r["matched"], True)
        self.assertNotIn(CENTINELA, json.dumps(r))

    async def test_disparo_que_no_cabe(self) -> None:
        self.MAX_BYTES = 600
        fake = FakeHA()
        fake.eventos = [_disparo(to_state={"state": "on",
                                           "attributes": {"x": "a" * 2000}})]
        self._registrar(fake)
        r = await self.esperar({"trigger": "state", "entity_id": "x.y"})
        self.assertIs(r["matched"], True)
        self.assertIs(r["truncated"], True)
        self.assertNotIn("to_state", r["trigger"])
        self.assertNotIn("from_state", r["trigger"])
        self.assertEqual(r["trigger"]["entity_id"], "input_boolean.prueba")
        self.assertLessEqual(len(json.dumps(r)), 600)


if __name__ == "__main__":
    unittest.main()
