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
        for alias in ("core_diagnostics", "logs", "log", "LOGS"):
            self.assertEqual(await self.guide(alias), tema, alias)
        for clave in ("duplicate_log_file", "NOTSET", "persistence", "error_log_unavailable"):
            self.assertIn(clave, tema)

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


if __name__ == "__main__":
    unittest.main()
