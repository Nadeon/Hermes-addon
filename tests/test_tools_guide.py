"""Tests del onboarding del cliente MCP: instructions + tool hermes_guide."""

import unittest

from hermes.tools.guide import INSTRUCTIONS, _GUIDE, register


class _MockMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self, *args, **kwargs):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


class TestHermesGuide(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_no_topic_returns_index(self) -> None:
        out = await self.guide()
        self.assertIn("Guía de Hermes", out)
        self.assertIn("services", out)
        self.assertIn("workflows", out)

    async def test_every_known_topic_has_content(self) -> None:
        for topic in _GUIDE:
            out = await self.guide(topic)
            self.assertGreater(len(out.strip()), 50, f"topic {topic} vacío")

    async def test_aliases_resolve_to_canonical(self) -> None:
        self.assertEqual(await self.guide("addons"), _GUIDE["supervisor"])
        self.assertEqual(await self.guide("files"), _GUIDE["filesystem"])
        self.assertEqual(await self.guide("dashboards"), _GUIDE["lovelace"])
        self.assertEqual(await self.guide("recetas"), _GUIDE["workflows"])

    async def test_workflows_topic_has_step_by_step(self) -> None:
        out = await self.guide("workflows")
        self.assertIn("CREAR UNA AUTOMATIZACIÓN", out)
        self.assertIn("CAMBIO SEGURO EN /config", out)

    async def test_topic_is_case_insensitive(self) -> None:
        self.assertEqual(await self.guide("BACKUPS"), _GUIDE["backups"])

    async def test_unknown_topic_returns_index_with_hint(self) -> None:
        out = await self.guide("nope-xyz")
        self.assertIn("no reconocido", out)
        self.assertIn("services", out)


class TestGuiaAlDia(unittest.TestCase):
    """Regresión FR-042 (C4): la guía es lo que el modelo copia al pie de la
    letra, así que tiene que enseñar lo que HA espera hoy."""

    def test_automatizaciones_sin_sintaxis_heredada(self) -> None:
        # `platform:` dentro de un trigger y `service:` en una acción son la
        # sintaxis anterior a HA 2024.8/2024.10; HA la sigue aceptando, pero
        # el editor y la documentación ya solo usan `trigger:` y `action:`.
        guia = _GUIDE["automations"]
        self.assertNotIn('"platform":', guia)
        self.assertNotIn('"service":', guia)
        self.assertIn('"triggers":', guia)
        self.assertIn('"actions":', guia)

    def test_registros_mencionan_ha_remove_device(self) -> None:
        guia = _GUIDE["registries"]
        self.assertIn("ha_remove_device`", guia)
        # La antigua sigue registrada, pero solo como deprecada: desde HA
        # 2026.9 borra el dispositivo entero.
        self.assertIn("ha_remove_device_from_config_entry", guia)
        self.assertIn("deprecada", guia)

    def test_servicios_recomienda_filtrar_por_dominio(self) -> None:
        # Sin filtro, la lista de servicios de una casa grande supera el
        # límite de respuesta del cliente (problema 14 de la hoja de ruta).
        self.assertIn("ha_list_services(domain=", _GUIDE["services"])


class TestGuiaMarketplace(unittest.IsolatedAsyncioTestCase):
    """Spec 004, FR-028: desde HA 2026.11 HACS es el Marketplace. El modelo
    tiene que saber qué tools hay, que Hermes no instala nada desde ahí y
    cómo se actualiza (entidad `update` con token)."""

    _TOOLS = (
        "ha_marketplace_info", "ha_marketplace_list_repositories",
        "ha_marketplace_get_repository", "ha_marketplace_list_updates",
        "ha_marketplace_list_releases", "ha_marketplace_list_critical",
        "ha_marketplace_list_removed",
    )

    def setUp(self) -> None:
        mcp = _MockMCP()
        register(mcp)
        self.guide = mcp.tools["hermes_guide"]

    async def test_marketplace_topic_and_hacs_alias(self) -> None:
        tema = await self.guide("marketplace")
        self.assertEqual(await self.guide("hacs"), tema)
        for nombre in self._TOOLS:
            self.assertIn(nombre, tema)
        self.assertIn("update.install", tema)
        self.assertIn("confirmation_token", tema)
        # El aviso de riesgos lo acepta una persona, por usuario de HA.
        self.assertIn("aviso", tema)
        self.assertIn("usuario", tema)
        # Nombres y descripciones los escriben terceros.
        self.assertIn("terceros", tema)

    async def test_retirados_con_filtros_y_resumen(self) -> None:
        """009 (FR-007, FR-013): la guía dice cómo acotar los retirados; sin
        esto el modelo pedía la lista entera (~500 entradas) para buscar lo
        suyo."""
        tema = await self.guide("marketplace")
        linea = tema[tema.index("ha_marketplace_list_removed"):]
        for texto in ("installed_only", "limit", "by_removal_type"):
            self.assertIn(texto, linea)

    async def test_index_mentions_marketplace(self) -> None:
        self.assertIn("marketplace", await self.guide())
        self.assertIn("marketplace", INSTRUCTIONS)


class TestGuiaDiagnosticoYOrganizacion(unittest.IsolatedAsyncioTestCase):
    """Spec 005, FR-041: plantas, etiquetas y categorías en `registries`, y un
    tema `diagnostics` para Repairs, trazas y relaciones."""

    def setUp(self) -> None:
        mcp = _MockMCP()
        register(mcp)
        self.guide = mcp.tools["hermes_guide"]

    async def test_diagnostics_topic_and_aliases(self) -> None:
        tema = await self.guide("diagnostics")
        for alias in ("repairs", "traces"):
            self.assertEqual(await self.guide(alias), tema, alias)
        for nombre in ("ha_list_repairs", "ha_ignore_repair", "ha_list_traces",
                       "ha_get_trace", "ha_search_related"):
            self.assertIn(nombre, tema)
        self.assertIn("diagnostics", await self.guide())

    def test_registries_name_floors_labels_and_categories(self) -> None:
        guia = _GUIDE["registries"]
        for nombre in ("ha_list_floors", "ha_update_floor", "ha_delete_floor",
                       "ha_list_labels", "ha_delete_label",
                       "ha_list_categories", "ha_delete_category"):
            self.assertIn(nombre, guia)

    async def test_diagnostics_covers_the_supervisor_resolution(self) -> None:
        tema = await self.guide("diagnostics")
        self.assertEqual(await self.guide("resolution"), tema)
        for nombre in ("sv_get_resolution", "sv_dismiss_resolution_issue",
                       "sv_dismiss_resolution_suggestion"):
            self.assertIn(nombre, tema)

    def test_backups_names_ha_backups_and_retention(self) -> None:
        guia = _GUIDE["backups"]
        for nombre in ("ha_list_backups", "ha_get_backup",
                       "ha_get_backup_config", "safety_backup_keep"):
            self.assertIn(nombre, guia)


class TestInstructions(unittest.TestCase):
    def test_instructions_mention_key_concepts(self) -> None:
        self.assertGreater(len(INSTRUCTIONS), 200)
        self.assertIn("confirmation_token", INSTRUCTIONS)
        self.assertIn("hermes_guide", INSTRUCTIONS)
        self.assertIn("ha_get_states", INSTRUCTIONS)

    def test_instructions_sin_recuento_de_tools(self) -> None:
        """Spec 011 (FR-022, principio V): el número de tools depende de las
        familias desactivadas y de la versión, así que las instrucciones no lo
        dan; un «~216» sería falso con las genéricas o con una familia
        apagada. Sí mencionan las genéricas y que dependen de la tabla.

        Control negativo comprobado: con las INSTRUCTIONS de la 1.1.2 («~216
        tools») cae.
        """
        import re

        self.assertIsNone(
            re.search(r"\d+\s*(?:tools|herramientas)\b", INSTRUCTIONS),
            "INSTRUCTIONS no debe dar un recuento de tools",
        )
        for nombre in ("ha_read_ws_command", "ha_call_ws_command",
                       "sv_read_api", "sv_call_api"):
            self.assertIn(nombre, INSTRUCTIONS)
        self.assertIn("tabla", INSTRUCTIONS)

    def test_instrucciones_sin_la_familia_generic_commands(self) -> None:
        """T049: sin la familia, ni el párrafo de las genéricas ni su tema
        en la lista; el resto, idéntico. Control negativo comprobado: con
        `activas` siempre verdadero en `instrucciones` → cae."""
        from hermes.tools.guide import instrucciones

        sin = instrucciones(frozenset({"generic_commands"}))
        for nombre in ("ha_read_ws_command", "ha_call_ws_command",
                       "sv_read_api", "sv_call_api", "generic_commands"):
            self.assertNotIn(nombre, sin)
        self.assertIn("security) y", sin)
        self.assertEqual(instrucciones(), INSTRUCTIONS)
        self.assertEqual(instrucciones(frozenset({"lovelace"})), INSTRUCTIONS)
        self.assertNotIn("@", INSTRUCTIONS)

    def test_instructions_accepted_and_exposed_by_fastmcp(self) -> None:
        # Verifica end-to-end que el SDK entrega instructions en el initialize.
        from mcp.server.mcpserver import MCPServer

        server = MCPServer("test", instructions=INSTRUCTIONS)
        self.assertEqual(server.instructions, INSTRUCTIONS)


class TestGuiaConfirmarSinDocumento(unittest.TestCase):
    """Spec 007 (FR-008): las instrucciones y la guía ya no piden repetir «los
    MISMOS argumentos». Si lo siguieran pidiendo, el agente reenviaría el
    documento grande y la confirmación volvería a caducar antes de llegar.

    Control negativo comprobado: con `guide.py` de 1.1.1 cae este test.
    """

    def test_ya_no_piden_repetir_los_mismos_argumentos(self) -> None:
        textos = {"INSTRUCTIONS": INSTRUCTIONS, **{t: _GUIDE[t] for t in
                  ("security", "filesystem", "workflows")}}
        for nombre, texto in textos.items():
            with self.subTest(texto=nombre):
                self.assertNotIn("MISMOS argumentos", texto)
                self.assertNotIn("mismos argumentos", texto)

    def test_explican_la_omision(self) -> None:
        for nombre, texto in (("INSTRUCTIONS", INSTRUCTIONS), ("security", _GUIDE["security"])):
            with self.subTest(texto=nombre):
                self.assertIn("omit_on_confirm", texto)
                self.assertIn("confirm_with", texto)
                self.assertIn("idéntico", texto)
        self.assertIn("omit_on_confirm", _GUIDE["filesystem"])
        self.assertIn("sin reenviar", _GUIDE["workflows"])

    def test_la_omision_depende_de_omit_on_confirm(self) -> None:
        """Revisión de la 1.1.2: con el tope lleno el token se emite sin
        documento, así que la guía no puede decir sin condición que ya está
        guardado. Cada sitio que habla de omitir lo condiciona a
        `omit_on_confirm` y dice que, si no, se reenvía todo.

        Control negativo comprobado: con el texto incondicional anterior cae.
        """
        self.assertNotIn("ya está guardado", _GUIDE["filesystem"])
        for nombre in ("filesystem", "workflows"):
            with self.subTest(texto=nombre):
                texto = _GUIDE[nombre]
                self.assertIn("omit_on_confirm", texto)
                self.assertIn("reenvía", texto)
                # Cada mención de omitir/sin reenviar va con su condición.
                for parrafo in texto.split("\n\n"):
                    plano = " ".join(parrafo.split())
                    if "sin reenviar" in plano or "omite `" in plano:
                        self.assertIn("trae `omit_on_confirm`", plano)



# ── Spec 011: tema `generic_commands` y búsqueda en la tabla (T035) ───────────

def _entrada(category: str, **kw):
    from hermes.command_policy import Entrada

    kw.setdefault("reason", f"motivo {category}")
    kw.setdefault("family", "generic_commands")
    if category == "dedicated":
        kw.setdefault("tool", "ha_get_demo")
    return Entrada(category=category, **kw)


def _tools_de_la_familia(familia: str) -> set[str]:
    """Tools declaradas (AST) en los módulos de una familia."""
    import ast
    import pathlib

    from hermes.tool_families import FAMILIAS

    carpeta = pathlib.Path(__file__).resolve().parents[1] / "hermes" / "src" / "hermes" / "tools"
    nombres: set[str] = set()
    for modulo in FAMILIAS[familia].modulos:
        arbol = ast.parse((carpeta / f"{modulo}.py").read_text(encoding="utf-8"))
        for n in ast.walk(arbol):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool"
                for d in n.decorator_list
            ):
                nombres.add(n.name)
    return nombres


def _tools_nombradas(texto: str) -> set[str]:
    """Nombres concretos de tools en un texto (sin los patrones `ha_list_*`)."""
    import re

    return set(re.findall(r"(?<![\w])((?:ha|sv|fs)_[a-z0-9_]*[a-z0-9])(?![\w*/])", texto))


class TestTemaIntegrationFlows(unittest.IsolatedAsyncioTestCase):
    """Spec 016 (T011; FR-016, FR-020): tema de la familia `integration_flows`
    y la sección de helpers por config entry.

    `test_cada_tool_de_la_familia_nombrada` es genérico: el tramo B, que añade
    `config_subentries` a la familia, no tiene que tocarlo (cae si una tool
    suya no sale en el tema). Control negativo comprobado: quitar
    `ha_ignore_discovery` del tema → cae nombrándola.
    """

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_y_alias(self) -> None:
        texto = await self.guide("integration_flows")
        self.assertIs(texto, _GUIDE["integration_flows"])
        for alias in ("discovery", "discovered", "DISCOVERY",
                      "subentries", "subentry", "reconfigure"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)
        for palabra in ("ha_continue_config_entry_flow", "ignorable", "ha_delete_config_entry",
                        "pref_disable_polling", "pref_disable_new_entities",
                        "homeassistant.update_entity", "OAuth",
                        "supported_subentry_types", "use_dedicated_tool",
                        "reconfigure_successful"):
            self.assertIn(palabra, texto)

    def test_reconfigure_con_token_en_cada_paso(self) -> None:
        # Decisión del supervisor (tramo B): el tema no puede dejar creer que
        # un reconfigure se sigue con la tool general ni que va sin token.
        texto = _GUIDE["integration_flows"]
        self.assertIn("token en cada paso", _GUIDE["config_entries"])
        self.assertIn("ha_continue_reconfigure_flow", _GUIDE["config_entries"])
        self.assertIn("CADA paso", texto)
        self.assertIn("rechaza estos flujos", texto)

    def test_convergencia_t046_t048(self) -> None:
        # T046: ignorar no es inocuo y solo vale para descubrimientos.
        # T048: un flujo desconocido no se envía. Control negativo comprobado:
        # con los textos de antes («no toca nada en marcha», «se envía como
        # cualquier otro», «pasaría por … sin token») cae este test.
        texto = _GUIDE["integration_flows"]
        self.assertNotIn("no toca nada en marcha", texto)
        self.assertIn("not_a_discovery", texto)
        self.assertIn("unknown_flow", texto)
        self.assertIn("unknown_flow", _GUIDE["config_entries"])
        self.assertNotIn("se envía como cualquier otro", texto)
        self.assertNotIn("token si se conociera", texto)

    async def test_cada_tool_de_la_familia_nombrada(self) -> None:
        tools = _tools_de_la_familia("integration_flows")
        self.assertTrue(tools)
        faltan = sorted(t for t in tools if t not in _GUIDE["integration_flows"])
        self.assertEqual(faltan, [], f"tools de la familia sin nombrar en el tema: {faltan}")

    async def test_el_indice_lo_lista(self) -> None:
        self.assertIn("`integration_flows`", await self.guide())

    def test_config_entries_remite_al_tema(self) -> None:
        self.assertIn('hermes_guide("integration_flows")', _GUIDE["config_entries"])

    def test_helpers_por_config_entry(self) -> None:
        texto = _GUIDE["helpers"]
        self.assertIn("HELPERS POR CONFIG ENTRY", texto)
        for nombre in ('ha_list_config_flow_domains(type="helper")',
                       'ha_start_config_entry_flow("template")',
                       "ha_continue_config_entry_flow", "next_step_id",
                       'ha_list_config_entries(type_filter="helper")',
                       "ha_start_options_flow", "ha_continue_options_flow",
                       "ha_delete_config_entry"):
            self.assertIn(nombre, texto)
        # Qué hacer con la familia desactivada.
        self.assertIn("desactivada", texto)

    def test_no_nombra_tools_que_no_existen(self) -> None:
        from tests.test_tools_registration import _declared_tool_names

        existentes = _declared_tool_names()
        for tema in ("integration_flows", "helpers"):
            with self.subTest(tema=tema):
                inventadas = sorted(_tools_nombradas(_GUIDE[tema]) - existentes)
                self.assertEqual(inventadas, [])


class TestTemaRepairFlows(unittest.IsolatedAsyncioTestCase):
    """Spec 016, tramo C (T041; FR-020): tema de la familia `repair_flows`,
    remisión desde `diagnostics` y la reautenticación con token (decisión
    del supervisor) en `integration_flows`."""

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_y_alias(self) -> None:
        texto = await self.guide("repair_flows")
        self.assertIs(texto, _GUIDE["repair_flows"])
        for alias in ("repair_fix", "fix", "FIX"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)
        for palabra in ("CADA paso", "finished_on_start", "flow_mismatch",
                        "issue_still_present", "is_fixable",
                        "arreglar un aviso de Repairs", "external"):
            self.assertIn(palabra, texto)

    async def test_cada_tool_de_la_familia_nombrada(self) -> None:
        tools = _tools_de_la_familia("repair_flows")
        self.assertEqual(len(tools), 4)
        faltan = sorted(t for t in tools if t not in _GUIDE["repair_flows"])
        self.assertEqual(faltan, [], f"tools de la familia sin nombrar en el tema: {faltan}")

    async def test_el_indice_lo_lista(self) -> None:
        self.assertIn("`repair_flows`", await self.guide())

    def test_diagnostics_remite_y_menciona_los_textos(self) -> None:
        texto = _GUIDE["diagnostics"]
        self.assertIn('hermes_guide("repair_flows")', texto)
        self.assertIn("`title`", texto)
        self.assertIn("`description`", texto)

    def test_reauth_con_token_y_limite_del_reconfigure(self) -> None:
        texto = _GUIDE["integration_flows"]
        self.assertIn("REAUTENTICACIÓN", texto)
        self.assertIn('`source: "reauth"`', texto)
        # T048: el límite del reconfigure tras reiniciar está cerrado; la
        # guía dice que no se puede continuar por ninguna vía.
        self.assertIn("Tras reiniciar Hermes no se reconoce un reconfigure", texto)
        self.assertIn("reauth", _GUIDE["config_entries"])

    def test_no_nombra_tools_que_no_existen(self) -> None:
        from tests.test_tools_registration import _declared_tool_names

        existentes = _declared_tool_names()
        for tema in ("repair_flows", "diagnostics", "integration_flows", "config_entries"):
            with self.subTest(tema=tema):
                self.assertEqual(sorted(_tools_nombradas(_GUIDE[tema]) - existentes), [])


class TestTemaGenericCommands(unittest.IsolatedAsyncioTestCase):
    """FR-022: el tema explica las genéricas y `search` consulta la tabla real.

    Controles negativos (T042 d): inventar un ejemplo cuando la entrada no lo
    tiene (p. ej. `{}`) → cae `test_sin_ejemplo_no_se_inventa`; sin el tope
    de 50 filas → cae `test_mas_de_50_resultados`.
    """

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_con_contenido_y_alias(self) -> None:
        texto = await self.guide("generic_commands")
        self.assertIs(texto, _GUIDE["generic_commands"])
        for palabra in ("ha_read_ws_command", "ha_call_ws_command", "sv_read_api",
                        "sv_call_api", "dedicated", "read", "confirm", "deny",
                        "command_not_classified", "use_dedicated_tool",
                        "wrong_generic_tool", "family_disabled", "path_not_allowed",
                        "confirmation_token", "search="):
            self.assertIn(palabra, texto)
        for alias in ("commands", "generic", "ws", "api", "table", "GENERIC"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)

    async def test_el_indice_lo_menciona(self) -> None:
        self.assertIn("generic_commands", await self.guide())
        self.assertIn("generic_commands", INSTRUCTIONS)

    async def test_search_tag_lista_la_tabla_real(self) -> None:
        texto = await self.guide("generic_commands", search="tag")
        for fila in ("| `tag/list` | read |", "| `tag/create` | confirm |",
                     "| `tag/delete` | confirm |", "| `tag/subscribe` | deny |"):
            self.assertIn(fila, texto)
        # Una dedicada muestra su tool; una `deny`, su motivo.
        texto = await self.guide("generic_commands", search="lovelace/config/save")
        self.assertIn("ha_save_lovelace_dashboard", texto)
        self.assertIn("dedicated", texto)

    async def test_search_en_el_supervisor_y_por_cap(self) -> None:
        texto = await self.guide("generic_commands", search="/supervisor/info")
        self.assertIn("`GET /supervisor/info`", texto)
        texto = await self.guide("generic_commands", search="cap-066")
        self.assertIn("`tag/create`", texto)

    async def test_ejemplo_de_la_tabla(self) -> None:
        texto = await self.guide("generic_commands", search="tag/create")
        self.assertIn('`{"tag_id": "tag-ficticio-3"', texto)

    async def test_sin_ejemplo_no_se_inventa(self) -> None:
        from hermes.tools.guide import buscar_en_tabla

        tabla = {"demo/list": _entrada("read"),
                 "demo/create": _entrada("confirm", example={"name": "Demo"})}
        texto = buscar_en_tabla("demo", tabla_core=tabla, tabla_supervisor={})
        self.assertIn("| `demo/list` | read | motivo read | — |", texto)
        self.assertIn('| `demo/create` | confirm | motivo confirm | `{"name": "Demo"}` |', texto)

    async def test_sin_resultados(self) -> None:
        texto = await self.guide("generic_commands", search="no-existe-xyz")
        self.assertIn("no-existe-xyz", texto)
        self.assertIn("No entry", texto)
        self.assertIn("search=", texto)

    async def test_mas_de_50_resultados(self) -> None:
        from hermes.tools.guide import buscar_en_tabla

        tabla = {f"demo/cmd{i:02d}": _entrada("read") for i in range(60)}
        texto = buscar_en_tabla("demo", tabla_core=tabla, tabla_supervisor={})
        filas = [linea for linea in texto.splitlines() if linea.startswith("| `demo/")]
        self.assertEqual(len(filas), 50)
        self.assertIn("10 more: refine the search", texto)

    async def test_barra_vertical_en_un_motivo_no_rompe_la_tabla(self) -> None:
        from hermes.tools.guide import buscar_en_tabla

        tabla = {"demo/x": _entrada("deny", reason="a | b")}
        texto = buscar_en_tabla("demo", tabla_core=tabla, tabla_supervisor={})
        self.assertIn(r"a \| b", texto)

    async def test_search_con_otro_tema_se_ignora_y_lo_dice(self) -> None:
        texto = await self.guide("backups", search="tag")
        self.assertTrue(texto.startswith(_GUIDE["backups"]))
        self.assertIn("search", texto)
        self.assertIn("generic_commands", texto)
        self.assertNotIn("`tag/list`", texto)
        texto = await self.guide(None, search="tag")
        self.assertIn("Guía de Hermes", texto)
        self.assertNotIn("`tag/list`", texto)

    async def test_sin_search_los_temas_de_la_1_1_2_no_cambian(self) -> None:
        for tema, texto in _GUIDE.items():
            if tema in ("overview", "generic_commands"):
                continue
            with self.subTest(tema=tema):
                self.assertEqual(await self.guide(tema), texto)
                self.assertEqual(await self.guide(tema, search=None), texto)


class TestTemaSystemDiagnostics(unittest.IsolatedAsyncioTestCase):
    """Spec 013, FR-023: tema `system_diagnostics` con las tools de logs,
    `boot`/`latest` y cómo encontrar un arranque o un identificador; el tema
    `supervisor` remite a él; los demás temas no cambian."""

    # sha256 (16 primeros hex) de cada tema ANTES de la 013. Una sub-feature
    # que cambie un tema a propósito actualiza aquí su huella y lo dice en su
    # CHANGELOG; un cambio accidental cae aquí.
    _HUELLAS_ANTES_DE_LA_013 = {
        # La 033 cambia `automations` (el token de una restringida ata
        # `variables`; escenas temporales), `config_entries`
        # (`ha_get_config_entry_options` da
        # `not_supported`) y `helpers` (counters); su CHANGELOG lo dice.
        "automations": "7792fa788da1e1cc",
        # La 027 cambia `backups` (`success` y `child_errors` de los jobs) y la
        # 019 (tramo 2) también (`location` en sv_create_backup_*); sus
        # CHANGELOG lo dicen. Huella recalculada al integrar la 019.
        "backups": "284e226b8aaf6fed",
        # La 016 cambia `config_entries` (remite a `integration_flows`; el
        # reconfigure va por su tool y el `reauth` pide token), `diagnostics`
        # (textos de los avisos y remite a `repair_flows`) y `helpers`
        # («Helpers por config entry», CAP-037); su CHANGELOG lo dice. Huellas
        # recalculadas al integrarla sobre las de la 033, la 027 y la 012.
        "config_entries": "c5acb413e7fedf5a",
        "data": "c77e3e6782cc89a7",
        # La 012 cambia `diagnostics` (remite a `core_diagnostics`); su
        # CHANGELOG lo dice.
        "diagnostics": "b0fdb0a20718d45d",
        "events": "3765a76095ece40f",
        "filesystem": "b5902d6d0ff666c1",
        "generic_commands": "906066a916e93727",
        "helpers": "c99850e94eb5c996",
        # La 018 cambia `lovelace` (guardado por vista) y `services`
        # (`ha_call_service_response` con token); su CHANGELOG lo dice.
        "lovelace": "38d00048b136b460",
        "marketplace": "f83ec233a87ad95b",
        "registries": "42894b4111cb8c80",
        "security": "157ee929e7db08ae",
        "services": "e7b494a2e8ad587e",
        "workflows": "53b81454a6708b9a",
    }

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_con_las_tools_y_alias(self) -> None:
        texto = await self.guide("system_diagnostics")
        self.assertIs(texto, _GUIDE["system_diagnostics"])
        for palabra in ("sv_get_core_logs", "sv_get_supervisor_logs",
                        "sv_get_plugin_logs", "sv_get_host_logs",
                        "sv_list_host_log_identifiers", "sv_list_boots",
                        "sv_get_addon_logs", "boot", "latest", "identifier",
                        "-1", "dns", "audio", "multicast"):
            self.assertIn(palabra, texto)
        for alias in ("system_logs", "supervisor_logs", "host_logs", "boots",
                      "SYSTEM_LOGS"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)
        # `logs` no es alias: chocaría con el log de Core de la spec 012.
        self.assertNotEqual(await self.guide("logs"), texto)

    async def test_indice_e_instrucciones_lo_nombran(self) -> None:
        from hermes.tools.guide import instrucciones

        self.assertIn("system_diagnostics", await self.guide())
        self.assertIn("system_diagnostics", INSTRUCTIONS)
        # Sin la familia, las instrucciones no anuncian su tema (principio V).
        self.assertNotIn("system_diagnostics",
                         instrucciones(frozenset({"system_diagnostics"})))

    async def test_supervisor_menciona_boot_y_latest(self) -> None:
        texto = _GUIDE["supervisor"]
        self.assertIn("boot", texto)
        self.assertIn("latest", texto)
        self.assertIn("system_diagnostics", texto)

    async def test_disco_host_y_os(self) -> None:
        """Tramo 2 (T025): las once tools, la poda, Home Assistant OS y las
        rutas de diagnóstico que se leen con `sv_read_api`."""
        texto = _GUIDE["system_diagnostics"]
        for palabra in ("sv_list_host_services", "sv_get_disk_usage",
                        "sv_get_os_info", "sv_get_swap",
                        "sv_list_datadisk_candidates", "max_depth", "20",
                        "children_omitted", "omitted_bytes", "Home Assistant OS",
                        "sv_read_api", "/jobs/info",
                        "/resolution/issue/{issue}/suggestions", "/host/disks",
                        "/hardware/info", "/security/info", "/docker/info",
                        "/time/info", "/network/info", "/security/integrity"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)
        # T032: los niveles que da cada `max_depth`, que en un montaje son
        # uno menos (el Supervisor convierte < 2 en 0). Control negativo:
        # volver al texto anterior («`max_depth` de 0 a 3.») → cae.
        for frase in ("montaje: 0 y 1 dan solo los totales",
                      "0 y 1 dan solo ese nivel",
                      "(en un montaje, 2)", "`truncated: true`"):
            with self.subTest(frase=frase):
                self.assertIn(frase, texto)
        for alias in ("disk", "storage", "os", "jobs", "DISK"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)
        # `host` sigue llevando al tema `supervisor`, como en la 1.1.2.
        self.assertEqual(await self.guide("host"), _GUIDE["supervisor"])

    async def test_jobs_en_la_tabla(self) -> None:
        texto = await self.guide("generic_commands", search="jobs")
        linea = next(l for l in texto.splitlines() if "/jobs/info" in l)
        self.assertIn("read", linea)

    def test_los_demas_temas_no_cambian(self) -> None:
        import hashlib

        for tema, huella in self._HUELLAS_ANTES_DE_LA_013.items():
            with self.subTest(tema=tema):
                real = hashlib.sha256(_GUIDE[tema].encode()).hexdigest()[:16]
                self.assertEqual(real, huella)


class TestGuiaGuardadoPorVista(unittest.TestCase):
    """Spec 018 (FR-007, FR-016): la guía y las instrucciones explican el
    guardado de una sola vista; si siguieran diciendo solo que
    `ha_save_lovelace_dashboard` reemplaza el dashboard entero, el cliente
    seguiría reescribiendo dashboards grandes (y perdiendo tarjetas).

    Control negativo comprobado: con `guide.py` anterior a la 018 caen los dos.
    """

    def test_tema_lovelace(self) -> None:
        texto = _GUIDE["lovelace"]
        self.assertIn("view_index", texto)
        self.assertIn("dashboard_changed", texto)
        self.assertIn("omit_on_confirm", texto)

    def test_instrucciones_mencionan_una_sola_vista(self) -> None:
        self.assertIn("view_index", INSTRUCTIONS)
        self.assertIn("una sola vista", INSTRUCTIONS)



class TestGuiaRespuestaConfirmadaYListas(unittest.IsolatedAsyncioTestCase):
    """Spec 018 (FR-011, FR-013): el índice describe el sobre común de las
    listas nuevas, y el tema `services` dice que `ha_call_service_response`
    confirma la denylist con token. Si la guía siguiera diciendo que no la
    admite, el cliente no intentaría el segundo paso (principio V).

    Control negativo comprobado: con `guide.py` anterior al tramo 2 de la 018
    caen los tres.
    """

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_indice_describe_el_sobre(self) -> None:
        texto = await self.guide()
        for palabra in ('"count"', '"items"', '"truncated"', "_response_limit", "1.2.0"):
            self.assertIn(palabra, texto)
        self.assertIn("conservan su forma", texto)

    def test_tema_services(self) -> None:
        texto = _GUIDE["services"]
        # La viñeta de `ha_call_service_response` (hasta la línea en blanco),
        # no el tema entero: «confirmation_token» ya salía en otra línea.
        ini = texto.index("- `ha_call_service_response(")
        fin = texto.find("\n\n", ini)
        vineta = texto[ini:fin]
        for palabra in ("confirmation_token", "denylist", "conversation.process"):
            self.assertIn(palabra, vineta)

    def test_nadie_dice_ya_que_no_la_admite(self) -> None:
        for nombre, texto in [("INSTRUCTIONS", INSTRUCTIONS), *_GUIDE.items()]:
            with self.subTest(texto=nombre):
                self.assertNotIn("No admite servicios de la denylist", texto)
                self.assertNotIn("no admite servicios de la denylist", texto)


class TestTemaSystemStatus(unittest.IsolatedAsyncioTestCase):
    """Spec 029, T015 (FR-021): el tema `system_status` nombra las cinco
    tools, dice que no modifican, cómo leer la salud con pendientes y que
    para reiniciar está `sv_restart_core`; sus alias resuelven a él y el
    índice lo menciona."""

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_con_contenido(self) -> None:
        texto = await self.guide("system_status")
        self.assertIs(texto, _GUIDE["system_status"])
        for palabra in ("ha_get_system_health", "ha_get_system_state",
                        "ha_list_integration_setup_times",
                        "ha_list_integration_manifests", "ha_get_integration_manifest",
                        "SOLO LECTURA", "pending", "complete", "failed",
                        "omitted_domains", "timeout_seconds", "sv_restart_core",
                        "_third_party_text", "system_health_not_loaded",
                        "unsupported_by_ha_version"):
            self.assertIn(palabra, texto)

    async def test_alias(self) -> None:
        texto = await self.guide("system_status")
        for alias in ("health", "system_health", "system_state", "manifest",
                      "manifests", "setup_times", "urls", "HEALTH"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)
        # Los alias de la 1.1.2 no cambian (`system` sigue en `supervisor`).
        self.assertEqual(await self.guide("system"), _GUIDE["supervisor"])
        self.assertEqual(await self.guide("statistics"), _GUIDE["data"])

    async def test_el_indice_lo_menciona(self) -> None:
        self.assertIn("`system_status`", await self.guide())

    async def test_red_urls_y_http(self) -> None:
        """Spec 029, T028 (FR-014): la llamada exacta por la genérica a
        `network`, `network/url` y `http/config`, y que Hermes aún no tiene
        tool para cambiarlos (la 021, CAP-069, actualizará este texto)."""
        texto = _GUIDE["system_status"]
        for palabra in ('ha_read_ws_command(type="network")',
                        'ha_read_ws_command(type="network/url")',
                        'ha_read_ws_command(type="http/config")',
                        "internal", "external", "cloud", "stable", "pending",
                        "NO tiene tool", "CAP-069"):
            self.assertIn(palabra, texto)
        self.assertEqual(await self.guide("network"), texto)


class TestTemaRecorder(unittest.IsolatedAsyncioTestCase):
    """Spec 029, T028 (FR-014, FR-021): el tema `recorder` nombra las tres
    tools y la auditoría por `ha_read_ws_command`; sus alias resuelven a él,
    el índice lo menciona, la búsqueda en la tabla enseña el ejemplo de
    `logbook/get_action_calls` y `statistics` sigue en `data`."""

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_con_contenido(self) -> None:
        texto = await self.guide("recorder")
        self.assertIs(texto, _GUIDE["recorder"])
        for palabra in ("ha_get_recorder_info", "ha_validate_statistics",
                        "ha_get_statistics_metadata", "SOLO LECTURA",
                        'ha_read_ws_command(type="logbook/get_action_calls"',
                        "start_time", "end_time", "code", "tapados", "missing",
                        "by_type", "not_found", "recorder_not_loaded",
                        "Repairs", "ha_list_statistic_ids",
                        "ha_statistics_during_period"):
            self.assertIn(palabra, texto)

    async def test_alias(self) -> None:
        texto = await self.guide("recorder")
        for alias in ("recorder_info", "statistics_validation", "action_calls",
                      "audit", "AUDIT"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)
        # Los de la 1.1.2 no cambian.
        self.assertEqual(await self.guide("statistics"), _GUIDE["data"])
        self.assertEqual(await self.guide("logbook"), _GUIDE["data"])
        self.assertEqual(await self.guide("history"), _GUIDE["data"])

    async def test_el_indice_lo_menciona(self) -> None:
        self.assertIn("`recorder`", await self.guide())

    async def test_la_busqueda_enseña_el_ejemplo(self) -> None:
        texto = await self.guide("generic_commands", search="action_calls")
        self.assertIn("logbook/get_action_calls", texto)
        self.assertIn('"start_time": "2026-01-01T00:00:00+00:00"', texto)
        self.assertIn('"end_time": "2026-01-01T06:00:00+00:00"', texto)


class TestTemaCoreDiagnostics(unittest.IsolatedAsyncioTestCase):
    """Spec 012 (FR-016, T014): el tema `core_diagnostics` existe con sus
    alias, el índice lo lista, `diagnostics` remite a él y nombra TODAS las
    tools registradas de la familia `core_diagnostics` (genérico: el tramo B
    no tiene que tocar este test, solo el texto del tema).

    Control negativo comprobado: quitar `ha_clear_system_log` del tema → cae
    `test_nombra_cada_tool_de_la_familia` nombrándola.
    """

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_y_alias(self) -> None:
        tema = _GUIDE["core_diagnostics"]
        # `notifications` y `validation`: tramo B (T029).
        for alias in ("core_diagnostics", "logs", "log", "LOGS", "notifications",
                      "validation"):
            self.assertEqual(await self.guide(alias), tema, alias)
        for clave in ("duplicate_log_file", "NOTSET", "persistence", "error_log_unavailable",
                      "not_validated", "response_too_large", "keys=", "dismiss_all",
                      "config_entry_id"):
            self.assertIn(clave, tema)

    def test_debug_se_lee_en_el_log_de_core(self) -> None:
        # T036 (principio V): el log del sistema solo guarda WARNING o más, así
        # que la receta no puede mandar a buscar las líneas DEBUG en él.
        # Control negativo (comprobado): con el paso 2 de antes («→ reproducir
        # el fallo → `ha_list_system_log` o `ha_get_error_log`») cae este test.
        tema = _GUIDE["core_diagnostics"]
        self.assertIn("HA solo guarda aquí WARNING, ERROR y CRITICAL", tema)
        self.assertIn("las líneas DEBUG e INFO NUNCA\nllegan al log del sistema", tema)
        receta = tema[tema.index("Receta «¿por qué falla esta integración?»"):]
        paso2 = receta[receta.index("\n2. "):receta.index("\n3. ")]
        self.assertIn("log de Core: `sv_get_core_logs` o `ha_get_error_log`", paso2)
        self.assertIn("NO en `ha_list_system_log`", paso2)
        self.assertNotIn("→ `ha_list_system_log`", paso2)

    async def test_indice_y_diagnostics(self) -> None:
        self.assertIn("core_diagnostics", await self.guide())
        self.assertIn('hermes_guide("core_diagnostics")', _GUIDE["diagnostics"])

    def test_nombra_cada_tool_de_la_familia(self) -> None:
        from tests.test_tools_registration import _do_register

        completo = set(_do_register().tools)
        sin = set(_do_register(["core_diagnostics"]).tools)
        de_la_familia = sorted(completo - sin)
        self.assertTrue(de_la_familia)
        faltan = [n for n in de_la_familia if f"`{n}" not in _GUIDE["core_diagnostics"]]
        self.assertEqual(faltan, [])


def _plano(texto: str) -> str:
    # Los textos van partidos en líneas de 80: se comparan con un solo espacio.
    return " ".join(texto.split())


def _apartado_4(texto: str) -> str:
    return _plano(texto[texto.index("4) OPERACIONES LARGAS"):texto.index("5) SI DUDAS")])


class TestGuiaJobs(unittest.TestCase):
    """Spec 027, FR-001: la guía dice qué significa `success` en un job.

    `done` es true también cuando el job falla, el Supervisor no distingue
    avisos de errores fatales, y los errores de los sub-jobs no suben al job
    (van en `child_errors` y también dan `success: false`, D-1).

    Control negativo comprobado: con el tema `backups` de antes (solo la lista
    de tools en la línea de jobs) → `test_backups` en rojo.
    """

    _FRASE = "cualquier entrada en `errors` da `success: false`"

    def test_backups(self) -> None:
        self.assertIn(self._FRASE, _plano(_GUIDE["backups"]))
        self.assertIn("`child_errors`", _GUIDE["backups"])
        self.assertIn("sv_get_backup", _GUIDE["backups"])

    def test_supervisor(self) -> None:
        self.assertIn(self._FRASE, _plano(_GUIDE["supervisor"]))
        self.assertIn("`child_errors`", _GUIDE["supervisor"])

    def test_instrucciones(self) -> None:
        apartado = _apartado_4(INSTRUCTIONS)
        self.assertIn(self._FRASE, apartado)
        self.assertIn("`child_errors`", apartado)


class TestGuiaApps(unittest.TestCase):
    """Spec 027, FR-007: «apps (add-ons)», el término del Supervisor
    2026.11.0, sin cambiar el nombre de ninguna tool.

    Control negativo comprobado: con el título de antes («Sistema: add-ons,
    host y core») → `test_titulo_del_tema_supervisor` en rojo.
    """

    def test_titulo_del_tema_supervisor(self) -> None:
        self.assertTrue(
            _GUIDE["supervisor"].startswith("# Sistema: apps (add-ons), host y core"))

    def test_instrucciones_apartado_4(self) -> None:
        self.assertIn("apps (add-ons)", _apartado_4(INSTRUCTIONS))

    def test_el_tema_nombra_las_doce_tools_de_apps(self) -> None:
        for nombre in (
            "sv_list_addons", "sv_get_addon", "sv_get_addon_options",
            "sv_set_addon_options", "sv_start_addon", "sv_stop_addon",
            "sv_restart_addon", "sv_install_addon", "sv_uninstall_addon",
            "sv_update_addon", "sv_get_addon_logs", "sv_get_addon_stats",
        ):
            with self.subTest(tool=nombre):
                self.assertIn(f"`{nombre}", _GUIDE["supervisor"])


class TestTemaUpdates(unittest.IsolatedAsyncioTestCase):
    """Spec 015, FR-020 (T013): tema `updates` (alias `update`, `upgrade`) con
    las tres tools del tramo 1, el orden, los bloqueos y el token atado; el
    tema `supervisor` remite a él; las instrucciones solo lo anuncian con la
    familia `system_updates` activa (principio V).

    Control negativo: quitar el alias `upgrade` → cae `test_tema_y_alias`.
    """

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_y_alias(self) -> None:
        texto = await self.guide("updates")
        self.assertIs(texto, _GUIDE["updates"])
        for alias in ("update", "upgrade", "UPDATE", " Upgrade "):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)

    def test_cita_las_tools_y_lo_que_hay_que_saber(self) -> None:
        texto = _GUIDE["updates"]
        for palabra in ("sv_list_available_updates", "sv_check_for_updates",
                        "sv_update_core", "sv_get_job_status", "sv_update_addon",
                        "update_blocked", "preview_outdated", "unhealthy",
                        "supervisor_update_pending", "plugins_outdated",
                        "low_disk_space", "config_invalid", "config_check_failed",
                        "Supervisor → Core → OS", "release_url", "update_with: null"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)

    def test_os_y_supervisor(self) -> None:
        # Tramo 2 (T025): las dos tools, el orden con el reinicio del host,
        # que el OS no se aplica hasta reiniciar y qué hacer tras el reinicio
        # del Supervisor.
        texto = _GUIDE["updates"]
        for palabra in ("sv_update_os", "sv_update_supervisor", "sv_reboot_host",
                        "Supervisor → Core → OS y reiniciar el host", "not_haos",
                        "reboot_pending", "reinicia TODO", "sv_get_supervisor_info",
                        "status: started", "verify_with", "sv_create_backup_full"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)

    def test_entidades_update(self) -> None:
        # Tramo 3 (T042): las tres tools, el encaminamiento por el registro,
        # el rechazo de Hermes y la `hint` de `ha_call_service`.
        texto = _GUIDE["updates"]
        for palabra in ("ha_list_updates", "ha_get_update_release_notes",
                        "ha_install_update", "use_dedicated_tool", "registro de entidades",
                        "self_update_not_supported", "self_check_unavailable",
                        "status: running", "ha_call_service", "hint",
                        "no_update_available", "texto de terceros"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)

    def test_las_tools_que_cita_existen(self) -> None:
        # La guía no puede anunciar tools que el servidor no tiene (principio
        # V): toda `sv_*`/`ha_*` citada está registrada.
        import re

        from tests.test_tools_registration import _real_registry

        tools = _real_registry()
        citadas = set(re.findall(r"`((?:sv|ha)_[a-z_]+)", _GUIDE["updates"]))
        self.assertTrue(citadas)
        self.assertEqual(sorted(citadas - set(tools)), [])

    async def test_supervisor_indice_e_instrucciones(self) -> None:
        from hermes.tools.guide import instrucciones

        self.assertIn('hermes_guide("updates")', _GUIDE["supervisor"])
        self.assertIn("`updates`", await self.guide())
        self.assertIn(", updates,", INSTRUCTIONS)
        sin = instrucciones(frozenset({"system_updates"}))
        self.assertNotIn("updates", sin.replace("ha_update_", ""))
        self.assertNotIn("@", sin)


class TestTemaAppStore(unittest.IsolatedAsyncioTestCase):
    """Spec 030, T010 (FR-020), tramo 1: tema `app_store` con las cinco
    tools de repositorios y recarga, el aviso de terceros al añadir, que
    quitar exige desinstalar antes y reparar frente a recargar; sus alias; el
    índice lo nombra y las instrucciones del servidor solo con la familia
    activa; los temas que este tramo no toca no cambian.

    Control negativo comprobado: sin `@TEMA_TIENDA@` en las instrucciones →
    cae `test_indice_e_instrucciones`."""

    # sha256 (16 hex) de temas que la 030 no toca, más `supervisor`, que el
    # tramo 2 cambia a propósito (remite a `app_store`, validación de
    # opciones y vistas previas de instalar y actualizar; FR-020) y el
    # converge vuelve a cambiar (mensajes sin valores y versión atada al
    # token, T029-T031). Al integrar la 030 en la rama del programa, la
    # huella de `supervisor` es la del texto mezclado: «apps (add-ons)» y los
    # jobs de la 027 y la remisión a `updates` de la 015, más lo de la 030.
    _HUELLAS = {
        "supervisor": "59ff6dec570dcfbf",
        "marketplace": "f83ec233a87ad95b",
        "system_diagnostics": "50509e336b5ca215",
        "security": "157ee929e7db08ae",
        "workflows": "53b81454a6708b9a",
    }

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_con_las_cinco_tools(self) -> None:
        texto = await self.guide("app_store")
        self.assertIs(texto, _GUIDE["app_store"])
        for palabra in ("sv_list_store_repositories", "sv_add_store_repository",
                        "sv_remove_store_repository", "sv_repair_store_repository",
                        "sv_reload_store", "CÓDIGO DE TERCEROS", "DOS PASOS",
                        "EXACTA", "***REDACTED***", "NO instala",
                        "repository_already_added", "builtin_repository",
                        "repository_in_use", "sv_uninstall_addon", "not_supported",
                        "_third_party_text", "Marketplace", "marketplace"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)
        # Reparar frente a recargar.
        self.assertIn("Reparar arregla UN repositorio roto; recargar trae lo nuevo de todos",
                      texto)

    async def test_alias(self) -> None:
        texto = _GUIDE["app_store"]
        for alias in ("store", "tienda", "repositories", "repository",
                      "repositorios", "STORE"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)

    async def test_tramo_2_fichas_reconstruir_y_version(self) -> None:
        """T024 (FR-011, FR-020): las nueve tools, que changelog y
        documentación son de la versión de la tienda y por trozos, la
        disponibilidad, reconstruir (local frente a `force`, qué pasa si
        falla) y que no se puede elegir versión, con la vuelta atrás."""
        texto = " ".join(_GUIDE["app_store"].split())
        for palabra in ("sv_get_addon_changelog", "sv_get_addon_documentation",
                        "sv_get_addon_availability", "sv_rebuild_addon",
                        "versión de la TIENDA", "POR TROZOS", "next_offset",
                        "changelog_not_found", "documentation_not_found",
                        "arquitectura", "force=true", "Si la construcción FALLA",
                        "rebuild_version_changed", "rebuild_not_supported",
                        "addon_not_in_store", "already_up_to_date",
                        "NO SE PUEDE ELEGIR", "sv_restore_backup_partial",
                        "usuario, contraseña o token"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)
        for alias in ("changelog", "documentation", "rebuild", "availability"):
            with self.subTest(alias=alias):
                self.assertIs(await self.guide(alias), _GUIDE["app_store"])

    async def test_el_tema_supervisor_remite(self) -> None:
        texto = " ".join(_GUIDE["supervisor"].split())
        for palabra in ('hermes_guide("app_store")', "VALIDA las opciones",
                        "invalid_options", "addon_not_available",
                        "principio del changelog", "no se puede elegir otra"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)

    async def test_la_busqueda_de_la_tabla_lista_las_dedicadas(self) -> None:
        texto = await self.guide("generic_commands", search="store")
        for palabra in ("sv_get_addon_changelog", "sv_get_addon_availability",
                        "sv_install_addon", "sv_list_store_repositories", "dedicated"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)
        texto = await self.guide("generic_commands", search="rebuild")
        self.assertIn("sv_rebuild_addon", texto)

    async def test_indice_e_instrucciones(self) -> None:
        from hermes.tools.guide import instrucciones

        self.assertIn("`app_store`", await self.guide())
        self.assertIn("app_store", INSTRUCTIONS)
        sin = instrucciones(frozenset({"app_store"}))
        self.assertNotIn("app_store", sin)
        self.assertNotIn("@", sin)
        self.assertIn("marketplace, security", sin)

    def test_los_temas_que_no_toca_no_cambian(self) -> None:
        import hashlib

        for tema, huella in self._HUELLAS.items():
            with self.subTest(tema=tema):
                real = hashlib.sha256(_GUIDE[tema].encode()).hexdigest()[:16]
                self.assertEqual(real, huella)


if __name__ == "__main__":
    unittest.main()


class TestTemaMounts(unittest.IsolatedAsyncioTestCase):
    """Spec 019, FR-018 (tramo 1): tema `mounts` con las seis tools de
    montajes, el flujo de llevar los backups a un NAS, que las credenciales
    no se devuelven y que editar sin ellas las quita; sus alias; el índice y
    las instrucciones lo nombran solo con la familia activa. El tema
    `backups` no cambia en este tramo (lo hace el tramo 2).

    Control negativo comprobado: sin el tema, su línea del índice y su
    hueco en las instrucciones caen los tres (3 failed, 45 passed).
    """

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_con_las_tools_y_alias(self) -> None:
        texto = await self.guide("mounts")
        self.assertIs(texto, _GUIDE["mounts"])
        for palabra in ("sv_list_mounts", "sv_create_mount", "sv_update_mount",
                        "sv_delete_mount", "sv_reload_mount",
                        "sv_set_default_backup_mount", "cifs", "nfs", "disk",
                        "device", "uuid", "sv_get_resolution", "safety backup",
                        "removed_if_present", "credentials"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)
        # Las frases que importan: no se devuelven y editar sin ellas las
        # quita; el flujo del NAS.
        for frase in ("nunca se devuelven", "las quita", "NAS"):
            with self.subTest(frase=frase):
                self.assertIn(frase, texto)
        for alias in ("cifs", "nfs", "nas", "network_storage", "backup_settings",
                      "NAS"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)
        # `backup` sigue llevando a `backups`, como en la 1.1.2.
        self.assertEqual(await self.guide("backup"), _GUIDE["backups"])

    async def test_las_tools_que_nombra_existen(self) -> None:
        import re

        from tests.test_tools_registration import _real_registry

        registradas = set(_real_registry())
        nombradas = set(re.findall(r"\b((?:sv|ha|fs)_[a-z_]+)\b", _GUIDE["mounts"]))
        self.assertTrue(nombradas)
        self.assertEqual(sorted(nombradas - registradas), [])

    async def test_indice_e_instrucciones(self) -> None:
        from hermes.tools.guide import instrucciones

        self.assertIn("`mounts`", await self.guide())
        self.assertIn("mounts", INSTRUCTIONS)
        self.assertNotIn("mounts", instrucciones(frozenset({"mounts"})))


class TestGuiaCompleta019(unittest.IsolatedAsyncioTestCase):
    """Spec 019, FR-018 (tramo 2): el tema `mounts` nombra las tres tools de
    ajustes de backup y `days_until_stale`; el tema `backups` explica
    `location`, `.local` y que sin ella el backup va al montaje por defecto.

    Control negativo comprobado: quitar `sv_reload_backups` del tema
    `mounts` → 1 failed (su subtest); quitar «`.cloud_backup` no se admite»
    de `backups` → 2 failed (su subtest y la huella del tema); restaurado,
    verde.
    """

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_mounts_con_los_ajustes(self) -> None:
        texto = await self.guide("mounts")
        for palabra in ("sv_get_backup_settings", "sv_set_backup_settings",
                        "sv_reload_backups", "days_until_stale", "location"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)

    async def test_backups_con_location(self) -> None:
        texto = await self.guide("backups")
        for palabra in ("location", ".local", "montaje por defecto",
                        ".cloud_backup", "sv_create_backup_full"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)
