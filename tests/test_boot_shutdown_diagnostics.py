"""Arranque y apagado: diagnóstico del bind del health y presupuesto de parada.

Tres observaciones del repaso del arranque, con un test cada una:

1. Si el socket del health no se puede bindear, uvicorn llamaba a `sys.exit(1)`
   DENTRO de la task del health: el proceso moría sin una sola línea de Hermes
   explicando por qué. Pasa en cuanto 172.30.32.1 no es una dirección local —
   fuera de HAOS, o sin `host_network: true`.

2. `__main__` esperaba 5 s a que el servidor MCP terminase tras el SIGTERM, pero
   s6-overlay manda SIGKILL a los 3000 ms por defecto (`S6_KILL_GRACETIME`) y
   uvicorn no tenía `timeout_graceful_shutdown`: el apagado ordenado no llegaba
   a terminar nunca. Los tres números viven en tres ficheros distintos, así que
   aquí se comprueba que sigan ordenados.

3. `health_startup_grace_seconds` se usa tal cual en tres pasos seguidos del
   boot (Tailscale, /core/info y WebSocket): no se reparte. No se cambia la
   semántica —acortarla rompería arranques en frío lentos—, se documenta.
"""

from __future__ import annotations

import asyncio
import logging
import re
import socket
import unittest
import unittest.mock as mock
from pathlib import Path

import structlog

from hermes.__main__ import (
    MCP_GRACEFUL_SHUTDOWN_SECONDS,
    MCP_SHUTDOWN_WAIT_SECONDS,
)
from hermes.health import HealthServer

RAIZ = Path(__file__).resolve().parents[1]
DOCKERFILE = RAIZ / "hermes" / "Dockerfile"
MAIN_PY = RAIZ / "hermes" / "src" / "hermes" / "__main__.py"
CONFIG_YAML = RAIZ / "hermes" / "config.yaml"

# Dirección de documentación (RFC 5737): nunca es local en la máquina que corre
# los tests, así que el bind falla siempre y por la razón que interesa.
IP_NO_LOCAL = "203.0.113.1"


def _puerto_libre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])



class TestHealthNeverBindsAllInterfaces(unittest.IsolatedAsyncioTestCase):
    """El health no lleva autenticación: un host vacío o comodín lo publicaría
    en todas las interfaces, y se rechaza antes de abrir el socket."""

    async def test_wildcard_hosts_are_refused(self) -> None:
        from hermes.health import HealthServer

        for host in ("", "0.0.0.0", "::", "*"):
            server = HealthServer(bind_host=host, bind_port=0)
            with self.assertRaises(RuntimeError, msg=repr(host)):
                await server.start()

class TestBindDelHealth(unittest.IsolatedAsyncioTestCase):
    async def test_un_bind_imposible_aborta_con_un_error_legible(self) -> None:
        """Antes: el proceso moría mudo desde dentro de la task del health."""
        server = HealthServer(bind_host=IP_NO_LOCAL, bind_port=_puerto_libre())
        with self.assertRaises(RuntimeError) as ctx:
            await server.start()
        mensaje = str(ctx.exception)
        self.assertIn(IP_NO_LOCAL, mensaje)
        self.assertIn("host_network", mensaje)

    async def test_el_fallo_queda_en_el_log_con_host_puerto_y_errno(self) -> None:
        """El log del add-on es lo único que ve quien reporta el problema."""
        puerto = _puerto_libre()
        server = HealthServer(bind_host=IP_NO_LOCAL, bind_port=puerto)
        with structlog.testing.capture_logs() as capturado:
            with self.assertRaises(RuntimeError):
                await server.start()
        eventos = [e for e in capturado if e.get("event") == "health_bind_failed"]
        self.assertEqual(len(eventos), 1, capturado)
        evento = eventos[0]
        self.assertEqual(evento["host"], IP_NO_LOCAL)
        self.assertEqual(evento["port"], puerto)
        self.assertIsNotNone(evento["errno"])
        self.assertIn("host_network", evento["hint"])

    async def test_no_deja_ninguna_task_colgando(self) -> None:
        """Si arrancara la task igualmente, uvicorn mataría el proceso luego."""
        server = HealthServer(bind_host=IP_NO_LOCAL, bind_port=_puerto_libre())
        with self.assertRaises(RuntimeError):
            await server.start()
        self.assertIsNone(server._server_task)

    async def test_un_bind_posible_sigue_arrancando(self) -> None:
        """El sondeo previo cierra su socket: uvicorn tiene que poder bindear."""
        server = HealthServer(bind_host="127.0.0.1", bind_port=_puerto_libre())
        await server.start()
        try:
            # Un respiro para que uvicorn llegue a abrir su propio socket; si el
            # sondeo hubiera dejado el puerto ocupado, la task moriría aquí.
            await asyncio.sleep(0.2)
            self.assertIsNotNone(server._server_task)
            assert server._server_task is not None
            self.assertFalse(server._server_task.done())
        finally:
            await server.stop()


class TestPresupuestoDeApagado(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        cls.main_py = MAIN_PY.read_text(encoding="utf-8")

    def _s6_kill_gracetime_segundos(self) -> float:
        m = re.search(
            r"^ENV\s+S6_KILL_GRACETIME=(\d+)\s*$", self.dockerfile, re.MULTILINE
        )
        self.assertIsNotNone(
            m,
            "el Dockerfile no fija S6_KILL_GRACETIME: s6 manda SIGKILL a los "
            "3000 ms por defecto y corta el apagado ordenado",
        )
        assert m is not None
        return int(m.group(1)) / 1000.0

    def test_los_tres_plazos_estan_ordenados(self) -> None:
        """uvicorn < espera de __main__ < margen de s6. Si no, hay SIGKILL."""
        s6 = self._s6_kill_gracetime_segundos()
        self.assertLess(
            MCP_GRACEFUL_SHUTDOWN_SECONDS,
            MCP_SHUTDOWN_WAIT_SECONDS,
            "__main__ tiene que esperar MÁS de lo que tarda uvicorn en cerrar",
        )
        self.assertLess(
            MCP_SHUTDOWN_WAIT_SECONDS,
            s6,
            "s6 mataría el proceso antes de que __main__ termine de esperar",
        )

    def test_queda_holgura_para_limpiar_los_temporales(self) -> None:
        """Tras esperar al MCP todavía hay que borrar los .tmp y loguear."""
        self.assertLessEqual(
            MCP_SHUTDOWN_WAIT_SECONDS + 1.0, self._s6_kill_gracetime_segundos()
        )

    def test_uvicorn_recibe_el_timeout_de_cierre(self) -> None:
        """Sin él, uvicorn espera indefinidamente a las conexiones en vuelo."""
        self.assertIn(
            "timeout_graceful_shutdown=MCP_GRACEFUL_SHUTDOWN_SECONDS", self.main_py
        )

    def test_la_espera_usa_la_constante(self) -> None:
        """Un 5.0 suelto se separa del resto sin que nadie se entere."""
        self.assertIn("timeout=MCP_SHUTDOWN_WAIT_SECONDS", self.main_py)

    def test_el_dockerfile_explica_el_porque(self) -> None:
        bloque = self.dockerfile.split("ENV S6_KILL_GRACETIME")[0]
        self.assertIn("SIGKILL", bloque)


class TestMargenDeArranquePorPaso(unittest.TestCase):
    """No se cambia la semántica: se documenta y se registra."""

    def test_el_manifiesto_avisa_de_que_es_por_paso(self) -> None:
        texto = CONFIG_YAML.read_text(encoding="utf-8")
        bloque = texto.split("health_startup_grace_seconds:")[0]
        self.assertIn("POR PASO", bloque)

    def test_el_paso_4_registra_el_presupuesto_efectivo(self) -> None:
        """Es el primer paso que lo consume; verlo evita deducirlo del reloj."""
        main_py = MAIN_PY.read_text(encoding="utf-8")
        bloque = main_py.split('logger.info("boot_step_4"')[1].split(")")[0]
        self.assertIn(
            "startup_grace_seconds=config.health_startup_grace_seconds", bloque
        )

    def test_los_readmes_lo_dicen_en_la_tabla_de_opciones(self) -> None:
        en = (RAIZ / "README.md").read_text(encoding="utf-8")
        es = (RAIZ / "README.es.md").read_text(encoding="utf-8")
        fila_en = [
            l for l in en.splitlines() if l.startswith("| `health_startup_grace_seconds`")
        ]
        fila_es = [
            l for l in es.splitlines() if l.startswith("| `health_startup_grace_seconds`")
        ]
        self.assertTrue(fila_en and fila_es)
        self.assertIn("per boot step", fila_en[0])
        self.assertIn("por paso", fila_es[0])


class TestResolucionDelBridgeSinTryExceptMuerto(unittest.TestCase):
    """`resolve_hassio_bridge_gateway` no lanza: devuelve el fallback él mismo.

    El `except Exception` que lo envolvía no se podía ejecutar nunca, y hacía
    creer que el fallo estaba cubierto cuando el fallo real —no poder bindear
    esa IP— ocurría dos líneas más abajo y sin diagnóstico.
    """

    def test_el_except_muerto_ya_no_esta(self) -> None:
        main_py = MAIN_PY.read_text(encoding="utf-8")
        bloque = main_py.split("boot_step_3.5")[1].split("boot_step_4")[0]
        self.assertNotIn("hassio_bridge_fallback", bloque)
        self.assertIn("resolve_hassio_bridge_gateway()", bloque)

    def test_la_funcion_sigue_devolviendo_el_fallback_en_vez_de_lanzar(self) -> None:
        
        from hermes import network

        with mock.patch.object(network.psutil, "net_if_addrs", return_value={}):
            self.assertEqual(network.resolve_hassio_bridge_gateway(), "172.30.32.1")


# ── 009, FR-011: apagado sin traza (problema 23) ──────────────────────────────


class _Captura(logging.Handler):
    """Guarda los registros del `logging` estándar tal cual llegan."""

    def __init__(self) -> None:
        super().__init__(level=0)
        self.registros: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.registros.append(record)

    def texto(self) -> str:
        formato = logging.Formatter("%(levelname)s %(name)s %(message)s")
        return "\n".join(formato.format(r) for r in self.registros)


class TestApagadoSinTraza(unittest.IsolatedAsyncioTestCase):
    """Al reiniciar el add-on con una petición en vuelo (por ejemplo un
    `ha_wait_for_event`), uvicorn 0.54 agota `timeout_graceful_shutdown`,
    cancela la petición y su `run_asgi`, que captura `BaseException`, registra
    `Exception in ASGI application` con la traza de un `CancelledError`. El log
    de un apagado normal parecía un fallo (problema 23).

    Reproducido ANTES del arreglo con este mismo montaje (uvicorn real, sin el
    filtro): salen `Cancel 1 running task(s), timeout graceful shutdown
    exceeded` y `Exception in ASGI application` con `CancelledError: Task
    cancelled, timeout graceful shutdown exceeded`.

    Control negativo (T037): sin el filtro cae (a); filtrando cualquier
    excepción cae (b); sin `CancelledError` en el `except` de `main()` cae (c).
    """

    def setUp(self) -> None:
        import hermes.__main__ as main_mod

        self.main_mod = main_mod
        self.logger = logging.getLogger("uvicorn.error")
        self.filtros_previos = list(self.logger.filters)
        self.nivel_previo = self.logger.level
        self.captura = _Captura()
        self.logger.addHandler(self.captura)
        # Instalado como en el arranque.
        main_mod._instalar_filtro_de_cancelacion()

    def tearDown(self) -> None:
        self.logger.removeHandler(self.captura)
        self.logger.filters[:] = self.filtros_previos
        self.logger.setLevel(self.nivel_previo)

    async def test_peticion_en_vuelo_al_apagar_sin_traza(self) -> None:
        import uvicorn

        empezo = asyncio.Event()

        async def app(scope, receive, send):  # app ASGI mínima
            if scope["type"] != "http":
                return
            empezo.set()
            await asyncio.sleep(5)

        puerto = _puerto_libre()
        server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=puerto, log_level="error", log_config=None,
            lifespan="off", timeout_graceful_shutdown=0.2,
        ))
        tarea = asyncio.create_task(server.serve())
        for _ in range(500):
            if server.started:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(server.started)
        _, escritor = await asyncio.open_connection("127.0.0.1", puerto)
        try:
            escritor.write(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
            await escritor.drain()
            await asyncio.wait_for(empezo.wait(), 5)
            server.should_exit = True
            await asyncio.wait_for(tarea, 5)
        finally:
            escritor.close()

        texto = self.captura.texto()
        self.assertNotIn("Traceback", texto)
        self.assertNotIn("CancelledError", texto)
        self.assertNotIn("Exception in ASGI application", texto)
        self.assertIn("request_cancelled_on_shutdown", texto)

    def test_otra_excepcion_conserva_su_traza(self) -> None:
        try:
            raise RuntimeError("fallo-de-verdad")
        except RuntimeError as exc:
            self.logger.error("Exception in ASGI application\n", exc_info=exc)
        texto = self.captura.texto()
        self.assertIn("Traceback", texto)
        self.assertIn("RuntimeError: fallo-de-verdad", texto)
        self.assertEqual(self.captura.registros[-1].levelno, logging.ERROR)

    def test_la_cancelacion_sale_como_una_linea_informativa(self) -> None:
        self.logger.error(
            "Exception in ASGI application\n", exc_info=asyncio.CancelledError("x")
        )
        registro = self.captura.registros[-1]
        self.assertEqual(registro.getMessage(), "request_cancelled_on_shutdown")
        self.assertEqual(registro.levelno, logging.INFO)
        self.assertIsNone(registro.exc_info)

    def test_el_filtro_se_instala_una_vez_y_desde_el_arranque(self) -> None:
        self.main_mod._instalar_filtro_de_cancelacion()
        self.assertEqual(
            sum(isinstance(f, self.main_mod._CancelacionSinTraza) for f in self.logger.filters),
            1,
        )
        self.logger.filters[:] = self.filtros_previos
        config = mock.MagicMock(log_redact_network=True, adjustments=[])
        with mock.patch.object(self.main_mod, "setup_logging"):
            self.main_mod._setup_logging_from_config(config)
        self.assertTrue(
            any(isinstance(f, self.main_mod._CancelacionSinTraza) for f in self.logger.filters)
        )

    def test_main_con_cancelacion_registra_interrupted(self) -> None:
        def run(coro):
            coro.close()  # sin «coroutine was never awaited»
            raise asyncio.CancelledError()

        config = mock.MagicMock()
        with mock.patch.object(self.main_mod, "load_config", return_value=config), \
                mock.patch.object(self.main_mod, "_setup_logging_from_config"), \
                mock.patch.object(self.main_mod, "check_crash_loop"), \
                mock.patch.object(self.main_mod.asyncio, "run", side_effect=run), \
                structlog.testing.capture_logs() as eventos:
            self.main_mod.main()  # no propaga
        self.assertIn("interrupted", [e["event"] for e in eventos])

    async def test_la_espera_del_servidor_cancela_y_recoge_la_task(self) -> None:
        """En Python 3.12+ `wait_for` ya cancela y espera la task al vencer el
        plazo; el `cancel()` y la espera explícitos lo dejan dicho y no
        dependen de la versión. Por eso este test no tiene control negativo:
        con el código de la 1.1.2 también pasa en 3.13."""
        colgada = asyncio.create_task(asyncio.sleep(60))
        await self.main_mod._esperar_servidor_mcp(colgada, 0.05)
        self.assertTrue(colgada.done())
        self.assertTrue(colgada.cancelled())

    async def test_la_espera_no_se_traga_una_cancelacion_de_fuera(self) -> None:
        colgada = asyncio.create_task(asyncio.sleep(60))
        espera = asyncio.create_task(self.main_mod._esperar_servidor_mcp(colgada, 30))
        await asyncio.sleep(0.01)
        espera.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await espera
        colgada.cancel()


if __name__ == "__main__":
    unittest.main()
