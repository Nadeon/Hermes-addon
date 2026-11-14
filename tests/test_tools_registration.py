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


def _do_register() -> _RecordingMCP:
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
    otra queda documentada abajo como excepción deliberada.

    El invariante inverso también se vigila: una herramienta que pide token es,
    por definición, consecuente, y debe declararse como tal. Si no, el cliente
    la trata como inofensiva y solo descubre lo contrario al llamarla.
    """

    # Única excepción admitida, y por qué.
    #
    # `ha_call_service_response` invoca servicios que devuelven datos
    # (`calendar.get_events`, `weather.get_forecasts`…). Va marcada como
    # destructiva porque el servicio lo elige quien llama y hay que asumir lo
    # peor, pero su guarda no es el token: es la denylist, que la rechaza de
    # plano ante cualquier servicio peligroso. Añadirle el token obligaría a dos
    # pasos para leer el tiempo.
    SIN_TOKEN_A_PROPOSITO = {"ha_call_service_response"}

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
        """Si mañana hay dos, que haya que justificar la segunda a mano."""
        assert len(self.SIN_TOKEN_A_PROPOSITO) == 1


# ── title (spec 003, FR-040) e hints intactos (FR-043) ───────────────────────

# Instantánea de los cuatro *hints* de cada tool, tomada con `classify` ANTES
# de añadir `title`. Añadir el título no puede cambiar lo que una tool dice de
# sí misma (principio V): si un día cambia un hint, tiene que ser a propósito y
# actualizando esta tabla en el mismo cambio.
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
    "ha_create_scene_from_current": "----",
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


def _hint_code(ann) -> str:
    flags = (ann.read_only_hint, ann.destructive_hint,
             ann.idempotent_hint, ann.open_world_hint)
    return "".join(c if f else "-" for c, f in zip("RDIO", flags))


def _real_registry() -> dict:
    """Todas las tools registradas en un `MCPServer` real, ya anotadas."""
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
        tools = _real_registry()
        assert set(tools) == set(_HINTS_SNAPSHOT), (
            "la lista de tools no coincide con la instantánea")
        cambiados = sorted(
            f"{n}: {_HINTS_SNAPSHOT[n]} -> {_hint_code(t.annotations)}"
            for n, t in tools.items()
            if _hint_code(t.annotations) != _HINTS_SNAPSHOT[n])
        assert cambiados == [], f"hints cambiados: {cambiados}"


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
    """El número de tools que anuncian las instrucciones, la guía, los README y
    DOCS.md es el del registro real, sin las de desarrollo. Se ha quedado
    atrás en varias versiones porque nadie lo recontaba al añadir módulos."""

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
        textos = {
            "INSTRUCTIONS": INSTRUCTIONS,
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
