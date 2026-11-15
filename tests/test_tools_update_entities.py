"""Entidades `update` de Core (spec 015, tramo 3: FR-011…FR-014, FR-018).

Todo contra el Core simulado de `tests/fixtures/supervisor_actualizaciones.py`
(estados, registro de entidades, `update/release_notes`, `call_service`) y
datos ficticios. Nunca hay una instalación real: lo que se comprueba es lo que
Hermes LEE, lo que MANDA y lo que devuelve. La ejecución contra HA real está en
el banco (`tests/banco/test_banco_actualizaciones.py`).

- `TestListarEntidades` (FR-011), `TestNotas` (FR-012).
- `TestInstalar` (FR-013): rechazos sin token, vista previa y ejecución.
- `TestEncaminar` (FR-014 y D-1): Core, OS, Supervisor y apps a sus `sv_*`;
  Hermes, rechazado sin token por el slug EXACTO de `/addons/self/info`.
- `TestTokenYSecretos` (FR-008, FR-013, FR-018).

Controles negativos del tramo 3 (T045), con sus recuentos en el commit.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from structlog.testing import capture_logs

from hermes import security
from hermes.ha import HAConnectionError
from hermes.tools import update_entities as mod
from tests.fixtures.supervisor_actualizaciones import (
    CENTINELA_JWT,
    CENTINELA_NOTAS,
    CENTINELA_PASSWORD,
    ENTIDAD_AL_DIA,
    ENTIDAD_APP,
    ENTIDAD_CORE,
    ENTIDAD_FIRMWARE,
    ENTIDAD_HERMES,
    ENTIDAD_OTRO_HERMES,
    ENTIDAD_SIN_NOTAS,
    FIRMWARE_ACTUAL,
    FIRMWARE_ULTIMA,
    SLUG_APP,
    SLUG_OTRO_HERMES,
    SupervisorActualizaciones,
    con_entidades_update,
    con_os_y_supervisor_desactualizados,
    error_404,
    sistema_sano,
)


class _MCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


class _Base(unittest.IsolatedAsyncioTestCase):
    max_bytes = 131_072

    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self._parche = mock.patch.object(security, "CONFIRMATIONS_DIR",
                                         Path(self.tmp.name) / "tokens")
        self._parche.start()
        self.sv = sistema_sano(SupervisorActualizaciones())
        con_os_y_supervisor_desactualizados(self.sv)
        con_entidades_update(self.sv)
        mcp = _MCP()
        mod.register(mcp, self.sv, response_max_bytes=self.max_bytes)
        self.t = mcp.tools

    async def asyncTearDown(self) -> None:
        self._parche.stop()
        self.tmp.cleanup()

    def estado(self, entity_id: str) -> dict[str, Any]:
        return next(e for e in self.sv.estados if e["entity_id"] == entity_id)

    def ws_tipos(self) -> list[str]:
        return [c["type"] for c in self.sv.ws_llamadas]

    async def instalar(self, **kw: Any) -> Any:
        kw.setdefault("entity_id", ENTIDAD_FIRMWARE)
        return await self.t["ha_install_update"](**kw)

    def token_guardado(self, token: str) -> dict[str, Any]:
        return json.loads((security.CONFIRMATIONS_DIR / f"{token}.json")
                          .read_text(encoding="utf-8"))


# ── ha_list_updates (FR-011) ──────────────────────────────────────────────────


class TestListarEntidades(_Base):
    async def test_por_defecto_solo_las_que_tienen_actualizacion(self) -> None:
        r = await self.t["ha_list_updates"]()
        ids = [i["entity_id"] for i in r["items"]]
        self.assertNotIn(ENTIDAD_AL_DIA, ids)
        self.assertIn(ENTIDAD_FIRMWARE, ids)
        self.assertEqual(r["count"], len(ids))
        self.assertIs(r["truncated"], False)
        self.assertTrue(all(i["state"] == "on" for i in r["items"]))
        self.assertEqual(r["_third_party_text"]["fields"], ["title", "release_summary"])

    async def test_include_up_to_date(self) -> None:
        r = await self.t["ha_list_updates"](include_up_to_date=True)
        self.assertIn(ENTIDAD_AL_DIA, [i["entity_id"] for i in r["items"]])
        # Ninguna entidad que no sea del dominio `update`.
        self.assertTrue(all(i["entity_id"].startswith("update.") for i in r["items"]))

    async def test_supports_decodificado(self) -> None:
        r = await self.t["ha_list_updates"]()
        por_id = {i["entity_id"]: i for i in r["items"]}
        self.assertEqual(por_id[ENTIDAD_FIRMWARE]["supports"], {
            "install": True, "specific_version": True, "progress": False,
            "backup": True, "release_notes": True})
        self.assertEqual(por_id[ENTIDAD_SIN_NOTAS]["supports"], {
            "install": True, "specific_version": False, "progress": False,
            "backup": False, "release_notes": False})
        for bit, nombre in ((1, "install"), (2, "specific_version"), (4, "progress"),
                            (8, "backup"), (16, "release_notes")):
            with self.subTest(bit=bit):
                s = mod._supports(bit)
                self.assertEqual([k for k, v in s.items() if v], [nombre])
        self.assertFalse(any(mod._supports(None).values()))
        self.assertFalse(any(mod._supports(True).values()))

    async def test_install_with_por_el_registro(self) -> None:
        r = await self.t["ha_list_updates"]()
        por_id = {i["entity_id"]: i for i in r["items"]}
        self.assertEqual(por_id[ENTIDAD_FIRMWARE]["install_with"], "ha_install_update")
        self.assertEqual(por_id[ENTIDAD_FIRMWARE]["platform"], "ficticia")
        self.assertEqual(por_id[ENTIDAD_CORE]["install_with"], "sv_update_core")
        self.assertEqual(por_id["update.sistema_operativo_renombrado"]["install_with"],
                         "sv_update_os")
        self.assertEqual(por_id["update.supervisor_renombrado"]["install_with"],
                         "sv_update_supervisor")
        self.assertEqual(por_id[ENTIDAD_APP]["install_with"], "sv_update_addon")
        # Hermes: null con la nota de cómo hacerlo (D-1).
        self.assertIsNone(por_id[ENTIDAD_HERMES]["install_with"])
        self.assertIn("Home Assistant UI", por_id[ENTIDAD_HERMES]["note"])
        # Otra app con sufijo `_hermes` NO es Hermes (criterio estricto), pero
        # tampoco se remite a `sv_update_addon`, que la rechazaría (T048, D-13).
        self.assertIsNone(por_id[ENTIDAD_OTRO_HERMES]["install_with"])
        self.assertIn("sv_update_addon refuses", por_id[ENTIDAD_OTRO_HERMES]["note"])
        self.assertNotIn("cannot update itself", por_id[ENTIDAD_OTRO_HERMES]["note"])
        # Una sola lectura del registro, con todos los entity_id.
        registro = [c for c in self.sv.ws_llamadas
                    if c["type"] == "config/entity_registry/get_entries"]
        self.assertEqual(len(registro), 1)
        self.assertEqual(sorted(registro[0]["entity_ids"]), sorted(por_id))

    async def test_sin_registro_no_dice_ha_install_update(self) -> None:
        original = self.sv.ws_send

        async def ws(payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
            if payload["type"] == "config/entity_registry/get_entries":
                raise HAConnectionError("caido")
            return await original(payload, timeout_seconds)

        self.sv.ws_send = ws  # type: ignore[method-assign]
        r = await self.t["ha_list_updates"]()
        self.assertIs(r["partial"], True)
        self.assertTrue(all(i["install_with"] is None for i in r["items"]))

    async def test_sin_slug_propio_las_apps_quedan_sin_tool(self) -> None:
        self.sv.respuesta("GET", "/addons/self/info", error_404("GET", "/addons/self/info"))
        r = await self.t["ha_list_updates"]()
        por_id = {i["entity_id"]: i for i in r["items"]}
        for eid in (ENTIDAD_APP, ENTIDAD_HERMES, ENTIDAD_OTRO_HERMES):
            with self.subTest(eid=eid):
                self.assertIsNone(por_id[eid]["install_with"])
                self.assertIn("cannot rule out", por_id[eid]["note"])

    async def test_resumen_recortado_y_redactado(self) -> None:
        self.estado(ENTIDAD_FIRMWARE)["attributes"]["release_summary"] = (
            f"password: {CENTINELA_PASSWORD} " + "x" * 600)
        r = await self.t["ha_list_updates"]()
        item = next(i for i in r["items"] if i["entity_id"] == ENTIDAD_FIRMWARE)
        self.assertLessEqual(len(item["release_summary"]), 300)
        self.assertNotIn(CENTINELA_PASSWORD, json.dumps(r))

    async def test_recorta_al_tope(self) -> None:
        for n in range(300):
            self.sv.estados.append({"entity_id": f"update.relleno_{n:03d}", "state": "on",
                                    "attributes": {"installed_version": "1",
                                                   "latest_version": "2",
                                                   "release_summary": "y" * 250}})
        mcp = _MCP()
        mod.register(mcp, self.sv, response_max_bytes=20_000)
        r = await mcp.tools["ha_list_updates"]()
        self.assertIs(r["truncated"], True)
        self.assertLessEqual(len(json.dumps(r)), 20_000)
        self.assertEqual(r["count"], len(r["items"]))

    async def test_core_caido(self) -> None:
        self.sv.core_caido = True
        r = await self.t["ha_list_updates"]()
        self.assertEqual(r["error"], "core_error")


# ── ha_get_update_release_notes (FR-012) ──────────────────────────────────────


class TestNotas(_Base):
    async def test_notas_redactadas_y_marcadas(self) -> None:
        r = await self.t["ha_get_update_release_notes"](ENTIDAD_FIRMWARE)
        self.assertIs(r["supported"], True)
        self.assertIn(CENTINELA_NOTAS, r["text"])
        self.assertNotIn(CENTINELA_PASSWORD, json.dumps(r))
        self.assertNotIn(CENTINELA_JWT, json.dumps(r))
        self.assertIs(r["truncated"], False)
        self.assertIn("text", r["_third_party_text"]["fields"])

    async def test_notas_recortadas_al_tope(self) -> None:
        self.sv.notas[ENTIDAD_FIRMWARE] = "ñ" * 200_000
        r = await self.t["ha_get_update_release_notes"](ENTIDAD_FIRMWARE)
        self.assertIs(r["truncated"], True)
        self.assertLessEqual(len(json.dumps(r, ensure_ascii=False).encode("utf-8")),
                             self.max_bytes)

    async def test_notas_con_escapes_no_pasan_del_tope(self) -> None:
        """T049: lo que viaja es JSON. Comillas, barras, saltos de línea,
        tabuladores y controles ocupan el doble (o seis veces) al escaparse;
        medir bytes crudos dejaba la respuesta en ~254 KB con tope de 128 KB y
        el guardián central la cambiaba por un error. Control negativo:
        `_recortar_bytes` midiendo `texto.encode()` en vez de `_bytes_json`
        pone este test en rojo (respuesta > tope)."""
        for relleno in ('"' * 200_000, "\\" * 200_000, "\n\t" * 100_000,
                        "\x01" * 200_000, 'a"ñ\\\n' * 50_000):
            with self.subTest(relleno=repr(relleno[:6])):
                self.sv.notas[ENTIDAD_FIRMWARE] = relleno
                r = await self.t["ha_get_update_release_notes"](ENTIDAD_FIRMWARE)
                self.assertIs(r["truncated"], True)
                tam = len(json.dumps(r, ensure_ascii=False).encode("utf-8"))
                self.assertLessEqual(tam, self.max_bytes)
                # Y no se recorta de más: el texto aprovecha casi todo el tope.
                self.assertGreater(tam, self.max_bytes - 2 * mod._MARGEN_NOTAS)
                self.assertTrue(relleno.startswith(r["text"]))

    def test_recorte_exacto(self) -> None:
        texto = 'x"' * 10
        recortado, corto = mod._recortar_bytes(texto, 12)
        self.assertIs(corto, True)
        self.assertLessEqual(mod._bytes_json(recortado), 12)
        # Un carácter más ya no cabría.
        self.assertGreater(mod._bytes_json(texto[:len(recortado) + 1]), 12)
        self.assertEqual(mod._recortar_bytes("abc", 100), ("abc", False))

    async def test_sin_release_notes_no_llama(self) -> None:
        r = await self.t["ha_get_update_release_notes"](ENTIDAD_SIN_NOTAS)
        self.assertIs(r["supported"], False)
        self.assertEqual(r["release_summary"], "Resumen sin notas")
        self.assertEqual(r["release_url"], "https://example.invalid/sin-notas")
        self.assertNotIn("update/release_notes", self.ws_tipos())

    async def test_entity_id_invalido_no_llama(self) -> None:
        for malo in ("light.salon", "update.", "update.a/b", "update.A", "", None,
                     "update.x y"):
            with self.subTest(malo=malo):
                r = await self.t["ha_get_update_release_notes"](malo)
                self.assertEqual(r["error"], "invalid_argument")
        self.assertEqual(self.sv.ws_llamadas, [])

    async def test_entidad_inexistente(self) -> None:
        r = await self.t["ha_get_update_release_notes"]("update.no_existe")
        self.assertEqual(r["error"], "entity_not_found")

    async def test_error_de_core_redactado(self) -> None:
        self.sv.notas[ENTIDAD_FIRMWARE] = HAConnectionError(
            f"fallo password: {CENTINELA_PASSWORD}")
        with capture_logs() as logs:
            r = await self.t["ha_get_update_release_notes"](ENTIDAD_FIRMWARE)
        self.assertEqual(r["error"], "core_error")
        self.assertNotIn(CENTINELA_PASSWORD, json.dumps(r))
        self.assertNotIn(CENTINELA_PASSWORD, json.dumps(logs, default=str))


# ── ha_install_update (FR-013) ────────────────────────────────────────────────


class TestInstalar(_Base):
    async def _rechazo(self, codigo: str, **kw: Any) -> None:
        r = await self.instalar(**kw)
        self.assertEqual(r.get("error"), codigo, r)
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.servicios, [])

    async def test_sin_actualizacion_y_sin_version(self) -> None:
        await self._rechazo("no_update_available", entity_id=ENTIDAD_AL_DIA)

    async def test_version_sin_specific_version(self) -> None:
        await self._rechazo("specific_version_not_supported", entity_id=ENTIDAD_SIN_NOTAS,
                            version="2.1.0")

    async def test_backup_sin_soporte(self) -> None:
        await self._rechazo("backup_not_supported", entity_id=ENTIDAD_SIN_NOTAS,
                            backup=True)

    async def test_en_curso(self) -> None:
        self.estado(ENTIDAD_FIRMWARE)["attributes"]["in_progress"] = True
        await self._rechazo("update_in_progress")

    async def test_sin_install(self) -> None:
        self.estado(ENTIDAD_SIN_NOTAS)["attributes"]["supported_features"] = 0
        await self._rechazo("install_not_supported", entity_id=ENTIDAD_SIN_NOTAS)

    async def test_entidad_inexistente(self) -> None:
        await self._rechazo("entity_not_found", entity_id="update.no_existe")

    async def test_argumentos_invalidos_no_llaman(self) -> None:
        for kw in ({"entity_id": "switch.x"}, {"version": "1 .2"}, {"version": "../x"},
                   {"version": "1..2"}, {"version": ""}, {"version": "v" * 65}):
            with self.subTest(kw=kw):
                r = await self.instalar(**kw)
                self.assertEqual(r["error"], "invalid_argument")
        self.assertEqual(self.sv.ws_llamadas, [])
        # Versiones de firmware con guiones o `v` delante sí valen.
        for v in ("v2.3", "1.2.3-rc1", "2024.6.0+build5"):
            self.assertTrue(mod._validar_version(v), v)

    async def test_vista_previa(self) -> None:
        r = await self.instalar(backup=True)
        self.assertIn("confirmation_token", r)
        p = r["preview"]
        self.assertEqual(p["action"], "install_update")
        self.assertEqual((p["from_version"], p["to_version"]), (FIRMWARE_ACTUAL, FIRMWARE_ULTIMA))
        self.assertIs(p["downgrade"], False)
        self.assertEqual(p["platform"], "ficticia")
        self.assertEqual(p["title"], "Firmware ficticio")
        self.assertIs(p["release_notes"]["available"], True)
        self.assertIn(CENTINELA_NOTAS, p["release_notes"]["text"])
        self.assertEqual(p["backup"]["requested"], True)
        self.assertEqual(p["backup"]["supported"], True)
        self.assertIn("ficticia", p["backup"]["note"])
        self.assertTrue(any("power off" in a for a in p["warnings"]))
        # La vista previa no instala nada.
        self.assertEqual(self.sv.servicios, [])

    async def test_vista_previa_notas_a_1500(self) -> None:
        self.sv.notas[ENTIDAD_FIRMWARE] = "z" * 5000
        p = (await self.instalar())["preview"]
        self.assertEqual(len(p["release_notes"]["text"]), 1500)
        self.assertIs(p["release_notes"]["truncated"], True)

    async def test_vista_previa_sin_notas_da_el_resumen(self) -> None:
        p = (await self.instalar(entity_id=ENTIDAD_SIN_NOTAS))["preview"]
        self.assertIs(p["release_notes"]["available"], False)
        self.assertEqual(p["release_notes"]["release_summary"], "Resumen sin notas")
        self.assertNotIn("update/release_notes", self.ws_tipos())
        self.assertFalse(any("power off" in a for a in p["warnings"]))
        self.assertIsNone(p["backup"]["note"])

    async def test_vista_previa_bajada(self) -> None:
        p = (await self.instalar(version="0.9"))["preview"]
        self.assertEqual(p["to_version"], "0.9")
        self.assertIs(p["downgrade"], True)
        self.assertTrue(any("downgrade" in a for a in p["warnings"]))

    async def test_confirmar_llama_una_vez_con_version_y_backup(self) -> None:
        r = await self.instalar(backup=True)
        r = await self.instalar(backup=True, confirmation_token=r["confirmation_token"])
        self.assertEqual(r["result"], "ok")
        self.assertEqual(self.sv.servicios, [{
            "dominio": "update", "servicio": "install",
            "datos": {"entity_id": ENTIDAD_FIRMWARE, "version": FIRMWARE_ULTIMA,
                      "backup": True},
            "allow_dangerous": True}])

    async def test_sin_specific_version_no_manda_version(self) -> None:
        # Core rechaza `version` si la entidad no admite SPECIFIC_VERSION: se
        # manda sin ella (instala la última, la atada al token).
        r = await self.instalar(entity_id=ENTIDAD_SIN_NOTAS)
        r = await self.instalar(entity_id=ENTIDAD_SIN_NOTAS,
                                confirmation_token=r["confirmation_token"])
        self.assertEqual(r["result"], "ok")
        self.assertEqual(self.sv.servicios[0]["datos"],
                         {"entity_id": ENTIDAD_SIN_NOTAS, "backup": False})

    async def test_espera_vencida_es_running(self) -> None:
        r = await self.instalar()
        self.sv.respuesta_servicio = TimeoutError()
        r = await self.instalar(confirmation_token=r["confirmation_token"])
        self.assertEqual(r["status"], "running")
        self.assertIn("ha_list_updates", r["hint"])
        self.assertNotIn("error", r)

    async def test_error_de_core(self) -> None:
        r = await self.instalar()
        token = r["confirmation_token"]
        self.sv.respuesta_servicio = HAConnectionError(
            'HA REST POST x failed 500: {"message": "fallo password: '
            + CENTINELA_PASSWORD + '"}', status=500)
        with capture_logs() as logs:
            r = await self.instalar(confirmation_token=token)
        self.assertEqual(r["error"], "core_error")
        self.assertNotIn(CENTINELA_PASSWORD, json.dumps(r))
        self.assertNotIn(CENTINELA_PASSWORD, json.dumps(logs, default=str))
        self.assertEqual(self.token_guardado(token)["state"], "failed")


# ── Encaminamiento (FR-014) y Hermes (D-1) ────────────────────────────────────


class TestEncaminar(_Base):
    async def _encaminada(self, entity_id: str, **kw: Any) -> dict[str, Any]:
        r = await self.instalar(entity_id=entity_id, **kw)
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.servicios, [])
        return r

    async def test_core(self) -> None:
        r = await self._encaminada(ENTIDAD_CORE, version="2026.12.0", backup=True)
        self.assertEqual((r["error"], r["tool"]), ("use_dedicated_tool", "sv_update_core"))
        self.assertEqual(r["arguments"], {"version": "2026.12.0", "backup": True})

    async def test_os_con_backup_avisa(self) -> None:
        r = await self._encaminada("update.sistema_operativo_renombrado", backup=True)
        self.assertEqual(r["tool"], "sv_update_os")
        self.assertEqual(r["arguments"], {"version": None})
        self.assertIn("does not make a backup", r["note"])

    async def test_supervisor(self) -> None:
        r = await self._encaminada("update.supervisor_renombrado")
        self.assertEqual((r["tool"], r["arguments"]), ("sv_update_supervisor", {}))

    async def test_app(self) -> None:
        r = await self._encaminada(ENTIDAD_APP)
        self.assertEqual((r["tool"], r["arguments"]), ("sv_update_addon", {"slug": SLUG_APP}))

    async def test_hermes_rechazado_sin_token(self) -> None:
        r = await self._encaminada(ENTIDAD_HERMES)
        self.assertEqual(r["error"], "self_update_not_supported")
        self.assertIn("Home Assistant UI", r["detail"])
        self.assertIn("automatic update", r["detail"])
        # Ni con un token traído de otra parte.
        r = await self._encaminada(ENTIDAD_HERMES, confirmation_token="x" * 32)
        self.assertEqual(r["error"], "self_update_not_supported")

    async def test_otra_app_con_sufijo_hermes_no_es_hermes(self) -> None:
        # No es Hermes (no es `self_update_not_supported`), pero tampoco se
        # remite a `sv_update_addon`, que la rechaza por el sufijo (T048,
        # D-13): antes salía `use_dedicated_tool` hacia un rechazo seguro.
        r = await self._encaminada(ENTIDAD_OTRO_HERMES)
        self.assertEqual(r["error"], "unsupported_entity")
        self.assertNotIn("tool", r)
        self.assertIn("sv_update_addon refuses", r["detail"])
        self.assertIn("Home Assistant UI", r["detail"])

    async def test_otra_app_con_sufijo_hermes_es_un_rechazo_real(self) -> None:
        # Lo que dice la nota es verdad: `sv_update_addon` (009) la rechaza.
        from hermes.tools import addons as addons_mod
        self.assertTrue(addons_mod._es_hermes(SLUG_OTRO_HERMES))

    async def test_otra_app_sin_slug_propio_no_remite_a_sv_update_addon(self) -> None:
        self.sv.respuesta("GET", "/addons/self/info", error_404("GET", "/addons/self/info"))
        r = await self._encaminada(ENTIDAD_OTRO_HERMES)
        self.assertEqual(r["error"], "self_check_unavailable")
        self.assertNotIn("update it with sv_update_addon", r["detail"])
        r = await self.t["ha_list_updates"]()
        item = next(i for i in r["items"] if i["entity_id"] == ENTIDAD_OTRO_HERMES)
        self.assertIsNone(item["install_with"])
        self.assertNotIn("use sv_update_addon", item["note"])

    async def test_sin_slug_propio_fail_closed(self) -> None:
        self.sv.respuesta("GET", "/addons/self/info", error_404("GET", "/addons/self/info"))
        for eid in (ENTIDAD_HERMES, ENTIDAD_APP):
            with self.subTest(eid=eid):
                r = await self._encaminada(eid)
                self.assertEqual(r["error"], "self_check_unavailable")
                self.assertIn("Home Assistant UI", r["detail"])

    async def test_slug_propio_se_lee_del_supervisor(self) -> None:
        await self._encaminada(ENTIDAD_HERMES)
        self.assertIn(("GET", "/addons/self/info"), self.sv.rutas())

    async def test_renombrada_se_decide_por_el_registro(self) -> None:
        # La entidad de Core con OTRO entity_id cualquiera: el registro manda.
        self.sv.estados.append(dict(self.estado(ENTIDAD_CORE), entity_id="update.cualquiera"))
        self.sv.registro["update.cualquiera"] = dict(
            self.sv.registro[ENTIDAD_CORE], entity_id="update.cualquiera")
        r = await self._encaminada("update.cualquiera")
        self.assertEqual(r["tool"], "sv_update_core")
        # Y una entidad que SE LLAMA como la de Hermes pero es de otra
        # integración no se encamina.
        r = await self.instalar(entity_id=ENTIDAD_FIRMWARE)
        self.assertIn("confirmation_token", r)

    async def test_hassio_desconocida_fail_closed(self) -> None:
        self.sv.registro[ENTIDAD_FIRMWARE] = {"platform": "hassio", "unique_id": "raro"}
        r = await self._encaminada(ENTIDAD_FIRMWARE)
        self.assertEqual(r["error"], "unsupported_entity")

    async def test_registro_ilegible_fail_closed(self) -> None:
        original = self.sv.ws_send

        async def ws(payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
            if payload["type"] == "config/entity_registry/get_entries":
                raise HAConnectionError("caido")
            return await original(payload, timeout_seconds)

        self.sv.ws_send = ws  # type: ignore[method-assign]
        r = await self._encaminada(ENTIDAD_FIRMWARE)
        self.assertEqual(r["error"], "registry_unavailable")


# ── Token atado y secretos (FR-008, FR-013, FR-018) ───────────────────────────


class TestTokenYSecretos(_Base):
    async def test_latest_cambiada_preview_outdated(self) -> None:
        r = await self.instalar()
        token = r["confirmation_token"]
        self.estado(ENTIDAD_FIRMWARE)["attributes"]["latest_version"] = "1.2"
        r = await self.instalar(confirmation_token=token)
        self.assertIs(r["preview_outdated"], True)
        self.assertEqual(self.sv.servicios, [])
        self.assertEqual(self.token_guardado(token)["state"], "pending")

    async def test_instalada_cambiada_preview_outdated(self) -> None:
        r = await self.instalar(version="1.1")
        self.estado(ENTIDAD_FIRMWARE)["attributes"]["installed_version"] = "1.05"
        r = await self.instalar(version="1.1", confirmation_token=r["confirmation_token"])
        self.assertIs(r["preview_outdated"], True)
        self.assertEqual(self.sv.servicios, [])

    async def test_argumentos_distintos(self) -> None:
        r = await self.instalar()
        token = r["confirmation_token"]
        for kw in ({"backup": True}, {"version": FIRMWARE_ULTIMA}):
            with self.subTest(kw=kw):
                r = await self.instalar(confirmation_token=token, **kw)
                self.assertIs(r["preview_outdated"], True)
        self.assertEqual(self.sv.servicios, [])
        r = await self.instalar(confirmation_token=token)
        self.assertEqual(r["result"], "ok")

    async def test_atados(self) -> None:
        # data-model: entity_id, version, backup y las dos versiones.
        with mock.patch.object(mod, "create_confirmation_token",
                               wraps=mod.create_confirmation_token) as crear:
            await self.instalar(backup=True)
        _tool, atados = crear.call_args.args
        self.assertEqual(atados, {"entity_id": ENTIDAD_FIRMWARE, "version": None,
                                  "backup": True, "_from_version": FIRMWARE_ACTUAL,
                                  "_to_version": FIRMWARE_ULTIMA})

    async def test_centinelas_fuera_de_vista_previa_respuesta_y_log(self) -> None:
        with capture_logs() as logs:
            r = await self.instalar()
            r2 = await self.instalar(confirmation_token=r["confirmation_token"])
            await self.t["ha_get_update_release_notes"](ENTIDAD_FIRMWARE)
            await self.t["ha_list_updates"]()
        texto = json.dumps([r, r2])
        self.assertNotIn(CENTINELA_PASSWORD, texto)
        self.assertNotIn(CENTINELA_JWT, texto)
        log = json.dumps(logs, default=str)
        for c in (CENTINELA_NOTAS, CENTINELA_PASSWORD, CENTINELA_JWT):
            self.assertNotIn(c, log)

    async def test_version_invalida_no_va_al_log(self) -> None:
        with capture_logs() as logs:
            await self.instalar(version="1 secreto-de-version")
        self.assertNotIn("secreto-de-version", json.dumps(logs, default=str))


if __name__ == "__main__":
    unittest.main()
