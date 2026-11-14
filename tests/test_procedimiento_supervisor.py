"""El procedimiento del banco del Supervisor se puede seguir sin trampas (spec 014, convergencia).

`docs/BANCO-SUPERVISOR.md` lo lee una persona y ejecuta sus comandos uno a
uno en una VM con un Hermes de rol `admin`. Tres errores de la primera versión
eran de los que no se ven hasta que se ejecutan, y este test impide que
vuelvan:

- T017 «Versiones»: en el Supervisor 2026.11.0, `POST /supervisor/update`
  solo respeta `version` en modo de desarrollo (`supervisor/api/supervisor.py`,
  `update`), así que `ha supervisor update --version …` no fija nada; y con
  `auto_update` desactivado, en cuanto hay un Supervisor más nuevo, la
  condición `supervisor_updated` bloquea instalar y actualizar add-ons,
  `ha store reload` y `ha core update` (`supervisor/jobs/decorator.py`). Los
  bloques de comandos no pueden pedir ninguna de las dos cosas, y si el texto
  ofrece ignorar la condición tiene que decir cómo deshacerlo.
- T018 «Conectar un cliente MCP»: por defecto la VM no se publica en internet
  (Tailscale Serve, solo el tailnet de pruebas). Funnel solo con un aviso de
  que publica un Hermes `admin` y con el comando que lo cierra, también en
  «Limpiar».
- T022 «Crear la VM» e «Instantáneas»: el arranque seguro se desactiva
  diciendo por qué; y nada de `virsh snapshot-create-as` sin `--disk-only`,
  que crea una instantánea interna que libvirt no admite con firmware UEFI.

Control negativo (014, T017, T018, T022): con el bloque de comandos de la
primera versión (`ha supervisor options --auto-update=false` y
`ha supervisor update --version 2026.11.0`) cae
`test_versiones_no_intenta_fijar_el_supervisor`; quitando el bloque de Serve
y dejando solo Funnel cae `test_por_defecto_sin_internet`; quitando el
`funnel … off` de «Limpiar» cae `test_funnel_se_cierra_al_limpiar`; con el
`virsh snapshot-create-as <vm> antes-tanda-1` de antes cae
`test_libvirt_sin_instantanea_interna`. Recuentos en el commit.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PROCEDIMIENTO = RAIZ / "docs" / "BANCO-SUPERVISOR.md"


def _seccion(texto: str, encabezado: str) -> str:
    """El cuerpo de la sección `## encabezado` hasta la siguiente `## `."""
    patron = re.compile(r"^## " + re.escape(encabezado) + r"\s*$(.*?)(?=^## |\Z)", re.M | re.S)
    m = patron.search(texto)
    assert m is not None, f"falta la sección «{encabezado}»"
    return m.group(1)


def _comandos(texto: str) -> list[str]:
    """Las líneas de los bloques de código (también los sangrados dentro de una
    lista), sin comentarios de cola."""
    lineas: list[str] = []
    for bloque in re.findall(r"^[ \t]*```[a-z]*\n(.*?)^[ \t]*```", texto, re.M | re.S):
        for linea in bloque.splitlines():
            linea = linea.split("  #", 1)[0].strip()
            if linea:
                lineas.append(linea)
    return lineas


class TestProcedimientoSupervisor(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.texto = PROCEDIMIENTO.read_text(encoding="utf-8")

    # ── T017: Versiones ────────────────────────────────────────────────────

    def test_versiones_no_intenta_fijar_el_supervisor(self) -> None:
        comandos = _comandos(_seccion(self.texto, "Versiones"))
        for linea in comandos:
            with self.subTest(linea=linea):
                self.assertNotRegex(
                    linea,
                    r"ha supervisor update\b.*--version",
                    "fuera del modo de desarrollo el Supervisor ignora --version",
                )
                self.assertNotRegex(
                    linea,
                    r"auto[-_]update[= ]+false",
                    "con auto_update desactivado, supervisor_updated bloquea add-ons y tienda",
                )
        # Core sí se fija; tiene que seguir habiendo un comando que lo haga.
        self.assertTrue(
            any(re.search(r"ha core update\b.*--version", l) for l in comandos),
            "falta fijar la versión de Core",
        )

    def test_versiones_explica_el_bloqueo_y_como_deshacerlo(self) -> None:
        seccion = _seccion(self.texto, "Versiones")
        for clave in ("supervisor_updated", "solo en la VM", "Nunca en la instalación real"):
            with self.subTest(clave=clave):
                self.assertIn(clave, seccion)
        if "ignore_conditions" in seccion:
            # Ofrecer la palanca sin decir cómo quitarla deja la VM, y a quien
            # copie el comando a otra instalación, sin la protección.
            self.assertTrue(
                '"ignore_conditions": []' in seccion or "jobs/reset" in seccion,
                "ignore_conditions sin cómo deshacerlo",
            )

    # ── T018: Conectar un cliente MCP ──────────────────────────────────────

    def test_por_defecto_sin_internet(self) -> None:
        seccion = _seccion(self.texto, "Conectar un cliente MCP")
        comandos = _comandos(seccion)
        serve = [i for i, l in enumerate(comandos) if re.search(r"tailscale serve\b.*8765", l)]
        funnel = [i for i, l in enumerate(comandos) if re.search(r"tailscale funnel\b.*8765", l)]
        self.assertTrue(serve, "falta publicar con `tailscale serve` (solo el tailnet)")
        if funnel:
            self.assertLess(serve[0], funnel[0], "Serve tiene que ser la forma por defecto")
        self.assertRegex(seccion, r"no se\s+publica en internet")
        self.assertRegex(seccion, r"tailnet de pruebas|tailnet aparte")

    def test_funnel_con_aviso_y_cierre(self) -> None:
        seccion = _seccion(self.texto, "Conectar un cliente MCP")
        comandos = _comandos(seccion)
        if not any(re.search(r"tailscale funnel\b.*8765", l) for l in comandos):
            return
        self.assertRegex(seccion, r"\*\*Aviso\.\*\*[^\n]*\n>[^\n]*`admin`", "Funnel sin aviso del rol admin")
        self.assertTrue(
            any(re.search(r"tailscale funnel --https=8443 off", l) for l in comandos),
            "Funnel sin el comando que lo cierra",
        )

    def test_funnel_se_cierra_al_limpiar(self) -> None:
        self.assertIn("tailscale funnel --https=8443 off", _seccion(self.texto, "Limpiar"))

    # ── T022: Crear la VM e Instantáneas ───────────────────────────────────

    def test_arranque_seguro_explicado(self) -> None:
        seccion = _seccion(self.texto, "Crear la VM")
        if "EnableSecureBoot Off" not in seccion:
            return
        self.assertIn("no está firmado", seccion, "falta por qué se desactiva el arranque seguro")
        self.assertRegex(seccion, r"Solo afecta al firmware de\s+esa VM")

    def test_libvirt_sin_instantanea_interna(self) -> None:
        for linea in _comandos(_seccion(self.texto, "Instantáneas")):
            if "snapshot-create-as" in linea:
                with self.subTest(linea=linea):
                    self.assertIn(
                        "--disk-only",
                        linea,
                        "una instantánea interna no se admite con firmware UEFI (pflash)",
                    )


if __name__ == "__main__":
    unittest.main()
