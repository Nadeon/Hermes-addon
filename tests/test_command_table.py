"""La tabla de clasificación real (spec 011, FR-001, FR-002, FR-005, FR-006,
FR-018, FR-023; SC-001, SC-002; T011).

`hermes/command_table.py` decide qué pueden ejecutar las genéricas. Estos
tests son su red de seguridad:

- **deriva** (FR-006): la tabla y los inventarios de la 008 tienen las mismas
  claves; una versión nueva de HA no abre ni deja colgada ninguna puerta sin
  que se vea aquí;
- **verbos** (FR-005, SC-002): ningún comando con un verbo de escritura ni
  ninguna ruta con método distinto de GET queda en `read` (el `readOnlyHint`
  de las genéricas de lectura depende de ello, principio V con la enmienda
  E-2), salvo excepciones explícitas y justificadas;
- **dedicadas** (FR-023): toda `dedicated` apunta a una tool que existe, con
  su familia;
- marcas, recuentos, versiones y las reglas de FR-002 que no dependen de la
  revisión manual.

Control negativo (T011/T016 a–d), con recuentos en el commit: pasar
`tag/create` a `read` → cae el de verbos nombrándolo; quitar una entrada o
añadir una inventada → cae la deriva nombrándola; una `dedicated` con una
tool inexistente o con la familia equivocada → cae el de dedicadas; una
entrada «sin revisar» → cae el suyo.
"""

from __future__ import annotations

import ast
import csv
import pathlib
import re
import unittest

from hermes import command_table as ct
from hermes.config import HA_CORE_LAST_TESTED
from hermes.tool_families import FAMILIAS, familia_de_modulo

_RAIZ = pathlib.Path(__file__).resolve().parents[1]
_INVENTARIO = _RAIZ / "specs" / "008-cobertura-total" / "inventario"
_TOOLS_DIR = _RAIZ / "hermes" / "src" / "hermes" / "tools"

# Lista explícita de FR-005 (FR-004 de la 008). Solo crece: quitar un verbo
# abriría `read` a comandos que escriben.
VERBOS_ESCRITURA = frozenset({
    "create", "delete", "remove", "update", "set", "save", "install",
    "uninstall", "restart", "reload", "import", "clear", "adjust", "change",
    "configure", "reset", "move", "reorder", "enable", "disable", "ignore",
    "dismiss", "add", "promote", "run", "start", "stop",
})

# Entradas `read` que contienen uno de esos verbos y aun así solo leen.
# Clave (comando o (método, ruta)) → justificación. Cada una lleva además un
# comentario en command_table.py. El test las enumera al fallar.
_EXCEPCIONES_VERBOS: dict[str | tuple[str, str], str] = {}

_CATEGORIAS = {"dedicated", "read", "confirm", "deny"}
_PROXY_CORE = ("/core/api", "/homeassistant/api")


def _leer(nombre: str) -> list[dict[str, str]]:
    with (_INVENTARIO / nombre).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


_CORE = {f["comando"]: f for f in _leer("core-ws.tsv")}
_SV = {(f["metodo"], f["ruta"]): f for f in _leer("supervisor-rutas.tsv")}


def _todas():
    yield from ct.CORE_WS.items()
    yield from ct.SUPERVISOR.items()


def _tokens(texto: str) -> set[str]:
    return set(re.split(r"[/_\-]", texto))


def _matriz_008() -> dict[str, tuple[str, list[str]]]:
    plan = (_RAIZ / "specs" / "008-cobertura-total" / "plan.md").read_text(encoding="utf-8")
    filas = re.findall(
        r"^\| (CAP-\d{3}) \| [^|]+ \| ([^|]+) \| [^|]+ \| ([^|]+) \|", plan, re.M)
    return {cap: (via.strip(), [s.strip() for s in sub.split(",")])
            for cap, sub, via in filas}


def _tool_a_familia() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(_TOOLS_DIR.glob("*.py")):
        arbol = ast.parse(path.read_text(encoding="utf-8"))
        for n in ast.walk(arbol):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                (isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool")
                or (isinstance(d, ast.Attribute) and d.attr == "tool")
                for d in n.decorator_list
            ):
                out[n.name] = familia_de_modulo(path.stem)
    return out


class TestDeriva(unittest.TestCase):
    def test_core(self) -> None:
        faltan = sorted(set(_CORE) - set(ct.CORE_WS))
        sobran = sorted(set(ct.CORE_WS) - set(_CORE))
        self.assertEqual(
            (faltan, sobran), ([], []),
            f"Core: sin entrada en la tabla: {faltan}; en la tabla y no en el "
            f"inventario: {sobran}")

    def test_supervisor(self) -> None:
        faltan = sorted(set(_SV) - set(ct.SUPERVISOR))
        sobran = sorted(set(ct.SUPERVISOR) - set(_SV))
        self.assertEqual(
            (faltan, sobran), ([], []),
            f"Supervisor: sin entrada en la tabla: {faltan}; en la tabla y no "
            f"en el inventario: {sobran}")

    def test_recuentos(self) -> None:
        self.assertEqual(len(ct.CORE_WS), 623)
        self.assertEqual(len(ct.SUPERVISOR), 254)

    def test_versiones(self) -> None:
        self.assertEqual(ct.TABLE_HA_CORE, HA_CORE_LAST_TESTED)
        self.assertEqual(ct.TABLE_SUPERVISOR, "2026.11.0")


class TestVerbos(unittest.TestCase):
    def test_ninguna_lectura_escribe(self) -> None:
        malas = []
        for clave, e in _todas():
            if e.category != "read" or clave in _EXCEPCIONES_VERBOS:
                continue
            texto = clave[1] if isinstance(clave, tuple) else clave
            verbos = sorted(_tokens(texto) & VERBOS_ESCRITURA)
            if verbos:
                malas.append(f"{clave}: verbo {verbos}")
            if isinstance(clave, tuple) and clave[0] != "GET":
                malas.append(f"{clave}: método {clave[0]}")
        self.assertEqual(
            malas, [],
            "entradas `read` que parecen escribir:\n  " + "\n  ".join(malas)
            + "\nexcepciones vigentes:\n  "
            + "\n  ".join(f"{k}: {v}" for k, v in _EXCEPCIONES_VERBOS.items()))

    def test_excepciones_vigentes(self) -> None:
        # Una excepción que ya no es `read` o que ya no existe sobra: dejarla
        # taparía en silencio una reclasificación futura.
        sobran = sorted(
            str(k) for k in _EXCEPCIONES_VERBOS
            if (ct.CORE_WS if isinstance(k, str) else ct.SUPERVISOR).get(k) is None
            or (ct.CORE_WS if isinstance(k, str) else ct.SUPERVISOR)[k].category != "read"
        )
        self.assertEqual(sobran, [])
        for k, porque in _EXCEPCIONES_VERBOS.items():
            self.assertTrue(porque.strip(), k)


class TestEstructura(unittest.TestCase):
    def test_categorias_motivos_y_familias(self) -> None:
        problemas = [
            f"{k}: {e.category!r} / {e.reason!r} / {e.family!r}"
            for k, e in _todas()
            if e.category not in _CATEGORIAS or not e.reason.strip()
            or e.family not in FAMILIAS
        ]
        self.assertEqual(problemas, [])

    def test_ninguna_sin_revisar(self) -> None:
        sin = sorted(str(k) for k, e in _todas() if "sin revisar" in e.reason)
        self.assertEqual(sin, [], f"entradas «sin revisar»: {sin}")

    def test_ninguna_provisional(self) -> None:
        provisionales = sorted(str(k) for k, e in _todas() if "provisional" in e.reason)
        self.assertEqual(provisionales, [],
                         f"{len(provisionales)} entradas provisionales: {provisionales}")

    def test_marcas(self) -> None:
        problemas = []
        for k, e in _todas():
            es_sv = isinstance(k, tuple)
            if (e.tool is not None) != (e.category == "dedicated"):
                problemas.append(f"{k}: tool {e.tool!r} con {e.category}")
            if e.one_shot and (e.category != "read" or es_sv):
                problemas.append(f"{k}: one_shot fuera de un read de Core")
            if e.response == "text" and not es_sv:
                problemas.append(f"{k}: respuesta de texto en Core")
            if e.cap is not None and not re.fullmatch(r"CAP-\d{3}", e.cap):
                problemas.append(f"{k}: cap {e.cap!r}")
        self.assertEqual(problemas, [])

    def test_ejemplos(self) -> None:
        """T037 (FR-001, FR-022): los ejemplos de carga los enseña la guía tal
        cual, así que solo van en entradas que una genérica ejecuta (`read`
        o `confirm`), son objetos JSON y no llevan `id` ni `type` (los pone
        Hermes; la genérica los rechaza). Los de `tag/*` existen: son los que
        la guía promete como referencia."""
        import json

        problemas = []
        for k, e in _todas():
            if e.example is None:
                continue
            if e.category not in ("read", "confirm"):
                problemas.append(f"{k}: ejemplo en una entrada {e.category}")
            if not isinstance(e.example, dict) or {"id", "type"} & set(e.example):
                problemas.append(f"{k}: ejemplo que no es un objeto o lleva id/type")
            else:
                json.dumps(e.example)
        self.assertEqual(problemas, [])
        for comando in ("tag/list", "tag/create", "tag/update", "tag/delete"):
            self.assertIsNotNone(ct.CORE_WS[comando].example, comando)

    def test_a_y_c_con_su_cap(self) -> None:
        problemas = []
        for inventario, tabla in ((_CORE, ct.CORE_WS), (_SV, ct.SUPERVISOR)):
            for k, fila in inventario.items():
                # Lo que falta en la tabla ya lo nombra la deriva.
                if fila["clase"][:1] in {"A", "C"} and k in tabla and tabla[k].cap != fila["cap"]:
                    problemas.append(f"{k}: cap {tabla[k].cap!r}, inventario {fila['cap']!r}")
        self.assertEqual(problemas, [])


class TestDedicadas(unittest.TestCase):
    def test_tool_existe_y_familia_coincide(self) -> None:
        from tests.test_tools_registration import _real_registry

        registro = _real_registry()
        familias = _tool_a_familia()
        problemas = []
        for k, e in _todas():
            if e.category != "dedicated":
                continue
            if e.tool not in registro:
                problemas.append(f"{k}: la tool {e.tool!r} no está registrada")
            elif e.family != familias[e.tool]:
                problemas.append(
                    f"{k}: familia {e.family!r}, la de {e.tool} es {familias[e.tool]!r}")
        self.assertEqual(problemas, [], "\n".join(problemas))

    def test_dedicadas_de_la_029(self) -> None:
        """Spec 029, T014 (FR-016): los cinco comandos de CAP-043 son
        `dedicated` hacia su tool de `system_status`, con la forma que escribe
        el generador, y el mapa del generador los nombra (una tabla generada
        desde cero sale igual). Tramo 2 (T027): lo mismo con los cuatro de
        CAP-049 hacia su tool de `recorder`, y ya no queda ninguna entrada
        «pendiente (spec 029)».
        Controles negativos: `manifest/get` en `deny` (T018 e) o
        `recorder/info` en `deny` (T034 f) → cae."""
        from scripts.inventario.generar_tabla import _DEDICADAS_INICIALES

        cinco = {
            "system_health/info": "ha_get_system_health",
            "subscribe_system_state": "ha_get_system_state",
            "integration/setup_info": "ha_list_integration_setup_times",
            "manifest/list": "ha_list_integration_manifests",
            "manifest/get": "ha_get_integration_manifest",
        }
        for comando, tool in cinco.items():
            with self.subTest(comando=comando):
                e = ct.CORE_WS[comando]
                self.assertEqual(
                    (e.category, e.reason, e.family, e.tool, e.cap),
                    ("dedicated", f"cubierto por {tool}", "system_status", tool, "CAP-043"))
                self.assertEqual(_DEDICADAS_INICIALES[comando], tool)
        # Tramo 2 (T027): los cuatro de CAP-049, hacia su tool de `recorder`.
        cuatro = {
            "recorder/info": "ha_get_recorder_info",
            "recorder/entity_options/get": "ha_get_recorder_info",
            "recorder/validate_statistics": "ha_validate_statistics",
            "recorder/get_statistics_metadata": "ha_get_statistics_metadata",
        }
        for comando, tool in cuatro.items():
            with self.subTest(comando=comando):
                e = ct.CORE_WS[comando]
                self.assertEqual(
                    (e.category, e.reason, e.family, e.tool, e.cap),
                    ("dedicated", f"cubierto por {tool}", "recorder", tool, "CAP-049"))
                self.assertEqual(_DEDICADAS_INICIALES[comando], tool)
        # Y ya no queda nada «pendiente (spec 029)» en ninguna de las dos
        # tablas (FR-016; control negativo T034 f: `recorder/info` en `deny`
        # -> cae).
        pendientes = sorted(str(k) for k, e in _todas() if "(spec 029)" in e.reason)
        self.assertEqual(pendientes, [])

    def test_lo_no_dedicado_es_de_las_genericas(self) -> None:
        # Hasta que una sub-feature asigne otra familia (data-model).
        otras = sorted(str(k) for k, e in _todas()
                       if e.category != "dedicated" and e.family != "generic_commands")
        self.assertEqual(otras, [])


# Entradas `read` que salen a internet, revisadas a mano (T047): con una
# fuente remota (radio_browser, google_photos, immich, xbox, nest…), navegar y
# buscar consultan APIs externas (media_source de Core 2026.11.1). Clave →
# por qué.
_READ_QUE_SALEN: dict[str | tuple[str, str], str] = {
    "media_source/browse_media": "las fuentes remotas consultan su API al navegar",
    "media_source/search_media": "las fuentes remotas consultan su API al buscar",
}


class TestMundoAbierto(unittest.TestCase):
    """FR-018 (T047): la anotación `openWorldHint` de cada genérica dice la
    verdad sobre su tabla. Una tool no puede declarar que no sale a internet
    si algún comando suyo lo hace, ni al revés (principio V).

    Control negativo comprobado: quitar `ha_read_ws_command` de `_OPEN_WORLD`
    → cae `test_anotacion_igual_a_la_tabla` (y el de hints de
    test_tools_registration); quitar `open_world=True` de
    `media_source/browse_media` → cae `test_reads_que_salen_revisadas`.
    """

    def test_reads_que_salen_revisadas(self) -> None:
        salen = {k for k, e in _todas() if e.category == "read" and e.open_world}
        self.assertEqual(salen, set(_READ_QUE_SALEN))

    def test_anotacion_igual_a_la_tabla(self) -> None:
        from hermes.tools._annotations import classify

        casos = (
            ("ha_read_ws_command", ct.CORE_WS, "read"),
            ("ha_call_ws_command", ct.CORE_WS, "confirm"),
            ("sv_read_api", ct.SUPERVISOR, "read"),
            ("sv_call_api", ct.SUPERVISOR, "confirm"),
        )
        for tool, tabla, categoria in casos:
            with self.subTest(tool=tool):
                sale = any(e.open_world for e in tabla.values() if e.category == categoria)
                self.assertEqual(classify(tool).open_world_hint, sale)


class TestPistasYMotivos(unittest.TestCase):
    def test_motivo_que_remite_a_ha_call_service(self) -> None:
        """T046: un motivo que manda a `ha_call_service` con una acción dice
        la verdad sobre ella: si dice que pide confirmación, la acción está en
        la denylist (que es lo que la pide); si no lo dice, no lo está.
        Control negativo comprobado: con la acción cambiada a una inexistente
        en `hassio/update/core` → cae."""
        from hermes.service_policy import CALL_SERVICE_DENYLIST

        patron = re.compile(r"`ha_call_service` con `([a-z_]+\.[a-z_]+)`")
        problemas = []
        vistos = set()
        for k, e in _todas():
            for accion in patron.findall(e.reason):
                vistos.add(k)
                if ("pide confirmación" in e.reason) != (accion in CALL_SERVICE_DENYLIST):
                    problemas.append(f"{k}: {accion} y el motivo {e.reason!r}")
        self.assertEqual(problemas, [], "\n".join(problemas))
        # Las dos que antes eran `dedicated` hacia `ha_call_service` sin decir
        # qué acción (T046) y que el test no esté vacío.
        self.assertTrue({"backup/generate_with_automatic_settings",
                         "hassio/update/core"} <= vistos)

    def test_ninguna_dedicada_a_ha_call_service_sin_accion(self) -> None:
        # Las que quedan apuntan a una acción del mismo nombre que el comando
        # (p. ej. `calendar/event/create` → `calendar.create_event`), ninguna
        # de la denylist; las dos de T046 ya no son `dedicated`.
        for k in ("backup/generate_with_automatic_settings", "hassio/update/core"):
            with self.subTest(k=k):
                self.assertEqual(ct.CORE_WS[k].category, "deny")
                self.assertRegex(ct.CORE_WS[k].reason, r"^pendiente de tool dedicada \(spec \d{3}\)")

    def test_motivo_de_dns_options(self) -> None:
        # T048: `SCHEMA_OPTIONS` de supervisor/api/dns.py (2026.11.0) solo
        # admite `servers` y `fallback`; el motivo sale en la vista previa y
        # no puede prometer otras opciones. Control negativo comprobado: con el
        # motivo anterior («fallback/LLMNR/mDNS») → cae.
        motivo = ct.SUPERVISOR[("POST", "/dns/options")].reason
        self.assertIn("`servers`", motivo)
        self.assertIn("`fallback`", motivo)
        for otra in ("LLMNR", "mDNS", "llmnr", "mdns"):
            self.assertNotIn(otra, motivo)


class TestReglasDeLaClasificacionInicial(unittest.TestCase):
    def test_proxy_de_core_siempre_deny(self) -> None:
        abiertas = sorted(
            str(k) for k, e in ct.SUPERVISOR.items()
            if k[1].startswith(_PROXY_CORE) and e.category != "deny")
        self.assertEqual(abiertas, [])
        # Y el inventario las tiene (si no, este test no probaría nada).
        self.assertGreaterEqual(
            sum(1 for k in ct.SUPERVISOR if k[1].startswith(_PROXY_CORE)), 10)

    def test_clase_c_pendiente_de_la_025(self) -> None:
        malas = sorted(
            str(k) for k, f in _CORE.items() if f["clase"] == "C"
            and (ct.CORE_WS[k].category, ct.CORE_WS[k].reason)
            != ("deny", "pendiente de revisión (spec 025)"))
        self.assertEqual(malas, [])

    def test_clase_a_de_via_dedicada_pendiente_de_su_spec(self) -> None:
        matriz = _matriz_008()
        malas = []
        for inventario, tabla in ((_CORE, ct.CORE_WS), (_SV, ct.SUPERVISOR)):
            for k, f in inventario.items():
                if not f["clase"].startswith("A"):
                    continue
                via, subs = matriz[f["cap"]]
                if via not in {"D", "D+T", "D+X"}:
                    continue
                e = tabla[k]
                # Spec 029, T002 (research R-7, mismo diseño que la 012):
                # cuando su sub-feature crea la tool, la entrada pasa a
                # `dedicated` hacia ella, y esa tool es de una familia de la
                # 1.2.0 (no de la 1.1.2 ni una genérica). `read` o `confirm`
                # siguen siendo un error: la vía D exige tool dedicada.
                if e.category == "dedicated":
                    familia = FAMILIAS.get(_tool_a_familia().get(e.tool, ""))
                    if (familia is None or familia.desde != "1.2.0"
                            or familia.nombre == "generic_commands"):
                        malas.append(f"{k} ({f['cap']}): dedicated hacia {e.tool!r}")
                    continue
                m = re.fullmatch(r"pendiente de tool dedicada \(spec (\d{3})\)", e.reason)
                if e.category != "deny" or not m or m.group(1) not in subs:
                    malas.append(f"{k} ({f['cap']}, {via}, {subs}): {e.category} {e.reason!r}")
        self.assertEqual(malas, [], "\n".join(malas))


if __name__ == "__main__":
    unittest.main()
