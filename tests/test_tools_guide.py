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
        # `not_supported`) y `helpers` (counters); su CHANGELOG lo dice. La
        # 017 (tramo D) cambia `automations` (la vista previa valida y remite
        # a `blueprints` y `automation_assist`; el caso de un HA anterior a
        # los comandos); su CHANGELOG lo dice. Huella recalculada al integrar
        # la 017 sobre la de la 033.
        "automations": "d27ee3c45bc13171",
        # La 027 cambia `backups` (`success` y `child_errors` de los jobs) y la
        # 019 (tramo 2) también (`location` en sv_create_backup_*); sus
        # CHANGELOG lo dicen. Huella recalculada al integrar la 019. La 031
        # (tramo 4, T055) añade el cifrado de los safety backups; su
        # CHANGELOG lo dice. La convergencia (T062) dice que `required` no
        # reutiliza uno sin cifrar; también en el CHANGELOG.
        "backups": "3e685f47171224e7",
        # La 016 cambia `config_entries` (remite a `integration_flows`; el
        # reconfigure va por su tool y el `reauth` pide token), `diagnostics`
        # (textos de los avisos y remite a `repair_flows`) y `helpers`
        # («Helpers por config entry», CAP-037); su CHANGELOG lo dice. Huellas
        # recalculadas al integrarla sobre las de la 033, la 027 y la 012.
        # El cierre de seguridad de la 1.2.0 cambia `config_entries` (las
        # opciones salen tapadas y se rechaza el marcador) y `generic_commands`
        # (la URL con `usuario:***@`); su CHANGELOG lo dice.
        "config_entries": "a37e88797523ec8e",
        "data": "c77e3e6782cc89a7",
        # La 012 cambia `diagnostics` (remite a `core_diagnostics`) y la 022
        # (tramo 2) también: ya no dice que Hermes nunca aplica sugerencias,
        # sino que lo hace `sv_apply_resolution_suggestion`; sus CHANGELOG lo
        # dicen.
        "diagnostics": "838ff4a3a3eeaddb",
        "events": "3765a76095ece40f",
        "filesystem": "b5902d6d0ff666c1",
        # La convergencia de la 025 (T047) cambia `generic_commands`: el rechazo
        # `redacted_value_in_payload`; su CHANGELOG lo dice.
        "generic_commands": "55325dfe9602e63b",
        "helpers": "c99850e94eb5c996",
        # La 018 cambia `lovelace` (guardado por vista) y `services`
        # (`ha_call_service_response` con token); su CHANGELOG lo dice. La
        # 024 (tramo 2) le añade la sección «Restablecer un dashboard»
        # (FR-016); su CHANGELOG lo dice. La convergencia de la 024 (T033,
        # T034) añade `strategy` y `dashboards_unavailable`. Huella recalculada.
        "lovelace": "04bebf2041d378db",
        # La converge de la 026 (T033) cambia `marketplace`: aceptar el aviso
        # en la interfaz no sirve a Hermes (D-29) y remite a
        # `marketplace_manage`; su CHANGELOG lo dice.
        "marketplace": "f49c5f1c9d78b51b",
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
        `network`, `network/url` y `http/config`. La 021 (tramo c, T046) ya
        tiene tools para cambiar la red y el HTTP: el tema remite a
        `core_network` y el alias `network` pasa a ese tema."""
        texto = _GUIDE["system_status"]
        for palabra in ('ha_read_ws_command(type="network")',
                        'ha_read_ws_command(type="network/url")',
                        'ha_read_ws_command(type="http/config")',
                        "internal", "external", "cloud", "stable", "pending",
                        "core_network", "ha_update_http_config"):
            self.assertIn(palabra, texto)
        self.assertNotIn("NO tiene tool", texto)
        self.assertEqual(await self.guide("network"), _GUIDE["core_network"])
        self.assertEqual(await self.guide("urls"), texto)


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

    async def test_mantenimiento_de_la_020(self) -> None:
        """Spec 020, T013 (FR-020): el tema suma las tres tools de
        mantenimiento, los dos pasos, `queued`, la diferencia entre convertir
        (cambiar la unidad) y no convertir (metadatos), que solo un backup lo
        deshace y el rango efectivo al borrar. «SOLO LECTURA» queda solo para
        el grupo de las tres lecturas, no para el tema entero."""
        texto = await self.guide("recorder")
        for palabra in ("ha_clear_statistics", "ha_change_statistics_unit",
                        "ha_update_statistics_metadata", "dos pasos",
                        "confirmation_token", "queued: true", "backup",
                        "CONVIERTE", "sin convertir valores", "converts_values: false",
                        "effective_range", "SE SOLAPAN", "not_supported_for_source",
                        "unit_mismatch", "statistics_not_found", "statistics_changed"):
            self.assertIn(palabra, texto)
        self.assertNotIn("Tres tools de SOLO LECTURA: ninguna", texto)
        self.assertIn("mantenimiento", await self.guide())

    async def test_mantenimiento_del_tramo_2_de_la_020(self) -> None:
        """Spec 020, T029 (FR-020): las cinco de mantenimiento; el ajuste no
        es idempotente; la importación (horas en punto, `mean_type`, fuente,
        `stats` omitible al confirmar) y la genérica para regenerar los avisos
        de Repairs."""
        texto = await self.guide("recorder")
        for palabra in ("ha_adjust_statistics_sum", "ha_import_statistics",
                        "NO es idempotente", "statistic_has_no_sum", "sum_at_start",
                        "hora en punto", "mean_type", "source: recorder", "stats",
                        "omit_on_confirm", "overwritten_rows", "5000",
                        'ha_call_ws_command(type="recorder/update_statistics_issues")',
                        "ha_statistics_during_period"):
            self.assertIn(palabra, texto)
        self.assertIn("Las cinco en dos pasos", texto)

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


class TestTemaEnergy(unittest.IsolatedAsyncioTestCase):
    """Spec 020, T045 (FR-020): el tema `energy` nombra las dos tools, la
    semántica de reemplazo por lista, el ciclo leer → editar → guardar y las
    cuatro lecturas con su llamada exacta; sus alias resuelven a él, el
    índice lo menciona y la búsqueda en la tabla enseña el ejemplo de
    consumo fósil."""

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_con_contenido(self) -> None:
        texto = await self.guide("energy")
        self.assertIs(texto, _GUIDE["energy"])
        for palabra in ("ha_get_energy_prefs", "ha_update_energy_prefs",
                        "REEMPLAZA ENTERA", "se conservan", "leer → editar → guardar",
                        "confirmation_token", "current", "new", "kept", "warnings",
                        "removes_all_sources", "unknown_statistic", "energy_prefs_changed",
                        "configured: false", "energy_not_loaded", "invalid_format",
                        'ha_read_ws_command(type="energy/validate")',
                        'ha_read_ws_command(type="energy/info")',
                        'ha_read_ws_command(type="energy/solar_forecast")',
                        'ha_read_ws_command(type="energy/fossil_energy_consumption"',
                        '"co2_statistic_id": "sensor.intensidad_co2"'):
            self.assertIn(palabra, texto)

    async def test_alias(self) -> None:
        texto = await self.guide("energy")
        for alias in ("energy_prefs", "energy_dashboard", "energia", "ENERGIA"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)

    async def test_el_indice_lo_menciona(self) -> None:
        self.assertIn("`energy`", await self.guide())

    async def test_la_busqueda_enseña_el_ejemplo(self) -> None:
        texto = await self.guide("generic_commands", search="fossil")
        self.assertIn("energy/fossil_energy_consumption", texto)
        self.assertIn('"co2_statistic_id": "sensor.intensidad_co2"', texto)
        self.assertIn('"period": "hour"', texto)


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
    # jobs de la 027 y la remisión a `updates` de la 015, más lo de la 030,
    # y, desde la integración de la 022, su remisión a `system_control` y,
    # desde la de la 032, su remisión a `host_control` (apagar, hostname,
    # swap, ranura y red del host; FR-017 de la 032).
    _HUELLAS = {
        "supervisor": "dc38e81c61a06932",
        "marketplace": "f49c5f1c9d78b51b",
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
        # Desde la 023, el tema `conversation` va entre los dos y, desde la
        # 026, con `marketplace_manage` activa su tema va detrás de
        # `marketplace`.
        self.assertIn("marketplace, marketplace_manage, conversation, security", sin)

    def test_los_temas_que_no_toca_no_cambian(self) -> None:
        import hashlib

        for tema, huella in self._HUELLAS.items():
            with self.subTest(tema=tema):
                real = hashlib.sha256(_GUIDE[tema].encode()).hexdigest()[:16]
                self.assertEqual(real, huella)


class TestTemasDeLa021TramoA(unittest.IsolatedAsyncioTestCase):
    """Spec 021, T013 (FR-022): temas `core_config` y `assistant_exposure`
    con sus tools, sus alias y su entrada en el índice y en el docstring de
    `hermes_guide`. Las huellas de los temas de antes de la 013 no cambian
    (`test_los_demas_temas_no_cambian`)."""

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_core_config(self) -> None:
        texto = await self.guide("core_config")
        self.assertIs(texto, _GUIDE["core_config"])
        for palabra in ("ha_get_core_config", "ha_update_core_config", "DOS PASOS",
                        "yaml_source", "update_units", "partial", "no_changes",
                        'ha_read_ws_command(type="config/core/detect")',
                        "sale a internet", "No guarda nada"):
            self.assertIn(palabra, texto)
        for alias in ("location", "units", "time_zone", "CORE_CONFIG"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)

    async def test_assistant_exposure(self) -> None:
        texto = await self.guide("assistant_exposure")
        self.assertIs(texto, _GUIDE["assistant_exposure"])
        for palabra in ("ha_list_exposed_entities", "ha_set_entity_exposure",
                        "ha_set_expose_new_entities", "conversation", "cloud.alexa",
                        "cloud.google_assistant", "MCP Server", "Home Assistant Cloud",
                        "sensitive", "sin token", "dos pasos"):
            self.assertIn(palabra, texto)
        # «voice» y «assist» pasaron al tema `conversation` al integrar la 023
        # (allí los vigila `TestTemaConversacion.test_alias`).
        for alias in ("exposure", "expose"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)
        # Los dos temas se citan entre sí (integración de la 023).
        self.assertIn('hermes_guide("conversation")', texto)

    async def test_indice_y_docstring(self) -> None:
        indice = await self.guide()
        doc = self.mcp.tools["hermes_guide"].__doc__
        for tema in ("core_config", "assistant_exposure"):
            self.assertIn(f"`{tema}`", indice)
            self.assertIn(tema, doc)

    def test_system_status_remite_las_urls_a_core_config(self) -> None:
        self.assertIn("ha_update_core_config", _GUIDE["system_status"])


class TestTemaDeUsuarios(unittest.IsolatedAsyncioTestCase):
    """Spec 021, T029 (FR-022): tema `users` con sus cuatro tools, que nada
    maneja contraseñas ni tokens, que el usuario creado no entra sin
    credenciales, las protecciones, que las sesiones no se listan y que todo
    confirma; alias `user` y `accounts`; índice y docstring."""

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_users(self) -> None:
        texto = await self.guide("users")
        self.assertIs(texto, _GUIDE["users"])
        for palabra in ("ha_list_users", "ha_create_user", "ha_update_user",
                        "ha_delete_user", "contraseñas", "tokens", "SIN credenciales",
                        "no puede iniciar sesión", "protected_user", "owner", "hermes",
                        "system_generated", "last_admin", "preview_unavailable",
                        "sesiones de los usuarios no se pueden listar", "dos pasos",
                        "irreversible"):
            self.assertIn(palabra, texto)
        for alias in ("user", "accounts", "USERS"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)

    async def test_indice_y_docstring(self) -> None:
        self.assertIn("`users`", await self.guide())
        self.assertIn("users", self.mcp.tools["hermes_guide"].__doc__)


class TestTemaDeRedYHttp(unittest.IsolatedAsyncioTestCase):
    """Spec 021, T046 (FR-022): tema `core_network` con sus tres tools, la
    prueba de 5 minutos, los avisos, el rechazo de `server_host`, el bloqueo
    de reinicio y cómo leer; sección de analytics y labs en `core_config` con
    las cuatro llamadas exactas; alias; índice y docstring."""

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_core_network(self) -> None:
        texto = await self.guide("core_network")
        self.assertIs(texto, _GUIDE["core_network"])
        for palabra in ("ha_update_network_config", "ha_update_http_config",
                        "ha_promote_http_config", "5 minutos", "REINICIA",
                        'ha_read_ws_command(type="network")',
                        'ha_read_ws_command(type="http/config")',
                        "access_risk", "apps_lockout", "172.30.32.1",
                        "restart_blocked", "sv_check_core_config",
                        "nothing_to_promote", "discard_pending",
                        "unsupported_by_ha_version", "dos pasos"):
            self.assertIn(palabra, texto)
        for codigo in ("port", "server_host", "ssl", "reverse_proxy", "ip_ban",
                       "ssl_profile", "cors", "x_frame_options", "pending_replaced"):
            self.assertIn(f"`{codigo}`", texto)
        for alias in ("http", "ssl", "port", "proxy", "network", "CORE_NETWORK"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)

    async def test_convergencia_t058_t061(self) -> None:
        """T058-T061: el porqué de D-3 dice la verdad en 2026.11 (socket Unix
        del Supervisor; se cortan las apps que van a `homeassistant:8123`),
        promover repite los avisos, la vuelta a la estable y los avisos de
        red. Control negativo: con el texto viejo («dejaría fuera a Hermes y a
        todas las apps») cae."""
        texto = await self.guide("core_network")
        for palabra in ("socket", "homeassistant:8123", "server_host_internal_only",
                        "`trial: false`", "`no_ipv4`", "`default_adapter_excluded`",
                        "repite los `warnings`"):
            self.assertIn(palabra, texto)
        self.assertNotIn("dejaría\n  fuera a Hermes", texto)
        self.assertNotIn("fuera a Hermes y a todas las apps", texto.replace("\n  ", " "))

    async def test_analytics_y_labs_en_core_config(self) -> None:
        texto = _GUIDE["core_config"]
        for palabra in ('ha_read_ws_command(type="analytics")',
                        'ha_call_ws_command(type="analytics/preferences"',
                        'ha_read_ws_command(type="labs/list")',
                        'ha_call_ws_command(type="labs/update"',
                        "mundo", "abierto"):
            self.assertIn(palabra, texto)
        for alias in ("analytics", "labs"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)

    async def test_indice_y_docstring(self) -> None:
        self.assertIn("`core_network`", await self.guide())
        self.assertIn("core_network", self.mcp.tools["hermes_guide"].__doc__)


class TestTemaHostControl(unittest.IsolatedAsyncioTestCase):
    """Spec 032, FR-017 (tramo 1): tema `host_control` con las cuatro tools
    del host, el aviso de que nadie enciende el host a distancia y cómo
    volver de la ranura; sus alias; el índice y las instrucciones lo nombran
    solo con la familia activa. `host` sigue llevando a `supervisor`, que
    remite al tema nuevo."""

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_con_las_tools_y_alias(self) -> None:
        texto = await self.guide("host_control")
        self.assertIs(texto, _GUIDE["host_control"])
        for palabra in ("sv_shutdown_host", "sv_set_hostname", "sv_set_swap",
                        "sv_set_boot_slot", "sv_reboot_host", "sv_get_os_info",
                        "outcome", "unknown", "force", ".local", "reboot_required"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)
        for frase in ("nadie puede encenderlo a distancia", "reinicia en el acto",
                      "Para volver"):
            with self.subTest(frase=frase):
                self.assertIn(frase, texto)
        for alias in ("hostname", "swap", "boot_slot", "shutdown", "SHUTDOWN"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)
        # `host` sigue siendo `supervisor`, como en la 1.1.2, y lo remite.
        self.assertEqual(await self.guide("host"), _GUIDE["supervisor"])
        self.assertIn("host_control", _GUIDE["supervisor"])

    async def test_las_tools_que_nombra_existen(self) -> None:
        import re

        from tests.test_tools_registration import _real_registry

        registradas = set(_real_registry())
        nombradas = set(re.findall(r"\b((?:sv|ha|fs)_[a-z_]+)\b", _GUIDE["host_control"]))
        self.assertTrue(nombradas)
        self.assertEqual(sorted(nombradas - registradas), [])

    async def test_indice_e_instrucciones(self) -> None:
        from hermes.tools.guide import instrucciones

        self.assertIn("`host_control`", await self.guide())
        self.assertIn("host_control", INSTRUCTIONS)
        # Desde el tramo 2 el tema cubre también la red del host: solo
        # desaparece con las dos familias desactivadas.
        self.assertIn("host_control", instrucciones(frozenset({"host_control"})))
        self.assertIn("host_control", instrucciones(frozenset({"host_network"})))
        self.assertNotIn("host_control",
                         instrucciones(frozenset({"host_control", "host_network"})))


class TestTemaHostNetwork(unittest.IsolatedAsyncioTestCase):
    """Spec 032, FR-017 (tramo 2): el tema `host_control` cubre también la
    red del host: las tres tools, la guarda de la principal, que la red se
    lee con `sv_read_api("/network/info")`, que los bloques se reemplazan
    enteros y que la PSK no se devuelve; con sus alias. `network` lleva a
    `core_network` (spec 021), y los dos temas remiten al otro."""

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_red_en_el_tema(self) -> None:
        texto = await self.guide("host_control")
        for palabra in ("sv_reload_network", "sv_update_network_interface",
                        "sv_create_vlan", 'sv_read_api("/network/info")',
                        "primary_interface", "only_connected_interface",
                        "primary_unknown", '"psk": "set"', "REEMPLAZA",
                        "NO lo revierte", "ruta por defecto", "sin token"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)
        for alias in ("host_network", "network_config", "vlan", "wifi", "WiFi"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)
        # Desde la integración con la 021, `network` lleva a `core_network`
        # (la red de Core); cada tema remite al otro para no confundirlas.
        self.assertEqual(await self.guide("network"), _GUIDE["core_network"])
        self.assertIn('hermes_guide("core_network")', texto)
        self.assertIn('hermes_guide("host_control")', _GUIDE["core_network"])
        self.assertIn("red del host", _GUIDE["supervisor"])
        self.assertIn("red del host", await self.guide())


class TestTemaBackupIntegration(unittest.IsolatedAsyncioTestCase):
    """Spec 031, tramo 1 (T012, FR-021): tema `backup_integration` con las
    cuatro tools de agentes y ajustes, la retención y su estimación, y que la
    clave de cifrado no sale ni se cambia aquí; sus alias; el índice lo
    menciona; `backup` sigue llevando a `backups`; los temas de la 1.1.2 no
    cambian (lo vigila `TestTemaSystemDiagnostics.test_los_demas_temas_no_cambian`).

    Control negativo, comprobado: sin el alias `backup_retention` cae
    `test_tema_y_alias`; con `backup` apuntando a `backup_integration` cae
    `test_backup_sigue_en_backups`.
    """

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_y_alias(self) -> None:
        texto = await self.guide("backup_integration")
        self.assertIs(texto, _GUIDE["backup_integration"])
        for palabra in ("ha_list_backup_agents", "ha_update_backup_config",
                        "retention_effect", "ESTIMACIÓN", "within_24h",
                        "after_next_automatic_backup", "password_set",
                        "kit de emergencia", "state_changed", "sv_",
                        "hassio/*"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)
        # HALLAZGO de la 031: estas dos se quitaron (el proxy del Supervisor
        # rechaza `hassio/*` a las apps); la guía no puede prometerlas.
        for quitada in ("ha_get_update_backup_settings", "ha_set_update_backup_settings",
                        "supervisor_integration_unavailable"):
            with self.subTest(quitada=quitada):
                self.assertNotIn(quitada, texto)
        for alias in ("backup_agents", "backup_config", "backup_schedule",
                      "backup_retention", "BACKUP_AGENTS"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)

    async def test_indice_lo_menciona(self) -> None:
        self.assertIn("backup_integration", await self.guide())

    async def test_backup_sigue_en_backups(self) -> None:
        self.assertEqual(await self.guide("backup"), _GUIDE["backups"])

    async def test_crear_y_borrar_del_tramo_2(self) -> None:
        """Tramo 2 (T028): crear (con `encrypt`, `follow_with` y
        `ha_list_backups`), crear con los ajustes automáticos (la retención
        borra) y borrar (todas las ubicaciones), con sus alias.
        Control negativo, comprobado: sin el alias `delete_backup` cae."""
        texto = await self.guide("backup_integration")
        for palabra in ("ha_create_backup", "encrypt", "follow_with", "ha_list_backups",
                        "last_action_event", "ha_create_automatic_backup", "BORRA",
                        "ha_delete_backup", "TODAS sus ubicaciones",
                        "backup_locations_unreadable", "no_encryption_key",
                        "unknown_agent"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)
        for alias in ("create_backup", "delete_backup"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)

    async def test_restaurar_del_tramo_3(self) -> None:
        """Tramo 3 (T043): qué se sobrescribe, elegir ubicación, `password` y
        la clave de HA, `restore_started` y cómo comprobarlo, que Core se
        reinicia; alias `restore_backup` y `restore` (que no usaba ningún
        tema). Control negativo, comprobado: sin el alias `restore` cae."""
        texto = await self.guide("backup_integration")
        for palabra in ("ha_restore_backup", "SOBRESCRIBE", "Core se reinicia",
                        "agent_id_required", "also_in", "password_source",
                        "backup_encryption_key", "backup_encryption_key_unavailable",
                        "restore_started", "NO está confirmada", "ha_list_backups",
                        "last_action_event", "password_incorrect", "not_in_backup",
                        "sv_restore_backup_*", "anterior: pásala"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)
        for alias in ("restore_backup", "restore", "RESTORE"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)


class TestTemaBackupsCifrado031(unittest.IsolatedAsyncioTestCase):
    """Spec 031, tramo 4 (T055, FR-021): el tema `backups` explica los
    safety backups cifrados con la clave de HA, los tres valores de
    `safety_backup_encryption`, cómo restaurarlos (sin `password` o con el
    kit de emergencia), la clave anterior y que la retención los sigue
    podando; el tema `backup_integration` no cambia por esto.

    Control negativo, comprobado: sin el párrafo del cifrado caen
    `test_cifrado_de_los_safety_backups` y la huella del tema `backups`.
    """

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_cifrado_de_los_safety_backups(self) -> None:
        texto = await self.guide("backups")
        for palabra in ("safety_backup_encryption", "`auto`", "`required`", "`off`",
                        "kit de emergencia", "`encrypted`", "encryption_skipped_reason",
                        "encryption_key_unavailable", "SIN cifrar",
                        "sv_restore_backup_full", "password_source", "la anterior",
                        "sigue podando", "no la guarda ni la devuelve"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)
        self.assertEqual(await self.guide("backup"), texto)


class TestTemasDeIntegraciones(unittest.IsolatedAsyncioTestCase):
    """Spec 025 (FR-013, R-7): un tema por grupo de integraciones de la clase
    C. Cada uno dice que va por las genéricas, tiene las secciones
    `POR LA GENÉRICA`, `RECHAZADO` y `OTRA VÍA`, y NO miente frente a la
    tabla: lo que presenta como disponible está en `read`/`confirm` y lo que
    presenta como rechazado, en `deny` (principio V). Crece por tramos.

    Control negativo comprobado (tramo 1): citar `zwave_js/add_node` en
    `POR LA GENÉRICA` → cae `test_cruce_con_la_tabla`; quitar el alias
    `z-wave` → cae `test_tema_y_alias`. Tramo 2: citar
    `thread/get_dataset_tlv` en `POR LA GENÉRICA` de `matter_thread` → cae
    `test_cruce_con_la_tabla`; quitar el alias `otbr` → cae
    `test_tema_y_alias`. Tramo 3: citar `esphome/get_encryption_key` en
    `POR LA GENÉRICA` de `other_integrations` → cae `test_cruce_con_la_tabla`;
    quitar el alias `knx` → cae `test_tema_y_alias`.
    """

    # Tema → (prefijos de sus comandos, alias).
    _TEMAS = {
        "zwave": (("zwave_js/",), ("zwave_js", "z-wave", "z_wave", "Z-Wave")),
        "zigbee": (("zha/",), ("zha", "ZHA", "Zigbee")),
        "matter_thread": (("matter/", "thread/", "otbr/"),
                          ("matter", "thread", "otbr", "Matter", "OTBR")),
        "other_integrations": (
            ("mqtt/", "usb/", "bluetooth/", "dhcp/", "dynalite/", "esphome/",
             "generic_camera/", "insteon/", "knx/", "lcn/", "lorawan/",
             "mobile_app/", "modbus/", "notify/", "sendspin/", "ssdp/",
             "wyoming/", "zeroconf/"),
            ("mqtt", "usb", "bluetooth", "knx", "insteon", "lcn", "esphome",
             "dynalite", "lorawan", "modbus", "wyoming", "MQTT", "KNX")),
    }

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    @staticmethod
    def _secciones(texto: str) -> dict[str, str]:
        import re

        trozos = re.split(r"^(POR LA GENÉRICA|RECHAZADO|OTRA VÍA).*$", texto, flags=re.M)
        return {trozos[i]: trozos[i + 1] for i in range(1, len(trozos) - 1, 2)}

    async def test_tema_y_alias(self) -> None:
        for tema, (_, alias) in self._TEMAS.items():
            texto = _GUIDE[tema]
            for a in (tema, *alias):
                with self.subTest(tema=tema, alias=a):
                    self.assertEqual(await self.guide(a), texto)

    async def test_secciones_y_vias(self) -> None:
        for tema in self._TEMAS:
            with self.subTest(tema=tema):
                texto = _GUIDE[tema]
                self.assertEqual(set(self._secciones(texto)),
                                 {"POR LA GENÉRICA", "RECHAZADO", "OTRA VÍA"})
                for palabra in ("ha_read_ws_command", "ha_call_ws_command",
                                "generic_commands", "search="):
                    self.assertIn(palabra, texto)

    async def test_cruce_con_la_tabla(self) -> None:
        import re

        from hermes import command_table as ct

        for tema, (prefijos, _) in self._TEMAS.items():
            secciones = self._secciones(_GUIDE[tema])
            patron = re.compile(
                "(?:" + "|".join(map(re.escape, prefijos)) + r")[a-z0-9_/\-]+")
            disponibles = set(patron.findall(secciones["POR LA GENÉRICA"]))
            rechazados = set(patron.findall(secciones["RECHAZADO"]))
            self.assertTrue(disponibles and rechazados, tema)
            for comando in sorted(disponibles):
                with self.subTest(tema=tema, disponible=comando):
                    self.assertIn(ct.CORE_WS[comando].category, ("read", "confirm"))
            for comando in sorted(rechazados):
                with self.subTest(tema=tema, rechazado=comando):
                    self.assertEqual(ct.CORE_WS[comando].category, "deny")

    async def test_el_indice_y_la_docstring_lo_nombran(self) -> None:
        indice = await self.guide()
        for tema in self._TEMAS:
            with self.subTest(tema=tema):
                self.assertIn(f"`{tema}`", indice)
                self.assertIn(tema, self.guide.__doc__)

    async def test_zigbee_claves_y_permit(self) -> None:
        texto = _GUIDE["zigbee"]
        for palabra in ("zha.permit", "ha_call_service", "network_key", "tc_link_key",
                        "key_table", "stack_specific", "alarm_master_code", "tapad"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)
        otra_via = self._secciones(texto)["OTRA VÍA"]
        self.assertIn("zha.permit", otra_via)

    async def test_matter_thread_sin_codigos_ni_claves(self) -> None:
        texto = _GUIDE["matter_thread"]
        for palabra in ("active_dataset_tlvs", "thread/get_dataset_tlv",
                        "matter/open_commissioning_window", "interfaz"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)

    async def test_otras_integraciones_secretos_y_vias(self) -> None:
        texto = _GUIDE["other_integrations"]
        for palabra in ("mqtt.publish", "ha_call_service", "tapad", "dynalite/get-config",
                        "REEMPLAZA", "un solo mensaje", "webhook_id", "unknown_command",
                        "interfaz"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)
        self.assertIn("mqtt.publish", self._secciones(texto)["OTRA VÍA"])

    async def test_zwave_avisa_de_la_radio(self) -> None:
        texto = _GUIDE["zwave"]
        for palabra in ("network_neighbors", "radio", "zwave_js.set_config_parameter",
                        "ha_call_service", "set_config_parameter", "rebuild_node_routes",
                        "un solo mensaje"):
            self.assertIn(palabra, texto)


if __name__ == "__main__":
    unittest.main()


class TestTemaMarketplaceManage(unittest.IsolatedAsyncioTestCase):
    """Spec 026, tramo 1 (T012; FR-022 tras la DV-1): tema
    `marketplace_manage` con las cuatro tools, ignorar frente a reconocer,
    quitar solo personalizados no instalados, la condición del aviso de
    riesgos y del usuario del Supervisor (lo que Hermes no puede hacer); sus
    alias; el índice y las instrucciones lo nombran solo con su familia
    activa; los temas que este tramo no toca no cambian (huellas).

    Control negativo (T013): sin `@TEMA_MARKETPLACE@` en las instrucciones →
    cae `test_indice_e_instrucciones`."""

    # sha256 (16 hex) de temas que el tramo 1 de la 026 no toca.
    # `marketplace` lo cambia a propósito la converge (T033): ver
    # `test_tema_marketplace_dice_la_verdad_y_remite`.
    _HUELLAS = {
        "marketplace": "f49c5f1c9d78b51b",
        "security": "157ee929e7db08ae",
        "workflows": "53b81454a6708b9a",
    }

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_con_las_cuatro_tools(self) -> None:
        texto = await self.guide("marketplace_manage")
        self.assertIs(texto, _GUIDE["marketplace_manage"])
        plano = " ".join(texto.split())
        for palabra in ("ha_marketplace_acknowledge_critical",
                        "ha_marketplace_ignore_repository",
                        "ha_marketplace_remove_repository",
                        "ha_marketplace_refresh_repository",
                        "DOS PASOS", "not_critical", "already_acknowledged",
                        "repository_not_removed", "critical_repository",
                        "not_custom_repository", "repository_installed",
                        "github_rate_limited", "marketplace_write_unsupported",
                        "Ignorar frente a reconocer", "PERSONALIZADO",
                        "aviso de riesgos", "usuario del Supervisor",
                        "Hermes nunca lo acepta", "interfaz del Marketplace",
                        "third_party", "reviewed_by_home_assistant",
                        "_third_party_text"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, plano)

    async def test_tema_marketplace_dice_la_verdad_y_remite(self) -> None:
        """Converge T033 (FR-018, FR-022, R-2, D-29): aceptar el aviso en la
        interfaz no hace que Hermes pueda instalar, y el tema de lectura
        remite a `marketplace_manage`. Control negativo comprobado: con el
        texto anterior («lo tiene que aceptar una persona») caen el
        `assertNotIn` y la remisión."""
        plano = " ".join(_GUIDE["marketplace"].split())
        for palabra in ("NO hace que Hermes pueda instalar", "D-29",
                        "usuario del Supervisor", 'hermes_guide("marketplace_manage")'):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, plano)
        self.assertNotIn("lo tiene que aceptar una persona", plano)

    async def test_converge_automatizaciones_betas_y_bajos(self) -> None:
        """Converge T031, T032, T034-T037: la guía ya no dice que
        `update.install` por automatización «choca con lo mismo» ni que
        Hermes no puede activar betas; explica la vía sin usuario, el aviso
        de la vista previa, el interruptor «pre-release» con token y
        `use_entity_ids`, el aviso de Repairs que queda al ignorar, GitHub
        para volver a añadir, y `outcome_unknown`. Control negativo
        comprobado: con el texto anterior cae el `assertNotIn`."""
        plano = " ".join(_GUIDE["marketplace_manage"].split())
        self.assertNotIn("choca con lo mismo", plano)
        self.assertNotIn("mostrar betas y añadir", plano)
        for palabra in ("ALGUNA persona aceptó el aviso", "warning_marketplace_install",
                        "Es un aviso, no una barrera", "pre-release",
                        "warning_marketplace_beta", "use_entity_ids",
                        "hasta el próximo reinicio de Core", "GitHub conectado",
                        "outcome_unknown", "ha_marketplace_get_repository",
                        "la carpeta y el dominio"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, plano)

    async def test_desinstalar(self) -> None:
        # Tramo 2 (T026): el backup parcial sin base de datos y qué pasa si
        # falla, el reinicio (Hermes no reinicia) y `repository_in_use`.
        plano = " ".join(_GUIDE["marketplace_manage"].split())
        for palabra in ("ha_marketplace_uninstall", "Las cinco", "repository_not_installed",
                        "repository_in_use", "ha_delete_config_entry",
                        "SIN la base de datos", "safety_backup_encryption",
                        "encryption_key_unavailable", "backup_failed",
                        "no se desinstala nada", "backup=false", "restart_required",
                        "Hermes NO reinicia", "sv_restart_core", "may_break",
                        "desinstálalo antes con `ha_marketplace_uninstall`"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, plano)
        self.assertNotIn("Las cuatro", plano)
        for alias in ("marketplace uninstall", "hacs uninstall", "desinstalar marketplace"):
            with self.subTest(alias=alias):
                self.assertIs(await self.guide(alias), _GUIDE["marketplace_manage"])

    async def test_las_tools_que_nombra_existen(self) -> None:
        import re

        from tests.test_tools_registration import _real_registry

        registradas = set(_real_registry())
        nombradas = set(re.findall(r"\b((?:sv|ha|fs)_[a-z_]+)\b",
                                   _GUIDE["marketplace_manage"]))
        self.assertTrue(nombradas)
        self.assertEqual(sorted(nombradas - registradas), [])

    async def test_alias(self) -> None:
        texto = _GUIDE["marketplace_manage"]
        for alias in ("marketplace write", "marketplace_write", "hacs install",
                      "critical", "custom repository", "repositorio personalizado",
                      "CRITICAL"):
            with self.subTest(alias=alias):
                self.assertIs(await self.guide(alias), texto)
        # `hacs` sigue llevando al de lectura, como en la 1.1.2.
        self.assertIs(await self.guide("hacs"), _GUIDE["marketplace"])

    async def test_indice_e_instrucciones(self) -> None:
        from hermes.tools.guide import instrucciones

        self.assertIn("`marketplace_manage`", await self.guide())
        self.assertIn("marketplace, marketplace_manage", INSTRUCTIONS)
        sin = instrucciones(frozenset({"marketplace_manage"}))
        self.assertNotIn("marketplace_manage", sin)
        self.assertNotIn("@", sin)
        self.assertIn("marketplace, app_store", sin)

    def test_los_temas_que_no_toca_no_cambian(self) -> None:
        import hashlib

        for tema, huella in self._HUELLAS.items():
            with self.subTest(tema=tema):
                real = hashlib.sha256(_GUIDE[tema].encode()).hexdigest()[:16]
                self.assertEqual(real, huella)


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


class TestTemaSystemControl(unittest.IsolatedAsyncioTestCase):
    """Spec 022, FR-020 (tramo 1): tema `system_control` con las siete tools,
    qué corta cada una y cuánto, las listas cerradas, los rechazos, lo que va
    por la tabla y la receta «Core no arranca»; sus alias; el índice y las
    instrucciones lo nombran solo con la familia activa; `supervisor` remite
    a él.

    Control negativo comprobado (T014): sin `jobs_in_progress` en el tema →
    cae su subtest; sin la línea del índice → cae `test_indice_e_instrucciones`.
    """

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_con_las_tools_y_alias(self) -> None:
        texto = await self.guide("system_control")
        self.assertIs(texto, _GUIDE["system_control"])
        for palabra in ("sv_start_core", "sv_rebuild_core", "sv_set_core_options",
                        "sv_reload_supervisor", "sv_restart_supervisor",
                        "sv_repair_supervisor", "sv_set_supervisor_options",
                        # qué corta y cuánto
                        "interrupts", "1-5 minutos", "30-90 s", "Minutos",
                        # listas cerradas y rechazos
                        "boot", "watchdog", "audio_input", "image", "refresh_token",
                        "timezone", "country", "logging", "auto_update",
                        "diagnostics", "channel", "not_allowed",
                        "jobs_in_progress", "already_running", "blocked",
                        "no_changes", "started", "verify_with",
                        # por la tabla
                        "/core/stats", "/supervisor/stats", "/host/reload",
                        "/core/stop",
                        # receta
                        "Core no arranca", "sv_get_core_logs", "sv_check_core_config"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)
        for alias in ("core_control", "supervisor_control", "CORE_CONTROL"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)
        # `core` y `system` siguen llevando a `supervisor`, como en la 1.1.2.
        self.assertEqual(await self.guide("core"), _GUIDE["supervisor"])
        self.assertEqual(await self.guide("system"), _GUIDE["supervisor"])

    async def test_las_tools_que_nombra_existen(self) -> None:
        import re

        from tests.test_tools_registration import _real_registry

        registradas = set(_real_registry())
        nombradas = set(re.findall(r"\b((?:sv|ha|fs)_[a-z_]+)\b", _GUIDE["system_control"]))
        self.assertTrue(nombradas)
        self.assertEqual(sorted(nombradas - registradas), [])

    async def test_indice_e_instrucciones(self) -> None:
        from hermes.tools.guide import instrucciones

        self.assertIn("`system_control`", await self.guide())
        self.assertIn("system_control", INSTRUCTIONS)
        self.assertNotIn("system_control", instrucciones(frozenset({"system_control"})))

    def test_supervisor_remite(self) -> None:
        self.assertIn('hermes_guide("system_control")', _GUIDE["supervisor"])


class TestTemaSystemControlTramo2(unittest.IsolatedAsyncioTestCase):
    """Spec 022, FR-020 (tramo 2): el tema `system_control` añade aplicar
    sugerencias (traducción, rechazos, arreglos automáticos), los chequeos y
    el healthcheck por la tabla, plugins, Docker (con el aviso de la red),
    placas y NTP; alias `suggestions` y `fixups`; `diagnostics` ya no dice que
    Hermes nunca aplica una sugerencia y remite a la tool (FR-012); la tabla
    de la genérica da los chequeos como `confirm`.

    Control negativo: quitar `targets_hermes` del tema → cae su subtest;
    devolver a `diagnostics` la frase «NUNCA aplica» → cae
    `test_diagnostics_dice_la_verdad` (y su huella)."""

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_y_alias(self) -> None:
        texto = await self.guide("system_control")
        for palabra in ("sv_apply_resolution_suggestion", "resolution_fixes",
                        "effect", "reversible", "clear_full_backup",
                        "also_auto_applied", "suggestion_changed", "no_fixup",
                        "unknown_effect", "not_allowed", "adopt_data_disk",
                        "targets_hermes", "/resolution/check/{check}/run",
                        "/resolution/healthcheck", "/dns/options", "/docker/options",
                        "sin red", "/docker/registries", "/os/boards/green",
                        "/time/options", "observer"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, texto)
        for alias in ("suggestions", "fixups", "FIXUPS"):
            with self.subTest(alias=alias):
                self.assertEqual(await self.guide(alias), texto)

    def test_diagnostics_dice_la_verdad(self) -> None:
        texto = _GUIDE["diagnostics"]
        self.assertNotIn("NUNCA aplica", texto)
        self.assertIn("sv_apply_resolution_suggestion", texto)

    async def test_chequeos_confirm_en_la_tabla(self) -> None:
        texto = await self.guide("generic_commands", search="resolution")
        for ruta in ("/resolution/check/{check}/run", "/resolution/check/{check}/options",
                     "/resolution/healthcheck"):
            with self.subTest(ruta=ruta):
                linea = next(l for l in texto.splitlines() if ruta in l)
                self.assertIn("confirm", linea)


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


class TestTemaBlueprints(unittest.IsolatedAsyncioTestCase):
    """Spec 017 (FR-014, T011): el tema `blueprints` existe con su alias, el
    índice lo lista y cada tema de una familia de la 017 (`blueprints` y,
    cuando exista, `automation_assist`) nombra TODAS las tools registradas
    de su familia. Genérico: los tramos B, C y D no tienen que tocar este
    test, solo el texto de los temas.

    Control negativo comprobado: quitar `ha_delete_blueprint` del tema → cae
    `test_nombra_cada_tool_de_las_familias_de_la_017` nombrándola.
    """

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_y_alias(self) -> None:
        tema = _GUIDE["blueprints"]
        for alias in ("blueprints", "blueprint", "BLUEPRINT"):
            self.assertEqual(await self.guide(alias), tema, alias)
        for clave in ("use_blueprint", "fs_write_file", "blueprint_in_use",
                      "already_exists", "allow_override", "saved: false"):
            self.assertIn(clave, tema)

    async def test_indice(self) -> None:
        self.assertIn("`blueprints`", await self.guide())

    def test_importar_avisa_de_texto_de_terceros(self) -> None:
        """Tramo B (T022): la parte de importar dice que HA descarga, que es
        texto de terceros y qué hacer con `content_changed`. Control negativo
        comprobado: sin el párrafo de importar → cae."""
        tema = _GUIDE["blueprints"]
        for clave in ("ha_import_blueprint", "third-party", "_third_party_text",
                      "content_changed", "content_sha256", "blueprint_too_large",
                      "invalid_blueprint", "Hermes no abre la URL"):
            self.assertIn(clave, tema)

    def test_nombra_cada_tool_de_las_familias_de_la_017(self) -> None:
        from hermes.tool_families import FAMILIAS
        from tests.test_tools_registration import _do_register

        completo = set(_do_register().tools)
        for familia in ("blueprints", "automation_assist"):
            if familia not in FAMILIAS:
                continue
            with self.subTest(familia=familia):
                de_la_familia = sorted(completo - set(_do_register([familia]).tools))
                self.assertTrue(de_la_familia)
                faltan = [n for n in de_la_familia if f"`{n}" not in _GUIDE[familia]]
                self.assertEqual(faltan, [])


class TestTemaAutomationAssist(unittest.IsolatedAsyncioTestCase):
    """Spec 017, tramo C (FR-014, T033): el tema `automation_assist` existe
    con sus alias (el tramo D añade `wait_for_trigger`), el índice lo lista y
    trae las dos recetas. Que nombre cada tool de la familia lo cubre
    `TestTemaBlueprints.test_nombra_cada_tool_de_las_familias_de_la_017`.
    Control negativo comprobado: quitar el alias `targets` → cae
    `test_tema_y_alias`."""

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_y_alias(self) -> None:
        tema = _GUIDE["automation_assist"]
        for alias in ("automation_assist", "device_automation", "targets", "TARGETS"):
            self.assertEqual(await self.guide(alias), tema, alias)
        for clave in ("include_capabilities", "capabilities_truncated", "extra_fields",
                      "AUTOMATIZACIÓN PARA UN DISPOSITIVO", "ha_validate_config",
                      '"trigger": "light.turned_on", "target"', "exclude",
                      "ha_version_unsupported", "invalid_argument"):
            self.assertIn(clave, tema)

    async def test_indice(self) -> None:
        self.assertIn("`automation_assist`", await self.guide())

    async def test_espera_de_trigger(self) -> None:
        """Tramo D (T046): la espera de trigger con su alias, frente a
        `ha_wait_for_event`, los rechazados y qué pasa con `events` apagada;
        el tema `automations` dice que la vista previa valida. Control
        negativo comprobado: sin el párrafo de la espera → cae."""
        tema = _GUIDE["automation_assist"]
        self.assertEqual(await self.guide("wait_for_trigger"), tema)
        for clave in ("ha_wait_for_trigger", "ha_wait_for_event", "trigger_not_allowed",
                      "webhook", "conversation", "samsungtv", "invalid_trigger",
                      "ha_cancel_wait", "ha_list_active_waits", "`events`",
                      "wait_for_event_max_seconds"):
            self.assertIn(clave, tema)
        automatizaciones = _GUIDE["automations"]
        for clave in ("invalid_config", "validation_unavailable", "not_validated",
                      "`blueprints`", "`automation_assist`"):
            self.assertIn(clave, automatizaciones)


class TestTemaConversacion(unittest.IsolatedAsyncioTestCase):
    """Spec 023, T012 (FR-013): tema `conversation` con las cuatro tools, que
    procesar ejecuta y confirma, el aviso del agente externo, lo que va por
    las genéricas y lo que sigue rechazado; sus alias; el índice lo nombra y
    las instrucciones del servidor solo con la familia activa; los temas que
    la 023 no toca no cambian. Desde la integración con la 021 nombra sus
    tools de exposición, que existen de verdad (principio V).

    Control negativo comprobado: sin `@TEMA_CONVERSACION@` en las
    instrucciones → cae `test_indice_e_instrucciones`."""

    # sha256 (16 hex) de temas que la 023 no toca. La de `supervisor` es la
    # de la rama del programa al integrar: la 022 y la 032 le añadieron su
    # remisión a `system_control` y `host_control` después de la base de la
    # 023, que no lo toca (la misma huella que `TestTemaAppStore`).
    _HUELLAS = {
        "services": "e7b494a2e8ad587e",
        "security": "157ee929e7db08ae",
        # La convergencia de la 025 (T047) añade a `generic_commands` el rechazo
        # `redacted_value_in_payload` de las cargas con el marcador de redacción
        # (su CHANGELOG lo dice); huella recalculada al integrar la 025.
        "generic_commands": "55325dfe9602e63b",
        "app_store": "f02491e7f0e6c93c",
        "workflows": "53b81454a6708b9a",
        "supervisor": "dc38e81c61a06932",
    }

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_tema_con_contenido(self) -> None:
        texto = await self.guide("conversation")
        self.assertIs(texto, _GUIDE["conversation"])
        plano = " ".join(texto.split())
        for palabra in ("ha_list_conversation_agents", "ha_list_conversation_sentences",
                        "ha_debug_conversation", "ha_process_conversation",
                        "confirmation_token", "SIN ejecutarlas", "SIEMPRE EN DOS PASOS",
                        "Hermes no puede predecir qué hará", "LLM en la nube",
                        "local: \"unknown\"", "outcome_unknown", "PUDO ejecutarse",
                        "assist_pipeline/pipeline/list", "ai_task/preferences/set",
                        "allow_automatic_evaluation", "assist_satellite/set_wake_words",
                        "assist_pipeline/pipeline/create", "EXPUESTAS",
                        "ha_call_service_response"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, plano)
        # `assist_pipeline/run` solo aparece como no disponible.
        self.assertIn("No disponibles: `assist_pipeline/run`", plano)
        self.assertEqual(plano.count("assist_pipeline/run"), 1)

    async def test_no_nombra_tools_que_no_existen(self) -> None:
        from hermes.tools.assistant_exposure import register as reg_exposicion
        from hermes.tools.conversation import register as reg_conversation
        from unittest.mock import MagicMock

        mcp = _MockMCP()
        reg_conversation(mcp, MagicMock(), response_max_bytes=131072)
        reg_exposicion(mcp, MagicMock(), response_max_bytes=131072)
        texto = _GUIDE["conversation"]
        # Integración con la 021: la referencia cruzada a la exposición nombra
        # sus tools, y tienen que existir. Control negativo comprobado: sin
        # registrar `assistant_exposure`, caen las tres nombrándolas.
        for nombre in ("ha_list_conversation_agents", "ha_list_conversation_sentences",
                       "ha_debug_conversation", "ha_process_conversation",
                       "ha_list_exposed_entities", "ha_set_entity_exposure",
                       "ha_set_expose_new_entities"):
            with self.subTest(nombre=nombre):
                self.assertIn(nombre, texto)
                self.assertIn(nombre, mcp.tools)
        self.assertIn('hermes_guide("assistant_exposure")', texto)

    async def test_alias(self) -> None:
        texto = _GUIDE["conversation"]
        for alias in ("assist", "voice", "conversation_agents", "sentences", "intents",
                      "pipelines", "assist_pipeline", "tts", "stt", "wake_word",
                      "satellite", "ai_task", "llm", "ASSIST"):
            with self.subTest(alias=alias):
                self.assertIs(await self.guide(alias), texto)

    async def test_indice_e_instrucciones(self) -> None:
        from hermes.tools.guide import instrucciones

        self.assertIn("`conversation`", await self.guide())
        self.assertIn(", conversation,", INSTRUCTIONS)
        sin = instrucciones(frozenset({"conversation"}))
        self.assertNotIn("conversation", sin)
        self.assertNotIn("@", sin)
        self.assertIn("app_store, security", sin)

    def test_los_temas_que_no_toca_no_cambian(self) -> None:
        import hashlib

        for tema, huella in self._HUELLAS.items():
            with self.subTest(tema=tema):
                real = hashlib.sha256(_GUIDE[tema].encode()).hexdigest()[:16]
                self.assertEqual(real, huella)



class TestTemasDeLa024(unittest.IsolatedAsyncioTestCase):
    """Spec 024, tramo 1 (FR-016, T010): temas `cameras` y `core_minor` (la
    parte de CAP-065, 066, 067 y 072) con sus alias; el índice los nombra;
    las instrucciones del servidor nombran `cameras` solo con su familia
    activa; los demás temas no cambian (el índice sí, a propósito).

    Control negativo comprobado: sin `@TEMA_CAMARAS@` en las instrucciones →
    cae `test_instrucciones_con_y_sin_la_familia`."""

    # sha256 (16 hex) de cada tema antes de la 024: el tramo 1 solo añade
    # temas (y dos líneas al índice, que no está aquí). El tramo 2 añade a
    # `lovelace` la sección «Restablecer un dashboard» (FR-016, la única
    # que cambia a propósito; la convergencia, T033 y T034, le añade
    # `strategy` y `dashboards_unavailable`): huella recalculada.
    # Al integrar en la rama del programa se recalculan `backups`,
    # `diagnostics`, `recorder`, `supervisor` y `system_status`: la 024 no los
    # toca, pero la 020, 021, 022, 031 y 032, integradas antes, sí (son las
    # huellas de la rama del programa, sin cambio de la 024).
    _HUELLAS = {
        "app_store": "f02491e7f0e6c93c",
        "automation_assist": "d360de0f7fd1deb5",
        "automations": "d27ee3c45bc13171",
        "backups": "3e685f47171224e7",
        "blueprints": "f0b99d3c0a4103e4",
        # El cierre de seguridad de la 1.2.0 cambia `config_entries` (las
        # opciones salen tapadas y se rechaza el marcador) y `generic_commands`
        # (la URL con `usuario:***@`); su CHANGELOG lo dice.
        "config_entries": "a37e88797523ec8e",
        "core_diagnostics": "29db774e2062ebde",
        "data": "c77e3e6782cc89a7",
        "diagnostics": "838ff4a3a3eeaddb",
        "events": "3765a76095ece40f",
        "filesystem": "b5902d6d0ff666c1",
        # La convergencia de la 025 (T047) añade a `generic_commands` el rechazo
        # `redacted_value_in_payload` de las cargas con el marcador de redacción
        # (su CHANGELOG lo dice); huella recalculada al integrar la 025.
        "generic_commands": "55325dfe9602e63b",
        "helpers": "c99850e94eb5c996",
        "integration_flows": "5df1b039b66924d5",
        "lovelace": "04bebf2041d378db",
        # La convergencia de la 026 (T033) cambia `marketplace` (D-29 y la
        # remisión a `marketplace_manage`); su CHANGELOG lo dice. Huella
        # recalculada al integrar la 026.
        "marketplace": "f49c5f1c9d78b51b",
        "mounts": "df26cd22a86efe39",
        "recorder": "690516ce68c93d6c",
        "registries": "42894b4111cb8c80",
        "repair_flows": "49f0ab3db2c30057",
        "security": "157ee929e7db08ae",
        "services": "e7b494a2e8ad587e",
        "supervisor": "dc38e81c61a06932",
        "system_diagnostics": "50509e336b5ca215",
        "system_status": "f6401ab7737759f6",
        "updates": "bde22d629e7468f4",
        "workflows": "53b81454a6708b9a",
    }

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_cameras_y_alias(self) -> None:
        tema = _GUIDE["cameras"]
        for alias in ("cameras", "camera", "cámaras", "camaras", "snapshot",
                      "image", "imagen", "CAMERA"):
            with self.subTest(alias=alias):
                self.assertIs(await self.guide(alias), tema)
        plano = " ".join(tema.split())
        for clave in ("`ha_get_camera_snapshot", "`ha_get_image_entity", "PRIVACIDAD",
                      "interior de la casa", "SOLO ESCALA JPEG", "2 MiB",
                      "image_too_large", "camera_unavailable", "unsupported_content_type",
                      "access_token", "camera/get_prefs", "camera/update_prefs",
                      '{"entity_id": "camera.entrada"}', "`cameras`"):
            with self.subTest(clave=clave):
                self.assertIn(clave, plano)

    async def test_core_minor_y_alias(self) -> None:
        tema = _GUIDE["core_minor"]
        for alias in ("core_minor", "minor", "menores", "MINOR"):
            with self.subTest(alias=alias):
                self.assertIs(await self.guide(alias), tema)
        plano = " ".join(tema.split())
        for clave in ("calendar/event/update", "calendar/event/delete", "todo/item/move",
                      "sale a internet", "tag/list", "tag/create",
                      "media_source/browse_media", "media_source/search_media",
                      "`thumbnail`", "TAPADA", "authSig", "media_source/resolve_media",
                      "DENEGADO", "media_source/local_source/remove", "IRREVERSIBLE",
                      "image/list", "image/delete", "Subir una imagen NO se puede",
                      "image/create"):
            with self.subTest(clave=clave):
                self.assertIn(clave, plano)

    async def test_indice(self) -> None:
        indice = await self.guide()
        self.assertIn("`cameras`", indice)
        self.assertIn("`core_minor`", indice)

    def test_instrucciones_con_y_sin_la_familia(self) -> None:
        from hermes.tools.guide import instrucciones

        self.assertIn("lovelace, cameras, marketplace", INSTRUCTIONS)
        sin = instrucciones(frozenset({"cameras"}))
        self.assertNotIn("cameras", sin)
        self.assertNotIn("@", sin)
        self.assertIn("lovelace, marketplace", sin)

    def test_nombra_cada_tool_de_la_familia(self) -> None:
        from tests.test_tools_registration import _do_register

        de_la_familia = sorted(set(_do_register().tools) - set(_do_register(["cameras"]).tools))
        self.assertEqual(de_la_familia, ["ha_get_camera_snapshot", "ha_get_image_entity"])
        self.assertEqual([n for n in de_la_familia if f"`{n}" not in _GUIDE["cameras"]], [])

    async def test_preferencias_en_la_tabla(self) -> None:
        texto = await self.guide("generic_commands", search="camera/")
        linea = next(l for l in texto.splitlines() if "camera/update_prefs" in l)
        self.assertIn("confirm", linea)

    def test_los_demas_temas_no_cambian(self) -> None:
        import hashlib

        for tema, huella in self._HUELLAS.items():
            with self.subTest(tema=tema):
                real = hashlib.sha256(_GUIDE[tema].encode()).hexdigest()[:16]
                self.assertEqual(real, huella)


class TestTemasDeLa024Tramo2(unittest.IsolatedAsyncioTestCase):
    """Spec 024, tramo 2 (FR-016, FR-020, T025): la sección «Restablecer» del
    tema `lovelace`, `core_minor` completo (CAP-070, 071 y 073) y sus alias;
    la búsqueda en la tabla da `lovelace/config/delete` como `dedicated`.

    Control negativo comprobado: sin la sección en `lovelace` → caen
    `test_lovelace_restablecer` y las huellas de los temas."""

    def setUp(self) -> None:
        self.mcp = _MockMCP()
        register(self.mcp)
        self.guide = self.mcp.tools["hermes_guide"]

    async def test_lovelace_restablecer(self) -> None:
        tema = _GUIDE["lovelace"]
        for alias in ("reset", "restablecer", "RESET"):
            with self.subTest(alias=alias):
                self.assertIs(await self.guide(alias), tema)
        plano = " ".join(tema.split())
        for clave in ("`ha_reset_lovelace_dashboard_config", "`dashboard_reset`",
                      "IRREVERSIBLE", "autogenerada", "ha_get_lovelace_dashboard(url_path)",
                      "cannot_reset_default_dashboard", "default_panel_unknown",
                      "dashboard_changed", "yaml_mode_dashboard", "nothing_to_reset",
                      "panel por defecto", "Con la familia desactivada"):
            with self.subTest(clave=clave):
                self.assertIn(clave, plano)

    async def test_core_minor_completo(self) -> None:
        tema = _GUIDE["core_minor"]
        for alias in ("webhooks", "themes", "temas"):
            with self.subTest(alias=alias):
                self.assertIs(await self.guide(alias), tema)
        plano = " ".join(tema.split())
        for clave in ("frontend/get_themes", "webhook/list", "`webhook_id` sale TAPADO",
                      "trace/contexts", "vacuum/get_segments", "salir a internet",
                      "radio_frequency/list", "config/area_registry/reorder",
                      "config/floor_registry/reorder",
                      "config/entity_registry/get_automatic_entity_ids",
                      "config/entity_registry/settings/update",
                      "config/device_registry/list_linked_devices",
                      "application_credentials/list", "application_credentials/config_entry",
                      "`client_secret` NUNCA sale", "Crear, cambiar y borrar credenciales NO se puede",
                      "`ha_reset_lovelace_dashboard_config`"):
            with self.subTest(clave=clave):
                self.assertIn(clave, plano)

    async def test_busqueda_da_la_dedicada(self) -> None:
        texto = await self.guide("generic_commands", search="lovelace/config/delete")
        linea = next(l for l in texto.splitlines() if l.startswith("| `lovelace/config/delete`"))
        self.assertIn("dedicated", linea)
        self.assertIn("ha_reset_lovelace_dashboard_config", linea)

    def test_nombra_la_tool_de_la_familia(self) -> None:
        from tests.test_tools_registration import _do_register

        de_la_familia = sorted(
            set(_do_register().tools) - set(_do_register(["dashboard_reset"]).tools))
        self.assertEqual(de_la_familia, ["ha_reset_lovelace_dashboard_config"])
        self.assertIn(f"`{de_la_familia[0]}", _GUIDE["lovelace"])


if __name__ == "__main__":
    unittest.main()
