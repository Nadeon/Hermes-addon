"""Lectura de `/data/options.json` en `run.sh`: los booleanos a `false`.

`run.sh` traduce las opciones del add-on a variables de entorno con `jq`. Los
helpers `cfg` y `cfg_default` usaban `jq -r '.clave // empty'`, y el operador
`//` de jq considera "vacío" tanto `null` como `false`. Resultado: cualquier
booleano puesto explícitamente a `false` —`call_service_auto_classify_dangerous`
es el caso real— se leía como cadena vacía y `cfg_default` lo sustituía por su
valor por defecto `true`. El usuario desactivaba la clasificación automática de
servicios peligrosos y obtenía exactamente lo contrario.

No hay forma de ejercitar esto desde Python: el bug vive en el filtro de jq. Los
tests extraen las funciones del propio `run.sh` —no una copia, que se quedaría
desincronizada— y las ejecutan con `sh` + `jq` contra un options.json temporal.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RUN_SH = Path(__file__).resolve().parent.parent / "hermes" / "run.sh"

# Una definición de función POSIX sh tal como las escribe run.sh: `nombre() {`
# en la columna 0 y el cierre `}` también en la columna 0.
_INICIO_FUNCION = re.compile(r"^(cfg|cfg_default)\(\)\s*\{$")


def _extraer_helpers(texto: str) -> str:
    """Devuelve el código de `cfg` y `cfg_default` tal cual está en run.sh."""
    lineas = texto.splitlines()
    bloques: list[str] = []
    i = 0
    while i < len(lineas):
        if _INICIO_FUNCION.match(lineas[i]):
            inicio = i
            while i < len(lineas) and lineas[i] != "}":
                i += 1
            bloques.append("\n".join(lineas[inicio : i + 1]))
        i += 1
    return "\n\n".join(bloques)


@unittest.skipIf(shutil.which("jq") is None, "jq no está instalado")
@unittest.skipIf(shutil.which("sh") is None, "sh no está instalado")
class TestHelpersDeOpciones(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.helpers = _extraer_helpers(RUN_SH.read_text(encoding="utf-8"))
        # Si un refactor renombra los helpers, el test debe fallar en vez de
        # pasar en vacío ejecutando un script sin funciones.
        assert "cfg_default()" in cls.helpers, "cfg_default no está en run.sh"
        assert "cfg()" in cls.helpers, "cfg no está en run.sh"

    def _ejecutar(self, opciones: dict[str, object], comando: str) -> str:
        """Corre `comando` con los helpers de run.sh cargados."""
        with tempfile.TemporaryDirectory() as tmp:
            options_path = Path(tmp) / "options.json"
            options_path.write_text(json.dumps(opciones), encoding="utf-8")
            script = (
                f'OPTIONS="{options_path}"\n'
                f"{self.helpers}\n"
                f"{comando}\n"
            )
            proc = subprocess.run(
                ["sh", "-c", script],
                capture_output=True,
                text=True,
                timeout=30,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def test_false_configurado_no_se_convierte_en_el_default(self) -> None:
        """El bug: `false` + default `true` devolvía `true`."""
        salida = self._ejecutar(
            {"call_service_auto_classify_dangerous": False},
            "cfg_default call_service_auto_classify_dangerous true",
        )
        self.assertEqual(salida, "false")

    def test_cfg_devuelve_false_tal_cual(self) -> None:
        salida = self._ejecutar({"safety_backup_enabled": False},
                                "cfg safety_backup_enabled")
        self.assertEqual(salida, "false")

    def test_true_configurado_se_respeta(self) -> None:
        salida = self._ejecutar(
            {"call_service_auto_classify_dangerous": True},
            "cfg_default call_service_auto_classify_dangerous false",
        )
        self.assertEqual(salida, "true")

    def test_clave_ausente_cae_al_default(self) -> None:
        salida = self._ejecutar({}, "cfg_default network_mode tailscale")
        self.assertEqual(salida, "tailscale")

    def test_clave_a_null_cae_al_default(self) -> None:
        """`null` es lo que el Supervisor escribe para una opción sin valor."""
        salida = self._ejecutar({"network_mode": None},
                                "cfg_default network_mode tailscale")
        self.assertEqual(salida, "tailscale")

    def test_valores_normales_siguen_funcionando(self) -> None:
        salida = self._ejecutar({"network_mode": "reverse_proxy"},
                                "cfg_default network_mode tailscale")
        self.assertEqual(salida, "reverse_proxy")

    def test_enteros_siguen_funcionando(self) -> None:
        salida = self._ejecutar({"mcp_max_requests_per_minute": 240},
                                "cfg_default mcp_max_requests_per_minute 120")
        self.assertEqual(salida, "240")

    def test_cero_no_se_confunde_con_ausente(self) -> None:
        """`0` es falsy en muchos lenguajes pero no en jq; que siga sin serlo."""
        salida = self._ejecutar({"safety_backup_window_minutes": 0},
                                "cfg_default safety_backup_window_minutes 30")
        self.assertEqual(salida, "0")


if __name__ == "__main__":
    unittest.main()
