"""Respuestas del Supervisor simulado para la spec 013 (diagnóstico).

Reproducen la FORMA de las respuestas del Supervisor 2026.11.0 (leída en su
código, `supervisor/api/host.py` y `api/utils.py`), con datos ficticios:
ids de arranque inventados, IPs de documentación (RFC 5737) y centinelas de
texto. Nada sale de una instalación real (principio VIII).

- Los logs son `text/plain`: el Supervisor devuelve las líneas del journal
  formateadas, una por línea.
- `/host/logs/boots` → `{"boots": {"0": <id>, "-1": <id>, …}}` (claves de
  texto con el desplazamiento).
- `/host/logs/identifiers` → `{"identifiers": [...]}` sin orden garantizado.
"""

from __future__ import annotations

import copy
from typing import Any

from hermes.ha import HAConnectionError

# Ids de arranque inventados (32 hexadecimales, como los de systemd).
BOOT_ACTUAL = "0123456789abcdef0123456789abcdef"
BOOT_ANTERIOR = "fedcba9876543210fedcba9876543210"
BOOT_ANTIGUO = "00112233445566778899aabbccddeeff"

BOOTS = {"boots": {"-1": BOOT_ANTERIOR, "0": BOOT_ACTUAL, "-2": BOOT_ANTIGUO}}

IDENTIFIERS = {
    "identifiers": [
        "systemd-journald", "kernel", "NetworkManager", "addon_core_ficticio",
        "hassio_supervisor", "addon_a1b2c3d4_hermes",
    ]
}

# Centinelas: si aparecen en una respuesta, la redacción ha fallado.
CENTINELA_PASSWORD = "centinela-1"
CENTINELA_TOKEN = "centinela-2"
# JWT de forma válida y contenido inventado (cabecera, cuerpo y firma).
CENTINELA_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiJjZW50aW5lbGEtand0In0."
    "c2lnbmF0dXJhLWNlbnRpbmVsYS1maWN0aWNpYQ"
)


def log_numerado(n: int, prefijo: str = "línea") -> str:
    """Un log de `n` líneas numeradas, como el texto del journal."""
    return "".join(
        f"2026-11-14 12:00:{i % 60:02d} servicio[{i}]: {prefijo} {i}\n"
        for i in range(n)
    )


def log_con_centinelas() -> str:
    return (
        "2026-11-14 12:00:00 core: arrancando\n"
        f"2026-11-14 12:00:01 core: password: {CENTINELA_PASSWORD}\n"
        f"2026-11-14 12:00:02 core: Authorization: Bearer {CENTINELA_JWT}\n"
        f"2026-11-14 12:00:03 core: GET /api?token={CENTINELA_TOKEN}\n"
        "2026-11-14 12:00:04 core: listo\n"
    )


class SupervisorSimulado:
    """Cliente simulado que apunta cada petición (ruta, `params`, tiempo de
    espera) y responde con lo configurado por ruta exacta.

    Lo que se comprueba con él es lo que Hermes MANDA al Supervisor y lo que
    hace con la respuesta; una ruta sin respuesta configurada da el mismo
    error que un 404 del Supervisor.
    """

    def __init__(self) -> None:
        self.textos: dict[str, Any] = {}
        self.json: dict[tuple[str, str], Any] = {}
        self.llamadas: list[dict[str, Any]] = []

    def texto(self, ruta: str, valor: Any) -> None:
        self.textos[ruta] = valor

    def respuesta(self, metodo: str, ruta: str, valor: Any) -> None:
        self.json[(metodo.upper(), ruta)] = valor

    async def sv_request_text(
        self,
        sv_path: str,
        params: dict[str, str] | None = None,
        timeout_seconds: float = 60.0,
    ) -> str:
        self.llamadas.append({
            "metodo": "GET", "ruta": sv_path, "params": copy.deepcopy(params),
            "timeout": timeout_seconds, "texto": True,
        })
        valor = self.textos.get(sv_path)
        if valor is None:
            raise HAConnectionError(
                f"Supervisor GET {sv_path} failed 404: not found", status=404)
        if isinstance(valor, Exception):
            raise valor
        return valor

    async def sv_request(
        self,
        method: str,
        sv_path: str,
        json_body: Any = None,
        params: Any = None,
        timeout_seconds: float = 60.0,
    ) -> Any:
        self.llamadas.append({
            "metodo": method.upper(), "ruta": sv_path,
            "params": copy.deepcopy(params), "timeout": timeout_seconds,
            "texto": False,
        })
        valor = self.json.get((method.upper(), sv_path))
        if valor is None:
            raise HAConnectionError(
                f"Supervisor {method.upper()} {sv_path} failed 404: not found",
                status=404)
        if isinstance(valor, Exception):
            raise valor
        return copy.deepcopy(valor)
