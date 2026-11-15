"""Tools de blueprints (spec 017, tramo A; T003–T007).

`ha_list_blueprints`, `ha_preview_blueprint_substitution`,
`ha_save_blueprint` y `ha_delete_blueprint` con Home Assistant simulado
(`AsyncMock` de `ws_send` con respuestas por `type`). Datos ficticios:
`light.salon`, rutas `hermes/…`, el centinela `centinela-017` y un JWT de
prueba, que no pueden salir en ninguna respuesta, vista previa, error, log de
Hermes ni fichero de token (salvo el `yaml` omitible de `ha_save_blueprint`,
que el token guarda como el `config` de las automatizaciones, spec 007).

Controles negativos del cierre del tramo (T016), cada uno visto en rojo y
restaurado, con recuentos en el commit:
(1) `_validar_ruta` sin la comprobación de `..` → cae
`TestRutasYYaml.test_rutas_invalidas`;
(2) la vista previa de guardar llamando a `blueprint/save` → cae
`TestGuardar.test_vista_previa_sin_escribir`;
(3) borrar sin consultar `search/related` → cae
`TestBorrar.test_en_uso_sin_token`;
(4) `blueprint_in_use` con token → cae `TestBorrar.test_en_uso_sin_token`;
(5) sin `redact_secrets` en el error de `ha_list_blueprints` → cae
`TestListar.test_error_de_carga_redactado`.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from structlog.testing import capture_logs

import hermes.security as security
import hermes.tools.blueprints as mod
from hermes.ha import HAConnectionError

_CENTINELA = "centinela-017"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJjZW50aW5lbGEifQ.c2lnbmF0dXJhLWZpY3RpY2lh"

_YAML = """\
blueprint:
  name: Luz por movimiento
  description: Enciende light.salon con movimiento
  domain: automation
  author: Banco
  homeassistant:
    min_version: 2024.6.0
  input:
    sensor:
      name: Sensor
      selector:
        entity: {}
    ajustes:
      name: Ajustes
      input:
        espera:
          name: Espera
          default: 120
triggers:
  - trigger: state
    entity_id: !input sensor
    to: "on"
actions:
  - action: light.turn_on
    target:
      entity_id: light.salon
"""

_YAML_CON_SECRETO = _YAML.replace(
    "Enciende light.salon con movimiento", f"Clave password={_CENTINELA} y {_JWT}")


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _meta(nombre: str, dominio: str = "automation", **extra: Any) -> dict[str, Any]:
    return {"metadata": {"name": nombre, "domain": dominio, "input": {"a": None}, **extra}}


class _Base(unittest.IsolatedAsyncioTestCase):
    max_bytes = 131_072

    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        # Respuestas por `type`: un valor, una excepción o una función.
        self.respuestas: dict[str, Any] = {
            "blueprint/list": lambda p: {
                "automation": {
                    "homeassistant/motion_light.yaml": _meta("Motion"),
                    "hermes/luz.yaml": _meta("Luz"),
                },
                "script": {"hermes/aviso.yaml": _meta("Aviso", "script")},
                "template": {"hermes/plantilla.yaml": _meta("Plantilla", "template")},
            }.get(p["domain"], {}),
            "search/related": {},
            "blueprint/save": {"overrides_existing": False},
            "blueprint/delete": None,
            "blueprint/substitute": {"substituted_config": {"triggers": []}},
        }
        self.enviados: list[dict[str, Any]] = []
        self.ha = MagicMock()
        self.ha.wait_ready = AsyncMock(return_value=True)
        self.ha.ws_send = AsyncMock(side_effect=self._ws_send)
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha, response_max_bytes=self.max_bytes)
        self.t = self.mcp.tools

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def _ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.enviados.append(payload)
        r = self.respuestas[payload["type"]]
        if isinstance(r, BaseException):
            raise r
        if callable(r):
            return r(payload)
        return r

    def tipos(self) -> list[str]:
        return [p["type"] for p in self.enviados]

    def ficheros_de_tokens(self) -> list[Path]:
        return list(Path(self.temp_dir.name).glob("*.json"))

    def texto_de_tokens(self) -> str:
        return "".join(p.read_text(encoding="utf-8") for p in self.ficheros_de_tokens())


# ── T003: helpers ─────────────────────────────────────────────────────────────


class TestRutasYYaml(unittest.TestCase):
    def test_rutas_validas(self) -> None:
        self.assertEqual(mod._validar_ruta("homeassistant/motion_light.yaml"),
                         ("homeassistant/motion_light.yaml", None))
        self.assertEqual(mod._validar_ruta("mio/luz"), ("mio/luz.yaml", None))
        self.assertEqual(mod._validar_ruta("Mi luz-1.v2"), ("Mi luz-1.v2.yaml", None))

    def test_rutas_invalidas(self) -> None:
        for ruta in ("../x", "a/../b", "..", "/abs", "\\x", "c:/x", "a\x00b", "a\nb", "",
                     "a//b", "./a", "a/", "x" * 256, "a/b$c", "a/b*c", None, 3):
            with self.subTest(ruta=ruta):
                final, error = mod._validar_ruta(ruta)
                self.assertIsNone(final)
                self.assertEqual((error["error"], error["field"]), ("invalid_argument", "path"))

    def test_dominios(self) -> None:
        for dominio in ("automation", "script", "template"):
            self.assertIsNone(mod._validar_dominio(dominio))
        for dominio in ("light", "", None, "Automation"):
            self.assertEqual(mod._validar_dominio(dominio)["field"], "domain")

    def test_yaml_con_input(self) -> None:
        doc = mod._cargar_yaml_blueprint(_YAML)
        self.assertEqual(doc["blueprint"]["name"], "Luz por movimiento")
        self.assertEqual(doc["triggers"][0]["entity_id"], {"tag": "!input", "value": "sensor"})
        # `!input` también en su forma literal y con ancla y alias.
        doc = mod._cargar_yaml_blueprint(
            _YAML + "extra: !<!input> sensor\notra: &a !input sensor\nrepe: *a\n")
        self.assertEqual(doc["extra"], {"tag": "!input", "value": "sensor"})
        self.assertEqual(doc["repe"], {"tag": "!input", "value": "sensor"})

    def test_etiquetas_distintas_de_input_rechazadas(self) -> None:
        # T055: HA resolvería estas etiquetas al guardar y escribiría el valor
        # resuelto (un secreto, un fichero, una variable de entorno).
        casos = {
            "!env_var": "x: !env_var SUPERVISOR_TOKEN\n",
            "!include": "x: !include /config/.storage/auth\n",
            "!include_dir_named": "x: !include_dir_named carpeta\n",
            "!include_dir_merge_list": "x: !include_dir_merge_list carpeta\n",
            "!secret": "x: !secret clave\n",
            "!rara": "x: !rara\n",  # sin argumento
            "!lista": "x: !lista [1, 2]\n",
            "!mapa": "x: !mapa {a: 1}\n",
            "!clave": "? !clave k\n: v\n",  # en una clave
            "!en_lista": "x:\n  - 1\n  - !en_lista v\n",
            "!anclada": "x: &a !anclada v\ny: *a\n",  # con ancla y alias
            "!": "x: ! v\n",  # etiqueta no específica
            "tag:yaml.org,2002:str": "x: !!str v\n",  # estándar, también fuera
            "tag:example.com,2000:input": "%TAG ! tag:example.com,2000:\n---\n"
                                          + _YAML,
        }
        for etiqueta, extra in casos.items():
            texto = extra if extra.startswith("%TAG") else _YAML + extra
            with self.subTest(etiqueta=etiqueta):
                self.assertEqual(mod._etiqueta_no_admitida(texto), etiqueta)
                with self.assertRaises(mod.EtiquetaNoAdmitida) as ctx:
                    mod._cargar_yaml_blueprint(texto)
                self.assertEqual(ctx.exception.etiqueta, etiqueta)
        # En un nivel anidado del propio blueprint (el `default` de una entrada).
        texto = _YAML.replace("default: 120", "default: !env_var SUPERVISOR_TOKEN")
        self.assertEqual(mod._etiqueta_no_admitida(texto), "!env_var")
        self.assertIsNone(mod._etiqueta_no_admitida(_YAML))

    def test_etiqueta_rechazada_sin_su_valor(self) -> None:
        with self.assertRaises(mod.EtiquetaNoAdmitida) as ctx:
            mod._cargar_yaml_blueprint(_YAML + f"x: !secret {_CENTINELA}\n")
        self.assertNotIn(_CENTINELA, str(ctx.exception))
        larga = "!" + "e" * 500
        self.assertLessEqual(len(mod.EtiquetaNoAdmitida(larga).etiqueta), 82)

    def test_yaml_rechazado(self) -> None:
        for texto in ("blueprint: [", "- a\n- b\n", "triggers: []\n", "blueprint: texto\n",
                      "a: !!python/object/apply:os.system ['x']\n",
                      "blueprint:\n  name: " + "x" * (256 * 1024) + "\n"):
            with self.subTest(texto=texto[:30]):
                with self.assertRaises(ValueError):
                    mod._cargar_yaml_blueprint(texto)

    def test_error_de_yaml_sin_el_contenido(self) -> None:
        # El mensaje de PyYAML cita la línea con el error: no puede salir.
        with self.assertRaises(ValueError) as ctx:
            mod._cargar_yaml_blueprint(f"blueprint:\n  name: [password={_CENTINELA}\n")
        self.assertNotIn(_CENTINELA, str(ctx.exception))
        self.assertIn("line", str(ctx.exception))

    def test_metadatos_y_entradas_con_secciones(self) -> None:
        doc = mod._cargar_yaml_blueprint(_YAML)
        meta = mod._metadatos(doc["blueprint"])
        self.assertEqual(meta, {"name": "Luz por movimiento",
                                "description": "Enciende light.salon con movimiento",
                                "author": "Banco", "domain": "automation",
                                "source_url": None, "min_version": "2024.6.0"})
        entradas = mod._entradas(doc["blueprint"]["input"])
        self.assertEqual([e["name"] for e in entradas], ["sensor", "espera"])
        self.assertEqual(entradas[1], {"name": "espera", "label": "Espera",
                                       "description": None, "has_default": True})
        # Nunca el valor por defecto: podría ser una contraseña.
        self.assertNotIn("120", json.dumps(entradas))


# ── T004: ha_list_blueprints ──────────────────────────────────────────────────


class TestListar(_Base):
    async def test_sin_dominio_los_tres(self) -> None:
        with capture_logs() as logs:
            r = await self.t["ha_list_blueprints"]()
        self.assertEqual(self.enviados, [
            {"type": "blueprint/list", "domain": d} for d in ("automation", "script", "template")
        ])
        self.assertEqual([(i["domain"], i["path"]) for i in r["items"]], [
            ("automation", "hermes/luz.yaml"),
            ("automation", "homeassistant/motion_light.yaml"),
            ("script", "hermes/aviso.yaml"),
            ("template", "hermes/plantilla.yaml"),
        ])
        self.assertEqual((r["count"], r["truncated"]), (4, False))
        self.assertEqual(r["_third_party_text"]["fields"], ["name", "description", "author"])
        self.assertNotIn("Luz", str(logs))

    async def test_con_dominio_solo_ese(self) -> None:
        r = await self.t["ha_list_blueprints"](domain="script")
        self.assertEqual(self.enviados, [{"type": "blueprint/list", "domain": "script"}])
        self.assertEqual([i["path"] for i in r["items"]], ["hermes/aviso.yaml"])

    async def test_campos_de_cada_elemento(self) -> None:
        self.respuestas["blueprint/list"] = lambda p: {
            "hermes/luz.yaml": {"metadata": {
                "name": "Luz", "description": "Desc", "author": "Autor", "domain": "automation",
                "source_url": "https://example.com/blueprints/luz.yaml",
                "homeassistant": {"min_version": "2024.6.0"},
                "input": {"sensor": {"name": "Sensor"},
                          "sec": {"name": "S", "input": {"espera": {"default": 3}}}},
            }}} if p["domain"] == "automation" else {}
        r = await self.t["ha_list_blueprints"](domain="automation")
        self.assertEqual(r["items"], [{
            "domain": "automation", "path": "hermes/luz.yaml", "name": "Luz",
            "description": "Desc", "author": "Autor",
            "source_url": "https://example.com/blueprints/luz.yaml",
            "min_version": "2024.6.0", "inputs": ["sensor", "espera"],
        }])

    async def test_error_de_carga_redactado(self) -> None:
        self.respuestas["blueprint/list"] = lambda p: {
            "hermes/roto.yaml": {"error": f"Invalid blueprint: password={_CENTINELA} {_JWT}"},
        } if p["domain"] == "automation" else {}
        r = await self.t["ha_list_blueprints"]()
        self.assertEqual(r["items"][0]["path"], "hermes/roto.yaml")
        self.assertIn("Invalid blueprint", r["items"][0]["error"])
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertNotIn(_JWT, json.dumps(r))

    async def test_metadatos_redactados(self) -> None:
        self.respuestas["blueprint/list"] = lambda p: {
            "hermes/x.yaml": _meta(f"token={_CENTINELA}", description=_JWT),
        } if p["domain"] == "automation" else {}
        r = await self.t["ha_list_blueprints"]()
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertNotIn(_JWT, json.dumps(r))

    async def test_dominio_invalido(self) -> None:
        r = await self.t["ha_list_blueprints"](domain="light")
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "domain"))
        self.ha.ws_send.assert_not_awaited()

    async def test_respuesta_que_no_es_mapa(self) -> None:
        self.respuestas["blueprint/list"] = ["raro"]
        r = await self.t["ha_list_blueprints"]()
        self.assertIn("error", r)
        self.assertNotIn("items", r)

    async def test_error_de_ha(self) -> None:
        self.respuestas["blueprint/list"] = HAConnectionError(
            f"HA WS command failed: password={_CENTINELA}", code="unknown_error")
        r = await self.t["ha_list_blueprints"]()
        self.assertIn("error", r)
        self.assertNotIn(_CENTINELA, json.dumps(r))

    async def test_recorte_por_tamano(self) -> None:
        self.respuestas["blueprint/list"] = lambda p: {
            f"hermes/b{i:03d}.yaml": _meta("x" * 500, description="y" * 500)
            for i in range(80)} if p["domain"] == "automation" else {}
        mcp = DummyMCP()
        mod.register(mcp, self.ha, response_max_bytes=20_000)
        r = await mcp.tools["ha_list_blueprints"]()
        self.assertTrue(r["truncated"])
        self.assertEqual(r["count"], len(r["items"]))
        self.assertLess(r["count"], 80)
        self.assertEqual(r["_response_limit"]["total"], 80)
        self.assertEqual(r["items"][0]["path"], "hermes/b000.yaml")
        self.assertLessEqual(len(json.dumps(r, ensure_ascii=False).encode()), 20_000)


# ── T005: ha_preview_blueprint_substitution ─────────────────────────────────────


class TestSustituir(_Base):
    async def test_un_solo_comando_y_sin_guardar(self) -> None:
        self.respuestas["blueprint/substitute"] = {"substituted_config": {
            "triggers": [{"trigger": "state", "entity_id": "binary_sensor.puerta"}],
            "variables": {"password": _CENTINELA}}}
        r = await self.t["ha_preview_blueprint_substitution"](
            domain="automation", path="homeassistant/motion_light",
            inputs={"motion_entity": "binary_sensor.puerta"})
        self.assertEqual(self.enviados, [{
            "type": "blueprint/substitute", "domain": "automation",
            "path": "homeassistant/motion_light.yaml",
            "input": {"motion_entity": "binary_sensor.puerta"}}])
        self.assertEqual(r["saved"], False)
        self.assertEqual(r["path"], "homeassistant/motion_light.yaml")
        self.assertEqual(r["substituted_config"]["triggers"][0]["entity_id"],
                         "binary_sensor.puerta")
        self.assertNotIn(_CENTINELA, json.dumps(r))

    async def test_error_de_ha_redactado(self) -> None:
        self.respuestas["blueprint/substitute"] = HAConnectionError(
            f"HA WS command failed: Missing input motion_entity password={_CENTINELA}",
            code="unknown_error")
        r = await self.t["ha_preview_blueprint_substitution"](
            domain="automation", path="homeassistant/motion_light.yaml", inputs={})
        self.assertEqual((r["error"], r["ha_code"]), ("substitution_failed", "unknown_error"))
        self.assertIn("Missing input", r["detail"])
        self.assertNotIn(_CENTINELA, json.dumps(r))

    async def test_argumentos_invalidos_sin_ha(self) -> None:
        for kw in ({"domain": "automation", "path": "../x", "inputs": {}},
                   {"domain": "light", "path": "x", "inputs": {}},
                   {"domain": "automation", "path": "x", "inputs": ["a"]}):
            with self.subTest(kw=kw):
                r = await self.t["ha_preview_blueprint_substitution"](**kw)
                self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()

    async def test_respuesta_rara(self) -> None:
        self.respuestas["blueprint/substitute"] = {"otra": 1}
        r = await self.t["ha_preview_blueprint_substitution"](
            domain="automation", path="x", inputs={})
        self.assertEqual(r["error"], "unexpected_response")

    async def test_no_cabe(self) -> None:
        self.respuestas["blueprint/substitute"] = {
            "substituted_config": {"actions": ["x" * 100] * 300}}
        mcp = DummyMCP()
        mod.register(mcp, self.ha, response_max_bytes=10_000)
        r = await mcp.tools["ha_preview_blueprint_substitution"](
            domain="automation", path="x", inputs={})
        self.assertEqual(r["error"], "response_too_large")
        self.assertGreater(r["bytes"], 10_000)


# ── T006: ha_save_blueprint ───────────────────────────────────────────────────


class TestGuardar(_Base):
    tool = "ha_save_blueprint"

    async def test_validacion_sin_ha(self) -> None:
        casos = [
            ({"domain": "light", "path": "x", "yaml": _YAML}, "domain"),
            ({"domain": "automation", "path": "../x", "yaml": _YAML}, "path"),
            ({"domain": "automation", "path": "x", "yaml": "blueprint: ["}, "yaml"),
            ({"domain": "automation", "path": "x", "yaml": "a: 1\n"}, "yaml"),
            ({"domain": "script", "path": "x", "yaml": _YAML}, "yaml"),
            ({"domain": "automation", "path": "x"}, "yaml"),
        ]
        for kw, campo in casos:
            with self.subTest(kw=kw):
                r = await self.t[self.tool](**kw)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", campo))
        self.ha.ws_send.assert_not_awaited()
        self.assertEqual(self.ficheros_de_tokens(), [])

    async def test_vista_previa_sin_escribir(self) -> None:
        with capture_logs() as logs:
            r = await self.t[self.tool](domain="automation", path="hermes/nuevo",
                                        yaml=_YAML_CON_SECRETO)
        self.assertEqual(self.tipos(), ["blueprint/list"])
        self.assertNotIn("blueprint/save", self.tipos())
        p = r["preview"]
        self.assertEqual((p["action"], p["domain"], p["path"], p["full_path"], p["exists"],
                          p["used_by"]),
                         ("save_blueprint", "automation", "hermes/nuevo.yaml",
                          "/config/blueprints/automation/hermes/nuevo.yaml", False, None))
        self.assertEqual(p["metadata"]["name"], "Luz por movimiento")
        self.assertEqual([e["name"] for e in p["inputs"]], ["sensor", "espera"])
        self.assertEqual(p["content_bytes"], len(_YAML_CON_SECRETO.encode()))
        self.assertEqual(p["content_sha256"],
                         hashlib.sha256(_YAML_CON_SECRETO.encode()).hexdigest())
        self.assertEqual(r["omit_on_confirm"], ["yaml"])
        self.assertIsInstance(r["confirmation_token"], str)
        # No repite el YAML ni sus secretos; el log solo lleva lo permitido.
        self.assertNotIn("triggers", json.dumps(r))
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertNotIn(_JWT, json.dumps(r))
        self.assertNotIn(_CENTINELA, str(logs))
        self.assertNotIn("Luz por movimiento", str(logs))
        evento = next(e for e in logs if e["event"] == "ha_save_blueprint_preview")
        self.assertEqual(evento["sha256"], p["content_sha256"])

    async def test_existe_sin_allow_override(self) -> None:
        r = await self.t[self.tool](domain="automation", path="hermes/luz.yaml", yaml=_YAML)
        self.assertEqual(r["error"], "already_exists")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.ficheros_de_tokens(), [])
        self.assertNotIn("search/related", self.tipos())

    async def test_etiquetas_que_ha_resolveria_sin_token(self) -> None:
        # T055: el escenario de la revisión, con las cuatro familias.
        for etiqueta, valor in (("!env_var", "SUPERVISOR_TOKEN"),
                                ("!include", "/config/.storage/auth"),
                                ("!include_dir_list", "carpeta"),
                                ("!secret", "clave")):
            texto = _YAML.replace("default: 120", f"default: {etiqueta} {valor}")
            with self.subTest(etiqueta=etiqueta):
                r = await self.t[self.tool](domain="automation", path="hermes/nuevo",
                                            yaml=texto)
                self.assertEqual((r["error"], r["field"], r["tag"]),
                                 ("unsupported_yaml_tag", "yaml", etiqueta))
                self.assertNotIn(valor, json.dumps(r))
                self.assertNotIn("confirmation_token", r)
        self.ha.ws_send.assert_not_awaited()
        self.assertEqual(self.ficheros_de_tokens(), [])

    async def test_etiqueta_en_un_token_previo_al_arreglo(self) -> None:
        # Un token que ya guardaba un YAML con etiqueta (creado antes del
        # arreglo) no lo manda a HA al confirmar.
        texto = _YAML + "x: !env_var SUPERVISOR_TOKEN\n"
        v = await security.create_confirmation_token(
            self.tool, {"domain": "automation", "path": "hermes/nuevo.yaml",
                        "allow_override": False, "yaml": texto},
            preview={}, omitibles=mod._OMITIBLES_GUARDAR)
        r = await self.t[self.tool](domain="automation", path="hermes/nuevo",
                                    confirmation_token=v["confirmation_token"])
        self.assertEqual(r["error"], "unsupported_yaml_tag")
        self.assertNotIn("blueprint/save", self.tipos())

    async def test_existe_con_allow_override(self) -> None:
        self.respuestas["search/related"] = {"automation": ["automation.b", "automation.a"]}
        r = await self.t[self.tool](domain="automation", path="hermes/luz.yaml", yaml=_YAML,
                                    allow_override=True)
        p = r["preview"]
        self.assertTrue(p["exists"])
        self.assertEqual(p["used_by"], {"automation": ["automation.a", "automation.b"]})
        self.assertEqual(p["used_by_count"], 2)
        self.assertIn("reloads", p["on_save"])
        self.assertIn({"type": "search/related", "item_type": "automation_blueprint",
                       "item_id": "hermes/luz.yaml"}, self.enviados)

    async def _vista(self, **kw: Any) -> dict[str, Any]:
        args = {"domain": "automation", "path": "hermes/nuevo", "yaml": _YAML, **kw}
        return await self.t[self.tool](**args)

    async def test_confirmacion_con_yaml(self) -> None:
        v = await self._vista()
        self.enviados.clear()
        r = await self.t[self.tool](domain="automation", path="hermes/nuevo", yaml=_YAML,
                                    confirmation_token=v["confirmation_token"])
        self.assertEqual(r["result"], "ok")
        self.assertEqual(self.enviados, [{
            "type": "blueprint/save", "domain": "automation", "path": "hermes/nuevo.yaml",
            "yaml": _YAML, "allow_override": False}])

    async def test_confirmacion_omitiendo_yaml(self) -> None:
        v = await self._vista()
        self.enviados.clear()
        r = await self.t[self.tool](domain="automation", path="hermes/nuevo",
                                    confirmation_token=v["confirmation_token"])
        self.assertEqual(r["result"], "ok")
        self.assertEqual([p["yaml"] for p in self.enviados], [_YAML])

    async def test_yaml_distinto_rechazado(self) -> None:
        v = await self._vista()
        self.enviados.clear()
        r = await self.t[self.tool](domain="automation", path="hermes/nuevo",
                                    yaml=_YAML.replace("Banco", "Otro"),
                                    confirmation_token=v["confirmation_token"])
        self.assertIn("does not match", r["error"])
        self.assertNotIn("blueprint/save", self.tipos())

    async def test_token_de_otros_argumentos(self) -> None:
        self.respuestas["blueprint/list"] = lambda p: {}
        for otros in ({"path": "hermes/otro"}, {"allow_override": True}):
            with self.subTest(otros=otros):
                v = await self._vista()
                self.enviados.clear()
                args = {"domain": "automation", "path": "hermes/nuevo", **otros}
                r = await self.t[self.tool](**args, confirmation_token=v["confirmation_token"])
                self.assertIn("does not match", r["error"])
                self.assertNotIn("blueprint/save", self.tipos())
        # Otro dominio: el YAML dice automation, así que se reenvía sin YAML.
        v = await self._vista()
        self.enviados.clear()
        r = await self.t[self.tool](domain="script", path="hermes/nuevo",
                                    confirmation_token=v["confirmation_token"])
        self.assertIn("does not match", r["error"])
        self.assertNotIn("blueprint/save", self.tipos())

    async def test_token_reutilizado(self) -> None:
        v = await self._vista()
        await self.t[self.tool](domain="automation", path="hermes/nuevo",
                                confirmation_token=v["confirmation_token"])
        self.enviados.clear()
        r = await self.t[self.tool](domain="automation", path="hermes/nuevo",
                                    confirmation_token=v["confirmation_token"])
        self.assertIn("already used", r["error"])
        self.assertEqual(self.enviados, [])

    async def test_ha_rechaza_al_guardar(self) -> None:
        v = await self._vista()
        self.respuestas["blueprint/save"] = HAConnectionError(
            f"HA WS command failed: Invalid blueprint password={_CENTINELA}",
            code="invalid_format")
        r = await self.t[self.tool](domain="automation", path="hermes/nuevo",
                                    confirmation_token=v["confirmation_token"])
        self.assertEqual((r["error"], r["ha_code"]), ("save_failed", "invalid_format"))
        self.assertNotIn(_CENTINELA, json.dumps(r))
        estado = json.loads(self.ficheros_de_tokens()[0].read_text(encoding="utf-8"))
        self.assertEqual(estado["state"], "failed")
        self.assertNotIn("stored_args", estado)

    async def test_carrera_ya_existe_al_guardar(self) -> None:
        v = await self._vista()
        self.respuestas["blueprint/save"] = HAConnectionError(
            "HA WS command failed: File already exists", code="already_exists")
        r = await self.t[self.tool](domain="automation", path="hermes/nuevo",
                                    confirmation_token=v["confirmation_token"])
        self.assertEqual(r["error"], "already_exists")

    async def test_lectura_previa_fallida(self) -> None:
        self.respuestas["blueprint/list"] = HAConnectionError("caída")
        r = await self._vista()
        self.assertEqual(r["error"], "preview_unavailable")
        self.assertEqual(self.ficheros_de_tokens(), [])
        # Y si falla saber quién lo usa al sobrescribir, tampoco hay token.
        self.respuestas["blueprint/list"] = lambda p: {"hermes/nuevo.yaml": _meta("x")}
        self.respuestas["search/related"] = HAConnectionError("caída")
        r = await self._vista(allow_override=True)
        self.assertEqual(r["error"], "preview_unavailable")
        self.assertEqual(self.ficheros_de_tokens(), [])

    async def test_el_token_guarda_el_yaml_y_lo_borra_al_completar(self) -> None:
        # Excepción de FR-015: el omitible se guarda como el `config` de las
        # automatizaciones (spec 007) y se borra al completar el token.
        v = await self._vista(yaml=_YAML_CON_SECRETO)
        self.assertIn(_CENTINELA, self.texto_de_tokens())
        await self.t[self.tool](domain="automation", path="hermes/nuevo",
                                confirmation_token=v["confirmation_token"])
        self.assertNotIn(_CENTINELA, self.texto_de_tokens())


# ── T007: ha_delete_blueprint ─────────────────────────────────────────────────


class TestBorrar(_Base):
    tool = "ha_delete_blueprint"

    async def test_no_existe(self) -> None:
        r = await self.t[self.tool](domain="automation", path="hermes/nada")
        self.assertEqual(r["error"], "not_found")
        self.assertEqual(self.tipos(), ["blueprint/list"])
        self.assertEqual(self.ficheros_de_tokens(), [])

    async def test_en_uso_sin_token(self) -> None:
        self.respuestas["search/related"] = {"automation": ["automation.b", "automation.a"]}
        r = await self.t[self.tool](domain="automation", path="hermes/luz")
        self.assertEqual(r["error"], "blueprint_in_use")
        self.assertEqual(r["used_by"], {"automation": ["automation.a", "automation.b"]})
        self.assertEqual(r["used_by_count"], 2)
        self.assertNotIn("confirmation_token", r)
        self.assertIn({"type": "search/related", "item_type": "automation_blueprint",
                       "item_id": "hermes/luz.yaml"}, self.enviados)
        self.assertNotIn("blueprint/delete", self.tipos())
        self.assertEqual(self.ficheros_de_tokens(), [])

    async def test_script_por_script_blueprint(self) -> None:
        self.respuestas["search/related"] = {"script": ["script.aviso"]}
        r = await self.t[self.tool](domain="script", path="hermes/aviso.yaml")
        self.assertEqual(r["error"], "blueprint_in_use")
        self.assertIn({"type": "search/related", "item_type": "script_blueprint",
                       "item_id": "hermes/aviso.yaml"}, self.enviados)

    async def test_sin_uso_vista_previa(self) -> None:
        r = await self.t[self.tool](domain="automation", path="hermes/luz")
        p = r["preview"]
        self.assertEqual((p["action"], p["path"], p["full_path"], p["used_by"]),
                         ("delete_blueprint", "hermes/luz.yaml",
                          "/config/blueprints/automation/hermes/luz.yaml",
                          {"automation": []}))
        self.assertEqual(p["metadata"], {"name": "Luz", "source_url": None})
        self.assertIn("backup", p["effect"])
        self.assertIsInstance(r["confirmation_token"], str)
        self.assertNotIn("blueprint/delete", self.tipos())

    async def test_template_sin_search(self) -> None:
        r = await self.t[self.tool](domain="template", path="hermes/plantilla")
        self.assertNotIn("search/related", self.tipos())
        self.assertIsNone(r["preview"]["used_by"])
        self.assertIn("does not expose", r["preview"]["used_by_note"])
        self.assertIsInstance(r["confirmation_token"], str)

    async def test_search_falla(self) -> None:
        self.respuestas["search/related"] = HAConnectionError(f"x password={_CENTINELA}")
        r = await self.t[self.tool](domain="automation", path="hermes/luz")
        self.assertEqual(r["error"], "preview_unavailable")
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertEqual(self.ficheros_de_tokens(), [])
        # Una respuesta con forma rara tampoco se toma como «sin uso».
        self.respuestas["search/related"] = {"automation": "automation.a"}
        r = await self.t[self.tool](domain="automation", path="hermes/luz")
        self.assertEqual(r["error"], "preview_unavailable")

    async def test_confirmacion(self) -> None:
        v = await self.t[self.tool](domain="automation", path="hermes/luz")
        self.enviados.clear()
        r = await self.t[self.tool](domain="automation", path="hermes/luz",
                                    confirmation_token=v["confirmation_token"])
        self.assertEqual(r, {"result": "ok", "domain": "automation", "path": "hermes/luz.yaml"})
        self.assertEqual(self.enviados, [{"type": "blueprint/delete", "domain": "automation",
                                          "path": "hermes/luz.yaml"}])

    async def test_en_uso_al_confirmar(self) -> None:
        v = await self.t[self.tool](domain="automation", path="hermes/luz")
        self.respuestas["blueprint/delete"] = HAConnectionError(
            "HA WS command failed: Failed to remove blueprint hermes/luz.yaml: Blueprint in use",
            code="home_assistant_error")
        r = await self.t[self.tool](domain="automation", path="hermes/luz",
                                    confirmation_token=v["confirmation_token"])
        self.assertEqual(r["error"], "blueprint_in_use")
        estado = json.loads(self.ficheros_de_tokens()[0].read_text(encoding="utf-8"))
        self.assertEqual(estado["state"], "failed")

    async def test_otro_error_al_confirmar(self) -> None:
        v = await self.t[self.tool](domain="automation", path="hermes/luz")
        self.respuestas["blueprint/delete"] = HAConnectionError(
            f"HA WS command failed: No such file password={_CENTINELA}", code="unknown_error")
        r = await self.t[self.tool](domain="automation", path="hermes/luz",
                                    confirmation_token=v["confirmation_token"])
        self.assertEqual((r["error"], r["ha_code"]), ("delete_failed", "unknown_error"))
        self.assertNotIn(_CENTINELA, json.dumps(r))

    async def test_token_de_otra_ruta_o_dominio(self) -> None:
        v = await self.t[self.tool](domain="automation", path="hermes/luz")
        self.enviados.clear()
        for kw in ({"domain": "automation", "path": "homeassistant/motion_light"},
                   {"domain": "script", "path": "hermes/luz"}):
            with self.subTest(kw=kw):
                r = await self.t[self.tool](**kw, confirmation_token=v["confirmation_token"])
                self.assertIn("does not match", r["error"])
        self.assertNotIn("blueprint/delete", self.tipos())

    async def test_mas_de_50_consumidores(self) -> None:
        self.respuestas["search/related"] = {
            "automation": [f"automation.a{i:03d}" for i in range(70)]}
        r = await self.t[self.tool](domain="automation", path="hermes/luz")
        self.assertEqual(len(r["used_by"]["automation"]), 50)
        self.assertEqual(r["used_by_count"], 70)

    async def test_vista_previa_y_tokens_sin_centinela(self) -> None:
        self.respuestas["blueprint/list"] = lambda p: {
            "hermes/luz.yaml": _meta(f"password={_CENTINELA}",
                                     source_url=f"https://u:{_CENTINELA}@example.com/b.yaml"),
        }
        with capture_logs() as logs:
            v = await self.t[self.tool](domain="automation", path="hermes/luz")
        self.assertNotIn(_CENTINELA, json.dumps(v))
        self.assertNotIn(_CENTINELA, self.texto_de_tokens())
        self.assertNotIn(_CENTINELA, str(logs))


# ── T017–T018: ha_import_blueprint (tramo B) ──────────────────────────────────

_URL = "https://example.com/blueprints/luz.yaml"


def _importado(raw: str = _YAML, sugerido: str = "example.com/luz", **extra: Any) -> dict[str, Any]:
    """Respuesta de `blueprint/import` como la da HA 2026.11.1
    (`components/blueprint/websocket_api.py`, `ws_import_blueprint`)."""
    respuesta = {
        "suggested_filename": sugerido,
        "raw_data": raw,
        "blueprint": {"metadata": {
            "name": "Luz por movimiento", "domain": "automation",
            "description": "Enciende light.salon", "author": "Banco",
            "source_url": _URL, "homeassistant": {"min_version": "2024.6.0"},
            "input": {"sensor": {"name": "Sensor", "selector": {"entity": {}}},
                      "ajustes": {"name": "Ajustes",
                                  "input": {"espera": {"name": "Espera", "default": 120}}}},
        }},
        "validation_errors": None,
        "exists": False,
    }
    respuesta.update(extra)
    return respuesta


class TestImportar(_Base):
    """T017 (vista previa) y T018 (confirmación) de `ha_import_blueprint`.

    Controles negativos del cierre del tramo B (T025), cada uno visto en rojo
    y restaurado:
    (1) confirmar sin comparar la huella (guarda lo nuevo) → cae
    `test_contenido_distinto_al_confirmar`;
    (2) guardar el `content` tapado en vez del original → cae
    `test_confirmacion_guarda_el_original`;
    (3) recortar el YAML en vez de `blueprint_too_large` → cae
    `test_no_cabe_sin_token`;
    (4) sin `_third_party_text` → cae `test_vista_previa_completa`;
    (6) dar token con `validation_errors` → cae
    `test_errores_de_validacion_sin_token`.
    El (5), `ha_import_blueprint` fuera de `_OPEN_WORLD`, está en
    tests/test_tools_registration.py.
    """

    tool = "ha_import_blueprint"

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.descargas: list[Any] = [_importado()]
        self.respuestas["blueprint/import"] = self._descarga

    def _descarga(self, payload: dict[str, Any]) -> Any:
        # La última se repite: cada llamada a HA «descarga» otra vez.
        siguiente = self.descargas.pop(0) if len(self.descargas) > 1 else self.descargas[0]
        if isinstance(siguiente, BaseException):
            raise siguiente
        return siguiente

    # ── T017(a): argumentos ──

    async def test_argumentos_invalidos_sin_ha(self) -> None:
        casos = [
            ({"url": ""}, "url"),
            ({"url": "   "}, "url"),
            ({"url": "ftp://example.com/luz.yaml"}, "url"),
            ({"url": "file:///config/secrets.yaml"}, "url"),
            ({"url": "example.com/luz.yaml"}, "url"),
            ({"url": "https://"}, "url"),
            ({"url": "https://example.com/a b.yaml"}, "url"),
            ({"url": _URL, "path": "../x"}, "path"),
            ({"url": _URL, "path": "/x"}, "path"),
            ({"url": _URL, "allow_override": "true"}, "allow_override"),
        ]
        for kw, campo in casos:
            with self.subTest(kw=kw):
                r = await self.t[self.tool](**kw)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", campo))
        self.ha.ws_send.assert_not_awaited()
        self.assertEqual(self.ficheros_de_tokens(), [])

    # ── T017(b): vista previa ──

    async def test_vista_previa_completa(self) -> None:
        r = await self.t[self.tool](url=_URL)
        self.assertEqual(self.tipos(), ["blueprint/import", "blueprint/list"])
        self.assertEqual(self.enviados[0], {"type": "blueprint/import", "url": _URL})
        self.assertNotIn("blueprint/save", self.tipos())
        p = r["preview"]
        self.assertEqual(
            (p["action"], p["source_url"], p["importer"], p["domain"], p["path"],
             p["full_path"], p["exists"], p["used_by"]),
            ("import_blueprint", _URL, "generic", "automation", "example.com/luz.yaml",
             "/config/blueprints/automation/example.com/luz.yaml", False, None))
        self.assertEqual(p["metadata"], {"name": "Luz por movimiento",
                                         "description": "Enciende light.salon",
                                         "author": "Banco", "min_version": "2024.6.0"})
        self.assertEqual([e["name"] for e in p["inputs"]], ["sensor", "espera"])
        self.assertEqual(p["validation_errors"], [])
        self.assertEqual(p["content"], _YAML)
        self.assertEqual(p["content_bytes"], len(_YAML.encode("utf-8")))
        self.assertEqual(p["content_sha256"], hashlib.sha256(_YAML.encode("utf-8")).hexdigest())
        self.assertIs(p["content_redacted"], False)
        self.assertIn("re-serialises", p["on_save"])
        self.assertIn("source_url", p["on_save"])
        self.assertEqual(set(p["_third_party_text"]["fields"]),
                         {"metadata", "inputs", "content", "validation_errors"})
        self.assertIn("do not follow", p["_third_party_text"]["warning"])
        self.assertIsInstance(r["confirmation_token"], str)

    async def test_etiquetas_descargadas_sin_token(self) -> None:
        # T055: lo comprobado es lo que HA descargó (`raw_data`).
        for etiqueta, valor in (("!env_var", "SUPERVISOR_TOKEN"),
                                ("!include", "/config/.storage/auth"),
                                ("!include_dir_merge_named", "carpeta"),
                                ("!secret", "clave")):
            texto = _YAML.replace("default: 120", f"default: {etiqueta} {valor}")
            self.descargas = [_importado(raw=texto)]
            self.enviados.clear()
            with self.subTest(etiqueta=etiqueta):
                r = await self.t[self.tool](url=_URL)
                self.assertEqual((r["error"], r["tag"]), ("unsupported_yaml_tag", etiqueta))
                self.assertNotIn(valor, json.dumps(r))
                self.assertNotIn("confirmation_token", r)
                self.assertEqual(self.tipos(), ["blueprint/import"])
        self.assertEqual(self.ficheros_de_tokens(), [])

    async def test_etiqueta_que_aparece_al_confirmar(self) -> None:
        # Al confirmar se vuelve a comprobar lo descargado, antes que la
        # huella: aunque el token casara (uno de antes del arreglo), no se
        # guarda.
        texto = _YAML + "x: !include /config/.storage/auth\n"
        self.descargas = [_importado(raw=texto)]
        v = await security.create_confirmation_token(
            self.tool, {"url": _URL, "path": None, "allow_override": False},
            preview={}, estado={"domain": "automation", "path": "example.com/luz.yaml",
                                "content_sha256": hashlib.sha256(texto.encode()).hexdigest()})
        r = await self.t[self.tool](url=_URL, confirmation_token=v["confirmation_token"])
        self.assertEqual((r["error"], r["tag"]), ("unsupported_yaml_tag", "!include"))
        self.assertNotIn("blueprint/save", self.tipos())

    async def test_yaml_descargado_ilegible_sin_token(self) -> None:
        self.descargas = [_importado(raw="blueprint: [")]
        r = await self.t[self.tool](url=_URL)
        self.assertEqual(r["error"], "invalid_blueprint")
        self.assertNotIn("confirmation_token", r)

    async def test_path_dado(self) -> None:
        r = await self.t[self.tool](url=_URL, path="hermes/importado")
        p = r["preview"]
        self.assertEqual((p["path"], p["full_path"]),
                         ("hermes/importado.yaml",
                          "/config/blueprints/automation/hermes/importado.yaml"))

    def test_importador_por_patron(self) -> None:
        casos = {
            "https://community.home-assistant.io/t/luz-por-movimiento/123456": "community",
            "https://community.home-assistant.io/t/luz-por-movimiento/123456/2": "community",
            "https://github.com/usuario/repo/blob/main/luz.yaml": "github",
            "https://raw.githubusercontent.com/usuario/repo/main/luz.yaml": "github",
            "https://gist.github.com/usuario/abc123": "gist",
            "https://www.home-assistant.io/blueprints/blog/motion_light.yaml":
                "homeassistant_website",
            _URL: "generic",
            "http://127.0.0.1:8123/local/hermes_banco/luz.yaml": "generic",
        }
        for url, esperado in casos.items():
            with self.subTest(url=url):
                self.assertEqual(mod._importador_de(url), esperado)

    async def test_sugerencia_de_ha_rara_pide_path(self) -> None:
        self.descargas = [_importado(sugerido="../fuera")]
        r = await self.t[self.tool](url=_URL)
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "path"))
        self.assertEqual(self.ficheros_de_tokens(), [])
        # Con `path`, la sugerencia no se usa.
        r = await self.t[self.tool](url=_URL, path="hermes/bien")
        self.assertIn("confirmation_token", r)

    # ── T017(c): inválido ──

    async def test_errores_de_validacion_sin_token(self) -> None:
        self.descargas = [_importado(validation_errors=[
            f"Missing input sensor password={_CENTINELA}"])]
        r = await self.t[self.tool](url=_URL)
        self.assertEqual(r["error"], "invalid_blueprint")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(len(r["validation_errors"]), 1)
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertEqual(self.ficheros_de_tokens(), [])

    async def test_dominio_no_admitido_sin_token(self) -> None:
        imp = _importado()
        imp["blueprint"]["metadata"]["domain"] = "light"
        self.descargas = [imp]
        r = await self.t[self.tool](url=_URL)
        self.assertEqual((r["error"], r["domain"]), ("invalid_blueprint", "light"))
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.ficheros_de_tokens(), [])

    # ── T017(d): ya existe ──

    async def test_existe_sin_allow_override(self) -> None:
        self.respuestas["blueprint/list"] = lambda p: {"example.com/luz.yaml": _meta("Luz")}
        r = await self.t[self.tool](url=_URL)
        self.assertEqual(r["error"], "already_exists")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.ficheros_de_tokens(), [])
        # HA también lo dice con `exists` para la ruta sugerida.
        self.respuestas["blueprint/list"] = lambda p: {}
        self.descargas = [_importado(exists=True)]
        r = await self.t[self.tool](url=_URL)
        self.assertEqual(r["error"], "already_exists")

    async def test_existe_con_allow_override(self) -> None:
        self.respuestas["blueprint/list"] = lambda p: {"example.com/luz.yaml": _meta("Luz")}
        self.respuestas["search/related"] = {"automation": ["automation.b", "automation.a"]}
        r = await self.t[self.tool](url=_URL, allow_override=True)
        p = r["preview"]
        self.assertTrue(p["exists"])
        self.assertEqual(p["used_by"], {"automation": ["automation.a", "automation.b"]})
        self.assertEqual(p["used_by_count"], 2)
        self.assertIn("reloads", p["on_save"])

    async def test_quien_lo_usa_falla(self) -> None:
        self.respuestas["blueprint/list"] = lambda p: {"example.com/luz.yaml": _meta("Luz")}
        self.respuestas["search/related"] = HAConnectionError("caída")
        r = await self.t[self.tool](url=_URL, allow_override=True)
        self.assertEqual(r["error"], "preview_unavailable")
        self.assertEqual(self.ficheros_de_tokens(), [])

    # ── T017(e): no cabe ──

    async def test_no_cabe_sin_token(self) -> None:
        relleno = "#" + "x" * 200 + "\n"
        grande = _YAML + relleno * (self.max_bytes // len(relleno) + 10)
        self.descargas = [_importado(raw=grande)]
        r = await self.t[self.tool](url=_URL)
        self.assertEqual(r["error"], "blueprint_too_large")
        self.assertEqual(r["content_bytes"], len(grande.encode("utf-8")))
        self.assertEqual(r["max_bytes"], self.max_bytes)
        self.assertNotIn("confirmation_token", r)
        self.assertNotIn("content", r)
        self.assertEqual(self.ficheros_de_tokens(), [])

    # ── T017(f): redacción ──

    async def test_contenido_con_secreto_tapado(self) -> None:
        self.descargas = [_importado(raw=_YAML_CON_SECRETO)]
        r = await self.t[self.tool](url=_URL)
        p = r["preview"]
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertNotIn(_JWT, json.dumps(r))
        self.assertIs(p["content_redacted"], True)
        self.assertIn("content_note", p)
        # La huella y el tamaño son los del original, que es lo que se guarda.
        self.assertEqual(p["content_sha256"],
                         hashlib.sha256(_YAML_CON_SECRETO.encode("utf-8")).hexdigest())
        self.assertNotIn(_CENTINELA, self.texto_de_tokens())

    # ── T017(g): errores de HA ──

    async def test_errores_de_ha(self) -> None:
        for codigo in ("not_supported", "timeout", "unknown_error", "invalid_format",
                       "home_assistant_error"):
            with self.subTest(codigo=codigo):
                self.descargas = [HAConnectionError(
                    f"HA WS command failed: 404 for https://u:{_CENTINELA}@example.com",
                    code=codigo)]
                r = await self.t[self.tool](url=_URL)
                self.assertEqual((r["error"], r["ha_code"]), ("import_failed", codigo))
                self.assertNotIn(_CENTINELA, json.dumps(r))
                self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.ficheros_de_tokens(), [])

    async def test_respuesta_rara(self) -> None:
        for raro in (None, [], {"raw_data": 1}, {"raw_data": "x"}):
            with self.subTest(raro=raro):
                self.descargas = [raro]
                r = await self.t[self.tool](url=_URL)
                self.assertEqual(r["error"], "import_failed")
                self.assertNotIn("confirmation_token", r)

    # ── T017(h): log ──

    async def test_log_sin_url_con_credenciales_ni_yaml(self) -> None:
        url = f"https://user:{_CENTINELA}@example.com/blueprints/luz.yaml"
        self.descargas = [_importado(raw=_YAML_CON_SECRETO)]
        with capture_logs() as logs:
            v = await self.t[self.tool](url=url)
            await self.t[self.tool](url=url, confirmation_token=v["confirmation_token"])
            self.descargas = [HAConnectionError("caída", code="timeout")]
            await self.t[self.tool](url=url)
        texto = str(logs)
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn("triggers", texto)
        self.assertNotIn("Luz por movimiento", texto)
        eventos = {e["event"] for e in logs}
        self.assertTrue({"ha_import_blueprint_preview", "ha_import_blueprint_ok",
                         "ha_import_blueprint_error"} <= eventos)

    # ── T018: confirmación ──

    async def _vista(self, **kw: Any) -> dict[str, Any]:
        return await self.t[self.tool](**{"url": _URL, **kw})

    async def test_confirmacion_guarda_el_original(self) -> None:
        self.descargas = [_importado(raw=_YAML_CON_SECRETO)]
        v = await self._vista()
        self.enviados.clear()
        r = await self.t[self.tool](url=_URL, confirmation_token=v["confirmation_token"])
        self.assertEqual(r["result"], "ok")
        self.assertEqual(self.tipos(), ["blueprint/import", "blueprint/save"])
        self.assertEqual(self.enviados[1], {
            "type": "blueprint/save", "domain": "automation",
            "path": "example.com/luz.yaml", "yaml": _YAML_CON_SECRETO,
            "source_url": _URL, "allow_override": False})
        self.assertEqual((r["domain"], r["path"], r["content_sha256"]),
                         ("automation", "example.com/luz.yaml",
                          hashlib.sha256(_YAML_CON_SECRETO.encode("utf-8")).hexdigest()))
        self.assertNotIn(_CENTINELA, json.dumps(r))

    async def test_confirmacion_con_path_y_allow_override(self) -> None:
        self.respuestas["blueprint/list"] = lambda p: {"hermes/x.yaml": _meta("x")}
        self.respuestas["search/related"] = {"automation": []}
        v = await self._vista(path="hermes/x", allow_override=True)
        self.enviados.clear()
        r = await self.t[self.tool](url=_URL, path="hermes/x", allow_override=True,
                                    confirmation_token=v["confirmation_token"])
        self.assertEqual(r["result"], "ok")
        guardar = self.enviados[-1]
        self.assertEqual((guardar["path"], guardar["allow_override"]), ("hermes/x.yaml", True))

    async def test_contenido_distinto_al_confirmar(self) -> None:
        self.descargas = [_importado(), _importado(raw=_YAML.replace("Banco", "Otro"))]
        v = await self._vista()
        self.enviados.clear()
        r = await self.t[self.tool](url=_URL, confirmation_token=v["confirmation_token"])
        self.assertEqual(r["error"], "content_changed")
        self.assertIn("new preview", r["hint"])
        self.assertNotIn("blueprint/save", self.tipos())

    async def test_sugerencia_distinta_al_confirmar(self) -> None:
        self.descargas = [_importado(), _importado(sugerido="example.com/otra")]
        v = await self._vista()
        self.enviados.clear()
        r = await self.t[self.tool](url=_URL, confirmation_token=v["confirmation_token"])
        self.assertEqual(r["error"], "content_changed")
        self.assertNotIn("blueprint/save", self.tipos())

    async def test_token_de_otros_argumentos(self) -> None:
        for otros in ({"url": "https://example.com/blueprints/otra.yaml"},
                      {"path": "hermes/otra"}, {"allow_override": True}):
            with self.subTest(otros=otros):
                v = await self._vista()
                self.enviados.clear()
                args = {"url": _URL, **otros}
                r = await self.t[self.tool](**args, confirmation_token=v["confirmation_token"])
                self.assertIn("does not match", r["error"])
                self.assertNotIn("blueprint/save", self.tipos())

    async def test_token_reutilizado(self) -> None:
        v = await self._vista()
        await self.t[self.tool](url=_URL, confirmation_token=v["confirmation_token"])
        self.enviados.clear()
        r = await self.t[self.tool](url=_URL, confirmation_token=v["confirmation_token"])
        self.assertIn("already used", r["error"])
        self.assertNotIn("blueprint/save", self.tipos())

    async def test_segunda_descarga_falla(self) -> None:
        self.descargas = [_importado(), HAConnectionError("caída", code="timeout")]
        v = await self._vista()
        self.enviados.clear()
        r = await self.t[self.tool](url=_URL, confirmation_token=v["confirmation_token"])
        self.assertEqual((r["error"], r["ha_code"]), ("import_failed", "timeout"))
        self.assertNotIn("blueprint/save", self.tipos())

    async def test_carrera_ya_existe_al_guardar(self) -> None:
        v = await self._vista()
        self.respuestas["blueprint/save"] = HAConnectionError(
            "HA WS command failed: File already exists", code="already_exists")
        r = await self.t[self.tool](url=_URL, confirmation_token=v["confirmation_token"])
        self.assertEqual(r["error"], "already_exists")
        estado = json.loads(self.ficheros_de_tokens()[0].read_text(encoding="utf-8"))
        self.assertEqual(estado["state"], "failed")

    async def test_ha_rechaza_al_guardar(self) -> None:
        v = await self._vista()
        self.respuestas["blueprint/save"] = HAConnectionError(
            f"HA WS command failed: Invalid password={_CENTINELA}", code="invalid_format")
        r = await self.t[self.tool](url=_URL, confirmation_token=v["confirmation_token"])
        self.assertEqual((r["error"], r["ha_code"]), ("save_failed", "invalid_format"))
        self.assertNotIn(_CENTINELA, json.dumps(r))

    async def test_el_token_no_guarda_el_yaml(self) -> None:
        self.descargas = [_importado(raw=_YAML_CON_SECRETO)]
        await self._vista()
        texto = self.texto_de_tokens()
        self.assertNotIn("triggers", texto)
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn("stored_args", texto)


class TestEsquemaDelYaml(unittest.TestCase):
    """`yaml` es `str` exactamente (como `content` de `fs_write_file`): el SDK
    MCP no lo convierte aunque parezca JSON. Control negativo comprobado: con
    `str | None` cae (`{"blueprint": 1}` llega como dict)."""

    def test_yaml_no_se_preparsea(self) -> None:
        from tests.test_tools_registration import _real_registry

        meta = _real_registry()["ha_save_blueprint"].fn_metadata
        base = {"domain": "automation", "path": "x"}
        for texto in ('{"blueprint": 1}', "[1]", "true", "null", "texto"):
            args = meta.validate_arguments({**base, "yaml": texto})
            self.assertEqual(args["yaml"], texto)
        self.assertIsNone(meta.validate_arguments(base)["yaml"])


if __name__ == "__main__":
    unittest.main()
