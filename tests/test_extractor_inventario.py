"""Extractor de los inventarios (spec 011, T038; FR-007).

Árboles mínimos de código INVENTADO en `tests/fixtures/inventario/` (nunca el
código real de HA en el CI): un componente con `websocket_command`, una
constante importada de otro módulo, un f-string con `DOMAIN`, un
`BASE_COMMAND_MESSAGE_SCHEMA.extend`, colecciones de almacenamiento
expandidas por prefijo (con un comando propio en una subclase) y un
`supervisor/api/__init__.py` con ramas de versión, logs avanzados, un
parámetro con expresión regular, un recurso estático y una ruta comodín.

Los dos `__init__.py` de ejemplo lanzan una excepción en cuanto se importan:
si el extractor los importara, la extracción fallaría.

Controles negativos comprobados (T042 e y otros, recuentos en el commit):
- el extractor importa el módulo leído (`importlib.import_module`) → cae
  `test_no_importa_el_codigo_que_lee`.
- sin expandir las plantillas de la subclase → cae `test_core_colecciones`.
- la rama V2 en vez de la V1 → cae `test_supervisor_rutas_v1`.
- la fusión sobrescribe las columnas manuales → cae
  `test_fusion_conserva_columnas_manuales`.
"""

from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

from scripts.inventario import extraer as x

_FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "inventario"
_CORE = _FIXTURES / "arbol_core"
_SV = _FIXTURES / "arbol_supervisor"


class TestCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.res = x.extraer_core(_CORE)

    def test_core_comandos_literales_y_constantes(self) -> None:
        f = self.res.filas
        for comando in ("demo/listar", "demo/importado", "demo/con_fstring",
                        "demo/extendido"):
            with self.subTest(comando=comando):
                self.assertIn(comando, f)
                self.assertEqual(f[comando], {
                    "integracion": "demo",
                    "fichero": "homeassistant/components/demo/__init__.py",
                })

    def test_core_no_toma_otros_esquemas_con_type(self) -> None:
        self.assertNotIn("demo/no_es_comando", self.res.filas)

    def test_core_colecciones(self) -> None:
        f = self.res.filas
        for accion in ("list", "create", "update", "delete", "subscribe"):
            with self.subTest(accion=accion):
                self.assertEqual(f[f"demo_coleccion/{accion}"], {
                    "integracion": "demo",
                    "fichero": "homeassistant/helpers/collection.py (StorageCollectionWebsocket)",
                })
                self.assertIn(f"otro/elementos/{accion}", f)
        # El comando propio de la subclase, con su fichero.
        self.assertEqual(f["otro/elementos/get"], {
            "integracion": "otro",
            "fichero": "homeassistant/components/otro/__init__.py",
        })

    def test_core_recuento_exacto(self) -> None:
        self.assertEqual(len(self.res.filas), 4 + 5 + 6, sorted(self.res.filas))
        self.assertEqual(self.res.avisos, [])

    def test_sintaxis_de_python_3_14(self) -> None:
        """`except A, B:` (PEP 758) lo usa Core 2026.11; un `ast` anterior no
        lo entiende y sin la reescritura se perderían 255 comandos."""
        with tempfile.TemporaryDirectory() as tmp:
            raiz = pathlib.Path(tmp) / "core"
            shutil.copytree(_CORE, raiz)
            (raiz / "homeassistant" / "components" / "nuevo").mkdir()
            (raiz / "homeassistant" / "components" / "nuevo" / "__init__.py").write_text(
                "from homeassistant.components import websocket_api\n\n"
                "@websocket_api.websocket_command({'type': 'nuevo/x'})\n"
                "def f(hass, connection, msg):\n"
                "    try:\n        pass\n"
                "    except ValueError, TypeError:\n        pass\n",
                encoding="utf-8")
            res = x.extraer_core(raiz)
        self.assertIn("nuevo/x", res.filas)
        self.assertEqual(res.avisos, [])


class TestSupervisor(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.res = x.extraer_supervisor(_SV)

    def test_supervisor_rutas_v1(self) -> None:
        self.assertEqual(set(self.res.filas), {
            ("GET", "/demo/info"),
            ("POST", "/demo/{app}/options"),
            ("DELETE", "/demo/{slug}"),
            ("GET", "/demo/api/{path}"),
            ("POST", "/demo/solo_v1"),
            ("GET", "/demo/logs"),
            ("GET", "/demo/logs/boots/{bootid}"),
            ("GET", "/app/{filename}"),
        })

    def test_supervisor_ruta_comodin_avisada(self) -> None:
        self.assertEqual(len(self.res.avisos), 1)
        self.assertIn("/demo/comodin/{x}", self.res.avisos[0])
        self.assertIn("comodín", self.res.avisos[0])


class TestNoImporta(unittest.TestCase):
    def test_no_importa_el_codigo_que_lee(self) -> None:
        antes = set(sys.modules)
        x.extraer_core(_CORE)
        x.extraer_supervisor(_SV)
        nuevos = {m for m in set(sys.modules) - antes
                  if m.split(".")[0] in ("homeassistant", "supervisor", "probatio", "aiohttp")}
        self.assertEqual(nuevos, set())


class TestFusion(unittest.TestCase):
    _PREVIO_CORE = (
        "comando\tintegracion\tfichero\tcobertura\tclase\tnota\tcap\n"
        "demo/listar\tdemo\tfichero/revisado.py\tno\tA\tnota revisada\tCAP-001\n"
        "demo/desaparecido\tdemo\tx.py\tno\tB\tse fue\t\n"
    )
    _PREVIO_SV = (
        "metodo\truta\tarea\tcobertura\tclase\trol_admin\tnota\tcap\n"
        "GET\t/demo/info\tDemo\tsi\tcubierto\t✔\tSí (`sv_demo`)\t\n"
    )

    def _ejecutar(self, comprobar: bool = False) -> tuple[int, str, str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            core_tsv = pathlib.Path(tmp) / "core-ws.tsv"
            sv_tsv = pathlib.Path(tmp) / "supervisor-rutas.tsv"
            core_tsv.write_text(self._PREVIO_CORE, encoding="utf-8", newline="")
            sv_tsv.write_text(self._PREVIO_SV, encoding="utf-8", newline="")
            argv = ["--core-src", str(_CORE), "--supervisor-src", str(_SV),
                    "--core-tsv", str(core_tsv), "--supervisor-tsv", str(sv_tsv)]
            if comprobar:
                argv.append("--comprobar")
            from contextlib import redirect_stdout
            from io import StringIO

            salida = StringIO()
            with redirect_stdout(salida):
                rc = x.main(argv)
            return (rc, core_tsv.read_text(encoding="utf-8"),
                    sv_tsv.read_text(encoding="utf-8"), salida.getvalue())

    def test_fusion_conserva_columnas_manuales(self) -> None:
        _, core, sv, _ = self._ejecutar()
        filas = {f["comando"]: f for f in x.leer_tsv_texto(core)}
        self.assertEqual(filas["demo/listar"], {
            "comando": "demo/listar", "integracion": "demo",
            "fichero": "fichero/revisado.py", "cobertura": "no", "clase": "A",
            "nota": "nota revisada", "cap": "CAP-001"})
        sv_filas = {(f["metodo"], f["ruta"]): f for f in x.leer_tsv_texto(sv)}
        self.assertEqual(sv_filas[("GET", "/demo/info")]["nota"], "Sí (`sv_demo`)")

    def test_fusion_filas_nuevas_sin_clase_y_quitadas(self) -> None:
        _, core, sv, salida = self._ejecutar()
        filas = {f["comando"]: f for f in x.leer_tsv_texto(core)}
        self.assertNotIn("demo/desaparecido", filas)
        self.assertIn("- demo/desaparecido", salida)
        nueva = filas["demo/importado"]
        self.assertEqual((nueva["integracion"], nueva["fichero"]),
                         ("demo", "homeassistant/components/demo/__init__.py"))
        self.assertEqual([nueva[c] for c in ("cobertura", "clase", "nota", "cap")],
                         ["", "", "", ""])
        self.assertIn("+ demo/importado", salida)
        sv_filas = {(f["metodo"], f["ruta"]): f for f in x.leer_tsv_texto(sv)}
        self.assertEqual(sv_filas[("POST", "/demo/solo_v1")]["clase"], "")
        self.assertEqual(len(sv_filas), 8)

    def test_fusion_determinista_y_estable(self) -> None:
        """Dos ejecuciones dan el mismo texto, y la segunda (sobre la salida
        de la primera) no cambia nada."""
        _, core1, sv1, _ = self._ejecutar()
        _, core2, sv2, _ = self._ejecutar()
        self.assertEqual((core1, sv1), (core2, sv2))
        filas, nuevas, quitadas = x.fusionar(
            x.leer_tsv_texto(core1), x.extraer_core(_CORE).filas,
            x.COLUMNAS_CORE, lambda f: f["comando"])
        self.assertEqual((nuevas, quitadas), ([], []))

    def test_comprobar_no_escribe_y_avisa_con_codigo(self) -> None:
        rc, core, sv, _ = self._ejecutar(comprobar=True)
        self.assertEqual(rc, 1)
        self.assertEqual(core, self._PREVIO_CORE)
        self.assertEqual(sv, self._PREVIO_SV)


if __name__ == "__main__":
    unittest.main()
