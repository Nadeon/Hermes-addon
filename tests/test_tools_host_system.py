"""Tools de disco, host y OS (spec 013, tramo 2; CAP-085).

`sv_list_host_services`, `sv_get_disk_usage`, `sv_get_os_info`, `sv_get_swap`
y `sv_list_datadisk_candidates`, contra un Supervisor simulado con la forma de
las respuestas del 2026.11.0 (`tests/fixtures/supervisor_diagnostico.py`). Se
comprueba lo que Hermes manda (ruta, `params`, tiempo de espera), la
validación previa (un argumento inválido no llega al Supervisor), la poda del
árbol de uso de disco, la redacción, los errores con su pista y el evento de
log, que nunca lleva datos de la respuesta (ni el número de serie de un disco).

Controles negativos (T027), con recuentos en el commit del tramo:
(a) quitar la poda → caen `test_poda_a_20_hijos` y los de la poda;
(b) no validar `max_depth` → cae `test_argumentos_invalidos_sin_llamada`;
(c) no poner la pista en el 404 de `/os/*` → cae `test_404_de_os_con_pista`.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from structlog.testing import capture_logs

from hermes.ha import HAConnectionError
from hermes.tools.host_system import podar_arbol, register
from tests.fixtures.supervisor_diagnostico import (
    CENTINELA_OS,
    CENTINELA_PASSWORD,
    DATADISK_LIST,
    HOST_SERVICES,
    OS_INFO,
    SERIAL_FICTICIO,
    SWAP,
    USO_DE_DISCO_V1,
    SupervisorSimulado,
    uso_de_disco_ancho,
    uso_de_disco_profundo,
)


class _MCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


class _Base(unittest.IsolatedAsyncioTestCase):
    max_bytes = 131_072

    def setUp(self) -> None:
        self.sv = SupervisorSimulado()
        mcp = _MCP()
        register(mcp, self.sv, response_max_bytes=self.max_bytes)
        self.tools = mcp.tools

    def rutas(self) -> list[str]:
        return [c["ruta"] for c in self.sv.llamadas]


def _ids(nodo: dict[str, Any]) -> list[str]:
    return [h["id"] for h in nodo.get("children", [])]


# ── Servicios del host (FR-011) ───────────────────────────────────────────────


class TestServicios(_Base):
    async def test_sobre_comun(self) -> None:
        self.sv.respuesta("GET", "/host/services", HOST_SERVICES)
        r = await self.tools["sv_list_host_services"]()
        self.assertEqual(self.rutas(), ["/host/services"])
        self.assertEqual(r["count"], 4)
        self.assertIs(r["truncated"], False)
        self.assertEqual(len(r["items"]), 4)
        self.assertEqual(set(r["items"][0]), {"name", "description", "state"})
        self.assertNotIn("state", r)

    async def test_state_filtra_exacto(self) -> None:
        self.sv.respuesta("GET", "/host/services", HOST_SERVICES)
        r = await self.tools["sv_list_host_services"](state="failed")
        self.assertEqual([i["name"] for i in r["items"]], ["servicio-ficticio.service"])
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["state"], "failed")

    async def test_lista_que_no_cabe_se_recorta_y_lo_dice(self) -> None:
        muchos = {"services": [
            {"name": f"s{i:04d}.service", "description": "x" * 200, "state": "active"}
            for i in range(2000)]}
        self.sv.respuesta("GET", "/host/services", muchos)
        r = await self.tools["sv_list_host_services"]()
        self.assertIs(r["truncated"], True)
        self.assertEqual(r["count"], 2000)
        self.assertLess(r["returned"], 2000)
        self.assertLessEqual(len(json.dumps(r, ensure_ascii=False).encode()), self.max_bytes)


# ── Uso de disco (FR-012) ─────────────────────────────────────────────────────


class TestUsoDeDisco(_Base):
    async def test_por_defecto(self) -> None:
        self.sv.respuesta("GET", "/host/disks/default/usage", USO_DE_DISCO_V1)
        r = await self.tools["sv_get_disk_usage"]()
        self.assertEqual(self.rutas(), ["/host/disks/default/usage"])
        llamada = self.sv.llamadas[0]
        self.assertEqual(llamada["params"], {"max_depth": "1"})
        # El Supervisor espera hasta 60 s por un montaje lento (research R-4).
        self.assertGreaterEqual(llamada["timeout"], 75)
        self.assertEqual(r["disk"], "default")
        self.assertEqual(r["max_depth"], 1)
        self.assertEqual(r["id"], "root")
        self.assertEqual(r["total_bytes"], 32_000_000_000)
        self.assertNotIn("children_omitted", r)
        # Ordenados por lo que ocupan; los ids antiguos de la v1 tal cual.
        self.assertEqual(_ids(r), ["homeassistant", "addons_data", "system",
                                   "backup", "addons_config"])

    async def test_montaje_y_profundidad(self) -> None:
        self.sv.respuesta("GET", "/host/disks/nas_backups/usage", USO_DE_DISCO_V1)
        r = await self.tools["sv_get_disk_usage"](disk="nas_backups", max_depth=3)
        self.assertEqual(self.rutas(), ["/host/disks/nas_backups/usage"])
        self.assertEqual(self.sv.llamadas[0]["params"], {"max_depth": "3"})
        self.assertEqual(r["disk"], "nas_backups")
        self.assertEqual(r["max_depth"], 3)

    async def test_argumentos_invalidos_sin_llamada(self) -> None:
        casos: tuple[tuple[dict[str, Any], str], ...] = (
            ({"disk": "a-b"}, "disk"), ({"disk": "a/b"}, "disk"),
            ({"disk": ""}, "disk"), ({"disk": "a" * 65}, "disk"),
            ({"disk": ".."}, "disk"), ({"disk": 7}, "disk"),
            ({"max_depth": -1}, "max_depth"), ({"max_depth": 4}, "max_depth"),
            ({"max_depth": True}, "max_depth"), ({"max_depth": "1"}, "max_depth"),
        )
        for kwargs, campo in casos:
            with self.subTest(kwargs=kwargs):
                r = await self.tools["sv_get_disk_usage"](**kwargs)
                self.assertEqual(r["error"], "invalid_argument")
                self.assertEqual(r["field"], campo)
                # El detalle dice la regla, nunca copia el valor.
                valor = str(kwargs[campo])
                if len(valor) > 2:
                    self.assertNotIn(valor, r["detail"])
        self.assertEqual(self.sv.llamadas, [])

    async def test_limites_validos(self) -> None:
        for disk, depth in (("default", 0), ("a" * 64, 3), ("Nas_1", 2)):
            with self.subTest(disk=disk, depth=depth):
                self.sv.llamadas.clear()
                self.sv.respuesta("GET", f"/host/disks/{disk}/usage", USO_DE_DISCO_V1)
                r = await self.tools["sv_get_disk_usage"](disk=disk, max_depth=depth)
                self.assertNotIn("error", r)
                self.assertEqual(len(self.sv.llamadas), 1)

    async def test_poda_a_20_hijos(self) -> None:
        arbol = uso_de_disco_ancho(30)
        self.sv.respuesta("GET", "/host/disks/default/usage", arbol)
        r = await self.tools["sv_get_disk_usage"]()
        self.assertEqual(len(r["children"]), 20)
        usados = [h["used_bytes"] for h in r["children"]]
        self.assertEqual(usados, sorted(usados, reverse=True))
        self.assertEqual(r["children"][0]["id"], "c29")
        # Los diez más pequeños se quitan y se resumen; la suma cuadra.
        self.assertEqual(r["children_omitted"], 10)
        quitados = sorted(arbol["children"], key=lambda h: (-h["used_bytes"], h["id"]))[20:]
        self.assertEqual(r["omitted_bytes"], sum(h["used_bytes"] for h in quitados))
        self.assertEqual(
            sum(usados) + r["omitted_bytes"],
            sum(h["used_bytes"] for h in arbol["children"]))

    def test_empate_por_id(self) -> None:
        # `c00` y `c01` ocupan lo mismo: con 30 hijos los dos quedan fuera;
        # con un tope de 29, entra `c00` por el orden de su `id`.
        arbol = uso_de_disco_ancho(30)
        podado = podar_arbol(arbol, max_hijos=29)
        self.assertIn("c00", _ids(podado))
        self.assertNotIn("c01", _ids(podado))
        self.assertEqual(podado["children_omitted"], 1)

    def test_poda_recursiva(self) -> None:
        arbol = uso_de_disco_profundo(25)
        podado = podar_arbol(arbol)
        niveles = [podado]
        for profundidad in range(3):
            siguientes = []
            for n in niveles:
                self.assertEqual(len(n["children"]), 20, (profundidad, n["id"]))
                self.assertEqual(n["children_omitted"], 5)
                self.assertGreater(n["omitted_bytes"], 0)
                siguientes.extend(n["children"])
            niveles = siguientes
        # Las hojas no ganan claves de poda.
        self.assertNotIn("children", niveles[0])
        self.assertNotIn("children_omitted", niveles[0])

    def test_poda_no_toca_el_original(self) -> None:
        arbol = uso_de_disco_ancho(30)
        podar_arbol(arbol)
        self.assertEqual(len(arbol["children"]), 30)

    def test_poda_con_pocos_hijos_no_anade_claves(self) -> None:
        podado = podar_arbol(USO_DE_DISCO_V1)
        self.assertEqual(len(podado["children"]), 5)
        self.assertNotIn("children_omitted", podado)
        self.assertNotIn("omitted_bytes", podado)


# ── OS (FR-013…FR-015) ────────────────────────────────────────────────────────


class TestOS(_Base):
    async def test_os_info(self) -> None:
        self.sv.respuesta("GET", "/os/info", OS_INFO)
        r = await self.tools["sv_get_os_info"]()
        self.assertEqual(self.rutas(), ["/os/info"])
        self.assertEqual(r, OS_INFO)

    async def test_os_info_redacta_estructura(self) -> None:
        # Defensa en profundidad (FR-016): hoy no lleva secretos, pero si un
        # día viaja uno bajo una clave sensible, sale tapado.
        datos = dict(OS_INFO, password=CENTINELA_OS)
        self.sv.respuesta("GET", "/os/info", datos)
        r = await self.tools["sv_get_os_info"]()
        self.assertNotIn(CENTINELA_OS, json.dumps(r))
        self.assertIn("password", r)

    async def test_swap(self) -> None:
        self.sv.respuesta("GET", "/os/config/swap", SWAP)
        r = await self.tools["sv_get_swap"]()
        self.assertEqual(self.rutas(), ["/os/config/swap"])
        self.assertEqual(r, SWAP)

    async def test_datadisk(self) -> None:
        self.sv.respuesta("GET", "/os/datadisk/list", DATADISK_LIST)
        r = await self.tools["sv_list_datadisk_candidates"]()
        self.assertEqual(self.rutas(), ["/os/datadisk/list"])
        self.assertEqual(r["count"], 1)
        self.assertIs(r["truncated"], False)
        self.assertEqual(r["devices"], ["disco-ficticio-2"])
        # El número de serie va en la respuesta (research R-7).
        self.assertEqual(r["items"][0]["serial"], SERIAL_FICTICIO)


# ── Errores (FR-016, T017) ────────────────────────────────────────────────────


class TestErrores(_Base):
    async def test_404_de_os_con_pista(self) -> None:
        # Sin respuesta configurada, el simulado da el 404 del Supervisor.
        for tool, ruta in (("sv_get_os_info", "/os/info"),
                           ("sv_get_swap", "/os/config/swap"),
                           ("sv_list_datadisk_candidates", "/os/datadisk/list")):
            with self.subTest(tool=tool):
                r = await self.tools[tool]()
                self.assertIn(ruta, r["error"])
                self.assertIn("404", r["error"])
                self.assertIn("Home Assistant OS", r["hint"])

    async def test_error_de_montaje_redactado_sin_pista(self) -> None:
        self.sv.respuesta("GET", "/host/disks/nas/usage", HAConnectionError(
            f"Supervisor GET /host/disks/nas/usage failed 400: password: {CENTINELA_PASSWORD}",
            status=400))
        r = await self.tools["sv_get_disk_usage"](disk="nas")
        self.assertIn("400", r["error"])
        self.assertNotIn(CENTINELA_PASSWORD, r["error"])
        self.assertNotIn("hint", r)

    async def test_otro_error_de_os_sin_pista(self) -> None:
        self.sv.respuesta("GET", "/os/info", HAConnectionError(
            "Supervisor GET /os/info failed 500: boom", status=500))
        r = await self.tools["sv_get_os_info"]()
        self.assertIn("500", r["error"])
        self.assertNotIn("hint", r)

    async def test_sin_conexion(self) -> None:
        for tool, ruta in (("sv_list_host_services", "/host/services"),
                           ("sv_get_disk_usage", "/host/disks/default/usage"),
                           ("sv_get_os_info", "/os/info")):
            with self.subTest(tool=tool):
                self.sv.respuesta("GET", ruta, HAConnectionError("sin conexión"))
                r = await self.tools[tool]()
                self.assertEqual(set(r), {"error"})
                self.assertIn("sin conexión", r["error"])

    async def test_respuesta_vacia_no_es_buena(self) -> None:
        # Un `data` vacío o de otra forma no se presenta como un resultado
        # (FR-016: nunca inventar ni dar por buena una respuesta vacía).
        for tool, ruta, valor in (
            ("sv_get_os_info", "/os/info", []),
            ("sv_get_swap", "/os/config/swap", "texto"),
            ("sv_get_disk_usage", "/host/disks/default/usage", {}),
            ("sv_list_host_services", "/host/services", {"otra": 1}),
            ("sv_list_datadisk_candidates", "/os/datadisk/list", {"devices": []}),
        ):
            with self.subTest(tool=tool):
                self.sv.respuesta("GET", ruta, valor)
                r = await self.tools[tool]()
                self.assertIn("error", r)


# ── Evento de log (FR-010, T017) ──────────────────────────────────────────────


class TestEventoDeLog(_Base):
    def _eventos(self, logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [e for e in logs if e["event"] == "system_diagnostics_read"]

    async def test_sin_datos_de_la_respuesta(self) -> None:
        self.sv.respuesta("GET", "/os/datadisk/list", DATADISK_LIST)
        self.sv.respuesta("GET", "/host/disks/nas_backups/usage", USO_DE_DISCO_V1)
        self.sv.respuesta("GET", "/host/services", HOST_SERVICES)
        self.sv.respuesta("GET", "/os/info", OS_INFO)
        with capture_logs() as logs:
            await self.tools["sv_list_datadisk_candidates"]()
            await self.tools["sv_get_disk_usage"](disk="nas_backups")
            await self.tools["sv_list_host_services"]()
            await self.tools["sv_get_os_info"]()
        eventos = self._eventos(logs)
        self.assertEqual(len(eventos), 4)
        texto = repr(logs)
        for dato in (SERIAL_FICTICIO, "disco-ficticio", "Modelo X", "/dev/sdz",
                     "servicio-ficticio", "nas_backups", "generic-x86-64",
                     "homeassistant"):
            self.assertNotIn(dato, texto)
        datadisk, uso, servicios, os_info = eventos
        self.assertEqual(datadisk["tool"], "sv_list_datadisk_candidates")
        self.assertEqual(datadisk["route"], "/os/datadisk/list")
        self.assertEqual(datadisk["count"], 1)
        self.assertEqual(datadisk["outcome"], "ok")
        # La plantilla de la tabla, no el nombre del montaje.
        self.assertEqual(uso["route"], "/host/disks/{disk}/usage")
        self.assertIsInstance(uso["bytes"], int)
        self.assertEqual(servicios["count"], 4)
        self.assertIsInstance(os_info["bytes"], int)

    async def test_invalido_y_error(self) -> None:
        with capture_logs() as logs:
            await self.tools["sv_get_disk_usage"](disk="a/b")
            await self.tools["sv_get_swap"]()
        invalido, error = self._eventos(logs)
        self.assertEqual(invalido["outcome"], "invalid_argument")
        self.assertEqual(invalido["field"], "disk")
        self.assertNotIn("a/b", repr(invalido))
        self.assertEqual(error["outcome"], "error")
        self.assertEqual(error["status"], 404)
        self.assertEqual(error["route"], "/os/config/swap")


if __name__ == "__main__":
    unittest.main()
