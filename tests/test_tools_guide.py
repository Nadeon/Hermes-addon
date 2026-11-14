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



if __name__ == "__main__":
    unittest.main()
