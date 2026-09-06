"""Regresiones de seguridad: un test por fallo que existió de verdad.

Cada caso reproduce un escape que **funcionaba** antes de su arreglo. No son
tests de "la función existe": son la prueba de explotación convertida en prueba
automática. Si alguien deshace la corrección, el test lo dice.

Todos llevan control negativo: se reintrodujo el fallo y se comprobó que el test
lo detecta. Un test de seguridad que no falla cuando la guarda desaparece no
sirve de nada, y esa comprobación es la única forma de saberlo.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import tempfile
import unittest
import unittest.mock

import hermes.fs as fs
from hermes.ha import HAConnectionError, _assert_safe_request_path
from hermes.security import redact_structure


class TestSupervisorPathEscape(unittest.TestCase):
    """`%2e%2e` alcanzaba cualquier endpoint del Supervisor.

    `_assert_safe_request_path` rechazaba el `..` literal pero no decodificaba
    el porcentaje, mientras que yarl —dentro de aiohttp— sí lo decodifica y
    normaliza DESPUÉS. Como el add-on corre con `hassio_role: admin`, esto
    convertía "llamar a un servicio de HA" en administrador del Supervisor:

        URL("http://supervisor/core/api" + "/services/%2e%2e/%2e%2e/%2e%2e/host/reboot")
            -> /host/reboot

    Saltaba a la vez la denylist (el "domain.service" compuesto nunca casaba),
    los confirmation tokens de sv_reboot_host / sv_uninstall_addon /
    sv_delete_backup, y la autoprotección de local_hermes.
    """

    def _blocked(self, path: str) -> bool:
        try:
            _assert_safe_request_path(path)
        except HAConnectionError:
            return True
        return False

    def test_literal_traversal_still_blocked(self) -> None:
        self.assertTrue(self._blocked("/services/../../../host/reboot"))

    def test_percent_encoded_traversal(self) -> None:
        self.assertTrue(self._blocked("/services/%2e%2e/%2e%2e/%2e%2e/host/reboot"))

    def test_percent_encoded_is_case_insensitive(self) -> None:
        self.assertTrue(self._blocked("/services/%2E%2E/%2e%2e/addons/self/security"))

    def test_double_encoding(self) -> None:
        self.assertTrue(self._blocked("/services/%252e%252e/host/reboot"))

    def test_encoded_slash(self) -> None:
        self.assertTrue(self._blocked("/addons/%2e%2e%2fhost/reboot"))

    def test_fragment_truncates_the_path(self) -> None:
        """yarl corta el path en '#': /addons/x#/stop acaba siendo /addons/x."""
        self.assertTrue(self._blocked("/addons/local_hermes#/stop"))

    def test_query_truncates_the_path(self) -> None:
        self.assertTrue(self._blocked("/addons/local_hermes?x=/stop"))

    def test_legitimate_paths_still_pass(self) -> None:
        for path in ("/addons/local_hermes/info", "/core/api/states/light.salon",
                     "/backups", "/core/check", "/addons/self/options/config"):
            _assert_safe_request_path(path)  # no debe lanzar

    def test_the_escape_no_longer_reaches_another_endpoint(self) -> None:
        """La prueba de fuego: reconstruye la URL como hace aiohttp."""
        from yarl import URL

        payload = "/services/%2e%2e/%2e%2e/%2e%2e/host/reboot"
        self.assertTrue(self._blocked(payload))
        # Y si alguien quitara el guardia, esto es lo que pasaría:
        self.assertEqual(URL("http://supervisor/core/api" + payload).raw_path,
                         "/host/reboot")


class TestBlacklistDefendsItself(unittest.TestCase):
    """la blacklist confiaba en el llamador."""

    def setUp(self) -> None:
        self.base = pathlib.Path(tempfile.mkdtemp(prefix="hermes_audit_"))
        (self.base / "sub").mkdir()
        (self.base / "esphome").mkdir()
        (self.base / "secrets.yaml").write_text("api_key: X\n", encoding="utf-8")
        (self.base / "esphome" / "secrets.yaml").write_text("wifi: Y\n", encoding="utf-8")
        (self.base / "sub" / "normal.yaml").write_text("foo: bar\n", encoding="utf-8")
        self._prev = fs.CONFIG_BASE
        fs.CONFIG_BASE = self.base

    def tearDown(self) -> None:
        fs.CONFIG_BASE = self._prev
        shutil.rmtree(self.base, ignore_errors=True)

    def test_unresolved_traversal_is_blocked(self) -> None:
        """`pathlib` no colapsa los '..' de un glob, pero el SO sí al abrir.

        `fs_search_in_config` construía los paths con rglob() y un patrón del
        cliente, así que `sub/../secrets.yaml` no casaba con ninguna regla
        —todas comparan cadenas— y el fichero se leía igualmente.
        """
        blocked, _ = fs.check_blacklisted(self.base / "sub" / ".." / "secrets.yaml")
        self.assertTrue(blocked)

    def test_path_outside_config_is_blocked(self) -> None:
        blocked, reason = fs.check_blacklisted(self.base / ".." / "cualquier_cosa")
        self.assertTrue(blocked)
        self.assertIn("outside", reason.lower())

    def test_nested_secrets_are_protected(self) -> None:
        """HA resuelve `!secret` desde el secrets.yaml más cercano.

        `esphome/secrets.yaml` guarda la contraseña del WiFi y la clave de la
        API; comparando solo la ruta exacta quedaba desprotegido.
        """
        for rel in ("secrets.yaml", "esphome/secrets.yaml"):
            blocked, _ = fs.check_blacklisted(self.base / rel)
            self.assertTrue(blocked, f"{rel} debería estar protegido")

    def test_ordinary_files_still_readable(self) -> None:
        blocked, _ = fs.check_blacklisted(self.base / "sub" / "normal.yaml")
        self.assertFalse(blocked)


class TestRedactionCoversTheWriteToolPreview(unittest.TestCase):
    """El primer arreglo de la fuga dejó abierta la tool de escritura.

    `sv_set_addon_options`, para construir su preview, lee las opciones ACTUALES
    del add-on. Esa lectura no pasaba por `redact_structure`, así que la primera
    llamada —la que solo genera el preview, sin confirmar nada— devolvía la
    `auth_password` en claro.
    """

    def test_preview_source_is_redacted(self) -> None:
        current = {"auth_password": "SECRETO", "public_hostname": "x.ts.net"}
        out = redact_structure(current)
        self.assertEqual(out["auth_password"], "***REDACTED***")
        self.assertEqual(out["public_hostname"], "x.ts.net")

    def test_the_tool_applies_it(self) -> None:
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "hermes/src/hermes/tools/addons.py").read_text(encoding="utf-8")
        idx = src.index('"current_options"')
        self.assertIn("redact_structure", src[idx:idx + 120],
                      "el preview de sv_set_addon_options debe redactar")



class TestCallServiceHasOneDoor(unittest.TestCase):
    """la denylist vivía solo en la tool.

    `HAClient.call_service` era una segunda puerta al mismo endpoint REST, y 36
    llamadas repartidas por 14 módulos entraban por ella sin pasar por ningún
    control. Bastaban tres pasos:

        1. crear un script con `shell_command.*`   -> 1 token (nombre inocuo)
        2. ha_run_script("script.x")               -> 0 tokens
        3. repetir indefinidamente
    """

    def test_policy_is_shared_by_both_layers(self) -> None:
        from hermes import service_policy
        from hermes.tools.ha import CALL_SERVICE_DENYLIST

        self.assertIs(CALL_SERVICE_DENYLIST, service_policy.CALL_SERVICE_DENYLIST)

    def test_denylist_never_shrank(self) -> None:
        """Al mudarla de módulo se perdieron 12 entradas; el test lo habría visto."""
        from hermes.service_policy import CALL_SERVICE_DENYLIST as D

        for entry in ("shell_command.*", "python_script.*", "homeassistant.restart",
                      "automation.reload", "recorder.purge", "lock.unlock",
                      "mqtt.publish", "conversation.process", "system_log.clear",
                      "backup.create", "device_tracker.see", "logger.set_level"):
            self.assertIn(entry, D, f"{entry} desapareció de la denylist")

    def test_effect_not_just_variant(self) -> None:
        """se vetaba `lock.unlock` pero no `lock.open`, que abre el pestillo."""
        from hermes.service_policy import CALL_SERVICE_DENYLIST as D

        self.assertIn("lock.open", D)
        self.assertIn("update.install", D)


class TestDangerousContentScanner(unittest.TestCase):
    """el escáner solo reconocía `service:`.

    `action:` es la sintaxis estándar de HA desde 2024.8 y la que escribe su
    propia interfaz, así que bastaba usar la forma moderna —la normal hoy— para
    que un script con `shell_command.*` no se clasificara como peligroso.
    """

    def _scan(self, data):
        from hermes.tools.ha import CALL_SERVICE_DENYLIST, _scan_for_dangerous_services

        return _scan_for_dangerous_services(data, CALL_SERVICE_DENYLIST)

    def test_modern_action_syntax(self) -> None:
        self.assertTrue(self._scan([{"action": "shell_command.evil"}]))

    def test_perform_action_alias(self) -> None:
        self.assertTrue(self._scan([{"perform_action": "homeassistant.restart"}]))

    def test_templates_cannot_be_analysed_so_they_count(self) -> None:
        self.assertTrue(self._scan([{"service": "{{ 'shell_command.evil' }}"}]))
        self.assertTrue(self._scan([{"action": "{% if x %}lock.open{% endif %}"}]))

    def test_nested_in_choose(self) -> None:
        self.assertTrue(self._scan(
            [{"choose": [{"sequence": [{"action": "homeassistant.restart"}]}]}]
        ))

    def test_harmless_stays_harmless(self) -> None:
        self.assertFalse(self._scan([{"action": "light.turn_on"}]))
        self.assertFalse(self._scan([{"service": "light.turn_on"}]))

class TestClientGuardActuallyBlocks(unittest.IsolatedAsyncioTestCase):
    """El test de comportamiento, no de estructura.

    Los tests estructurales de arriba (la política se comparte, la denylist
    tiene N entradas) seguían pasando con el guardia desactivado: lo comprobé
    con un control negativo. Sin este test, el arreglo no está protegido.
    """

    class _Spy:
        def __init__(self) -> None:
            self.reached: list[str] = []

        async def _request_json(self, method, path, json_body=None):
            self.reached.append(path)
            return {"ok": True}

    async def _call(self, domain, service, **kw):
        from hermes.ha import HAClient

        spy = self._Spy()
        result = await HAClient.call_service(spy, domain, service, None, **kw)
        return spy, result

    async def test_denylisted_service_never_reaches_the_endpoint(self) -> None:
        from hermes.service_policy import DangerousServiceError

        for domain, service in (("shell_command", "evil"), ("automation", "reload"),
                                ("homeassistant", "restart"), ("lock", "open"),
                                ("recorder", "purge"), ("update", "install")):
            spy = self._Spy()
            from hermes.ha import HAClient

            with self.assertRaises(DangerousServiceError,
                                   msg=f"{domain}.{service} debería bloquearse"):
                await HAClient.call_service(spy, domain, service, None)
            self.assertEqual(spy.reached, [],
                             f"{domain}.{service} llegó al endpoint REST")

    async def test_case_and_whitespace_do_not_evade(self) -> None:
        from hermes.ha import HAClient
        from hermes.service_policy import DangerousServiceError

        for domain, service in ((" Homeassistant ", " Restart "),
                                ("SHELL_COMMAND", "X")):
            with self.assertRaises(DangerousServiceError):
                await HAClient.call_service(self._Spy(), domain, service, None)

    async def test_harmless_service_passes_through(self) -> None:
        spy, _ = await self._call("light", "turn_on")
        self.assertEqual(spy.reached, ["/services/light/turn_on"])

    async def test_explicit_authorisation_is_honoured(self) -> None:
        """La tool ha_call_service, tras validar su token, sí puede."""
        spy, _ = await self._call("homeassistant", "restart", allow_dangerous=True)
        self.assertEqual(spy.reached, ["/services/homeassistant/restart"])


class TestRestrictedEntityInvocation(unittest.IsolatedAsyncioTestCase):
    """ha_run_script ignoraba el set de entidades restringidas."""

    def setUp(self) -> None:
        from hermes import service_policy

        service_policy.set_auto_restricted_entities({"script.peligroso"})

    def tearDown(self) -> None:
        from hermes import service_policy

        service_policy.set_auto_restricted_entities(set())

    class _Spy:
        def __init__(self) -> None:
            self.reached: list[str] = []

        async def call_service(self, domain, service, data=None, *, allow_dangerous=False):
            self.reached.append(f"{domain}.{service}")
            return {"ok": True}

    async def test_restricted_entity_requires_a_token(self) -> None:
        import json

        from hermes.tools._common import guarded_entity_invoke

        spy = self._Spy()
        out = await guarded_entity_invoke(
            spy, "script", "turn_on", "script.peligroso", "ha_run_script", None
        )
        data = json.loads(out) if isinstance(out, str) else out
        self.assertIn("confirmation_token", data)
        self.assertEqual(spy.reached, [], "se ejecutó sin confirmación")

    async def test_unrestricted_entity_stays_one_step(self) -> None:
        from hermes.tools._common import guarded_entity_invoke

        spy = self._Spy()
        await guarded_entity_invoke(
            spy, "script", "turn_on", "script.inocuo", "ha_run_script", None
        )
        self.assertEqual(spy.reached, ["script.turn_on"])

class TestLegitimatePathStillWorks(unittest.IsolatedAsyncioTestCase):
    """El guardia nuevo no puede romper el camino autorizado.

    Al mover la denylist al cliente faltó pasar `allow_dangerous=True` en
    la llamada que `ha_call_service` hace DESPUÉS de validar su confirmation
    token, así que un servicio vetado dejaba de poder ejecutarse ni siquiera con
    autorización. La suite no lo detectó porque ningún test ejecutaba un servicio
    vetado con un token VÁLIDO: solo comprobaban que se pedía token y que uno
    inválido se rechazaba. Este test cubre ese hueco.
    """

    def test_the_authorised_call_passes_allow_dangerous(self) -> None:
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "hermes/src/hermes/tools/ha.py").read_text(encoding="utf-8")
        marker = "valid, error = await validate_confirmation_token("
        idx = src.index(marker)
        window = src[idx:idx + 900]
        self.assertIn("allow_dangerous=True", window,
                      "tras validar el token hay que autorizar explícitamente")

    def test_unconfirmed_path_does_not(self) -> None:
        """La ruta sin token no debe autorizar nunca."""
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "hermes/src/hermes/tools/ha.py").read_text(encoding="utf-8")
        # La última llamada de ha_call_service es la de servicios inocuos.
        tail = src[src.index("return await ha_client.call_service(domain_lower"):]
        self.assertNotIn("allow_dangerous", tail.split(")")[0])

class TestRestrictedEntityMatching(unittest.TestCase):
    """la comprobación era una igualdad exacta sobre un solo campo.

    Home Assistant normaliza mucho más en `cv.entity_ids` —parte por comas,
    hace strip y lower— y acepta objetivos indirectos por área o dispositivo.
    Seis elusiones distintas funcionaban con una sola llamada.
    """

    R = frozenset({"script.peligroso"})

    def _t(self, domain, data):
        from hermes.service_policy import targets_restricted_entity

        return targets_restricted_entity(domain, data, self.R)

    def test_comma_separated_list(self) -> None:
        """HA parte por comas; el `in` de Python veía un solo literal."""
        self.assertTrue(self._t("script", {"entity_id": "script.inocuo, script.peligroso"}))

    def test_case_insensitive(self) -> None:
        self.assertTrue(self._t("script", {"entity_id": "Script.Peligroso"}))

    def test_match_all_wildcard(self) -> None:
        self.assertTrue(self._t("script", {"entity_id": "all"}))

    def test_nested_target(self) -> None:
        self.assertTrue(self._t("script", {"target": {"entity_id": "script.peligroso"}}))

    def test_indirect_targets_fail_closed(self) -> None:
        """No se pueden resolver sin consultar los registros: se exige token."""
        for key in ("area_id", "device_id", "label_id", "floor_id"):
            self.assertTrue(self._t("script", {key: "x"}), f"{key} debería fallar cerrado")

    def test_list_form(self) -> None:
        self.assertTrue(self._t("script", {"entity_id": ["script.x", "script.peligroso"]}))

    def test_no_false_positives(self) -> None:
        """Fallar cerrado no puede convertirse en ruido."""
        self.assertFalse(self._t("light", {"area_id": "salon"}))
        self.assertFalse(self._t("light", {"entity_id": "light.salon"}))
        self.assertFalse(self._t("script", {"entity_id": "script.inocuo"}))

    def test_empty_restricted_set_never_matches(self) -> None:
        from hermes.service_policy import targets_restricted_entity

        self.assertFalse(targets_restricted_entity(
            "script", {"entity_id": "script.peligroso"}, frozenset()))


class TestClassificationHappensOnSave(unittest.TestCase):
    """la clasificación solo ocurría al arrancar y tras un reload.

    Los caminos normales de creación —`ha_create_or_update_script` y
    `ha_create_or_update_automation`— no la disparaban, así que un script recién
    creado con `shell_command.*` quedaba sin restringir hasta el siguiente
    reinicio del add-on.
    """

    def setUp(self) -> None:
        from hermes import service_policy

        service_policy.set_auto_restricted_entities(set())

    tearDown = setUp

    def test_dangerous_config_is_classified_immediately(self) -> None:
        from hermes.service_policy import get_auto_restricted_entities
        from hermes.tools.ha import classify_saved_config

        self.assertTrue(classify_saved_config(
            "script.mantenimiento",
            {"sequence": [{"action": "shell_command.evil"}]},
        ))
        self.assertIn("script.mantenimiento", get_auto_restricted_entities())

    def test_and_then_requires_a_token(self) -> None:
        """La cadena completa: guardar -> clasificar -> exigir confirmación."""
        from hermes.service_policy import (
            get_auto_restricted_entities,
            targets_restricted_entity,
        )
        from hermes.tools.ha import classify_saved_config

        classify_saved_config("script.x", {"sequence": [{"action": "homeassistant.restart"}]})
        self.assertTrue(targets_restricted_entity(
            "script", {"entity_id": "script.x"}, get_auto_restricted_entities()))

    def test_harmless_config_is_not_restricted(self) -> None:
        from hermes.tools.ha import classify_saved_config

        self.assertFalse(classify_saved_config(
            "script.saludo", {"sequence": [{"action": "light.turn_on"}]}))

    def test_the_save_paths_call_it(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1]
        for rel in ("hermes/src/hermes/tools/automations.py", "hermes/src/hermes/tools/scripts.py"):
            src = (root / rel).read_text(encoding="utf-8")
            idx = src.index("config_save(")
            self.assertIn("classify_saved_config", src[idx:idx + 500],
                          f"{rel} no clasifica tras guardar")

class TestWebSocketCannotHangForever(unittest.TestCase):
    """se pasaba el tipo de timeout equivocado a ws_connect.

    `ws_connect` espera un `ClientWSTimeout`; se le pasaba un `ClientTimeout`, y
    aiohttp lo trataba como el parámetro float legacy: construía
    `ClientWSTimeout(ws_close=<ClientTimeout>)` dejando `ws_receive=None`, lo que
    a su vez pone `conn_proto.read_timeout = None`.

    Si la conexión TCP moría en silencio —evicción de NAT, cambio de red del
    host— `receive()` se bloqueaba para siempre, `_connect_and_watch` nunca
    retornaba y `set_ws_connected(False)` nunca se ejecutaba: /health seguía
    diciendo "healthy" y el watchdog del Supervisor tampoco reiniciaba nada.
    """

    def _source(self) -> str:
        import inspect

        from hermes.ha import HAClient

        return inspect.getsource(HAClient._connect_and_watch)

    def test_uses_the_websocket_timeout_type(self) -> None:
        src = self._source()
        self.assertIn("ClientWSTimeout(", src)
        self.assertNotIn("timeout=ClientTimeout(", src)

    def test_has_a_heartbeat(self) -> None:
        """Es lo único que detecta de verdad una conexión muerta."""
        self.assertIn("heartbeat=", self._source())

    def test_the_type_is_what_aiohttp_expects(self) -> None:
        import inspect

        from aiohttp import ClientSession, ClientWSTimeout

        anno = inspect.signature(ClientSession.ws_connect).parameters["timeout"].annotation
        self.assertIn("ClientWSTimeout", str(anno))
        ClientWSTimeout(ws_close=10.0)  # construible con la forma que usamos


class TestReadyIsNotAOneWayLatch(unittest.TestCase):
    """`_connected_event` se ponía a True y no se limpiaba nunca.

    Con la WS caída, `get_states()` seguía sirviendo la caché congelada como si
    fuera dato vivo —su fallback REST era código muerto— y `wait_ready()`
    devolvía True al instante, así que `requires_ready` no protegía las
    reconexiones.
    """

    def test_the_reconnect_loop_clears_it(self) -> None:
        import inspect

        from hermes.ha import HAClient

        self.assertIn("_connected_event.clear()",
                      inspect.getsource(HAClient._run_background))


class TestLogRedactionCoversEverything(unittest.TestCase):
    """Los secretos escapaban por tres huecos a la vez."""

    def test_json_format_in_addon_logs(self) -> None:
        """el patrón exigía `clave` + `:` + valor, pero en JSON la comilla
        de cierre se interpone, así que esas líneas salían intactas — incluidas
        las del propio Hermes, cuyo JSONRenderer produce justo esa forma."""
        from hermes.security import redact_secrets

        out = redact_secrets('{"password": "hunter2", "api_key": "sk-live-42"}')
        self.assertNotIn("hunter2", out)
        self.assertNotIn("sk-live-42", out)

    def test_separatorless_format(self) -> None:
        from hermes.security import redact_secrets

        self.assertNotIn("hunter2", redact_secrets("user admin, password hunter2"))

    def test_it_did_not_break_what_already_worked(self) -> None:
        """La primera versión del patrón nuevo usaba `\\s+` y en un log de
        Mosquitto se comía "passwd" + salto + "password:", dejando el valor real
        expuesto. Lo detectó un test que ya existía."""
        from hermes.security import redact_secrets

        raw = "listener 1883" + chr(10) + "password_file /mosquitto/config/passwd" + chr(10) + "password: mypassword"
        self.assertNotIn("mypassword", redact_secrets(raw))

    def test_no_false_positives(self) -> None:
        from hermes.security import redact_secrets

        self.assertNotIn("REDACTED",
                         redact_secrets('{"username": "admin", "port": 1883}'))

    def test_structured_fields_beyond_event(self) -> None:
        """la redacción por patrones solo tocaba `event`, y la de
        claves comparaba el nombre completo. `body` y `error` —que se llenaron
        con contenido ajeno— se saltaban las dos reglas."""
        from hermes.logging_setup import _redact_processor

        out = _redact_processor(None, "info", {
            "event": "http_request",
            "body": '{"auth_password": "SECRETO"}',
            "error": 'HA REST failed 400: {"password": "hunter2"}',
            "mqtt_password": "otro",
            "user_agent": "Bearer TOKEN",
            "status": 400,
        })
        blob = str(out)
        for secreto in ("SECRETO", "hunter2", "otro", "TOKEN"):
            self.assertNotIn(secreto, blob, f"{secreto} salió en claro")
        self.assertEqual(out["status"], 400, "los no-strings no deben tocarse")

    def test_traceback_is_redacted_too(self) -> None:
        """El traceback se añadía DESPUÉS del redactor en la cadena de structlog,
        así que no se redactaba jamás."""
        import inspect

        from hermes import logging_setup

        src = inspect.getsource(logging_setup.setup_logging)
        self.assertLess(src.index("format_exc_info"), src.index("_redact_processor"),
                        "format_exc_info debe ir ANTES del redactor")

class TestConsentScreen(unittest.TestCase):
    """la pantalla de login no decía quién pedía acceso ni a dónde iba.

    `/oauth/register` es público —lo exige RFC 7591— y quien se registra aporta
    su propio `redirect_uri`. Con la pantalla anterior, que solo decía "Autorizar
    acceso al servidor MCP", cualquiera podía registrar un cliente, mandarle al
    dueño el enlace de autorización y recibir el código: dominio real, TLS real,
    página de login auténtica. Con Tailscale Funnel el hostname ni hay que
    adivinarlo — el certificado de `*.ts.net` queda publicado en los registros de
    Certificate Transparency.

    Validar el `redirect_uri` no arregla esto: la lista contra la que se valida
    la escribe el propio cliente. La única defensa real es que el dueño VEA a
    dónde va el código.
    """

    def setUp(self) -> None:
        import json
        import tempfile

        import hermes.oauth as oauth

        self.oauth = oauth
        self._prev_dir = oauth._CLIENTS_DIR
        d = pathlib.Path(tempfile.mkdtemp(prefix="hermes_oauth_"))
        oauth._CLIENTS_DIR = d / "clients"
        oauth._CLIENTS_DIR.mkdir(parents=True, exist_ok=True)
        self.cid = "aaaabbbb-cccc-dddd-eeee-ffff00001111"
        (oauth._CLIENTS_DIR / f"{self.cid}.json").write_text(
            json.dumps({"client_name": "Claude",
                        "redirect_uris": ["https://claude.ai/cb"]}),
            encoding="utf-8",
        )
        self.srv = oauth.OAuthServer.__new__(oauth.OAuthServer)
        self.tmp = d

    def tearDown(self) -> None:
        import shutil

        self.oauth._CLIENTS_DIR = self._prev_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _html(self, client_id: str, redirect_uri: str) -> str:
        return self.srv._login_html(
            client_id=client_id, redirect_uri=redirect_uri, state="s",
            code_challenge="c", code_challenge_method="S256", scope="mcp", error="",
        )

    def test_shows_who_is_asking(self) -> None:
        self.assertIn("Claude", self._html(self.cid, "https://claude.ai/cb"))

    def test_shows_where_the_code_goes(self) -> None:
        """Es lo que delata el phishing: el destino no es quien dice ser."""
        html = self._html(self.cid, "https://atacante.example/cb")
        self.assertIn("atacante.example", html)

    def test_shows_only_the_origin_not_the_query(self) -> None:
        """Una query larga podría empujar el origen fuera de la vista.

        El `redirect_uri` completo sigue estando en el campo oculto del
        formulario —hace falta para el POST—, así que se comprueba el BLOQUE de
        consentimiento, que es lo que el usuario lee.
        """
        import re as _re

        html = self._html(self.cid, "https://atacante.example/cb?a=" + "x" * 300)
        bloque = _re.search(r'<div class="consent">.*?</div>', html, _re.S)
        self.assertIsNotNone(bloque, "no se renderizó el bloque de consentimiento")
        self.assertIn("atacante.example", bloque.group(0))
        self.assertNotIn("x" * 300, bloque.group(0))

    def test_unknown_client_is_labelled_as_such(self) -> None:
        html = self._html("00000000-0000-0000-0000-000000000000", "https://x/cb")
        self.assertIn("cliente sin nombre", html)

    def test_client_name_is_escaped(self) -> None:
        """El nombre lo elige quien se registra: podría intentar inyectar HTML."""
        import json

        cid = "bbbbcccc-dddd-eeee-ffff-000011112222"
        (self.oauth._CLIENTS_DIR / f"{cid}.json").write_text(
            json.dumps({"client_name": "<script>alert(1)</script>"}), encoding="utf-8")
        html = self._html(cid, "https://x/cb")
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)


class _PeticionFormulario:
    """Doble mínimo de Request: los handlers de OAuth solo usan .form()."""

    def __init__(self, campos: dict) -> None:
        self._campos = campos
        self.client = None
        self.headers: dict = {}

    async def form(self):
        return self._campos

class TestClientIdIsNotAPath(unittest.IsolatedAsyncioTestCase):
    """`client_id` se interpolaba en una ruta del sistema de ficheros.

    Todos los demás nombres de fichero del módulo se derivan de `_hash_token()`
    (hex); este era el único que venía crudo del formulario.
    """

    _ATRIBUTOS = ("_OAUTH_DIR", "_CLIENTS_DIR", "_CODES_DIR", "_TOKENS_DIR")

    async def asyncSetUp(self) -> None:
        import hermes.oauth as oauth

        self.oauth = oauth
        self._orig = {a: getattr(oauth, a) for a in self._ATRIBUTOS}
        self._tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self._tmp.name) / "oauth"
        oauth._OAUTH_DIR = base
        oauth._CLIENTS_DIR = base / "clients"
        oauth._CODES_DIR = base / "codes"
        oauth._TOKENS_DIR = base / "tokens"
        for d in (oauth._CLIENTS_DIR, oauth._CODES_DIR, oauth._TOKENS_DIR):
            d.mkdir(parents=True, exist_ok=True)
        self.server = oauth.OAuthServer(
            auth_password="test-password-1234",
            public_hostname="hermes.tail-xxxx.ts.net",
        )

    async def asyncTearDown(self) -> None:
        for a, v in self._orig.items():
            setattr(self.oauth, a, v)
        self._tmp.cleanup()


    def test_traversal_is_rejected(self) -> None:
        from hermes.oauth import _is_valid_client_id

        for bad in ("../../fuera", "a/b", "..", "", "x" * 200, "con espacio",
                    "null\x00byte"):
            self.assertFalse(_is_valid_client_id(bad), f"{bad!r} debería rechazarse")

    def test_real_uuids_are_accepted(self) -> None:
        import uuid

        from hermes.oauth import _is_valid_client_id

        for _ in range(5):
            self.assertTrue(_is_valid_client_id(str(uuid.uuid4())))

    async def test_a_traversal_client_id_never_builds_a_path(self) -> None:
        """Por el camino real: POST /oauth/authorize con la password correcta.

        La primera versión de este test tenía la guarda escrita DENTRO del
        propio test (`if _is_valid_client_id(...)`, siempre falso), así que
        comprobaba su propio `if` y no el del servidor. Su docstring decía
        «comportamiento, no texto» y era justo lo contrario.

        Ahora se ejerce el handler de verdad y se vigila cada ruta que se
        intenta leer: ninguna puede salir del directorio de clientes.
        """
        import hermes.oauth as oauth

        leidas: list = []
        original = oauth._safe_read
        oauth._safe_read = lambda ruta: (leidas.append(ruta), original(ruta))[1]
        try:
            resp = await self.server.authorize_post(_PeticionFormulario({
                "password": "test-password-1234",
                "client_id": "../../../etc/passwd",
                "redirect_uri": "https://claude.ai/cb",
                "state": "s",
                "code_challenge": "c",
                "code_challenge_method": "S256",
                "scope": "mcp",
            }))
        finally:
            oauth._safe_read = original

        self.assertEqual(resp.status_code, 200)
        clientes = oauth._CLIENTS_DIR.resolve()
        for ruta in leidas:
            with self.subTest(ruta=str(ruta)):
                self.assertEqual(
                    ruta.resolve().parent, clientes,
                    f"se construyó una ruta fuera del directorio de clientes: {ruta}")

    async def test_a_valid_client_id_does_read_its_file(self) -> None:
        """Control negativo: la guarda no puede bloquear a los clientes buenos."""
        import json
        import uuid

        import hermes.oauth as oauth

        cid = str(uuid.uuid4())
        oauth._CLIENTS_DIR.mkdir(parents=True, exist_ok=True)
        (oauth._CLIENTS_DIR / f"{cid}.json").write_text(
            json.dumps({"client_name": "Claude",
                        "redirect_uris": ["https://claude.ai/cb"]}),
            encoding="utf-8")

        leidas: list = []
        original = oauth._safe_read
        oauth._safe_read = lambda ruta: (leidas.append(ruta), original(ruta))[1]
        try:
            await self.server.authorize_post(_PeticionFormulario({
                "password": "test-password-1234",
                "client_id": cid,
                "redirect_uri": "https://claude.ai/cb",
                "state": "s",
                "code_challenge": "c",
                "code_challenge_method": "S256",
                "scope": "mcp",
            }))
        finally:
            oauth._safe_read = original

        self.assertTrue(
            any(r.name == f"{cid}.json" for r in leidas),
            "no se llegó a leer el fichero del cliente legítimo")

class TestNoBufferingBeforeAuth(unittest.TestCase):
    """se bufferizaba el cuerpo de quien iba a recibir un 401.

    Bufferizar es inevitable para responder un 413 limpio a un body chunked: hay
    que leer por delante y conservar lo leído para poder reenviarlo. Pero
    bufferizar el cuerpo de una petición que se va a rechazar igualmente NO lo
    es, y eso era exactamente lo que pasaba con el limitador como middleware más
    externo: hasta 4 MiB de memoria del host por conexión, a coste cero para un
    atacante sin credenciales, sin tope de conexiones simultáneas.

    Medido antes del arreglo: 2.000.000 bytes leídos. Después: 0.
    """

    def setUp(self) -> None:
        # El cubo de fallos de autenticación es de modulo: si otro test lo deja
        # lleno, aquí saldria un 429 en vez del 401 que se quiere comprobar.
        from hermes.middleware import _AUTH_FAILURE_BUCKET

        _AUTH_FAILURE_BUCKET.clear()

    class _Espia:
        def __init__(self, app):
            self.app = app
            self.leidos = 0

        async def __call__(self, scope, receive, send):
            if scope.get("type") != "http":
                await self.app(scope, receive, send)
                return

            async def contando():
                msg = await receive()
                if msg["type"] == "http.request":
                    self.leidos += len(msg.get("body", b""))
                return msg

            await self.app(scope, contando, send)

    def _stack(self):
        from starlette.applications import Starlette
        from starlette.middleware import Middleware
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        from hermes.middleware import (
            BodySizeLimitMiddleware,
            OAuthBearerAuth,
            RateLimitPreAuth,
            SecurityHeadersMiddleware,
        )

        espias = []

        class Captura(self._Espia):
            def __init__(self, app):
                super().__init__(app)
                espias.append(self)

        async def eco(request):
            return PlainTextResponse(f"ok:{len(await request.body())}")

        app = Starlette(
            routes=[Route("/mcp", eco, methods=["POST"]),
                    Route("/oauth/register", eco, methods=["POST"])],
            middleware=[
                Middleware(Captura),
                # Mismo orden que producción (ver __main__.py)
                Middleware(SecurityHeadersMiddleware),
                Middleware(RateLimitPreAuth, max_per_minute=1000),
                Middleware(OAuthBearerAuth, oauth_validator=None),
                Middleware(BodySizeLimitMiddleware, max_body_bytes=4_194_304),
            ],
        )
        return app, espias

    def test_anonymous_body_is_never_read(self) -> None:
        from starlette.testclient import TestClient

        app, espias = self._stack()
        with TestClient(app) as c:
            r = c.post("/mcp", content=b"x" * 500_000)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(espias[0].leidos, 0,
                         "se leyó el cuerpo de una petición sin autenticar")

    def test_authenticated_traffic_is_unaffected(self) -> None:
        from starlette.testclient import TestClient

        app, espias = self._stack()
        with TestClient(app) as c:
            r = c.post("/mcp", content=b"x" * 50_000,
                       headers={"Authorization": "Bearer x"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(espias[0].leidos, 50_000)

    def test_public_paths_have_a_small_ceiling(self) -> None:
        """Un registro DCR legítimo son cientos de bytes; megas no tienen uso."""
        from starlette.testclient import TestClient

        app, _ = self._stack()
        with TestClient(app) as c:
            grande = c.post("/oauth/register", content=b"x" * 1_000_000)
            normal = c.post("/oauth/register", content=b"x" * 500)
        self.assertEqual(grande.status_code, 413)
        self.assertEqual(normal.status_code, 200)

    def test_the_413_carries_security_headers(self) -> None:
        """el 413 se generaba por fuera de SecurityHeaders."""
        from starlette.testclient import TestClient

        app, _ = self._stack()
        with TestClient(app) as c:
            r = c.post("/oauth/register", content=b"x" * 1_000_000)
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(r.headers.get("x-frame-options"), "DENY")

    def test_production_order_puts_body_limit_after_auth(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1]
        src = (root / "hermes/src/hermes/__main__.py").read_text(encoding="utf-8")
        stack = src[src.index("middleware_stack = ["):src.index("# Combinar rutas")]
        self.assertLess(stack.index("OAuthBearerAuth"), stack.index("BodySizeLimitMiddleware"))
        self.assertLess(stack.index("SecurityHeadersMiddleware"), stack.index("OAuthBearerAuth"))

    def test_uvicorn_has_a_concurrency_cap(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1]
        src = (root / "hermes/src/hermes/__main__.py").read_text(encoding="utf-8")
        self.assertIn("limit_concurrency=", src)


class TestRegistrationHasContentLimits(unittest.IsolatedAsyncioTestCase):
    """el registro DCR no acotaba el CONTENIDO, solo el número de clientes.

    `MAX_REGISTERED_CLIENTS` (100) existía y funciona, pero dentro de cada
    registro no había limite ninguno: `client_name` se tomaba sin comprobar
    siquiera el tipo y `redirect_uris` no tenía tope de elementos ni de
    longitud. `/oauth/register` es público —lo exige RFC 7591—, así que
    cualquiera podia escribir a disco lo que quisiera dentro de esos 100.
    """

    _ATRIBUTOS = ("_OAUTH_DIR", "_CLIENTS_DIR", "_CODES_DIR", "_TOKENS_DIR")

    class _Peticion:
        def __init__(self, cuerpo: dict) -> None:
            self._cuerpo = cuerpo

        async def json(self) -> dict:
            return self._cuerpo

    async def asyncSetUp(self) -> None:
        import hermes.oauth as oauth

        self.oauth = oauth
        self._orig = {a: getattr(oauth, a) for a in self._ATRIBUTOS}
        self._tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self._tmp.name) / "oauth"
        oauth._OAUTH_DIR = base
        oauth._CLIENTS_DIR = base / "clients"
        oauth._CODES_DIR = base / "codes"
        oauth._TOKENS_DIR = base / "tokens"
        self.server = oauth.OAuthServer(
            auth_password="test-password-1234",
            public_hostname="hermes.tail-xxxx.ts.net",
        )

    async def asyncTearDown(self) -> None:
        for a, v in self._orig.items():
            setattr(self.oauth, a, v)
        self._tmp.cleanup()

    async def _registrar(self, **campos):
        cuerpo = {"redirect_uris": ["https://claude.ai/api/mcp/auth_callback"]}
        cuerpo.update(campos)
        return await self.server.register_client(self._Peticion(cuerpo))

    async def test_a_huge_client_name_is_rejected(self) -> None:
        resp = await self._registrar(client_name="A" * 100_000)
        self.assertEqual(resp.status_code, 400)

    async def test_a_huge_name_is_never_written_to_disk(self) -> None:
        """Lo que importa no es el código, es que no acabe almacenado."""
        await self._registrar(client_name="A" * 100_000)
        ficheros = list(self.oauth._CLIENTS_DIR.glob("*.json")) if \
            self.oauth._CLIENTS_DIR.exists() else []
        self.assertEqual(ficheros, [], "el registro rechazado dejo rastro en disco")

    async def test_too_many_redirect_uris_are_rejected(self) -> None:
        resp = await self._registrar(
            redirect_uris=[f"https://c{i}.example/cb" for i in range(50)])
        self.assertEqual(resp.status_code, 400)

    async def test_a_huge_redirect_uri_is_rejected(self) -> None:
        resp = await self._registrar(
            redirect_uris=["https://claude.ai/cb?x=" + "y" * 50_000])
        self.assertEqual(resp.status_code, 400)

    async def test_a_non_string_name_is_rejected(self) -> None:
        """Antes ni se comprobaba el tipo: un dict acababa en el JSON."""
        resp = await self._registrar(client_name={"$ref": "algo"})
        self.assertEqual(resp.status_code, 400)

    async def test_a_normal_registration_still_works(self) -> None:
        resp = await self._registrar(client_name="Claude")
        self.assertEqual(resp.status_code, 201)

    async def test_an_absent_name_still_works(self) -> None:
        resp = await self.server.register_client(
            self._Peticion({"redirect_uris": ["https://claude.ai/cb"]}))
        self.assertEqual(resp.status_code, 201)

    async def test_an_explicit_null_name_still_works(self) -> None:
        """Antes se aceptaba; rechazarlo ahora sería romper lo que funciona."""
        resp = await self._registrar(client_name=None)
        self.assertEqual(resp.status_code, 201)

    async def test_two_uris_are_fine(self) -> None:
        resp = await self._registrar(
            redirect_uris=["https://claude.ai/cb", "https://claude.com/cb"])
        self.assertEqual(resp.status_code, 201)


class TestWebSocketOptionIsWired(unittest.TestCase):
    """`ha_ws_max_msg_size_bytes` no tocaba la WebSocket.

    Se cableaba al tamaño del cuerpo HTTP, así que subirla a 16 MiB no movía
    nada y el frame seguía topado en el default de aiohttp. Un único resultado
    grande derribaba TODA la WS, no solo esa llamada.
    """

    def test_the_option_reaches_ws_connect(self) -> None:
        """Comportamiento, no texto: el valor tiene que LLEGAR a aiohttp.

        La primera versión de este test miraba el código fuente y por eso
        detecto que el arreglo estaba a medias (el cliente aceptaba el
        parametro y nadie lo usaba). Este lo ejecuta de verdad.
        """
        import asyncio

        from hermes.ha import HAClient

        recibido: dict = {}

        class _Alto(Exception):
            pass

        class _CtxWS:
            async def __aenter__(self):
                raise _Alto

            async def __aexit__(self, *exc):
                return False

        class _SesionFalsa:
            closed = False

            def ws_connect(self, url, **kwargs):
                recibido.update(kwargs)
                return _CtxWS()

        class _SaludFalsa:
            def set_ws_connected(self, _v):
                pass

        cliente = HAClient(
            supervisor_base_url="http://supervisor",
            supervisor_token="t",
            health_server=_SaludFalsa(),
            ws_max_msg_size=7_654_321,
        )
        cliente._session = _SesionFalsa()

        async def _correr():
            with self.assertRaises(_Alto):
                await cliente._connect_and_watch()

        asyncio.run(_correr())
        self.assertEqual(recibido.get("max_msg_size"), 7_654_321,
                         "el tope configurado no llega a ws_connect")

    def test_the_default_is_not_the_aiohttp_one(self) -> None:
        """Sin configurar nada, el tope debe seguir siendo explicito."""
        import inspect

        from hermes.ha import HAClient

        por_defecto = inspect.signature(HAClient.__init__).parameters[
            "ws_max_msg_size"].default
        self.assertGreaterEqual(por_defecto, 4_194_304)

    def test_the_http_body_limit_has_its_own_option(self) -> None:
        """Ya no comparte opción con la WebSocket."""
        from hermes.config import HermesConfig

        self.assertIn("max_request_body_bytes", HermesConfig.__dataclass_fields__)
        root = pathlib.Path(__file__).resolve().parents[1]
        src = (root / "hermes/src/hermes/__main__.py").read_text(encoding="utf-8")
        self.assertNotIn("max_body_bytes=config.ha_ws_max_msg_size_bytes", src)

class TestOptionsAreWiredEndToEnd(unittest.TestCase):
    """Una opción solo sirve si recorre las TRES capas.

    Al separar el tope del cuerpo HTTP del de la WebSocket se añadieron dos
    opciones a `config.py` y se quedaron
    ahi: sin entrada en `config.yaml` no salen en la UI del add-on, y sin
    `export` en `run.sh` el proceso nunca ve la variable, así que el usuario
    podia cambiarlas y no pasaba absolutamente nada.

    Es el mismo tipo de fallo que la opción del WebSocket: algo documentado que
    no estaba
    conectada a nada—, así que se comprueba la cadena entera, no una capa.
    """

    @classmethod
    def setUpClass(cls) -> None:
        raiz = pathlib.Path(__file__).resolve().parents[1]
        cls.config_py = (raiz / "hermes/src/hermes/config.py").read_text(encoding="utf-8")
        cls.run_sh = (raiz / "hermes" / "run.sh").read_text(encoding="utf-8")
        cls.config_yaml = (raiz / "hermes" / "config.yaml").read_text(encoding="utf-8")

    def test_every_env_var_read_is_exported(self) -> None:
        leidas = set(re.findall(r'"(HERMES_[A-Z0-9_]+)"', self.config_py))
        exportadas = set(re.findall(r"export (HERMES_[A-Z0-9_]+)=", self.run_sh))
        huerfanas = leidas - exportadas
        self.assertEqual(
            huerfanas, set(),
            f"config.py lee variables que run.sh no exporta: {sorted(huerfanas)}")

    def test_every_option_is_read_by_the_launcher(self) -> None:
        y = self.config_yaml
        bloque = y[y.index("\noptions:\n"):]
        opciones = set(re.findall(r"^  ([a-z0-9_]+):", bloque, re.M))
        usadas = set(re.findall(r"cfg(?:_default)? ([a-z0-9_]+)", self.run_sh))
        usadas |= set(re.findall(r"\.([a-z0-9_]+) // \[\]", self.run_sh))
        self.assertEqual(opciones - usadas, set(),
                         "opciones de config.yaml que run.sh nunca lee")

    def test_schema_and_defaults_agree(self) -> None:
        """Toda opción con default declarado tiene que estar en el schema."""
        y = self.config_yaml
        schema = y[y.index("\nschema:\n"):y.index("\noptions:\n")]
        bloque = y[y.index("\noptions:\n"):]
        en_schema = set(re.findall(r"^  ([a-z0-9_]+):", schema, re.M))
        en_options = set(re.findall(r"^  ([a-z0-9_]+):", bloque, re.M))
        self.assertEqual(en_options - en_schema, set(),
                         "hay defaults sin entrada en el schema")

    def test_the_new_resource_limits_are_present(self) -> None:
        for opción in ("max_request_body_bytes", "max_concurrent_requests"):
            self.assertIn(opción, self.config_yaml, f"{opción} no sale en la UI")
            self.assertIn(opción, self.run_sh, f"{opción} no llega al proceso")

class TestTheClientIpIsRealAndCannotBeForged(unittest.TestCase):
    """De donde sale la IP que ve el rate limit — y por que no se falsifica.

    El código afirmaba que tras el Funnel todas las conexiones llegan desde
    127.0.0.1 y que por tanto el cubo por IP era global. Es falso: uvicorn
    monta `ProxyHeadersMiddleware` por defecto con `forwarded_allow_ips`
    "127.0.0.1", tailscaled hace proxy desde el loopback, y la IP real llega.
    Con el proxy en el loopback, cada petición trae la IP real del cliente.

    Falsificarla no funciona: cuatro variantes de X-Forwarded-For contra
    producción (una entrada, cadena, solo loopback, sin cabecera) se
    registraron todas con la misma IP real. Este test fija el porque —el
    comportamiento de la dependencia— para que un cambio de versión de uvicorn
    no lo altere en silencio.
    """

    def _resuelve(self, xff: str, par: str = "127.0.0.1") -> str:
        """Que IP acaba viendo la app con esa cabecera y ese par TCP."""
        import asyncio

        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

        visto = {}

        async def app(scope, receive, send):
            visto["cliente"] = scope["client"][0]

        cabeceras = [(b"host", b"x")]
        if xff:
            cabeceras.append((b"x-forwarded-for", xff.encode()))
        scope = {"type": "http", "headers": cabeceras, "client": (par, 12345),
                 "scheme": "http"}
        asyncio.run(ProxyHeadersMiddleware(app, trusted_hosts="127.0.0.1")(
            scope, None, None))
        return visto["cliente"]

    def test_a_single_forged_hop_does_not_win(self) -> None:
        """El proxy de verdad anade su valor; el último no-confiable manda."""
        self.assertEqual(self._resuelve("203.0.113.7, 198.51.100.9"), "198.51.100.9")

    def test_the_real_ip_reaches_the_app(self) -> None:
        self.assertEqual(self._resuelve("198.51.100.9"), "198.51.100.9")

    def test_an_untrusted_peer_is_not_believed(self) -> None:
        """Modo reverse_proxy: si el par no es loopback, la cabecera se ignora."""
        self.assertEqual(self._resuelve("203.0.113.7", par="172.30.32.5"),
                         "172.30.32.5")

    def test_without_the_header_the_peer_stands(self) -> None:
        self.assertEqual(self._resuelve(""), "127.0.0.1")

    def test_nothing_authorises_by_ip(self) -> None:
        """La IP solo vale para rate limit y logs; nunca para dar acceso.

        Es lo que hace que el caveat del modo reverse_proxy sea tolerable: aun
        si un día llegara una IP falseada, no habría escalada de privilegio.
        """
        raiz = pathlib.Path(__file__).resolve().parents[1] / "hermes/src/hermes"
        for fichero in raiz.rglob("*.py"):
            texto = fichero.read_text(encoding="utf-8")
            for n, linea in enumerate(texto.splitlines(), 1):
                if "client.host" not in linea:
                    continue
                contexto = "\n".join(texto.splitlines()[max(0, n - 2):n + 6])
                self.assertNotIn("return True", contexto,
                                 f"{fichero.name}:{n} parece autorizar por IP")

class TestWriteRateLimitSurvivesConcurrency(unittest.IsolatedAsyncioTestCase):
    """el freno de escrituras se saltaba pidiendo las cosas a la vez.

    `check_rate_limit()` comprobaba y una funcion aparte apuntaba la escritura
    después. Entre una cosa y otra no había nada, así que varias llamadas
    concurrentes pasaban el mismo control con el mismo estado — un
    check-then-act de manual.

    No era teorico: el cliente MCP lanza rafagas en paralelo, es su modo normal
    de trabajar. Con el limite en «1 escritura cada 5s», 24 llamadas a la vez
    pasaban las 24.

    El freno protege /config: es lo que impide que un bucle del cliente, o una
    instruccion colada en cualquier dato que Claude lea, reescriba la
    configuración decenas de veces seguidas.
    """

    def setUp(self) -> None:
        import hermes.fs_write as fw

        self.fw = fw
        self._orig = fw.WRITE_RATE_LIMIT_PATH
        self._tmp = tempfile.TemporaryDirectory()
        fw.WRITE_RATE_LIMIT_PATH = pathlib.Path(self._tmp.name) / "rate.json"

    def tearDown(self) -> None:
        self.fw.WRITE_RATE_LIMIT_PATH = self._orig
        self._tmp.cleanup()

    async def _intento(self):
        import asyncio

        try:
            await self.fw.reserve_write_slot(min_interval_seconds=5, max_per_minute=10)
        except self.fw.RateLimitError:
            return False
        # Trabajo real entre reservar y escribir: backup, escritura, etc.
        await asyncio.sleep(0.01)
        return True

    async def test_a_parallel_burst_gets_exactly_one_slot(self) -> None:
        import asyncio

        res = await asyncio.gather(*(self._intento() for _ in range(24)))
        self.assertEqual(sum(res), 1,
                         f"pasaron {sum(res)} escrituras donde solo cabia 1")

    async def test_sequential_calls_still_respect_the_interval(self) -> None:
        self.assertTrue(await self._intento())
        self.assertFalse(await self._intento())

    async def test_the_slot_is_taken_the_moment_it_is_granted(self) -> None:
        """Sin funcion aparte que apunte después: no queda ventana."""
        import json

        await self.fw.reserve_write_slot(min_interval_seconds=5, max_per_minute=10)
        estado = json.loads(self.fw.WRITE_RATE_LIMIT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(estado["timestamps"]), 1,
                         "la reserva no quedo anotada en el mismo paso")

    async def test_there_is_no_record_function_left_to_forget(self) -> None:
        """Si volviera a existir, volveria la ventana entre comprobar y apuntar."""
        self.assertFalse(hasattr(self.fw, "record_write"))
        self.assertFalse(hasattr(self.fw, "check_rate_limit"))

    async def test_a_full_window_still_blocks(self) -> None:
        """El otro freno (max por minuto) sigue en pie."""
        import json
        import time

        ahora = time.time()
        # Diez escrituras dentro de la ventana, la ultima hace 6s (pasa el
        # intervalo minimo) -> solo puede pararlo el maximo por minuto.
        self.fw.WRITE_RATE_LIMIT_PATH.write_text(
            json.dumps({"timestamps": [ahora - 6 - i * 3 for i in range(10)]}),
            encoding="utf-8")
        with self.assertRaises(self.fw.RateLimitError):
            await self.fw.reserve_write_slot(min_interval_seconds=5, max_per_minute=10)

class TestStateCacheDoesNotLoseUpdates(unittest.TestCase):
    """la cache de estados perdia cambios por dos vias distintas.

    se pedia el snapshot REST y DESPUES se suscribia a los eventos. Todo
    lo que cambiara entre una cosa y otra no lo veia nadie: la entrada se
    quedaba con el valor viejo hasta que esa entidad volviera a cambiar, y
    `ha_get_state` lo servía sin avisar de nada. En una casa con cientos de
    entidades, esa ventana cae encima de algo con facilidad.

    cada evento lanzaba `asyncio.create_task(...)` sin guardar la
    referencia. El loop solo guarda una referencia debil y la documentacion de
    asyncio avisa expresamente: el recolector puede llevarse la tarea a medias
    y la actualizacion se pierde en silencio.
    """

    def _cliente(self, **kw):
        from hermes.ha import HAClient

        class _Salud:
            def set_ws_connected(self, _v):
                pass

        return HAClient(supervisor_base_url="http://supervisor",
                        supervisor_token="t", health_server=_Salud(), **kw)

    def test_subscribing_happens_before_the_snapshot(self) -> None:
        import asyncio

        orden = []

        class _Alto(Exception):
            pass

        class _CtxWS:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *exc):
                return False

        class _Sesion:
            closed = False

            def ws_connect(self, url, **kw):
                return _CtxWS()

        cliente = self._cliente()
        cliente._session = _Sesion()

        async def _marca(nombre):
            orden.append(nombre)

        cliente._authenticate_ws = lambda: _marca("auth")
        cliente._subscribe_state_changes = lambda: _marca("suscribir")
        cliente._populate_state_cache = lambda: _marca("snapshot")

        async def _fin():
            raise _Alto

        cliente._read_ws_messages = _fin

        async def _correr():
            with self.assertRaises(_Alto):
                await cliente._connect_and_watch()

        asyncio.run(_correr())
        self.assertEqual(orden, ["auth", "suscribir", "snapshot"],
                         "el snapshot se toma antes de suscribirse: se pierden cambios")

    def _evento(self, entity_id, estado, marca):
        return {"type": "event", "event": {
            "event_type": "state_changed",
            "time_fired": marca,
            "data": {"entity_id": entity_id,
                     "new_state": {"entity_id": entity_id, "state": estado,
                                   "last_updated": marca}}}}

    def test_an_event_is_applied_without_a_detour(self) -> None:
        """Al esperar el manejador, el cambio ya esta puesto. Sin tareas sueltas."""
        import asyncio

        cliente = self._cliente()

        async def _correr():
            await cliente._handle_ws_message(
                self._evento("light.cocina", "on", "2026-09-06T10:00:00+00:00"))
            # Sin ceder el control: si hiciera falta un salto de planificacion,
            # aquí todavia no habría nada.
            return dict(cliente._state_cache)

        cache = asyncio.run(_correr())
        self.assertEqual(cache["light.cocina"]["state"], "on")

    def test_an_older_event_does_not_overwrite_a_newer_state(self) -> None:
        """Suscribir primero implica procesar eventos anteriores al snapshot."""
        import asyncio

        cliente = self._cliente()

        async def _correr():
            await cliente._handle_ws_message(
                self._evento("light.cocina", "on", "2026-09-06T10:00:05+00:00"))
            await cliente._handle_ws_message(
                self._evento("light.cocina", "off", "2026-09-06T10:00:00+00:00"))
            return dict(cliente._state_cache)

        cache = asyncio.run(_correr())
        self.assertEqual(cache["light.cocina"]["state"], "on",
                         "un evento viejo piso uno nuevo")

    def test_a_newer_event_does_win(self) -> None:
        import asyncio

        cliente = self._cliente()

        async def _correr():
            await cliente._handle_ws_message(
                self._evento("light.cocina", "on", "2026-09-06T10:00:00+00:00"))
            await cliente._handle_ws_message(
                self._evento("light.cocina", "off", "2026-09-06T10:00:05+00:00"))
            return dict(cliente._state_cache)

        cache = asyncio.run(_correr())
        self.assertEqual(cache["light.cocina"]["state"], "off")

    def test_without_timestamps_it_still_writes(self) -> None:
        """Sin marcas utilizables se conserva el comportamiento de siempre."""
        import asyncio

        cliente = self._cliente()

        async def _correr():
            for estado in ("on", "off"):
                await cliente._handle_ws_message({"type": "event", "event": {
                    "event_type": "state_changed",
                    "data": {"entity_id": "light.x",
                             "new_state": {"entity_id": "light.x", "state": estado}}}})
            return dict(cliente._state_cache)

        cache = asyncio.run(_correr())
        self.assertEqual(cache["light.x"]["state"], "off")

    def test_a_removal_still_removes(self) -> None:
        import asyncio

        cliente = self._cliente()

        async def _correr():
            await cliente._handle_ws_message(
                self._evento("light.cocina", "on", "2026-09-06T10:00:00+00:00"))
            await cliente._handle_ws_message({"type": "event", "event": {
                "event_type": "state_changed",
                "time_fired": "2026-09-06T10:00:05+00:00",
                "data": {"entity_id": "light.cocina", "new_state": None}}})
            return dict(cliente._state_cache)

        self.assertEqual(asyncio.run(_correr()), {})

    def test_no_stray_tasks_are_spawned(self) -> None:
        """ninguna tarea sin referencia fuerte en el cliente de HA.

        Por AST y no por texto: la primera versión buscaba la cadena en el
        fuente y se disparaba con el comentario que explica el arreglo.
        """
        import ast as _ast
        import pathlib as _pathlib

        raiz = _pathlib.Path(__file__).resolve().parents[1] / "hermes/src/hermes"
        sueltas = []
        for fichero in raiz.rglob("*.py"):
            arbol = _ast.parse(fichero.read_text(encoding="utf-8"))
            referenciadas = set()
            for nodo in _ast.walk(arbol):
                if isinstance(nodo, (_ast.Assign, _ast.AnnAssign, _ast.Return,
                                     _ast.Await)):
                    for hijo in _ast.walk(nodo):
                        if isinstance(hijo, _ast.Call):
                            referenciadas.add(id(hijo))
                elif isinstance(nodo, _ast.Call):
                    for arg in list(nodo.args) + [k.value for k in nodo.keywords]:
                        for hijo in _ast.walk(arg):
                            if isinstance(hijo, _ast.Call):
                                referenciadas.add(id(hijo))
            for nodo in _ast.walk(arbol):
                if not isinstance(nodo, _ast.Call):
                    continue
                f = nodo.func
                nombre = (f.attr if isinstance(f, _ast.Attribute)
                          else getattr(f, "id", ""))
                if nombre == "create_task" and id(nodo) not in referenciadas:
                    sueltas.append(f"{fichero.name}:{nodo.lineno}")
        self.assertEqual(sueltas, [],
                         f"tareas sin referencia fuerte: {sueltas}")

class TestSubscriptionIsNeverOrphaned(unittest.IsolatedAsyncioTestCase):
    """si la confirmación no llegaba, la suscripcion se quedaba viva en HA.

    `ws_subscribe_events_queue` monta tres cosas antes de mandar el
    `subscribe_events`: la cola, el future pendiente y la suscripcion del lado
    de HA. Al agotarse el plazo solo se quitaba la cola. El `sub_id` no llegaba
    a devolverse —la excepcion sale antes—, así que el `finally` de quien
    llamaba se encontraba `None` y no cancelaba nada.

    Si HA había creado la suscripcion y lo único lento fue la confirmación, HA
    seguia mandando ese tipo de evento por la WebSocket indefinidamente, sin
    nadie leyendo. Cada `ha_wait_for_event` que fallara así dejaba otro.
    """

    def _cliente(self):
        from hermes.ha import HAClient

        class _Salud:
            def set_ws_connected(self, _v):
                pass

        cliente = HAClient(supervisor_base_url="http://supervisor",
                           supervisor_token="t", health_server=_Salud())
        self.enviados = []

        class _WS:
            closed = False

            async def send_json(_self, payload):
                self.enviados.append(payload)

        cliente._ws = _WS()
        return cliente

    async def test_a_timeout_cancels_the_subscription_in_ha(self) -> None:
        from hermes.ha import HAConnectionError

        cliente = self._cliente()
        # La confirmación no llega nunca: el future se queda sin resolver.
        with unittest.mock.patch("hermes.ha.asyncio.wait_for",
                                 side_effect=__import__("asyncio").TimeoutError):
            with self.assertRaises(HAConnectionError):
                await cliente.ws_subscribe_events_queue("call_service")

        tipos = [p.get("type") for p in self.enviados]
        self.assertIn("subscribe_events", tipos)
        self.assertIn("unsubscribe_events", tipos,
                      "se dejo la suscripcion viva en Home Assistant")

    async def test_a_timeout_leaves_nothing_behind(self) -> None:
        from hermes.ha import HAConnectionError

        cliente = self._cliente()
        with unittest.mock.patch("hermes.ha.asyncio.wait_for",
                                 side_effect=__import__("asyncio").TimeoutError):
            with self.assertRaises(HAConnectionError):
                await cliente.ws_subscribe_events_queue("call_service")

        self.assertEqual(cliente._event_subscription_queues, {})
        self.assertEqual(cliente._pending_ws_responses, {},
                         "el future pendiente se queda hasta la reconexion")

    async def test_a_refusal_from_ha_leaves_nothing_behind(self) -> None:
        """El otro camino: HA responde que no. Tambien dejaba la cola puesta."""
        from hermes.ha import HAConnectionError

        cliente = self._cliente()
        with unittest.mock.patch("hermes.ha.asyncio.wait_for",
                                 side_effect=HAConnectionError("no")):
            with self.assertRaises(HAConnectionError):
                await cliente.ws_subscribe_events_queue("call_service")

        self.assertEqual(cliente._event_subscription_queues, {})
        self.assertEqual(cliente._pending_ws_responses, {})

    async def test_a_good_subscription_is_not_cancelled(self) -> None:
        cliente = self._cliente()

        async def _ok(fut, timeout=None):
            return {"success": True}

        with unittest.mock.patch("hermes.ha.asyncio.wait_for", new=_ok):
            sub_id, cola, gen = await cliente.ws_subscribe_events_queue("call_service")

        tipos = [p.get("type") for p in self.enviados]
        self.assertEqual(tipos, ["subscribe_events"])
        self.assertIn(sub_id, cliente._event_subscription_queues)

class TestAnnotationFailureIsNotSilent(unittest.TestCase):
    """si no se podia anotar nada, no se enteraba nadie.

    `apply_tool_annotations` alcanza el registro de tools por un detalle
    interno del SDK (`mcp._tool_manager._tools`). Si un día lo renombran,
    NINGUNA tool queda anotada y el cliente pierde la única senal que tiene
    para distinguir lo que solo lee de lo que borra o reinicia.

    El código devolvia ceros con un comentario diciendo que «no es crítico», y
    el llamador solo escribia en el log cuando el recuento era distinto de
    cero. O sea: el caso bueno dejaba rastro y el malo no.

    Las protecciones de verdad —tokens de confirmación, denylist— viven en el
    servidor y siguen en pie, así que no se aborta el arranque. Pero tiene que
    verse.
    """

    class _Log:
        def __init__(self):
            self.errores = []
            self.avisos = []
            self.infos = []

        def error(self, evento, **kw):
            self.errores.append((evento, kw))

        def warning(self, evento, **kw):
            self.avisos.append((evento, kw))

        def info(self, evento, **kw):
            self.infos.append((evento, kw))

    def test_a_missing_registry_is_reported(self) -> None:
        from hermes.tools import _annotations

        registro = self._Log()
        with unittest.mock.patch.object(_annotations, "logger", registro):
            stats = _annotations.apply_tool_annotations(object())

        self.assertEqual(stats["annotated"], 0)
        self.assertTrue(registro.errores, "el fallo no dejo rastro en el log")
        evento, campos = registro.errores[0]
        self.assertEqual(evento, "tool_annotations_unavailable")
        self.assertIn("reason", campos)

    def test_an_empty_registry_is_reported(self) -> None:
        from hermes.tools import _annotations

        class _Vacio:
            class _Manager:
                _tools: dict = {}

            _tool_manager = _Manager()

        registro = self._Log()
        with unittest.mock.patch.object(_annotations, "logger", registro):
            _annotations.apply_tool_annotations(_Vacio())

        self.assertTrue(registro.avisos, "un registro vacio pasaba inadvertido")

    def test_the_happy_path_stays_quiet(self) -> None:
        """Sin ruido cuando todo va bien: si no, el aviso no significa nada."""
        from mcp.server.mcpserver import MCPServer

        from hermes.tools import _annotations

        mcp = MCPServer("test-anotaciones")

        @mcp.tool()
        async def ha_get_states(domain: str | None = None) -> object:
            """Lista estados."""
            return {}

        registro = self._Log()
        with unittest.mock.patch.object(_annotations, "logger", registro):
            stats = _annotations.apply_tool_annotations(mcp)

        self.assertEqual(stats["annotated"], 1)
        self.assertEqual(registro.errores, [])
        self.assertEqual(registro.avisos, [])

    def test_the_caller_logs_the_bad_case_too(self) -> None:
        """El llamador solo registraba el caso bueno."""
        import inspect

        from hermes import tools

        fuente = inspect.getsource(tools.register_all_tools)
        i = fuente.index("apply_tool_annotations(mcp)")
        self.assertIn("else:", fuente[i:],
                      "el arranque sigue sin decir nada cuando no se anota nada")

class TestRefreshTokensRotate(unittest.IsolatedAsyncioTestCase):
    """el refresh token era eterno durante 7 días y reutilizable.

    Es el único credencial duradero del sistema: quien lo tenga fabrica access
    tokens durante una semana, sin la password y sin que nada lo delate — el
    cliente legítimo sigue funcionando igual, así que el robo es invisible.

    Y además se acumulaban: cada autorizacion creaba uno nuevo sin tocar los
    anteriores. Observado antes del arreglo: **21 refresh
    tokens vivos** a la vez, para un servidor de un solo usuario con un único
    cliente conectado.
    """

    _ATRIBUTOS = ("_OAUTH_DIR", "_CLIENTS_DIR", "_CODES_DIR", "_TOKENS_DIR")

    class _Form(dict):
        pass

    async def asyncSetUp(self) -> None:
        import hermes.oauth as oauth

        self.oauth = oauth
        self._orig = {a: getattr(oauth, a) for a in self._ATRIBUTOS}
        self._tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self._tmp.name) / "oauth"
        oauth._OAUTH_DIR = base
        oauth._CLIENTS_DIR = base / "clients"
        oauth._CODES_DIR = base / "codes"
        oauth._TOKENS_DIR = base / "tokens"
        for d in (oauth._CLIENTS_DIR, oauth._CODES_DIR, oauth._TOKENS_DIR):
            d.mkdir(parents=True, exist_ok=True)
        self.server = oauth.OAuthServer(
            auth_password="test-password-1234",
            public_hostname="hermes.tail-xxxx.ts.net",
        )

    async def asyncTearDown(self) -> None:
        for a, v in self._orig.items():
            setattr(self.oauth, a, v)
        self._tmp.cleanup()

    def _sembrar_refresh(self, client_id="cli-1"):
        """Crea un refresh token valido directamente, como si vinieras del login."""
        import time

        tok = self.oauth._generate_token()
        h = self.oauth._hash_token(tok)
        self.oauth._atomic_write(self.oauth._TOKENS_DIR / f"{h}.json", {
            "token_hash": h,
            "token_type": "refresh",
            "client_id": client_id,
            "sub": self.oauth._FIXED_SUB,
            "scope": "mcp",
            "created_at": time.time(),
            "expires_at": time.time() + self.oauth.REFRESH_TOKEN_TTL,
        })
        return tok

    async def _refrescar(self, tok, client_id="cli-1"):
        import json

        resp = await self.server._token_refresh(
            self._Form({"refresh_token": tok, "client_id": client_id}))
        return resp.status_code, json.loads(bytes(resp.body).decode())

    async def test_a_refresh_returns_a_new_refresh_token(self) -> None:
        tok = self._sembrar_refresh()
        estado, cuerpo = await self._refrescar(tok)
        self.assertEqual(estado, 200, cuerpo)
        self.assertIn("refresh_token", cuerpo, "no rota: devuelve el mismo de siempre")
        self.assertNotEqual(cuerpo["refresh_token"], tok)

    async def test_the_new_one_works(self) -> None:
        tok = self._sembrar_refresh()
        _, cuerpo = await self._refrescar(tok)
        estado, cuerpo2 = await self._refrescar(cuerpo["refresh_token"])
        self.assertEqual(estado, 200, cuerpo2)

    async def test_reusing_the_old_one_is_refused_and_burns_the_chain(self) -> None:
        """Dos copias del mismo token = alguien lo copio. Caen las dos."""
        import time

        tok = self._sembrar_refresh()
        _, cuerpo = await self._refrescar(tok)
        nuevo = cuerpo["refresh_token"]

        # Fuera de la ventana de gracia.
        h = self.oauth._hash_token(tok)
        ruta = self.oauth._TOKENS_DIR / f"{h}.json"
        datos = self.oauth._safe_read(ruta)
        datos["rotated_at"] = time.time() - self.oauth.REFRESH_ROTATION_GRACE_SECONDS - 10
        self.oauth._atomic_write(ruta, datos)

        estado, cuerpo2 = await self._refrescar(tok)
        self.assertEqual(estado, 400)
        self.assertEqual(cuerpo2.get("error"), "invalid_grant")

        # Y el sucesor también queda revocado: no se sabe cual es el del dueno.
        estado3, _ = await self._refrescar(nuevo)
        self.assertEqual(estado3, 400, "el sucesor sobrevivio a la reutilizacion")

    async def test_a_retry_inside_the_grace_window_still_works(self) -> None:
        """Si la respuesta se pierde, el cliente reintenta con el token viejo."""
        tok = self._sembrar_refresh()
        _, cuerpo = await self._refrescar(tok)
        estado, cuerpo2 = await self._refrescar(tok)
        self.assertEqual(estado, 200, cuerpo2)
        self.assertIn("access_token", cuerpo2)

    async def _canjear_codigo(self, client_id="cli-1"):
        """Recorre el intercambio de código de verdad, con PKCE incluido.

        La primera versión de este test llamaba directamente a
        `_revoke_previous_sessions`, así que quitar la llamada del intercambio
        no lo rompia: el control negativo lo destapo.
        """
        import hashlib
        import json
        import time
        from base64 import urlsafe_b64encode

        verifier = "v" * 64
        challenge = urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        code = self.oauth._generate_token()
        self.oauth._atomic_write(
            self.oauth._CODES_DIR / f"{self.oauth._hash_token(code)}.json", {
                "client_id": client_id,
                "redirect_uri": "https://claude.ai/cb",
                "code_challenge": challenge,
                "scope": "mcp",
                "expires_at": time.time() + 60,
            })
        resp = await self.server._token_auth_code(self._Form({
            "code": code, "client_id": client_id,
            "redirect_uri": "https://claude.ai/cb", "code_verifier": verifier,
        }))
        return resp.status_code, json.loads(bytes(resp.body).decode())

    async def test_rotation_does_not_extend_the_deadline(self) -> None:
        """Si la caducidad se estirara, una sesión no terminaria nunca.

        Se siembra una caducidad distintiva: con `time.time() + TTL` en ambos
        lados, un reloj de poca resolucion podia dar el mismo número y el test
        pasaba por casualidad (lo destapo el control negativo).
        """
        import time

        tok = self._sembrar_refresh()
        ruta = self.oauth._TOKENS_DIR / f"{self.oauth._hash_token(tok)}.json"
        datos = self.oauth._safe_read(ruta)
        datos["expires_at"] = time.time() + 12345.0
        self.oauth._atomic_write(ruta, datos)
        original = datos["expires_at"]

        _, cuerpo = await self._refrescar(tok)
        nuevo = self.oauth._safe_read(
            self.oauth._TOKENS_DIR
            / f"{self.oauth._hash_token(cuerpo['refresh_token'])}.json")["expires_at"]
        self.assertEqual(nuevo, original,
                         "rotar estiro la caducidad: la sesion no termina nunca")

    async def test_a_new_authorisation_retires_the_previous_sessions(self) -> None:
        """Por el camino real: lo que producia 21 refresh tokens vivos a la vez."""
        viejos = [self._sembrar_refresh() for _ in range(5)]

        estado, cuerpo = await self._canjear_codigo()
        self.assertEqual(estado, 200, cuerpo)

        for v in viejos:
            est, _ = await self._refrescar(v)
            self.assertEqual(est, 400, "una sesion vieja siguio sirviendo")

        est, _ = await self._refrescar(cuerpo["refresh_token"])
        self.assertEqual(est, 200, "se cargo la sesion recien creada")

    async def test_sessions_from_other_client_ids_are_capped(self) -> None:
        """Lo que de verdad producia 21 tokens vivos.

        La primera versión revocaba solo las del MISMO client_id, y no servía
        de nada: los 20 huerfanos de producción tenian cada uno el suyo, porque
        Claude hace un registro dinamico nuevo en cada autorizacion.
        """
        viejos = [self._sembrar_refresh(client_id=f"cli-viejo-{i}")
                  for i in range(20)]

        estado, cuerpo = await self._canjear_codigo(client_id="cli-nuevo")
        self.assertEqual(estado, 200, cuerpo)

        vivos = [t for t in viejos
                 if (await self._refrescar(t, client_id=""))[0] == 200]
        self.assertLessEqual(len(vivos), self.oauth.MAX_ACTIVE_SESSIONS - 1,
                             f"quedaron {len(vivos)} sesiones viejas vivas")

    async def test_the_most_recent_sessions_are_the_ones_kept(self) -> None:
        """Echar a las recientes dejaria fuera al dispositivo que si se usa."""
        import time

        marcados = []
        for i in range(8):
            tok = self._sembrar_refresh(client_id=f"cli-{i}")
            ruta = self.oauth._TOKENS_DIR / f"{self.oauth._hash_token(tok)}.json"
            datos = self.oauth._safe_read(ruta)
            datos["created_at"] = time.time() - (8 - i) * 3600
            self.oauth._atomic_write(ruta, datos)
            marcados.append(tok)

        await self._canjear_codigo(client_id="cli-nuevo")

        estados = [(await self._refrescar(t, client_id=""))[0] for t in marcados]
        # Las supervivientes tienen que ser las del final de la lista.
        vivas = [i for i, e in enumerate(estados) if e == 200]
        self.assertTrue(all(i >= len(marcados) - self.oauth.MAX_ACTIVE_SESSIONS
                            for i in vivas),
                        f"sobrevivieron sesiones antiguas en vez de las recientes: {vivas}")

    async def test_a_couple_of_devices_are_not_evicted(self) -> None:
        """Autorizar en el movil no puede echar al escritorio."""
        escritorio = self._sembrar_refresh(client_id="cli-escritorio")
        await self._canjear_codigo(client_id="cli-movil")
        estado, _ = await self._refrescar(escritorio, client_id="cli-escritorio")
        self.assertEqual(estado, 200, "se echo a un dispositivo legítimo")

class TestPathValuesAreValidatedWhereTheyAreUsed(unittest.TestCase):
    """cinco modulos metían valores en rutas de la API sin comprobarlos.

    La red de `_assert_safe_request_path` impide lo grave —
    salir del endpoint previsto—, pero no impide que un valor con '/' aterrice
    en un endpoint vecino, y no sabe qué forma debería tener cada cosa. El
    propio modulo de validadores nombraba `flow_id` y `job_id` como ids que hay
    que validar, y no se validaban en ninguno de los cinco sitios donde se
    interpolaban.
    """

    def _cliente(self):
        from hermes.ha import HAClient

        class _Salud:
            def set_ws_connected(self, _v):
                pass

        cliente = HAClient(supervisor_base_url="http://supervisor",
                           supervisor_token="t", health_server=_Salud())

        class _SesionQueNoDebeUsarse:
            closed = False

            def request(self, *a, **kw):
                raise AssertionError("se llegó a hacer la petición")

        cliente._session = _SesionQueNoDebeUsarse()
        return cliente

    def test_a_slash_in_an_entity_id_never_reaches_the_request(self) -> None:
        import asyncio

        from hermes.identifiers import InvalidIdentifier

        cliente = self._cliente()
        with self.assertRaises(InvalidIdentifier):
            asyncio.run(cliente.get_state("light.cocina/../../config/core"))

    def test_a_slash_in_a_service_never_reaches_the_request(self) -> None:
        import asyncio

        from hermes.identifiers import InvalidIdentifier

        cliente = self._cliente()
        with self.assertRaises(InvalidIdentifier):
            asyncio.run(cliente.call_service("homeassistant/x", "turn_on"))

    def test_percent_encoding_is_refused_too(self) -> None:
        """Nada de escapes que se resuelvan más tarde, cuando ya no se comprueba."""
        import asyncio

        from hermes.identifiers import InvalidIdentifier

        cliente = self._cliente()
        with self.assertRaises(InvalidIdentifier):
            asyncio.run(cliente.get_state("light.%2e%2e"))

    def test_a_normal_entity_id_is_not_refused(self) -> None:
        """El validador no impone formato: no puede rechazar uno legítimo raro."""
        from hermes.identifiers import validate_path_segment

        for bueno in ("light.cocina", "sensor.temperatura_2", "binary_sensor.x",
                      "sensor.ñoño", "climate.salón"):
            validate_path_segment(bueno, field="entity_id")

    def test_the_flow_path_validates(self) -> None:
        from hermes.identifiers import InvalidIdentifier
        from hermes.tools.config_entry_flows import _flow_path

        self.assertEqual(_flow_path("abc123"),
                         "/config/config_entries/flow/abc123")
        for malo in ("../../core/restart", "a/b", "x?y", ""):
            with self.assertRaises(InvalidIdentifier, msg=malo):
                _flow_path(malo)

    def test_every_module_that_builds_a_path_has_a_validator(self) -> None:
        """El inventario que destapó los cinco módulos, convertido en test."""
        import ast as _ast
        import pathlib as _pl

        raiz = _pl.Path(__file__).resolve().parents[1] / "hermes/src/hermes"
        # network.py y oauth.py solo interpolan la URL base de la configuración,
        # que no viene de ninguna petición.
        permitidos = {"network.py", "oauth.py"}
        sin = set()
        for f in sorted(raiz.rglob("*.py")):
            txt = f.read_text(encoding="utf-8")
            valida = any(v in txt for v in ("validate_identifier", "validate_slug",
                                            "validate_path_segment"))
            if valida or f.name in permitidos:
                continue
            for nodo in _ast.walk(_ast.parse(txt)):
                if not isinstance(nodo, _ast.JoinedStr):
                    continue
                partes = [p.value for p in nodo.values if isinstance(p, _ast.Constant)]
                tiene_valor = any(isinstance(v, _ast.FormattedValue) for v in nodo.values)
                if partes and partes[0].startswith("/") and tiene_valor:
                    sin.add(f.relative_to(raiz).as_posix())
        self.assertEqual(sin, set(),
                         f"módulos que construyen rutas sin validar: {sorted(sin)}")

    def test_there_is_a_single_definition_of_the_validators(self) -> None:
        """`tools/_validation` reexporta; no puede haber dos regex distintas."""
        from hermes import identifiers
        from hermes.tools import _validation

        self.assertIs(_validation.validate_identifier, identifiers.validate_identifier)
        self.assertIs(_validation.InvalidIdentifier, identifiers.InvalidIdentifier)


class TestPublicHostnameShape(unittest.TestCase):
    """El hostname acaba dentro de las URLs de descubrimiento OAuth.

    Solo se comprobaba que no estuviera vacío, aunque la documentación dice
    «sin esquema ni path». Un `https://` delante pasaba y el fallo aparecía
    mucho más tarde, como un flujo OAuth roto sin explicación.
    """

    def test_the_real_hostname_is_accepted(self) -> None:
        from hermes.config import _HOSTNAME_RE

        for bueno in ("homeassistant.tail1234.ts.net", "hermes.midominio.com",
                      "localhost", "hermes.local:8765"):
            self.assertTrue(_HOSTNAME_RE.match(bueno), bueno)

    def test_a_scheme_or_a_path_is_refused(self) -> None:
        from hermes.config import _HOSTNAME_RE

        for malo in ("https://hermes.ts.net", "hermes.ts.net/mcp",
                     "hermes.ts.net?x=1", "user:pw@hermes.ts.net", "a b.com",
                     "-mal.com", ""):
            self.assertIsNone(_HOSTNAME_RE.match(malo), malo)

    def test_the_config_refuses_it_at_boot(self) -> None:
        import dataclasses

        from hermes.config import HermesConfig

        campos = {f.name for f in dataclasses.fields(HermesConfig)}
        self.assertIn("public_hostname", campos)
        cfg = HermesConfig(
            auth_password="una-password-larga-y-aleatoria",
            public_hostname="https://hermes.ts.net",
            supervisor_token="t",
        )
        with self.assertRaises(ValueError) as ctx:
            cfg.validate()
        self.assertIn("public_hostname", str(ctx.exception))

class TestAddonInfoDoesNotShipTheWholeReadme(unittest.IsolatedAsyncioTestCase):
    """`sv_get_addon` devolvía el README entero del add-on en cada llamada.

    `long_description` suele ser la mayor parte de la respuesta —en un add-on
    con documentación larga, el 84 % de ella— y casi nunca se necesita. Se
    pagaba en cada llamada aunque nadie fuera a leerlo, desplazando contexto
    útil. Ahora se omite por defecto y se deja una nota con su tamaño.
    """

    class _MCP:
        def __init__(self):
            self.tools = {}

        def tool(self, *a, **kw):
            def dec(fn):
                self.tools[fn.__name__] = fn
                return fn
            return dec

    def _tools(self, respuesta):
        from hermes.tools.addons import register as registrar

        class _Cliente:
            async def sv_request(self, method, path, **kw):
                return dict(respuesta)

        mcp = self._MCP()
        registrar(mcp, _Cliente())
        return mcp.tools

    _INFO = {
        "slug": "local_hermes",
        "name": "Hermes",
        "version": "0.34.0",
        "state": "started",
        "long_description": "# README\n" + ("texto largo. " * 2000),
    }

    async def test_the_readme_is_left_out_by_default(self) -> None:
        tools = self._tools(self._INFO)
        res = await tools["sv_get_addon"]("local_hermes")
        self.assertNotIn("long_description", res)
        self.assertEqual(res["slug"], "local_hermes")

    async def test_it_says_that_it_left_it_out_and_how_to_get_it(self) -> None:
        """Callar sin más dejaría al cliente sin saber que existe."""
        tools = self._tools(self._INFO)
        res = await tools["sv_get_addon"]("local_hermes")
        nota = res.get("long_description_omitted")
        self.assertIsInstance(nota, dict)
        self.assertGreater(nota["bytes"], 1000)
        self.assertIn("include_long_description", nota["hint"])

    async def test_it_can_still_be_asked_for(self) -> None:
        tools = self._tools(self._INFO)
        res = await tools["sv_get_addon"]("local_hermes",
                                          include_long_description=True)
        self.assertIn("long_description", res)
        self.assertNotIn("long_description_omitted", res)

    async def test_the_rest_of_the_payload_is_untouched(self) -> None:
        tools = self._tools(self._INFO)
        res = await tools["sv_get_addon"]("local_hermes")
        for campo in ("slug", "name", "version", "state"):
            self.assertEqual(res[campo], self._INFO[campo])

    async def test_an_addon_without_a_readme_gets_no_note(self) -> None:
        tools = self._tools({"slug": "x", "name": "X"})
        res = await tools["sv_get_addon"]("x")
        self.assertNotIn("long_description_omitted", res)

    async def test_secrets_are_still_redacted(self) -> None:
        """La redacción de D1 sigue en pie: no se ha roto al meter esto."""
        tools = self._tools({
            "slug": "x",
            "options": {"auth_password": "supersecreto-en-claro"},
            "long_description": "y" * 5000,
        })
        res = await tools["sv_get_addon"]("x")
        self.assertNotIn("supersecreto-en-claro", json.dumps(res))

class TestNoModuleUsesANameItNeverImported(unittest.TestCase):
    """Un nombre usado y nunca importado no se nota hasta que se ejecuta.

    Python resuelve los nombres globales en tiempo de ejecución, así que un
    módulo con un `except NombreQueNoExiste` importa sin quejarse y la suite
    puede pasar entera en verde. El fallo aparece solo cuando se entra por esa
    rama — que, tratándose de guardas de seguridad, es justo el peor momento.

    Este test recorre el paquete buscando nombres usados y nunca definidos ni
    importados. Es un lint, pero vive aquí porque lo que protege es que una
    guarda no reviente el día que tiene que actuar.
    """

    def test_every_global_name_used_is_available(self) -> None:
        import ast as _ast
        import builtins
        import pathlib as _pl

        def _nombres_de_args(args) -> set:
            salida = {a.arg for a in list(args.posonlyargs) + list(args.args)
                      + list(args.kwonlyargs)}
            for extra in (args.vararg, args.kwarg):
                if extra:
                    salida.add(extra.arg)
            return salida

        raiz = _pl.Path(__file__).resolve().parents[1] / "hermes/src/hermes"
        problemas = []
        for fichero in sorted(raiz.rglob("*.py")):
            arbol = _ast.parse(fichero.read_text(encoding="utf-8"))
            definidos = set(dir(builtins))
            for nodo in _ast.walk(arbol):
                if isinstance(nodo, (_ast.Import, _ast.ImportFrom)):
                    for alias in nodo.names:
                        definidos.add(alias.asname or alias.name.split(".")[0])
                elif isinstance(nodo, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    definidos.add(nodo.name)
                    definidos |= _nombres_de_args(nodo.args)
                elif isinstance(nodo, _ast.Lambda):
                    definidos |= _nombres_de_args(nodo.args)
                elif isinstance(nodo, _ast.ClassDef):
                    definidos.add(nodo.name)
                elif isinstance(nodo, _ast.Name) and isinstance(nodo.ctx, _ast.Store):
                    definidos.add(nodo.id)
                elif isinstance(nodo, _ast.ExceptHandler) and nodo.name:
                    definidos.add(nodo.name)
                elif isinstance(nodo, _ast.Global):
                    definidos.update(nodo.names)

            for nodo in _ast.walk(arbol):
                if isinstance(nodo, _ast.Name) and isinstance(nodo.ctx, _ast.Load):
                    if nodo.id not in definidos:
                        problemas.append(
                            f"{fichero.relative_to(raiz).as_posix()}:{nodo.lineno} "
                            f"usa {nodo.id!r} sin importarlo ni definirlo")
        self.assertEqual(problemas, [], "\n".join(problemas))

    def test_the_slug_helper_actually_runs(self) -> None:
        """Habia DOS `_slugify`; la primera reventaba y quedaba tapada."""
        from hermes.tools.ha import _slugify

        self.assertEqual(_slugify("Salón Principal"), "salon_principal")
        self.assertEqual(_slugify("Habitación 2"), "habitacion_2")


if __name__ == "__main__":
    unittest.main()
