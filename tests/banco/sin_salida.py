"""¿Tiene salida a internet este proceso? (spec 010, FR-002, T040).

Lo ejecuta el job del banco DENTRO del contenedor de HA, con su python3:

    docker exec -i ha-banco python3 - 1.1.1.1:443 8.8.8.8:443 < tests/banco/sin_salida.py

Abre una conexión TCP a cada destino, que va como IP literal para no depender
del DNS: un fallo solo de DNS no prueba que no haya salida. Fail-closed:

- salida 0 («sin salida») solo si TODAS las conexiones fallan a nivel de red
  (rechazada, sin ruta o tiempo agotado);
- salida 1 si alguna se establece. Basta con eso: no se habla HTTP, así que
  un 429 o un 5xx del otro lado, que también prueban que hay salida, no
  pueden pasar por «sin salida» (era el fallo de la versión con `urllib`,
  donde `HTTPError` es un `OSError`);
- cualquier otra salida (argumentos mal puestos, un error inesperado) también
  hace fallar el paso.

Solo usa la biblioteca estándar: corre con el python3 de la imagen de HA.
"""

from __future__ import annotations

import socket
import sys

TIMEOUT = 5.0


def hay_salida(destinos: list[tuple[str, int]], timeout: float = TIMEOUT) -> bool:
    salida = False
    for host, puerto in destinos:
        try:
            with socket.create_connection((host, puerto), timeout=timeout):
                pass
        except OSError as exc:
            # ConnectionRefusedError (el REJECT del cortafuegos), TimeoutError,
            # sin ruta… La conexión no llegó a establecerse.
            print(f"{host}:{puerto}: sin conexión ({type(exc).__name__})")
            continue
        print(f"{host}:{puerto}: CONEXIÓN ESTABLECIDA")
        salida = True
    return salida


def _destinos(argumentos: list[str]) -> list[tuple[str, int]]:
    destinos = []
    for argumento in argumentos:
        host, _, puerto = argumento.rpartition(":")
        # Solo IP literal: con un nombre, el fallo podría ser solo de DNS.
        socket.inet_aton(host)
        destinos.append((host, int(puerto)))
    if not destinos:
        raise ValueError("sin destinos")
    return destinos


def main(argumentos: list[str]) -> int:
    try:
        destinos = _destinos(argumentos)
    except (OSError, ValueError):
        print("uso: sin_salida.py <ip>:<puerto> [...]", file=sys.stderr)
        return 2
    return 1 if hay_salida(destinos) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
