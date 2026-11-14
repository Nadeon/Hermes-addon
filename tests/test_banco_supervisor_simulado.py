"""Contrato del Supervisor simulado del banco de Core (spec 010, FR-004).

Se prueba contra el doble de Core, sin Docker. Cada test corresponde a una
línea de la sección «Tests de contrato» de
`specs/010-banco-de-pruebas-core/contracts/supervisor-simulado.md`.

Control negativo (T010), comprobado en local y restaurado:
  1. sin comprobar el token de add-on caen los de 401 y `auth_invalid`;
  2. sin el filtro de `supervisor/` y `hassio/` caen los de `unauthorized`;
  3. aceptando `PUT` cae el de 405;
  4. reenviando a Core el token del cliente cae el de «llega con el token de
     Core».
"""

from __future__ import annotations

import asyncio
import secrets
import unittest

import aiohttp
from yarl import URL

from tests.banco.core_doble import CoreDoble
from tests.banco.supervisor_simulado import arrancar


class _ConSimulado(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.token_core = "core-" + secrets.token_urlsafe(8)
        self.token_addon = "addon-" + secrets.token_urlsafe(8)
        self.core = CoreDoble(token_core=self.token_core)
        await self.core.__aenter__()
        self.runner, self.url = await arrancar(
            self.core.url, self.token_addon, self.token_core, "2026.11.1"
        )
        self.session = aiohttp.ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()
        await self.runner.cleanup()
        await self.core.__aexit__(None, None, None)

    def _auth(self, token: str | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token or self.token_addon}"}

    async def _get(self, ruta: str, **kw: object) -> tuple[int, object]:
        async with self.session.get(self.url + ruta, **kw) as resp:  # type: ignore[arg-type]
            try:
                return resp.status, await resp.json(content_type=None)
            except ValueError:
                return resp.status, await resp.text()


class TestRutasDelSupervisor(_ConSimulado):
    async def test_ping_sin_token(self) -> None:
        estado, cuerpo = await self._get("/supervisor/ping")
        self.assertEqual((estado, cuerpo), (200, {"result": "ok", "data": {}}))

    async def test_core_info_con_token(self) -> None:
        estado, cuerpo = await self._get("/core/info", headers=self._auth())
        self.assertEqual(estado, 200)
        self.assertEqual(cuerpo["result"], "ok")  # type: ignore[index]
        self.assertEqual(cuerpo["data"]["version"], "2026.11.1")  # type: ignore[index]

    async def test_core_info_sin_token_o_con_otro(self) -> None:
        estado, cuerpo = await self._get("/core/info")
        self.assertEqual((estado, cuerpo), (401, {"result": "error", "message": "Unauthorized"}))
        estado, _ = await self._get("/core/info", headers=self._auth("otro"))
        self.assertEqual(estado, 401)

    async def test_ruta_desconocida_404_con_formato_del_supervisor(self) -> None:
        estado, cuerpo = await self._get("/addons/self/info", headers=self._auth())
        self.assertEqual(estado, 404)
        self.assertEqual(cuerpo["result"], "error")  # type: ignore[index]
        self.assertIn("/addons/self/info", cuerpo["message"])  # type: ignore[index]


class TestProxyRest(_ConSimulado):
    async def test_get_post_delete_llegan_con_el_token_de_core(self) -> None:
        for metodo in ("GET", "POST", "DELETE"):
            async with self.session.request(
                metodo,
                f"{self.url}/core/api/eco/algo?a=1&b=%2F",
                headers={**self._auth(), "Content-Type": "application/json"},
                data=b'{"x": 1}' if metodo == "POST" else None,
            ) as resp:
                self.assertEqual(resp.status, 200, metodo)
                eco = await resp.json()
            self.assertEqual(eco["metodo"], metodo)
            self.assertEqual(eco["ruta"], "algo")
            self.assertEqual(eco["query"], "a=1&b=/")
            self.assertEqual(eco["token"], self.token_core)
            if metodo == "POST":
                self.assertEqual(eco["cuerpo"], '{"x": 1}')
                self.assertEqual(eco["content_type"], "application/json")
        tokens = {r["token"] for r in self.core.registro.rest}
        self.assertEqual(tokens, {self.token_core})
        self.assertNotIn(self.token_addon, tokens)

    async def test_raiz_de_la_api(self) -> None:
        estado, cuerpo = await self._get("/core/api/", headers=self._auth())
        self.assertEqual((estado, cuerpo), (200, {"message": "API running."}))

    async def test_sin_token_401_y_nada_llega_a_core(self) -> None:
        estado, cuerpo = await self._get("/core/api/eco/algo", headers=self._auth("otro"))
        self.assertEqual((estado, cuerpo), (401, {"result": "error", "message": "Unauthorized"}))
        self.assertEqual(self.core.registro.rest, [])

    async def test_put_y_patch_405(self) -> None:
        for metodo in ("PUT", "PATCH"):
            async with self.session.request(
                metodo, f"{self.url}/core/api/eco/algo", headers=self._auth()
            ) as resp:
                self.assertEqual(resp.status, 405, metodo)
        self.assertEqual(self.core.registro.rest, [])

    async def test_hassio_403_sin_llegar_a_core(self) -> None:
        for ruta in ("hassio/addons", "hassio_auth", "hassio%5Fauth", "hassio%255Fauth"):
            estado, _ = await self._get(f"/core/api/{ruta}", headers=self._auth())
            self.assertEqual(estado, 403, ruta)
        self.assertEqual(self.core.registro.rest, [])

    async def test_core_inalcanzable_502(self) -> None:
        await self.core.__aexit__(None, None, None)
        estado, _ = await self._get("/core/api/eco/algo", headers=self._auth())
        self.assertEqual(estado, 502)


class TestFiltrosComoElReal(_ConSimulado):
    """T039: `block_bad_requests` del real (FILTERS sobre la ruta y la query
    decodificadas). El simulado no puede ser más permisivo que él.

    Control negativo (T039), comprobado en local y restaurado: sin el
    middleware `bloquear_peticiones_peligrosas` caen los dos tests de 400 (las
    peticiones llegan a Core con 200).
    """

    PELIGROSAS = (
        "/core/api/eco/algo?q=concat(1)",
        "/core/api/eco/algo?q=union%20select%20(1)",
        "/core/api/eco/algo?q=union%20all%20select%201",
        "/core/api/eco/%3Cscript%3Ealert(1)%3C/script%3E",
        "/core/api/eco/algo?q=%253Cscript%253E",
        "/core/api/eco/algo?v=/.//b",
        "/core/api/eco/algo?f=..%2F..%2Fsecretos",
        "/core/api/eco/proc/self/environ",
    )

    async def _estado(self, ruta: str, **kw: object) -> int:
        url = URL(self.url + ruta, encoded=True)
        async with self.session.get(url, **kw) as resp:  # type: ignore[arg-type]
            return resp.status

    async def test_peticiones_peligrosas_400_sin_llegar_a_core(self) -> None:
        for ruta in self.PELIGROSAS:
            self.assertEqual(await self._estado(ruta, headers=self._auth()), 400, ruta)
        self.assertEqual(self.core.registro.rest, [])

    async def test_el_filtro_va_antes_que_el_token(self) -> None:
        # Como en el real: es el primer middleware, así que sin token también 400.
        self.assertEqual(await self._estado(self.PELIGROSAS[0]), 400)

    async def test_consultas_normales_pasan(self) -> None:
        for ruta in (
            "/core/api/eco/history/period/2026-11-14T00:00:00%2B00:00"
            "?filter_entity_id=light.salon,sensor.temperatura&minimal_response",
            "/core/api/eco/logbook?entity=light.salon&end_time=2026-11-14T01:00:00",
            "/core/api/eco/template?nombre=union_de_datos",
        ):
            self.assertEqual(await self._estado(ruta, headers=self._auth()), 200, ruta)
        self.assertEqual(len(self.core.registro.rest), 3)


class TestProxyWebSocket(_ConSimulado):
    async def _conectar(self, token: str | None = None, ruta: str = "/core/api/websocket"):
        ws = await self.session.ws_connect(self.url.replace("http://", "ws://") + ruta)
        inicio = await ws.receive_json(timeout=5)
        await ws.send_json({"type": "auth", "access_token": token or self.token_addon})
        auth = await ws.receive_json(timeout=5)
        return ws, inicio, auth

    async def test_auth_ok_con_version(self) -> None:
        for ruta in ("/core/api/websocket", "/core/websocket"):
            ws, inicio, auth = await self._conectar(ruta=ruta)
            self.assertEqual(inicio, {"type": "auth_required", "ha_version": "2026.11.1"})
            self.assertEqual(auth, {"type": "auth_ok", "ha_version": "2026.11.1"})
            await ws.close()

    async def test_auth_invalid_y_cierre(self) -> None:
        ws, _, auth = await self._conectar("otro")
        self.assertEqual(auth, {"type": "auth_invalid", "message": "Invalid access"})
        msg = await ws.receive(timeout=5)
        self.assertIn(msg.type, (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING))
        await ws.close()
        # Nunca se abrió la conexión con Core.
        self.assertEqual(self.core.registro.ws_tokens, [])

    async def test_comando_normal_ida_y_vuelta_con_el_token_de_core(self) -> None:
        ws, _, _ = await self._conectar()
        await ws.send_json({"id": 7, "type": "get_states"})
        resultado = await ws.receive_json(timeout=5)
        await ws.close()
        self.assertEqual(resultado["id"], 7)
        self.assertTrue(resultado["success"])
        self.assertEqual(resultado["result"]["eco"], "get_states")
        self.assertEqual(self.core.registro.ws_tokens, [self.token_core])

    async def test_comandos_reservados_unauthorized_y_no_llegan(self) -> None:
        ws, _, _ = await self._conectar()
        await ws.send_json({"id": 1, "type": "supervisor/info"})
        r1 = await ws.receive_json(timeout=5)
        await ws.send_json({"id": 2, "type": "hassio/x"})
        r2 = await ws.receive_json(timeout=5)
        # Dentro de una lista: no se reenvía nada de ella, tampoco lo permitido.
        await ws.send_json([{"id": 3, "type": "get_states"}, {"id": 4, "type": "supervisor/api"}])
        r3 = await ws.receive_json(timeout=5)
        # Mal formado (sin `type` de texto).
        await ws.send_json({"id": 5, "type": 1})
        r4 = await ws.receive_json(timeout=5)
        # Uno permitido después, para saber que lo anterior ya se procesó.
        await ws.send_json({"id": 6, "type": "ping"})
        r5 = await ws.receive_json(timeout=5)
        await ws.close()
        error = {"code": "unauthorized", "message": "Unauthorized"}
        self.assertEqual(r1, {"id": 1, "type": "result", "success": False, "error": error})
        self.assertEqual(r2, {"id": 2, "type": "result", "success": False, "error": error})
        # El real responde a una lista con un único resultado sin id.
        self.assertEqual(r3, {"id": None, "type": "result", "success": False, "error": error})
        self.assertEqual(r4["error"], error)
        self.assertEqual(r5["id"], 6)
        tipos = [c.get("type") for c in self.core.registro.ws_comandos]
        self.assertEqual(tipos, ["ping"])

    async def test_cierre_del_cliente_cierra_el_lado_de_core(self) -> None:
        ws, _, _ = await self._conectar()
        await ws.send_json({"id": 1, "type": "ping"})
        await ws.receive_json(timeout=5)
        await ws.close()
        for _ in range(200):
            if self.core.registro.ws_cerradas >= 1:
                break
            await asyncio.sleep(0.025)
        self.assertEqual(self.core.registro.ws_cerradas, 1)

    async def test_sin_auth_a_tiempo_se_cierra(self) -> None:
        from tests.banco import supervisor_simulado

        original = supervisor_simulado.TIMEOUT_AUTH_WS
        supervisor_simulado.TIMEOUT_AUTH_WS = 0.2  # type: ignore[assignment]
        try:
            ws = await self.session.ws_connect(self.url.replace("http://", "ws://") + "/core/api/websocket")
            await ws.receive_json(timeout=5)
            msg = await ws.receive(timeout=5)
            self.assertIn(msg.type, (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING))
            await ws.close()
        finally:
            supervisor_simulado.TIMEOUT_AUTH_WS = original
        self.assertEqual(self.core.registro.ws_tokens, [])


if __name__ == "__main__":
    unittest.main()
