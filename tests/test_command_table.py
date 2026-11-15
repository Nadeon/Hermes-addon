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
_EXCEPCIONES_VERBOS: dict[str | tuple[str, str], str] = {
    # Spec 025 (FR-010): lecturas de Z-Wave JS con `update` en el nombre por
    # «firmware update»; los tres handlers solo consultan el driver.
    "zwave_js/is_node_firmware_update_in_progress":
        "solo pregunta si un nodo se está actualizando; no actualiza nada",
    "zwave_js/is_any_ota_firmware_update_in_progress":
        "solo pregunta si algún nodo se está actualizando; no actualiza nada",
    "zwave_js/get_node_firmware_update_capabilities":
        "solo lee qué admite el nodo para actualizar firmware; no actualiza nada",
}

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

    def test_dedicadas_de_la_017_tramo_a(self) -> None:
        """Spec 017, T010 (FR-012): los cuatro comandos de blueprints del
        tramo A son `dedicated` hacia su tool de `blueprints`, con la forma
        que escribe el generador, y el mapa del generador los nombra. Tramo B
        (T021): `blueprint/import` también, hacia `ha_import_blueprint`.
        Control negativo (T016, 7): `blueprint/delete` de vuelta a `deny` →
        cae aquí (y `test_desde_cero_igual_que_la_tabla_real` de test_generar_tabla)."""
        from scripts.inventario.generar_tabla import _DEDICADAS_INICIALES

        cuatro = {
            "blueprint/list": "ha_list_blueprints",
            "blueprint/save": "ha_save_blueprint",
            "blueprint/delete": "ha_delete_blueprint",
            "blueprint/substitute": "ha_preview_blueprint_substitution",
            "blueprint/import": "ha_import_blueprint",
        }
        for comando, tool in cuatro.items():
            with self.subTest(comando=comando):
                e = ct.CORE_WS[comando]
                self.assertEqual(
                    (e.category, e.reason, e.family, e.tool, e.cap),
                    ("dedicated", f"cubierto por {tool}", "blueprints", tool, "CAP-046"))
                self.assertEqual(_DEDICADAS_INICIALES[comando], tool)

    def test_dedicada_de_la_017_tramo_d(self) -> None:
        """Spec 017, T045 (FR-012, research R-13): `subscribe_trigger` pasa de
        clase B a A (CAP-038) y es `dedicated` hacia `ha_wait_for_trigger`,
        con la forma del generador y en su mapa.
        Control negativo (T054, 8): la fila del inventario de vuelta a clase
        B → cae `test_subscribe_trigger_es_clase_a` de test_generar_tabla;
        la entrada de la tabla de vuelta a `deny` → cae este test (y tres
        más de este fichero y el de las genéricas)."""
        from scripts.inventario.generar_tabla import _DEDICADAS_INICIALES

        e = ct.CORE_WS["subscribe_trigger"]
        self.assertEqual(
            (e.category, e.reason, e.family, e.tool, e.cap),
            ("dedicated", "cubierto por ha_wait_for_trigger", "automation_assist",
             "ha_wait_for_trigger", "CAP-038"))
        self.assertEqual(_DEDICADAS_INICIALES["subscribe_trigger"], "ha_wait_for_trigger")

    def test_dedicadas_de_la_017_tramo_c(self) -> None:
        """Spec 017, T032 (FR-012): los seis comandos de `device_automation/*`
        (lista y capacidades van a la misma tool) y los cinco de targets son
        `dedicated` hacia su tool de `automation_assist`, con la forma que
        escribe el generador, y el mapa del generador los nombra.
        Control negativo (T037, 4): `device_automation/trigger/capabilities`
        de vuelta a `deny` → cae aquí (y
        `test_desde_cero_igual_que_la_tabla_real` de test_generar_tabla)."""
        from scripts.inventario.generar_tabla import _DEDICADAS_INICIALES

        once = {
            "device_automation/trigger/list": ("ha_list_device_triggers", "CAP-051"),
            "device_automation/trigger/capabilities": ("ha_list_device_triggers", "CAP-051"),
            "device_automation/condition/list": ("ha_list_device_conditions", "CAP-051"),
            "device_automation/condition/capabilities": ("ha_list_device_conditions", "CAP-051"),
            "device_automation/action/list": ("ha_list_device_actions", "CAP-051"),
            "device_automation/action/capabilities": ("ha_list_device_actions", "CAP-051"),
            "extract_from_target": ("ha_resolve_target", "CAP-052"),
            "explain_target": ("ha_explain_target", "CAP-052"),
            "get_triggers_for_target": ("ha_list_triggers_for_target", "CAP-052"),
            "get_conditions_for_target": ("ha_list_conditions_for_target", "CAP-052"),
            "get_services_for_target": ("ha_list_actions_for_target", "CAP-052"),
        }
        for comando, (tool, cap) in once.items():
            with self.subTest(comando=comando):
                e = ct.CORE_WS[comando]
                self.assertEqual(
                    (e.category, e.reason, e.family, e.tool, e.cap),
                    ("dedicated", f"cubierto por {tool}", "automation_assist", tool, cap))
                self.assertEqual(_DEDICADAS_INICIALES[comando], tool)
        # Ya no queda nada de la 017 «pendiente» (T053).
        pendientes = sorted(str(k) for k, e in _todas() if "(spec 017)" in e.reason)
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
    # Spec 025: pregunta al servicio de Z-Wave JS si hay base de datos de
    # dispositivos nueva.
    "zwave_js/check_for_config_updates": "consulta por internet la base de datos de Z-Wave JS",
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
        # La que antes era `dedicated` hacia `ha_call_service` sin decir qué
        # acción (T046) y que el test no esté vacío. `hassio/update/core`
        # también lo era hasta que la 015 le dio su tool (`sv_update_core`).
        self.assertIn("backup/generate_with_automatic_settings", vistos)

    def test_ninguna_dedicada_a_ha_call_service_sin_accion(self) -> None:
        # Las que quedan apuntan a una acción del mismo nombre que el comando
        # (p. ej. `calendar/event/create` → `calendar.create_event`), ninguna
        # de la denylist; las dos de T046 ya no son `dedicated` hacia
        # `ha_call_service`: una sigue pendiente de su spec y la otra apunta
        # desde la 015 a `sv_update_core`, su tool dedicada.
        k = "backup/generate_with_automatic_settings"
        self.assertEqual(ct.CORE_WS[k].category, "deny")
        self.assertRegex(ct.CORE_WS[k].reason, r"^pendiente de tool dedicada \(spec \d{3}\)")
        e = ct.CORE_WS["hassio/update/core"]
        self.assertEqual((e.category, e.tool), ("dedicated", "sv_update_core"))

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


# Clase A de una CAP de vía dedicada que su sub-feature deja por la tabla:
# «dentro de una CAP dedicada, sus lecturas menores pueden ir por la tabla si
# la sub-spec lo justifica» (regla de reparto de la 008). Clave → «spec NNN:
# porqué». Dejarlo aquí hace visible la justificación y obliga a la siguiente
# sub-feature a dar la suya.
# Tools de la 1.1.2 que una sub-feature amplía para cubrir una entrada de vía
# D, en vez de crear una tool nueva. Fuera de esta lista, una entrada
# `dedicated` de vía D tiene que ir a una tool de una familia de la 1.2.0
# (029, T002). Integración de la 029 con la 013: sin esta excepción caen
# `/addons/{app}/logs/latest` y `/addons/{app}/logs/boots/{bootid}`.
_DE_LA_1_1_2_AMPLIADAS: dict[str, str] = {
    "sv_get_addon_logs": "spec 013 (CAP-081): `boot` y `latest`",
    # Spec 030 (research R-2 y R-7): el Supervisor 2026.11.0 ignora
    # `{version}`, así que esas rutas son las de las tools sin versión de la
    # 1.1.2; la validación de opciones va en la vista previa de
    # `sv_set_addon_options`. Ninguna gana argumentos: ganan vista previa.
    "sv_install_addon": "spec 030 (CAP-082): ignora `{version}`; vista previa con la tienda",
    "sv_update_addon": "spec 030 (CAP-082): ignora `{version}`; vista previa con el changelog",
    "sv_get_addon": "spec 030 (CAP-082): `GET /store/addons/{app}/{version}` ignora la versión",
    "sv_set_addon_options": "spec 030 (CAP-093): valida las opciones en la vista previa",
}

_POR_LA_TABLA: dict[tuple[str, str] | str, str] = {
    ("GET", "/jobs/info"): (
        "spec 013: FR-046 de la 008 lo pide en la tabla; es una lectura de "
        "prioridad media y su forma (objeto con una lista) la recorta bien el tope"),
    ("GET", "/resolution/issue/{issue}/suggestions"): (
        "spec 013: sv_get_resolution ya trae las sugerencias; esta ruta solo "
        "filtra las de un issue"),
    ("GET", "/host/disks"): (
        "spec 013: lectura menor de CAP-085 (discos con particiones montables, "
        "para los montajes de la 019); sin tool en el research de la 008"),
    "recorder/update_statistics_issues": (
        "spec 020: no toca filas ni metadatos, solo vuelve a crear o quitar los "
        "avisos de Repairs de las estadísticas; sin argumentos, una tool no "
        "tendría vista previa útil (research R-3, decisión D-3)"),
    # Spec 020, tramo 3 (FR-013): las cuatro lecturas de energía. Revisadas
    # en `energy/websocket_api.py`: ninguna escribe ni sale a internet (la
    # previsión solar devuelve lo que la integración ya descargó).
    "energy/validate": (
        "spec 020: problemas de configuración del panel por fuente y "
        "dispositivo; solo lee"),
    "energy/info": (
        "spec 020: sensores de coste y dominios con previsión solar; solo lee"),
    "energy/solar_forecast": (
        "spec 020: la previsión que ya tienen las integraciones de las fuentes "
        "solares; solo lee, no la descarga"),
    "energy/fossil_energy_consumption": (
        "spec 020: un cálculo sobre estadísticas de energía y de CO2; solo "
        "lee, con ejemplo de carga"),
    ("GET", "/core/stats"): (
        "spec 022: FR-076 de la 008 pide las estadísticas `read` en la tabla, "
        "sin tool dedicada"),
    ("GET", "/supervisor/stats"): (
        "spec 022: FR-076 de la 008 pide las estadísticas `read` en la tabla, "
        "sin tool dedicada"),
    ("POST", "/host/reload"): (
        "spec 022: CAP-084 la incluye pero FR-076 no le da tool; solo refresca "
        "la información del host (principio IX)"),
    ("POST", "/resolution/check/{check}/run"): (
        "spec 022: FR-077 de la 008 deja los chequeos `confirm` en la tabla"),
    ("POST", "/resolution/check/{check}/options"): (
        "spec 022: FR-077 de la 008 deja los chequeos `confirm` en la tabla"),
    ("POST", "/resolution/healthcheck"): (
        "spec 022: FR-077 de la 008 lo deja `confirm` en la tabla; puede "
        "aplicar los arreglos automáticos del Supervisor"),
}


class TestReglasDeLaClasificacionInicial(unittest.TestCase):
    def test_proxy_de_core_siempre_deny(self) -> None:
        abiertas = sorted(
            str(k) for k, e in ct.SUPERVISOR.items()
            if k[1].startswith(_PROXY_CORE) and e.category != "deny")
        self.assertEqual(abiertas, [])
        # Y el inventario las tiene (si no, este test no probaría nada).
        self.assertGreaterEqual(
            sum(1 for k in ct.SUPERVISOR if k[1].startswith(_PROXY_CORE)), 10)

    # La clase C ya no está «pendiente»: la vigila entera
    # tests/test_command_table_clase_c.py (spec 025, tramo 3).

    def test_clase_a_de_via_dedicada_pendiente_de_su_spec(self) -> None:
        """Clase A de vía D/D+T/D+X: `deny` «pendiente de tool dedicada (spec
        NNN)» con NNN de la matriz, `dedicated` hacia una tool de una familia
        de la 1.2.0 cuando su sub-feature ya la ha hecho (specs 012 y 029,
        research R-7), o `read`/`confirm` si la clave está en `_POR_LA_TABLA`
        con su spec y su porqué (research R-5 de la 013). Que la tool exista y
        su familia coincida lo comprueba `test_tool_existe_y_familia_coincide`.

        Control negativo (T018 g de la 012), comprobado: pasar
        `system_log/list` a `read` → cae este test nombrándola. Dejarla en
        `deny` «pendiente (spec 012)» no lo hace caer (era el estado anterior
        y sigue siendo válido aquí): eso lo vigila el test de la genérica
        (`TestDedicadasDeLaSpec012` de test_tools_generic_commands.py).

        Spec 016 (T016 g): además, la familia anotada en la entrada es la de
        su tool. Control negativo comprobado: con `config_entries/update` en
        `read` → cae nombrándola."""
        matriz = _matriz_008()
        tools = _tool_a_familia()
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
                    if e.tool in _DE_LA_1_1_2_AMPLIADAS:
                        continue
                    # Spec 016: y la familia de la entrada es la de su tool.
                    if (familia is None or familia.desde != "1.2.0"
                            or familia.nombre == "generic_commands"
                            or e.family != familia.nombre):
                        malas.append(f"{k} ({f['cap']}): dedicated hacia {e.tool!r} "
                                     f"de {e.family!r}")
                    continue
                if k in _POR_LA_TABLA and e.category in {"read", "confirm"}:
                    spec = re.match(r"spec (\d{3}): ", _POR_LA_TABLA[k])
                    if spec and spec.group(1) in subs:
                        continue
                m = re.fullmatch(r"pendiente de tool dedicada \(spec (\d{3})\)", e.reason)
                if e.category != "deny" or not m or m.group(1) not in subs:
                    malas.append(f"{k} ({f['cap']}, {via}, {subs}): {e.category} {e.reason!r}")
        self.assertEqual(malas, [], "\n".join(malas))


class TestCapitulosDeLa020(unittest.TestCase):
    """Spec 020, T043 (FR-013, FR-015, SC-002): no queda ninguna entrada
    «(spec 020)» y las doce de CAP-050 y CAP-054 tienen la categoría de
    data-model, con su tool o su familia."""

    _ESPERADAS = {
        "recorder/clear_statistics": ("dedicated", "ha_clear_statistics", "recorder"),
        "recorder/change_statistics_unit": ("dedicated", "ha_change_statistics_unit", "recorder"),
        "recorder/update_statistics_metadata": ("dedicated", "ha_update_statistics_metadata",
                                                "recorder"),
        "recorder/adjust_sum_statistics": ("dedicated", "ha_adjust_statistics_sum", "recorder"),
        "recorder/import_statistics": ("dedicated", "ha_import_statistics", "recorder"),
        "recorder/update_statistics_issues": ("confirm", None, "generic_commands"),
        "energy/get_prefs": ("dedicated", "ha_get_energy_prefs", "energy"),
        "energy/save_prefs": ("dedicated", "ha_update_energy_prefs", "energy"),
        "energy/validate": ("read", None, "generic_commands"),
        "energy/info": ("read", None, "generic_commands"),
        "energy/solar_forecast": ("read", None, "generic_commands"),
        "energy/fossil_energy_consumption": ("read", None, "generic_commands"),
    }

    def test_ninguna_pendiente_de_la_020(self) -> None:
        pendientes = sorted(str(k) for tabla in (ct.CORE_WS, ct.SUPERVISOR)
                            for k, e in tabla.items() if "(spec 020)" in e.reason)
        self.assertEqual(pendientes, [])

    def test_las_doce_con_su_categoria(self) -> None:
        for comando, (categoria, tool, familia) in self._ESPERADAS.items():
            with self.subTest(comando=comando):
                e = ct.CORE_WS[comando]
                self.assertEqual((e.category, e.tool, e.family, e.cap),
                                 (categoria, tool, familia,
                                  "CAP-054" if comando.startswith("energy/") else "CAP-050"))
                # Ninguna sale a internet (research R-5).
                self.assertFalse(e.open_world)


# Spec 013 (data-model, «A dedicated»): las rutas de logs de CAP-081 y su tool.
_LOGS_013: dict[tuple[str, str], tuple[str, str]] = {
    **{("GET", f"/core/logs{s}"): ("sv_get_core_logs", "system_diagnostics")
       for s in ("", "/latest", "/boots/{bootid}")},
    **{("GET", f"/supervisor/logs{s}"): ("sv_get_supervisor_logs", "system_diagnostics")
       for s in ("", "/latest", "/boots/{bootid}")},
    **{("GET", f"/{p}/logs{s}"): ("sv_get_plugin_logs", "system_diagnostics")
       for p in ("dns", "audio", "multicast") for s in ("", "/latest", "/boots/{bootid}")},
    **{("GET", r): ("sv_get_host_logs", "system_diagnostics") for r in (
        "/host/logs", "/host/logs/boots/{bootid}", "/host/logs/identifiers/{identifier}",
        "/host/logs/boots/{bootid}/identifiers/{identifier}")},
    ("GET", "/host/logs/identifiers"): ("sv_list_host_log_identifiers", "system_diagnostics"),
    ("GET", "/host/logs/boots"): ("sv_list_boots", "system_diagnostics"),
    ("GET", "/addons/{app}/logs/latest"): ("sv_get_addon_logs", "supervisor"),
    ("GET", "/addons/{app}/logs/boots/{bootid}"): ("sv_get_addon_logs", "supervisor"),
}


class TestLogsDeLa013(unittest.TestCase):
    """FR-017 de la 013: las 23 rutas de logs pasan a `dedicated` en el mismo
    cambio que sus tools, con su CAP-081; `follow` (streaming) y el alias
    legado `/homeassistant/logs*` siguen `deny`.

    Control negativo (T013 f): dejar `/core/logs/latest` como `deny` → cae
    `test_rutas_de_logs_dedicadas` nombrándola.
    """

    def test_rutas_de_logs_dedicadas(self) -> None:
        self.assertEqual(len(_LOGS_013), 23)
        malas = []
        for k, (tool, familia) in _LOGS_013.items():
            e = ct.SUPERVISOR[k]
            esperado = ("dedicated", tool, familia, "CAP-081", f"cubierto por {tool}")
            real = (e.category, e.tool, e.family, e.cap, e.reason)
            if real != esperado:
                malas.append(f"{k}: {real}")
        self.assertEqual(malas, [], "\n".join(malas))

    def test_follow_y_alias_legado_siguen_deny(self) -> None:
        abiertas = sorted(
            str(k) for k, e in ct.SUPERVISOR.items()
            if "/logs" in k[1]
            and (k[1].endswith("/follow") or k[1].startswith("/homeassistant/"))
            and e.category != "deny")
        self.assertEqual(abiertas, [])
        self.assertGreaterEqual(
            sum(1 for k in ct.SUPERVISOR if "/logs" in k[1] and k[1].endswith("/follow")), 15)

    def test_ninguna_ruta_de_logs_pendiente_de_la_013(self) -> None:
        pendientes = sorted(
            str(k) for k, e in ct.SUPERVISOR.items()
            if "/logs" in k[1] and e.reason == "pendiente de tool dedicada (spec 013)")
        self.assertEqual(pendientes, [])



# Spec 013, tramo 2 (data-model): disco, host y OS (CAP-085) a `dedicated`.
_HOST_013: dict[tuple[str, str], str] = {
    ("GET", "/host/services"): "sv_list_host_services",
    ("GET", "/host/disks/{disk}/usage"): "sv_get_disk_usage",
    ("GET", "/os/info"): "sv_get_os_info",
    ("GET", "/os/config/swap"): "sv_get_swap",
    ("GET", "/os/datadisk/list"): "sv_list_datadisk_candidates",
}

# Las que pasan a `read` (FR-018 de la 013) con su CAP.
_READ_013: dict[tuple[str, str], str] = {
    ("GET", "/jobs/info"): "CAP-087",
    ("GET", "/resolution/issue/{issue}/suggestions"): "CAP-087",
    ("GET", "/host/disks"): "CAP-085",
}

# Las de CAP-088 y CAP-089 que siguen `read` (FR-019, FR-020 de la 013).
_READ_SIN_CAMBIO_013: dict[tuple[str, str], str] = {
    **{("GET", r): "CAP-088" for r in (
        "/hardware/info", "/hardware/audio", "/security/info", "/docker/info",
        "/time/info")},
    **{("GET", r): "CAP-089" for r in (
        "/network/info", "/network/interface/{interface}/info",
        "/network/interface/{interface}/accesspoints")},
}


class TestDiscoHostYOsDeLa013(unittest.TestCase):
    """FR-017…FR-019 de la 013: las cinco rutas de CAP-085 son `dedicated`
    con su tool; `/jobs/info`, las sugerencias de un issue y `/host/disks`
    pasan a `read` con su porqué en `_POR_LA_TABLA`; las de hardware, Docker,
    hora, seguridad y red siguen `read`, y la comprobación de integridad
    sigue `deny` (desviación de FR-047 de la 008: el Supervisor 2026.11.0
    responde 410).

    Controles negativos (T027): (d) dejar `/jobs/info` como `deny` → cae
    `test_tres_rutas_a_read`; (e) pasar `/security/integrity` a `confirm` →
    cae `test_integridad_sigue_deny`.
    """

    def test_cinco_rutas_dedicadas(self) -> None:
        malas = []
        for k, tool in _HOST_013.items():
            e = ct.SUPERVISOR[k]
            esperado = ("dedicated", tool, "system_diagnostics", "CAP-085",
                        f"cubierto por {tool}")
            real = (e.category, e.tool, e.family, e.cap, e.reason)
            if real != esperado:
                malas.append(f"{k}: {real}")
        self.assertEqual(malas, [], "\n".join(malas))

    def test_tres_rutas_a_read(self) -> None:
        malas = []
        for k, cap in _READ_013.items():
            e = ct.SUPERVISOR[k]
            if (e.category, e.family, e.cap, e.tool) != ("read", "generic_commands", cap, None):
                malas.append(f"{k}: {(e.category, e.family, e.cap, e.tool)}")
            elif "solo lee" not in e.reason:
                malas.append(f"{k}: el motivo no dice que solo lee: {e.reason!r}")
        self.assertEqual(malas, [], "\n".join(malas))
        # Las de la 013 en `_POR_LA_TABLA`; otras specs suman las suyas (020).
        self.assertEqual(set(_READ_013), {k for k, v in _POR_LA_TABLA.items()
                                          if v.startswith("spec 013: ")})

    def test_hardware_y_red_siguen_read(self) -> None:
        malas = sorted(
            str(k) for k, cap in _READ_SIN_CAMBIO_013.items()
            if (ct.SUPERVISOR[k].category, ct.SUPERVISOR[k].cap) != ("read", cap))
        self.assertEqual(malas, [])

    def test_integridad_sigue_deny(self) -> None:
        e = ct.SUPERVISOR[("POST", "/security/integrity")]
        self.assertEqual(e.category, "deny")
        self.assertIn("410", e.reason)

    def test_ninguna_entrada_pendiente_de_la_013(self) -> None:
        pendientes = sorted(
            str(k) for k, e in _todas() if "spec 013" in e.reason)
        self.assertEqual(pendientes, [])


# Spec 019, tramo 1 (data-model): las seis rutas de montajes (CAP-083).
_MOUNTS_019: dict[tuple[str, str], str] = {
    ("GET", "/mounts"): "sv_list_mounts",
    ("POST", "/mounts"): "sv_create_mount",
    ("PUT", "/mounts/{mount}"): "sv_update_mount",
    ("DELETE", "/mounts/{mount}"): "sv_delete_mount",
    ("POST", "/mounts/{mount}/reload"): "sv_reload_mount",
    ("POST", "/mounts/options"): "sv_set_default_backup_mount",
}
# Tramo 2: las tres de ajustes de backup (`/backups`), misma familia.
_BACKUP_SETTINGS_019: dict[tuple[str, str], str] = {
    ("GET", "/backups/info"): "sv_get_backup_settings",
    ("POST", "/backups/options"): "sv_set_backup_settings",
    ("POST", "/backups/reload"): "sv_reload_backups",
}


class TestMontajesDeLa019(unittest.TestCase):
    """FR-015 de la 019: las 9 rutas de CAP-083 (6 de `/mounts` en el
    tramo 1 y 3 de `/backups` en el 2) pasan a `dedicated` con su tool en el
    mismo cambio, familia `mounts` y CAP-083; no queda ninguna «spec 019».

    Controles negativos: dejar `POST /mounts` como `deny` (T016 i) o
    `POST /backups/options` como `deny` (T030 e) → cae
    `test_rutas_de_montajes_dedicadas` nombrándola.
    """

    def test_rutas_de_montajes_dedicadas(self) -> None:
        malas = []
        for k, tool in {**_MOUNTS_019, **_BACKUP_SETTINGS_019}.items():
            e = ct.SUPERVISOR[k]
            esperado = ("dedicated", tool, "mounts", "CAP-083", f"cubierto por {tool}")
            real = (e.category, e.tool, e.family, e.cap, e.reason)
            if real != esperado:
                malas.append(f"{k}: {real}")
        self.assertEqual(malas, [], "\n".join(malas))

    def test_ninguna_ruta_de_montajes_pendiente(self) -> None:
        pendientes = sorted(
            str(k) for k, e in ct.SUPERVISOR.items()
            if k[1].startswith("/mounts") and e.category != "dedicated")
        self.assertEqual(pendientes, [])
        quedan = sorted(str(k) for k, e in ct.SUPERVISOR.items()
                        if "spec 019" in e.reason)
        self.assertEqual(quedan, [])

# Spec 015, tramo 1 (data-model, «Entradas de la tabla que cambian»): clave →
# (tool, CAP). `None` donde el inventario no tiene CAP: `/refresh_updates` es
# de clase B y `hassio/update/core` estaba «cubierto».
_ACTUALIZACIONES_015: dict[str | tuple[str, str], tuple[str, str | None]] = {
    ("GET", "/available_updates"): ("sv_list_available_updates", "CAP-080"),
    ("POST", "/refresh_updates"): ("sv_check_for_updates", None),
    ("POST", "/reload_updates"): ("sv_check_for_updates", "CAP-080"),
    ("POST", "/core/update"): ("sv_update_core", "CAP-080"),
    "hassio/update/core": ("sv_update_core", None),
}


class TestActualizacionesDeLa015(unittest.TestCase):
    """FR-016 de la 015: las cinco entradas del tramo 1 pasan a `dedicated`
    con su tool, la familia `system_updates` y la CAP del inventario en las de
    clase A; los alias legados siguen `deny`.

    Control negativo (T015 g): dejar `/core/update` como `deny` → cae
    `test_cinco_entradas_dedicadas` nombrándola.
    """

    def test_cinco_entradas_dedicadas(self) -> None:
        malas = []
        for k, (tool, cap) in _ACTUALIZACIONES_015.items():
            e = ct.CORE_WS[k] if isinstance(k, str) else ct.SUPERVISOR[k]
            real = (e.category, e.tool, e.family, e.cap)
            if real != ("dedicated", tool, "system_updates", cap):
                malas.append(f"{k}: {real}")
            elif not e.reason.startswith(f"cubierto por {tool}"):
                malas.append(f"{k}: motivo {e.reason!r}")
        self.assertEqual(malas, [], "\n".join(malas))

    def test_por_que_las_que_no_son_la_ruta_de_la_tool(self) -> None:
        # data-model: `/reload_updates` no es la ruta que usa la tool (no
        # recarga la tienda) y `hassio/update/core` es la misma actualización
        # por Core, sin la vista previa.
        self.assertIn("/refresh_updates", ct.SUPERVISOR[("POST", "/reload_updates")].reason)
        self.assertIn("vista previa", ct.CORE_WS["hassio/update/core"].reason)

    def test_tramo_2_os_y_supervisor_dedicadas(self) -> None:
        # Tramo 2 (T022): las rutas de actualizar el OS y el Supervisor, a sus
        # tools. Control negativo (T028): con `/os/update` de vuelta a
        # `deny`, cae nombrándola.
        malas = []
        for k, tool in ((("POST", "/os/update"), "sv_update_os"),
                        (("POST", "/supervisor/update"), "sv_update_supervisor")):
            e = ct.SUPERVISOR[k]
            real = (e.category, e.tool, e.family, e.cap)
            if real != ("dedicated", tool, "system_updates", "CAP-080"):
                malas.append(f"{k}: {real}")
            elif e.reason != f"cubierto por {tool}":
                malas.append(f"{k}: motivo {e.reason!r}")
        self.assertEqual(malas, [], "\n".join(malas))

    def test_tramo_3_release_notes_dedicada(self) -> None:
        # Tramo 3 (T038): `update/release_notes` a su tool, con la familia y la
        # CAP-064. Control negativo (T045): de vuelta a `deny` → cae.
        e = ct.CORE_WS["update/release_notes"]
        self.assertEqual(
            (e.category, e.tool, e.family, e.cap, e.reason),
            ("dedicated", "ha_get_update_release_notes", "system_updates", "CAP-064",
             "cubierto por ha_get_update_release_notes"))

    def test_ninguna_pendiente_de_la_015(self) -> None:
        # Al cerrar la 015 no queda ninguna entrada «pendiente (spec 015)».
        pendientes = sorted(str(k) for k, e in (*ct.CORE_WS.items(), *ct.SUPERVISOR.items())
                            if "spec 015" in e.reason)
        self.assertEqual(pendientes, [])

    def test_alias_legados_siguen_deny(self) -> None:
        for k in (("POST", "/homeassistant/update"), ("GET", "/supervisor/available_updates")):
            with self.subTest(k=k):
                self.assertEqual(ct.SUPERVISOR[k].category, "deny")

    def test_lo_de_otras_specs_no_cambia(self) -> None:
        # Las apps siguen con su tool de la 1.1.2; los plugins, `confirm` (022).
        self.assertEqual(ct.CORE_WS["hassio/update/addon"].tool, "sv_update_addon")
        for p in ("audio", "cli", "dns", "multicast", "observer"):
            with self.subTest(p=p):
                self.assertEqual(ct.SUPERVISOR[("POST", f"/{p}/update")].category, "confirm")


# Spec 030, tramo 1 (data-model, «Entradas de la tabla que cambian»): las siete
# rutas de repositorios y recarga de la tienda (CAP-082) → (tool, motivo).
_TIENDA_030_T1: dict[tuple[str, str], tuple[str, str]] = {
    ("GET", "/store"): (
        "sv_list_store_repositories",
        "cubierto por sv_list_store_repositories (repositorios) y sv_list_addons (apps)"),
    ("GET", "/store/repositories"): (
        "sv_list_store_repositories", "cubierto por sv_list_store_repositories"),
    ("GET", "/store/repositories/{repository}"): (
        "sv_list_store_repositories",
        "cubierto por sv_list_store_repositories(repository=…)"),
    ("POST", "/store/repositories"): (
        "sv_add_store_repository", "cubierto por sv_add_store_repository"),
    ("DELETE", "/store/repositories/{repository}"): (
        "sv_remove_store_repository", "cubierto por sv_remove_store_repository"),
    ("POST", "/store/repositories/{repository}/repair"): (
        "sv_repair_store_repository", "cubierto por sv_repair_store_repository"),
    ("POST", "/store/reload"): ("sv_reload_store", "cubierto por sv_reload_store"),
}

# Spec 030, tramo 2: las ocho restantes → (tool, familia, CAP, motivo). Tres
# rutas con `{version}` apuntan a la tool SIN versión de la 1.1.2 porque el
# Supervisor 2026.11.0 ignora `{version}` (research R-2; desviación de FR-051).
_TIENDA_030_T2: dict[tuple[str, str], tuple[str, str, str, str]] = {
    ("GET", "/store/addons/{app}/changelog"): (
        "sv_get_addon_changelog", "app_store", "CAP-082",
        "cubierto por sv_get_addon_changelog"),
    ("GET", "/store/addons/{app}/documentation"): (
        "sv_get_addon_documentation", "app_store", "CAP-082",
        "cubierto por sv_get_addon_documentation"),
    ("GET", "/store/addons/{app}/availability"): (
        "sv_get_addon_availability", "app_store", "CAP-082",
        "cubierto por sv_get_addon_availability"),
    ("GET", "/store/addons/{app}/{version}"): (
        "sv_get_addon", "supervisor", "CAP-082",
        "el Supervisor 2026.11.0 ignora `{version}` y devuelve la ficha actual: "
        "cubierto por sv_get_addon"),
    ("POST", "/store/addons/{app}/install/{version}"): (
        "sv_install_addon", "supervisor", "CAP-082",
        "el Supervisor 2026.11.0 ignora `{version}` e instala la de la tienda: "
        "cubierto por sv_install_addon"),
    ("POST", "/store/addons/{app}/update/{version}"): (
        "sv_update_addon", "supervisor", "CAP-082",
        "el Supervisor 2026.11.0 ignora `{version}` y actualiza a la de la tienda: "
        "cubierto por sv_update_addon"),
    ("POST", "/addons/{app}/options/validate"): (
        "sv_set_addon_options", "supervisor", "CAP-093",
        "cubierto por sv_set_addon_options (valida en la vista previa)"),
    ("POST", "/addons/{app}/rebuild"): (
        "sv_rebuild_addon", "app_store", "CAP-093", "cubierto por sv_rebuild_addon"),
}

# Iconos, logos y alias legados de la tienda: clase B, siguen `deny`.
_TIENDA_DENY_030: tuple[tuple[str, str], ...] = (
    ("GET", "/store/addons/{app}/icon"), ("GET", "/store/addons/{app}/logo"),
    ("GET", "/addons/{app}/icon"), ("GET", "/addons/{app}/logo"),
    ("GET", "/addons/{app}/changelog"), ("GET", "/addons/{app}/documentation"),
    ("POST", "/addons/{app}/install"), ("POST", "/addons/{app}/update"),
    ("POST", "/addons/reload"),
)


class TestTiendaDeLa030(unittest.TestCase):
    """FR-014 de la 030: las siete rutas de repositorios y recarga (tramo 1)
    y las ocho de fichas, versiones, validación y reconstrucción (tramo 2)
    pasan a `dedicated`; iconos, logos y alias legados siguen `deny` (clase
    B); no queda ninguna «spec 030».

    Control negativo (T012 g): dejar `POST /store/repositories` como `deny`
    → cae `test_siete_rutas_dedicadas` nombrándola."""

    def test_siete_rutas_dedicadas(self) -> None:
        self.assertEqual(len(_TIENDA_030_T1), 7)
        malas = []
        for k, (tool, motivo) in _TIENDA_030_T1.items():
            e = ct.SUPERVISOR[k]
            esperado = ("dedicated", tool, "app_store", "CAP-082", motivo)
            real = (e.category, e.tool, e.family, e.cap, e.reason)
            if real != esperado:
                malas.append(f"{k}: {real}")
        self.assertEqual(malas, [], "\n".join(malas))

    def test_iconos_logos_y_alias_siguen_deny(self) -> None:
        abiertas = sorted(
            str(k) for k in _TIENDA_DENY_030
            if ct.SUPERVISOR[k].category != "deny" or "clase B" not in ct.SUPERVISOR[k].reason)
        self.assertEqual(abiertas, [])

    def test_ocho_rutas_del_tramo_2(self) -> None:
        """T022 (FR-011, FR-014). Control negativo (T026 g): dejar
        `POST /addons/{app}/rebuild` como `deny` → cae este test nombrándola,
        `test_ninguna_pendiente` y el de las genéricas."""
        self.assertEqual(len(_TIENDA_030_T2), 8)
        malas = []
        for k, (tool, familia, cap, motivo) in _TIENDA_030_T2.items():
            e = ct.SUPERVISOR[k]
            real = (e.category, e.tool, e.family, e.cap, e.reason)
            if real != ("dedicated", tool, familia, cap, motivo):
                malas.append(f"{k}: {real}")
        self.assertEqual(malas, [], "\n".join(malas))

    def test_ninguna_pendiente(self) -> None:
        pendientes = sorted(
            str(k) for k, e in ct.SUPERVISOR.items() if "spec 030" in e.reason)
        self.assertEqual(pendientes, [])
        texto = (_RAIZ / "hermes" / "src" / "hermes" / "command_table.py").read_text(
            encoding="utf-8")
        self.assertEqual(texto.count("spec 030"), 0)


# Spec 022, tramo 1 (data-model, «Entradas de la tabla que cambian»).
_CONTROL_022: dict[tuple[str, str], str] = {
    ("POST", "/core/start"): "sv_start_core",
    ("POST", "/core/rebuild"): "sv_rebuild_core",
    ("POST", "/core/options"): "sv_set_core_options",
    ("POST", "/supervisor/reload"): "sv_reload_supervisor",
    ("POST", "/supervisor/restart"): "sv_restart_supervisor",
    ("POST", "/supervisor/repair"): "sv_repair_supervisor",
    ("POST", "/supervisor/options"): "sv_set_supervisor_options",
}
_POR_LA_TABLA_022: dict[tuple[str, str], tuple[str, str]] = {
    ("GET", "/core/stats"): ("read", "solo lee"),
    ("GET", "/supervisor/stats"): ("read", "solo lee"),
    ("POST", "/host/reload"): ("confirm", "no corta nada"),
}


class TestEntradasDeLa022(unittest.TestCase):
    """FR-013 de la 022 (parte 1): las 7 rutas de CAP-084 con tool pasan a
    `dedicated` (familia `system_control`); las estadísticas a `read` y
    `/host/reload` a `confirm`, con su porqué en `_POR_LA_TABLA`; `/core/stop`
    y los alias `/homeassistant/*` siguen `deny`. Quedan 4 «spec 022» (las de
    CAP-087, del tramo 2; el tramo 2 las deja en 0).

    Control negativo (T014 h): dejar `/supervisor/restart` como `deny` → cae
    `test_siete_dedicadas` (y el de la genérica en test_tools_control_tabla).
    """

    def test_siete_dedicadas(self) -> None:
        malas = []
        for k, tool in _CONTROL_022.items():
            e = ct.SUPERVISOR[k]
            esperado = ("dedicated", tool, "system_control", "CAP-084", f"cubierto por {tool}")
            real = (e.category, e.tool, e.family, e.cap, e.reason)
            if real != esperado:
                malas.append(f"{k}: {real}")
        self.assertEqual(malas, [], "\n".join(malas))

    def test_tres_por_la_tabla(self) -> None:
        for k, (categoria, frase) in _POR_LA_TABLA_022.items():
            with self.subTest(clave=k):
                e = ct.SUPERVISOR[k]
                self.assertEqual((e.category, e.family, e.cap, e.tool),
                                 (categoria, "generic_commands", "CAP-084", None))
                self.assertIn(frase, e.reason)
                self.assertTrue(_POR_LA_TABLA[k].startswith("spec 022: "))

    def test_parar_core_y_alias_siguen_deny(self) -> None:
        self.assertEqual(ct.SUPERVISOR[("POST", "/core/stop")].category, "deny")
        abiertas = sorted(str(k) for k, e in ct.SUPERVISOR.items()
                          if k[1].startswith("/homeassistant/") and e.category != "deny")
        self.assertEqual(abiertas, [])

    def test_ninguna_pendiente_de_la_022(self) -> None:
        # Tramo 2 (T023): no queda ninguna «spec 022».
        quedan = sorted(k for k, e in ct.SUPERVISOR.items() if "spec 022" in e.reason)
        self.assertEqual(quedan, [])


# Spec 022, tramo 2 (data-model): CAP-087 escritura.
_CHEQUEOS_022: dict[tuple[str, str], str] = {
    ("POST", "/resolution/check/{check}/run"): "ejecuta ya un chequeo",
    ("POST", "/resolution/check/{check}/options"): "desactivarlo oculta ese problema",
    ("POST", "/resolution/healthcheck"): "puede aplicar los arreglos automáticos",
}


class TestEntradasDeLa022Tramo2(unittest.TestCase):
    """FR-013 de la 022 (parte 2): aplicar una sugerencia pasa a `dedicated`
    (`sv_apply_resolution_suggestion`, familia `resolution_fixes`); los dos
    chequeos y el healthcheck, a `confirm` con su porqué en `_POR_LA_TABLA`.

    Control negativo (T028 i): dejar `/resolution/check/{check}/run` como
    `deny` → cae `test_chequeos_confirm` (y el de la genérica en
    test_tools_control_tabla).
    """

    def test_aplicar_dedicada(self) -> None:
        e = ct.SUPERVISOR[("POST", "/resolution/suggestion/{suggestion}")]
        self.assertEqual(
            (e.category, e.tool, e.family, e.cap, e.reason),
            ("dedicated", "sv_apply_resolution_suggestion", "resolution_fixes",
             "CAP-087", "cubierto por sv_apply_resolution_suggestion"))

    def test_chequeos_confirm(self) -> None:
        for k, frase in _CHEQUEOS_022.items():
            with self.subTest(clave=k):
                e = ct.SUPERVISOR[k]
                self.assertEqual((e.category, e.family, e.cap, e.tool),
                                 ("confirm", "generic_commands", "CAP-087", None))
                self.assertIn(frase, e.reason)
                self.assertTrue(_POR_LA_TABLA[k].startswith("spec 022: "))

    def test_descartar_sigue_igual(self) -> None:
        # US6: descartar sigue en `diagnostics` (1.1.2).
        e = ct.SUPERVISOR[("DELETE", "/resolution/suggestion/{suggestion}")]
        self.assertEqual((e.category, e.tool, e.family),
                         ("dedicated", "sv_dismiss_resolution_suggestion", "diagnostics"))


if __name__ == "__main__":
    unittest.main()
