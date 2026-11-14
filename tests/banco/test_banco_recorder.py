"""Banco de Core: la familia `recorder` y las lecturas por la tabla de la 029
contra HA Core 2026.11.1 real (spec 029, T030; FR-012, FR-013, FR-022).

Las tres tools leen, así que lo que se comprueba es que funcionan contra la
HA de verdad y, donde se puede, se contrasta con el lector independiente
(directo a Core, sin Hermes):

- `ha_get_recorder_info`: el recorder graba, con los mismos campos que da
  `recorder/info` al lector; con el `entity_id` de un `input_boolean` que crea
  el lector, `recorded: true`; con uno que no existe, `not_found`;
- `ha_validate_statistics`: responde con el sobre y cada problema es de una
  estadística que el lector también ve con problemas. `kitchen_sink` importa
  con el recorder cargado estadísticas hechas para dar problemas, así que la
  lista no suele salir vacía;
- `ha_get_statistics_metadata`: una estadística real (la primera que lista el
  lector, de las que importa `kitchen_sink`) igual que la ve el lector, y
  `sensor.no_existe` en `missing`;
- auditoría: tras `input_boolean.turn_on` por `ha_call_service`,
  `ha_read_ws_command("logbook/get_action_calls", …)` incluye esa llamada
  (CAP-058);
- `network`, `network/url` y `http/config` responden por la genérica de
  lectura (CAP-068);
- la genérica rechaza `recorder/info` hacia su tool.

La configuración del banco carga `recorder:` y `logbook:` (ver
`ha_config/configuration.yaml`).

Inventario: `PROBADAS_EN_BANCO_029` (`tests/banco/cobertura.py`); el job exige
que cada una se haya llamado con éxito en un test que ha pasado.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from tests.banco.base_helpers import BancoHelpers, nombre_de_prueba, sin_error
from tests.banco.entorno import llamar

pytestmark = pytest.mark.banco

# El recorder confirma en la base cada pocos segundos (`commit_interval`, 5 s
# por defecto): lo que se lee de la base puede tardar en aparecer.
_ESPERA_BASE = 30.0


async def _rechazo(cliente: Any, tool: str, **args: Any) -> dict[str, Any]:
    """Llama a una tool que DEBE rechazar y devuelve su `{"error": …}` (como
    en `test_banco_genericas.py`: `llamar` convertiría el rechazo en fallo)."""
    resultado = await cliente.call_tool(tool, args)
    assert getattr(resultado, "is_error", False), f"{tool}: se esperaba un rechazo"
    return json.loads(resultado.content[0].text)


async def _input_boolean(s: Any) -> str:
    """Crea con el lector un `input_boolean` (se borra al cerrar la sesión)."""
    creado = await s.lector.crear("input_boolean", {"name": nombre_de_prueba("input_boolean")})
    s.creados.append(("input_boolean", creado["id"]))
    entity_id = f"input_boolean.{creado['id']}"
    await s.esperar_estado(entity_id, lambda e: True, "creado")
    return entity_id


class TestRecorder(BancoHelpers):
    async def test_info_del_recorder(self) -> None:
        tool = "ha_get_recorder_info"
        async with self.sesion() as s:
            r = sin_error(tool, await llamar(s.cliente, tool))
            directo = await s.lector.comando({"type": "recorder/info"})
            self.assertIs(r["recording"], True)
            self.assertIs(r["thread_running"], True)
            self.assertEqual(set(r), set(directo))
            for clave in ("recording", "thread_running", "max_backlog",
                          "migration_in_progress", "db_in_default_location"):
                self.assertEqual(r[clave], directo[clave], clave)

            entity_id = await _input_boolean(s)
            r = sin_error(tool, await llamar(s.cliente, tool, entity_id=entity_id))
            self.assertEqual(r["entity"], {"entity_id": entity_id, "recorded": True,
                                           "recording_disabled_by": None})
            opciones = await s.lector.comando(
                {"type": "recorder/entity_options/get", "entity_id": entity_id})
            self.assertIsNone(opciones["recording_disabled_by"])

            no = await _rechazo(s.cliente, tool, entity_id="input_boolean.banco_no_existe")
            self.assertEqual(no["error"], "not_found")

    async def test_validar_estadisticas(self) -> None:
        tool = "ha_validate_statistics"
        async with self.sesion() as s:
            r = sin_error(tool, await llamar(s.cliente, tool))
            for clave in ("count", "truncated", "by_type", "items"):
                self.assertIn(clave, r)
            self.assertEqual(r["count"], len(r["items"]))
            self.assertGreaterEqual(sum(r["by_type"].values()), r["count"])
            directo = await s.lector.comando({"type": "recorder/validate_statistics"})
            con_problemas = {k for k, v in directo.items() if v}
            for item in r["items"]:
                self.assertEqual(set(item), {"statistic_id", "type", "data"})
                self.assertIn(item["statistic_id"], con_problemas)

    async def test_metadatos_de_estadisticas(self) -> None:
        tool = "ha_get_statistics_metadata"
        async with self.sesion() as s:
            # `kitchen_sink` importa sus estadísticas al arrancar, por la cola
            # del recorder: se espera a que el lector vea alguna.
            lista = await s.lector.esperar(
                lambda: s.lector.comando({"type": "recorder/list_statistic_ids"}),
                lambda v: bool(v),
                descripcion="alguna estadística en recorder/list_statistic_ids",
                timeout=_ESPERA_BASE,
            )
            real = sorted(x["statistic_id"] for x in lista)[0]
            r = sin_error(tool, await llamar(
                s.cliente, tool, statistic_ids=[real, "sensor.no_existe", real]))
            self.assertEqual(r["missing"], ["sensor.no_existe"])
            self.assertEqual([i["statistic_id"] for i in r["items"]], [real])
            directo = await s.lector.comando(
                {"type": "recorder/get_statistics_metadata", "statistic_ids": [real]})
            self.assertEqual(r["items"][0], directo[0])

    async def test_auditoria_de_llamadas(self) -> None:
        async with self.sesion() as s:
            entity_id = await _input_boolean(s)
            inicio = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
            sin_error("ha_call_service", await llamar(
                s.cliente, "ha_call_service", domain="input_boolean", service="turn_on",
                service_data={"entity_id": entity_id}))

            def es_la_llamada(item: dict[str, Any]) -> bool:
                datos = item.get("service_data") or {}
                eids = datos.get("entity_id")
                eids = eids if isinstance(eids, list) else [eids]
                return ((item.get("domain"), item.get("service")) == ("input_boolean", "turn_on")
                        and entity_id in eids)

            async def leer() -> dict[str, Any]:
                return sin_error("ha_read_ws_command", await llamar(
                    s.cliente, "ha_read_ws_command", type="logbook/get_action_calls",
                    payload={"start_time": inicio}))

            r = await s.lector.esperar(
                leer, lambda v: any(es_la_llamada(i) for i in v.get("items", [])),
                descripcion="input_boolean.turn_on en logbook/get_action_calls",
                timeout=_ESPERA_BASE,
            )
            self.assertNotIn("error", r)

    async def test_red_y_http_por_la_generica(self) -> None:
        tool = "ha_read_ws_command"
        async with self.sesion() as s:
            red = sin_error(tool, await llamar(s.cliente, tool, type="network"))
            self.assertIn("adapters", red["result"])
            urls = sin_error(tool, await llamar(s.cliente, tool, type="network/url"))
            self.assertEqual(set(urls["result"]), {"internal", "external", "cloud"})
            http = sin_error(tool, await llamar(s.cliente, tool, type="http/config"))
            self.assertIn("stable", http["result"])

    async def test_la_generica_rechaza_hacia_la_dedicada(self) -> None:
        async with self.sesion() as s:
            r = await _rechazo(s.cliente, "ha_read_ws_command", type="recorder/info")
            self.assertEqual((r["error"], r["tool"]),
                             ("use_dedicated_tool", "ha_get_recorder_info"))
