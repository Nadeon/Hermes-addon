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

    async def test_malformed_token_never_leaves_the_confirmations_dir(self) -> None:
        """Un token como `../options` no puede convertirse en una ruta.

        `validate_confirmation_token` construía la ruta con el token tal cual
        y borraba el fichero que encontraba si no parecía un token vigente:
        cualquier `.json` alcanzable desde CONFIRMATIONS_DIR se podía borrar
        con solo pasarlo como confirmation_token a una tool destructiva.
        """
        base = Path(self.temp_dir.name)
        security.CONFIRMATIONS_DIR = base / "confirmations"
        security.CONFIRMATIONS_DIR.mkdir()
        sibling = base / "options.json"
        sibling.write_text('{"auth_password": "x"}', encoding="utf-8")

        forged = ("../options", "..\\options", "options", "", "x" * 36,
                  "00000000-0000-0000-0000-000000000000/../../options")
        for token in forged:
            valid, error = await security.validate_confirmation_token(
                token, "fs_write_file", {"path": "a.yaml"}
            )
            self.assertFalse(valid, token)
            self.assertIn("malformed", error, token)
            await security.complete_confirmation_token(token, success=False, error="e")

        self.assertTrue(sibling.exists(), "el fichero vecino fue borrado")
        self.assertEqual(sorted(p.name for p in base.iterdir()),
                         ["confirmations", "options.json"])

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


class TestCanonicalizacionInyectiva(unittest.TestCase):
    """El action_hash no puede colisionar entre dos acciones distintas.

    Los floats y los bools se serializan con centinelas (`__float__`,
    `__bool__`). Sin escapar las claves del usuario, un dict escrito a mano
    reproducía el centinela y ambas acciones salían con el MISMO action_hash:
    un confirmation_token emitido para una valía para la otra.
    """

    def test_float_y_su_centinela_escrito_a_mano_no_colisionan(self) -> None:
        self.assertNotEqual(
            security.compute_action_hash("t", {"x": 1.5}),
            security.compute_action_hash("t", {"x": {"__float__": "1.5"}}),
        )

    def test_bool_y_su_centinela_escrito_a_mano_no_colisionan(self) -> None:
        self.assertNotEqual(
            security.compute_action_hash("t", {"x": True}),
            security.compute_action_hash("t", {"x": {"__bool__": True}}),
        )

    def test_el_escape_no_colisiona_con_su_propio_prefijo(self) -> None:
        """Escapar con un '_' extra sigue distinguiendo claves vecinas."""
        self.assertNotEqual(
            security.compute_action_hash("t", {"x": {"__float__": "1.5"}}),
            security.compute_action_hash("t", {"x": {"___float__": "1.5"}}),
        )

    def test_hash_sigue_siendo_estable_para_el_mismo_valor(self) -> None:
        """Control negativo: no vale hacer que todo hashee distinto."""
        args = {"entity_id": "light.salon", "brillo": 1.5, "on": True,
                "anidado": {"__raro__": [1, 2.5, False]}}
        self.assertEqual(
            security.compute_action_hash("t", args),
            security.compute_action_hash("t", dict(args)),
        )


class TestConfirmarSoloConToken(unittest.IsolatedAsyncioTestCase):
    """Confirmar sin reenviar el documento grande (spec 007, Hermes 1.1.2).

    Hasta 1.1.1 la confirmación tenía que repetir TODOS los argumentos y el
    token caduca a los 60 s. Un cliente LLM escribe unos 0,4 KB/s: un
    dashboard de 41 KB llegaba a los 104 s y daba «expired». Ahora la vista
    previa guarda los omitibles que declara la tool y la confirmación los
    puede omitir; el action_hash se comprueba sobre los argumentos resultantes.

    Control negativo comprobado: con `security.py` de 1.1.1 (sin `omitibles`
    ni `resolve_confirmation_token`) caen todos los tests de esta clase salvo
    los de compatibilidad (c) y (j); si `resolve_confirmation_token` acepta lo
    guardado sin recalcular el hash sobre los resueltos caen (d) y (e); con un
    `await asyncio.sleep(0)` entre leer el estado y escribir `executing` cae
    (i).
    """

    TOOL = "ha_save_lovelace_dashboard"
    OMITIBLES = ("config",)

    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self.config = {"views": [{"title": "Vista ficticia", "cards": []}]}
        self.args = {"url_path": "panel-ficticio", "config": self.config}

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    def _fichero(self, token: str) -> Path:
        return security.CONFIRMATIONS_DIR / f"{token}.json"

    def _datos(self, token: str) -> dict:
        return json.loads(self._fichero(token).read_text(encoding="utf-8"))

    async def _vista_previa(self, args: dict | None = None) -> dict:
        return await security.create_confirmation_token(
            self.TOOL, dict(args or self.args), preview={"diff": {}},
            omitibles=self.OMITIBLES,
        )

    # (a) qué se guarda
    async def test_a_solo_se_guardan_los_omitibles(self) -> None:
        centinela = "CENTINELA-NO-OMITIBLE-7f3a"
        args = {"url_path": centinela, "config": self.config}
        r = await self._vista_previa(args)
        datos = self._datos(r["confirmation_token"])
        self.assertEqual(datos["stored_args"], {"config": self.config})
        self.assertIsInstance(datos["stored_bytes"], int)
        self.assertNotIn(centinela, self._fichero(r["confirmation_token"]).read_text(
            encoding="utf-8"))

    async def test_a_sin_omitibles_el_fichero_es_como_en_1_1_1(self) -> None:
        r = await security.create_confirmation_token(self.TOOL, self.args)
        datos = self._datos(r["confirmation_token"])
        self.assertEqual(
            set(datos),
            {"token", "action_hash", "expires_at", "state", "tool_name",
             "created_at", "retries"},
        )

    # (b) omitir el documento
    async def test_b_confirmar_sin_el_documento(self) -> None:
        r = await self._vista_previa()
        ok, error, resueltos = await security.resolve_confirmation_token(
            r["confirmation_token"], self.TOOL, {"url_path": "panel-ficticio"},
            omitibles=self.OMITIBLES,
        )
        self.assertTrue(ok, error)
        self.assertEqual(error, "")
        self.assertEqual(resueltos, self.args)
        self.assertEqual(self._datos(r["confirmation_token"])["state"], "executing")

    async def test_b_none_cuenta_como_omision(self) -> None:
        r = await self._vista_previa()
        ok, error, resueltos = await security.resolve_confirmation_token(
            r["confirmation_token"], self.TOOL,
            {"url_path": "panel-ficticio", "config": None},
            omitibles=self.OMITIBLES,
        )
        self.assertTrue(ok, error)
        self.assertEqual(resueltos, self.args)

    # (c) compatibilidad con 1.1.1
    async def test_c_confirmar_con_todos_los_argumentos(self) -> None:
        r = await self._vista_previa()
        ok, error, resueltos = await security.resolve_confirmation_token(
            r["confirmation_token"], self.TOOL, dict(self.args),
            omitibles=self.OMITIBLES,
        )
        self.assertTrue(ok, error)
        self.assertEqual(resueltos, self.args)

    # (d) documento distinto
    async def test_d_documento_distinto_no_vale_y_no_gasta_el_token(self) -> None:
        r = await self._vista_previa()
        otro = {"views": [{"title": "Otra vista", "cards": []}]}
        ok, error, resueltos = await security.resolve_confirmation_token(
            r["confirmation_token"], self.TOOL,
            {"url_path": "panel-ficticio", "config": otro},
            omitibles=self.OMITIBLES,
        )
        self.assertFalse(ok)
        self.assertIn("does not match this action", error)
        self.assertEqual(resueltos, {})
        self.assertEqual(self._datos(r["confirmation_token"])["state"], "pending")

    async def test_d_otro_destino_sin_documento_no_vale(self) -> None:
        r = await self._vista_previa()
        ok, error, _ = await security.resolve_confirmation_token(
            r["confirmation_token"], self.TOOL, {"url_path": "otro-panel"},
            omitibles=self.OMITIBLES,
        )
        self.assertFalse(ok)
        self.assertIn("does not match this action", error)

    # (e) argumento añadido
    async def test_e_argumento_anadido_no_vale(self) -> None:
        r = await self._vista_previa()
        ok, error, _ = await security.resolve_confirmation_token(
            r["confirmation_token"], self.TOOL,
            {"url_path": "panel-ficticio", "remove_top_level_keys": ["title"]},
            omitibles=self.OMITIBLES,
        )
        self.assertFalse(ok)
        self.assertIn("does not match this action", error)
        self.assertEqual(self._datos(r["confirmation_token"])["state"], "pending")

    # (f) otra tool
    async def test_f_token_de_otra_tool_no_vale(self) -> None:
        r = await self._vista_previa()
        ok, error, _ = await security.resolve_confirmation_token(
            r["confirmation_token"], "ha_create_or_update_automation",
            {"url_path": "panel-ficticio"}, omitibles=self.OMITIBLES,
        )
        self.assertFalse(ok)
        self.assertIn("does not match this action", error)

    # (g) omitido sin nada guardado
    async def test_g_omitido_sin_guardar_pide_la_llamada_completa(self) -> None:
        # Un token de 1.1.1: sin `omitibles`, el fichero no tiene stored_args.
        r = await security.create_confirmation_token(self.TOOL, self.args)
        token = r["confirmation_token"]
        ok, error, _ = await security.resolve_confirmation_token(
            token, self.TOOL, {"url_path": "panel-ficticio"},
            omitibles=self.OMITIBLES,
        )
        self.assertFalse(ok)
        self.assertEqual(
            error,
            "confirmation_token has no stored value for: config. "
            "Repeat the call with all its arguments.",
        )
        self.assertEqual(self._datos(token)["state"], "pending")
        ok, error, _ = await security.resolve_confirmation_token(
            token, self.TOOL, dict(self.args), omitibles=self.OMITIBLES,
        )
        self.assertTrue(ok, error)

    # (h) "" y {} son valores, no omisiones
    async def test_h_vacios_no_son_omision(self) -> None:
        for vacio in ("", {}):
            with self.subTest(vacio=vacio):
                args = {"path": "ficticio.yaml", "content": vacio}
                r = await security.create_confirmation_token(
                    "fs_write_file", args, omitibles=("content",))
                self.assertEqual(
                    self._datos(r["confirmation_token"])["stored_args"],
                    {"content": vacio},
                )
                # Confirmar con otro vacío no es omitir: se compara y no casa.
                otro = {} if vacio == "" else ""
                ok, error, _ = await security.resolve_confirmation_token(
                    r["confirmation_token"], "fs_write_file",
                    {"path": "ficticio.yaml", "content": otro},
                    omitibles=("content",),
                )
                self.assertFalse(ok)
                self.assertIn("does not match", error)
                ok, error, resueltos = await security.resolve_confirmation_token(
                    r["confirmation_token"], "fs_write_file",
                    {"path": "ficticio.yaml"}, omitibles=("content",),
                )
                self.assertTrue(ok, error)
                self.assertEqual(resueltos["content"], vacio)

    # (i) dos confirmaciones simultáneas
    async def test_i_dos_confirmaciones_simultaneas_solo_pasa_una(self) -> None:
        """Control negativo: un `await asyncio.sleep(0)` entre leer el estado
        y escribir `executing` deja que las dos corrutinas lean `pending` y
        las dos pasen; este test cae (comprobado)."""
        r = await self._vista_previa()
        token = r["confirmation_token"]
        resultados = await asyncio.gather(
            security.resolve_confirmation_token(
                token, self.TOOL, {"url_path": "panel-ficticio"},
                omitibles=self.OMITIBLES),
            security.resolve_confirmation_token(
                token, self.TOOL, dict(self.args), omitibles=self.OMITIBLES),
        )
        self.assertEqual([ok for ok, _, _ in resultados].count(True), 1)
        perdedor = next(err for ok, err, _ in resultados if not ok)
        self.assertIn("currently being executed", perdedor)

    # (j) validate_confirmation_token sin cambios
    async def test_j_validate_conserva_firma_y_resultados(self) -> None:
        r = await security.create_confirmation_token(self.TOOL, self.args)
        token = r["confirmation_token"]
        self.assertEqual(
            await security.validate_confirmation_token(
                token, self.TOOL, {"url_path": "panel-ficticio"}),
            (False, "confirmation_token does not match this action."),
        )
        self.assertEqual(
            await security.validate_confirmation_token(token, self.TOOL, self.args),
            (True, ""),
        )

    async def test_j_validate_no_omite_aunque_haya_guardado(self) -> None:
        """Las tools sin omitibles siguen exigiendo todos los argumentos."""
        r = await self._vista_previa()
        ok, error = await security.validate_confirmation_token(
            r["confirmation_token"], self.TOOL, {"url_path": "panel-ficticio"})
        self.assertFalse(ok)
        self.assertIn("does not match", error)

    # ── T017: lo que dice la vista previa (FR-007) ──────────────────────────
    async def test_vista_previa_dice_como_confirmar(self) -> None:
        """Control negativo: sin `_pistas_de_confirmacion` cae (comprobado)."""
        r = await self._vista_previa()
        self.assertEqual(r["confirm_with"], ["confirmation_token", "url_path"])
        self.assertEqual(r["omit_on_confirm"], ["config"])
        self.assertEqual(
            r["confirm_hint"],
            "To confirm, call ha_save_lovelace_dashboard again with only "
            "confirmation_token, url_path. config can be omitted: the server "
            "kept the one from this preview. Any argument you do send must be "
            "identical to the preview.",
        )

    async def test_vista_previa_sin_omitibles_no_cambia(self) -> None:
        r = await security.create_confirmation_token(
            self.TOOL, self.args, preview={"diff": {}})
        self.assertEqual(
            set(r), {"confirmation_token", "expires_in_seconds", "preview"})

    # ── T024: disco, tope y log (FR-009…FR-011) ─────────────────────────────
    async def test_completar_borra_el_documento_y_conserva_el_estado(self) -> None:
        """Control negativo: sin los `pop` de `complete_confirmation_token`
        cae (comprobado)."""
        centinela = "CENTINELA-DOCUMENTO-91c2"
        for exito in (True, False):
            with self.subTest(exito=exito):
                args = {"url_path": "panel-ficticio",
                        "config": {"views": [{"title": centinela}]}}
                r = await self._vista_previa(args)
                token = r["confirmation_token"]
                ok, error, _ = await security.resolve_confirmation_token(
                    token, self.TOOL, {"url_path": "panel-ficticio"},
                    omitibles=self.OMITIBLES)
                self.assertTrue(ok, error)
                if exito:
                    await security.complete_confirmation_token(
                        token, success=True, result={"result": "ok"})
                else:
                    await security.complete_confirmation_token(
                        token, success=False, error="fallo ficticio")
                datos = self._datos(token)
                self.assertNotIn("stored_args", datos)
                self.assertNotIn("stored_bytes", datos)
                self.assertEqual(datos["state"], "completed" if exito else "failed")
                if exito:
                    self.assertEqual(datos["cached_result"], {"result": "ok"})
                else:
                    self.assertEqual(datos["cached_error"], "fallo ficticio")
                self.assertNotIn(
                    centinela, self._fichero(token).read_text(encoding="utf-8"))

    async def _caducar(self, token: str) -> None:
        datos = self._datos(token)
        datos["expires_at"] = 0
        self._fichero(token).write_text(json.dumps(datos), encoding="utf-8")

    async def test_resolve_borra_el_token_caducado(self) -> None:
        r = await self._vista_previa()
        token = r["confirmation_token"]
        await self._caducar(token)
        ok, error, _ = await security.resolve_confirmation_token(
            token, self.TOOL, {"url_path": "panel-ficticio"},
            omitibles=self.OMITIBLES)
        self.assertFalse(ok)
        self.assertIn("expired", error)
        self.assertFalse(self._fichero(token).exists())

    async def test_cada_vista_previa_barre_los_caducados(self) -> None:
        """Control negativo: sin el barrido en `create_confirmation_token`
        cae (comprobado)."""
        r = await self._vista_previa()
        viejo = r["confirmation_token"]
        await self._caducar(viejo)
        await self._vista_previa()
        self.assertFalse(self._fichero(viejo).exists())

    async def test_tope_lleno_emite_el_token_sin_documento(self) -> None:
        """Control negativo: sin la comparación con el tope cae (comprobado)."""
        import unittest.mock as mock
        from structlog.testing import capture_logs

        centinela = "CENTINELA-TOPE-55d0"
        args = {"url_path": "panel-ficticio",
                "config": {"views": [{"title": centinela}]}}
        with mock.patch.object(security, "CONFIRMATION_STORED_MAX_BYTES", 10), \
                capture_logs() as logs:
            r = await self._vista_previa(args)
        token = r["confirmation_token"]
        self.assertNotIn("stored_args", self._datos(token))
        self.assertNotIn("omit_on_confirm", r)
        self.assertEqual(r["confirm_with"],
                         ["config", "confirmation_token", "url_path"])
        self.assertEqual(
            r["confirm_hint"],
            "Repeat the same call with all the same arguments plus "
            "confirmation_token: the server could not keep config this time.",
        )
        evento = [e for e in logs if e["event"] == "confirmation_args_not_stored"]
        self.assertEqual(len(evento), 1)
        self.assertEqual(evento[0]["reason"], "storage_cap")
        self.assertEqual(evento[0]["keys"], ["config"])
        self.assertEqual(evento[0]["tool"], self.TOOL)
        self.assertIsInstance(evento[0]["bytes"], int)
        self.assertNotIn(centinela, repr(logs))
        # Y la confirmación completa sigue funcionando, como en 1.1.1.
        ok, error, _ = await security.resolve_confirmation_token(
            token, self.TOOL, dict(args), omitibles=self.OMITIBLES)
        self.assertTrue(ok, error)

    async def test_el_tope_suma_los_documentos_de_los_tokens_vigentes(self) -> None:
        """El tope cuenta los documentos guardados en los tokens vigentes, no
        los de tokens caducados, completados ni sin documento."""
        import unittest.mock as mock

        primero = await self._vista_previa()
        tam = self._datos(primero["confirmation_token"])["stored_bytes"]
        with mock.patch.object(
            security, "CONFIRMATION_STORED_MAX_BYTES", 2 * tam
        ):
            segundo = await self._vista_previa()
            self.assertIn("omit_on_confirm", segundo)
            tercero = await self._vista_previa()
            self.assertNotIn("omit_on_confirm", tercero)
            # Completar uno libera su parte.
            await security.resolve_confirmation_token(
                segundo["confirmation_token"], self.TOOL,
                {"url_path": "panel-ficticio"}, omitibles=self.OMITIBLES)
            await security.complete_confirmation_token(
                segundo["confirmation_token"], success=True, result={})
            cuarto = await self._vista_previa()
            self.assertIn("omit_on_confirm", cuarto)
            # Caducar otro también.
            await self._caducar(primero["confirmation_token"])
            quinto = await self._vista_previa()
            self.assertIn("omit_on_confirm", quinto)

    async def test_el_documento_nunca_llega_al_log(self) -> None:
        from structlog.testing import capture_logs

        centinela = "CENTINELA-LOG-a8e4"
        args = {"url_path": "panel-ficticio",
                "config": {"views": [{"title": centinela}]}}
        with capture_logs() as logs:
            r = await self._vista_previa(args)
            await security.resolve_confirmation_token(
                r["confirmation_token"], self.TOOL, {"url_path": "otro"},
                omitibles=self.OMITIBLES)
            await security.resolve_confirmation_token(
                r["confirmation_token"], self.TOOL, {"url_path": "panel-ficticio"},
                omitibles=self.OMITIBLES)
            await security.complete_confirmation_token(
                r["confirmation_token"], success=True, result={})
            caduca = await self._vista_previa(args)
            await self._caducar(caduca["confirmation_token"])
            await security.cleanup_expired_confirmations()
        self.assertTrue(logs, "el test no capturó ningún evento")
        self.assertNotIn(centinela, repr(logs))
