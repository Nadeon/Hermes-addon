"""Matriz de pruebas tool → entorno → resultado (spec 014, FR-002 a FR-005).

Invariante: `docs/HOJA-DE-RUTA.md` tiene, entre
`<!-- matriz-pruebas:inicio -->` y `<!-- matriz-pruebas:fin -->`, exactamente
una fila por cada tool que modifica del registro de producción (todas las
familias activas, sin `readOnlyHint`), y cada fila dice la verdad respecto a
los inventarios del banco de Core (`tests/banco/cobertura*.py`). Así ninguna
tool que modifica entra sin decir dónde se prueba contra el software real, y
la matriz no puede quedarse diciendo menos (o más) de lo que el banco ejecuta.

Los simuladores de la suite normal no son un entorno de la matriz: corren
siempre, para todas. Los entornos son el banco de Core (CI con HA Core real),
la VM con HAOS de `docs/BANCO-SUPERVISOR.md` y la instalación real.

Regla para las sub-features siguientes (contrato en
`specs/014-banco-de-pruebas-supervisor/contracts/matriz.md`): quien añade una
tool que modifica añade su fila en el mismo cambio. De Core: `banco de Core`, y
`ok` cuando su inventario la lista como probada. Del Supervisor o de ficheros:
`VM` y `pendiente`, y su línea en «Tandas de pruebas» del procedimiento. Quien
la prueba en la VM o en vivo cambia `pendiente` por `ok` (con versión de
Hermes y fecha en la nota) o `falla` (con la causa).

Los inventarios se descubren por convención de nombres (la de la 010 y la
028): `PROBADAS*` (conjunto), `FALLAN*`, `NO_EJECUTABLES*` y `FUERA_DEL_BANCO`
(diccionarios tool → motivo). Cualquier otra constante se ignora (`DOMINIOS_*`,
`MODULOS_*`, `XFAIL_*`, `PENDIENTES_*`, `HALLAZGOS_*`…). Un inventario con el
tipo equivocado hace caer el test: la convención no admite ambigüedad.

Control negativo (014, T008): borrar la fila de `sv_reboot_host`; `ok` sin nota
en `sv_restart_core`; `banco de Core` en `fs_write_file`; `pendiente` en
`ha_set_input_boolean`; un inventario temporal con `PROBADAS_*` como lista; y
el mismo con `sv_reboot_host` como probada. Cada uno pone en rojo su test,
nombrando la tool (o el módulo y la constante). Recuentos en el commit.
"""

from __future__ import annotations

import functools
import importlib
import pkgutil
import re
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

RAIZ = Path(__file__).resolve().parent.parent
HOJA_DE_RUTA = RAIZ / "docs" / "HOJA-DE-RUTA.md"
PROCEDIMIENTO = RAIZ / "docs" / "BANCO-SUPERVISOR.md"
BANCO = RAIZ / "tests" / "banco"

INICIO = "<!-- matriz-pruebas:inicio -->"
FIN = "<!-- matriz-pruebas:fin -->"
CABECERA = ("| Tool | Entorno | Resultado | Nota |", "|---|---|---|---|")

BANCO_DE_CORE = "banco de Core"
VM = "VM"
REAL = "instalación real"
ENTORNOS = (BANCO_DE_CORE, VM, REAL)
RESULTADOS = ("ok", "falla", "pendiente")

RE_TOOL = re.compile(r"^`([a-z][a-z0-9_]*)`$")
RE_VERSION = re.compile(r"\b\d+\.\d+\.\d+\b")
RE_FECHA = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

# Secciones obligatorias del procedimiento, en orden
# (contracts/procedimiento.md).
SECCIONES_DEL_PROCEDIMIENTO = (
    "Para qué sirve y qué no",
    "Versiones",
    "Crear la VM",
    "Instantáneas",
    "Instalar Hermes como add-on local",
    "Conectar un cliente MCP",
    "Tandas de pruebas",
    "Probar hassio_role: manager",
    "Pruebas manuales que se pueden hacer en la VM",
    "Anotar el resultado",
    "Limpiar",
)

# Texto que tiene que aparecer en alguna casilla de «Pruebas manuales
# pendientes»: SC-011 de la 008 (Supervisor real, rol, tools nuevas tras
# publicar) y las abiertas de CAP-035.
CLAVES_DE_CASILLAS = (
    "Matriz del Supervisor",
    "hassio_role: manager",
    "tras publicar",
    "sv_get_resolution",
    "CIMD con Claude Code",
    "Primer byte tras el proxy",
    "Clave `homeassistant`",
    "Funnel en el 8443",
    "fs_write_file",
    "trazas de un script",
)


# ── Registro de producción ─────────────────────────────────────────────────


@functools.cache
def _registro_de_produccion() -> dict[str, Any]:
    from hermes.__main__ import _build_mcp
    from hermes.config import HermesConfig

    # Como en tests/test_banco_cobertura.py: sin la clasificación automática
    # de `ha_call_service`, que programa una tarea en el bucle al registrarse.
    # No cambia qué tools se registran (todas las familias activas).
    mcp = _build_mcp(HermesConfig(call_service_auto_classify_dangerous=False), MagicMock())
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def _que_modifican() -> set[str]:
    return {
        nombre
        for nombre, tool in _registro_de_produccion().items()
        if not (tool.annotations is not None and tool.annotations.read_only_hint)
    }


# ── Inventarios del banco ──────────────────────────────────────────────────


class _Inventario:
    def __init__(self) -> None:
        self.probadas: dict[str, str] = {}  # tool → «módulo.CONSTANTE»
        self.fallan: dict[str, str] = {}
        self.no_ejecutables: dict[str, str] = {}
        self.fuera_del_banco: dict[str, str] = {}
        self.modulos: list[str] = []
        self.errores: list[str] = []


def _modulos_de_inventario() -> list[str]:
    return sorted(
        info.name for info in pkgutil.iter_modules([str(BANCO)]) if info.name.startswith("cobertura")
    )


def _inventarios() -> _Inventario:
    inv = _Inventario()
    for nombre in _modulos_de_inventario():
        modulo = importlib.import_module(f"tests.banco.{nombre}")
        inv.modulos.append(nombre)
        for constante, valor in vars(modulo).items():
            origen = f"tests/banco/{nombre}.py:{constante}"
            if constante.startswith("PROBADAS"):
                if not isinstance(valor, (set, frozenset)):
                    inv.errores.append(f"{origen} tendría que ser un conjunto")
                    continue
                destino = inv.probadas
            elif constante.startswith("FALLAN"):
                destino = inv.fallan
            elif constante.startswith("NO_EJECUTABLES"):
                destino = inv.no_ejecutables
            elif constante == "FUERA_DEL_BANCO":
                destino = inv.fuera_del_banco
            else:
                # DOMINIOS_*, MODULOS_*, XFAIL_*, PENDIENTES_*, HALLAZGOS_* y
                # demás auxiliares: no son inventario de resultado.
                continue
            if destino is not inv.probadas and not isinstance(valor, dict):
                inv.errores.append(f"{origen} tendría que ser un diccionario tool → motivo")
                continue
            for tool in valor:
                destino.setdefault(tool, origen)
    return inv


# ── Lectura de los documentos ──────────────────────────────────────────────


def _texto(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8")


def _lineas_de_la_matriz() -> list[str]:
    texto = _texto(HOJA_DE_RUTA)
    inicio = texto.index(INICIO) + len(INICIO)
    fin = texto.index(FIN)
    return [l.strip() for l in texto[inicio:fin].splitlines() if l.strip()]


def _filas() -> list[tuple[str, str, str, str]]:
    """(tool, entorno, resultado, nota) de cada fila bien formada."""
    filas = []
    for linea in _lineas_de_la_matriz()[2:]:
        celdas = _celdas(linea)
        if celdas is None:
            continue
        m = RE_TOOL.match(celdas[0])
        if m:
            filas.append((m.group(1), celdas[1], celdas[2], celdas[3]))
    return filas


def _celdas(linea: str) -> list[str] | None:
    if not (linea.startswith("|") and linea.endswith("|")):
        return None
    celdas = [c.strip() for c in linea[1:-1].split("|")]
    return celdas if len(celdas) == 4 else None


def _matriz() -> dict[str, tuple[str, str, str]]:
    return {tool: (entorno, resultado, nota) for tool, entorno, resultado, nota in _filas()}


def _seccion(texto: str, encabezado: str, nivel: int) -> str:
    """El cuerpo de la sección `encabezado` hasta el siguiente de nivel ≤ `nivel`."""
    lineas = texto.splitlines()
    marca = "#" * nivel + " " + encabezado
    inicio = next(i for i, l in enumerate(lineas) if l.strip() == marca)
    cuerpo = []
    for linea in lineas[inicio + 1 :]:
        m = re.match(r"^(#+) ", linea)
        if m and len(m.group(1)) <= nivel:
            break
        cuerpo.append(linea)
    return "\n".join(cuerpo)


def _casillas() -> list[str]:
    """Cada casilla de «Pruebas manuales pendientes», en una sola línea."""
    cuerpo = _seccion(_texto(HOJA_DE_RUTA), "Pruebas manuales pendientes", 3)
    casillas: list[str] = []
    for linea in cuerpo.splitlines():
        if re.match(r"^- \[[ x]\] ", linea):
            casillas.append(linea[6:].strip())
        elif casillas and linea.startswith("  ") and linea.strip():
            casillas[-1] += " " + linea.strip()
        elif not linea.strip() and casillas:
            casillas.append("")  # corta la continuación
    return [c for c in casillas if c]


class TestMatrizDePruebas(unittest.TestCase):
    def test_marcadores_y_cabecera(self) -> None:
        texto = _texto(HOJA_DE_RUTA)
        self.assertEqual(texto.count(INICIO), 1, "tiene que haber un marcador de inicio")
        self.assertEqual(texto.count(FIN), 1, "tiene que haber un marcador de fin")
        self.assertLess(texto.index(INICIO), texto.index(FIN), "marcadores al revés")
        self.assertEqual(tuple(_lineas_de_la_matriz()[:2]), CABECERA, "cabecera de la matriz")

    def test_filas_bien_formadas(self) -> None:
        malas = []
        for linea in _lineas_de_la_matriz()[2:]:
            celdas = _celdas(linea)
            if (
                celdas is None
                or not RE_TOOL.match(celdas[0])
                or celdas[1] not in ENTORNOS
                or celdas[2] not in RESULTADOS
            ):
                malas.append(linea)
        self.assertEqual(malas, [], "filas mal formadas (cuatro celdas, tool, entorno, resultado)")

    def test_sin_repetidas(self) -> None:
        vistas: set[str] = set()
        repetidas = sorted({t for t, *_ in _filas() if t in vistas or vistas.add(t)})
        self.assertEqual(repetidas, [], "tools con más de una fila")

    def test_orden_alfabetico(self) -> None:
        # Para que los conflictos al integrar sub-features sean de una línea.
        tools = [t for t, *_ in _filas()]
        self.assertEqual(tools, sorted(tools), "las filas van en orden alfabético")

    def test_una_fila_por_tool_que_modifica(self) -> None:
        en_la_matriz = set(_matriz())
        que_modifican = _que_modifican()
        self.assertEqual(
            sorted(que_modifican - en_la_matriz), [], "tools que modifican sin fila en la matriz"
        )
        self.assertEqual(
            sorted(en_la_matriz - que_modifican),
            [],
            "filas de tools que no existen o no modifican (tienen readOnlyHint)",
        )

    def test_sv_y_fs_en_la_vm(self) -> None:
        fuera = sorted(
            tool
            for tool, (entorno, _r, _n) in _matriz().items()
            if tool.startswith(("sv_", "fs_")) and entorno != VM
        )
        self.assertEqual(fuera, [], "las sv_* y fs_* que modifican se prueban en la VM")

    def test_inventarios_descubiertos(self) -> None:
        inv = _inventarios()
        self.assertIn("cobertura", inv.modulos, "falta el inventario de la 010")
        self.assertEqual(inv.errores, [], "inventarios con un tipo fuera de la convención")

    def test_coherente_con_los_inventarios(self) -> None:
        inv = _inventarios()
        matriz = _matriz()
        errores = []

        def fila(tool: str) -> tuple[str, str, str] | None:
            if tool not in matriz:
                errores.append(f"{tool}: está en un inventario y no tiene fila")
                return None
            return matriz[tool]

        for tool, origen in sorted(inv.probadas.items()):
            f = fila(tool)
            if f and (f[0], f[1]) != (BANCO_DE_CORE, "ok"):
                errores.append(f"{tool}: probada en {origen}, la fila tiene que decir banco de Core / ok")
        for tool, origen in sorted(inv.fallan.items()):
            f = fila(tool)
            if f and (f[0], f[1]) != (BANCO_DE_CORE, "falla"):
                errores.append(f"{tool}: falla en {origen}, la fila tiene que decir banco de Core / falla")
        for tool, origen in sorted(inv.no_ejecutables.items()):
            f = fila(tool)
            if f and f[0] == BANCO_DE_CORE:
                errores.append(f"{tool}: no ejecutable según {origen}, el entorno no puede ser banco de Core")
        for tool, origen in sorted(inv.fuera_del_banco.items()):
            f = fila(tool)
            if f and f[0] != VM:
                errores.append(f"{tool}: fuera del banco según {origen}, el entorno tiene que ser VM")
        en_algun_inventario = (
            set(inv.probadas) | set(inv.fallan) | set(inv.no_ejecutables) | set(inv.fuera_del_banco)
        )
        for tool, (entorno, resultado, _n) in sorted(matriz.items()):
            if tool.startswith("ha_") and tool not in en_algun_inventario:
                if (entorno, resultado) != (BANCO_DE_CORE, "pendiente"):
                    errores.append(
                        f"{tool}: de Core y en ningún inventario, la fila tiene que decir "
                        "banco de Core / pendiente"
                    )
        self.assertEqual(errores, [], "\n".join(errores))

    def test_ok_en_banco_solo_si_probada(self) -> None:
        probadas = set(_inventarios().probadas)
        sin_probar = sorted(
            tool
            for tool, (entorno, resultado, _n) in _matriz().items()
            if (entorno, resultado) == (BANCO_DE_CORE, "ok") and tool not in probadas
        )
        self.assertEqual(sin_probar, [], "ok en el banco sin estar en ningún PROBADAS*")

    def test_notas_obligatorias(self) -> None:
        errores = []
        for tool, (entorno, resultado, nota) in sorted(_matriz().items()):
            if resultado == "falla" and not nota:
                errores.append(f"{tool}: falla sin la causa en la nota")
            if resultado == "ok" and entorno in (VM, REAL):
                if not (RE_VERSION.search(nota) and RE_FECHA.search(nota)):
                    errores.append(f"{tool}: ok en {entorno} sin versión de Hermes y fecha en la nota")
        self.assertEqual(errores, [], "\n".join(errores))

    def test_hoja_de_ruta_enlaza_el_procedimiento(self) -> None:
        self.assertTrue(PROCEDIMIENTO.is_file(), "falta docs/BANCO-SUPERVISOR.md")
        self.assertRegex(
            _texto(HOJA_DE_RUTA),
            r"\]\((?:\./)?BANCO-SUPERVISOR\.md(?:#[^)]*)?\)",
            "la hoja de ruta no enlaza el procedimiento",
        )

    def test_casillas_manuales(self) -> None:
        casillas = _casillas()
        for clave in CLAVES_DE_CASILLAS:
            with self.subTest(clave=clave):
                self.assertTrue(any(clave in c for c in casillas), f"falta la casilla de «{clave}»")
        for casilla in casillas:
            with self.subTest(casilla=casilla[:60]):
                m = re.match(r"^\(([^)]*)\)", casilla)
                self.assertTrue(
                    m and re.search(r"VM|instalación real|cliente", m.group(1)),
                    "la casilla no empieza por su entorno entre paréntesis",
                )
        rol = [c for c in casillas if "hassio_role: manager" in c]
        for casilla in rol:
            self.assertNotIn("bashio::config", casilla, "Hermes no usa bashio::config")

    def test_procedimiento_con_sus_secciones(self) -> None:
        encabezados = re.findall(r"^## (.+?)\s*$", _texto(PROCEDIMIENTO), re.MULTILINE)
        self.assertEqual(tuple(encabezados), SECCIONES_DEL_PROCEDIMIENTO)

    def test_cada_tool_de_la_vm_en_el_procedimiento(self) -> None:
        tandas = _seccion(_texto(PROCEDIMIENTO), "Tandas de pruebas", 2)
        nombradas = set(re.findall(r"`([a-z][a-z0-9_]*)`", tandas))
        faltan = sorted(
            tool
            for tool, (entorno, _r, _n) in _matriz().items()
            if entorno == VM and tool not in nombradas
        )
        self.assertEqual(faltan, [], "tools de la VM sin su apartado en «Tandas de pruebas»")


if __name__ == "__main__":
    unittest.main()
