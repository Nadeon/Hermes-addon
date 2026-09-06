import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from hermes import security


class TestSecurityConfirmationTokens(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def test_confirmation_token_lifecycle(self) -> None:
        payload = {
            "automation_id": "automation.test",
            "config": {"alias": "Test automation"},
        }

        token_response = await security.create_confirmation_token(
            "ha_create_or_update_automation",
            payload,
            preview={"alias": "Test automation"},
        )

        self.assertIn("confirmation_token", token_response)
        token = token_response["confirmation_token"]
        token_file = security.CONFIRMATIONS_DIR / f"{token}.json"
        self.assertTrue(token_file.exists())

        valid, error = await security.validate_confirmation_token(
            token,
            "ha_create_or_update_automation",
            payload,
        )
        self.assertTrue(valid)
        self.assertEqual(error, "")

        await security.complete_confirmation_token(
            token,
            success=True,
            result={"status": "ok"},
        )

        stored = json.loads(token_file.read_text(encoding="utf-8"))
        self.assertEqual(stored.get("state"), "completed")
        self.assertEqual(stored.get("cached_result"), {"status": "ok"})

    async def test_confirmation_token_mismatch(self) -> None:
        payload = {
            "automation_id": "automation.test",
            "config": {"alias": "Test automation"},
        }

        token_response = await security.create_confirmation_token(
            "ha_create_or_update_automation",
            payload,
        )
        token = token_response["confirmation_token"]

        invalid_payload = {
            "automation_id": "automation.other",
            "config": {"alias": "Test automation"},
        }

        valid, error = await security.validate_confirmation_token(
            token,
            "ha_create_or_update_automation",
            invalid_payload,
        )
        self.assertFalse(valid)
        self.assertIn("does not match", error)

    async def test_expired_confirmation_token_is_cleaned_up(self) -> None:
        payload = {
            "automation_id": "automation.test",
            "config": {"alias": "Test automation"},
        }

        token_response = await security.create_confirmation_token(
            "ha_create_or_update_automation",
            payload,
        )
        token = token_response["confirmation_token"]
        token_file = security.CONFIRMATIONS_DIR / f"{token}.json"
        data = json.loads(token_file.read_text(encoding="utf-8"))
        data["expires_at"] = 0
        token_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        cleaned = await security.cleanup_expired_confirmations()
        self.assertEqual(cleaned, 1)
        self.assertFalse(token_file.exists())

class TestUsedTokenCannotBeReused(unittest.IsolatedAsyncioTestCase):
    """Un token de confirmación vale UNA vez. Nadie lo comprobaba.

    Se verificó desactivando la guarda (`state == "completed"` → nunca) y
    corriendo la suite entera: **0 tests fallaban**. Un token consumido volvía
    a autorizar su acción y no había red que lo detectara.

    Importa porque el token es lo que separa «Claude te enseña qué va a hacer»
    de «Claude lo hace». Si se puede reutilizar, una acción confirmada una vez
    queda autorizada para siempre: reiniciar el host, borrar una automatización,
    ejecutar un servicio vetado.
    """

    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self.args = {"entity_id": "automation.prueba"}

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def _token(self) -> str:
        r = await security.create_confirmation_token("ha_delete_automation", self.args)
        return r["confirmation_token"]

    async def test_a_consumed_token_is_refused(self) -> None:
        token = await self._token()
        valido, _ = await security.validate_confirmation_token(
            token, "ha_delete_automation", self.args)
        self.assertTrue(valido)
        await security.complete_confirmation_token(token, success=True, result={})

        valido, error = await security.validate_confirmation_token(
            token, "ha_delete_automation", self.args)
        self.assertFalse(valido, "un token ya usado volvió a autorizar la acción")
        self.assertIn("already used", error)

    async def test_a_token_consumed_after_a_failure_is_also_refused(self) -> None:
        """Que la acción fallara no devuelve el token al bote."""
        token = await self._token()
        await security.validate_confirmation_token(
            token, "ha_delete_automation", self.args)
        await security.complete_confirmation_token(
            token, success=False, error="lo que sea")

        valido, _ = await security.validate_confirmation_token(
            token, "ha_delete_automation", self.args)
        self.assertFalse(valido)

    async def test_a_fresh_token_still_works_after_another_was_used(self) -> None:
        """Control negativo: la guarda no puede bloquear tokens nuevos."""
        primero = await self._token()
        await security.validate_confirmation_token(
            primero, "ha_delete_automation", self.args)
        await security.complete_confirmation_token(primero, success=True, result={})

        segundo = await self._token()
        valido, error = await security.validate_confirmation_token(
            segundo, "ha_delete_automation", self.args)
        self.assertTrue(valido, error)


class TestExpiredTokenIsRefused(unittest.IsolatedAsyncioTestCase):
    """Un token caduca. Tampoco lo comprobaba nadie.

    Había un test de la RECOGIDA de tokens caducados, que es otra cosa: el
    recolector pasa cada cierto tiempo, y entre medias el fichero sigue en
    disco. Lo que importa es que `validate_confirmation_token` lo rechace
    aunque siga ahí.

    Verificado antes de escribirlo: quitando la comprobación de caducidad,
    los 913 tests seguían en verde.
    """

    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self.args = {"entity_id": "automation.prueba"}

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def _token_caducado(self) -> str:
        import time

        r = await security.create_confirmation_token("ha_delete_automation", self.args)
        token = r["confirmation_token"]
        ruta = next(Path(self.temp_dir.name).glob("*.json"))
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        datos["expires_at"] = time.time() - 1
        ruta.write_text(json.dumps(datos), encoding="utf-8")
        return token

    async def test_an_expired_token_is_refused(self) -> None:
        token = await self._token_caducado()
        valido, error = await security.validate_confirmation_token(
            token, "ha_delete_automation", self.args)
        self.assertFalse(valido, "un token caducado autorizó la acción")
        self.assertIn("expired", error)

    async def test_a_token_that_has_not_expired_is_accepted(self) -> None:
        """Control negativo: no vale rechazarlos todos."""
        r = await security.create_confirmation_token("ha_delete_automation", self.args)
        valido, error = await security.validate_confirmation_token(
            r["confirmation_token"], "ha_delete_automation", self.args)
        self.assertTrue(valido, error)
