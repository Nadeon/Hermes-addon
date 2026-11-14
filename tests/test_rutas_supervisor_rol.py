"""Las rutas del Supervisor que usa Hermes caben en el rol `manager` (spec 014, FR-008, SC-006).

`hermes/config.yaml` pide `hassio_role: admin`. Bajarlo a `manager` es la duda
D-02 de la 008 y exige una prueba en vivo (`docs/BANCO-SUPERVISOR.md`). Lo que
sí se puede comprobar sin un Supervisor es lo que dice su código: cada ruta
que llama Hermes casa con alguno de los patrones que el Supervisor 2026.11.0
deja pasar a un add-on con rol `manager`. Si una ruta nueva solo pasara con
`admin`, este test cae nombrándola, y la ruta tiene que ir a
`EXCEPCIONES_ADMIN` con su motivo (y el comentario de `hassio_role` y la
casilla manual de la hoja de ruta, nombrarla).

Este test NO sustituye a la prueba en vivo: comprueba los patrones copiados,
no lo que hace un Supervisor real (otras comprobaciones, otra versión).

De dónde salen las rutas:

- las llamadas `*.sv_request(método, ruta)` y `*.sv_request_text(ruta)` del
  código de `hermes/src/hermes`, leídas con `ast` (literales y f-strings, con
  cada hueco sustituido por `x`);
- las que se llaman sin `sv_request`: el proxy de Core de `HAClient` y las
  sondas del arranque de `network.py`;
- las llamadas cuya ruta es una variable, declaradas con sus rutas posibles
  en `LLAMADAS_DECLARADAS`; una llamada así sin declarar hace caer el test;
- si existe la tabla de clasificación de la 011
  (`hermes/src/hermes/command_table.py`), sus entradas del Supervisor `read` y
  `confirm`.

Control negativo (014, T005): una llamada `sv_request("GET", "/auth/list")`
añadida en una tool hace caer `test_rutas_de_hermes_caben_en_manager`
nombrándola; quitar `(?!security)` del patrón de `manager` hace caer
`test_patrones_copiados_rechazan_lo_de_admin`; una llamada
`sv_request("GET", ruta)` con una variable hace caer
`test_toda_llamada_reconocida` con el fichero y la línea.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CODIGO = RAIZ / "hermes" / "src"

# ── Patrones copiados del Supervisor 2026.11.0 ─────────────────────────────
# Literales de `supervisor/api/middleware/security.py` (`_V1_PATTERNS`), con
# `RE_SLUG` de `supervisor/apps/const.py`. Si el Supervisor los cambia, se
# vuelven a copiar citando la versión nueva; no se «arreglan» aquí.
RE_SLUG = r"[-_.A-Za-z0-9]+"

_V1_FRONTEND_PATHS = (
    r"|/app/.*\.(?:js|gz|json|map|woff2)"
    r"|/(store/)?addons/" + RE_SLUG + r"/(logo|icon)"
)

API_BYPASS = re.compile(
    r"^(?:"
    r"|/addons/self/(?!security|update)[^/]+"
    r"|/addons/self/options/config"
    r"|/info"
    r"|/services.*"
    r"|/discovery.*"
    r"|/auth"
    r")$"
)

ROL_MANAGER = re.compile(
    r"^(?:"
    r"|/.+/info"
    r"|/addons(?:/" + RE_SLUG + r"/(?!security).+|/reload)?"
    r"|/audio/.+"
    r"|/auth/cache"
    r"|/available_updates"
    r"|/backups.*"
    r"|/cli/.+"
    r"|/core/.+"
    r"|/dns/.+"
    r"|/docker/.+"
    r"|/jobs/.+"
    r"|/hardware/.+"
    r"|/homeassistant/.+"
    r"|/host/.+"
    r"|/mounts.*"
    r"|/multicast/.+"
    r"|/network/.+"
    r"|/observer/.+"
    r"|/os/(?!datadisk/wipe|ssh/authorized_keys).+"
    r"|/refresh_updates"
    r"|/resolution/.+"
    r"|/security/.+"
    r"|/snapshots.*"
    r"|/store.*"
    r"|/supervisor/.+"
    r"|/time/.+"
    r")$"
)

NO_SECURITY_CHECK = re.compile(
    r"^(?:"
    r"|/homeassistant/api/.*"
    r"|/homeassistant/websocket"
    r"|/core/api/.*"
    r"|/core/websocket"
    r"|/supervisor/ping"
    r"|/ingress/[-_A-Za-z0-9]+/.*"
    + _V1_FRONTEND_PATHS
    + r")$"
)

# ── Rutas que no pasan por `sv_request` ─────────────────────────────────────
# `HAClient` (ha.py) habla con Core a través del proxy del Supervisor: REST en
# `/core/api/...` (una muestra basta, el patrón es `/core/api/.*`) y el
# WebSocket en `/core/api/websocket`.
RUTAS_DEL_PROXY_DE_CORE: tuple[str, ...] = ("/core/api/states", "/core/api/websocket")

# Sondas del arranque en `network.py`, con su propia sesión HTTP:
# `/supervisor/ping` para elegir la URL base y `/core/info` para esperar a Core.
RUTAS_DEL_ARRANQUE: tuple[str, ...] = ("/supervisor/ping", "/core/info")

# Llamadas cuya ruta no es un literal ni un f-string: (módulo, función) → las
# rutas que puede tomar, o "tabla de la 011" para las genéricas que leen la
# ruta de `command_table.SUPERVISOR`. Las rutas declaradas se comprueban como
# las demás.
LLAMADAS_DECLARADAS: dict[tuple[str, str], tuple[str, ...] | str] = {
    ("hermes.tools.addons", "sv_list_addons"): ("/addons", "/store/addons"),
    # La genérica del Supervisor de la 011 (todavía en su rama): sus rutas son
    # las claves de `command_table.SUPERVISOR`, que comprueba
    # `test_rutas_de_la_tabla_de_la_011` cuando el módulo existe.
    ("hermes.tools.generic_commands", "ejecutar_supervisor"): "tabla de la 011",
}

# Ruta → motivo por el que Hermes la necesita aunque solo pase con `admin`.
# Vacía con el código de la 1.2.0: todas caben en `manager`. Si se llena, el
# comentario de `hassio_role` y la casilla manual de la hoja de ruta la nombran.
EXCEPCIONES_ADMIN: dict[str, str] = {}

_METODOS = {"sv_request": 1, "sv_request_text": 0}  # método → posición de la ruta


def _admitida_por_manager(ruta: str) -> bool:
    # El mismo orden que `SecurityMiddleware`: sin comprobación, bypass, rol.
    return bool(
        NO_SECURITY_CHECK.match(ruta) or API_BYPASS.match(ruta) or ROL_MANAGER.match(ruta)
    )


def _ruta_de_fstring(nodo: ast.JoinedStr) -> str:
    partes = []
    for valor in nodo.values:
        if isinstance(valor, ast.Constant) and isinstance(valor.value, str):
            partes.append(valor.value)
        else:
            partes.append("x")
    return "".join(partes)


class _Llamada:
    def __init__(self, fichero: Path, linea: int, modulo: str, funcion: str, ruta: str | None):
        self.fichero = fichero
        self.linea = linea
        self.modulo = modulo
        self.funcion = funcion
        self.ruta = ruta  # None: no es un literal ni un f-string

    def donde(self) -> str:
        return f"{self.fichero.relative_to(RAIZ).as_posix()}:{self.linea} ({self.funcion})"


class _Extractor(ast.NodeVisitor):
    def __init__(self, fichero: Path, modulo: str) -> None:
        self.fichero = fichero
        self.modulo = modulo
        self.pila: list[str] = []
        self.llamadas: list[_Llamada] = []

    def _visitar_funcion(self, nodo: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.pila.append(nodo.name)
        self.generic_visit(nodo)
        self.pila.pop()

    visit_FunctionDef = _visitar_funcion
    visit_AsyncFunctionDef = _visitar_funcion

    def visit_Call(self, nodo: ast.Call) -> None:
        if isinstance(nodo.func, ast.Attribute) and nodo.func.attr in _METODOS:
            posicion = _METODOS[nodo.func.attr]
            arg: ast.expr | None = None
            if len(nodo.args) > posicion:
                arg = nodo.args[posicion]
            for kw in nodo.keywords:
                if kw.arg in ("path", "sv_path"):
                    arg = kw.value
            ruta: str | None = None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                ruta = arg.value
            elif isinstance(arg, ast.JoinedStr):
                ruta = _ruta_de_fstring(arg)
            funcion = self.pila[-1] if self.pila else "<módulo>"
            self.llamadas.append(_Llamada(self.fichero, nodo.lineno, self.modulo, funcion, ruta))
        self.generic_visit(nodo)


def _ficheros() -> list[Path]:
    return sorted((CODIGO / "hermes").rglob("*.py"))


def _modulo(fichero: Path) -> str:
    return ".".join(fichero.relative_to(CODIGO).with_suffix("").parts)


def _llamadas() -> list[_Llamada]:
    todas: list[_Llamada] = []
    for fichero in _ficheros():
        arbol = ast.parse(fichero.read_text(encoding="utf-8"), filename=str(fichero))
        extractor = _Extractor(fichero, _modulo(fichero))
        extractor.visit(arbol)
        todas.extend(extractor.llamadas)
    return todas


def _apariciones_en_el_texto() -> int:
    # Cuenta a ciegas, en el texto, las llamadas por atributo. Si el extractor
    # deja de ver alguna (otra forma de escribirla), los números no cuadran.
    patron = re.compile(r"\.sv_request(?:_text)?\s*\(")
    return sum(len(patron.findall(f.read_text(encoding="utf-8"))) for f in _ficheros())


def _rutas_de_la_tabla_de_la_011() -> list[str] | None:
    if importlib.util.find_spec("hermes.command_table") is None:
        return None
    tabla = importlib.import_module("hermes.command_table")
    # Formato de la 011: (método, ruta con `{…}`) → Entrada con `category`.
    rutas = []
    for (_metodo, ruta), entrada in tabla.SUPERVISOR.items():
        if entrada.category in ("read", "confirm"):
            rutas.append(re.sub(r"\{[^}]*\}", "x", ruta))
    return rutas


def _rutas_de_hermes() -> dict[str, str]:
    """Ruta → de dónde sale (para el mensaje de fallo)."""
    rutas: dict[str, str] = {}
    for llamada in _llamadas():
        if llamada.ruta is not None:
            rutas.setdefault(llamada.ruta, llamada.donde())
    for (modulo, funcion), declaradas in LLAMADAS_DECLARADAS.items():
        if isinstance(declaradas, tuple):
            for ruta in declaradas:
                rutas.setdefault(ruta, f"{modulo}.{funcion} (declarada)")
    for ruta in RUTAS_DEL_PROXY_DE_CORE:
        rutas.setdefault(ruta, "proxy de Core de HAClient")
    for ruta in RUTAS_DEL_ARRANQUE:
        rutas.setdefault(ruta, "arranque (network.py)")
    return rutas


class TestRutasSupervisorRol(unittest.TestCase):
    def test_patrones_copiados_rechazan_lo_de_admin(self) -> None:
        # Lo que solo da `admin` en 2026.11.0. Si alguien afloja un patrón
        # copiado, el resto del test dejaría de servir sin avisar.
        for ruta in (
            "/auth/list",
            "/auth/reset",
            "/addons/x/security",
            "/os/datadisk/wipe",
            "/ingress/panels",
        ):
            with self.subTest(ruta=ruta):
                self.assertFalse(_admitida_por_manager(ruta), f"{ruta} casa con un patrón")

    def test_patrones_copiados_aceptan_options_config(self) -> None:
        # Es el hecho que corrige el comentario de `hassio_role`.
        self.assertTrue(API_BYPASS.match("/addons/self/options/config"))

    def test_extractor_encuentra_las_rutas_conocidas(self) -> None:
        rutas = {ll.ruta for ll in _llamadas()}
        for ruta in (
            "/info",
            "/addons/x/info",
            "/store/addons/x/install",
            "/backups/x/restore/full",
            "/host/reboot",
            "/core/restart",
            "/jobs/x",
            "/addons/x/logs",
        ):
            with self.subTest(ruta=ruta):
                self.assertIn(ruta, rutas)

    def test_toda_llamada_reconocida(self) -> None:
        llamadas = _llamadas()
        self.assertEqual(
            len(llamadas),
            _apariciones_en_el_texto(),
            "hay llamadas a sv_request que el extractor no ve",
        )
        sin_leer = [
            ll.donde()
            for ll in llamadas
            if ll.ruta is None and (ll.modulo, ll.funcion) not in LLAMADAS_DECLARADAS
        ]
        self.assertEqual(
            sin_leer,
            [],
            "llamadas con una ruta que no se puede leer: declárala en LLAMADAS_DECLARADAS",
        )

    def test_rutas_de_hermes_caben_en_manager(self) -> None:
        fuera = {
            ruta: origen
            for ruta, origen in _rutas_de_hermes().items()
            if not _admitida_por_manager(ruta) and ruta not in EXCEPCIONES_ADMIN
        }
        self.assertEqual(fuera, {}, "rutas que solo pasan con admin (ver EXCEPCIONES_ADMIN)")

    def test_rutas_de_la_tabla_de_la_011(self) -> None:
        rutas = _rutas_de_la_tabla_de_la_011()
        if rutas is None:
            # La tabla de la 011 no está en esta rama: no hay nada que
            # comprobar. Cuando se integre, este test empieza a mirarla solo.
            return
        fuera = [r for r in rutas if not _admitida_por_manager(r) and r not in EXCEPCIONES_ADMIN]
        self.assertEqual(fuera, [], "entradas read/confirm del Supervisor fuera de manager")

    def test_excepciones_con_motivo(self) -> None:
        usadas = set(_rutas_de_hermes()) | set(_rutas_de_la_tabla_de_la_011() or [])
        for ruta, motivo in EXCEPCIONES_ADMIN.items():
            with self.subTest(ruta=ruta):
                self.assertTrue(motivo.strip(), "excepción sin motivo")
                self.assertIn(ruta, usadas, "excepción que ya no usa nadie")
                self.assertFalse(_admitida_por_manager(ruta), "ya cabe en manager: sobra")


if __name__ == "__main__":
    unittest.main()
