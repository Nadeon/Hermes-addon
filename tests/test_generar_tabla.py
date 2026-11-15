"""Generador de la tabla de comandos (spec 011, FR-002, FR-007; T009).

El generador crea `command_table.py` la primera vez aplicando las reglas de
research R-4 y, en versiones siguientes, conserva lo revisado a mano, añade lo
nuevo como `deny` «sin revisar» y quita lo que desaparece. Si conservara una
entrada sin mirar el inventario, un comando que HA ya no tiene seguiría
clasificado; si pisara una entrada revisada, regenerar desharía decisiones de
seguridad. Se prueba con inventarios pequeños de `tests/fixtures/inventario/`
(una fila por caso de R-4; comandos ficticios `demo/*`).

Control negativo (T009/T016 f), con recuentos en el commit:
- conservar las entradas de la tabla previa sin mirar si siguen en el
  inventario → cae `test_fila_desaparecida_se_quita_y_se_lista`.
- clasificar la clase C por verbo en vez de `deny` → cae `test_clase_c`.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from scripts.inventario import generar_tabla as gt

_RAIZ = pathlib.Path(__file__).resolve().parents[1]
_FIXTURES = _RAIZ / "tests" / "fixtures" / "inventario"


def _importar(ruta: pathlib.Path):
    nombre = f"_tabla_generada_{abs(hash(ruta))}"
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    try:
        spec.loader.exec_module(modulo)
    finally:
        sys.modules.pop(nombre, None)
    return modulo


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.core = self.dir / "core-ws.tsv"
        self.sv = self.dir / "supervisor-rutas.tsv"
        shutil.copy(_FIXTURES / "core-ws.tsv", self.core)
        shutil.copy(_FIXTURES / "supervisor-rutas.tsv", self.sv)
        self.salida = self.dir / "command_table.py"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _generar(self, **kw):
        kw.setdefault("ha_core", "2026.11.1")
        kw.setdefault("supervisor", "2026.11.0")
        return gt.generar(self.core, self.sv, self.salida, **kw)

    def _tabla(self):
        return _importar(self.salida)


class TestPrimeraGeneracion(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.resultado = self._generar()
        self.t = self._tabla()

    def test_versiones(self) -> None:
        self.assertEqual(self.t.TABLE_HA_CORE, "2026.11.1")
        self.assertEqual(self.t.TABLE_SUPERVISOR, "2026.11.0")

    def test_una_entrada_por_fila(self) -> None:
        self.assertEqual(len(self.t.CORE_WS), 13)
        self.assertEqual(len(self.t.SUPERVISOR), 11)

    def test_cubierto_con_tool(self) -> None:
        e = self.t.CORE_WS["lovelace/config/save"]
        self.assertEqual((e.category, e.tool, e.family),
                         ("dedicated", "ha_save_lovelace_dashboard", "lovelace"))
        e = self.t.SUPERVISOR[("GET", "/addons")]
        self.assertEqual((e.category, e.tool, e.family),
                         ("dedicated", "sv_list_addons", "supervisor"))

    def test_cubierto_por_accion_generica(self) -> None:
        e = self.t.CORE_WS["calendar/event/create"]
        self.assertEqual((e.category, e.tool, e.family),
                         ("dedicated", "ha_call_service", "services"))

    def test_cubierto_sin_tool_en_el_mapa(self) -> None:
        e = self.t.CORE_WS["demo/cubierto_sin_tool"]
        self.assertEqual(e.category, "deny")
        self.assertIn("sin revisar", e.reason)

    def test_uso_interno(self) -> None:
        e = self.t.CORE_WS["get_config"]
        self.assertEqual((e.category, e.reason), ("deny", "uso interno de Hermes"))

    def test_clase_b_y_d_con_el_motivo_de_la_nota(self) -> None:
        e = self.t.CORE_WS["demo/frontend"]
        self.assertEqual(e.category, "deny")
        self.assertIn("datos internos del frontend", e.reason)
        e = self.t.CORE_WS["demo/python"]
        self.assertIn("ejecuta Python arbitrario", e.reason)
        e = self.t.SUPERVISOR[("GET", "/addons/{app}/logs/follow")]
        self.assertEqual(e.category, "deny")
        self.assertIn("Streaming", e.reason)
        self.assertFalse(e.reason.startswith("No "))
        e = self.t.SUPERVISOR[("POST", "/backups/freeze")]
        self.assertIn("Congela Core", e.reason)

    def test_clase_a_via_dedicada(self) -> None:
        casos = {
            "demo/via_d": "012",    # CAP-041, D
            "demo/via_dt": "021",   # CAP-053, D+T
            "demo/via_dx": "012",   # CAP-040, D+X (012 y 017: la validación es de 012)
        }
        for comando, spec in casos.items():
            with self.subTest(comando=comando):
                e = self.t.CORE_WS[comando]
                self.assertEqual(
                    (e.category, e.reason),
                    ("deny", f"pendiente de tool dedicada (spec {spec})"))
        # Era el ejemplo de «spec 032»; desde su tramo 1 la tool existe y la
        # fila está en el mapa: dedicada (la regla del mapa va antes).
        e = self.t.SUPERVISOR[("POST", "/host/shutdown")]
        self.assertEqual((e.category, e.tool, e.family),
                         ("dedicated", "sv_shutdown_host", "host_control"))
        # CAP-087 se reparte: la lectura es de 013 y la escritura de 022.
        self.assertEqual(self.t.SUPERVISOR[("GET", "/jobs/info")].reason,
                         "pendiente de tool dedicada (spec 013)")
        self.assertEqual(self.t.SUPERVISOR[("POST", "/resolution/healthcheck")].reason,
                         "pendiente de tool dedicada (spec 022)")

    def test_clase_a_via_tabla_por_verbo_y_metodo(self) -> None:
        self.assertEqual(self.t.CORE_WS["demo/item/list"].category, "read")
        self.assertEqual(self.t.CORE_WS["demo/item/create"].category, "confirm")
        self.assertEqual(self.t.SUPERVISOR[("GET", "/dns/info")].category, "read")
        self.assertEqual(self.t.SUPERVISOR[("POST", "/dns/options")].category, "confirm")
        # Una suscripción no se ejecuta por la genérica hasta revisarla.
        self.assertEqual(self.t.CORE_WS["demo/item/subscribe"].category, "deny")
        for e in (self.t.CORE_WS["demo/item/list"], self.t.CORE_WS["demo/item/create"],
                  self.t.CORE_WS["demo/item/subscribe"]):
            self.assertIn(gt.PROVISIONAL, e.reason)
            self.assertEqual(e.cap, "CAP-066")
            self.assertEqual(e.family, "generic_commands")

    def test_clase_c(self) -> None:
        e = self.t.CORE_WS["demo/radio/reset"]
        self.assertEqual((e.category, e.reason, e.cap),
                         ("deny", "pendiente de revisión (spec 025)", "CAP-100"))

    def test_proxy_de_core_siempre_deny(self) -> None:
        # Prevalece sobre «cubierto» y sobre la clase B.
        for clave in (("GET", "/core/api/{path}"), ("GET", "/homeassistant/api/stream")):
            with self.subTest(clave=clave):
                e = self.t.SUPERVISOR[clave]
                self.assertEqual(e.category, "deny")
                self.assertIn("proxy de Core", e.reason)

    def test_fila_sin_clase(self) -> None:
        e = self.t.SUPERVISOR[("GET", "/ruta/sin/clase")]
        self.assertEqual(e.category, "deny")
        self.assertIn("sin revisar", e.reason)

    def test_resultado_de_la_primera_vez(self) -> None:
        self.assertEqual(len(self.resultado.nuevas), 24)
        self.assertEqual(self.resultado.quitadas, [])


class TestClaseAConToolDedicada(_Base):
    """Un solo mecanismo para todas las sub-features (specs 012, 013 y 029;
    research R-7): una fila A de vía D cuya clave ya tiene tool dedicada en
    `_DEDICADAS_INICIALES` sale `dedicated`, con la familia de su tool, en la
    primera generación, con el mismo constructor que una fila «cubierto»; y
    una fila «cubierto» por una acción que ya tiene dedicada no se anuncia
    como «(acción de HA)». Si el generador aplicara antes la regla
    «pendiente», una tabla regenerada desde cero desharía el paso a
    `dedicated` de cada sub-feature.

    Control negativo (T018 g de la 012): quitar la consulta del mapa para la
    clase A en `_clasificar` → caen `test_fila_a_de_via_d_en_el_mapa`
    («pendiente de tool dedicada (spec 012)»),
    `test_clase_a_via_dedicada_con_tool_en_el_mapa` y
    `test_desde_cero_igual_que_la_tabla_real`.
    """

    def setUp(self) -> None:
        super().setUp()
        filas = [
            ("system_log/list", "system_log", "homeassistant/components/system_log/__init__.py",
             "no", "A", "Log del sistema y niveles de log", "CAP-041"),
            ("logger/integration_log_level", "logger",
             "homeassistant/components/logger/websocket_api.py",
             "accion-generica", "cubierto", "logger.set_level", ""),
        ]
        with self.core.open("a", encoding="utf-8", newline="") as f:
            for fila in filas:
                f.write(chr(9).join(fila) + chr(10))
        self._generar()
        self.t = self._tabla()

    def test_fila_a_de_via_d_en_el_mapa(self) -> None:
        e = self.t.CORE_WS["system_log/list"]
        self.assertEqual(
            (e.category, e.reason, e.family, e.tool, e.cap),
            ("dedicated", "cubierto por ha_list_system_log", "core_diagnostics",
             "ha_list_system_log", "CAP-041"))
        # La de vía D que no está en el mapa sigue pendiente.
        self.assertEqual(self.t.CORE_WS["demo/via_d"].reason,
                         "pendiente de tool dedicada (spec 012)")

    def test_cubierto_por_accion_con_dedicada(self) -> None:
        e = self.t.CORE_WS["logger/integration_log_level"]
        self.assertEqual(
            (e.category, e.reason, e.family, e.tool, e.cap),
            ("dedicated", "cubierto por ha_set_log_level", "core_diagnostics",
             "ha_set_log_level", None))
        # La que sí cubre la acción genérica lo sigue diciendo.
        self.assertIn("(acción de HA)", self.t.CORE_WS["calendar/event/create"].reason)

    def test_clase_a_via_dedicada_con_tool_en_el_mapa(self) -> None:
        """Spec 029, T002 (FR-016): con el mapa parcheado, la fila sale
        `dedicated` con la familia de su tool aunque esta sea de otra familia
        que la de la sub-feature (aquí, una genérica). Control negativo
        comprobado: sin la consulta al mapa en la rama de la clase A → cae
        (sale «pendiente de tool dedicada (spec 012)»)."""
        with mock.patch.dict(gt._DEDICADAS_INICIALES, {"demo/via_d": "ha_read_ws_command"}):
            self.salida.unlink()
            self._generar()
        e = self._tabla().CORE_WS["demo/via_d"]
        self.assertEqual(
            (e.category, e.reason, e.family, e.tool, e.cap),
            ("dedicated", "cubierto por ha_read_ws_command", "generic_commands",
             "ha_read_ws_command", "CAP-041"))
        # Las demás filas A de vía D, sin clave en el mapa, siguen pendientes.
        self.assertEqual(self._tabla().CORE_WS["demo/via_dt"].reason,
                         "pendiente de tool dedicada (spec 021)")

    def test_subscribe_trigger_es_clase_a(self) -> None:
        """Spec 017, T045 (research R-13): la fila de `subscribe_trigger` del
        inventario real es clase A con CAP-038 (reclasificada desde B, como
        proponía la research de la 008) y la generación desde cero la saca
        `dedicated` hacia `ha_wait_for_trigger`.

        Control negativo (T054, 8), comprobado y restaurado: la fila de vuelta
        a clase B → cae este test (y la generación desde cero da `deny`)."""
        inventario = _RAIZ / "specs" / "008-cobertura-total" / "inventario"
        fila = next(f for f in gt._leer_tsv(inventario / "core-ws.tsv")
                    if f["comando"] == "subscribe_trigger")
        self.assertEqual((fila["clase"], fila["cap"]), ("A", "CAP-038"))
        self.salida.unlink(missing_ok=True)
        gt.generar(inventario / "core-ws.tsv", inventario / "supervisor-rutas.tsv",
                   self.salida, ha_core="2026.11.1", supervisor="2026.11.0")
        e = self._tabla().CORE_WS["subscribe_trigger"]
        self.assertEqual(
            (e.category, e.family, e.tool, e.cap),
            ("dedicated", "automation_assist", "ha_wait_for_trigger", "CAP-038"))

    def test_desde_cero_igual_que_la_tabla_real(self) -> None:
        """Integración de la 012: con los inventarios reales, la generación
        desde cero da la MISMA entrada que la tabla revisada en cada fila de
        clase A que la tabla tiene como `dedicated` (las de la 012, la 013 y
        la 029), y una fila A del mapa nunca sale de otra forma. Una
        sub-feature que pase una fila A a `dedicated` sin añadirla al mapa (o
        al revés) cae aquí nombrándola. Las filas «cubierto» no entran: varias
        se revisaron a mano después de la primera generación.

        Control negativo comprobado: quitar del mapa `system_log/list` (012),
        `("GET", "/core/logs")` (013) o `manifest/get` (029) → cae nombrando
        cada una."""
        from hermes import command_table as real

        inventario = _RAIZ / "specs" / "008-cobertura-total" / "inventario"
        self.salida.unlink(missing_ok=True)
        gt.generar(inventario / "core-ws.tsv", inventario / "supervisor-rutas.tsv",
                   self.salida, ha_core="2026.11.1", supervisor="2026.11.0")
        cero = self._tabla()
        clases = {
            **{f["comando"]: f["clase"]
               for f in gt._leer_tsv(inventario / "core-ws.tsv")},
            **{(f["metodo"], f["ruta"]): f["clase"]
               for f in gt._leer_tsv(inventario / "supervisor-rutas.tsv")},
        }

        def campos(e):
            return (e.category, e.reason, e.family, e.tool, e.cap)

        malas = []
        n = 0
        for nombre in ("CORE_WS", "SUPERVISOR"):
            generada, revisada = getattr(cero, nombre), getattr(real, nombre)
            for k, e in revisada.items():
                if not clases[k].startswith("A"):
                    continue
                en_mapa = isinstance(gt._DEDICADAS_INICIALES.get(k), str)
                if e.category != "dedicated" and not en_mapa:
                    continue
                n += 1
                if campos(generada[k]) != campos(e):
                    malas.append(f"{k}: desde cero {campos(generada[k])}, tabla {campos(e)}")
        self.assertEqual(malas, [], "\n".join(malas))
        # 9 de la 012 menos `logger/integration_log_level` (cubierto), 28 de la
        # 013, 9 de la 029 y, desde la integración de la 019, sus 9 rutas de
        # CAP-083 (`/mounts` y `/backups/info|options|reload`), que entran en
        # el mapa del generador: si baja, el test ha dejado de mirarlas. Desde
        # la integración de la 015, también sus 6 filas A (`/available_updates`,
        # `/reload_updates`, `/core/update`, `/os/update`, `/supervisor/update`
        # y `update/release_notes`). Desde la integración de la 030, sus 15
        # rutas (7 de repositorios y recarga, 8 de fichas, versiones,
        # validación y reconstrucción). Desde la integración de la 032, sus 4
        # rutas de CAP-086 (tramo 1) y sus 3 de CAP-090 (tramo 2).
        self.assertGreaterEqual(n, 82)

    def test_desde_cero_las_de_la_030_con_su_motivo(self) -> None:
        """Integración de la 030: las rutas cuyo motivo no sigue la forma
        «cubierto por <tool>» (`GET /store`, que cubren dos tools, y las tres
        con `{version}`, que cubre la tool sin versión) salen desde cero con
        el motivo entero de la tabla revisada (`_ConMotivo`).

        Control negativo comprobado: con `("GET", "/store"):
        "sv_list_store_repositories"` en el mapa (sin el motivo) cae este test
        y el de arriba nombrándola; quitar `("POST", "/store/reload")` del
        mapa → cae el de arriba nombrándola."""
        from hermes import command_table as real

        inventario = _RAIZ / "specs" / "008-cobertura-total" / "inventario"
        self.salida.unlink(missing_ok=True)
        gt.generar(inventario / "core-ws.tsv", inventario / "supervisor-rutas.tsv",
                   self.salida, ha_core="2026.11.1", supervisor="2026.11.0")
        cero = self._tabla()
        for k in (("GET", "/store"), ("GET", "/store/repositories/{repository}"),
                  ("GET", "/store/addons/{app}/{version}"),
                  ("POST", "/store/addons/{app}/install/{version}"),
                  ("POST", "/store/addons/{app}/update/{version}"),
                  ("POST", "/addons/{app}/options/validate")):
            with self.subTest(k=k):
                g, r = cero.SUPERVISOR[k], real.SUPERVISOR[k]
                self.assertEqual((g.category, g.reason, g.family, g.tool, g.cap),
                                 (r.category, r.reason, r.family, r.tool, r.cap))

    def test_desde_cero_las_de_la_015_con_su_matiz(self) -> None:
        """Integración de la 015: las dos entradas cuya tool no usa esa misma
        ruta o comando salen desde cero con el matiz de la tabla revisada.
        `hassio/update/core` es «cubierto» (no entra en el test de arriba) y
        `/reload_updates` es de clase A.

        Control negativo comprobado: con `"hassio/update/core":
        "ha_call_service"` en el mapa (lo de antes de la 015) cae este test;
        quitar `("POST", "/os/update")` del mapa → cae el de arriba
        nombrándola."""
        from hermes import command_table as real

        inventario = _RAIZ / "specs" / "008-cobertura-total" / "inventario"
        self.salida.unlink(missing_ok=True)
        gt.generar(inventario / "core-ws.tsv", inventario / "supervisor-rutas.tsv",
                   self.salida, ha_core="2026.11.1", supervisor="2026.11.0")
        cero = self._tabla()
        for nombre, k in (("CORE_WS", "hassio/update/core"),
                          ("SUPERVISOR", ("POST", "/reload_updates"))):
            with self.subTest(k=k):
                g, r = getattr(cero, nombre)[k], getattr(real, nombre)[k]
                self.assertEqual((g.category, g.reason, g.family, g.tool, g.cap),
                                 (r.category, r.reason, r.family, r.tool, r.cap))

    def test_dedicada_con_la_familia_de_su_tool(self) -> None:
        """Spec 016 (T010): la familia sale de la tool del mapa, aquí una de
        `integration_flows`."""
        mapa = dict(gt._DEDICADAS_INICIALES)
        mapa["demo/via_d"] = "ha_update_config_entry"
        original = gt._DEDICADAS_INICIALES
        gt._DEDICADAS_INICIALES = mapa
        try:
            self.salida.unlink()
            self._generar()
        finally:
            gt._DEDICADAS_INICIALES = original
        e = self._tabla().CORE_WS["demo/via_d"]
        self.assertEqual((e.category, e.tool, e.family, e.cap),
                         ("dedicated", "ha_update_config_entry", "integration_flows", "CAP-041"))
        self.assertEqual(e.reason, "cubierto por ha_update_config_entry")
        # Las demás de vía D siguen pendientes.
        self.assertEqual(self._tabla().CORE_WS["demo/via_dt"].category, "deny")


class TestRegeneracion(_Base):
    def test_determinista(self) -> None:
        self._generar()
        primero = self.salida.read_bytes()
        self.salida.unlink()
        self._generar()
        self.assertEqual(self.salida.read_bytes(), primero)
        # Regenerar sobre sí misma tampoco cambia nada.
        self._generar()
        self.assertEqual(self.salida.read_bytes(), primero)

    def test_conserva_lo_editado_a_mano(self) -> None:
        self._generar()
        texto = self.salida.read_text(encoding="utf-8")
        linea = next(l for l in texto.splitlines() if l.startswith('    "demo/item/list"'))
        editada = (
            "    # Revisado a mano: solo lee (comentario que debe sobrevivir).\n"
            '    "demo/item/list": E("read", "Demo: lista de elementos",'
            ' "generic_commands", cap="CAP-066",\n'
            '                        example={"filtro": "ficticio"}),'
        )
        self.salida.write_text(texto.replace(linea, editada), encoding="utf-8")
        self._generar()
        nuevo = self.salida.read_text(encoding="utf-8")
        self.assertIn(editada, nuevo)
        self.assertEqual(self._tabla().CORE_WS["demo/item/list"].example,
                         {"filtro": "ficticio"})

    def test_fila_nueva_entra_como_sin_revisar(self) -> None:
        self._generar()
        with self.core.open("a", encoding="utf-8", newline="") as f:
            f.write("demo/nuevo\tdemo\tx.py\tno\tA\tDemo\tCAP-066\n")
        with self.sv.open("a", encoding="utf-8", newline="") as f:
            f.write("GET\t/demo/nueva\tDemo\tno\tA\t✔\tNo\tCAP-091\n")
        r = self._generar(ha_core="2026.12.0", supervisor="2026.12.1")
        self.assertEqual(r.nuevas, ["demo/nuevo", ("GET", "/demo/nueva")])
        t = self._tabla()
        e = t.CORE_WS["demo/nuevo"]
        self.assertEqual((e.category, e.reason),
                         ("deny", "sin revisar (nuevo en 2026.12.0)"))
        e = t.SUPERVISOR[("GET", "/demo/nueva")]
        self.assertEqual(e.reason, "sin revisar (nuevo en 2026.12.1)")
        self.assertEqual((t.TABLE_HA_CORE, t.TABLE_SUPERVISOR), ("2026.12.0", "2026.12.1"))

    def test_fila_desaparecida_se_quita_y_se_lista(self) -> None:
        self._generar()
        lineas = self.core.read_text(encoding="utf-8").splitlines(keepends=True)
        self.core.write_text("".join(l for l in lineas if not l.startswith("demo/python\t")),
                             encoding="utf-8")
        lineas = self.sv.read_text(encoding="utf-8").splitlines(keepends=True)
        self.sv.write_text("".join(l for l in lineas if "/backups/freeze" not in l),
                           encoding="utf-8")
        r = self._generar()
        self.assertEqual(r.quitadas, ["demo/python", ("POST", "/backups/freeze")])
        self.assertEqual(r.nuevas, [])
        t = self._tabla()
        self.assertNotIn("demo/python", t.CORE_WS)
        self.assertNotIn(("POST", "/backups/freeze"), t.SUPERVISOR)
        self.assertNotIn("demo/python", self.salida.read_text(encoding="utf-8"))

    def test_salida_es_python_valido_con_cabecera(self) -> None:
        self._generar()
        texto = self.salida.read_text(encoding="utf-8")
        compile(texto, str(self.salida), "exec")
        self.assertIn("generar_tabla.py", texto.split('"""')[1])
        self.assertIn("REVISA A MANO", texto.split('"""')[1])


class TestRender(unittest.TestCase):
    def test_marcas_booleanas_y_ejemplo_son_python(self) -> None:
        # La revisión T013-T015 fue la primera en escribir `open_world=True`:
        # el render con `json.dumps` sacaba `true` y la tabla no se importaba.
        # Control negativo: con el `_lit` anterior (solo `json.dumps`) este
        # test cae con NameError.
        from hermes.command_policy import Entrada

        linea = gt._render("demo/escribe", {
            "category": "confirm", "reason": "r", "family": "generic_commands",
            "open_world": True, "redact_extra": ("clave",),
            "example": {"activo": False, "nada": None, "lista": [True, 1, "x"]},
        })
        entrada = eval(linea.strip().split(": ", 1)[1].rstrip(","), {"E": Entrada})
        self.assertTrue(entrada.open_world)
        self.assertEqual(entrada.redact_extra, ("clave",))
        self.assertEqual(entrada.example, {"activo": False, "nada": None, "lista": [True, 1, "x"]})


class TestMatriz(unittest.TestCase):
    def test_copia_de_la_matriz_de_la_008(self) -> None:
        # La matriz del generador es una copia revisada de la de la 008: si la
        # 008 cambia una vía o una sub-feature, este test lo dice.
        plan = (_RAIZ / "specs" / "008-cobertura-total" / "plan.md").read_text(encoding="utf-8")
        filas = re.findall(
            r"^\| (CAP-\d{3}) \| [^|]+ \| ([^|]+) \| [^|]+ \| ([^|]+) \|", plan, re.M)
        de_la_008 = {cap: (via.strip(), sub.strip()) for cap, sub, via in filas}
        self.assertGreater(len(de_la_008), 90)
        for cap, (via, lectura, escritura) in gt.MATRIZ.items():
            with self.subTest(cap=cap):
                via_008, subs_008 = de_la_008[cap]
                self.assertEqual(via, via_008)
                subs = [s.strip() for s in subs_008.split(",")]
                self.assertIn(lectura, subs)
                self.assertIn(escritura, subs)
        # Ninguna CAP de vía D, T, D+T o D+X de la 008 falta en la copia.
        faltan = sorted(c for c, (v, _) in de_la_008.items()
                        if v in {"D", "T", "D+T", "D+X"} and c not in gt.MATRIZ)
        self.assertEqual(faltan, [])


if __name__ == "__main__":
    unittest.main()
