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


if __name__ == "__main__":
    unittest.main()
