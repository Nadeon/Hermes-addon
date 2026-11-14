"""Tools de notificaciones persistentes (spec 012, tramo B; T024).

`ha_list_persistent_notifications` y `ha_dismiss_persistent_notification`
con Home Assistant simulado (`AsyncMock` de `ws_send` y `call_service`).
Datos ficticios: ids `aviso1`/`aviso2`, el centinela `centinela-012` y un JWT
de prueba, que no pueden salir en ninguna respuesta, en el log de Hermes ni
en los ficheros de token.

Controles negativos (T033 e), comprobados y con recuentos en el commit: no
releer al confirmar → cae `test_desaparecida_entre_medias`; guardar el
mensaje sin redactar en la vista previa → cae
`test_vista_previa_y_tokens_sin_centinela`.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from structlog.testing import capture_logs

import hermes.security as security
import hermes.tools.persistent_notifications as mod
from hermes.ha import HAConnectionError

_CENTINELA = "centinela-012"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJjZW50aW5lbGEifQ.c2lnbmF0dXJhLWZpY3RpY2lh"


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _nota(nid: str, creada: str, mensaje: str = "Hay una actualización",
          titulo: str = "Aviso") -> dict[str, Any]:
    return {"notification_id": nid, "title": titulo, "message": mensaje,
            "created_at": creada}


class _Base(unittest.IsolatedAsyncioTestCase):
    max_bytes = 131_072

    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self.notas: list[Any] = [
            _nota("aviso1", "2026-11-14T10:00:00+00:00"),
            _nota("aviso2", "2026-11-14T12:00:00+00:00",
                  mensaje=f"Clave password={_CENTINELA} y {_JWT}"),
        ]
        self.lecturas: list[Any] = []
        self.fallo: HAConnectionError | None = None
        self.ha = MagicMock()
        self.ha.wait_ready = AsyncMock(return_value=True)
        self.ha.ws_send = AsyncMock(side_effect=self._ws_send)
        self.ha.call_service = AsyncMock(return_value=[])
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha, response_max_bytes=self.max_bytes)
        self.t = self.mcp.tools

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def _ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        assert payload == {"type": "persistent_notification/get"}, payload
        if self.fallo is not None:
            raise self.fallo
        # Cada lectura puede devolver una lista distinta (cola `lecturas`).
        if self.lecturas:
            return self.lecturas.pop(0)
        return self.notas

    def ficheros_de_tokens(self) -> str:
        return "".join(p.read_text(encoding="utf-8") for p in Path(self.temp_dir.name).glob("*"))


class TestListPersistentNotifications(_Base):
    async def test_lista_ordenada_y_redactada(self) -> None:
        with capture_logs() as logs:
            r = await self.t["ha_list_persistent_notifications"]()
        self.assertEqual((r["count"], r["returned"], r["truncated"]), (2, 2, False))
        self.assertEqual([n["notification_id"] for n in r["items"]], ["aviso2", "aviso1"])
        self.assertEqual(sorted(r["items"][1]), ["created_at", "message", "notification_id",
                                                 "title"])
        self.assertEqual(r["_third_party_text"]["fields"], ["title", "message"])
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertNotIn(_JWT, json.dumps(r))
        self.assertNotIn(_CENTINELA, str(logs))
        self.assertNotIn("aviso", str(logs))

    async def test_sobre_y_recorte(self) -> None:
        self.notas = [_nota(f"n{i}", f"2026-11-14T10:{i:02d}:00+00:00", mensaje="x" * 2000)
                      for i in range(60)]
        mcp = DummyMCP()
        mod.register(mcp, self.ha, response_max_bytes=20_000)
        r = await mcp.tools["ha_list_persistent_notifications"]()
        self.assertTrue(r["truncated"])
        self.assertEqual(r["count"], 60)
        self.assertEqual(r["returned"], len(r["items"]))
        self.assertLess(r["returned"], 60)
        self.assertEqual(r["items"][0]["notification_id"], "n59")
        self.assertIn("_response_limit", r)
        self.assertLessEqual(len(json.dumps(r, ensure_ascii=False).encode()), 20_000)

    async def test_respuesta_que_no_es_lista(self) -> None:
        self.notas = {"raro": True}
        r = await self.t["ha_list_persistent_notifications"]()
        self.assertIn("error", r)


class TestDismissPersistentNotification(_Base):
    async def test_id_vacio(self) -> None:
        for nid in ("", "   ", None, "x" * 256):
            with self.subTest(nid=nid):
                r = await self.t["ha_dismiss_persistent_notification"](notification_id=nid)
                self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()

    async def test_inexistente_sin_token(self) -> None:
        r = await self.t["ha_dismiss_persistent_notification"](notification_id="nada")
        self.assertEqual((r["error"], r["notification_id"]), ("not_found", "nada"))
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.ficheros_de_tokens(), "")

    async def test_vista_previa(self) -> None:
        r = await self.t["ha_dismiss_persistent_notification"](notification_id="aviso1")
        p = r["preview"]
        self.assertEqual((p["notification_id"], p["title"], p["message"]),
                         ("aviso1", "Aviso", "Hay una actualización"))
        self.assertFalse(p["message_truncated"])
        self.assertEqual(p["created_at"], "2026-11-14T10:00:00+00:00")
        self.assertIn("cannot be restored", p["effect"])
        self.assertIn("confirmation_token", r)
        self.ha.call_service.assert_not_awaited()

    async def test_mensaje_largo_recortado(self) -> None:
        self.notas = [_nota("largo", "2026-11-14T10:00:00+00:00", mensaje="m" * 5000)]
        r = await self.t["ha_dismiss_persistent_notification"](notification_id="largo")
        self.assertEqual(len(r["preview"]["message"]), 2000)
        self.assertTrue(r["preview"]["message_truncated"])

    async def test_vista_previa_y_tokens_sin_centinela(self) -> None:
        r = await self.t["ha_dismiss_persistent_notification"](notification_id="aviso2")
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertNotIn(_JWT, json.dumps(r))
        self.assertNotIn(_CENTINELA, self.ficheros_de_tokens())
        self.assertNotIn(_JWT, self.ficheros_de_tokens())

    async def test_confirmacion(self) -> None:
        r = await self.t["ha_dismiss_persistent_notification"](notification_id="aviso1")
        with capture_logs() as logs:
            r = await self.t["ha_dismiss_persistent_notification"](
                notification_id="aviso1", confirmation_token=r["confirmation_token"])
        self.assertEqual(r, {"result": "ok"})
        self.ha.call_service.assert_awaited_once()
        args, kwargs = self.ha.call_service.call_args
        self.assertEqual(args, ("persistent_notification", "dismiss",
                                {"notification_id": "aviso1"}))
        # Dos lecturas: la de la vista previa y la relectura al confirmar.
        self.assertEqual(self.ha.ws_send.await_count, 2)
        self.assertNotIn("aviso1", str(logs))

    async def test_desaparecida_entre_medias(self) -> None:
        r = await self.t["ha_dismiss_persistent_notification"](notification_id="aviso1")
        self.lecturas = [[_nota("aviso2", "2026-11-14T12:00:00+00:00")]]
        r = await self.t["ha_dismiss_persistent_notification"](
            notification_id="aviso1", confirmation_token=r["confirmation_token"])
        self.assertEqual(r, {"result": "already_dismissed"})
        self.ha.call_service.assert_not_awaited()

    async def test_token_con_otro_id(self) -> None:
        r = await self.t["ha_dismiss_persistent_notification"](notification_id="aviso1")
        r = await self.t["ha_dismiss_persistent_notification"](
            notification_id="aviso2", confirmation_token=r["confirmation_token"])
        self.assertIn("error", r)
        self.ha.call_service.assert_not_awaited()

    async def test_token_reutilizado(self) -> None:
        r = await self.t["ha_dismiss_persistent_notification"](notification_id="aviso1")
        token = r["confirmation_token"]
        await self.t["ha_dismiss_persistent_notification"](
            notification_id="aviso1", confirmation_token=token)
        r = await self.t["ha_dismiss_persistent_notification"](
            notification_id="aviso1", confirmation_token=token)
        self.assertIn("error", r)
        self.ha.call_service.assert_awaited_once()

    async def test_lectura_previa_que_falla(self) -> None:
        self.fallo = HAConnectionError(f"caída token: {_CENTINELA}")
        r = await self.t["ha_dismiss_persistent_notification"](notification_id="aviso1")
        self.assertEqual(r["error"], "preview_unavailable")
        self.assertNotIn(_CENTINELA, str(r))
        self.assertEqual(self.ficheros_de_tokens(), "")


if __name__ == "__main__":
    unittest.main()
