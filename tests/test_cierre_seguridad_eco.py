"""Cierre de seguridad de la 1.2.0, punto 1: el eco de los valores en los
errores del Supervisor, limpiado en un único punto para todas las `sv_*`.

El Supervisor 2026.11.0 valida los cuerpos con `api_validate`
(`supervisor/api/utils.py`) y, sin `redact_values`, responde con
`humanize_error(data, ex)` de voluptuous: «<error>. Got <repr() del valor>»,
cortado a 497 caracteres + `...`. Con un validador en la raíz (`vol.All(
vol.Any(...), usage_specific_validation)` de `mounts/validate.py`) o en un
objeto (`_validate_wifi_config_v2` de `api/network.py`), el valor es el
objeto ENTERO, contraseña incluida, entre las comillas simples de `repr()`,
que `redact_secrets` no reconoce. El error viaja en el cuerpo JSON del 400
(`{"result": "error", "message": …}`), que `HAClient.sv_request` mete en el
texto del `HAConnectionError` («Supervisor REST POST … failed 400: …»).

Controles negativos (comprobados al escribirlos):
(a) `sin_eco_del_supervisor` devolviendo `redact_secrets(texto)` sin más →
    caen `TestSinEco` (todos menos el texto limpio) y los de extremo a
    extremo de montajes, backups, opciones de Core y API genérica;
(b) quitar la llamada en `backups.py` (`sv_create_backup_full`) → cae
    `test_backup_completo_con_contrasena`;
(c) quitar el módulo de `_eco_supervisor` de la lista de un módulo que
    manda cuerpos (p. ej. borrar el import de `host_network.py`) → cae
    `TestTodasLasSvQueMandanCuerpo`.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from hermes import security
from hermes.ha import HAConnectionError
from hermes.tools._eco_supervisor import sin_eco_del_supervisor

_CLAVE = "Kp9-centinela-eco-4Wz"
_TOOLS = Path(__file__).resolve().parent.parent / "hermes" / "src" / "hermes" / "tools"


def humanize(valor: Any, error: str) -> str:
    """`humanize_error` de voluptuous para un error con `valor` en su ruta."""
    got = repr(valor)
    if len(got) > 500:
        got = got[:497] + "..."
    return f"{error}. Got {got}"


def error_400(ruta: str, mensaje: str) -> HAConnectionError:
    """El 400 de `api_process` tal como lo deja `HAClient.sv_request`."""
    cuerpo = json.dumps({"result": "error", "message": mensaje})
    return HAConnectionError(
        f"Supervisor REST POST http://supervisor{ruta} failed 400: {cuerpo}", status=400)


def trozos(secreto: str, largo: int = 6) -> list[str]:
    formas = {secreto, repr(secreto)[1:-1], json.dumps(secreto)[1:-1]}
    return [f[i:i + largo] for f in formas for i in range(len(f) - largo + 1)]


class _SinSecreto(unittest.TestCase):
    def assertSinSecreto(self, valor: Any, secreto: str = _CLAVE) -> None:  # noqa: N802
        texto = valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False)
        for trozo in trozos(secreto):
            self.assertNotIn(trozo, texto)


class TestSinEco(_SinSecreto):
    def test_wifi_con_psk_en_el_objeto(self) -> None:
        # `_validate_wifi_config_v2`: el error va en `data['wifi']` y el
        # «Got» es el objeto wifi entero, con la PSK.
        wifi = {"mode": "infrastructure", "ssid": "casa", "auth": "open", "psk": _CLAVE}
        mensaje = humanize(wifi, "psk is only valid when auth is wpa-psk for "
                                 "dictionary value @ data['wifi']")
        texto = str(error_400("/network/interface/wlan0/update", mensaje))
        self.assertIn(_CLAVE, texto)  # el escenario: el Supervisor la repite
        limpio = sin_eco_del_supervisor(texto, {"wifi": wifi})
        self.assertSinSecreto(limpio)
        self.assertIn("psk is only valid when auth is wpa-psk", limpio)
        self.assertNotIn("Got", limpio)

    def test_corte_de_voluptuous_dentro_del_secreto(self) -> None:
        # Un campo largo empuja el corte a 497 caracteres dentro de la
        # contraseña: queda el principio, sin comilla de cierre.
        base = {"name": "nas", "type": "cifs", "usage": "backup", "server": "",
                "share": "copias", "username": "u", "password": _CLAVE}
        hasta = repr({**base, "server": ""}).index(_CLAVE)
        for k in (1, 6, len(_CLAVE) - 1):
            with self.subTest(k=k):
                datos = {**base, "server": "s" * (497 - hasta - k)}
                mensaje = humanize(datos, "Backup mounts cannot be read only")
                self.assertIn(_CLAVE[:k], mensaje)
                self.assertSinSecreto(sin_eco_del_supervisor(mensaje, datos))

    def test_texto_sin_eco_no_cambia(self) -> None:
        texto = "Supervisor error: A mount already exists with name nas"
        self.assertEqual(sin_eco_del_supervisor(texto, {"name": "x_otro"}), texto)

    def test_mensaje_generico_si_queda_un_rastro(self) -> None:
        # El secreto aparece ANTES de «Got» (un mensaje que lo citara): no se
        # arriesga, solo la clave que falla.
        texto = f"invalid value {_CLAVE[:-1]} @ data['password']. Got 'x'"
        limpio = sin_eco_del_supervisor(texto + "", {"password": _CLAVE + "Q"})
        self.assertSinSecreto(limpio, _CLAVE + "Q")
        self.assertIn("The Supervisor rejected the request", limpio)
        self.assertIn("data['password']", limpio)


class _MCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, *a: Any, **k: Any):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


class TestDeExtremoAExtremo(unittest.IsolatedAsyncioTestCase, _SinSecreto):
    async def test_crear_montaje(self) -> None:
        from hermes.tools.mounts import register
        from tests.fixtures.supervisor_montajes import SupervisorDeMontajes

        sv = SupervisorDeMontajes()
        mcp = _MCP()
        register(mcp, sv)
        args = {"name": "nas2", "type": "cifs", "usage": "media", "server": "nas2.local",
                "share": "recurso2", "username": "copias", "password": _CLAVE}
        cuerpo = {**args, "read_only": False}
        sv.errores[("POST", "/mounts")] = error_400(
            "/mounts", humanize(cuerpo, "not a valid value"))
        vista = await mcp.tools["sv_create_mount"](**args)
        r = await mcp.tools["sv_create_mount"](
            **args, confirmation_token=vista["confirmation_token"])
        self.assertIn("error", r)
        self.assertIn("not a valid value", r["error"])
        self.assertSinSecreto(r)

    async def test_backup_completo_con_contrasena(self) -> None:
        from hermes.tools.backups import register

        ha = MagicMock()
        payload = {"name": "copia semanal", "background": True, "password": _CLAVE,
                   "location": "nas"}
        # El esquema pide `str` en `location` y cada error repite su valor;
        # aquí, un validador en la raíz que repite la carga entera.
        ha.sv_request = AsyncMock(side_effect=error_400(
            "/backups/new/full", humanize(payload, "expected a dictionary")))
        mcp = _MCP()
        register(mcp, ha)
        r = await mcp.tools["sv_create_backup_full"](
            name="copia semanal", password=_CLAVE, location="nas")
        self.assertIn("expected a dictionary", r["error"])
        self.assertSinSecreto(r)
        # La 1.1.2 lo dejaba pasar: `'password': '…'` con comillas simples.
        self.assertIn(_CLAVE, security.redact_secrets(str(ha.sv_request.side_effect)))

    async def test_opciones_de_core(self) -> None:
        from hermes.tools.system_control import register

        valor = "alsa_output.usb-" + _CLAVE
        ha = MagicMock()

        async def sv_request(metodo: str, ruta: str, **kw: Any) -> Any:
            if metodo == "GET":
                return {"boot": True, "watchdog": True, "audio_output": None}
            raise error_400(ruta, humanize(valor, "Invalid audio device @ data['audio_output']"))

        ha.sv_request = sv_request
        mcp = _MCP()
        register(mcp, ha, response_max_bytes=65536)
        opciones = {"audio_output": valor}
        vista = await mcp.tools["sv_set_core_options"](opciones)
        r = await mcp.tools["sv_set_core_options"](
            opciones, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "supervisor_request_failed", r)
        self.assertIn("Invalid audio device", r["detail"])
        self.assertSinSecreto(r)

    async def test_api_generica(self) -> None:
        from hermes.tools._eco_supervisor import sin_eco_del_supervisor as f
        # La genérica pasa el cuerpo enviado: lo comprueba la guarda estática
        # de abajo; aquí, que su limpieza local más la común no dejan nada.
        from hermes.tools.generic_commands import _mensaje_seguro

        cuerpo = {"options": {"token_de_api": "corto", "nota": _CLAVE}}
        texto = str(error_400("/addons/x/options", humanize(cuerpo, "bad")))
        self.assertSinSecreto(_mensaje_seguro(f(texto, cuerpo), cuerpo))


# Módulos que mandan un cuerpo al Supervisor y no repiten su error: sin
# texto del Supervisor en la respuesta o sin datos del usuario en el cuerpo.
_SIN_ECO_POSIBLE = {
    # `{"background": True}` y `{"force": …}`: nada del usuario.
    "store_apps.py": "body is only {'force': bool}",
    # El backup previo del Marketplace manda un nombre que genera Hermes.
    "_marketplace_write.py": "backup body is generated by Hermes",
    # Las de Core (`_request_json` a HA), no al Supervisor.
    "config_entry_flows.py": "Core REST, not the Supervisor",
    "config_subentries.py": "Core REST, not the Supervisor",
    "repair_flows.py": "Core REST, not the Supervisor",
    # `days_until_stale` y `default_backup_mount`: pasan por
    # `mounts._limpiar_error`, que acaba en la limpieza común.
    "backup_settings.py": "uses mounts._limpiar_error",
}


class TestTodasLasSvQueMandanCuerpo(unittest.TestCase):
    """Guarda: todo módulo que hace `sv_request(..., json_body=...)` usa la
    limpieza común (o está en `_SIN_ECO_POSIBLE` con su motivo)."""

    def test_guarda(self) -> None:
        faltan = []
        for ruta in sorted(_TOOLS.glob("*.py")):
            arbol = ast.parse(ruta.read_text(encoding="utf-8"))
            manda = any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "sv_request"
                and any(k.arg == "json_body" for k in n.keywords)
                for n in ast.walk(arbol))
            if not manda or ruta.name in _SIN_ECO_POSIBLE:
                continue
            if "sin_eco_del_supervisor" not in ruta.read_text(encoding="utf-8") \
                    and "_sin_valores_secretos" not in ruta.read_text(encoding="utf-8"):
                faltan.append(ruta.name)
        self.assertEqual(faltan, [])
