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

Límites del extractor (convergencia, T019 y T020):

- Un hueco de f-string puede ocupar justo el segmento que decide el permiso
  (`f"/addons/self/{accion}"` con `accion = "security"`). Por eso cada
  f-string se prueba también con cada hueco sustituido por los segmentos que
  solo da `admin` (`SONDAS_DE_HUECO`), y tiene que seguir cabiendo en
  `manager`; si no, el test cae (fail-closed) salvo que la plantilla esté en
  `HUECOS_DECLARADOS` con su motivo.
- El extractor solo ve `X.sv_request(...)` y `X.sv_request_text(...)`. Una
  llamada por alias (`llamar = cliente.sv_request`), por `functools.partial`
  o por `getattr(cliente, "sv_request")` no la vería. En vez de seguir esos
  caminos, el test los prohíbe en `hermes/src/hermes`: cualquier atributo
  `sv_request*` que no sea la función de una llamada y cualquier cadena
  `"sv_request"`/`"sv_request_text"` lo hacen caer con el fichero y la línea.
  Un nombre construido a trozos (`"sv_" + "request"`) queda fuera de su
  alcance.

Control negativo (014, T005): una llamada `sv_request("GET", "/auth/list")`
añadida en una tool hace caer `test_rutas_de_hermes_caben_en_manager`
nombrándola; quitar `(?!security)` del patrón de `manager` hace caer
`test_patrones_copiados_rechazan_lo_de_admin`; una llamada
`sv_request("GET", ruta)` con una variable hace caer
`test_toda_llamada_reconocida` con el fichero y la línea.

Control negativo (014, T019): `accion = "security"` y
`sv_request("POST", f"/addons/self/{accion}")` en una tool hacen caer
`test_huecos_de_fstring_no_deciden_el_permiso` nombrando la plantilla, la
sonda y la línea; la misma plantilla en `HUECOS_DECLARADOS` con su motivo lo
deja pasar. (T020): `llamar = ha_client.sv_request` y
`getattr(ha_client, "sv_request")` hacen caer
`test_sin_llamadas_por_alias_ni_getattr` con el fichero y la línea.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import re
import unittest
from pathlib import Path

# Los plugins con log de la 013, de su propia lista: si se añade uno, sus
# rutas de log entran solas en LLAMADAS_DECLARADAS.
from hermes.tools._logs import PLUGINS as _PLUGINS_CON_LOG

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
    # Spec 013: las rutas de log se construyen en `tools/_logs.py`
    # (`ruta_de_log`, `ruta_de_plugin`, `ruta_de_host`) con el slug, el plugin,
    # el arranque y el identificador ya validados; aquí, cada forma posible
    # con sus huecos como `x`.
    ("hermes.tools.addons", "sv_get_addon_logs"): (
        "/addons/x/logs",
        "/addons/x/logs/latest",
        "/addons/x/logs/boots/x",
    ),
    ("hermes.tools.system_logs", "_leer_log"): tuple(
        f"/{base}/logs{cola}"
        for base in ("core", "supervisor", *_PLUGINS_CON_LOG)
        for cola in ("", "/latest", "/boots/x")
    )
    + (
        "/host/logs",
        "/host/logs/boots/x",
        "/host/logs/identifiers/x",
        "/host/logs/boots/x/identifiers/x",
    ),
    ("hermes.tools.system_logs", "sv_list_host_log_identifiers"): ("/host/logs/identifiers",),
    ("hermes.tools.system_logs", "sv_list_boots"): ("/host/logs/boots",),
    ("hermes.tools.host_system", "_leer"): (
        "/host/services",
        "/host/disks/x/usage",
        "/os/info",
        "/os/config/swap",
        "/os/datadisk/list",
    ),
    # Spec 032, tramo 1: lecturas de las vistas previas y escrituras del
    # control del host, con la ruta como constante en cada tool.
    ("hermes.tools.host_control", "_leer"): ("/host/info", "/os/config/swap", "/os/info"),
    ("hermes.tools.host_control", "_enviar"): (
        "/host/shutdown",
        "/host/options",
        "/os/config/swap",
        "/os/boot-slot",
    ),
    # Spec 032, tramo 2: las escrituras de la red del host; la ruta es un
    # f-string con la interfaz (validada como nombre de interfaz) y el id
    # (entero de 1 a 4094).
    ("hermes.tools.host_network", "_enviar"): (
        "/network/interface/x/update",
        "/network/interface/x/vlan/1",
    ),
    # La genérica del Supervisor de la 011 (todavía en su rama): sus rutas son
    # las claves de `command_table.SUPERVISOR`, que comprueba
    # `test_rutas_de_la_tabla_de_la_011` cuando el módulo existe.
    ("hermes.tools.generic_commands", "ejecutar_supervisor"): "tabla de la 011",
}

# Ruta → motivo por el que Hermes la necesita aunque solo pase con `admin`.
# Vacía con el código de la 1.2.0: todas caben en `manager`. Si se llena, el
# comentario de `hassio_role` y la casilla manual de la hoja de ruta la nombran.
EXCEPCIONES_ADMIN: dict[str, str] = {}

# Segmentos que solo da `admin` en 2026.11.0 (lo que excluyen los patrones
# copiados) más `self`, que es el que decide `api_bypass`. Cada hueco de un
# f-string se sustituye por cada uno: si alguna sustitución deja la ruta fuera
# de `manager`, el hueco decide el permiso y el test no puede saber qué valor
# tomará, así que cae.
SONDAS_DE_HUECO: tuple[str, ...] = (
    "security",
    "update",
    "list",
    "reset",
    "datadisk/wipe",
    "ssh/authorized_keys",
    "panels",
    "self",
)

# Plantilla de f-string (huecos como `{}`) → motivo por el que su hueco no
# puede tomar un valor solo-admin (por ejemplo, porque se valida antes contra
# una lista cerrada). Vacía con el código de la 1.2.0.
HUECOS_DECLARADOS: dict[str, str] = {}

_METODOS = {"sv_request": 1, "sv_request_text": 0}  # método → posición de la ruta


def _admitida_por_manager(ruta: str) -> bool:
    # El mismo orden que `SecurityMiddleware`: sin comprobación, bypass, rol.
    return bool(
        NO_SECURITY_CHECK.match(ruta) or API_BYPASS.match(ruta) or ROL_MANAGER.match(ruta)
    )


def _partes_de_fstring(nodo: ast.JoinedStr) -> list[str | None]:
    """Los trozos literales del f-string; `None` en cada hueco."""
    return [
        valor.value if isinstance(valor, ast.Constant) and isinstance(valor.value, str) else None
        for valor in nodo.values
    ]


def _rellenar(partes: list[str | None], hueco: int | None = None, valor: str = "x") -> str:
    """La ruta con el hueco número `hueco` como `valor` y los demás como `x`."""
    salida = []
    n = 0
    for parte in partes:
        if parte is None:
            salida.append(valor if n == hueco else "x")
            n += 1
        else:
            salida.append(parte)
    return "".join(salida)


def _plantilla(partes: list[str | None]) -> str:
    return "".join("{}" if p is None else p for p in partes)


class _Llamada:
    def __init__(
        self,
        fichero: Path,
        linea: int,
        modulo: str,
        funcion: str,
        ruta: str | None,
        partes: list[str | None] | None = None,
    ):
        self.fichero = fichero
        self.linea = linea
        self.modulo = modulo
        self.funcion = funcion
        self.ruta = ruta  # None: no es un literal ni un f-string
        self.partes = partes  # solo en los f-strings: trozos, None en los huecos

    def donde(self) -> str:
        return f"{self.fichero.relative_to(RAIZ).as_posix()}:{self.linea} ({self.funcion})"


class _Extractor(ast.NodeVisitor):
    def __init__(self, fichero: Path, modulo: str) -> None:
        self.fichero = fichero
        self.modulo = modulo
        self.pila: list[str] = []
        self.llamadas: list[_Llamada] = []
        # Usos de `sv_request*` que no son una llamada directa: (línea, qué).
        self.prohibidos: list[tuple[int, str]] = []
        self._funciones_de_llamada: set[int] = set()

    def _visitar_funcion(self, nodo: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.pila.append(nodo.name)
        self.generic_visit(nodo)
        self.pila.pop()

    visit_FunctionDef = _visitar_funcion
    visit_AsyncFunctionDef = _visitar_funcion

    def visit_Attribute(self, nodo: ast.Attribute) -> None:
        # `visit_Call` marca antes la función de cada llamada directa; un
        # atributo `sv_request*` sin marcar es un alias o un `partial`.
        if nodo.attr in _METODOS and id(nodo) not in self._funciones_de_llamada:
            self.prohibidos.append((nodo.lineno, f"atributo .{nodo.attr} sin llamarlo (alias)"))
        self.generic_visit(nodo)

    def visit_Constant(self, nodo: ast.Constant) -> None:
        if isinstance(nodo.value, str) and nodo.value in _METODOS:
            self.prohibidos.append((nodo.lineno, f"cadena {nodo.value!r} (getattr)"))

    def visit_Call(self, nodo: ast.Call) -> None:
        if isinstance(nodo.func, ast.Attribute) and nodo.func.attr in _METODOS:
            self._funciones_de_llamada.add(id(nodo.func))
            posicion = _METODOS[nodo.func.attr]
            arg: ast.expr | None = None
            if len(nodo.args) > posicion:
                arg = nodo.args[posicion]
            for kw in nodo.keywords:
                if kw.arg in ("path", "sv_path"):
                    arg = kw.value
            ruta: str | None = None
            partes: list[str | None] | None = None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                ruta = arg.value
            elif isinstance(arg, ast.JoinedStr):
                partes = _partes_de_fstring(arg)
                ruta = _rellenar(partes)
            funcion = self.pila[-1] if self.pila else "<módulo>"
            self.llamadas.append(
                _Llamada(self.fichero, nodo.lineno, self.modulo, funcion, ruta, partes)
            )
        self.generic_visit(nodo)


def _ficheros() -> list[Path]:
    return sorted((CODIGO / "hermes").rglob("*.py"))


def _modulo(fichero: Path) -> str:
    return ".".join(fichero.relative_to(CODIGO).with_suffix("").parts)


def _extractores() -> list[_Extractor]:
    extractores = []
    for fichero in _ficheros():
        arbol = ast.parse(fichero.read_text(encoding="utf-8"), filename=str(fichero))
        extractor = _Extractor(fichero, _modulo(fichero))
        extractor.visit(arbol)
        extractores.append(extractor)
    return extractores


def _llamadas() -> list[_Llamada]:
    return [ll for ex in _extractores() for ll in ex.llamadas]


def _huecos_que_deciden() -> list[str]:
    """F-strings cuyo hueco, con un valor solo-admin, saca la ruta de `manager`."""
    fuera = []
    for llamada in _llamadas():
        if llamada.partes is None:
            continue
        plantilla = _plantilla(llamada.partes)
        if plantilla in HUECOS_DECLARADOS:
            continue
        for hueco in range(sum(p is None for p in llamada.partes)):
            for sonda in SONDAS_DE_HUECO:
                ruta = _rellenar(llamada.partes, hueco, sonda)
                if not _admitida_por_manager(ruta) and ruta not in EXCEPCIONES_ADMIN:
                    fuera.append(
                        f"{plantilla}, hueco {hueco + 1} = {sonda!r} → {ruta} ({llamada.donde()})"
                    )
    return fuera


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
            # `/addons/x/logs` ya no: desde la 013 la ruta se construye en
            # `tools/_logs.py` y está en LLAMADAS_DECLARADAS.
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

    def test_huecos_de_fstring_no_deciden_el_permiso(self) -> None:
        self.assertEqual(
            _huecos_que_deciden(),
            [],
            "un hueco de f-string ocupa el segmento que decide el permiso: "
            "escribe ese segmento literal o declara la plantilla en HUECOS_DECLARADOS",
        )

    def test_huecos_declarados_con_motivo(self) -> None:
        plantillas = {_plantilla(ll.partes) for ll in _llamadas() if ll.partes is not None}
        for plantilla, motivo in HUECOS_DECLARADOS.items():
            with self.subTest(plantilla=plantilla):
                self.assertTrue(motivo.strip(), "declaración sin motivo")
                self.assertIn(plantilla, plantillas, "declaración que ya no usa nadie")

    def test_las_sondas_sacan_de_manager(self) -> None:
        # Sin esto, unas sondas inofensivas harían pasar siempre el test de
        # los huecos. Cada plantilla de aquí cabe en `manager` con `x` y deja
        # de caber con su sonda (la primera es la ruta sintética de la
        # revisión).
        for partes, sonda in (
            (["/addons/self/", None], "security"),
            # `/addons/self/update` no: lo excluye `api_bypass`, pero el
            # patrón de `manager` (`/addons/<slug>/(?!security).+`) lo admite.
            (["/auth/", None], "list"),
            (["/os/", None], "datadisk/wipe"),
            (["/os/", None], "ssh/authorized_keys"),
            (["/ingress/", None], "panels"),
        ):
            with self.subTest(plantilla=_plantilla(partes), sonda=sonda):
                self.assertIn(sonda, SONDAS_DE_HUECO)
                self.assertFalse(_admitida_por_manager(_rellenar(partes, 0, sonda)))

    def test_sin_llamadas_por_alias_ni_getattr(self) -> None:
        prohibidos = [
            f"{ex.fichero.relative_to(RAIZ).as_posix()}:{linea}: {que}"
            for ex in _extractores()
            for linea, que in ex.prohibidos
        ]
        self.assertEqual(
            prohibidos,
            [],
            "sv_request por alias o getattr: el extractor no ve su ruta; llámalo directamente",
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
