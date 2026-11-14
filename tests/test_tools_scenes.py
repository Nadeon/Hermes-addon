"""Tests de tools de scenes con transporte REST mockeado."""

from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path

from aiohttp import ClientSession
from aioresponses import aioresponses

from hermes import security
from hermes.models.scene import SceneConfig
import hermes.tools.scenes as scenes_module

from tests._ha_fixture import REST_BASE, make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class TestToolsScenes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)

        self.session = ClientSession()
        self.cache = {
            "scene.fiesta": {
                "entity_id": "scene.fiesta",
                "state": "scening",
                "attributes": {
                    "id": "1710000000001",
                    "friendly_name": "Fiesta",
                    "icon": "mdi:party-popper",
                },
            }
        }
        self.ha_client = make_ready_client(self.session, self.cache)
        self.mcp = DummyMCP()
        scenes_module.register(self.mcp, self.ha_client)

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    # ── list ────────────────────────────────────────────────

    async def test_list_scenes(self) -> None:
        result = await self.mcp.tools["ha_list_scenes"]()
        parsed = json.loads(result)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["entity_id"], "scene.fiesta")
        self.assertEqual(parsed[0]["friendly_name"], "Fiesta")
        self.assertEqual(parsed[0]["icon"], "mdi:party-popper")

    # ── get ─────────────────────────────────────────────────

    async def test_get_scene_returns_config_and_state(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=200,
                payload={
                    "id": "1710000000001",
                    "name": "Fiesta",
                    "entities": {"light.salon": "on"},
                },
            )
            result = await self.mcp.tools["ha_get_scene"]("scene.fiesta")

        self.assertEqual(result["config"]["name"], "Fiesta")
        self.assertEqual(result["state"]["entity_id"], "scene.fiesta")

    async def test_get_scene_missing_config(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_get_scene"]("scene.fiesta")

        self.assertIsNone(result["config"])
        self.assertEqual(result["state"]["entity_id"], "scene.fiesta")

    # ── update ──────────────────────────────────────────────

    async def test_update_scene_preview_when_exists(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=200,
                payload={"name": "Fiesta antigua", "entities": {"light.salon": "off"}},
            )
            result = await self.mcp.tools["ha_create_or_update_scene"](
                "scene.fiesta",
                {"name": "Fiesta nueva", "entities": {"light.salon": "on"}},
            )

        self.assertIn("confirmation_token", result)
        self.assertEqual(result["preview"]["current"]["name"], "Fiesta antigua")
        self.assertEqual(result["preview"]["new"]["name"], "Fiesta nueva")

    async def test_update_scene_apply_with_token(self) -> None:
        new_config = {"name": "Fiesta nueva", "entities": {"light.salon": "on"}}
        normalized = SceneConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_scene",
            {"scene_id": "scene.fiesta", "config": normalized},
        )
        token = token_response["confirmation_token"]

        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=200,
                payload={"result": "ok"},
            )
            result = await self.mcp.tools["ha_create_or_update_scene"](
                "scene.fiesta",
                new_config,
                confirmation_token=token,
            )

        self.assertEqual(result, {"result": "ok"})

    async def test_update_scene_creates_directly_when_not_exists(self) -> None:
        """Sin token y sin config previa: se crea directamente."""
        new_config = {"name": "Nueva", "entities": {"light.cocina": "on"}}

        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=404,
                body="nope",
            )
            m.post(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=200,
                payload={"result": "ok"},
            )
            result = await self.mcp.tools["ha_create_or_update_scene"](
                "scene.fiesta",
                new_config,
            )

        self.assertEqual(result, {"result": "ok"})

    async def test_update_scene_refuses_when_current_config_cannot_be_read(self) -> None:
        """Un error transitorio al leer la config se trataba como "no existe"
        y se sobreescribía la escena sin vista previa ni token."""
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=502,
                body="bad gateway",
            )
            result = await self.mcp.tools["ha_create_or_update_scene"](
                "scene.fiesta",
                {"name": "Nueva", "entities": {"light.cocina": "on"}},
            )
            posted = [k for k in m.requests if k[0].upper() == "POST"]

        self.assertEqual(result.get("error"), "ha_unavailable", result)
        self.assertEqual(posted, [])

    # ── delete ──────────────────────────────────────────────

    async def test_delete_scene_requires_token(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=200,
                payload={"name": "Fiesta"},
            )
            result = await self.mcp.tools["ha_delete_scene"]("scene.fiesta")

        self.assertIn("confirmation_token", result)

    async def test_delete_scene_apply(self) -> None:
        token_response = await security.create_confirmation_token(
            "ha_delete_scene",
            {"scene_id": "scene.fiesta"},
        )
        token = token_response["confirmation_token"]

        with aioresponses() as m:
            m.delete(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=200,
                payload={"result": "ok"},
            )
            result = await self.mcp.tools["ha_delete_scene"](
                "scene.fiesta",
                confirmation_token=token,
            )

        self.assertEqual(result, {"result": "ok"})

    # ── service wrappers ────────────────────────────────────

    async def test_activate_scene_calls_service(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/scene/turn_on",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_activate_scene"](
                "scene.fiesta",
                transition=2.5,
            )
        self.assertEqual(result, [])

    # ── Bug 1: serialization ────────────────────────────────

    async def test_update_scene_body_has_no_nulls(self) -> None:
        new_config = {
            "name": "Fiesta",
            "icon": None,
            "entities": {"light.salon": "on"},
        }
        normalized = SceneConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_scene",
            {"scene_id": "scene.fiesta", "config": normalized},
        )
        token = token_response["confirmation_token"]

        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=200,
                payload={"result": "ok"},
            )
            await self.mcp.tools["ha_create_or_update_scene"](
                "scene.fiesta",
                new_config,
                confirmation_token=token,
            )
            posted = None
            for (method, _url), calls in m.requests.items():
                if method.upper() == "POST":
                    posted = calls[0].kwargs.get("json")
                    break

        self.assertIsNotNone(posted)
        self.assertNotIn("icon", posted)
        for k, v in posted.items():
            self.assertIsNotNone(v, f"clave {k} no debería ser null")

    # ── Bug 3: existence check ─────────────────────────────

    async def test_activate_scene_not_found(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/scene.fantasma",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_activate_scene"]("scene.fantasma")
        self.assertEqual(
            result,
            {"error": "not_found", "entity_id": "scene.fantasma"},
        )

    async def test_reload_scenes(self) -> None:
        """Recargar exige confirmación: `scene.reload` está en la denylist.

        Antes esta tool llamaba directa al cliente y ejecutaba el servicio sin
        token, pese a que la denylist lo veta expresamente ("Reloads que pueden
        activar YAML envenenado"). Era la ruta limpia para materializar un
        fs_write_file malicioso previo.
        """
        # 1. Sin token: preview + confirmation_token, y NADA se ejecuta.
        first = await self.mcp.tools["ha_reload_scenes"]()
        payload = json.loads(first) if isinstance(first, str) else first
        self.assertIn("confirmation_token", payload)
        self.assertEqual(payload["preview"]["service"], "scene.reload")

        # 2. Con el token: se ejecuta.
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/scene/reload",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_reload_scenes"](
                confirmation_token=payload["confirmation_token"]
            )
        self.assertEqual(result, [])



class TestConfirmarSinConfigScene(unittest.IsolatedAsyncioTestCase):
    """Confirmar `ha_create_or_update_scene` sin reenviar `config` (spec 007, Hermes 1.1.2).

    La vista previa guarda la configuración normalizada junto al token; la
    confirmación con solo `scene_id` y `confirmation_token` guarda
    exactamente esa. Control negativo comprobado: con `scenes.py` de 1.1.1
    (`config` obligatorio y `validate_confirmation_token`) caen todos los de
    esta clase; con `resolve_confirmation_token` tomando lo guardado aunque se
    envíe otro `config`, cae el de config distinto.
    """

    asyncSetUp = TestToolsScenes.asyncSetUp
    asyncTearDown = TestToolsScenes.asyncTearDown

    URL = f"{REST_BASE}/config/scene/config/1710000000001"
    NUEVA = {'name': 'Ficticia nueva', 'entities': {'light.salon': 'on'}}
    OTRA = {'name': 'Ficticia distinta', 'entities': {'light.salon': 'off'}}

    async def _vista_previa(self) -> dict:
        with aioresponses() as m:
            m.get(self.URL, status=200, payload={'name': 'Ficticia antigua', 'entities': {'light.salon': 'off'}})
            return await self.mcp.tools["ha_create_or_update_scene"]("scene.fiesta", self.NUEVA)

    async def _confirmar(self, token: str, **extra) -> tuple[object, list]:
        with aioresponses() as m:
            m.post(self.URL, status=200, payload={"result": "ok"})
            res = await self.mcp.tools["ha_create_or_update_scene"](
                "scene.fiesta", confirmation_token=token, **extra)
            enviados = [
                c.kwargs.get("json")
                for (metodo, _url), llamadas in m.requests.items()
                if metodo.upper() == "POST"
                for c in llamadas
            ]
        return res, enviados

    async def test_confirmar_sin_config_guarda_la_de_la_vista_previa(self) -> None:
        r = await self._vista_previa()
        self.assertEqual(r["omit_on_confirm"], ["config"])
        self.assertEqual(r["confirm_with"], ["confirmation_token", "scene_id"])
        self.assertIn("scene_id", r["confirm_hint"])
        res, enviados = await self._confirmar(r["confirmation_token"])
        self.assertEqual(res, {"result": "ok"})
        normalizada = SceneConfig.model_validate(self.NUEVA).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        self.assertEqual(enviados, [normalizada])

    async def test_sin_token_y_sin_config_es_invalid_argument(self) -> None:
        with aioresponses() as m:
            res = await self.mcp.tools["ha_create_or_update_scene"]("scene.fiesta")
            self.assertEqual(dict(m.requests), {})
        self.assertEqual(res["error"], "invalid_argument")
        self.assertEqual(res["field"], "config")
        self.assertNotIn("confirmation_token", res)
        self.assertEqual(list(security.CONFIRMATIONS_DIR.glob("*.json")), [])

    async def test_config_distinto_al_confirmar_no_vale(self) -> None:
        r = await self._vista_previa()
        res, enviados = await self._confirmar(r["confirmation_token"], config=self.OTRA)
        self.assertEqual(res, {"error": "confirmation_token does not match this action."})
        self.assertEqual(enviados, [])
        # El token no se ha gastado: la confirmación correcta sigue sirviendo.
        res, enviados = await self._confirmar(r["confirmation_token"])
        self.assertEqual(res, {"result": "ok"})
        self.assertEqual(len(enviados), 1)

    async def test_escena_nueva_sin_config_no_guarda_nada(self) -> None:
        """La escena nueva no pide token: sin `config` no hay nada que crear."""
        with aioresponses() as m:
            m.get(self.URL, status=404, body="nope")
            res = await self.mcp.tools["ha_create_or_update_scene"]("scene.fiesta")
            enviados = [k for k in m.requests if k[0].upper() == "POST"]
        self.assertEqual(res["error"], "invalid_argument")
        self.assertEqual(res["field"], "config")
        self.assertEqual(enviados, [])


class TestEscenaDesdeElEstadoActual(unittest.IsolatedAsyncioTestCase):
    """Spec 033 (FR-006, T021): `ha_create_scene_from_current` dice y hace
    lo que hace `scene.create` de Core (research R-4).

    El doble de HA imita a Core: `scene.create` crea o reemplaza la escena
    temporal con las entidades capturadas (atributo `entity_id`), y el
    estado posterior se lee por REST sin caché.

    Control negativo (T024), comprobado y restaurado: ver el recuento en el
    commit del tramo 2 (mandar otra vez `name`, quitar la consulta de
    existencia, quitar la comprobación posterior).
    """

    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self.session = ClientSession()

        def luz(eid: str) -> dict:
            return {"entity_id": eid, "state": "on", "attributes": {}}

        self.estados: dict[str, dict] = {
            "light.salon": luz("light.salon"),
            "light.cocina": luz("light.cocina"),
            # Temporal: de `scene.create`, sin `id` y sin registro.
            "scene.temporal": {
                "entity_id": "scene.temporal",
                "state": "unknown",
                "attributes": {"entity_id": ["light.salon"], "friendly_name": "temporal"},
                "last_updated": "2026-01-01T00:00:00+00:00",
            },
            # De configuración (`scenes.yaml`): con `id`.
            "scene.fiesta": {
                "entity_id": "scene.fiesta",
                "state": "unknown",
                "attributes": {"id": "1710000000001", "entity_id": ["light.salon"]},
            },
            # De otra integración: sin `id`, pero en el registro de entidades.
            "scene.de_integracion": {
                "entity_id": "scene.de_integracion",
                "state": "unknown",
                "attributes": {"friendly_name": "De integración"},
            },
        }
        self.registro = {"scene.de_integracion"}
        self.llamadas: list[tuple] = []
        # Si el doble de `scene.create` no hace nada (como Core ante una
        # escena de configuración sin `id`, o sin entidades).
        self.ignorar_create = False
        # Core quita la escena y añade otra: cada `scene.create` que hace
        # algo deja un `last_updated` nuevo.
        self.relojes = 0

        self.ha_client = make_ready_client(self.session, self.estados)

        async def call_service(domain, service, data=None, **kwargs):
            self.llamadas.append((domain, service, data))
            if (domain, service) == ("scene", "create") and not self.ignorar_create:
                eid = "scene." + data["scene_id"]
                self.relojes += 1
                self.estados[eid] = {
                    "entity_id": eid,
                    "state": "unknown",
                    "attributes": {"entity_id": list(data["snapshot_entities"])},
                    "last_updated": f"2026-01-02T00:00:{self.relojes:02d}+00:00",
                }
            return [{"respuesta": "de HA"}]

        async def ws_send(payload, timeout_seconds=30):
            from hermes.ha import HAConnectionError

            self.assertEqual(payload["type"], "config/entity_registry/get")
            if payload["entity_id"] in self.registro:
                return {"entity_id": payload["entity_id"], "unique_id": "u1"}
            raise HAConnectionError("Entity not found", code="not_found")

        async def request_json(method, path, json_body=None, params=None):
            from hermes.ha import HAConnectionError

            self.assertEqual(method, "GET")
            eid = path.removeprefix("/states/")
            if eid not in self.estados:
                raise HAConnectionError("404", status=404)
            return self.estados[eid]

        self.ha_client.call_service = call_service  # type: ignore[method-assign]
        self.ha_client.ws_send = ws_send  # type: ignore[method-assign]
        self.ha_client._request_json = request_json  # type: ignore[method-assign]
        self.mcp = DummyMCP()
        scenes_module.register(self.mcp, self.ha_client)
        self.tool = self.mcp.tools["ha_create_scene_from_current"]

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def test_name_no_soportado(self) -> None:
        r = await self.tool("scene.nueva", ["light.salon"], name="Nueva")
        self.assertEqual(r["error"], "name_not_supported")
        self.assertIn("ha_create_or_update_scene", r["hint"])
        self.assertIn("1.3.0", r["_deprecated"])
        self.assertEqual(self.llamadas, [])

    async def test_entidad_inexistente(self) -> None:
        r = await self.tool("scene.nueva", ["light.salon", "light.inexistente"])
        self.assertEqual(r, {"error": "entity_not_found", "entity_ids": ["light.inexistente"]})
        self.assertEqual(self.llamadas, [])

    async def test_escena_nueva_sin_token(self) -> None:
        r = await self.tool("nueva", ["light.salon", "light.cocina"])
        self.assertEqual(
            self.llamadas,
            [("scene", "create", {"scene_id": "nueva",
                                  "snapshot_entities": ["light.salon", "light.cocina"]})],
        )
        self.assertEqual(r["result"], "ok")
        self.assertEqual(r["scene_id"], "scene.nueva")
        self.assertEqual(r["entity_ids"], ["light.salon", "light.cocina"])
        self.assertIs(r["replaced"], False)
        self.assertIs(r["temporary"], True)
        self.assertEqual(r["ha_response"], [{"respuesta": "de HA"}])

    async def test_reemplazo_de_temporal_en_dos_pasos(self) -> None:
        nuevas = ["light.salon", "light.cocina"]
        vista = await self.tool("scene.temporal", nuevas)
        self.assertEqual(self.llamadas, [])
        self.assertIn("confirmation_token", vista)
        p = vista["preview"]
        self.assertEqual(p["action"], "scene.create")
        self.assertEqual(p["scene_id"], "scene.temporal")
        self.assertEqual(p["current_entities"], ["light.salon"])
        self.assertEqual(p["new_entities"], nuevas)
        self.assertIn("restart", p["effect"])

        r = await self.tool("scene.temporal", nuevas, confirmation_token=vista["confirmation_token"])
        self.assertEqual(len(self.llamadas), 1)
        self.assertEqual(r["result"], "ok")
        self.assertIs(r["replaced"], True)
        self.assertEqual(self.estados["scene.temporal"]["attributes"]["entity_id"], nuevas)

    async def test_reemplazo_con_otras_entidades_rechaza_el_token(self) -> None:
        vista = await self.tool("scene.temporal", ["light.cocina"])
        r = await self.tool(
            "scene.temporal", ["light.salon", "light.cocina"],
            confirmation_token=vista["confirmation_token"],
        )
        self.assertIn("error", r)
        self.assertEqual(self.llamadas, [])

    async def test_escena_de_configuracion_existe(self) -> None:
        r = await self.tool("scene.fiesta", ["light.salon"])
        self.assertEqual(r["error"], "scene_exists")
        self.assertEqual(r["scene_id"], "scene.fiesta")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.llamadas, [])

    async def test_escena_del_registro_existe(self) -> None:
        r = await self.tool("scene.de_integracion", ["light.salon"])
        self.assertEqual(r["error"], "scene_exists")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.llamadas, [])

    async def test_escena_no_creada(self) -> None:
        # Core no hace nada: la escena sigue con las entidades de antes.
        self.ignorar_create = True
        vista = await self.tool("scene.temporal", ["light.cocina"])
        r = await self.tool("scene.temporal", ["light.cocina"],
                            confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "scene_not_created")
        self.assertEqual(r["scene_id"], "scene.temporal")
        self.assertEqual(r["seen_entity_ids"], ["light.salon"])
        self.assertEqual(len(self.llamadas), 1)

    async def test_reemplazo_ignorado_con_las_mismas_entidades(self) -> None:
        # T038 (B2 de la revisión): escena de YAML sin `id` (S-03), que la
        # tool ve como temporal, con las mismas entidades que se piden. Core
        # ignora `scene.create` y las entidades coinciden; solo el
        # `last_updated` sin cambiar delata que no se reemplazó.
        # Control negativo, comprobado y restaurado: sin la comparación de
        # `last_updated` en `scenes.py`, la tool responde `replaced: true` y
        # este test cae.
        self.ignorar_create = True
        vista = await self.tool("scene.temporal", ["light.salon"])
        r = await self.tool("scene.temporal", ["light.salon"],
                            confirmation_token=vista["confirmation_token"])
        self.assertEqual(r, {"error": "scene_not_created", "scene_id": "scene.temporal",
                             "seen_entity_ids": ["light.salon"]})
        self.assertEqual(len(self.llamadas), 1)

    async def test_reemplazo_real_con_las_mismas_entidades(self) -> None:
        # La otra cara de T038: si Core la recrea con las mismas entidades,
        # el `last_updated` cambia y es un reemplazo de verdad.
        vista = await self.tool("scene.temporal", ["light.salon"])
        r = await self.tool("scene.temporal", ["light.salon"],
                            confirmation_token=vista["confirmation_token"])
        self.assertEqual((r["result"], r["replaced"]), ("ok", True))

    async def test_token_ajeno_con_escena_nueva(self) -> None:
        # T039 (B3 de la revisión): con `confirmation_token` y la escena sin
        # existir, el token se valida igual (fail-closed). Ni uno aleatorio (con
        # forma válida, para pasar del chequeo de formato) ni
        # uno de otra tool hacen nada en HA.
        # Control negativo, comprobado y restaurado: validando solo dentro del
        # camino del reemplazo, los dos tokens pasan, se llama a
        # `scene.create` y este test cae.
        r = await self.tool("scene.nueva", ["light.salon"], confirmation_token=str(uuid.uuid4()))
        self.assertIn("expired or lost", r.get("error", ""))
        ajeno = await security.create_confirmation_token(
            "ha_delete_scene", {"scene_id": "nueva"}, preview={"action": "delete"}
        )
        r = await self.tool("scene.nueva", ["light.salon"],
                            confirmation_token=ajeno["confirmation_token"])
        self.assertIn("does not match", r.get("error", ""))
        self.assertEqual(self.llamadas, [])
        self.assertNotIn("scene.nueva", self.estados)

    async def test_escena_nueva_que_no_aparece(self) -> None:
        self.ignorar_create = True
        r = await self.tool("scene.nueva", ["light.salon"])
        self.assertEqual(r, {"error": "scene_not_created", "scene_id": "scene.nueva",
                             "seen_entity_ids": None})


class TestDescripcionesDeEscenas(unittest.TestCase):
    """Spec 033 (FR-007, T023): las escenas editables viven en `scenes.yaml`
    (`SCENE_CONFIG_PATH` de `components/config/scene.py`), no en
    `.storage/core.scene_*`, y las de `scene.create` no están en ese fichero
    (research R-5).

    Control negativo, comprobado y restaurado: con las docstrings de antes
    caen los dos tests.
    """

    def _docs(self) -> dict[str, str]:
        mcp = DummyMCP()
        scenes_module.register(mcp, object())
        return {n: mcp.tools[n].__doc__ or "" for n in
                ("ha_get_scene", "ha_create_or_update_scene", "ha_delete_scene")}

    def test_nombran_scenes_yaml(self) -> None:
        for nombre, doc in self._docs().items():
            self.assertIn("scenes.yaml", doc, nombre)
            self.assertNotIn(".storage/core.scene_", doc, nombre)

    def test_crear_o_editar_no_ve_las_de_scene_create(self) -> None:
        doc = " ".join(self._docs()["ha_create_or_update_scene"].split())
        # La 1.1.2 decía que el endpoint ve las escenas «creadas desde la UI o
        # con `scene.create`»: las de `scene.create` no están en scenes.yaml.
        self.assertNotIn("o con `scene.create`", doc)
        self.assertIn("ha_create_scene_from_current", doc)
