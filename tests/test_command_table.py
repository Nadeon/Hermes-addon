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
from scripts.inventario.generar_tabla import MOTIVO_PROXY_SUPERVISOR

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

    def test_dedicadas_de_la_021(self) -> None:
        """Spec 021, tramo a (T002; FR-003, FR-018): los cinco comandos de
        CAP-053 y CAP-055 son `dedicated` hacia su tool, con la forma que
        escribe el generador y su clave en `_DEDICADAS_INICIALES`; y
        `config/core/detect` es `read` de mundo abierto con su porqué en
        `_POR_LA_TABLA`.
        Control negativo (T018 f): `homeassistant/expose_entity` en `deny` →
        cae."""
        from scripts.inventario.generar_tabla import _DEDICADAS_INICIALES

        cinco = {
            "config/core/update": ("ha_update_core_config", "core_config", "CAP-053"),
            "homeassistant/expose_entity": (
                "ha_set_entity_exposure", "assistant_exposure", "CAP-055"),
            "homeassistant/expose_entity/list": (
                "ha_list_exposed_entities", "assistant_exposure", "CAP-055"),
            "homeassistant/expose_new_entities/get": (
                "ha_list_exposed_entities", "assistant_exposure", "CAP-055"),
            "homeassistant/expose_new_entities/set": (
                "ha_set_expose_new_entities", "assistant_exposure", "CAP-055"),
            # Tramo b (T027): los cuatro de CAP-056, familia `users`.
            "config/auth/list": ("ha_list_users", "users", "CAP-056"),
            "config/auth/create": ("ha_create_user", "users", "CAP-056"),
            "config/auth/update": ("ha_update_user", "users", "CAP-056"),
            "config/auth/delete": ("ha_delete_user", "users", "CAP-056"),
            # Tramo c (T045): los tres de CAP-069, familia `core_network`.
            "network/configure": ("ha_update_network_config", "core_network", "CAP-069"),
            "http/config/configure": ("ha_update_http_config", "core_network", "CAP-069"),
            "http/config/promote": ("ha_promote_http_config", "core_network", "CAP-069"),
        }
        self.assertEqual(len(cinco), 12)
        for comando, (tool, familia, cap) in cinco.items():
            with self.subTest(comando=comando):
                e = ct.CORE_WS[comando]
                self.assertEqual(
                    (e.category, e.reason, e.family, e.tool, e.cap),
                    ("dedicated", f"cubierto por {tool}", familia, tool, cap))
                self.assertEqual(_DEDICADAS_INICIALES[comando], tool)
        e = ct.CORE_WS["config/core/detect"]
        self.assertEqual((e.category, e.family, e.cap, e.open_world, e.tool),
                         ("read", "generic_commands", "CAP-053", True, None))
        self.assertIn("servicio externo", e.reason)
        self.assertIn("no guarda nada", e.reason)
        self.assertTrue(_POR_LA_TABLA["config/core/detect"].startswith("spec 021: "))
        self.assertNotIn("config/core/detect", _DEDICADAS_INICIALES)
        # Tramo c (T045, SC-002): ya no queda nada «pendiente (spec 021)» en
        # ninguna de las dos tablas. Control negativo (T056 h):
        # `http/config/promote` en `deny` pendiente → cae.
        pendientes = sorted(str(k) for k, e in _todas() if "(spec 021)" in e.reason)
        self.assertEqual(pendientes, [])

    def test_cap_074_por_la_tabla(self) -> None:
        """Spec 021, tramo c (T043; FR-016): las cuatro de analytics y labs
        siguen por las genéricas con `cap="CAP-074"`; `analytics/preferences`
        es de mundo abierto (activar el envío manda datos a los servidores de
        Home Assistant). Control negativo (T056 g): sin `open_world` → cae."""
        esperado = {
            "analytics": ("read", False),
            "labs/list": ("read", False),
            "analytics/preferences": ("confirm", True),
            "labs/update": ("confirm", False),
        }
        for comando, (categoria, sale) in esperado.items():
            with self.subTest(comando=comando):
                e = ct.CORE_WS[comando]
                self.assertEqual((e.category, e.cap, e.open_world, e.family),
                                 (categoria, "CAP-074", sale, "generic_commands"))

    def test_credenciales_y_sesiones_siguen_deny(self) -> None:
        """Spec 021, tramo b (T027; FR-012): `auth/refresh_tokens` queda `deny`
        revisado (research R-5, en `_DENY_TRAS_REVISION`), y lo que maneja
        contraseñas o revoca sesiones sigue `deny` de clase D (D-01 de la
        008): ninguna tool de usuarios lo abre."""
        e = ct.CORE_WS["auth/refresh_tokens"]
        self.assertEqual((e.category, e.family, e.cap, e.tool),
                         ("deny", "generic_commands", "CAP-056", None))
        self.assertIn("propia conexión", e.reason)
        self.assertNotIn("pendiente", e.reason)
        self.assertTrue(_DENY_TRAS_REVISION["auth/refresh_tokens"].startswith("spec 021: "))
        clase_d = [f"config/auth_provider/homeassistant/{c}" for c in (
            "admin_change_password", "admin_change_username", "change_password",
            "create", "delete")] + [
            "auth/delete_refresh_token", "auth/refresh_token_set_expiry",
            "auth/delete_all_refresh_tokens", "auth/long_lived_access_token"]
        for comando in clase_d:
            with self.subTest(comando=comando):
                e = ct.CORE_WS[comando]
                self.assertEqual(e.category, "deny")
                self.assertIn("(clase D)", e.reason)
        # `auth/current_user` lo usa Hermes por dentro; la genérica, no.
        self.assertEqual(ct.CORE_WS["auth/current_user"].category, "deny")

    def test_dedicadas_de_la_031(self) -> None:
        """Spec 031, T011 (FR-017): los dos comandos de agentes y ajustes de
        los backups de HA son `dedicated` hacia su tool de
        `backup_integration`, con la forma exacta que escribe el generador
        (data-model sección 13), y el mapa del generador los nombra. Los dos
        de `hassio/update/config/*` (HALLAZGO del tramo 1) son `deny` con el
        motivo del proxy del Supervisor, también desde el mapa.
        Control negativo (T015 d): `backup/config/update` en `deny` → cae.

        Tramo 2 (T027): crear y borrar, `dedicated` SIN `cap` (sus filas del
        inventario son `cubierto`, sin CAP) y sin « (acción de HA)».

        Tramo 3 (T042): restaurar, igual que los del tramo 2, y ya no queda
        ninguna entrada «pendiente de tool dedicada (spec 031)» en ninguna
        tabla (SC-001). Control negativo (T045 g): `backup/restore` en `deny`
        → cae."""
        from scripts.inventario.generar_tabla import _DEDICADAS_INICIALES, _Deny

        tramo_2 = {
            "backup/delete": "ha_delete_backup",
            "backup/generate": "ha_create_backup",
            "backup/generate_with_automatic_settings": "ha_create_automatic_backup",
            "backup/restore": "ha_restore_backup",
        }
        for comando, tool in tramo_2.items():
            with self.subTest(comando=comando):
                e = ct.CORE_WS[comando]
                self.assertEqual(
                    (e.category, e.reason, e.family, e.tool, e.cap),
                    ("dedicated", f"cubierto por {tool}", "backup_integration", tool, None))
                self.assertEqual(_DEDICADAS_INICIALES[comando], tool)

        tramo_1 = {
            "backup/agents/info": "ha_list_backup_agents",
            "backup/config/update": "ha_update_backup_config",
        }
        for comando, tool in tramo_1.items():
            with self.subTest(comando=comando):
                e = ct.CORE_WS[comando]
                self.assertEqual(
                    (e.category, e.reason, e.family, e.tool, e.cap),
                    ("dedicated", f"cubierto por {tool}", "backup_integration", tool,
                     "CAP-057"))
                self.assertEqual(_DEDICADAS_INICIALES[comando], tool)
        for comando in ("hassio/update/config/info", "hassio/update/config/update"):
            with self.subTest(comando=comando):
                e = ct.CORE_WS[comando]
                self.assertEqual(
                    (e.category, e.reason, e.family, e.tool, e.cap),
                    ("deny", MOTIVO_PROXY_SUPERVISOR, "generic_commands", None, "CAP-057"))
                self.assertEqual(_DEDICADAS_INICIALES[comando], _Deny(MOTIVO_PROXY_SUPERVISOR))
        pendientes = sorted(str(k) for k, e in _todas() if "(spec 031)" in e.reason)
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
    # Spec 021 (FR-003, FR-071 de la 008): propone la configuración del
    # núcleo consultando un servicio externo de geolocalización por IP.
    "config/core/detect": "consulta un servicio externo de geolocalización por IP",
    # Spec 024 (research R-5): `async_get_segments` lo implementa cada
    # integración; la de Roborock refresca el mapa por red al leer.
    "vacuum/get_segments": "algunas integraciones piden los segmentos al aspirador o a su nube",
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
        # Las dos que antes eran `dedicated` hacia `ha_call_service` sin decir
        # qué acción (T046) tienen ya su tool: `hassio/update/core` desde la
        # 015 y `backup/generate_with_automatic_settings` desde la 031 (tramo
        # 2). Hoy ningún motivo remite a `ha_call_service` con una acción; el
        # bucle de arriba queda de guarda para el que lo haga.
        self.assertEqual(vistos, set())

    def test_ninguna_dedicada_a_ha_call_service_sin_accion(self) -> None:
        # Las que quedan apuntan a una acción del mismo nombre que el comando
        # (p. ej. `calendar/event/create` → `calendar.create_event`), ninguna
        # de la denylist; las dos de T046 ya no son `dedicated` hacia
        # `ha_call_service`: cada una apunta a su tool dedicada (la 015 y la
        # 031, tramo 2).
        for k, tool in (
            ("hassio/update/core", "sv_update_core"),
            ("backup/generate_with_automatic_settings", "ha_create_automatic_backup"),
        ):
            with self.subTest(k=k):
                e = ct.CORE_WS[k]
                self.assertEqual((e.category, e.tool), ("dedicated", tool))

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
    "config/core/detect": (
        "spec 021: FR-071 de la 008 la deja `read` en la tabla; consulta un "
        "servicio externo de geolocalización y no guarda nada"),
    # Spec 024 (research R-1): la 008 manda las preferencias de cámara a la
    # tabla (FR-085); la instantánea sí tiene tool dedicada.
    "camera/get_prefs": (
        "spec 024: lectura de las preferencias de stream (precarga y "
        "orientación); FR-085 de la 008 la manda a la tabla"),
    "camera/update_prefs": (
        "spec 024: escritura de bajo riesgo (precarga y orientación), en dos "
        "pasos; FR-085 de la 008 la manda a la tabla"),
    # Spec 024, tramo 2 (research R-5): las lecturas de CAP-071; la 008
    # (FR-086) solo pide tool para restablecer un dashboard.
    "trace/contexts": (
        "spec 024: lectura de los contextos con traza; FR-086 de la 008 la "
        "manda a la tabla"),
    "frontend/get_themes": (
        "spec 024: lectura de los temas del frontend; FR-086 de la 008 la "
        "manda a la tabla"),
    "webhook/list": (
        "spec 024: lectura de los webhooks con el webhook_id tapado por la "
        "redacción estructural; FR-086 de la 008 la manda a la tabla"),
    "vacuum/get_segments": (
        "spec 024: lectura de los segmentos de un aspirador, de mundo "
        "abierto; FR-086 de la 008 la manda a la tabla"),
    "radio_frequency/list": (
        "spec 024: lectura de los transmisores y receptores de "
        "radiofrecuencia; FR-086 de la 008 la manda a la tabla"),
}


# Spec 021 (T027, research R-5): claves de clase A de vía D que, tras leer el
# código de HA, quedan `deny` con un motivo que NO es «pendiente»: no hay tool
# dedicada posible. Clave → «spec NNN: porqué»; la spec tiene que ser una de
# las de su CAP en la matriz, igual que `_POR_LA_TABLA`. Control negativo
# (T035 f): sin la clave de `auth/refresh_tokens` caen el test de la clase A y
# `test_credenciales_y_sesiones_siguen_deny`.
_DENY_TRAS_REVISION: dict[tuple[str, str] | str, str] = {
    "auth/refresh_tokens": (
        "spec 021: solo da las sesiones del usuario de la conexión (el propio "
        "Hermes), nunca las de otros usuarios; research R-5"),
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
                # Spec 031: lo que el proxy WebSocket del Supervisor no deja
                # mandar a una app no puede tener tool (lo vigila
                # `TestProxyDelSupervisor`).
                if (e.category, e.reason) == ("deny", MOTIVO_PROXY_SUPERVISOR):
                    continue
                if k in _POR_LA_TABLA and e.category in {"read", "confirm"}:
                    spec = re.match(r"spec (\d{3}): ", _POR_LA_TABLA[k])
                    if spec and spec.group(1) in subs:
                        continue
                # Spec 021 (T027): `deny` revisado, con un motivo que no es
                # «pendiente» y la spec que lo revisó en el porqué.
                if (k in _DENY_TRAS_REVISION and e.category == "deny"
                        and "pendiente" not in e.reason):
                    spec = re.match(r"spec (\d{3}): ", _DENY_TRAS_REVISION[k])
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


# Prefijos WS que el proxy del Supervisor 2026.11.0 rechaza a las apps
# (`DENIED_WS_TYPE_PREFIXES` de `supervisor/api/proxy.py`).
_PREFIJOS_DENEGADOS_POR_EL_PROXY = ("hassio/", "supervisor/")


def _fuente_de_cada_tool() -> dict[str, str]:
    """Nombre de cada función de `tools/*.py` → texto de su módulo."""
    out: dict[str, str] = {}
    for path in sorted(_TOOLS_DIR.glob("*.py")):
        texto = path.read_text(encoding="utf-8")
        for n in ast.walk(ast.parse(texto)):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.setdefault(n.name, texto)
    return out


def problemas_proxy_del_supervisor(
    core_ws: dict[str, ct.E], fuentes: dict[str, str],
) -> list[str]:
    """Entradas WS `hassio/*` o `supervisor/*` que prometen algo imposible.

    Hermes es una app y habla con Core por el proxy WebSocket del Supervisor,
    que rechaza esos comandos con «Unauthorized» (HALLAZGO de la 031). En
    `read` o `confirm`, la genérica nunca llegaría a HA; y una `dedicated`
    solo vale si su tool NO manda ese comando por WebSocket (p. ej.
    `hassio/update/addon` → `sv_update_addon`, que va por la API REST del
    Supervisor): el módulo de la tool no puede contener el tipo del comando.
    """
    problemas = []
    for k, e in core_ws.items():
        if not k.startswith(_PREFIJOS_DENEGADOS_POR_EL_PROXY):
            continue
        if e.category in {"read", "confirm"}:
            problemas.append(f"{k}: {e.category}, y el proxy del Supervisor lo rechaza")
        elif e.category == "dedicated":
            fuente = fuentes.get(e.tool or "")
            if fuente is None:
                problemas.append(f"{k}: dedicated hacia {e.tool!r}, que no existe")
            elif f'"{k}"' in fuente:
                problemas.append(f"{k}: {e.tool} manda el comando por WebSocket")
    return problemas


class TestProxyDelSupervisor(unittest.TestCase):
    """Spec 031, HALLAZGO del tramo 1: ninguna entrada WS `hassio/*` o
    `supervisor/*` puede estar en `read` ni en `confirm`, y una `dedicated`
    solo si su tool no manda ese comando por WebSocket.

    Control negativo, comprobado a mano: `supervisor/event` en `read` en
    command_table.py → cae `test_ninguna_entrada_imposible` nombrándola. Y
    queda fijo en `test_control_negativo`."""

    def test_ninguna_entrada_imposible(self) -> None:
        problemas = problemas_proxy_del_supervisor(ct.CORE_WS, _fuente_de_cada_tool())
        self.assertEqual(problemas, [], "\n".join(problemas))
        # Hay entradas que mirar, y una `dedicated` válida (si no, el test no
        # probaría nada).
        self.assertGreaterEqual(
            sum(1 for k in ct.CORE_WS if k.startswith(_PREFIJOS_DENEGADOS_POR_EL_PROXY)), 9)
        self.assertEqual(ct.CORE_WS["hassio/update/addon"].category, "dedicated")

    def test_control_negativo(self) -> None:
        import dataclasses

        tabla = dict(ct.CORE_WS)
        tabla["supervisor/event"] = dataclasses.replace(
            tabla["supervisor/event"], category="read")
        tabla["hassio/update/config/info"] = dataclasses.replace(
            tabla["hassio/update/config/info"], category="confirm")
        fuentes = _fuente_de_cada_tool()
        # Una `sv_update_addon` que mandase `hassio/update/addon` por WS.
        fuentes["sv_update_addon"] += '\nws_send({"type": "hassio/update/addon"})\n'
        problemas = problemas_proxy_del_supervisor(tabla, fuentes)
        self.assertEqual(sorted(p.split(":")[0] for p in problemas),
                         ["hassio/update/addon", "hassio/update/config/info",
                          "supervisor/event"])


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


# Spec 032, tramo 1 (data-model): las cuatro rutas del host y del OS (CAP-086).
_HOST_CONTROL_032: dict[tuple[str, str], str] = {
    ("POST", "/host/shutdown"): "sv_shutdown_host",
    ("POST", "/host/options"): "sv_set_hostname",
    ("POST", "/os/config/swap"): "sv_set_swap",
    ("POST", "/os/boot-slot"): "sv_set_boot_slot",
}


class TestHostControlDeLa032(unittest.TestCase):
    """FR-014 de la 032 (tramo 1): las cuatro rutas de CAP-086 pasan de
    `deny` «spec 032» a `dedicated` con su tool, familia `host_control` y
    CAP-086; quedan solo las tres de la red (tramo 2).

    Control negativo (T012 f): dejar `POST /host/shutdown` como `deny` → cae
    `test_rutas_dedicadas` nombrándola.
    """

    def test_rutas_dedicadas(self) -> None:
        malas = []
        for k, tool in _HOST_CONTROL_032.items():
            e = ct.SUPERVISOR[k]
            esperado = ("dedicated", tool, "host_control", "CAP-086", f"cubierto por {tool}")
            real = (e.category, e.tool, e.family, e.cap, e.reason)
            if real != esperado:
                malas.append(f"{k}: {real}")
        self.assertEqual(malas, [], "\n".join(malas))

    def test_no_queda_ninguna_de_la_032(self) -> None:
        # Desde el tramo 2 tampoco quedan las tres de la red (FR-014).
        quedan = sorted(k for k, e in ct.SUPERVISOR.items() if "spec 032" in e.reason)
        self.assertEqual(quedan, [])
        # Las lecturas que usan las vistas previas no cambian.
        for k in (("GET", "/host/info"), ("GET", "/os/info"), ("GET", "/os/config/swap")):
            self.assertEqual(ct.SUPERVISOR[k].category, "dedicated", k)


# Spec 032, tramo 2 (data-model): las tres rutas de la red del host (CAP-090).
_HOST_NETWORK_032: dict[tuple[str, str], str] = {
    ("POST", "/network/reload"): "sv_reload_network",
    ("POST", "/network/interface/{interface}/update"): "sv_update_network_interface",
    ("POST", "/network/interface/{interface}/vlan/{vlan}"): "sv_create_vlan",
}


class TestHostNetworkDeLa032(unittest.TestCase):
    """FR-014 de la 032 (tramo 2): las tres rutas de CAP-090 pasan de `deny`
    «spec 032» a `dedicated` con su tool, familia `host_network` y CAP-090;
    las lecturas de la red siguen `read` (013).

    Control negativo (T026 h): dejar `POST /network/reload` como `deny` →
    cae `test_rutas_dedicadas` nombrándola.
    """

    def test_rutas_dedicadas(self) -> None:
        malas = []
        for k, tool in _HOST_NETWORK_032.items():
            e = ct.SUPERVISOR[k]
            esperado = ("dedicated", tool, "host_network", "CAP-090", f"cubierto por {tool}")
            real = (e.category, e.tool, e.family, e.cap, e.reason)
            if real != esperado:
                malas.append(f"{k}: {real}")
        self.assertEqual(malas, [], "\n".join(malas))

    def test_las_lecturas_de_red_siguen_read(self) -> None:
        for k in (("GET", "/network/info"),
                  ("GET", "/network/interface/{interface}/info"),
                  ("GET", "/network/interface/{interface}/accesspoints")):
            self.assertEqual(ct.SUPERVISOR[k].category, "read", k)
# Spec 023 (data-model, «Entradas de la tabla»): los cinco comandos de CAP-060
# → (tool, motivo).
_CONVERSACION_023: dict[str, tuple[str, str]] = {
    "conversation/agent/homeassistant/debug": (
        "ha_debug_conversation", "cubierto por ha_debug_conversation"),
    "conversation/agent/homeassistant/language_scores": (
        "ha_list_conversation_agents",
        "cubierto por ha_list_conversation_agents (con include_language_scores=true)"),
    "conversation/agent/list": (
        "ha_list_conversation_agents", "cubierto por ha_list_conversation_agents"),
    "conversation/process": (
        "ha_process_conversation", "cubierto por ha_process_conversation"),
    "conversation/sentences/list": (
        "ha_list_conversation_sentences", "cubierto por ha_list_conversation_sentences"),
}


class TestConversacionDeLa023(unittest.TestCase):
    """FR-008 y FR-009 de la 023 (T011, SC-002): los cinco comandos de
    CAP-060 pasan a `dedicated` con su clave en el mapa del generador; no
    queda ninguna «(spec 023)»; las tres revisadas de CAP-061/CAP-062 dicen lo
    que hacen; `assist_pipeline/run` sigue en `deny` (clase D).

    Control negativo (T016 e): dejar `conversation/process` en `deny` → cae
    `test_dedicadas_de_la_023` nombrándolo (y el de las genéricas)."""

    def test_dedicadas_de_la_023(self) -> None:
        import sys

        sys.path.insert(0, str(_RAIZ / "scripts" / "inventario"))
        try:
            import generar_tabla as gt
        finally:
            sys.path.pop(0)
        malas = []
        for comando, (tool, motivo) in _CONVERSACION_023.items():
            e = ct.CORE_WS[comando]
            real = (e.category, e.tool, e.family, e.cap, e.reason)
            if real != ("dedicated", tool, "conversation", "CAP-060", motivo):
                malas.append(f"{comando}: {real}")
            destino = gt._DEDICADAS_INICIALES.get(comando)
            nombre = getattr(destino, "tool", destino)
            if nombre != tool:
                malas.append(f"{comando}: no está en el mapa del generador ({destino!r})")
        self.assertEqual(malas, [], "\n".join(malas))
        pendientes = sorted(k for k, e in ct.CORE_WS.items() if "spec 023" in e.reason)
        self.assertEqual(pendientes, [])

    def test_revisadas(self) -> None:
        debug = ct.CORE_WS["assist_pipeline/pipeline_debug/get"]
        self.assertEqual(debug.category, "read")
        self.assertIn("url", debug.redact_extra)
        self.assertIn("tts_proxy", debug.reason)
        ai = ct.CORE_WS["ai_task/preferences/set"]
        self.assertEqual(ai.category, "confirm")
        self.assertIn("allow_automatic_evaluation", ai.reason)
        self.assertIn("LLM", ai.reason)
        crear = ct.CORE_WS["assist_pipeline/pipeline/create"]
        self.assertEqual(crear.category, "confirm")
        self.assertEqual(crear.example["conversation_engine"], "conversation.home_assistant")
        self.assertEqual(len(crear.example), 11)
        run = ct.CORE_WS["assist_pipeline/run"]
        self.assertEqual(run.category, "deny")
        self.assertIn("clase D", run.reason)


# Spec 024 (FR-005, FR-008…FR-012, FR-014; SC-003): las 33 entradas de
# CAP-059, 065, 066, 067, 070, 071, 072 y 073, con su categoría,
# `open_world` y `redact_extra`. Todas de `generic_commands` salvo
# `lovelace/config/delete`, que va a la tool dedicada.
_CLASIFICACION_024: dict[str, tuple[str, bool, tuple[str, ...]]] = {
    # CAP-059: preferencias de cámara (la imagen va por tools dedicadas).
    "camera/get_prefs": ("read", False, ()),
    "camera/update_prefs": ("confirm", True, ()),
    # CAP-065: calendario y tareas; los remotos salen a internet.
    "calendar/event/update": ("confirm", True, ()),
    "calendar/event/delete": ("confirm", True, ()),
    "todo/item/move": ("confirm", True, ()),
    # CAP-066: tags.
    "tag/list": ("read", False, ()),
    "tag/create": ("confirm", False, ()),
    "tag/update": ("confirm", False, ()),
    "tag/delete": ("confirm", False, ()),
    # CAP-067: medios; miniaturas tapadas (research R-6) y la URL firmada
    # de `resolve_media`, denegada.
    "media_source/browse_media": ("read", True, ("thumbnail",)),
    "media_source/search_media": ("read", True, ("thumbnail",)),
    "media_source/local_source/remove": ("confirm", False, ()),
    "media_source/resolve_media": ("deny", False, ()),
    # CAP-070: orden y ajustes de los registros.
    "config/area_registry/reorder": ("confirm", False, ()),
    "config/floor_registry/reorder": ("confirm", False, ()),
    "config/entity_registry/settings/update": ("confirm", False, ()),
    "config/entity_registry/settings/get": ("read", False, ()),
    "config/entity_registry/get_automatic_entity_ids": ("read", False, ()),
    "config/device_registry/list_linked_devices": ("read", False, ()),
    "config/device_registry/list_composite_splits": ("read", False, ()),
    # CAP-071: restablecer va por la tool dedicada; el resto, lecturas
    # (`webhook_id` tapado por el marcador general; segmentos de mundo abierto).
    "lovelace/config/delete": ("dedicated", False, ()),
    "trace/contexts": ("read", False, ()),
    "frontend/get_themes": ("read", False, ()),
    "webhook/list": ("read", False, ()),
    "vacuum/get_segments": ("read", True, ()),
    "radio_frequency/list": ("read", False, ()),
    # CAP-072: imágenes subidas; subir va por REST multipart.
    "image/list": ("read", False, ()),
    "image/update": ("confirm", False, ()),
    "image/delete": ("confirm", False, ()),
    "image/create": ("deny", False, ()),
    # CAP-073: credenciales de aplicación; `client_secret` y el id tapados
    # por la redacción general.
    "application_credentials/list": ("read", False, ()),
    "application_credentials/config": ("read", False, ()),
    "application_credentials/config_entry": ("read", False, ()),
}

_CAPS_024 = {"CAP-059", "CAP-065", "CAP-066", "CAP-067", "CAP-070", "CAP-071",
             "CAP-072", "CAP-073"}


class TestClasificacionDeLa024(unittest.TestCase):
    """Spec 024, T009 y T024. Controles negativos: (T013 f) dejar
    `camera/update_prefs` en `deny` → cae `test_las_33_entradas` nombrándola
    (y los de la genérica en test_tools_generic_commands.py); (T029 e) dejar
    `lovelace/config/delete` en `deny` → caen `test_las_33_entradas`,
    `test_restablecer_va_a_la_tool_dedicada`, `test_ninguna_pendiente` y
    `test_desde_cero_igual_que_la_tabla_real` (está en el mapa)."""

    def test_las_33_entradas(self) -> None:
        self.assertEqual(len(_CLASIFICACION_024), 33)
        malas = []
        for k, esperado in _CLASIFICACION_024.items():
            e = ct.CORE_WS[k]
            real = (e.category, e.open_world, tuple(e.redact_extra))
            if e.category == "dedicated":
                familia_ok = e.family == "dashboard_reset"
            else:
                familia_ok = e.family == "generic_commands" and e.tool is None
            if real != esperado or not familia_ok:
                malas.append(f"{k}: {real} {e.family} {e.tool}")
        self.assertEqual(malas, [], "\n".join(malas))

    def test_son_todas_las_de_sus_cap(self) -> None:
        de_sus_cap = {k for k, e in ct.CORE_WS.items() if e.cap in _CAPS_024}
        self.assertEqual(de_sus_cap, set(_CLASIFICACION_024))

    def test_restablecer_va_a_la_tool_dedicada(self) -> None:
        e = ct.CORE_WS["lovelace/config/delete"]
        self.assertEqual(
            (e.category, e.tool, e.family, e.cap, e.reason),
            ("dedicated", "ha_reset_lovelace_dashboard_config", "dashboard_reset",
             "CAP-071", "cubierto por ha_reset_lovelace_dashboard_config"))
        # Y el generador la tiene en su mapa (una generación desde cero da lo
        # mismo: test_desde_cero_igual_que_la_tabla_real).
        from scripts.inventario import generar_tabla as gt

        self.assertEqual(gt._DEDICADAS_INICIALES["lovelace/config/delete"],
                         "ha_reset_lovelace_dashboard_config")

    def test_motivos(self) -> None:
        self.assertIn("solo lee", ct.CORE_WS["camera/get_prefs"].reason)
        self.assertIn("internet", ct.CORE_WS["camera/update_prefs"].reason)
        for k in ("media_source/browse_media", "media_source/search_media"):
            with self.subTest(k=k):
                self.assertIn("thumbnail", ct.CORE_WS[k].reason)
                self.assertIn("tapada", ct.CORE_WS[k].reason)
        self.assertIn("authSig", ct.CORE_WS["media_source/resolve_media"].reason)
        self.assertIn("multipart", ct.CORE_WS["image/create"].reason)
        self.assertIn("webhook_id sale tapado", ct.CORE_WS["webhook/list"].reason)
        self.assertIn("nube", ct.CORE_WS["vacuum/get_segments"].reason)
        # H2 de la revisión de la spec (research R-7): el motivo no promete
        # el id, que sale tapado.
        motivo = ct.CORE_WS["application_credentials/config_entry"].reason
        self.assertIn("el id sale tapado", motivo)
        self.assertIn("client_secret sale tapado",
                      ct.CORE_WS["application_credentials/list"].reason)
        for k in ("trace/contexts", "frontend/get_themes", "webhook/list",
                  "vacuum/get_segments", "radio_frequency/list"):
            with self.subTest(k=k):
                self.assertIn("solo lee", ct.CORE_WS[k].reason)

    def test_lo_de_clase_d_sigue_denegado(self) -> None:
        for k in ("application_credentials/create", "application_credentials/update",
                  "application_credentials/delete", "webhook/handle"):
            with self.subTest(k=k):
                self.assertEqual(ct.CORE_WS[k].category, "deny")

    def test_ninguna_de_la_024_por_el_proxy(self) -> None:
        self.assertEqual(
            [k for k in _CLASIFICACION_024 if k.startswith(("hassio/", "supervisor/"))], [])

    def test_ninguna_pendiente(self) -> None:
        # Al cerrar la 024 (T024): ninguna entrada «spec 024» en la tabla.
        pendientes = sorted(
            k for k, e in ct.CORE_WS.items() if "(spec 024)" in e.reason)
        self.assertEqual(pendientes, [])
        texto = (_RAIZ / "hermes" / "src" / "hermes" / "command_table.py").read_text(
            encoding="utf-8")
        self.assertEqual(texto.count("spec 024"), 0)


if __name__ == "__main__":
    unittest.main()
