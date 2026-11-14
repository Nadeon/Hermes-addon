"""Tools de logs del sistema (spec 013, tramo 1; CAP-081).

`sv_get_core_logs`, `sv_get_supervisor_logs`, `sv_get_plugin_logs`,
`sv_get_host_logs`, `sv_list_host_log_identifiers` y `sv_list_boots`, contra un
Supervisor simulado con la forma de respuestas del 2026.11.0
(`tests/fixtures/supervisor_diagnostico.py`). Lo que se comprueba es lo que
Hermes manda (ruta y `params`), la validación previa (fail-closed: un
argumento inválido no llega al Supervisor), la redacción y el recorte de lo
que devuelve, y el evento de log.

Controles negativos (T013), con recuentos en el commit del tramo:
(a) aceptar cualquier texto en `boot` → caen los de `boot` inválido;
(b) no rechazar `boot`+`latest` → cae `test_boot_y_latest_a_la_vez`;
(c) no aplicar `redact_network` al identificador de Hermes en el host → cae
`test_identifier_de_hermes_tapa_la_red`;
(d) recortar por el principio en vez de por el final → cae
`test_log_grande_devuelve_las_ultimas_lineas`;
(e) registrar `boot` o el contenido en el evento → caen los de `TestEventoDeLog`.
"""

from __future__ import annotations

import unittest
from typing import Any

from structlog.testing import capture_logs

from hermes.ha import HAConnectionError
from hermes.tools.system_logs import register
from tests.fixtures.supervisor_diagnostico import (
    BOOT_ACTUAL,
    BOOT_ANTERIOR,
    BOOT_ANTIGUO,
    BOOTS,
    CENTINELA_JWT,
    CENTINELA_PASSWORD,
    CENTINELA_TOKEN,
    IDENTIFIERS,
    SupervisorSimulado,
    log_con_centinelas,
    log_numerado,
)

_HEX_MAYUS = "0123456789ABCDEF0123456789ABCDEF"
_BOOTS_INVALIDOS: tuple[Any, ...] = (
    "abc", 1.5, 1000, -1000, "1" * 31, "a" * 33, "../x", True, "", " -1",
)
_HERMES = "a1b2c3d4_hermes"


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


# ── Core, Supervisor y plugins (T003) ─────────────────────────────────────────


class TestRutasCoreSupervisorPlugin(_Base):
    """Ruta según data-model para cada combinación de `boot` y `latest`."""

    _CASOS = (
        ({}, "", None),
        ({"latest": True}, "/latest", None),
        ({"boot": -1}, "/boots/-1", -1),
        ({"boot": "-1"}, "/boots/-1", -1),
        ({"boot": 0}, "/boots/0", 0),
        ({"boot": _HEX_MAYUS}, "/boots/" + _HEX_MAYUS.lower(), _HEX_MAYUS.lower()),
    )

    async def _comprobar(self, tool: str, base: str, source: str, **extra: Any) -> None:
        for kwargs, sufijo, boot in self._CASOS:
            with self.subTest(tool=tool, kwargs=kwargs):
                self.sv.llamadas.clear()
                ruta = f"{base}/logs{sufijo}"
                self.sv.texto(ruta, "una línea\n")
                r = await self.tools[tool](**extra, **kwargs)
                self.assertEqual(self.rutas(), [ruta])
                self.assertTrue(self.sv.llamadas[0]["texto"])
                self.assertEqual(self.sv.llamadas[0]["params"], {"lines": "100"})
                self.assertEqual(r["source"], source)
                self.assertEqual(r["logs"], "una línea\n")
                self.assertEqual(r["lines_requested"], 100)
                # La plantilla, nunca el id concreto.
                self.assertNotIn(_HEX_MAYUS.lower(), r["route"])
                if boot is None:
                    self.assertNotIn("boot", r)
                else:
                    self.assertEqual(r["boot"], boot)
                    self.assertTrue(r["route"].endswith("/logs/boots/{bootid}"))
                if kwargs.get("latest"):
                    self.assertIs(r["latest"], True)
                    self.assertTrue(r["route"].endswith("/logs/latest"))
                else:
                    self.assertNotIn("latest", r)

    async def test_core(self) -> None:
        await self._comprobar("sv_get_core_logs", "/core", "core")

    async def test_supervisor(self) -> None:
        await self._comprobar("sv_get_supervisor_logs", "/supervisor", "supervisor")

    async def test_plugins(self) -> None:
        for plugin in ("dns", "audio", "multicast"):
            await self._comprobar("sv_get_plugin_logs", f"/{plugin}", plugin, plugin=plugin)

    async def test_route_es_la_plantilla(self) -> None:
        self.sv.texto(f"/core/logs/boots/{BOOT_ANTERIOR}", "x\n")
        r = await self.tools["sv_get_core_logs"](boot=BOOT_ANTERIOR)
        self.assertEqual(r["route"], "/core/logs/boots/{bootid}")
        self.sv.texto("/dns/logs/latest", "x\n")
        r = await self.tools["sv_get_plugin_logs"]("dns", latest=True)
        self.assertEqual(r["route"], "/dns/logs/latest")


class TestLineas(_Base):
    async def test_lines_acotado(self) -> None:
        self.sv.texto("/core/logs", "x\n")
        for pedido, enviado in ((0, "1"), (-5, "1"), (5000, "1000"), (250, "250")):
            with self.subTest(lines=pedido):
                self.sv.llamadas.clear()
                r = await self.tools["sv_get_core_logs"](lines=pedido)
                self.assertEqual(self.sv.llamadas[0]["params"], {"lines": enviado})
                self.assertEqual(r["lines_requested"], int(enviado))


class TestValidacion(_Base):
    """Fail-closed: nada inválido llega al Supervisor y el `detail` dice la
    regla sin copiar el valor."""

    async def test_boot_invalido(self) -> None:
        llamadas = (
            ("sv_get_core_logs", {}),
            ("sv_get_supervisor_logs", {}),
            ("sv_get_plugin_logs", {"plugin": "dns"}),
            ("sv_get_host_logs", {}),
        )
        for tool, extra in llamadas:
            for boot in _BOOTS_INVALIDOS:
                with self.subTest(tool=tool, boot=boot):
                    r = await self.tools[tool](**extra, boot=boot)
                    self.assertEqual(r["error"], "invalid_argument")
                    self.assertEqual(r["field"], "boot")
                    if isinstance(boot, str) and boot.strip():
                        self.assertNotIn(boot.strip(), r["detail"])
        self.assertEqual(self.sv.llamadas, [])

    async def test_boot_y_latest_a_la_vez(self) -> None:
        for tool, extra in (("sv_get_core_logs", {}), ("sv_get_supervisor_logs", {}),
                            ("sv_get_plugin_logs", {"plugin": "audio"})):
            with self.subTest(tool=tool):
                r = await self.tools[tool](**extra, boot=-1, latest=True)
                self.assertEqual(r["error"], "invalid_argument")
                self.assertEqual(r["field"], "latest")
        self.assertEqual(self.sv.llamadas, [])

    async def test_plugin_invalido(self) -> None:
        for plugin in ("cli", "observer", "DNS", "", "../core"):
            with self.subTest(plugin=plugin):
                r = await self.tools["sv_get_plugin_logs"](plugin)
                self.assertEqual(r["error"], "invalid_argument")
                self.assertEqual(r["field"], "plugin")
                for valido in ("dns", "audio", "multicast"):
                    self.assertIn(valido, r["detail"])
        self.assertEqual(self.sv.llamadas, [])


class TestRedaccion(_Base):
    async def test_centinelas_no_salen(self) -> None:
        for tool, ruta, extra in (
            ("sv_get_core_logs", "/core/logs", {}),
            ("sv_get_supervisor_logs", "/supervisor/logs", {}),
            ("sv_get_plugin_logs", "/multicast/logs", {"plugin": "multicast"}),
            ("sv_get_host_logs", "/host/logs", {}),
        ):
            with self.subTest(tool=tool):
                self.sv.texto(ruta, log_con_centinelas())
                r = await self.tools[tool](**extra)
                for centinela in (CENTINELA_PASSWORD, CENTINELA_TOKEN, CENTINELA_JWT):
                    self.assertNotIn(centinela, r["logs"])
                self.assertIs(r["redacted"], True)
                self.assertIs(r["secrets_redacted"], True)
                self.assertIs(r["network_redacted"], False)
                self.assertIn("listo", r["logs"])

    async def test_sin_secretos_redacted_false(self) -> None:
        self.sv.texto("/core/logs", "todo bien\n")
        r = await self.tools["sv_get_core_logs"]()
        self.assertIs(r["redacted"], False)

    async def test_error_del_supervisor_redactado(self) -> None:
        self.sv.texto("/core/logs", HAConnectionError(
            f"Supervisor GET /core/logs failed 500: password: {CENTINELA_PASSWORD}",
            status=500))
        r = await self.tools["sv_get_core_logs"]()
        self.assertIn("error", r)
        self.assertNotIn(CENTINELA_PASSWORD, r["error"])
        self.assertNotIn("logs", r)

    async def test_error_de_conexion(self) -> None:
        self.sv.texto("/host/logs/boots", HAConnectionError("sin conexión"))
        self.sv.texto("/supervisor/logs", HAConnectionError("sin conexión"))
        r = await self.tools["sv_get_supervisor_logs"]()
        self.assertEqual(r, {"error": "sin conexión"})


# ── Host, identificadores y arranques (T004) ──────────────────────────────────


class TestHost(_Base):
    async def test_cuatro_rutas(self) -> None:
        casos = (
            ({}, "/host/logs", "/host/logs"),
            ({"boot": -1}, "/host/logs/boots/-1", "/host/logs/boots/{bootid}"),
            ({"identifier": "kernel"}, "/host/logs/identifiers/kernel",
             "/host/logs/identifiers/{identifier}"),
            ({"boot": -2, "identifier": "kernel"},
             "/host/logs/boots/-2/identifiers/kernel",
             "/host/logs/boots/{bootid}/identifiers/{identifier}"),
        )
        for kwargs, ruta, plantilla in casos:
            with self.subTest(kwargs=kwargs):
                self.sv.llamadas.clear()
                self.sv.texto(ruta, "kernel: usb 1-1: new device\n")
                r = await self.tools["sv_get_host_logs"](**kwargs)
                self.assertEqual(self.rutas(), [ruta])
                self.assertEqual(self.sv.llamadas[0]["params"], {"lines": "100"})
                self.assertEqual(r["source"], "host")
                self.assertEqual(r["route"], plantilla)
                if "identifier" in kwargs:
                    self.assertEqual(r["identifier"], kwargs["identifier"])
                else:
                    self.assertNotIn("identifier", r)

    async def test_identifier_invalido(self) -> None:
        # `a..b` cumple la forma de `identifier` y lo para la segunda capa,
        # `validate_path_segment` (`..` nunca va dentro de una ruta).
        for identifier in ("..", ".hidden", "a/b", "a b", "a%2e", "x" * 65, "", "a?b",
                           "a#b", "a..b"):
            with self.subTest(identifier=identifier):
                r = await self.tools["sv_get_host_logs"](identifier=identifier)
                self.assertEqual(r["error"], "invalid_argument")
                self.assertEqual(r["field"], "identifier")
        self.assertEqual(self.sv.llamadas, [])

    async def test_identifier_valido(self) -> None:
        for identifier in ("kernel", "systemd-journald", "NetworkManager",
                           "addon_core_ficticio", "hassio_supervisor", "x" * 64):
            with self.subTest(identifier=identifier):
                self.sv.llamadas.clear()
                ruta = f"/host/logs/identifiers/{identifier}"
                self.sv.texto(ruta, "x\n")
                r = await self.tools["sv_get_host_logs"](identifier=identifier)
                self.assertNotIn("error", r)
                self.assertEqual(self.rutas(), [ruta])


class TestHostLogDeHermes(_Base):
    """El log de Hermes por el journal del host lleva la redacción de red,
    como `sv_get_addon_logs` desde la 1.1.2 (data-model, «Redacción»)."""

    def setUp(self) -> None:
        from hermes.logging_setup import configure_network_redaction
        configure_network_redaction(True, "homeassistant.tailXXXX.ts.net")
        super().setUp()

    def tearDown(self) -> None:
        from hermes.logging_setup import configure_network_redaction
        configure_network_redaction(False, "")

    async def test_identifier_de_hermes_tapa_la_red(self) -> None:
        for identifier in (f"addon_{_HERMES}", f"app_{_HERMES}"):
            with self.subTest(identifier=identifier):
                self.sv.texto(f"/host/logs/identifiers/{identifier}",
                              "conexión desde 192.0.2.10\n")
                r = await self.tools["sv_get_host_logs"](identifier=identifier)
                self.assertNotIn("192.0.2.10", r["logs"])
                self.assertIs(r["network_redacted"], True)
                self.assertIs(r["redacted"], True)

    async def test_otro_identifier_conserva_la_red(self) -> None:
        for identifier in ("addon_core_ficticio", "kernel", None):
            with self.subTest(identifier=identifier):
                ruta = ("/host/logs" if identifier is None
                        else f"/host/logs/identifiers/{identifier}")
                self.sv.texto(ruta, "conexión desde 192.0.2.10\n")
                r = await self.tools["sv_get_host_logs"](identifier=identifier)
                self.assertIn("192.0.2.10", r["logs"])
                self.assertIs(r["network_redacted"], False)


class TestIdentificadores(_Base):
    async def test_ordenados_con_el_sobre(self) -> None:
        self.sv.respuesta("GET", "/host/logs/identifiers", IDENTIFIERS)
        r = await self.tools["sv_list_host_log_identifiers"]()
        self.assertEqual(self.rutas(), ["/host/logs/identifiers"])
        self.assertEqual(r["items"], sorted(IDENTIFIERS["identifiers"]))
        self.assertEqual(r["count"], len(IDENTIFIERS["identifiers"]))
        self.assertIs(r["truncated"], False)
        self.assertNotIn("search", r)

    async def test_search_sin_mayusculas(self) -> None:
        self.sv.respuesta("GET", "/host/logs/identifiers", IDENTIFIERS)
        r = await self.tools["sv_list_host_log_identifiers"](search="NETWORK")
        self.assertEqual(r["items"], ["NetworkManager"])
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["search"], "NETWORK")
        r = await self.tools["sv_list_host_log_identifiers"](search="addon_")
        self.assertEqual(r["items"], ["addon_a1b2c3d4_hermes", "addon_core_ficticio"])

    async def test_error(self) -> None:
        r = await self.tools["sv_list_host_log_identifiers"]()
        self.assertIn("error", r)

    async def test_forma_inesperada_es_error(self) -> None:
        """T031: sin `identifiers`, o con otra forma, error claro y no una
        lista vacía dada por buena (FR-016). Control negativo: volver a
        `brutos or []` → caen las cuatro subpruebas (`count: 0` sin `error`)."""
        for valor in ({}, {"identifiers": "kernel"}, {"identifiers": {"a": 1}}, ["kernel"]):
            with self.subTest(valor=valor):
                self.sv.respuesta("GET", "/host/logs/identifiers", valor)
                r = await self.tools["sv_list_host_log_identifiers"]()
                self.assertEqual(r, {"error": (
                    "Unexpected Supervisor response for GET /host/logs/identifiers.")})

    async def test_lista_vacia_con_la_clave_es_buena(self) -> None:
        # Contraste: la clave presente y vacía SÍ es una respuesta válida.
        self.sv.respuesta("GET", "/host/logs/identifiers", {"identifiers": []})
        r = await self.tools["sv_list_host_log_identifiers"]()
        self.assertEqual(r, {"count": 0, "truncated": False, "items": []})


class TestArranques(_Base):
    async def test_del_actual_al_mas_antiguo(self) -> None:
        self.sv.respuesta("GET", "/host/logs/boots", BOOTS)
        r = await self.tools["sv_list_boots"]()
        self.assertEqual(self.rutas(), ["/host/logs/boots"])
        self.assertEqual(r, {"count": 3, "truncated": False, "items": [
            {"offset": 0, "boot_id": BOOT_ACTUAL},
            {"offset": -1, "boot_id": BOOT_ANTERIOR},
            {"offset": -2, "boot_id": BOOT_ANTIGUO},
        ]})

    async def test_error(self) -> None:
        r = await self.tools["sv_list_boots"]()
        self.assertIn("error", r)

    async def test_forma_inesperada_es_error(self) -> None:
        """T031: sin `boots`, o con `boots` que no es un objeto, error claro
        en vez de una lista vacía o de un `AttributeError` (FR-016). Control
        negativo: volver a `(boots or {}).items()` → caen las subpruebas (lista
        vacía como buena, y `AttributeError` con la lista)."""
        for valor in ({}, {"boots": ["x"]}, {"boots": "0"}, [BOOT_ACTUAL]):
            with self.subTest(valor=valor):
                self.sv.respuesta("GET", "/host/logs/boots", valor)
                r = await self.tools["sv_list_boots"]()
                self.assertEqual(r, {"error": (
                    "Unexpected Supervisor response for GET /host/logs/boots.")})

    async def test_items_pasan_por_redact_structure(self) -> None:
        """T031: los `items` pasan por `redact_structure` como el resto de
        respuestas JSON del Supervisor (FR-016 para FR-006). Hoy sus claves
        no son sensibles, así que se comprueba la llamada con un espía que
        marca lo que recibe. Control negativo: quitar la llamada → cae."""
        from unittest.mock import patch

        from hermes.tools import system_logs

        def espia(valor: Any, _key: str = "") -> Any:
            return [{**i, "redactado": True} for i in valor]

        self.sv.respuesta("GET", "/host/logs/boots", BOOTS)
        with patch.object(system_logs, "redact_structure", espia):
            r = await self.tools["sv_list_boots"]()
        self.assertEqual(len(r["items"]), 3)
        self.assertTrue(all(i.get("redactado") for i in r["items"]))


class TestRecorte(_Base):
    max_bytes = 2048

    async def test_log_grande_devuelve_las_ultimas_lineas(self) -> None:
        self.sv.texto("/core/logs", log_numerado(400))
        r = await self.tools["sv_get_core_logs"](lines=400)
        self.assertIs(r["truncated"], True)
        self.assertGreater(r["lines_returned"], 0)
        self.assertLess(r["lines_returned"], 400)
        self.assertIn("línea 399\n", r["logs"])
        self.assertNotIn("línea 0\n", r["logs"])
        self.assertEqual(r["logs"].count("\n"), r["lines_returned"])
        self.assertIn("fewer lines", r["hint"])
        self.assertEqual(r["route"], "/core/logs")


# ── Evento de log (T006) ──────────────────────────────────────────────────────


class TestEventoDeLog(_Base):
    """Un `system_diagnostics_read` por llamada, con la plantilla de la ruta y
    recuentos; nunca el contenido, el id de arranque, el `identifier` ni el
    `search` (FR-010; el log se pega en issues públicos)."""

    def _eventos(self, logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [e for e in logs if e.get("event") == "system_diagnostics_read"]

    async def test_lectura_correcta(self) -> None:
        ruta = f"/host/logs/boots/{BOOT_ANTERIOR}/identifiers/kernel-secreto"
        self.sv.texto(ruta, log_con_centinelas())
        with capture_logs() as logs:
            await self.tools["sv_get_host_logs"](
                boot=BOOT_ANTERIOR, identifier="kernel-secreto", lines=50)
        ev = self._eventos(logs)
        self.assertEqual(len(ev), 1)
        e = ev[0]
        self.assertEqual(e["tool"], "sv_get_host_logs")
        self.assertEqual(e["route"], "/host/logs/boots/{bootid}/identifiers/{identifier}")
        self.assertEqual(e["lines"], 50)
        self.assertEqual(e["bytes"], len(log_con_centinelas()))
        self.assertIs(e["redacted"], True)
        self.assertEqual(e["outcome"], "ok")
        texto = repr(logs)
        for prohibido in (BOOT_ANTERIOR, "kernel-secreto", CENTINELA_PASSWORD,
                          CENTINELA_TOKEN, "arrancando"):
            self.assertNotIn(prohibido, texto)

    async def test_argumento_invalido(self) -> None:
        with capture_logs() as logs:
            await self.tools["sv_get_core_logs"](boot="valor-raro-xyz")
            await self.tools["sv_get_host_logs"](identifier="a/secreto")
        ev = self._eventos(logs)
        self.assertEqual([e["outcome"] for e in ev], ["invalid_argument"] * 2)
        self.assertEqual([e["field"] for e in ev], ["boot", "identifier"])
        texto = repr(logs)
        self.assertNotIn("valor-raro-xyz", texto)
        self.assertNotIn("secreto", texto)

    async def test_error(self) -> None:
        with capture_logs() as logs:
            await self.tools["sv_get_core_logs"](boot=BOOT_ANTIGUO)
        ev = self._eventos(logs)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["outcome"], "error")
        self.assertEqual(ev[0]["route"], "/core/logs/boots/{bootid}")
        self.assertNotIn(BOOT_ANTIGUO, repr(logs))

    async def test_listas_sin_search_ni_ids(self) -> None:
        self.sv.respuesta("GET", "/host/logs/identifiers", IDENTIFIERS)
        self.sv.respuesta("GET", "/host/logs/boots", BOOTS)
        with capture_logs() as logs:
            await self.tools["sv_list_host_log_identifiers"](search="busqueda-privada")
            await self.tools["sv_list_boots"]()
        ev = self._eventos(logs)
        self.assertEqual([e["tool"] for e in ev],
                         ["sv_list_host_log_identifiers", "sv_list_boots"])
        self.assertEqual([e["count"] for e in ev], [0, 3])
        self.assertTrue(all(e["outcome"] == "ok" for e in ev))
        texto = repr(logs)
        for prohibido in ("busqueda-privada", BOOT_ACTUAL, "NetworkManager"):
            self.assertNotIn(prohibido, texto)


if __name__ == "__main__":
    unittest.main()
