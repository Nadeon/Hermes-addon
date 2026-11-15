"""Banco de Core: restablecer un dashboard y lo menor de la UI por las
genéricas (spec 024, tramo 2, T026).

Contra HA Core 2026.11.1 real, con el efecto comprobado por el lector
independiente y la vista previa sin efecto:

- CAP-071, tool dedicada: `ha_reset_lovelace_dashboard_config` sobre un
  dashboard creado con `ha_create_lovelace_dashboard` y guardado por el
  lector; la vista previa cuenta las vistas y tarjetas y no borra (el lector
  sigue viendo la configuración); al confirmar, el lector ve
  `config_not_found` (autogenerado). `lovelace` se rechaza sin token.
- CAP-071 por la tabla: `trace/contexts` tras disparar una automatización;
  `frontend/get_themes`; `webhook/list` con una automatización de
  disparador `webhook` (el `webhook_id` sale tapado); `vacuum/get_segments`
  con el aspirador de plantilla de `configuration.yaml`;
  `radio_frequency/list` con el transmisor de `kitchen_sink`.
- CAP-070: `config/entity_registry/settings/get`,
  `config/entity_registry/get_automatic_entity_ids`,
  `config/device_registry/list_linked_devices` y
  `config/area_registry/reorder` en dos pasos (el orden se restaura al
  final con el lector).
- CAP-073: `application_credentials/config` y `application_credentials/list`.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo
from tests.banco.entorno import rechazo
from tests.banco.lector import ErrorCore

pytestmark = pytest.mark.banco

_LEER = "ha_read_ws_command"
_LLAMAR = "ha_call_ws_command"
_RESET = "ha_reset_lovelace_dashboard_config"
# El aspirador de plantilla de `ha_config/configuration.yaml`.
_ASPIRADOR = "vacuum.banco_aspirador"


async def _dashboard(s: SesionEscrituras, url_path: str) -> dict[str, Any] | None:
    for d in await s.lector.comando({"type": "lovelace/dashboards/list"}):
        if d.get("url_path") == url_path:
            return d
    return None


async def _config_guardada(s: SesionEscrituras, url_path: str) -> Any:
    """La configuración guardada, o `None` si Core responde `config_not_found`."""
    try:
        return await s.lector.comando({"type": "lovelace/config", "url_path": url_path})
    except ErrorCore as exc:
        if exc.codigo == "config_not_found":
            return None
        raise


async def _automatizacion(s: SesionEscrituras, id_: str, config: dict[str, Any]) -> str:
    """Automatización creada por el lector (REST de Core); devuelve su entity_id."""
    s.limpiar_config("automation", id_)
    estado, cuerpo = await s.lector.rest(
        "POST", f"/api/config/automation/config/{id_}", config)
    assert estado == 200, (estado, cuerpo)

    async def entidad() -> str | None:
        for e in await s.lector.comando({"type": "config/entity_registry/list"}):
            if e.get("platform") == "automation" and e.get("unique_id") == id_:
                return e["entity_id"]
        return None

    return await s.lector.esperar(entidad, lambda e: e is not None,
                                  descripcion=f"automatización {id_} registrada")


class TestRestablecerDashboard(BancoEscrituras):
    async def test_restablecer_con_vista_previa_sin_efecto(self) -> None:
        hexa = sufijo()
        url_path = f"banco-{hexa}"
        async with self.sesion() as s:

            async def borrar() -> None:
                d = await _dashboard(s, url_path)
                if d is not None:
                    await s.lector.comando(
                        {"type": "lovelace/dashboards/delete", "dashboard_id": d["id"]})

            s.limpiezas.append(borrar)
            await s.accion("ha_create_lovelace_dashboard", url_path=url_path,
                           title=f"Banco {hexa}", icon="mdi:test-tube")
            await s.lector.esperar(lambda: _dashboard(s, url_path), lambda d: d is not None,
                                   descripcion=f"{url_path} creado")
            config = {"title": f"Banco {hexa}", "views": [
                {"title": "Vista", "path": "vista", "cards": [
                    {"type": "markdown", "content": "banco de pruebas"},
                    {"type": "markdown", "content": "segunda tarjeta"}]}]}
            await s.lector.comando(
                {"type": "lovelace/config/save", "url_path": url_path, "config": config})
            self.assertEqual(await _config_guardada(s, url_path), config)

            # Vista previa: cuenta lo que se pierde y no borra nada.
            vista = await s.vista(_RESET, url_path=url_path)
            p = vista["preview"]
            self.assertEqual((p["url_path"], p["mode"], p["views"], p["cards"]),
                             (url_path, "storage", 1, 2))
            self.assertEqual(await _config_guardada(s, url_path), config)

            r = await s.confirmar(_RESET, vista, url_path=url_path)
            self.assertEqual(r, {"result": "ok", "url_path": url_path,
                                 "views_removed": 1, "cards_removed": 2})
            await s.lector.esperar(lambda: _config_guardada(s, url_path), lambda c: c is None,
                                   descripcion=f"{url_path} autogenerado")
            # El dashboard sigue existiendo: solo se borró su configuración.
            self.assertIsNotNone(await _dashboard(s, url_path))

            # Otra vez: ya no hay nada que restablecer, sin token.
            r = await rechazo(s.cliente, _RESET, url_path=url_path)
            self.assertEqual(r["error"], "nothing_to_reset")

    async def test_el_principal_se_rechaza_sin_token(self) -> None:
        async with self.sesion() as s:
            r = await rechazo(s.cliente, _RESET, url_path="lovelace")
            self.assertEqual(r["error"], "cannot_reset_default_dashboard")
            self.assertNotIn("confirmation_token", r)


class TestLecturasDeLaUI(BancoEscrituras):
    async def test_webhook_list_tapa_el_id_y_trace_contexts(self) -> None:
        hexa = sufijo()
        id_ = f"banco_024_{hexa}"
        webhook_id = f"banco-024-{hexa}"
        async with self.sesion() as s:
            # El alias repite el id (como el nombre de ONVIF, T032): Core lo
            # devuelve como `name` en `webhook/list` y tiene que salir tapado.
            entidad = await _automatizacion(s, id_, {
                "alias": f"Banco 024 {webhook_id}",
                "triggers": [{"trigger": "webhook", "webhook_id": webhook_id,
                              "local_only": True}],
                "actions": [{"event": f"banco_024_{hexa}"}],
            })

            async def webhooks() -> list[dict[str, Any]]:
                return await s.lector.comando({"type": "webhook/list"})

            await s.lector.esperar(
                webhooks, lambda ws: any(w["webhook_id"] == webhook_id for w in ws),
                descripcion="webhook de la automatización registrado")
            r = await s.accion(_LEER, type="webhook/list")
            self.assertNotIn(webhook_id, json.dumps(r))
            de_automatizacion = [w for w in r["items"] if w.get("domain") == "automation"]
            self.assertTrue(de_automatizacion, r)
            self.assertTrue(all(w["webhook_id"] == "***REDACTED***" for w in r["items"]))
            self.assertIn("Banco 024 ***REDACTED***",
                          [w.get("name") for w in de_automatizacion])

            # Dispara la automatización (por el lector) y busca su traza.
            await s.lector.comando({"type": "call_service", "domain": "automation",
                                    "service": "trigger",
                                    "target": {"entity_id": entidad}})

            async def contextos() -> dict[str, Any]:
                return await s.lector.comando(
                    {"type": "trace/contexts", "domain": "automation", "item_id": id_})

            await s.lector.esperar(contextos, lambda c: len(c) >= 1,
                                   descripcion="contexto de la traza")
            r = await s.accion(_LEER, type="trace/contexts",
                               payload={"domain": "automation", "item_id": id_})
            self.assertEqual(r["result"], await contextos())
            self.assertTrue(all(v["item_id"] == id_ for v in r["result"].values()))

    async def test_temas_segmentos_y_radiofrecuencia(self) -> None:
        async with self.sesion() as s:
            r = await s.accion(_LEER, type="frontend/get_themes")
            self.assertEqual(r["result"], await s.lector.comando({"type": "frontend/get_themes"}))
            self.assertIn("default_theme", r["result"])

            await s.esperar_estado(_ASPIRADOR, lambda e: e is not None, "aspirador cargado")
            r = await s.accion(_LEER, type="vacuum/get_segments",
                               payload={"entity_id": _ASPIRADOR})
            self.assertEqual([g["id"] for g in r["result"]["segments"]], ["cocina", "salon"])

            r = await s.accion(_LEER, type="radio_frequency/list")
            self.assertEqual(r["result"],
                             await s.lector.comando({"type": "radio_frequency/list"}))
            self.assertIn("transmitters", r["result"])


class TestRegistrosYCredenciales(BancoEscrituras):
    async def test_lecturas_de_los_registros(self) -> None:
        async with self.sesion() as s:
            r = await s.accion(_LEER, type="config/entity_registry/settings/get")
            self.assertEqual(r["result"], await s.lector.comando(
                {"type": "config/entity_registry/settings/get"}))
            self.assertIn("entity_id_parts", r["result"])

            r = await s.accion(_LEER, type="config/entity_registry/get_automatic_entity_ids",
                               payload={"entity_ids": [_ASPIRADOR]})
            self.assertIn(_ASPIRADOR, r["result"])

            dispositivos = await s.lector.comando({"type": "config/device_registry/list"})
            self.assertTrue(dispositivos, "el banco no tiene dispositivos (kitchen_sink)")
            device_id = dispositivos[0]["id"]
            r = await s.accion(_LEER, type="config/device_registry/list_linked_devices",
                               payload={"device_id": device_id})
            self.assertEqual(r["result"], await s.lector.comando(
                {"type": "config/device_registry/list_linked_devices",
                 "device_id": device_id}))

    async def test_reordenar_las_areas_en_dos_pasos(self) -> None:
        async with self.sesion() as s:
            for nombre in (f"Banco 024 A {sufijo()}", f"Banco 024 B {sufijo()}"):
                area = await s.lector.comando(
                    {"type": "config/area_registry/create", "name": nombre})

                async def borrar(area_id: str = area["area_id"]) -> None:
                    await s.lector.comando(
                        {"type": "config/area_registry/delete", "area_id": area_id})

                s.limpiezas.append(borrar)

            async def orden() -> list[str]:
                return [a["area_id"] for a in
                        await s.lector.comando({"type": "config/area_registry/list"})]

            original = await orden()
            self.assertGreaterEqual(len(original), 2)

            async def restaurar() -> None:
                actual = await orden()
                await s.lector.comando({
                    "type": "config/area_registry/reorder",
                    "area_ids": [a for a in original if a in actual]
                    + [a for a in actual if a not in original]})

            s.limpiezas.append(restaurar)
            invertido = list(reversed(original))
            carga = {"area_ids": invertido}
            vista = await s.vista(_LLAMAR, type="config/area_registry/reorder", payload=carga)
            self.assertEqual(vista["preview"]["cap"], "CAP-070")
            self.assertEqual(await orden(), original)
            await s.confirmar(_LLAMAR, vista, type="config/area_registry/reorder", payload=carga)
            await s.lector.esperar(orden, lambda o: o == invertido,
                                   descripcion="áreas en el orden nuevo")

    async def test_credenciales_de_aplicacion(self) -> None:
        async with self.sesion() as s:
            r = await s.accion(_LEER, type="application_credentials/config")
            self.assertEqual(r["result"], await s.lector.comando(
                {"type": "application_credentials/config"}))
            self.assertIn("domains", r["result"])

            # El banco no tiene credenciales (crearlas es clase D): la lista
            # vacía basta para ejecutar el comando; el centinela del
            # `client_secret` está en los unitarios de la genérica.
            r = await s.accion(_LEER, type="application_credentials/list")
            self.assertEqual(r["items"], await s.lector.comando(
                {"type": "application_credentials/list"}))
