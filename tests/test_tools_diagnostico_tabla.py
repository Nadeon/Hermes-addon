"""Rutas de diagnóstico del Supervisor que van por la tabla (spec 013, tramo 2).

FR-018…FR-020 de la 013 (CAP-087 lectura, CAP-088, CAP-089): las rutas `read`
de jobs, sugerencias, discos montables, hardware, seguridad, Docker, hora y
red se ejecutan por `sv_read_api` (la genérica de la 011) con la TABLA REAL y
un Supervisor simulado; lo que tiene tool dedicada se rechaza hacia ella sin
llamar, y la comprobación de integridad, que el Supervisor 2026.11.0 eliminó
(410), no llega al Supervisor por ninguna genérica.

Aquí no hay código de producto de la 013: si algo falla, es la tabla o la
genérica de la 011 (T023).

Controles negativos (T027): (d) dejar `/jobs/info` como `deny` → cae
`test_rutas_read_se_ejecutan`; (e) pasar `/security/integrity` a `confirm` →
cae `test_integridad_no_llega_al_supervisor`; (f) añadir al evento de la
genérica un dato de la respuesta → cae `test_log_de_red_sin_direcciones`.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from structlog.testing import capture_logs

from hermes import security
from hermes.tools import generic_commands as mod
from tests.fixtures.supervisor_diagnostico import CENTINELA_PASSWORD, SupervisorSimulado

_UUID = "0f0e0d0c-0b0a-4908-8706-050403020100"
_IP = "192.0.2.10"
_IP_GW = "192.0.2.1"
_MAC = "02:00:00:00:00:01"
_SSID = "red-ficticia"

# Ruta concreta → respuesta del Supervisor simulado (`data`, con la forma del
# 2026.11.0 y datos ficticios).
_LECTURAS: dict[str, Any] = {
    "/jobs/info": {"ignore_conditions": [], "jobs": [
        {"name": "backup_manager_full_backup", "reference": None, "uuid": _UUID,
         "progress": 50, "stage": "addons", "done": False, "errors": [],
         "child_jobs": []}]},
    f"/resolution/issue/{_UUID}/suggestions": {"suggestions": [
        {"type": "execute_repair", "context": "system", "reference": None,
         "uuid": "1f0e0d0c-0b0a-4908-8706-050403020100", "auto": False}]},
    "/host/disks": {"disks": [
        {"name": "Disco ficticio", "vendor": "Fabricante", "model": "Modelo X",
         "serial": "SERIAL-FICTICIO-0002", "size": 1000, "id": "disco-ficticio-3",
         "dev_path": "/dev/sdy", "partitions": []}]},
    "/hardware/info": {"devices": [
        {"name": "ttyACM0", "sysfs": "/sys/devices/ficticio", "dev_path": "/dev/ttyACM0",
         "by_id": None, "subsystem": "tty", "attributes": {}, "children": []}],
        "drives": []},
    "/hardware/audio": {"audio": {"input": {}, "output": {}}},
    "/security/info": {"content_trust": True, "pwned": True, "force_security": False},
    "/docker/info": {"version": "27.0.0", "enable_ipv6": None, "storage": "overlay2",
                     "logging": "journald", "mtu": None, "registries": {
                         "registro.ficticio": {"username": "u", "password": CENTINELA_PASSWORD}}},
    "/time/info": {"timezone": "Etc/UTC", "use_ntp": True, "dt_utc": "x",
                   "dt_local": "y", "host_time_sync": True},
    "/network/info": {"interfaces": [
        {"interface": "eth0", "type": "ethernet", "enabled": True, "connected": True,
         "primary": True, "mac": _MAC,
         "ipv4": {"method": "static", "address": [f"{_IP}/24"], "gateway": _IP_GW,
                  "nameservers": [_IP_GW]}}],
        "docker": {"interface": "hassio", "address": "172.30.32.0/23"},
        "host_internet": True, "supervisor_internet": True},
    "/network/interface/eth0/info": {"interface": "eth0", "mac": _MAC,
                                     "ipv4": {"address": [f"{_IP}/24"]}},
    "/network/interface/wlan0/accesspoints": {"accesspoints": [
        {"mode": "infrastructure", "ssid": _SSID, "mac": _MAC, "frequency": 2412,
         "signal": 80}]},
}

# Ruta concreta → plantilla de la tabla.
_PLANTILLA = {
    f"/resolution/issue/{_UUID}/suggestions": "/resolution/issue/{issue}/suggestions",
    "/network/interface/eth0/info": "/network/interface/{interface}/info",
    "/network/interface/wlan0/accesspoints": "/network/interface/{interface}/accesspoints",
}


class _Simulado(SupervisorSimulado):
    async def wait_ready(self, timeout: float = 5.0) -> bool:
        return True


class _MCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


class _Base(unittest.IsolatedAsyncioTestCase):
    desactivadas: frozenset[str] = frozenset()

    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self.sv = _Simulado()
        for ruta, datos in _LECTURAS.items():
            self.sv.respuesta("GET", ruta, datos)
        mcp = _MCP()
        # Sin tablas inyectadas: la tabla REAL de command_table.py.
        mod.register(mcp, self.sv, response_max_bytes=131_072,
                     familias_desactivadas=self.desactivadas)
        self.t = mcp.tools

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()


class TestLecturasPorLaTabla(_Base):
    async def test_rutas_read_se_ejecutan(self) -> None:
        for ruta in _LECTURAS:
            with self.subTest(ruta=ruta):
                self.sv.llamadas.clear()
                r = await self.t["sv_read_api"](ruta)
                self.assertNotIn("error", r, r)
                self.assertEqual(r["category"], "read")
                self.assertEqual(r["route"], _PLANTILLA.get(ruta, ruta))
                self.assertEqual(
                    [(c["metodo"], c["ruta"]) for c in self.sv.llamadas], [("GET", ruta)])

    async def test_docker_info_redactada(self) -> None:
        r = await self.t["sv_read_api"]("/docker/info")
        texto = json.dumps(r)
        self.assertNotIn(CENTINELA_PASSWORD, texto)
        self.assertIn("registro.ficticio", texto)

    async def test_numero_de_serie_en_la_respuesta(self) -> None:
        # research R-7: el número de serie no es un secreto y va en la respuesta.
        r = await self.t["sv_read_api"]("/host/disks")
        self.assertIn("SERIAL-FICTICIO-0002", json.dumps(r))

    async def test_log_de_red_sin_direcciones(self) -> None:
        with capture_logs() as logs:
            for ruta in ("/network/info", "/network/interface/eth0/info",
                         "/network/interface/wlan0/accesspoints", "/host/disks"):
                await self.t["sv_read_api"](ruta)
        eventos = [e for e in logs if e.get("event") == "generic_command"]
        self.assertEqual(len(eventos), 4)
        texto = repr(logs)
        for dato in (_IP, _IP_GW, _MAC, _SSID, "eth0", "wlan0", "SERIAL-FICTICIO-0002"):
            self.assertNotIn(dato, texto)


class TestRechazos(_Base):
    async def test_integridad_no_llega_al_supervisor(self) -> None:
        # Desviación de FR-047 de la 008 (research R-6): el Supervisor 2026.11.0
        # eliminó la comprobación y responde 410; sigue `deny`.
        r = await self.t["sv_call_api"]("POST", "/security/integrity")
        self.assertEqual(r["error"], "command_denied")
        self.assertIn("410", r["reason"])
        self.assertNotIn("confirmation_token", r)
        r = await self.t["sv_read_api"]("/security/integrity")
        self.assertIn("error", r)
        self.assertEqual(self.sv.llamadas, [])

    async def test_dedicadas_hacia_su_tool(self) -> None:
        casos = {
            "/core/logs": "sv_get_core_logs",
            "/os/info": "sv_get_os_info",
            "/host/disks/default/usage": "sv_get_disk_usage",
            "/addons/ficticio_addon/logs/latest": "sv_get_addon_logs",
        }
        for ruta, tool in casos.items():
            with self.subTest(ruta=ruta):
                r = await self.t["sv_read_api"](ruta)
                self.assertEqual(r["error"], "use_dedicated_tool")
                self.assertEqual(r["tool"], tool)
                self.assertIs(r["family_disabled"], False)
        self.assertEqual(self.sv.llamadas, [])


class TestConLaFamiliaApagada(_Base):
    desactivadas = frozenset({"system_diagnostics"})

    async def test_family_disabled(self) -> None:
        for ruta, tool in (("/core/logs", "sv_get_core_logs"),
                           ("/os/info", "sv_get_os_info")):
            with self.subTest(ruta=ruta):
                r = await self.t["sv_read_api"](ruta)
                self.assertEqual(r["error"], "use_dedicated_tool")
                self.assertEqual(r["tool"], tool)
                self.assertIs(r["family_disabled"], True)
        # La de add-ons es de la familia `supervisor`, que sigue activa.
        r = await self.t["sv_read_api"]("/addons/ficticio_addon/logs/latest")
        self.assertIs(r["family_disabled"], False)
        self.assertEqual(self.sv.llamadas, [])


if __name__ == "__main__":
    unittest.main()
