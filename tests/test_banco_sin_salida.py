"""Comprobación «sin salida a internet» del job del banco (spec 010, FR-002, T040).

Se ejecuta `tests/banco/sin_salida.py` como lo hace el job (`python3 -` con el
script por la entrada estándar) contra destinos locales: un puerto cerrado
(como el REJECT del cortafuegos), uno que acepta la conexión y uno que
responde HTTP 429. Los dos últimos prueban que hay salida y tienen que dar
fallo; la versión anterior, con `urllib`, daba por buena la respuesta 429
porque `HTTPError` es un `OSError`.

Control negativo (T040), comprobado en local y restaurado: con `hay_salida`
devolviendo siempre False caen `test_conexion_establecida_es_salida` y
`test_respuesta_http_429_es_salida`.
"""

from __future__ import annotations

import http.server
import socket
import subprocess
import sys
import threading
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "banco" / "sin_salida.py"


def _ejecutar(*destinos: str) -> subprocess.CompletedProcess[str]:
    with SCRIPT.open("rb") as entrada:
        return subprocess.run(
            [sys.executable, "-", *destinos],
            stdin=entrada,
            capture_output=True,
            timeout=60,
            check=False,
        )


def _puerto_cerrado() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Responde429(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — nombre que exige http.server
        self.send_response(429)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


class TestSinSalida(unittest.TestCase):
    def test_conexion_rechazada_es_sin_salida(self) -> None:
        resultado = _ejecutar(f"127.0.0.1:{_puerto_cerrado()}", f"127.0.0.1:{_puerto_cerrado()}")
        self.assertEqual(resultado.returncode, 0, resultado.stdout)
        self.assertIn(b"ConnectionRefusedError", resultado.stdout)

    def test_conexion_establecida_es_salida(self) -> None:
        with socket.socket() as servidor:
            servidor.bind(("127.0.0.1", 0))
            servidor.listen()
            puerto = servidor.getsockname()[1]
            # Una sola conexión establecida basta, aunque la otra falle.
            resultado = _ejecutar(f"127.0.0.1:{_puerto_cerrado()}", f"127.0.0.1:{puerto}")
        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("ESTABLECIDA".encode(), resultado.stdout)

    def test_respuesta_http_429_es_salida(self) -> None:
        servidor = http.server.HTTPServer(("127.0.0.1", 0), _Responde429)
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        try:
            resultado = _ejecutar(f"127.0.0.1:{servidor.server_address[1]}")
        finally:
            servidor.shutdown()
            servidor.server_close()
        self.assertEqual(resultado.returncode, 1, resultado.stdout)

    def test_sin_ip_literal_o_sin_destinos_falla(self) -> None:
        # Un nombre obligaría a resolver DNS: un fallo solo de DNS no prueba nada.
        self.assertEqual(_ejecutar("localhost:443").returncode, 2)
        self.assertEqual(_ejecutar().returncode, 2)


if __name__ == "__main__":
    unittest.main()
