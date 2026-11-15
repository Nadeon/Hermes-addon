"""Invariante de registro: toda `@mcp.tool()` definida en `hermes/tools/` debe
quedar expuesta por `register_all_tools`.

Un módulo de tools puede existir, importarse y pasar todos sus tests
unitarios y aun así no llegar al cliente MCP: basta con que nadie llame a su
`register()` desde `register_all_tools`. Los tests por módulo no lo detectan —
prueban las funciones, no el cableado— y la documentación seguiría anunciando
herramientas que no se ven. Este test compara lo que se declara con lo que
queda registrado de verdad.
"""

from __future__ import annotations

import ast
import os
import pathlib
import unittest
from unittest.mock import MagicMock

from hermes.tools import register_all_tools

_TOOLS_DIR = pathlib.Path(__file__).resolve().parents[1] / "hermes" / "src" / "hermes" / "tools"

# Tools que devuelven PROSA para que la lea una persona (texto plano/Markdown),
# no datos. Son las únicas que declaran `-> str`; el resto declara `-> object`.
_PROSE_TOOLS = {"ping", "hermes_guide"}


def _declared_return_annotations() -> dict[str, str]:
    """Nombre de cada tool -> anotación de retorno declarada."""
    out: dict[str, str] = {}
    for path in sorted(_TOOLS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            for deco in node.decorator_list:
                is_tool = (
                    isinstance(deco, ast.Call)
                    and getattr(getattr(deco, "func", None), "attr", "") == "tool"
                ) or (isinstance(deco, ast.Attribute) and deco.attr == "tool")
                if is_tool:
                    out[node.name] = (
                        ast.unparse(node.returns) if node.returns else "(sin anotación)"
                    )
                    break
    return out


def _declared_tool_names() -> set[str]:
    """Nombres de todas las funciones decoradas con @mcp.tool() en el paquete."""
    names: set[str] = set()
    for path in sorted(_TOOLS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            for deco in node.decorator_list:
                is_tool = (
                    isinstance(deco, ast.Call)
                    and getattr(getattr(deco, "func", None), "attr", "") == "tool"
                ) or (isinstance(deco, ast.Attribute) and deco.attr == "tool")
                if is_tool:
                    names.add(node.name)
                    break
    return names


class _RecordingMCP:
    """Doble de MCPServer que solo anota qué tools se registran."""

    def __init__(self) -> None:
        self.tools: dict[str, object] = {}
        self.duplicates: list[str] = []

    def tool(self, *args: object, **kwargs: object):
        def decorator(fn):
            if fn.__name__ in self.tools:
                self.duplicates.append(fn.__name__)
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _register_all(dev: bool = True) -> _RecordingMCP:
    """Registra todas las tools. `dev=True` incluye las de desarrollo."""
    previous = os.environ.get("HERMES_DEV")
    if dev:
        os.environ["HERMES_DEV"] = "1"
    else:
        os.environ.pop("HERMES_DEV", None)
    try:
        return _do_register()
    finally:
        if previous is None:
            os.environ.pop("HERMES_DEV", None)
        else:
            os.environ["HERMES_DEV"] = previous


def _do_register(tool_families_disabled: list[str] | None = None) -> _RecordingMCP:
    mcp = _RecordingMCP()
    register_all_tools(
        mcp,
        MagicMock(),
        fire_event_allowlist=[],
        response_max_bytes=1_048_576,
        safety_backup_window_minutes=30,
        safety_backup_enabled=False,
        file_backup_max_per_path=20,
        file_backup_max_total_mb=200,
        config_write_min_interval_seconds=5,
        config_write_max_per_minute=10,
        call_service_denylist_extra=[],
        call_service_restricted_entities=[],
        # False: evita que el registro lance la task de auto-clasificación,
        # que necesitaría un event loop en marcha.
        call_service_auto_classify=False,
        wait_for_event_max_seconds=90,
        wait_for_event_max_concurrent=5,
        # [] y no None: que una variable del entorno de quien ejecuta la
        # suite no cambie qué se registra.
        tool_families_disabled=tool_families_disabled or [],
    )
    return mcp


class TestToolRegistration(unittest.TestCase):
    def test_every_declared_tool_is_registered(self) -> None:
        mcp = _register_all()
        missing = sorted(_declared_tool_names() - set(mcp.tools))
        self.assertEqual(
            missing,
            [],
            "Hay tools declaradas con @mcp.tool() que register_all_tools no "
            f"registra (¿falta la llamada a su register()?): {missing}",
        )

    def test_no_duplicate_tool_names(self) -> None:
        mcp = _register_all()
        self.assertEqual(mcp.duplicates, [], f"Nombres duplicados: {mcp.duplicates}")

    def test_lovelace_tools_are_exposed(self) -> None:
        # Regresión explícita del fallo de 0.20.0.
        mcp = _register_all()
        for name in (
            "ha_list_lovelace_dashboards",
            "ha_get_lovelace_dashboard",
            "ha_save_lovelace_dashboard",
            "ha_create_lovelace_dashboard",
            "ha_delete_lovelace_dashboard",
            "ha_update_lovelace_dashboard_metadata",
            "ha_list_lovelace_resources",
            "ha_create_lovelace_resource",
            "ha_update_lovelace_resource",
            "ha_delete_lovelace_resource",
        ):
            self.assertIn(name, mcp.tools)

    def test_return_annotations_follow_the_contract(self) -> None:
        """Contrato único de retorno para todas las tools.

        - Tools de prosa (texto para leer)  -> `str`
        - Tools de datos (todas las demás)  -> `object`

        `object` es deliberado: el SDK deriva `outputSchema` de la anotación, y
        para `dict[str, Any]` genera `{"additionalProperties": true}` y para
        `str` genera `{"result": {"type": "string"}}`. Ninguno describe la forma
        real de la respuesta, así que costaban ~3 000 tokens de schema sin
        aportar información. Con `object` no se emite `outputSchema` y además no
        hay validación de retorno en runtime — necesario porque varias tools
        devuelven listas legítimamente (p. ej. las que retornan directamente el
        resultado de `ha_client.call_service`).

        Si algún día se quiere salida estructurada de verdad, la vía correcta es
        declarar modelos de respuesta por tool, no anotar `dict[str, Any]`.
        """
        wrong: list[str] = []
        for name, ann in sorted(_declared_return_annotations().items()):
            expected = "str" if name in _PROSE_TOOLS else "object"
            if ann != expected:
                wrong.append(f"{name}: declara '{ann}', debería ser '{expected}'")
        self.assertEqual(wrong, [], "Anotaciones fuera del contrato:\n" + "\n".join(wrong))

    def test_prose_tools_exist(self) -> None:
        # Si se renombran, la allowlist debe actualizarse a conciencia.
        declared = set(_declared_return_annotations())
        self.assertTrue(_PROSE_TOOLS <= declared, f"Falta alguna de {_PROSE_TOOLS}")

    def test_tool_names_do_not_lie_about_creating(self) -> None:
        """Un nombre `update` no puede ocultar que la tool también crea.

        Los nombres MCP los elegimos nosotros (la API de HA expone `create` y
        `update` como comandos separados y Hermes los fusiona). En modo diferido
        el cliente ve el NOMBRE antes que la descripción, así que el nombre es
        el que tiene que decir la verdad: las que hacen upsert se llaman
        `ha_create_or_update_*` y las que solo editan algo existente,
        `ha_update_*`.
        """
        liars: list[str] = []
        for path in sorted(_TOOLS_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    continue
                if not node.name.startswith("ha_update_"):
                    continue
                doc = (ast.get_docstring(node) or "").strip().lower()
                first = doc.splitlines()[0] if doc else ""
                if first.startswith(("crea o", "crea/")):
                    liars.append(f"{node.name} ({path.name}): «{first[:60]}»")
        self.assertEqual(
            liars,
            [],
            "Estas tools se llaman 'update' pero su descripción dice que crean; "
            "renómbralas a ha_create_or_update_*:\n" + "\n".join(liars),
        )

    def test_upsert_tools_are_named_create_or_update(self) -> None:
        mcp = _register_all()
        for name in (
            "ha_create_or_update_automation",
            "ha_create_or_update_script",
            "ha_create_or_update_scene",
            "ha_create_or_update_input_boolean",
            "ha_create_or_update_input_number",
            "ha_create_or_update_input_select",
            "ha_create_or_update_input_text",
            "ha_create_or_update_input_datetime",
            "ha_create_or_update_input_button",
            "ha_create_or_update_counter",
            "ha_create_or_update_timer",
            "ha_create_or_update_schedule",
            "ha_create_or_update_zone",
        ):
            self.assertIn(name, mcp.tools)
        # Y los nombres antiguos no deben seguir existiendo.
        for old in ("ha_update_automation", "ha_update_input_boolean", "ha_update_zone"):
            self.assertNotIn(old, mcp.tools)

    def test_pure_update_tools_keep_their_name(self) -> None:
        """Las que solo editan algo existente siguen siendo `ha_update_*`."""
        mcp = _register_all()
        for name in ("ha_update_area", "ha_update_device", "ha_update_entity_registry",
                     "ha_update_person", "ha_update_lovelace_resource"):
            self.assertIn(name, mcp.tools)

    def test_flow_handlers_tool_renamed_to_what_it_does(self) -> None:
        """Se llamaba ha_list_flow_handlers y prometía el catálogo de
        integraciones instalables; en realidad lista las YA configuradas."""
        mcp = _register_all()
        self.assertIn("ha_list_configured_domains", mcp.tools)
        self.assertNotIn("ha_list_flow_handlers", mcp.tools)

    def test_dev_tools_are_not_exposed_in_production(self) -> None:
        """`test_progress` duerme 40 s; es andamiaje, no una tool de usuario."""
        prod = _register_all(dev=False)
        self.assertNotIn("test_progress", prod.tools)
        self.assertIn("ping", prod.tools)
        dev = _register_all(dev=True)
        self.assertIn("test_progress", dev.tools)

    def test_every_tool_has_a_description(self) -> None:
        """Sin docstring, el cliente MCP no recibe descripción y el modelo no
        sabe para qué sirve la tool (le pasó a sv_create_safety_backup, cuyo
        docstring llevaba un .format() que lo convertía en expresión)."""
        mcp = _register_all()
        undocumented = sorted(
            name for name, fn in mcp.tools.items() if not (fn.__doc__ or "").strip()
        )
        self.assertEqual(undocumented, [], f"Tools sin descripción: {undocumented}")


class TestToolAnnotations(unittest.TestCase):
    """Las anotaciones MCP declaran al cliente qué hace cada tool.

    Los clientes las usan para su experiencia de permisos: no preguntar por lo
    que solo lee y avisar antes de lo que borra o reinicia.
    """

    def test_every_tool_gets_annotations(self) -> None:
        from hermes.tools._annotations import classify

        for name in sorted(_declared_return_annotations()):
            ann = classify(name)
            self.assertIsNotNone(ann.read_only_hint, name)
            self.assertIsNotNone(ann.destructive_hint, name)

    def test_read_only_tools_are_marked(self) -> None:
        from hermes.tools._annotations import classify

        for name in (
            "ha_get_states", "ha_get_state", "ha_list_automations",
            "sv_get_host_info", "sv_list_backups", "fs_read_file",
            "fs_search_in_config", "ha_render_template", "hermes_guide",
            "ping", "ha_hacs_info", "ha_marketplace_info",
        ):
            ann = classify(name)
            self.assertTrue(ann.read_only_hint, f"{name} debería ser de solo lectura")
            self.assertFalse(ann.destructive_hint, f"{name} no destruye nada")

    def test_destructive_tools_are_marked(self) -> None:
        from hermes.tools._annotations import classify

        for name in (
            "ha_delete_automation", "ha_delete_config_entry", "sv_delete_backup",
            "sv_uninstall_addon", "sv_restore_backup_full", "sv_reboot_host",
            "sv_restart_core", "fs_delete_file", "fs_write_file",
            "fs_restore_file_backup", "ha_save_lovelace_dashboard",
            "ha_call_service",
        ):
            ann = classify(name)
            self.assertFalse(ann.read_only_hint, f"{name} no es de solo lectura")
            self.assertTrue(ann.destructive_hint, f"{name} debería marcarse destructiva")

    def test_additive_tools_are_not_destructive(self) -> None:
        """Aditiva = añade algo sin quitar nada, y no se hace confirmar.

        `sv_start_addon` estaba en esta lista y no encaja: pide
        `confirmation_token`, que es precisamente la señal de que se la
        considera consecuente. Una herramienta no puede hacerse confirmar y a
        la vez anunciarse inofensiva; lo vigila
        `TestDestructiveToolsAskBeforeActing`.
        """
        from hermes.tools._annotations import classify

        for name in ("ha_create_area", "ha_set_input_number",
                     "ha_start_timer", "ha_activate_scene"):
            ann = classify(name)
            self.assertFalse(ann.read_only_hint, name)
            self.assertFalse(ann.destructive_hint, f"{name} es aditiva, no destructiva")

    def test_tools_that_write_are_not_read_only(self) -> None:
        """El prefijo del nombre es una heurística ciega.

        `sv_check_core_config` y `sv_get_job_status` escriben en disco pese a
        llamarse `sv_check_*` / `sv_get_*`. La primera, además, levanta el
        bloqueo que impide reiniciar HA con configuración sin validar: era la
        única tool "de solo lectura" que alteraba una decisión de seguridad.
        """
        from hermes.tools._annotations import classify

        for name in ("sv_check_core_config", "sv_get_job_status"):
            self.assertFalse(classify(name).read_only_hint,
                             f"{name} escribe: no puede declararse read-only")

    def test_open_world_only_for_internet_tools(self) -> None:
        from hermes.tools._annotations import classify

        self.assertTrue(classify("sv_install_addon").open_world_hint)
        # Los alias `ha_hacs_*` ya no salen a GitHub (spec 004, FR-018): leen
        # la lista que HA tiene en memoria. Solo las versiones publicadas se
        # piden a GitHub.
        self.assertFalse(classify("ha_hacs_list_repositories").open_world_hint)
        self.assertTrue(classify("ha_marketplace_list_releases").open_world_hint)
        self.assertFalse(classify("ha_get_states").open_world_hint)
        self.assertFalse(classify("fs_read_file").open_world_hint)

    def test_non_idempotent_tools(self) -> None:
        from hermes.tools._annotations import classify

        self.assertFalse(classify("ha_increment_counter").idempotent_hint)
        self.assertFalse(classify("ha_toggle_input_boolean").idempotent_hint)
        self.assertFalse(classify("ha_create_area").idempotent_hint)
        self.assertTrue(classify("ha_set_input_number").idempotent_hint)
        self.assertTrue(classify("ha_get_states").idempotent_hint)
        # `duration` es un DELTA: llamarla dos veces suma dos veces, igual que
        # ha_increment_counter. La tabla la clasificaba al revés por no encajar
        # con ningún prefijo.
        self.assertFalse(classify("ha_change_timer").idempotent_hint)

    def test_upserts_are_idempotent_despite_the_create_prefix(self) -> None:
        """`ha_create_or_update_*` empieza por `ha_create_`, que se clasifica
        como no idempotente. Pero un upsert repetido con la misma configuración
        deja el mismo estado, así que debe declararse idempotente."""
        from hermes.tools._annotations import classify

        for name in ("ha_create_or_update_automation",
                     "ha_create_or_update_input_number",
                     "ha_create_or_update_zone"):
            ann = classify(name)
            self.assertTrue(ann.idempotent_hint, f"{name} debería ser idempotente")
            # Destructiva porque, si el id ya existe, `config_save` REEMPLAZA la
            # configuración entera —no hace merge— y la anterior se pierde. Es el
            # mismo razonamiento por el que ha_save_lovelace_dashboard ya estaba
            # marcada. Idempotente y destructiva no se
            # contradicen: repetirla deja el mismo estado, pero pisa lo que hubiera.
            self.assertTrue(ann.destructive_hint, f"{name} reemplaza la config")
            self.assertFalse(ann.read_only_hint, f"{name} sí modifica")

    def test_applied_to_the_real_registry(self) -> None:
        """Se aplican de verdad sobre las tools registradas, no solo en teoría."""
        from mcp.server.mcpserver import MCPServer

        from hermes.tools._annotations import apply_tool_annotations

        mcp = MCPServer("test-annotations")

        @mcp.tool()
        async def ha_get_states(domain: str | None = None) -> object:
            """Lista estados."""
            return {}

        @mcp.tool()
        async def ha_delete_automation(entity_id: str) -> object:
            """Borra una automatización."""
            return {}

        stats = apply_tool_annotations(mcp)
        self.assertEqual(stats["annotated"], 2)
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        self.assertTrue(tools["ha_get_states"].annotations.read_only_hint)
        self.assertTrue(tools["ha_delete_automation"].annotations.destructive_hint)


if __name__ == "__main__":
    unittest.main()

class TestDestructiveToolsAskBeforeActing:
    """La promesa que Hermes le hace al modelo tiene que ser cierta.

    Las instrucciones que el cliente MCP lee al conectarse dicen que una acción
    destructiva devuelve, en la primera llamada, una vista previa y un
    `confirmation_token`, y que no ejecuta nada hasta que se la vuelve a llamar
    con ese token. Si una herramienta marcada `destructiveHint` actúa a la
    primera, esa promesa es falsa justo donde más importa.

    Al escribir este test había dos que la rompían. Una se corrigió
    —`ha_disable_config_entry`, que deja una integración fuera de servicio— y la
    otra, `ha_call_service_response`, fue excepción deliberada hasta la spec
    018, que le dio `confirmation_token` (ver abajo).

    El invariante inverso también se vigila: una herramienta que pide token es,
    por definición, consecuente, y debe declararse como tal. Si no, el cliente
    la trata como inofensiva y solo descubre lo contrario al llamarla.
    """

    # Excepciones admitidas: ninguna.
    #
    # Hasta la 1.1.2 lo era `ha_call_service_response`, que rechazaba de plano
    # la denylist sin flujo de confirmación. Desde la spec 018 (FR-008, FR-016)
    # acepta `confirmation_token` para la denylist y las entidades
    # restringidas, así que la excepción deja de hacer falta. Fuera de ellas
    # sigue respondiendo a la primera: leer el tiempo no pide dos pasos.
    SIN_TOKEN_A_PROPOSITO: set[str] = set()

    @staticmethod
    def _firmas() -> dict:
        import ast as _ast
        import pathlib as _pl

        raiz = _pl.Path(__file__).resolve().parents[1] / "hermes/src/hermes/tools"
        firmas = {}
        for f in raiz.glob("*.py"):
            arbol = _ast.parse(f.read_text(encoding="utf-8"))
            for nodo in _ast.walk(arbol):
                if not isinstance(nodo, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    continue
                if not any(isinstance(d, _ast.Call)
                           and getattr(d.func, "attr", "") == "tool"
                           for d in nodo.decorator_list):
                    continue
                args = [a.arg for a in nodo.args.args] + \
                       [a.arg for a in nodo.args.kwonlyargs]
                firmas[nodo.name] = "confirmation_token" in args
        return firmas

    def test_every_destructive_tool_takes_a_confirmation_token(self):
        from hermes.tools._annotations import classify

        firmas = self._firmas()
        assert len(firmas) > 150, "no se han encontrado las tools"
        incumplen = sorted(
            n for n, tiene in firmas.items()
            if classify(n).destructive_hint and not tiene
            and n not in self.SIN_TOKEN_A_PROPOSITO)
        assert incumplen == [], (
            "declaradas destructivas pero ejecutan a la primera: " + str(incumplen))

    def test_every_tool_that_asks_for_a_token_says_it_is_destructive(self):
        from hermes.tools._annotations import classify

        firmas = self._firmas()
        incumplen = sorted(
            n for n, tiene in firmas.items()
            if tiene and not classify(n).destructive_hint)
        assert incumplen == [], (
            "piden confirmación pero se anuncian inofensivas: " + str(incumplen))

    def test_the_documented_exception_is_still_only_one(self):
        """Ya no queda ninguna (spec 018): si mañana aparece una, que haya
        que justificarla a mano."""
        assert len(self.SIN_TOKEN_A_PROPOSITO) == 0


# ── title (spec 003, FR-040) e hints intactos (FR-043) ───────────────────────

# Instantánea de los cuatro *hints* de cada tool, tomada con `classify` ANTES
# de añadir `title`. Añadir el título no puede cambiar lo que una tool dice de
# sí misma (principio V): si un día cambia un hint, tiene que ser a propósito y
# actualizando esta tabla en el mismo cambio.
#
# Es la REFERENCIA DE LA 1.1.2 (spec 011, FR-021): las 216 tools de producción
# más `test_progress` (desarrollo). Las tools nuevas de la 1.2.0 no se añaden
# aquí: van en `_HINTS_NUEVAS_1_2_0`, para que esta tabla siga diciendo qué
# prometía la 1.1.2 y un cambio en una de ellas se vea como tal.
# Código: R = readOnlyHint, D = destructiveHint, I = idempotentHint,
# O = openWorldHint; «-» = False.
_HINTS_SNAPSHOT: dict[str, str] = {
    "fs_delete_file": "-DI-",
    "fs_list_dir": "R-I-",
    "fs_list_file_backups": "R-I-",
    "fs_move_file": "-DI-",
    "fs_read_file": "R-I-",
    "fs_read_file_lines": "R-I-",
    "fs_restore_file_backup": "-DI-",
    "fs_search_in_config": "R-I-",
    "fs_set_secret": "-DI-",
    "fs_stat": "R-I-",
    "fs_write_file": "-DI-",
    "ha_abort_config_entry_flow": "--I-",
    "ha_activate_scene": "--I-",
    "ha_call_service": "-DI-",
    "ha_call_service_response": "-DI-",
    "ha_cancel_timer": "--I-",
    "ha_cancel_wait": "--I-",
    "ha_change_timer": "----",
    "ha_continue_config_entry_flow": "--I-",
    "ha_continue_options_flow": "--I-",
    "ha_create_area": "----",
    "ha_create_category": "----",
    "ha_create_floor": "----",
    "ha_create_label": "----",
    "ha_create_lovelace_dashboard": "----",
    "ha_create_lovelace_resource": "-D-O",
    "ha_create_or_update_automation": "-DI-",
    "ha_create_or_update_counter": "-DI-",
    "ha_create_or_update_input_boolean": "-DI-",
    "ha_create_or_update_input_button": "-DI-",
    "ha_create_or_update_input_datetime": "-DI-",
    "ha_create_or_update_input_number": "-DI-",
    "ha_create_or_update_input_select": "-DI-",
    "ha_create_or_update_input_text": "-DI-",
    "ha_create_or_update_scene": "-DI-",
    "ha_create_or_update_schedule": "-DI-",
    "ha_create_or_update_script": "-DI-",
    "ha_create_or_update_timer": "-DI-",
    "ha_create_or_update_zone": "-DI-",
    "ha_create_person": "----",
    # Spec 033 (FR-011 de la 033, FR-099 de la 008): pasa de `----` a `-D--`.
    # Puede reemplazar una escena temporal (lo pide confirmar con token), y
    # anunciarse no destructiva era la mentira; un cliente que confiara en
    # `----` solo pierde un aviso que debió tener.
    "ha_create_scene_from_current": "-D--",
    "ha_cycle_input_select": "----",
    "ha_decrement_counter": "----",
    "ha_decrement_input_number": "----",
    "ha_delete_area": "-DI-",
    "ha_delete_automation": "-DI-",
    "ha_delete_category": "-DI-",
    "ha_delete_config_entry": "-DI-",
    "ha_delete_counter": "-DI-",
    "ha_delete_floor": "-DI-",
    "ha_delete_input_boolean": "-DI-",
    "ha_delete_input_button": "-DI-",
    "ha_delete_input_datetime": "-DI-",
    "ha_delete_input_number": "-DI-",
    "ha_delete_input_select": "-DI-",
    "ha_delete_input_text": "-DI-",
    "ha_delete_label": "-DI-",
    "ha_delete_lovelace_dashboard": "-DI-",
    "ha_delete_lovelace_resource": "-DI-",
    "ha_delete_person": "-DI-",
    "ha_delete_scene": "-DI-",
    "ha_delete_schedule": "-DI-",
    "ha_delete_script": "-DI-",
    "ha_delete_timer": "-DI-",
    "ha_delete_zone": "-DI-",
    "ha_disable_automation": "--I-",
    "ha_disable_config_entry": "-DI-",
    "ha_enable_automation": "--I-",
    "ha_enable_config_entry": "--I-",
    "ha_finish_timer": "--I-",
    "ha_fire_event": "----",
    "ha_get_area": "R-I-",
    "ha_get_automation": "R-I-",
    "ha_get_backup": "R-I-",
    "ha_get_backup_config": "R-I-",
    "ha_get_config_entry": "R-I-",
    "ha_get_config_entry_options": "R-I-",
    "ha_get_counter": "R-I-",
    "ha_get_device": "R-I-",
    "ha_get_entity_registry": "R-I-",
    "ha_get_history": "R-I-",
    "ha_get_input_boolean": "R-I-",
    "ha_get_input_button": "R-I-",
    "ha_get_input_datetime": "R-I-",
    "ha_get_input_number": "R-I-",
    "ha_get_input_select": "R-I-",
    "ha_get_input_text": "R-I-",
    "ha_get_logbook": "R-I-",
    "ha_get_lovelace_dashboard": "R-I-",
    "ha_get_person": "R-I-",
    "ha_get_scene": "R-I-",
    "ha_get_schedule": "R-I-",
    "ha_get_script": "R-I-",
    "ha_get_state": "R-I-",
    "ha_get_states": "R-I-",
    "ha_get_timer": "R-I-",
    "ha_get_trace": "R-I-",
    "ha_get_zone": "R-I-",
    "ha_hacs_get_repository": "R-I-",
    "ha_hacs_info": "R-I-",
    "ha_hacs_list_repositories": "R-I-",
    "ha_hacs_list_updates": "R-I-",
    "ha_ignore_repair": "-DI-",
    "ha_increment_counter": "----",
    "ha_increment_input_number": "----",
    "ha_list_active_waits": "R-I-",
    "ha_list_areas": "R-I-",
    "ha_list_automations": "R-I-",
    "ha_list_backups": "R-I-",
    "ha_list_categories": "R-I-",
    "ha_list_config_entries": "R-I-",
    "ha_list_configured_domains": "R-I-",
    "ha_list_counters": "R-I-",
    "ha_list_devices": "R-I-",
    "ha_list_entities_registry": "R-I-",
    "ha_list_floors": "R-I-",
    "ha_list_input_booleans": "R-I-",
    "ha_list_input_buttons": "R-I-",
    "ha_list_input_datetimes": "R-I-",
    "ha_list_input_numbers": "R-I-",
    "ha_list_input_selects": "R-I-",
    "ha_list_input_texts": "R-I-",
    "ha_list_labels": "R-I-",
    "ha_list_lovelace_dashboards": "R-I-",
    "ha_list_lovelace_resources": "R-I-",
    "ha_list_persons": "R-I-",
    "ha_list_repairs": "R-I-",
    "ha_list_scenes": "R-I-",
    "ha_list_schedules": "R-I-",
    "ha_list_scripts": "R-I-",
    "ha_list_services": "R-I-",
    "ha_list_statistic_ids": "R-I-",
    "ha_list_timers": "R-I-",
    "ha_list_traces": "R-I-",
    "ha_list_zones": "R-I-",
    "ha_marketplace_get_repository": "R-I-",
    "ha_marketplace_info": "R-I-",
    "ha_marketplace_list_critical": "R-I-",
    "ha_marketplace_list_releases": "R-IO",
    "ha_marketplace_list_removed": "R-I-",
    "ha_marketplace_list_repositories": "R-I-",
    "ha_marketplace_list_updates": "R-I-",
    "ha_pause_timer": "--I-",
    "ha_press_input_button": "----",
    "ha_reload_automations": "-DI-",
    "ha_reload_config_entry": "--I-",
    "ha_reload_counters": "-DI-",
    "ha_reload_scenes": "-DI-",
    "ha_reload_schedules": "-DI-",
    "ha_reload_scripts": "-DI-",
    "ha_reload_timers": "-DI-",
    "ha_reload_zones": "-DI-",
    "ha_remove_device": "-DI-",
    "ha_remove_device_from_config_entry": "-DI-",
    "ha_remove_entity_registry": "-DI-",
    "ha_render_template": "R-I-",
    "ha_reset_counter": "--I-",
    "ha_run_script": "-D--",
    "ha_save_lovelace_dashboard": "-DI-",
    "ha_search_related": "R-I-",
    "ha_set_counter_value": "--I-",
    "ha_set_input_boolean": "--I-",
    "ha_set_input_datetime": "--I-",
    "ha_set_input_number": "--I-",
    "ha_set_input_select": "--I-",
    "ha_set_input_select_options": "--I-",
    "ha_set_input_text": "--I-",
    "ha_start_config_entry_flow": "--I-",
    "ha_start_options_flow": "--I-",
    "ha_start_timer": "--I-",
    "ha_statistics_during_period": "R-I-",
    "ha_toggle_input_boolean": "----",
    "ha_trigger_automation": "-D--",
    "ha_update_area": "-DI-",
    "ha_update_category": "-DI-",
    "ha_update_device": "-DI-",
    "ha_update_entity_registry": "-DI-",
    "ha_update_floor": "-DI-",
    "ha_update_label": "-DI-",
    "ha_update_lovelace_dashboard_metadata": "-DI-",
    "ha_update_lovelace_resource": "-DIO",
    "ha_update_person": "-DI-",
    "ha_wait_for_event": "R-I-",
    "hermes_guide": "R-I-",
    "ping": "R-I-",
    "sv_check_core_config": "--I-",
    "sv_create_backup_full": "----",
    "sv_create_backup_partial": "----",
    "sv_create_safety_backup": "----",
    "sv_delete_backup": "-DI-",
    "sv_dismiss_resolution_issue": "-DI-",
    "sv_dismiss_resolution_suggestion": "-DI-",
    "sv_get_addon": "R-I-",
    "sv_get_addon_logs": "R-I-",
    "sv_get_addon_options": "R-I-",
    "sv_get_addon_stats": "R-I-",
    "sv_get_backup": "R-I-",
    "sv_get_core_info": "R-I-",
    "sv_get_host_info": "R-I-",
    "sv_get_job_status": "--I-",
    "sv_get_resolution": "R-I-",
    "sv_get_supervisor_info": "R-I-",
    "sv_install_addon": "-DIO",
    "sv_list_addons": "R-I-",
    "sv_list_backups": "R-I-",
    "sv_list_pending_jobs": "R-I-",
    "sv_reboot_host": "-DI-",
    "sv_restart_addon": "-DI-",
    "sv_restart_core": "-DI-",
    "sv_restore_backup_full": "-DI-",
    "sv_restore_backup_partial": "-DI-",
    "sv_set_addon_options": "-DI-",
    "sv_start_addon": "-DI-",
    "sv_stop_addon": "-DI-",
    "sv_uninstall_addon": "-DI-",
    "sv_update_addon": "-DIO",
    "test_progress": "R-I-",
}


# Tools nuevas de la 1.2.0: código de hints y título exactos (spec 011,
# contracts/tools.md). La de lectura de Core es de mundo abierto porque
# `media_source/browse_media` y `search_media` salen a internet con fuentes
# remotas (T047); la del Supervisor no. Las de escritura son destructivas, no
# idempotentes y de mundo abierto, porque ejecutan lo que la tabla permita.
_HINTS_NUEVAS_1_2_0: dict[str, tuple[str, str]] = {
    "ha_read_ws_command": ("R-IO", "Read WS command (Home Assistant)"),
    "ha_call_ws_command": ("-D-O", "Call WS command (Home Assistant)"),
    "sv_read_api": ("R-I-", "Read API (Supervisor)"),
    "sv_call_api": ("-D-O", "Call API (Supervisor)"),
    # Spec 013 (contracts/tools.md): logs del sistema, familia
    # `system_diagnostics`. Solo leen, son idempotentes y no salen a internet.
    "sv_get_core_logs": ("R-I-", "Get core logs (Supervisor)"),
    "sv_get_supervisor_logs": ("R-I-", "Get supervisor logs (Supervisor)"),
    "sv_get_plugin_logs": ("R-I-", "Get plugin logs (Supervisor)"),
    "sv_get_host_logs": ("R-I-", "Get host logs (Supervisor)"),
    "sv_list_host_log_identifiers": ("R-I-", "List host log identifiers (Supervisor)"),
    "sv_list_boots": ("R-I-", "List boots (Supervisor)"),
    # Spec 013, tramo 2: disco, host y OS, misma familia y mismas garantías.
    "sv_list_host_services": ("R-I-", "List host services (Supervisor)"),
    "sv_get_disk_usage": ("R-I-", "Get disk usage (Supervisor)"),
    "sv_get_os_info": ("R-I-", "Get OS info (Supervisor)"),
    "sv_get_swap": ("R-I-", "Get swap (Supervisor)"),
    "sv_list_datadisk_candidates": ("R-I-", "List datadisk candidates (Supervisor)"),
    # Spec 029 (CAP-043, familia `system_status`): solo leen; el prefijo
    # `ha_get_`/`ha_list_` da el `readOnlyHint` (FR-017). La salud es además
    # de mundo abierto (T037): HA comprueba si llega a servicios de internet
    # al pedirla. Control negativo comprobado: quitarla de `_OPEN_WORLD` →
    # cae `test_hints_y_titulos_de_las_nuevas` (sale `R-I-`).
    "ha_get_system_health": ("R-IO", "Get system health (Home Assistant)"),
    "ha_get_system_state": ("R-I-", "Get system state (Home Assistant)"),
    "ha_list_integration_setup_times": ("R-I-", "List integration setup times (Home Assistant)"),
    "ha_list_integration_manifests": ("R-I-", "List integration manifests (Home Assistant)"),
    "ha_get_integration_manifest": ("R-I-", "Get integration manifest (Home Assistant)"),
    # Spec 029 (CAP-049, familia `recorder`): solo leen. `ha_validate_statistics`
    # no tiene prefijo de lectura: va por nombre exacto en `_READ_ONLY_EXACT`
    # (T034 e: sin esa línea, este hint cae).
    "ha_validate_statistics": ("R-I-", "Validate statistics (Home Assistant)"),
    "ha_get_statistics_metadata": ("R-I-", "Get statistics metadata (Home Assistant)"),
    "ha_get_recorder_info": ("R-I-", "Get recorder info (Home Assistant)"),
    # Spec 012, tramo A (contracts/tools.md): las de lectura por su prefijo;
    # fijar el nivel y limpiar piden token y van en `_DESTRUCTIVE_EXACT`.
    "ha_list_system_log": ("R-I-", "List system log (Home Assistant)"),
    "ha_get_error_log": ("R-I-", "Get error log (Home Assistant)"),
    "ha_get_log_levels": ("R-I-", "Get log levels (Home Assistant)"),
    "ha_set_log_level": ("-DI-", "Set log level (Home Assistant)"),
    "ha_clear_system_log": ("-DI-", "Clear system log (Home Assistant)"),
    # Spec 012, tramo B: validar y probar una condición no guardan nada y van
    # en `_READ_ONLY_EXACT` (no tienen prefijo de lectura); descartar una
    # notificación pide token y va en `_DESTRUCTIVE_EXACT`.
    "ha_validate_config": ("R-I-", "Validate config (Home Assistant)"),
    "ha_test_condition": ("R-I-", "Test condition (Home Assistant)"),
    "ha_list_diagnostics_handlers": ("R-I-", "List diagnostics handlers (Home Assistant)"),
    "ha_get_config_entry_diagnostics": ("R-I-", "Get config entry diagnostics (Home Assistant)"),
    "ha_get_device_diagnostics": ("R-I-", "Get device diagnostics (Home Assistant)"),
    "ha_list_persistent_notifications": ("R-I-", "List persistent notifications (Home Assistant)"),
    "ha_dismiss_persistent_notification": ("-DI-", "Dismiss persistent notification (Home Assistant)"),
    # Spec 016, tramo A (contracts/tools.md). Las dos de lectura, por prefijo.
    # `ha_ignore_discovery` modifica sin destruir y es idempotente: crea la
    # entrada `ignore` y HA deja de ofrecer ese descubrimiento (se deshace
    # borrando esa entrada). Desde T046 solo acepta flujos de descubrimiento;
    # ignorar un `reauth` borraba la entrada real, y eso se rechaza en vez de
    # anunciarse destructivo, porque no pide token; `ha_update_config_entry` es
    # destructiva por nombre exacto porque puede pedir token.
    "ha_list_discovered_integrations": ("R-I-", "List discovered integrations (Home Assistant)"),
    "ha_ignore_discovery": ("--I-", "Ignore discovery (Home Assistant)"),
    "ha_list_config_flow_domains": ("R-I-", "List config flow domains (Home Assistant)"),
    "ha_update_config_entry": ("-DI-", "Update config entry (Home Assistant)"),
    # Spec 016, tramo B (contracts/tools.md). Abrir o avanzar un flujo no es
    # idempotente; `ha_delete_subentry` es destructiva por prefijo y
    # `ha_continue_reconfigure_flow` por nombre exacto (pide token en cada
    # paso: decisión del supervisor). Renombrar y abortar, ni lo uno ni lo
    # otro.
    "ha_list_config_subentries": ("R-I-", "List config subentries (Home Assistant)"),
    "ha_start_subentry_flow": ("----", "Start subentry flow (Home Assistant)"),
    "ha_continue_subentry_flow": ("----", "Continue subentry flow (Home Assistant)"),
    "ha_abort_subentry_flow": ("--I-", "Abort subentry flow (Home Assistant)"),
    "ha_update_subentry": ("--I-", "Update subentry (Home Assistant)"),
    "ha_delete_subentry": ("-DI-", "Delete subentry (Home Assistant)"),
    "ha_start_reconfigure_flow": ("----", "Start reconfigure flow (Home Assistant)"),
    "ha_continue_reconfigure_flow": ("-D--", "Continue reconfigure flow (Home Assistant)"),
    # Spec 016, tramo C. `ha_get_repair` de lectura por prefijo; abrir y
    # avanzar un flujo de reparación no son idempotentes; avanzar es
    # destructiva por nombre exacto (pide token en cada paso); abortar, como
    # `ha_abort_config_entry_flow`.
    "ha_get_repair": ("R-I-", "Get repair (Home Assistant)"),
    "ha_start_repair_fix": ("----", "Start repair fix (Home Assistant)"),
    "ha_continue_repair_fix": ("-D--", "Continue repair fix (Home Assistant)"),
    "ha_abort_repair_fix": ("--I-", "Abort repair fix (Home Assistant)"),
    # Spec 019, tramo 1 (contracts/tools.md): montajes, familia `mounts`. Las
    # cuatro con token se anuncian destructivas; crear no es idempotente
    # (prefijo `sv_create_`); recargar ni lee solo ni destruye. Ninguna sale a
    # internet: el NAS está en la red local.
    "sv_list_mounts": ("R-I-", "List mounts (Supervisor)"),
    "sv_create_mount": ("-D--", "Create mount (Supervisor)"),
    "sv_update_mount": ("-DI-", "Update mount (Supervisor)"),
    "sv_delete_mount": ("-DI-", "Delete mount (Supervisor)"),
    "sv_reload_mount": ("--I-", "Reload mount (Supervisor)"),
    "sv_set_default_backup_mount": ("-DI-", "Set default backup mount (Supervisor)"),
    # Tramo 2: ajustes de backup. Ninguna pide token (research R-7):
    # leer es de solo lectura; cambiar `days_until_stale` y releer, ni de
    # solo lectura ni destructivas, e idempotentes.
    "sv_get_backup_settings": ("R-I-", "Get backup settings (Supervisor)"),
    "sv_set_backup_settings": ("--I-", "Set backup settings (Supervisor)"),
    "sv_reload_backups": ("--I-", "Reload backups (Supervisor)"),
    # Spec 015 (contracts/tools.md), familia `system_updates`. La lista solo
    # lee; buscar actualizaciones no pide token pero sale a internet y no es
    # de solo lectura (refresca la caché del Supervisor); actualizar Core es
    # destructiva, idempotente (repetirla a la misma versión la rechaza el
    # Supervisor) y de mundo abierto.
    "sv_list_available_updates": ("R-I-", "List available updates (Supervisor)"),
    "sv_check_for_updates": ("--IO", "Check for updates (Supervisor)"),
    "sv_update_core": ("-DIO", "Update core (Supervisor)"),
    # Tramo 2: OS y Supervisor, mismas garantías que Core. `OS` en mayúsculas
    # por `_TITLE_WORDS` (lo trajo la 013).
    "sv_update_os": ("-DIO", "Update OS (Supervisor)"),
    "sv_update_supervisor": ("-DIO", "Update supervisor (Supervisor)"),
    # Tramo 3: entidades `update` de Core. La lista lee lo que HA tiene; las
    # notas pueden pedirse a internet al leerlas; instalar es destructiva,
    # idempotente y de mundo abierto como las `sv_update_*`.
    "ha_list_updates": ("R-I-", "List updates (Home Assistant)"),
    "ha_get_update_release_notes": ("R-IO", "Get update release notes (Home Assistant)"),
    "ha_install_update": ("-DIO", "Install update (Home Assistant)"),
    # Spec 030, tramo 1 (contracts/tools.md, familia `app_store`). Añadir y
    # quitar piden token, así que son destructivas (invariante de la 1.1.2);
    # añadir, reparar y recargar provocan descargas en el Supervisor (mundo
    # abierto). Todas idempotentes: añadir dos veces da «ya añadido».
    "sv_list_store_repositories": ("R-I-", "List store repositories (Supervisor)"),
    "sv_add_store_repository": ("-DIO", "Add store repository (Supervisor)"),
    "sv_remove_store_repository": ("-DI-", "Remove store repository (Supervisor)"),
    "sv_repair_store_repository": ("--IO", "Repair store repository (Supervisor)"),
    "sv_reload_store": ("--IO", "Reload store (Supervisor)"),
    # Spec 030, tramo 2: las tres de lectura heredan `readOnlyHint` del
    # prefijo `sv_get_` (leen el clon local, no salen); reconstruir pide token
    # (destructiva) y descarga imágenes (mundo abierto).
    "sv_get_addon_changelog": ("R-I-", "Get add-on changelog (Supervisor)"),
    "sv_get_addon_documentation": ("R-I-", "Get add-on documentation (Supervisor)"),
    "sv_get_addon_availability": ("R-I-", "Get add-on availability (Supervisor)"),
    "sv_rebuild_addon": ("-DIO", "Rebuild add-on (Supervisor)"),
    # Spec 017, tramo A (contracts/tools.md): listar por prefijo; la
    # sustitución no guarda y va en `_READ_ONLY_EXACT`; guardar pide token y
    # va en `_DESTRUCTIVE_EXACT`; borrar es destructiva por `ha_delete_`.
    # Ninguna sale a internet (importar, del tramo B, sí).
    "ha_list_blueprints": ("R-I-", "List blueprints (Home Assistant)"),
    "ha_preview_blueprint_substitution": ("R-I-", "Preview blueprint substitution (Home Assistant)"),
    "ha_save_blueprint": ("-DI-", "Save blueprint (Home Assistant)"),
    "ha_delete_blueprint": ("-DI-", "Delete blueprint (Home Assistant)"),
    # Tramo B: importar pide token (`_DESTRUCTIVE_EXACT`) y es la única de
    # la familia de mundo abierto (`_OPEN_WORLD`): HA descarga de la URL.
    "ha_import_blueprint": ("-DIO", "Import blueprint (Home Assistant)"),
    # Tramo C (contracts/tools.md): las ocho solo leen. Las `ha_list_*`, por
    # prefijo; resolver y explicar, en `_READ_ONLY_EXACT`. Ninguna sale a
    # internet.
    "ha_list_device_triggers": ("R-I-", "List device triggers (Home Assistant)"),
    "ha_list_device_conditions": ("R-I-", "List device conditions (Home Assistant)"),
    "ha_list_device_actions": ("R-I-", "List device actions (Home Assistant)"),
    "ha_resolve_target": ("R-I-", "Resolve target (Home Assistant)"),
    "ha_explain_target": ("R-I-", "Explain target (Home Assistant)"),
    "ha_list_triggers_for_target": ("R-I-", "List triggers for target (Home Assistant)"),
    "ha_list_conditions_for_target": ("R-I-", "List conditions for target (Home Assistant)"),
    "ha_list_actions_for_target": ("R-I-", "List actions for target (Home Assistant)"),
    # Tramo D: la espera de trigger solo escucha (lista cerrada de triggers,
    # research R-8), en `_READ_ONLY_EXACT`.
    "ha_wait_for_trigger": ("R-I-", "Wait for trigger (Home Assistant)"),
    # Spec 024, tramo 1 (contracts/tools.md): las dos de imagen solo leen
    # (prefijo `ha_get_`) y son de mundo abierto (`_OPEN_WORLD`): una cámara
    # en la nube o una entidad `image` que descarga de una URL salen a
    # internet al pedir la imagen.
    "ha_get_camera_snapshot": ("R-IO", "Get camera snapshot (Home Assistant)"),
    "ha_get_image_entity": ("R-IO", "Get image entity (Home Assistant)"),
}

# Únicos hints de la 1.1.2 que cambian a propósito en la 1.2.0, con su motivo.
# La tabla de arriba sigue diciendo lo que prometía la 1.1.2.
_HINTS_CAMBIADOS_A_PROPOSITO: dict[str, str] = {
    # Spec 016, tramo C (decisión del supervisor): pide token en cada paso de
    # un flujo `reauth` (cambia credenciales); «pide token ⇔ destructiva».
    "ha_continue_config_entry_flow": "-DI-",
}

# Tools de cada familia nueva de la 1.2.0 (sus contratos). Con la familia
# desactivada no aparece ninguna.
_TOOLS_DE_FAMILIA_1_2_0: dict[str, set[str]] = {
    "integration_flows": {
        "ha_list_discovered_integrations", "ha_ignore_discovery",
        "ha_list_config_flow_domains", "ha_update_config_entry",
        "ha_list_config_subentries", "ha_start_subentry_flow",
        "ha_continue_subentry_flow", "ha_abort_subentry_flow",
        "ha_update_subentry", "ha_delete_subentry",
        "ha_start_reconfigure_flow", "ha_continue_reconfigure_flow",
    },
    "repair_flows": {
        "ha_get_repair", "ha_start_repair_fix", "ha_continue_repair_fix",
        "ha_abort_repair_fix",
    },
    "mounts": {
        "sv_list_mounts", "sv_create_mount", "sv_update_mount",
        "sv_delete_mount", "sv_reload_mount", "sv_set_default_backup_mount",
        "sv_get_backup_settings", "sv_set_backup_settings", "sv_reload_backups",
    },
    "system_updates": {
        "sv_list_available_updates", "sv_check_for_updates", "sv_update_core",
        "sv_update_os", "sv_update_supervisor", "ha_list_updates",
        "ha_get_update_release_notes", "ha_install_update",
    },
    "app_store": {
        "sv_list_store_repositories", "sv_add_store_repository",
        "sv_remove_store_repository", "sv_repair_store_repository",
        "sv_reload_store", "sv_get_addon_changelog",
        "sv_get_addon_documentation", "sv_get_addon_availability",
        "sv_rebuild_addon",
    },
}

# Las de la spec 019, tramo 1 (montajes, CAP-083).
_MOUNTS_019 = (
    "sv_list_mounts", "sv_create_mount", "sv_update_mount", "sv_delete_mount",
    "sv_reload_mount", "sv_set_default_backup_mount",
)
# Las de la spec 019, tramo 2 (ajustes de backup, misma familia).
_BACKUP_SETTINGS_019 = (
    "sv_get_backup_settings", "sv_set_backup_settings", "sv_reload_backups",
)

# Las nueve de la spec 030: tramo 1 (repositorios y recarga, CAP-082) y
# tramo 2 (fichas, disponibilidad y reconstrucción, CAP-082 y CAP-093).
_TIENDA_030 = (
    "sv_list_store_repositories", "sv_add_store_repository",
    "sv_remove_store_repository", "sv_repair_store_repository",
    "sv_reload_store",
    "sv_get_addon_changelog", "sv_get_addon_documentation",
    "sv_get_addon_availability", "sv_rebuild_addon",
)

# Las tools de la spec 013 en este tramo (logs, CAP-081).
_LOGS_013 = (
    "sv_get_core_logs", "sv_get_supervisor_logs", "sv_get_plugin_logs",
    "sv_get_host_logs", "sv_list_host_log_identifiers", "sv_list_boots",
)

# Las del tramo 2 de la spec 013 (disco, host y OS, CAP-085).
_HOST_013 = (
    "sv_list_host_services", "sv_get_disk_usage", "sv_get_os_info",
    "sv_get_swap", "sv_list_datadisk_candidates",
)

# Las del tramo 1 de la spec 015 (actualizaciones, CAP-080).
_UPDATES_015 = ("sv_list_available_updates", "sv_check_for_updates", "sv_update_core")

# Las del tramo 2 de la spec 015 (OS y Supervisor, CAP-080).
_UPDATES_015_T2 = ("sv_update_os", "sv_update_supervisor")

# Las del tramo 3 de la spec 015 (entidades `update`, CAP-064).
_UPDATES_015_T3 = ("ha_list_updates", "ha_get_update_release_notes", "ha_install_update")


def _hint_code(ann) -> str:
    flags = (ann.read_only_hint, ann.destructive_hint,
             ann.idempotent_hint, ann.open_world_hint)
    return "".join(c if f else "-" for c, f in zip("RDIO", flags))


def _real_registry(tool_families_disabled: list[str] | None = None) -> dict:
    """Todas las tools registradas en un `MCPServer` real, ya anotadas
    (todas las familias activas salvo `tool_families_disabled`)."""
    from mcp.server.mcpserver import MCPServer

    previous = os.environ.get("HERMES_DEV")
    os.environ["HERMES_DEV"] = "1"
    try:
        mcp = MCPServer("test-titles")
        register_all_tools(
            mcp,
            MagicMock(),
            fire_event_allowlist=[],
            response_max_bytes=131_072,
            call_service_auto_classify=False,
            tool_families_disabled=tool_families_disabled or [],
        )
    finally:
        if previous is None:
            os.environ.pop("HERMES_DEV", None)
        else:
            os.environ["HERMES_DEV"] = previous
    return {t.name: t for t in mcp._tool_manager.list_tools()}


class TestToolTitles:
    """Cada tool lleva un `title` legible, el mismo en la tool y en sus
    anotaciones, y ninguno se repite: el cliente lo enseña al usuario en vez
    del nombre técnico, y dos iguales no se podrían distinguir."""

    def test_every_tool_has_a_unique_title_equal_to_annotations_title(self):
        tools = _real_registry()
        assert len(tools) > 150, "no se han registrado las tools"
        sin_titulo = sorted(n for n, t in tools.items() if not t.title)
        assert sin_titulo == [], f"tools sin title: {sin_titulo}"
        distintos = sorted(
            n for n, t in tools.items()
            if t.annotations is None or t.annotations.title != t.title)
        assert distintos == [], f"title y annotations.title difieren: {distintos}"
        titulos = [t.title for t in tools.values()]
        repetidos = sorted({x for x in titulos if titulos.count(x) > 1})
        assert repetidos == [], f"títulos repetidos: {repetidos}"

    def test_contract_examples(self):
        from hermes.tools._annotations import title_for

        # Ejemplos de contracts/mcp-y-log.md.
        assert title_for("ha_get_state") == "Get state (Home Assistant)"
        assert title_for("ha_hacs_list_repositories") == "HACS list repositories (Home Assistant)"
        assert title_for("ha_save_lovelace_dashboard") == "Save Lovelace dashboard (Home Assistant)"
        assert title_for("fs_read_file") == "Read file (files)"
        assert title_for("sv_restart_core") == "Restart core (Supervisor)"
        assert title_for("ping") == "Ping"
        assert title_for("hermes_guide") == "Hermes guide"

    def test_titles_reach_the_registered_tools(self):
        tools = _real_registry()
        assert tools["ha_list_statistic_ids"].title == "List statistic IDs (Home Assistant)"
        assert tools["sv_get_addon_logs"].title == "Get add-on logs (Supervisor)"

    def test_hints_did_not_change(self):
        """Las de la 1.1.2 conservan sus hints y las únicas de más son las de
        la 1.2.0 que la spec enumera (FR-021)."""
        tools = _real_registry()
        faltan = sorted(set(_HINTS_SNAPSHOT) - set(tools))
        assert faltan == [], f"tools de la 1.1.2 que ya no están: {faltan}"
        sobran = sorted(set(tools) - set(_HINTS_SNAPSHOT) - set(_HINTS_NUEVAS_1_2_0))
        assert sobran == [], f"tools nuevas sin declarar: {sobran}"
        esperado = {**_HINTS_SNAPSHOT, **_HINTS_CAMBIADOS_A_PROPOSITO}
        cambiados = sorted(
            f"{n}: {esperado[n]} -> {_hint_code(tools[n].annotations)}"
            for n in _HINTS_SNAPSHOT
            if _hint_code(tools[n].annotations) != esperado[n])
        assert cambiados == [], f"hints cambiados: {cambiados}"
        # Cada cambio a propósito es de verdad un cambio respecto a la 1.1.2.
        for nombre, codigo in _HINTS_CAMBIADOS_A_PROPOSITO.items():
            assert _HINTS_SNAPSHOT[nombre] != codigo, nombre

    def test_hints_y_titulos_de_las_nuevas(self):
        """Contrato de la 011 (contracts/tools.md): hints y títulos exactos."""
        tools = _real_registry()
        for nombre, (codigo, titulo) in _HINTS_NUEVAS_1_2_0.items():
            assert nombre in tools, f"{nombre} no está registrada"
            assert _hint_code(tools[nombre].annotations) == codigo, nombre
            assert tools[nombre].title == titulo, (nombre, tools[nombre].title)

    def test_api_no_cambia_ningun_titulo_existente(self):
        """`"api": "API"` en `_TITLE_WORDS` solo toca a las nuevas: ninguna
        tool de la 1.1.2 tiene `api` como palabra de su nombre."""
        con_api = sorted(n for n in _HINTS_SNAPSHOT if "api" in n.split("_"))
        assert con_api == [], con_api

    def test_os_no_cambia_ningun_titulo_existente(self):
        """Spec 013 (T021): `"os": "OS"` da `Get OS info (Supervisor)` y no
        toca ningún título de la 1.1.2: ninguna tiene `os` como palabra."""
        from hermes.tools._annotations import title_for

        assert title_for("sv_get_os_info") == "Get OS info (Supervisor)"
        con_os = sorted(n for n in _HINTS_SNAPSHOT if "os" in n.split("_"))
        assert con_os == [], con_os

    def test_esquemas_de_la_1_1_2(self):
        """Las tools de la 1.1.2 conservan los argumentos (nombres y
        obligatorios) de su esquema de entrada (FR-021).

        `tests/fixtures/esquemas_1_1_2.json` se generó del registro real ANTES
        de añadir las genéricas, con:

            tools = _real_registry()
            {n: {"properties": sorted(t.parameters.get("properties", {})),
                 "required": sorted(t.parameters.get("required", []))}
             for n, t in sorted(tools.items())}

        (json.dumps con indent=1 y sort_keys). No se regenera: es la referencia.
        """
        import json

        ruta = pathlib.Path(__file__).resolve().parent / "fixtures" / "esquemas_1_1_2.json"
        esperado = json.loads(ruta.read_text(encoding="utf-8"))
        # Única diferencia permitida (spec 011, T032 f; research R-8):
        # `hermes_guide` gana el argumento OPCIONAL `search`. Un argumento
        # opcional nuevo no rompe a ningún cliente que no lo use; uno
        # obligatorio, sí, por eso `search` no puede entrar en `required`.
        esperado["hermes_guide"] = {
            "properties": sorted([*esperado["hermes_guide"]["properties"], "search"]),
            "required": esperado["hermes_guide"]["required"],
        }
        # Segunda diferencia permitida, de la spec 009 (FR-007 de la 009,
        # FR-031 de la 008): `ha_marketplace_list_removed` gana los argumentos
        # OPCIONALES `installed_only` y `limit`. Sin ellos la lista es la de la
        # 1.1.2. Esta excepción entra al integrar la 011 con la 009: cada rama
        # tenía la suya y la referencia es común.
        esperado["ha_marketplace_list_removed"] = {
            "properties": sorted([*esperado["ha_marketplace_list_removed"]["properties"],
                                  "installed_only", "limit"]),
            "required": esperado["ha_marketplace_list_removed"]["required"],
        }
        # Tercera diferencia permitida, de la spec 013 (FR-007; research R-3):
        # `sv_get_addon_logs` gana `boot` y `latest`, OPCIONALES. Sin ellos la
        # petición y la respuesta son las de la 1.1.2 (lo comprueba
        # `test_tools_supervisor.TestLogsDeAddonPorArranque`).
        esperado["sv_get_addon_logs"] = {
            "properties": sorted([*esperado["sv_get_addon_logs"]["properties"],
                                  "boot", "latest"]),
            "required": esperado["sv_get_addon_logs"]["required"],
        }
        # Cuarta diferencia permitida, de la spec 018 (FR-016 de la 018,
        # FR-063 de la 008): `ha_save_lovelace_dashboard` gana `view_index` y
        # `view`, OPCIONALES, para guardar una sola vista. Sin ellos el
        # guardado completo es el de la 1.1.2; `required` no cambia.
        esperado["ha_save_lovelace_dashboard"] = {
            "properties": sorted([*esperado["ha_save_lovelace_dashboard"]["properties"],
                                  "view", "view_index"]),
            "required": esperado["ha_save_lovelace_dashboard"]["required"],
        }
        # Quinta diferencia permitida, de la spec 018 (FR-016 de la 018,
        # FR-064 de la 008): `ha_call_service_response` gana
        # `confirmation_token`, OPCIONAL, para confirmar la denylist y las
        # entidades restringidas. Sin él responde como en la 1.1.2 (el mismo
        # `error`, con el token añadido); `required` no cambia.
        esperado["ha_call_service_response"] = {
            "properties": sorted([*esperado["ha_call_service_response"]["properties"],
                                  "confirmation_token"]),
            "required": esperado["ha_call_service_response"]["required"],
        }
        # Sexta diferencia permitida, de la spec 033 (FR-011 de la 033,
        # FR-099 de la 008): `ha_wait_for_event` pierde `ctx` (propiedad y
        # obligatorio). Era el `Context` del SDK mal anotado (`Any`): se
        # publicaba como argumento obligatorio sin ningún valor con sentido, y
        # un cliente que lo siga mandando no recibe error (el SDK no prohíbe
        # claves de más; `tests/test_tools_wait_for_event.py` lo comprueba).
        esperado["ha_wait_for_event"] = {
            "properties": [p for p in esperado["ha_wait_for_event"]["properties"] if p != "ctx"],
            "required": [r for r in esperado["ha_wait_for_event"]["required"] if r != "ctx"],
        }
        # Séptima, también de la 033 (FR-006 y FR-011; FR-099 de la 008):
        # `ha_create_scene_from_current` gana `confirmation_token` OPCIONAL,
        # que solo hace falta para reemplazar una escena temporal. Quien no lo
        # usa sigue llamando igual.
        esperado["ha_create_scene_from_current"] = {
            "properties": sorted([*esperado["ha_create_scene_from_current"]["properties"],
                                  "confirmation_token"]),
            "required": esperado["ha_create_scene_from_current"]["required"],
        }
        # Octava diferencia permitida, de la spec 016 (tramo C, decisión del
        # supervisor): `ha_continue_config_entry_flow` gana el argumento
        # OPCIONAL `confirmation_token`, que solo usan los flujos `reauth`.
        # Una llamada de la 1.1.2 sin él sigue valiendo para los demás.
        esperado["ha_continue_config_entry_flow"] = {
            "properties": sorted([*esperado["ha_continue_config_entry_flow"]["properties"],
                                  "confirmation_token"]),
            "required": esperado["ha_continue_config_entry_flow"]["required"],
        }
        # Novena diferencia permitida, de la spec 019 (FR-014 y FR-017 de la
        # 019, FR-066 de la 008): `sv_create_backup_full` y
        # `sv_create_backup_partial` ganan `location`, OPCIONAL, para elegir
        # el montaje. Sin ella la carga y la respuesta son las de la 1.1.2 (lo
        # comprueba `test_tools_supervisor.TestUbicacionDelBackup`); nunca
        # entra en `required`.
        for nombre in ("sv_create_backup_full", "sv_create_backup_partial"):
            esperado[nombre] = {
                "properties": sorted([*esperado[nombre]["properties"], "location"]),
                "required": esperado[nombre]["required"],
            }
        assert set(esperado) == set(_HINTS_SNAPSHOT)
        tools = _real_registry()
        distintos = []
        for nombre, esquema in esperado.items():
            actual = tools[nombre].parameters
            real = {"properties": sorted(actual.get("properties", {})),
                    "required": sorted(actual.get("required", []))}
            if real != esquema:
                distintos.append(f"{nombre}: {esquema} -> {real}")
        assert distintos == [], "esquemas cambiados: " + "; ".join(distintos)


# ── Spec 011: registro por familias (FR-020, FR-021, SC-005; T032) ────────────

def _tools_por_modulo() -> dict[str, set[str]]:
    """Módulo de `hermes/tools/` → nombres de las tools que declara (AST)."""
    out: dict[str, set[str]] = {}
    for path in sorted(_TOOLS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            for deco in node.decorator_list:
                is_tool = (
                    isinstance(deco, ast.Call)
                    and getattr(getattr(deco, "func", None), "attr", "") == "tool"
                ) or (isinstance(deco, ast.Attribute) and deco.attr == "tool")
                if is_tool:
                    out.setdefault(path.stem, set()).add(node.name)
                    break
    return out


class TestRegistroPorFamilias:
    """`tool_families_disabled` quita exactamente las tools de las familias
    nombradas, y con las familias de la 1.2.0 apagadas la lista vuelve a ser
    la de la 1.1.2 (SC-005).

    Control negativo (T042 b): registrar `lovelace` aunque esté desactivada
    (quitar su `if _activa(...)`) → caen `test_cada_familia_quita_sus_tools`
    («lovelace») y `test_cada_register_dentro_de_su_familia`; con
    `generic_commands`, además `test_sc005_sin_las_de_la_1_2_0_queda_la_1_1_2`.
    """

    def test_cada_familia_quita_sus_tools(self):
        from hermes.tool_families import FAMILIAS

        completo = set(_do_register().tools)
        por_modulo = _tools_por_modulo()
        for nombre, familia in FAMILIAS.items():
            if not familia.desactivable:
                continue
            reducido = set(_do_register([nombre]).tools)
            esperadas = set().union(*(por_modulo.get(m, set()) for m in familia.modulos))
            assert esperadas, f"{nombre}: la familia no declara tools"
            assert completo - reducido == esperadas, (
                f"{nombre}: quita {sorted(completo - reducido)}, "
                f"debería quitar {sorted(esperadas)}")
            assert reducido <= completo, nombre

    def test_sc005_sin_las_de_la_1_2_0_queda_la_1_1_2(self):
        """SC-005: con todas las familias `desde="1.2.0"` desactivadas, los
        nombres son EXACTAMENTE los 216 de la 1.1.2 (más `test_progress`,
        que solo existe con HERMES_DEV y ya estaba en la instantánea) y con
        los mismos hints."""
        from hermes.tool_families import FAMILIAS

        nuevas = [n for n, f in FAMILIAS.items() if f.desde == "1.2.0"]
        assert {"generic_commands", "system_diagnostics", "mounts",
                "system_updates"} <= set(nuevas)
        tools = _real_registry(nuevas)
        assert set(tools) == set(_HINTS_SNAPSHOT), (
            f"sobran {sorted(set(tools) - set(_HINTS_SNAPSHOT))}, "
            f"faltan {sorted(set(_HINTS_SNAPSHOT) - set(tools))}")
        assert len(set(tools) - {"test_progress"}) == 216
        # Salvo los cambios a propósito (y justificados) de la 1.2.0.
        esperado = {**_HINTS_SNAPSHOT, **_HINTS_CAMBIADOS_A_PROPOSITO}
        cambiados = sorted(
            n for n in _HINTS_SNAPSHOT
            if _hint_code(tools[n].annotations) != esperado[n])
        assert cambiados == [], f"hints cambiados: {cambiados}"

    def test_familias_nuevas_con_sus_tools(self):
        """Spec 016 (T009, FR-017): cada familia nueva de la 1.2.0 registra
        exactamente sus tools y, desactivada, ninguna (las demás siguen)."""
        completo = set(_do_register().tools)
        for familia, tools in _TOOLS_DE_FAMILIA_1_2_0.items():
            assert tools <= completo, (familia, sorted(tools - completo))
            reducido = set(_do_register([familia]).tools)
            assert reducido.isdisjoint(tools), (familia, sorted(reducido & tools))
            assert completo - reducido == tools, familia

    def test_por_defecto_la_1_1_2_entera(self):
        """Con la opción vacía, las 216 están y con los mismos hints."""
        tools = _real_registry()
        assert set(_HINTS_SNAPSHOT) <= set(tools)
        esperado = {**_HINTS_SNAPSHOT, **_HINTS_CAMBIADOS_A_PROPOSITO}
        assert all(_hint_code(tools[n].annotations) == h for n, h in esperado.items())

    def test_cada_register_dentro_de_su_familia(self):
        """Por AST: cada `register_*` importado de `hermes.tools.<módulo>`
        dentro de `register_all_tools` se llama dentro de un
        `if _activa("<familia>")` cuya familia es la de su módulo. Un bloque
        nuevo sin comprobación se registraría siempre, aunque el usuario
        apagara su familia."""
        from hermes.tool_families import familia_de_modulo

        arbol = ast.parse((_TOOLS_DIR / "__init__.py").read_text(encoding="utf-8"))
        funcion = next(n for n in ast.walk(arbol)
                       if isinstance(n, ast.FunctionDef) and n.name == "register_all_tools")
        padres: dict[ast.AST, ast.AST] = {}
        for nodo in ast.walk(funcion):
            for hijo in ast.iter_child_nodes(nodo):
                padres[hijo] = nodo
        modulo_de: dict[str, str] = {}
        for nodo in ast.walk(funcion):
            if (isinstance(nodo, ast.ImportFrom) and nodo.module
                    and nodo.module.startswith("hermes.tools.")):
                for alias in nodo.names:
                    if alias.name.startswith("register"):
                        modulo_de[alias.asname or alias.name] = nodo.module.rsplit(".", 1)[1]
        assert len(modulo_de) >= 40, modulo_de

        def familia_del_if(nodo: ast.AST) -> str | None:
            while nodo in padres:
                nodo = padres[nodo]
                if (isinstance(nodo, ast.If) and isinstance(nodo.test, ast.Call)
                        and getattr(nodo.test.func, "id", "") == "_activa"
                        and nodo.test.args
                        and isinstance(nodo.test.args[0], ast.Constant)):
                    return nodo.test.args[0].value
            return None

        llamadas = [n for n in ast.walk(funcion)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id in modulo_de]
        assert {c.func.id for c in llamadas} == set(modulo_de), "register importado sin llamar"
        errores = []
        for llamada in llamadas:
            modulo = modulo_de[llamada.func.id]
            esperada = familia_de_modulo(modulo)
            real = familia_del_if(llamada)
            if real != esperada:
                errores.append(f"{modulo}: dentro de {real!r}, debería ser {esperada!r}")
        assert errores == [], errores

    def test_log_de_arranque(self):
        from structlog.testing import capture_logs

        completo = len(_do_register().tools)
        with capture_logs() as logs:
            mcp = _do_register(["marketplace", "lovelace"])
        eventos = [e for e in logs if e.get("event") == "tool_families"]
        assert len(eventos) == 1, eventos
        assert eventos[0]["disabled"] == ["lovelace", "marketplace"]
        assert eventos[0]["tools_registered"] == len(mcp.tools) < completo
        with capture_logs() as logs:
            _do_register()
        eventos = [e for e in logs if e.get("event") == "tool_families"]
        assert eventos[0]["disabled"] == []
        assert eventos[0]["tools_registered"] == completo

    def test_un_nombre_invalido_no_registra_nada(self):
        """Fail-closed también si se llama sin pasar por `validate()`."""
        import pytest

        with pytest.raises(ValueError, match="familia_inventada"):
            _do_register(["familia_inventada"])
        with pytest.raises(ValueError, match="base"):
            _do_register(["base"])


# ── Spec 013: logs del sistema (FR-021, FR-022; T011) ─────────────────────────


class TestLogsDelSistema013:
    """Las seis tools de logs se registran por defecto, solo leen y no piden
    token; con `system_diagnostics` apagada no existe ninguna, y
    `sv_get_addon_logs` (familia `supervisor`) conserva `boot` y `latest`."""

    def test_registradas_y_de_solo_lectura(self):
        tools = _real_registry()
        for nombre in _LOGS_013:
            assert nombre in tools, nombre
            ann = tools[nombre].annotations
            assert ann.read_only_hint is True, nombre
            assert ann.destructive_hint is False, nombre
            assert ann.idempotent_hint is True, nombre
            assert ann.open_world_hint is False, nombre
            assert "confirmation_token" not in tools[nombre].parameters.get(
                "properties", {}), nombre

    def test_argumentos(self):
        tools = _real_registry()
        props = {n: set(tools[n].parameters.get("properties", {})) for n in _LOGS_013}
        assert props["sv_get_core_logs"] == {"lines", "boot", "latest"}
        assert props["sv_get_supervisor_logs"] == {"lines", "boot", "latest"}
        assert props["sv_get_plugin_logs"] == {"plugin", "lines", "boot", "latest"}
        assert props["sv_get_host_logs"] == {"lines", "boot", "identifier"}
        assert props["sv_list_host_log_identifiers"] == {"search"}
        assert props["sv_list_boots"] == set()
        assert tools["sv_get_plugin_logs"].parameters.get("required") == ["plugin"]

    def test_con_la_familia_apagada(self):
        tools = _real_registry(["system_diagnostics"])
        assert [n for n in _LOGS_013 + _HOST_013 if n in tools] == []
        esquema = tools["sv_get_addon_logs"].parameters
        assert {"boot", "latest"} <= set(esquema["properties"])
        assert sorted(esquema.get("required", [])) == ["slug"]


# ── Spec 013, tramo 2: disco, host y OS (FR-021; T020, T024) ─────────────────


class TestHostSystem013:
    """Las cinco tools de disco, host y OS se registran por defecto, solo leen
    y no piden token; con `system_diagnostics` apagada no existe ninguna y la
    tabla sigue apuntándolas como `dedicated`."""

    def test_registradas_y_de_solo_lectura(self):
        tools = _real_registry()
        for nombre in _HOST_013:
            assert nombre in tools, nombre
            ann = tools[nombre].annotations
            assert ann.read_only_hint is True, nombre
            assert ann.destructive_hint is False, nombre
            assert ann.idempotent_hint is True, nombre
            assert ann.open_world_hint is False, nombre
            assert "confirmation_token" not in tools[nombre].parameters.get(
                "properties", {}), nombre

    def test_argumentos(self):
        tools = _real_registry()
        props = {n: set(tools[n].parameters.get("properties", {})) for n in _HOST_013}
        assert props == {
            "sv_list_host_services": {"state"},
            "sv_get_disk_usage": {"disk", "max_depth"},
            "sv_get_os_info": set(),
            "sv_get_swap": set(),
            "sv_list_datadisk_candidates": set(),
        }
        assert not tools["sv_get_disk_usage"].parameters.get("required")

    def test_con_la_familia_apagada_la_tabla_sigue_igual(self):
        """T024 (FR-021; FR-012 de la 008): apagar la familia quita las tools
        pero no cambia la tabla: sus 28 entradas siguen `dedicated` y apuntan
        a tools de `system_diagnostics` o de `supervisor`."""
        from hermes.command_table import SUPERVISOR

        tools = _real_registry(["system_diagnostics"])
        dedicadas = {
            k: e for k, e in SUPERVISOR.items()
            if e.category == "dedicated" and e.family == "system_diagnostics"
        }
        assert len(dedicadas) == 26
        assert {e.tool for e in dedicadas.values()} == set(_LOGS_013 + _HOST_013)
        con_boot = [k for k, e in SUPERVISOR.items()
                    if e.category == "dedicated" and e.cap == "CAP-081"
                    and e.family == "supervisor"]
        assert len(con_boot) == 2
        assert [n for n in _LOGS_013 + _HOST_013 if n in tools] == []


# ── Spec 019, tramo 1: montajes del Supervisor (FR-016, SC-001; T011) ────────


class TestMontajes019:
    """Las seis tools de montajes se registran por defecto; las cuatro que
    piden token se anuncian destructivas y la de lectura `readOnlyHint`; con
    `mounts` apagada no existe ninguna y sus rutas siguen `dedicated`."""

    _CON_TOKEN = ("sv_create_mount", "sv_update_mount", "sv_delete_mount",
                  "sv_set_default_backup_mount")

    def test_registradas_y_sus_hints(self):
        tools = _real_registry()
        for nombre in _MOUNTS_019:
            assert nombre in tools, nombre
            ann = tools[nombre].annotations
            assert ann.open_world_hint is False, nombre
            con_token = "confirmation_token" in tools[nombre].parameters.get(
                "properties", {})
            assert con_token == (nombre in self._CON_TOKEN), nombre
            assert ann.destructive_hint == con_token, nombre
        assert tools["sv_list_mounts"].annotations.read_only_hint is True
        recargar = tools["sv_reload_mount"].annotations
        assert (recargar.read_only_hint, recargar.destructive_hint,
                recargar.idempotent_hint) == (False, False, True)

    def test_ajustes_de_backup_registrados_y_sus_hints(self):
        # Tramo 2 (T025): sin token; leer, de solo lectura; cambiar y releer,
        # ni de solo lectura ni destructivas, e idempotentes.
        tools = _real_registry()
        for nombre in _BACKUP_SETTINGS_019:
            assert nombre in tools, nombre
            ann = tools[nombre].annotations
            assert ann.open_world_hint is False, nombre
            assert ann.destructive_hint is False, nombre
            assert ann.idempotent_hint is True, nombre
            assert "confirmation_token" not in tools[nombre].parameters.get(
                "properties", {}), nombre
            assert ann.read_only_hint is (nombre == "sv_get_backup_settings"), nombre
        assert set(tools["sv_set_backup_settings"].parameters["properties"]) == {
            "days_until_stale"}
        assert tools["sv_set_backup_settings"].parameters["required"] == [
            "days_until_stale"]

    def test_argumentos(self):
        tools = _real_registry()
        props = {n: set(tools[n].parameters.get("properties", {})) for n in _MOUNTS_019}
        campos = {"name", "type", "usage", "server", "share", "path", "port",
                  "version", "read_only", "username", "password", "device", "uuid",
                  "confirmation_token"}
        assert props == {
            "sv_list_mounts": set(),
            "sv_create_mount": campos,
            "sv_update_mount": campos,
            "sv_delete_mount": {"name", "confirmation_token"},
            "sv_reload_mount": {"name"},
            "sv_set_default_backup_mount": {"name", "confirmation_token"},
        }
        assert sorted(tools["sv_create_mount"].parameters["required"]) == [
            "name", "type", "usage"]
        assert tools["sv_update_mount"].parameters["required"] == ["name"]

    def test_con_la_familia_apagada(self):
        from hermes.command_table import SUPERVISOR

        tools = _real_registry(["mounts"])
        assert [n for n in _MOUNTS_019 + _BACKUP_SETTINGS_019 if n in tools] == []
        dedicadas = {e.tool for e in SUPERVISOR.values()
                     if e.category == "dedicated" and e.family == "mounts"}
        assert dedicadas == set(_MOUNTS_019 + _BACKUP_SETTINGS_019)
        # `location` es de `backups` (1.1.2): sigue aunque `mounts` se apague.
        assert "location" in tools["sv_create_backup_full"].parameters["properties"]


# ── Spec 015, tramo 1: actualizaciones del sistema (FR-017, FR-019; T009) ─────


class TestActualizaciones015:
    """Las tres tools del tramo 1 se registran por defecto con las anotaciones
    de contracts/tools.md; con `system_updates` apagada no existe ninguna y
    las entradas de la tabla siguen apuntándolas como `dedicated`.

    Control negativo (T015 g, en test_command_table): dejar `/core/update`
    como `deny` → cae `TestActualizacionesDeLa015`.
    """

    def test_registradas_con_sus_anotaciones(self):
        tools = _real_registry()
        for nombre in _UPDATES_015:
            assert nombre in tools, nombre
        ann = {n: tools[n].annotations for n in _UPDATES_015}
        assert ann["sv_list_available_updates"].read_only_hint is True
        assert ann["sv_list_available_updates"].open_world_hint is False
        # Refresca la caché del Supervisor y la tienda: ni de solo lectura ni
        # destructiva, pero sí sale a internet.
        assert ann["sv_check_for_updates"].read_only_hint is False
        assert ann["sv_check_for_updates"].destructive_hint is False
        assert ann["sv_check_for_updates"].open_world_hint is True
        assert ann["sv_update_core"].destructive_hint is True
        assert ann["sv_update_core"].open_world_hint is True
        assert ann["sv_update_core"].idempotent_hint is True

    def test_argumentos(self):
        tools = _real_registry()
        props = {n: set(tools[n].parameters.get("properties", {})) for n in _UPDATES_015}
        assert props == {
            "sv_list_available_updates": set(),
            "sv_check_for_updates": set(),
            "sv_update_core": {"version", "backup", "confirmation_token"},
        }
        assert not tools["sv_update_core"].parameters.get("required")
        assert tools["sv_update_core"].parameters["properties"]["backup"].get("default") is True

    def test_con_la_familia_apagada(self):
        from hermes.command_table import CORE_WS, SUPERVISOR

        tools = _real_registry(["system_updates"])
        todas = _UPDATES_015 + _UPDATES_015_T2 + _UPDATES_015_T3
        assert [n for n in todas if n in tools] == []
        dedicadas = [e.tool for e in (*CORE_WS.values(), *SUPERVISOR.values())
                     if e.category == "dedicated" and e.family == "system_updates"]
        # Las que tienen entrada en la tabla: todas salvo `ha_list_updates` y
        # `ha_install_update` (lee estados; instala por `call_service`).
        assert sorted(set(dedicadas)) == sorted(
            _UPDATES_015 + _UPDATES_015_T2 + ("ha_get_update_release_notes",))
        # 5 del tramo 1, 2 del tramo 2 y `update/release_notes` del tramo 3.
        assert len(dedicadas) == 8

    def test_tramo_2_registradas_con_sus_anotaciones(self):
        """Tramo 2 (T024): las dos destructivas, idempotentes y de mundo
        abierto; `sv_update_supervisor` sin argumento `version` (FR-007)."""
        tools = _real_registry()
        for nombre in _UPDATES_015_T2:
            ann = tools[nombre].annotations
            assert _hint_code(ann) == "-DIO", nombre
        assert set(tools["sv_update_os"].parameters["properties"]) == {
            "version", "confirmation_token"}
        assert set(tools["sv_update_supervisor"].parameters["properties"]) == {
            "confirmation_token"}
        assert tools["sv_update_os"].title == "Update OS (Supervisor)"

    def test_tramo_3_entidades_update(self):
        """Tramo 3 (T036): las tres con sus anotaciones y argumentos de
        contracts/tools.md; `ha_install_update` con backup=false por defecto
        (el de `update.install` en Core)."""
        tools = _real_registry()
        codigos = {n: _hint_code(tools[n].annotations) for n in _UPDATES_015_T3}
        assert codigos == {"ha_list_updates": "R-I-",
                           "ha_get_update_release_notes": "R-IO",
                           "ha_install_update": "-DIO"}
        props = {n: set(tools[n].parameters.get("properties", {})) for n in _UPDATES_015_T3}
        assert props == {
            "ha_list_updates": {"include_up_to_date"},
            "ha_get_update_release_notes": {"entity_id"},
            "ha_install_update": {"entity_id", "version", "backup", "confirmation_token"},
        }
        assert tools["ha_install_update"].parameters["required"] == ["entity_id"]
        assert tools["ha_install_update"].parameters["properties"]["backup"].get("default") is False


# ── Spec 004: Marketplace y alias `ha_hacs_*` (FR-018, FR-021, SC-006) ───────

_MARKETPLACE_TOOLS = (
    "ha_marketplace_info", "ha_marketplace_list_repositories",
    "ha_marketplace_get_repository", "ha_marketplace_list_updates",
    "ha_marketplace_list_releases", "ha_marketplace_list_critical",
    "ha_marketplace_list_removed",
)
_HACS_ALIASES = (
    "ha_hacs_info", "ha_hacs_list_repositories",
    "ha_hacs_get_repository", "ha_hacs_list_updates",
)


class TestSystemStatusRegistration:
    """Spec 029, T010 (FR-015, FR-017, SC-001): las cinco de CAP-043 se
    registran, ninguna pide `confirmation_token` y con `system_status`
    desactivada no queda ninguna y el resto no cambia."""

    _CINCO = {
        "ha_get_system_health", "ha_get_system_state",
        "ha_list_integration_setup_times", "ha_list_integration_manifests",
        "ha_get_integration_manifest",
    }

    def test_registradas_y_sin_token(self):
        tools = _real_registry()
        assert self._CINCO <= set(tools)
        for nombre in self._CINCO:
            props = tools[nombre].parameters.get("properties", {})
            assert "confirmation_token" not in props, nombre

    def test_desactivada_no_registra_ninguna(self):
        completo = set(_real_registry())
        sin = set(_real_registry(["system_status"]))
        assert completo - sin == self._CINCO
        assert sin <= completo


class TestRecorderRegistration:
    """Spec 029, T020 (FR-015, FR-017, SC-001): las tres de CAP-049 se
    registran sin `confirmation_token`; con `recorder` desactivada no queda
    ninguna, y con `system_status` y `recorder` desactivadas la lista es
    exactamente la de antes de la 029."""

    _TRES = {"ha_validate_statistics", "ha_get_statistics_metadata", "ha_get_recorder_info"}

    def test_registradas_y_sin_token(self):
        tools = _real_registry()
        assert self._TRES <= set(tools)
        for nombre in self._TRES:
            props = tools[nombre].parameters.get("properties", {})
            assert "confirmation_token" not in props, nombre

    def test_desactivada_no_registra_ninguna(self):
        completo = set(_real_registry())
        sin = set(_real_registry(["recorder"]))
        assert completo - sin == self._TRES

    def test_sin_las_dos_familias_es_la_lista_de_antes_de_la_029(self):
        completo = set(_real_registry())
        sin = set(_real_registry(["system_status", "recorder"]))
        assert completo - sin == self._TRES | TestSystemStatusRegistration._CINCO
        assert sin <= completo


class TestTiendaDeApps030:
    """Spec 030, T008 y T023 (FR-015, FR-016): las nueve tools de la tienda
    se registran por defecto con las anotaciones de contracts/tools.md;
    añadir, quitar y reconstruir llevan `confirmation_token`, el resto no;
    con `app_store` desactivada no queda ninguna y el resto no cambia.

    Control negativo comprobado: quitar `sv_remove_store_repository` de
    `_DESTRUCTIVE_EXACT` → caen `test_anotaciones` y el invariante de
    `TestDestructiveToolsAskBeforeActing`."""

    def test_anotaciones(self):
        tools = _real_registry()
        for nombre in _TIENDA_030:
            assert nombre in tools, nombre
            codigo, titulo = _HINTS_NUEVAS_1_2_0[nombre]
            assert _hint_code(tools[nombre].annotations) == codigo, nombre
            assert tools[nombre].title == titulo, nombre

    def test_argumentos(self):
        tools = _real_registry()
        props = {n: set(tools[n].parameters.get("properties", {})) for n in _TIENDA_030}
        assert props == {
            "sv_list_store_repositories": {"repository"},
            "sv_add_store_repository": {"repository", "confirmation_token"},
            "sv_remove_store_repository": {"repository", "confirmation_token"},
            "sv_repair_store_repository": {"repository"},
            "sv_reload_store": set(),
            "sv_get_addon_changelog": {"slug", "offset", "max_chars"},
            "sv_get_addon_documentation": {"slug", "offset", "max_chars"},
            "sv_get_addon_availability": {"slug"},
            "sv_rebuild_addon": {"slug", "force", "confirmation_token"},
        }
        for nombre in ("sv_add_store_repository", "sv_remove_store_repository",
                       "sv_repair_store_repository"):
            assert tools[nombre].parameters.get("required") == ["repository"], nombre
        for nombre in ("sv_get_addon_changelog", "sv_get_addon_documentation",
                       "sv_get_addon_availability", "sv_rebuild_addon"):
            assert tools[nombre].parameters.get("required") == ["slug"], nombre

    def test_las_tres_de_la_1_1_2_no_cambian(self):
        """T023 (SC-005): `sv_install_addon`, `sv_update_addon` y
        `sv_set_addon_options` ganan vista previa, no argumentos ni
        anotaciones."""
        tools = _real_registry()
        for nombre in ("sv_install_addon", "sv_update_addon", "sv_set_addon_options"):
            assert _hint_code(tools[nombre].annotations) == _HINTS_SNAPSHOT[nombre], nombre
        assert set(tools["sv_install_addon"].parameters["properties"]) == {
            "slug", "confirmation_token"}
        assert set(tools["sv_update_addon"].parameters["properties"]) == {
            "slug", "confirmation_token"}
        assert set(tools["sv_set_addon_options"].parameters["properties"]) == {
            "slug", "options", "confirmation_token"}

    def test_con_la_familia_apagada(self):
        completo = set(_real_registry())
        sin = set(_real_registry(["app_store"]))
        assert completo - sin == set(_TIENDA_030)


class TestMarketplaceRegistration:
    def test_marketplace_and_aliases_are_registered(self):
        mcp = _register_all()
        faltan = sorted(n for n in _MARKETPLACE_TOOLS + _HACS_ALIASES if n not in mcp.tools)
        assert faltan == [], f"no registradas: {faltan}"

    def test_all_read_only_and_only_releases_is_open_world(self):
        from hermes.tools._annotations import classify

        for name in _MARKETPLACE_TOOLS + _HACS_ALIASES:
            ann = classify(name)
            assert ann.read_only_hint, name
            assert not ann.destructive_hint, name
            # Solo `list_releases` pide datos a GitHub; el resto lee lo que HA
            # ya tiene en memoria.
            assert ann.open_world_hint is (name == "ha_marketplace_list_releases"), name

    def test_read_only_is_by_exact_name_not_prefix(self):
        """Fail-closed: una tool de escritura futura con el prefijo
        `ha_marketplace_` no puede heredar el `readOnlyHint` por el nombre."""
        from hermes.tools._annotations import classify

        assert not classify("ha_marketplace_install").read_only_hint

    def test_retirados_con_argumentos_nuevos_opcionales(self):
        """009 (FR-007, FR-014): `installed_only` y `limit` existen en el
        esquema que ve el cliente y no son obligatorios: una llamada de la
        1.1.2 sin argumentos sigue valiendo."""
        esquema = _real_registry()["ha_marketplace_list_removed"].parameters
        assert {"installed_only", "limit"} <= set(esquema["properties"])
        assert not {"installed_only", "limit"} & set(esquema.get("required", []))


# ── Spec 005, bloques A y B: plantas, etiquetas, categorías y diagnóstico ────

_ORGANIZACION_Y_DIAGNOSTICO = (
    "ha_list_floors", "ha_create_floor", "ha_update_floor", "ha_delete_floor",
    "ha_list_labels", "ha_create_label", "ha_update_label", "ha_delete_label",
    "ha_list_categories", "ha_create_category", "ha_update_category",
    "ha_delete_category",
    "ha_list_repairs", "ha_ignore_repair",
    "ha_list_traces", "ha_get_trace", "ha_search_related",
)


class TestOrganizationAndDiagnosticsRegistration:
    def test_registered(self):
        mcp = _register_all()
        faltan = sorted(n for n in _ORGANIZACION_Y_DIAGNOSTICO if n not in mcp.tools)
        assert faltan == [], f"no registradas: {faltan}"

    def test_read_only(self):
        from hermes.tools._annotations import classify

        for name in ("ha_list_floors", "ha_list_labels", "ha_list_categories",
                     "ha_list_repairs", "ha_list_traces", "ha_get_trace",
                     "ha_search_related"):
            ann = classify(name)
            assert ann.read_only_hint, name
            assert not ann.destructive_hint, name

    def test_token_tools_are_destructive(self):
        from hermes.tools._annotations import classify

        for name in ("ha_update_floor", "ha_update_label", "ha_update_category",
                     "ha_ignore_repair", "ha_delete_floor", "ha_delete_label",
                     "ha_delete_category"):
            ann = classify(name)
            assert not ann.read_only_hint, name
            assert ann.destructive_hint, name

    def test_creates_are_additive_and_not_idempotent(self):
        from hermes.tools._annotations import classify

        for name in ("ha_create_floor", "ha_create_label", "ha_create_category"):
            ann = classify(name)
            assert not ann.read_only_hint, name
            assert not ann.destructive_hint, name
            assert not ann.idempotent_hint, name

    def test_traces_receive_response_max_bytes(self):
        """Una sola traza de una automatización larga puede pesar megas: si el
        módulo no recibe el límite configurado, usa su tope interno y la
        opción `response_max_bytes` deja de mandar sobre `ha_get_trace`."""
        from unittest.mock import patch

        with patch("hermes.tools.traces.register") as reg:
            mcp = _RecordingMCP()
            register_all_tools(
                mcp, MagicMock(), fire_event_allowlist=[],
                response_max_bytes=54_321, call_service_auto_classify=False,
            )
        assert reg.call_args.kwargs.get("response_max_bytes") == 54_321

    def test_none_is_open_world(self):
        from hermes.tools._annotations import classify

        assert [n for n in _ORGANIZACION_Y_DIAGNOSTICO if classify(n).open_world_hint] == []


# ── Spec 012, tramo A: logs de Core (FR-013, FR-015, FR-020; T012) ──────────

_CORE_LOGS = (
    "ha_list_system_log", "ha_get_error_log", "ha_get_log_levels",
    "ha_set_log_level", "ha_clear_system_log",
)


class TestCoreLogsRegistration:
    """Las cinco tools de `core_logs` se registran bajo `core_diagnostics`,
    con los hints del contrato (`_HINTS_NUEVAS_1_2_0`) y desaparecen con la
    familia desactivada.

    Control negativo (T018 h): quitar `ha_set_log_level` de
    `_DESTRUCTIVE_EXACT` → caen `test_hints_y_titulos_de_las_nuevas` y el
    invariante «pide token ⇔ destructiva»
    (`test_every_tool_that_asks_for_a_token_says_it_is_destructive`).
    """

    def test_registradas(self):
        mcp = _register_all()
        assert [n for n in _CORE_LOGS if n not in mcp.tools] == []

    def test_con_la_familia_desactivada_no_aparece_ninguna(self):
        mcp = _do_register(["core_diagnostics"])
        assert [n for n in _CORE_LOGS if n in mcp.tools] == []
        assert "ha_list_repairs" in mcp.tools

    def test_reciben_response_max_bytes(self):
        from unittest.mock import patch

        with patch("hermes.tools.core_logs.register") as reg:
            register_all_tools(
                _RecordingMCP(), MagicMock(), fire_event_allowlist=[],
                response_max_bytes=54_321, call_service_auto_classify=False,
                tool_families_disabled=[],
            )
        assert reg.call_args.kwargs.get("response_max_bytes") == 54_321

    def test_ninguna_sale_a_internet(self):
        from hermes.tools._annotations import classify

        assert [n for n in _CORE_LOGS if classify(n).open_world_hint] == []


# ── Spec 012, tramo B: validación, diagnósticos y notificaciones (T026) ─────

_CORE_DIAGNOSTICS_B = (
    "ha_validate_config", "ha_test_condition",
    "ha_list_diagnostics_handlers", "ha_get_config_entry_diagnostics",
    "ha_get_device_diagnostics",
    "ha_list_persistent_notifications", "ha_dismiss_persistent_notification",
)


class TestCoreDiagnosticsTramoBRegistration:
    """Las siete tools del tramo B se registran bajo `core_diagnostics`, con
    los hints del contrato (`_HINTS_NUEVAS_1_2_0`); con la familia
    desactivada no aparece ninguna de las 12.

    Control negativo (T033 f): quitar `ha_validate_config` de
    `_READ_ONLY_EXACT` → cae `test_hints_y_titulos_de_las_nuevas` (y
    `test_validar_y_probar_son_de_lectura`).
    """

    def test_registradas(self):
        mcp = _register_all()
        assert [n for n in _CORE_DIAGNOSTICS_B if n not in mcp.tools] == []

    def test_con_la_familia_desactivada_no_aparece_ninguna_de_las_12(self):
        mcp = _do_register(["core_diagnostics"])
        assert [n for n in _CORE_LOGS + _CORE_DIAGNOSTICS_B if n in mcp.tools] == []
        assert "ha_list_repairs" in mcp.tools

    def test_reciben_response_max_bytes(self):
        from unittest.mock import patch

        for modulo in ("integration_diagnostics", "persistent_notifications"):
            with patch(f"hermes.tools.{modulo}.register") as reg:
                register_all_tools(
                    _RecordingMCP(), MagicMock(), fire_event_allowlist=[],
                    response_max_bytes=54_321, call_service_auto_classify=False,
                    tool_families_disabled=[],
                )
            assert reg.call_args.kwargs.get("response_max_bytes") == 54_321, modulo

    def test_validar_y_probar_son_de_lectura(self):
        from hermes.tools._annotations import classify

        for nombre in ("ha_validate_config", "ha_test_condition"):
            ann = classify(nombre)
            assert ann.read_only_hint and not ann.destructive_hint, nombre
        ann = classify("ha_dismiss_persistent_notification")
        assert ann.destructive_hint and not ann.read_only_hint

    def test_ninguna_sale_a_internet(self):
        from hermes.tools._annotations import classify

        assert [n for n in _CORE_DIAGNOSTICS_B if classify(n).open_world_hint] == []


# ── Spec 017, tramo A: blueprints (T009) ─────────────────────────────────────

_BLUEPRINTS_017 = (
    "ha_list_blueprints", "ha_preview_blueprint_substitution",
    "ha_save_blueprint", "ha_delete_blueprint",
    "ha_import_blueprint",  # tramo B
)


class TestBlueprintsRegistration:
    """Las cuatro tools del tramo A se registran bajo `blueprints`, con los
    hints del contrato (`_HINTS_NUEVAS_1_2_0`); con la familia desactivada no
    aparece ninguna y las de la 1.1.2 siguen igual.

    Control negativo (T016, 6): quitar `ha_save_blueprint` de
    `_DESTRUCTIVE_EXACT` → caen `test_hints_y_titulos_de_las_nuevas` y el
    invariante «pide token ⇔ destructiva»
    (`test_every_tool_that_asks_for_a_token_says_it_is_destructive`).
    `ha_delete_blueprint` no está en esa lista: ya es destructiva por el
    prefijo `ha_delete_` (desviación de T009, que la ponía en las dos).
    """

    def test_registradas(self):
        mcp = _register_all()
        assert [n for n in _BLUEPRINTS_017 if n not in mcp.tools] == []

    def test_con_la_familia_desactivada_no_aparece_ninguna(self):
        mcp = _do_register(["blueprints"])
        assert [n for n in _BLUEPRINTS_017 if n in mcp.tools] == []
        assert "ha_create_or_update_automation" in mcp.tools

    def test_reciben_response_max_bytes(self):
        from unittest.mock import patch

        with patch("hermes.tools.blueprints.register") as reg:
            register_all_tools(
                _RecordingMCP(), MagicMock(), fire_event_allowlist=[],
                response_max_bytes=54_321, call_service_auto_classify=False,
                tool_families_disabled=[],
            )
        assert reg.call_args.kwargs.get("response_max_bytes") == 54_321

    def test_las_que_modifican_piden_token_y_solo_importar_sale_a_internet(self):
        """Spec 017, tramo B (T020): `openWorldHint` verdadero solo en
        `ha_import_blueprint` de entre las de la familia.

        Control negativo (T025, 5): quitar `ha_import_blueprint` de
        `_OPEN_WORLD` → cae este test (y `test_hints_y_titulos_de_las_nuevas`).
        """
        from hermes.tools._annotations import classify

        for nombre in ("ha_save_blueprint", "ha_delete_blueprint", "ha_import_blueprint"):
            ann = classify(nombre)
            assert ann.destructive_hint and not ann.read_only_hint, nombre
        assert classify("ha_preview_blueprint_substitution").read_only_hint
        assert [n for n in _BLUEPRINTS_017 if classify(n).open_world_hint] == [
            "ha_import_blueprint"]


# ── Spec 017, tramo C: automatizaciones de dispositivo y targets (T031) ───────

_AUTOMATION_ASSIST_017 = (
    "ha_list_device_triggers", "ha_list_device_conditions", "ha_list_device_actions",
    "ha_resolve_target", "ha_explain_target", "ha_list_triggers_for_target",
    "ha_list_conditions_for_target", "ha_list_actions_for_target",
)


class TestAutomationAssistRegistration:
    """Las ocho tools del tramo C se registran bajo `automation_assist`, con
    los hints del contrato (`_HINTS_NUEVAS_1_2_0`); con la familia
    desactivada no aparece ninguna y las de la 1.1.2 siguen igual.

    Control negativo comprobado: quitar `ha_resolve_target` de
    `_READ_ONLY_EXACT` → caen `test_las_ocho_solo_leen` y
    `test_hints_y_titulos_de_las_nuevas`.
    """

    def test_registradas(self):
        mcp = _register_all()
        assert [n for n in _AUTOMATION_ASSIST_017 if n not in mcp.tools] == []

    def test_con_la_familia_desactivada_no_aparece_ninguna(self):
        mcp = _do_register(["automation_assist"])
        assert [n for n in _AUTOMATION_ASSIST_017 if n in mcp.tools] == []
        assert "ha_search_related" in mcp.tools
        assert "ha_list_blueprints" in mcp.tools

    def test_reciben_response_max_bytes(self):
        from unittest.mock import patch

        with patch("hermes.tools.device_automation.register") as dispositivo, \
                patch("hermes.tools.targets.register") as targets:
            register_all_tools(
                _RecordingMCP(), MagicMock(), fire_event_allowlist=[],
                response_max_bytes=54_321, call_service_auto_classify=False,
                tool_families_disabled=[],
            )
        assert dispositivo.call_args.kwargs.get("response_max_bytes") == 54_321
        assert targets.call_args.kwargs.get("response_max_bytes") == 54_321

    def test_las_ocho_solo_leen(self):
        from hermes.tools._annotations import classify

        for nombre in _AUTOMATION_ASSIST_017:
            ann = classify(nombre)
            assert ann.read_only_hint and not ann.destructive_hint, nombre
            assert not ann.open_world_hint, nombre


class TestEsperaDeTriggerRegistration:
    """Spec 017, tramo D (T042): `ha_wait_for_trigger` se registra en
    `automation_assist` con el gestor de esperas compartido; solo lee; y,
    como `ha_wait_for_event` desde la 033, `ctx` es el `Context` del SDK y no
    sale en el esquema.

    Control negativo comprobado: anotando `ctx: Any` caen
    `test_esquema_sin_ctx` y `test_ctx_es_el_contexto_inyectado`; quitando
    `ha_wait_for_trigger` de `_READ_ONLY_EXACT` caen `test_solo_lee` y
    `test_hints_y_titulos_de_las_nuevas`.
    """

    def test_registrada_en_su_familia(self):
        assert "ha_wait_for_trigger" in _register_all().tools
        mcp = _do_register(["automation_assist"])
        assert "ha_wait_for_trigger" not in mcp.tools
        assert "ha_wait_for_event" in mcp.tools

    def test_solo_lee(self):
        from hermes.tools._annotations import classify

        ann = classify("ha_wait_for_trigger")
        assert ann.read_only_hint and not ann.destructive_hint
        assert not ann.open_world_hint

    def test_esquema_sin_ctx(self):
        esquema = _real_registry()["ha_wait_for_trigger"].parameters
        assert sorted(esquema["properties"]) == ["timeout_seconds", "trigger", "variables"]
        assert esquema.get("required", []) == ["trigger"]

    def test_ctx_es_el_contexto_inyectado(self):
        assert _real_registry()["ha_wait_for_trigger"].context_kwarg == "ctx"

    def test_gestor_compartido_y_mismo_tope(self):
        from unittest.mock import patch

        with patch("hermes.tools.wait_for_event.register") as evento,                 patch("hermes.tools.wait_for_trigger.register") as trigger:
            register_all_tools(
                _RecordingMCP(), MagicMock(), fire_event_allowlist=[],
                response_max_bytes=54_321, call_service_auto_classify=False,
                wait_for_event_max_seconds=77, wait_for_event_max_concurrent=3,
                tool_families_disabled=[],
            )
        gestor = evento.call_args.kwargs["manager"]
        assert trigger.call_args.kwargs["manager"] is gestor
        assert gestor.max_concurrent == 3
        assert trigger.call_args.kwargs["wait_for_event_max_seconds"] == 77
        assert trigger.call_args.kwargs["response_max_bytes"] == 54_321


# ── Spec 024, tramo 1: cámaras e imágenes (T008) ─────────────────────────────

_CAMERAS_024 = ("ha_get_camera_snapshot", "ha_get_image_entity")


class TestCamerasRegistration:
    """Las dos tools de imagen se registran bajo `cameras`, con los hints del
    contrato (`_HINTS_NUEVAS_1_2_0`), sin `confirmation_token`; con la familia
    desactivada no aparece ninguna y las de la 1.1.2 siguen igual.

    Control negativo comprobado: quitar las dos de `_OPEN_WORLD` → caen
    `test_solo_leen_y_salen_a_internet` y `test_hints_y_titulos_de_las_nuevas`.
    """

    def test_registradas_por_defecto(self):
        mcp = _register_all()
        assert [n for n in _CAMERAS_024 if n not in mcp.tools] == []

    def test_con_la_familia_desactivada_no_aparece_ninguna(self):
        mcp = _do_register(["cameras"])
        assert [n for n in _CAMERAS_024 if n in mcp.tools] == []
        assert "ha_get_state" in mcp.tools

    def test_sin_confirmation_token(self):
        registro = _real_registry()
        for nombre in _CAMERAS_024:
            assert "confirmation_token" not in registro[nombre].parameters["properties"], nombre

    def test_esquemas(self):
        registro = _real_registry()
        assert sorted(registro["ha_get_camera_snapshot"].parameters["properties"]) == [
            "entity_id", "max_width"]
        assert registro["ha_get_camera_snapshot"].parameters.get("required") == ["entity_id"]
        assert sorted(registro["ha_get_image_entity"].parameters["properties"]) == ["entity_id"]

    def test_solo_leen_y_salen_a_internet(self):
        from hermes.tools._annotations import classify

        for nombre in _CAMERAS_024:
            ann = classify(nombre)
            assert ann.read_only_hint and not ann.destructive_hint, nombre
            assert ann.open_world_hint, nombre

    def test_reciben_response_max_bytes(self):
        from unittest.mock import patch

        with patch("hermes.tools.cameras.register") as reg:
            register_all_tools(
                _RecordingMCP(), MagicMock(), fire_event_allowlist=[],
                response_max_bytes=54_321, call_service_auto_classify=False,
                tool_families_disabled=[],
            )
        assert reg.call_args.kwargs.get("response_max_bytes") == 54_321


# ── Spec 005, bloque C: resolución del Supervisor y backups de HA ────────────

_RESOLUCION_Y_BACKUPS_HA = (
    "sv_get_resolution", "sv_dismiss_resolution_issue",
    "sv_dismiss_resolution_suggestion",
    "ha_list_backups", "ha_get_backup", "ha_get_backup_config",
)


class TestResolutionAndHABackupsRegistration:
    def test_registered(self):
        mcp = _register_all()
        faltan = sorted(n for n in _RESOLUCION_Y_BACKUPS_HA if n not in mcp.tools)
        assert faltan == [], f"no registradas: {faltan}"

    def test_read_only(self):
        from hermes.tools._annotations import classify

        for name in ("sv_get_resolution", "ha_list_backups", "ha_get_backup",
                     "ha_get_backup_config"):
            ann = classify(name)
            assert ann.read_only_hint, name
            assert not ann.destructive_hint, name

    def test_dismiss_tools_are_destructive(self):
        """Descartar un issue del Supervisor oculta un aviso que puede ser
        importante: piden token y tienen que anunciarse destructivas."""
        from hermes.tools._annotations import classify

        for name in ("sv_dismiss_resolution_issue",
                     "sv_dismiss_resolution_suggestion"):
            ann = classify(name)
            assert not ann.read_only_hint, name
            assert ann.destructive_hint, name

    def test_none_is_open_world(self):
        from hermes.tools._annotations import classify

        assert [n for n in _RESOLUCION_Y_BACKUPS_HA if classify(n).open_world_hint] == []

    def test_safety_backup_keep_reaches_register_write(self):
        """Sin este cableado la opción no manda: `register_write` usaría su
        valor por defecto aunque el usuario hubiera puesto otro."""
        from unittest.mock import patch

        with patch("hermes.tools.filesystem_write.register_write") as reg:
            register_all_tools(
                _RecordingMCP(), MagicMock(), fire_event_allowlist=[],
                response_max_bytes=131_072, call_service_auto_classify=False,
                safety_backup_keep=7,
            )
        assert reg.call_args.kwargs.get("safety_backup_keep") == 7

    def test_safety_backup_keep_from_config_when_not_given(self):
        from unittest.mock import patch

        with patch.dict(os.environ, {"HERMES_SAFETY_BACKUP_KEEP": "9"}), \
                patch("hermes.tools.filesystem_write.register_write") as reg:
            register_all_tools(
                _RecordingMCP(), MagicMock(), fire_event_allowlist=[],
                response_max_bytes=131_072, call_service_auto_classify=False,
            )
        assert reg.call_args.kwargs.get("safety_backup_keep") == 9


# ── Recuento de tools en la documentación ────────────────────────────────────

class TestToolCountInDocs:
    """El número de tools que anuncian los README y DOCS.md es el del registro
    real, sin las de desarrollo. Se ha quedado atrás en varias versiones
    porque nadie lo recontaba al añadir módulos. Las instrucciones del
    servidor ya no dan ninguno (spec 011, FR-022): depende de las familias
    desactivadas; lo comprueba también `test_tools_guide`."""

    def test_documented_count_matches_registry(self):
        import re

        from hermes.tools.guide import INSTRUCTIONS

        previous = os.environ.pop("HERMES_DEV", None)
        try:
            mcp = _do_register()
        finally:
            if previous is not None:
                os.environ["HERMES_DEV"] = previous
        total = len(mcp.tools)
        raiz = pathlib.Path(__file__).resolve().parents[1]
        assert re.findall(r"(\d{3}) (?:tools|herramientas)\b", INSTRUCTIONS) == []
        textos = {
            "README.md": (raiz / "README.md").read_text(encoding="utf-8"),
            "README.es.md": (raiz / "README.es.md").read_text(encoding="utf-8"),
            "DOCS.md": (raiz / "hermes" / "DOCS.md").read_text(encoding="utf-8"),
        }
        patron = re.compile(r"(\d{3}) (?:tools|herramientas)\b")
        for nombre, texto in textos.items():
            numeros = {int(n) for n in patron.findall(texto)}
            assert numeros == {total}, f"{nombre}: {sorted(numeros)} != {total}"


class TestDocumentoOmitibleEnElEsquema:
    """Spec 007 (FR-006): en las cinco tools con documento grande, el
    documento deja de ser obligatorio en el esquema de entrada MCP (se puede
    omitir al confirmar) y el destino sigue siéndolo. Comprobado sobre el
    registro real, que es lo que ve el cliente.

    Control negativo comprobado: con las firmas de 1.1.1 (documento sin valor
    por defecto) el documento vuelve a `required` y este test cae.
    """

    DOCUMENTO_Y_DESTINO = {
        "ha_save_lovelace_dashboard": ("config", "url_path"),
        "fs_write_file": ("content", "path"),
        "ha_create_or_update_automation": ("config", "automation_id"),
        "ha_create_or_update_script": ("config", "script_id"),
        "ha_create_or_update_scene": ("config", "scene_id"),
    }

    def test_documento_opcional_y_destino_obligatorio(self):
        tools = _real_registry()
        for nombre, (documento, destino) in self.DOCUMENTO_Y_DESTINO.items():
            esquema = tools[nombre].parameters
            requeridos = esquema.get("required", [])
            assert documento in esquema["properties"], nombre
            assert documento not in requeridos, nombre
            assert destino in requeridos, nombre


class TestArgumentosCambiadosAnteLaValidacionDelSdk:
    """Revisión de la 1.1.2: el SDK MCP hace `json.loads` de los argumentos de
    texto cuya anotación no es exactamente `str`. Se comprueba, con la
    validación real del registro, cada argumento que la spec 007 cambió.

    - `content` de `fs_write_file` (`str`): un texto que parece JSON llega
      intacto. Control negativo comprobado: con `str | None` cae.
    - `config` de las otras cuatro (`dict | None`): un objeto mandado como
      texto JSON se convierte en dict, que es lo deseado y lo que ya hacía la
      1.1.1 con `dict`; omitirlo da None.
    """

    def test_content_no_se_preparsea(self):
        meta = _real_registry()["fs_write_file"].fn_metadata
        for contenido in ('{"a": 1}', "[1, 2]", "true", "false", "null", "texto"):
            args = meta.validate_arguments({"path": "f.json", "content": contenido})
            assert args["content"] == contenido, contenido
        assert meta.validate_arguments({"path": "f.json"})["content"] is None

    def test_config_se_sigue_preparseando_como_dict(self):
        tools = _real_registry()
        for nombre, destino in (
            ("ha_save_lovelace_dashboard", "url_path"),
            ("ha_create_or_update_automation", "automation_id"),
            ("ha_create_or_update_script", "script_id"),
            ("ha_create_or_update_scene", "scene_id"),
        ):
            meta = tools[nombre].fn_metadata
            args = meta.validate_arguments({destino: "ficticio", "config": '{"a": 1}'})
            assert args["config"] == {"a": 1}, nombre
            args = meta.validate_arguments({destino: "ficticio", "config": {"a": 1}})
            assert args["config"] == {"a": 1}, nombre
            assert meta.validate_arguments({destino: "ficticio"})["config"] is None, nombre

    def test_view_se_preparsea_como_config(self):
        """Spec 018 (FR-016): `view` de `ha_save_lovelace_dashboard` es
        `dict | None` como `config`: un objeto mandado como texto JSON llega
        como dict y omitido llega None (se puede omitir al confirmar)."""
        meta = _real_registry()["ha_save_lovelace_dashboard"].fn_metadata
        base = {"url_path": "panel-prueba", "view_index": 1}
        args = meta.validate_arguments({**base, "view": '{"title": "Cocina"}'})
        assert args["view"] == {"title": "Cocina"}
        args = meta.validate_arguments({**base, "view": {"title": "Cocina"}})
        assert args["view"] == {"title": "Cocina"}
        args = meta.validate_arguments(base)
        assert args["view"] is None
        assert args["view_index"] == 1
        assert meta.validate_arguments({"url_path": "panel-prueba"})["view_index"] is None

class TestEsperaSinCtxEnElEsquema:
    """Spec 033 (FR-005, T018): `ctx` de `ha_wait_for_event` es el `Context`
    del SDK y no un argumento del cliente. Con `ctx: Any`, el SDK no lo
    reconocía (`find_context_parameter` solo acepta subclases de `Context`),
    lo publicaba como obligatorio y no lo inyectaba (research R-3).

    Comprobado sobre el registro real, con el envoltorio de `requires_ready`
    (`functools.wraps`) en medio: `get_type_hints` sigue `__wrapped__`.

    Control negativo (T020), comprobado y restaurado: volviendo a `ctx: Any`
    caen los dos tests, `test_esquemas_de_la_1_1_2` (`ctx` vuelve al esquema
    y la excepción escrita allí ya no cuadra) y, en
    `tests/test_tools_wait_for_event.py`, `test_sin_ctx_por_el_servidor_real`.
    """

    def test_esquema_sin_ctx(self):
        esquema = _real_registry()["ha_wait_for_event"].parameters
        assert sorted(esquema["properties"]) == ["event_type", "filters", "timeout_seconds"]
        assert esquema.get("required", []) == ["event_type"]

    def test_ctx_es_el_contexto_inyectado(self):
        assert _real_registry()["ha_wait_for_event"].context_kwarg == "ctx"
