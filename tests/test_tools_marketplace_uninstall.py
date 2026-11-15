"""Tests de `ha_marketplace_uninstall` (spec 026, tramo 2; FR-001, FR-004,
FR-006, FR-007, FR-014, FR-017; SC-003, SC-005).

Familia `marketplace_manage` (decisión D-2 del supervisor). HA simulado con la
forma de 2026.11.1 y Supervisor simulado del backup
(`tests/fixtures/marketplace_escritura.py`). Datos ficticios (`ejemplo/*`).

Controles negativos (T028), comprobados revirtiendo el código un momento:
- (a) enviar el comando aunque el backup falle (sin el `return` tras
  `backup_failed`) → caen `TestBackup.test_backup_fallido_no_envia_nada`,
  `test_backup_sin_terminar` y `test_backup_sin_slug` (3 failed);
- (e) no rechazar `repository_in_use` → caen `TestDesinstalar.test_en_uso`,
  `test_en_uso_con_una_ignorada` y `test_en_uso_entre_vista_y_confirmacion`
  (3 failed: en el último, el backup se hacía en balde);
- (h) poner el `full_name` en el nombre del backup → caen
  `TestBackup.test_carga_y_orden` y `TestComun.test_evento_y_backup_sin_datos`
  (2 failed).
(El (g), dejar `marketplace/repository/uninstall` como `deny` «pendiente»,
lo vigilan los tests de la tabla, del generador desde cero, de la genérica y
del registro: 7 fallos contando subtests.)
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any

from aiohttp import ClientSession
from structlog.testing import capture_logs

import hermes.security as security
from hermes.tools import marketplace_manage as mm
from tests._ha_fixture import make_ready_client
from tests.fixtures.marketplace_escritura import (
    ID_CATALOGO,
    ID_INSTALADO,
    ID_PERSONALIZADO,
    JOB,
    SLUG,
    MarketplaceSimulado,
    SupervisorSimulado,
    error,
)

T = "ha_marketplace_uninstall"
_DESINSTALAR = "marketplace/repository/uninstall"
_NOMBRE_RE = re.compile(r"^hermes_marketplace_uninstall_\d{8}T\d{6}Z$")


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.client = make_ready_client(self.session, {})
        self.ha = MarketplaceSimulado()
        self.sv = SupervisorSimulado(self.ha)
        self.client.ws_send = self.ha  # type: ignore[method-assign]
        self.client.sv_request = self.sv  # type: ignore[method-assign]
        self.mcp = DummyMCP()
        mm.register(self.mcp, self.client)

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def call(self, **kwargs: Any) -> Any:
        return await self.mcp.tools[T](**kwargs)

    async def vista(self, **kwargs: Any) -> Any:
        r = await self.call(**kwargs)
        self.assertIn("confirmation_token", r, r)
        self.assertEqual(self.ha.escrituras(), [], "la vista previa escribió")
        self.assertEqual(self.sv.llamadas, [], "la vista previa pidió un backup")
        return r

    def estado_token(self, token: str) -> dict[str, Any]:
        return json.loads((Path(security.CONFIRMATIONS_DIR) / f"{token}.json").read_text("utf-8"))

    def assert_nada(self) -> None:
        self.assertEqual(self.ha.escrituras(), [])
        self.assertEqual(self.sv.llamadas, [])


# ── Desinstalar ──────────────────────────────────────────────────────────────


class TestDesinstalar(_Base):
    async def test_vista_de_una_integracion(self) -> None:
        r = await self.vista(repository_id=ID_INSTALADO)
        p = r["preview"]
        self.assertEqual(p["action"], "uninstall")
        self.assertEqual((p["repository"]["full_name"], p["repository"]["domain"],
                          p["repository"]["installed_version"]),
                         ("ejemplo/integracion", "ejemplo", "1.1.0"))
        self.assertIn("custom_components", p["removes"]["files"])
        self.assertIs(p["removes"]["lovelace_resource"], False)
        self.assertIn("update entity", p["removes"]["update_entity"])
        # Con `config_flow`, HA pide reiniciar solo si esta ejecución la
        # cargó: Hermes no lo ve y no adivina.
        self.assertIsNone(p["restart"]["likely"])
        self.assertIn("sv_restart_core", p["restart"]["after"])
        self.assertIs(p["may_break"]["listed_by_home_assistant"], False)
        self.assertIn("YAML", p["may_break"]["detail"])
        self.assertIs(p["third_party"], True)
        self.assertIs(p["backup"]["will_create"], True)
        self.assertIn("without the database", p["backup"]["kind"])
        # Sin la 031 no hay safety backups cifrados: no se promete cifrado.
        self.assertIs(p["backup"]["encrypted"], False)
        self.assertEqual(["config_entries/get"],
                         [t for t in self.ha.tipos if not t.startswith("marketplace/")])

    async def test_sin_config_flow_pide_reinicio(self) -> None:
        self.ha.repo(ID_INSTALADO)["config_flow"] = False
        p = (await self.vista(repository_id=ID_INSTALADO))["preview"]
        self.assertIs(p["restart"]["likely"], True)

    async def test_vista_de_una_tarjeta_con_su_recurso(self) -> None:
        self.ha.repo(ID_PERSONALIZADO).update(installed=True, installed_version="2.0.0")
        p = (await self.vista(repository_id=ID_PERSONALIZADO))["preview"]
        self.assertIs(p["removes"]["lovelace_resource"], True)
        self.assertIn("Lovelace", p["removes"]["files"])
        self.assertEqual(p["removes"]["path"], "/config/www/community/tarjeta")
        self.assertIs(p["restart"]["likely"], False)
        self.assertIn("cards", p["may_break"]["detail"])
        self.assertIs(p["in_default_catalog"], False)
        # Una tarjeta no tiene entradas de configuración: no se leen.
        self.assertNotIn("config_entries/get", self.ha.tipos)

    async def test_confirmacion(self) -> None:
        vista = await self.vista(repository_id=ID_INSTALADO)
        hecho = await self.call(repository_id=ID_INSTALADO,
                                confirmation_token=vista["confirmation_token"])
        self.assertEqual(hecho["result"], "ok")
        self.assertEqual(self.ha.escrituras(), [
            {"type": _DESINSTALAR, "repository": ID_INSTALADO}])
        self.assertIs(hecho["repository"]["installed"], False)
        self.assertIs(hecho["restart_required"], False)
        self.assertEqual(hecho["backup"]["slug"], SLUG)
        self.assertEqual(self.estado_token(vista["confirmation_token"])["state"], "completed")

    async def test_reinicio_pedido_por_ha(self) -> None:
        self.ha.cargadas.add("ejemplo")
        vista = await self.vista(repository_id=ID_INSTALADO)
        hecho = await self.call(repository_id=ID_INSTALADO,
                                confirmation_token=vista["confirmation_token"])
        self.assertIs(hecho["restart_required"], True)
        self.assertIn("sv_restart_core", hecho["next"])

    async def test_no_encontrado(self) -> None:
        r = await self.call(repository_id="999999")
        self.assertEqual(r["error"], "repository_not_found")
        self.assertNotIn("confirmation_token", r)
        self.assert_nada()

    async def test_no_instalado(self) -> None:
        r = await self.call(repository_id=ID_CATALOGO)
        self.assertEqual(r["error"], "repository_not_installed")
        self.assertNotIn("confirmation_token", r)
        self.assert_nada()

    async def test_en_uso(self) -> None:
        self.ha.entradas["ejemplo"] = [{"entry_id": "01ABC", "domain": "ejemplo",
                                       "source": "user", "title": "Ejemplo"}]
        r = await self.call(repository_id=ID_INSTALADO)
        self.assertEqual(r["error"], "repository_in_use")
        self.assertIn("ha_delete_config_entry", r["hint"])
        self.assertEqual(r["config_entries"], [{"entry_id": "01ABC", "source": "user"}])
        self.assertNotIn("confirmation_token", r)
        self.assert_nada()

    async def test_en_uso_con_una_ignorada(self) -> None:
        # HA cuenta también las ignoradas (`async_entries` sin filtro).
        self.ha.entradas["ejemplo"] = [{"entry_id": "01IGN", "domain": "ejemplo",
                                       "source": "ignore", "title": "Ejemplo"}]
        r = await self.call(repository_id=ID_INSTALADO)
        self.assertEqual(r["error"], "repository_in_use")
        self.assert_nada()

    async def test_entradas_que_no_se_pueden_leer(self) -> None:
        from hermes.ha import HAConnectionError

        self.ha.errores["config_entries/get"] = HAConnectionError("WS down")
        r = await self.call(repository_id=ID_INSTALADO)
        self.assertEqual(r["error"], "ha_error")
        self.assertNotIn("confirmation_token", r)
        self.assert_nada()

    async def test_en_uso_entre_vista_y_confirmacion(self) -> None:
        vista = await self.vista(repository_id=ID_INSTALADO)
        self.ha.entradas["ejemplo"] = [{"entry_id": "01ABC", "source": "user"}]
        r = await self.call(repository_id=ID_INSTALADO,
                            confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "repository_in_use")
        self.assert_nada()

    async def test_version_cambiada_entre_vista_y_confirmacion(self) -> None:
        vista = await self.vista(repository_id=ID_INSTALADO)
        self.ha.repo(ID_INSTALADO)["installed_version"] = "1.2.0"
        r = await self.call(repository_id=ID_INSTALADO,
                            confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], security.ESTADO_CAMBIADO)
        self.assert_nada()

    async def test_token_de_otro_repositorio(self) -> None:
        self.ha.repo(ID_PERSONALIZADO).update(installed=True)
        vista = await self.vista(repository_id=ID_INSTALADO)
        r = await self.call(repository_id=ID_PERSONALIZADO,
                            confirmation_token=vista["confirmation_token"])
        self.assertIn("does not match", r["error"])
        self.assert_nada()

    async def test_token_sin_backup_no_vale_con_backup(self) -> None:
        # `backup` va atado: quien previsualizó sin backup no confirma con él
        # (ni al revés).
        vista = await self.vista(repository_id=ID_INSTALADO, backup=False)
        r = await self.call(repository_id=ID_INSTALADO, backup=True,
                            confirmation_token=vista["confirmation_token"])
        self.assertIn("does not match", r["error"])
        self.assert_nada()

    async def test_argumentos_invalidos(self) -> None:
        r = await self.call(repository_id="a b")
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "repository_id"))
        r = await self.call(repository_id=ID_INSTALADO, backup="no")
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "backup"))
        self.assertEqual(self.ha.enviados, [])

    async def test_error_de_ha_al_confirmar(self) -> None:
        vista = await self.vista(repository_id=ID_INSTALADO)
        self.ha.errores[_DESINSTALAR] = error("repository_busy", "Repository is busy")
        token = vista["confirmation_token"]
        r = await self.call(repository_id=ID_INSTALADO, confirmation_token=token)
        self.assertEqual(r["error"], "repository_busy")
        # El backup ya está hecho: se dice a qué volver.
        self.assertEqual(r["backup"]["slug"], SLUG)
        self.assertEqual(self.estado_token(token)["state"], "failed")


# ── Backup previo (FR-017, SC-005) ───────────────────────────────────────────


class TestBackup(_Base):
    async def test_carga_y_orden(self) -> None:
        vista = await self.vista(repository_id=ID_INSTALADO)
        await self.call(repository_id=ID_INSTALADO,
                        confirmation_token=vista["confirmation_token"])
        self.assertEqual(len(self.sv.llamadas), 1)
        llamada = self.sv.llamadas[0]
        self.assertEqual((llamada["method"], llamada["path"], llamada["timeout_seconds"]),
                         ("POST", "/backups/new/partial", 300.0))
        carga = llamada["json_body"]
        self.assertTrue(_NOMBRE_RE.match(carga.pop("name")))
        self.assertEqual(carga, {"homeassistant": True,
                                 "homeassistant_exclude_database": True,
                                 "background": False})
        # Primero el backup y después el comando de HA.
        self.assertNotIn(_DESINSTALAR, self.sv.enviados_a_ha_antes)
        self.assertIn(_DESINSTALAR, self.ha.tipos)

    async def _fallo(self, modo: str) -> dict[str, Any]:
        vista = await self.vista(repository_id=ID_INSTALADO)
        self.sv.modo = modo
        token = vista["confirmation_token"]
        r = await self.call(repository_id=ID_INSTALADO, confirmation_token=token)
        self.assertEqual(r["error"], "backup_failed")
        self.assertIs(r["sent_to_home_assistant"], False)
        self.assertEqual(self.ha.escrituras(), [], "se envió el comando sin backup")
        self.assertEqual(self.estado_token(token)["state"], "failed")
        # El token gastado no sirve para reintentar.
        otra = await self.call(repository_id=ID_INSTALADO, confirmation_token=token)
        self.assertNotIn("result", otra)
        self.assertEqual(self.ha.escrituras(), [])
        return r

    async def test_backup_fallido_no_envia_nada(self) -> None:
        r = await self._fallo("error")
        self.assertEqual(r["job_id"], JOB)

    async def test_backup_sin_terminar(self) -> None:
        r = await self._fallo("lento")
        self.assertNotIn("job_id", r)

    async def test_backup_sin_slug(self) -> None:
        r = await self._fallo("sin_slug")
        self.assertEqual(r["job_id"], JOB)

    async def test_sin_backup(self) -> None:
        vista = await self.vista(repository_id=ID_INSTALADO, backup=False)
        b = vista["preview"]["backup"]
        self.assertIs(b["will_create"], False)
        self.assertIn("keeps no copy", b["warning"])
        hecho = await self.call(repository_id=ID_INSTALADO, backup=False,
                                confirmation_token=vista["confirmation_token"])
        self.assertEqual(hecho["backup"], {"created": False})
        self.assertEqual(self.sv.llamadas, [])
        self.assertEqual(self.ha.escrituras(), [
            {"type": _DESINSTALAR, "repository": ID_INSTALADO}])

    async def test_url_con_credenciales_en_el_error(self) -> None:
        # Centinela: el texto del error del Supervisor sale redactado, también
        # en el fichero del token.
        vista = await self.vista(repository_id=ID_INSTALADO)
        self.sv.mensaje_error = ("Supervisor error: can't reach "
                                 "https://usuario:centinela-026@example.com/backup")
        token = vista["confirmation_token"]
        self.sv.modo = "error"
        r = await self.call(repository_id=ID_INSTALADO, confirmation_token=token)
        self.assertNotIn("centinela-026", json.dumps(r))
        fichero = (Path(security.CONFIRMATIONS_DIR) / f"{token}.json").read_text("utf-8")
        self.assertNotIn("centinela-026", fichero)


# ── Común ────────────────────────────────────────────────────────────────────


class TestComun(_Base):
    async def test_sin_marketplace_no_prueba_hacs(self) -> None:
        self.ha.errores["marketplace/repositories/list"] = error("unknown_command")
        r = await self.call(repository_id=ID_INSTALADO)
        self.assertEqual(r["error"], "marketplace_write_unsupported")
        self.assertEqual([t for t in self.ha.tipos if t.startswith("hacs/")], [])
        self.assert_nada()

    async def test_desinstalar_desconocido_al_confirmar(self) -> None:
        vista = await self.vista(repository_id=ID_INSTALADO)
        self.ha.errores[_DESINSTALAR] = error("unknown_command")
        r = await self.call(repository_id=ID_INSTALADO,
                            confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "marketplace_write_unsupported")
        self.assertEqual([t for t in self.ha.tipos if t.startswith("hacs/")], [])

    async def test_solo_comandos_permitidos(self) -> None:
        vista = await self.vista(repository_id=ID_INSTALADO)
        await self.call(repository_id=ID_INSTALADO,
                        confirmation_token=vista["confirmation_token"])
        prohibidos = {"marketplace/warning/accept", "marketplace/github/connect"}
        for tipo in self.ha.tipos:
            self.assertFalse(tipo.startswith(("hassio/", "supervisor/")), tipo)
            self.assertNotIn(tipo, prohibidos)
            self.assertTrue(tipo.startswith("marketplace/") or tipo == "config_entries/get",
                            tipo)
        self.assertEqual([p["type"] for p in self.ha.escrituras()], [_DESINSTALAR])
        self.assertEqual([c["path"] for c in self.sv.llamadas], ["/backups/new/partial"])

    async def test_evento_y_backup_sin_datos(self) -> None:
        with capture_logs() as logs:
            vista = await self.vista(repository_id=ID_INSTALADO)
            hecho = await self.call(repository_id=ID_INSTALADO,
                                    confirmation_token=vista["confirmation_token"])
            await self.call(repository_id=ID_CATALOGO)
        eventos = [e for e in logs if e.get("event") == "marketplace_write"]
        self.assertEqual([e["outcome"] for e in eventos],
                         ["preview", "ok", "rejected:repository_not_installed"])
        for e in eventos:
            self.assertEqual(set(e) - {"log_level"}, {"event", "tool", "outcome", "category"})
        texto = json.dumps(logs, default=str)
        for dato in ("ejemplo", ID_INSTALADO, ID_CATALOGO, "1.1.0", SLUG,
                     "hermes_marketplace_uninstall"):
            self.assertNotIn(dato, texto)
        # El nombre del backup no lleva el repositorio (los backups se listan
        # en sitios que se comparten).
        self.assertTrue(_NOMBRE_RE.match(hecho["backup"]["name"]))
        self.assertNotIn("ejemplo", self.sv.llamadas[0]["json_body"]["name"])


if __name__ == "__main__":
    unittest.main()
