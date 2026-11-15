"""Banco de Core: blueprints (spec 017, tramo A, T013).

Las cuatro tools del tramo A contra HA Core real, con el lector independiente
preparando cada caso y comprobando cada efecto directamente en Core
(`blueprint/list` y `search/related` por su propia WebSocket):

- **Listar**: `ha_list_blueprints` ve los blueprints que HA copia al cargar
  `automation:` y `script:` (carpeta `homeassistant/`).
- **Sustituir**: `ha_preview_blueprint_substitution` de
  `homeassistant/motion_light.yaml`, con un valor genérico para cada entrada
  (los nombres los da la propia lista), devuelve una configuración con
  disparadores y no guarda nada.
- **Guardar**: un blueprint mínimo propio en `hermes_banco/…`: tras la vista
  previa el lector no lo ve; tras confirmar, sí, con su nombre. Otra vez sin
  `allow_override` → `already_exists`; con `allow_override` y otro nombre, el
  lector ve el nombre nuevo.
- **Borrar**: el lector crea por REST una automatización que usa ese
  blueprint → `blueprint_in_use` con ella y sin token, y el fichero sigue; el
  lector borra la automatización → vista previa (el fichero sigue) →
  confirmación → el lector ya no lo ve.
- **Importar** (tramo B, T023): el banco no tiene salida a internet, así que
  HA sirve un blueprint propio desde su carpeta `www`
  (`ha_config/www/hermes_banco/luz_por_movimiento.yaml`, en `/local/`) y se
  importa desde `http://127.0.0.1:8123/local/…`: dentro del contenedor,
  127.0.0.1 es la propia HA, que la regla de `iptables` del workflow no toca
  (solo corta lo que sale de la subred). Es una descarga HTTP real por el
  importador genérico de HA. Vista previa con el YAML y su huella (la misma
  que la del fichero que lee el lector) → el lector no lo ve → confirmación
  → el lector lo ve con `source_url` → se borra con `ha_delete_blueprint`.
  Los importadores de GitHub, gist y foro necesitan internet: prueba manual
  pendiente en docs/HOJA-DE-RUTA.md.

Todo lo creado se borra al cerrar la sesión, pase lo que pase. Solo corre en
el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo

pytestmark = pytest.mark.banco


def _blueprint(nombre: str) -> str:
    """Blueprint de automatización mínimo, propio y genérico."""
    return (
        "blueprint:\n"
        f"  name: {nombre}\n"
        "  description: Blueprint de prueba del banco de Hermes\n"
        "  domain: automation\n"
        "  input:\n"
        "    entidad:\n"
        "      name: Entidad\n"
        "triggers:\n"
        "  - trigger: state\n"
        "    entity_id: !input entidad\n"
        "    to: \"on\"\n"
        "actions: []\n"
    )


async def _rechazo(s: SesionEscrituras, tool: str, **args: Any) -> dict[str, Any]:
    """Llama a una tool que DEBE rechazar y devuelve su `{"error": …}`.

    No sirve `accion`: Hermes marca con `isError` toda respuesta
    `{"error": …}` y aquí el rechazo es lo esperado (mismo patrón que
    `_rechazo` de test_banco_genericas.py).
    """
    resultado = await s.cliente.call_tool(tool, args)
    assert getattr(resultado, "is_error", False), f"{tool}: se esperaba un rechazo"
    return json.loads(resultado.content[0].text)


async def _blueprints(s: SesionEscrituras, dominio: str = "automation") -> dict[str, Any]:
    """`blueprint/list` directo a Core: lo que hay de verdad en el disco de HA."""
    return await s.lector.comando({"type": "blueprint/list", "domain": dominio})


class TestListarYSustituir(BancoEscrituras):
    async def test_lista_los_de_ha(self) -> None:
        async with self.sesion() as s:
            r = await s.accion("ha_list_blueprints")
            claves = {(i["domain"], i["path"]) for i in r["items"]}
            self.assertIn(("automation", "homeassistant/motion_light.yaml"), claves)
            self.assertIn(("script", "homeassistant/confirmable_notification.yaml"), claves)
            # Lo mismo que ve el lector, ni más ni menos, en automation.
            solo = await s.accion("ha_list_blueprints", domain="automation")
            self.assertEqual({i["path"] for i in solo["items"]},
                             set(await _blueprints(s)))

    async def test_sustitucion_de_motion_light(self) -> None:
        async with self.sesion() as s:
            lista = await s.accion("ha_list_blueprints", domain="automation")
            motion = next(i for i in lista["items"]
                          if i["path"] == "homeassistant/motion_light.yaml")
            self.assertTrue(motion["inputs"])
            entradas = {n: "binary_sensor.banco_017" for n in motion["inputs"]}
            antes = await _blueprints(s)
            r = await s.accion("ha_preview_blueprint_substitution", domain="automation",
                               path="homeassistant/motion_light", inputs=entradas)
            self.assertIs(r["saved"], False)
            cfg = r["substituted_config"]
            self.assertTrue(cfg.get("triggers") or cfg.get("trigger"), cfg)
            self.assertNotIn("use_blueprint", cfg)
            # No ha guardado nada.
            self.assertEqual(set(await _blueprints(s)), set(antes))


class TestGuardarYBorrar(BancoEscrituras):
    async def test_ciclo_completo(self) -> None:
        marca = sufijo()
        ruta = f"hermes_banco/guardado_{marca}.yaml"
        nombre = f"Banco 017 {marca}"
        id_automatizacion = f"banco_017_{marca}"

        async with self.sesion() as s:

            async def borrar_blueprint() -> None:
                if ruta in await _blueprints(s):
                    await s.lector.comando({"type": "blueprint/delete",
                                            "domain": "automation", "path": ruta})

            s.limpiezas.append(borrar_blueprint)

            # ── Guardar ──────────────────────────────────────────────────
            tool = "ha_save_blueprint"
            vista = await s.vista(tool, domain="automation", path=ruta,
                                  yaml=_blueprint(nombre))
            p = vista["preview"]
            self.assertEqual((p["path"], p["exists"], p["metadata"]["name"]),
                             (ruta, False, nombre))
            self.assertNotIn(ruta, await _blueprints(s))
            r = await s.confirmar(tool, vista, domain="automation", path=ruta)
            self.assertEqual(r["result"], "ok")
            guardados = await s.lector.esperar(
                lambda: _blueprints(s), lambda b: ruta in b,
                descripcion=f"blueprint {ruta} guardado")
            self.assertEqual(guardados[ruta]["metadata"]["name"], nombre)

            # Otra vez sin `allow_override`: rechazado sin token.
            r = await _rechazo(s, tool, domain="automation", path=ruta,
                               yaml=_blueprint(nombre))
            self.assertEqual(r["error"], "already_exists")
            self.assertNotIn("confirmation_token", r)

            # Con `allow_override` y otro nombre: el lector ve el nuevo.
            nuevo = f"{nombre} v2"
            vista = await s.vista(tool, domain="automation", path=ruta,
                                  yaml=_blueprint(nuevo), allow_override=True)
            self.assertIs(vista["preview"]["exists"], True)
            self.assertEqual(vista["preview"]["used_by"], {"automation": []})
            self.assertEqual((await _blueprints(s))[ruta]["metadata"]["name"], nombre)
            r = await s.confirmar(tool, vista, domain="automation", path=ruta,
                                  allow_override=True)
            self.assertIs(r["overrides_existing"], True)
            await s.lector.esperar(
                lambda: _blueprints(s),
                lambda b: b.get(ruta, {}).get("metadata", {}).get("name") == nuevo,
                descripcion=f"blueprint {ruta} sustituido")

            # ── Borrar en uso: sin token, y el fichero sigue ───────────────
            entidad = await s.input_boolean(f"banco_017_{marca}")
            s.limpiar_config("automation", id_automatizacion)
            estado, _ = await s.lector.rest(
                "POST", f"/api/config/automation/config/{id_automatizacion}",
                {"alias": f"Banco 017 {marca}",
                 "use_blueprint": {"path": ruta, "input": {"entidad": entidad}}})
            self.assertEqual(estado, 200)

            async def usuarios() -> list[str]:
                r = await s.lector.comando({"type": "search/related",
                                            "item_type": "automation_blueprint",
                                            "item_id": ruta})
                return r.get("automation", [])

            consumidores = await s.lector.esperar(
                usuarios, lambda u: len(u) == 1,
                descripcion=f"automatización que usa {ruta}")
            tool = "ha_delete_blueprint"
            r = await _rechazo(s, tool, domain="automation", path=ruta)
            self.assertEqual((r["error"], r["used_by"], r["used_by_count"]),
                             ("blueprint_in_use", {"automation": consumidores}, 1))
            self.assertNotIn("confirmation_token", r)
            self.assertIn(ruta, await _blueprints(s))

            # ── Borrar sin uso ─────────────────────────────────────────────
            estado, _ = await s.lector.rest(
                "DELETE", f"/api/config/automation/config/{id_automatizacion}")
            self.assertEqual(estado, 200)
            await s.lector.esperar(usuarios, lambda u: u == [],
                                   descripcion=f"nadie usa {ruta}")
            vista = await s.vista(tool, domain="automation", path=ruta)
            self.assertEqual(vista["preview"]["metadata"]["name"], nuevo)
            # La vista previa no ha borrado nada.
            self.assertIn(ruta, await _blueprints(s))
            r = await s.confirmar(tool, vista, domain="automation", path=ruta)
            self.assertEqual(r["result"], "ok")
            await s.lector.esperar(lambda: _blueprints(s), lambda b: ruta not in b,
                                   descripcion=f"blueprint {ruta} borrado")


# La URL la abre HA DENTRO de su contenedor: 127.0.0.1 es la propia HA.
_URL_LOCAL = "http://127.0.0.1:8123/local/hermes_banco/luz_por_movimiento.yaml"
_RUTA_IMPORTADA = "127.0.0.1/luz_por_movimiento.yaml"


class TestImportar(BancoEscrituras):
    async def test_importar_desde_local(self) -> None:
        async with self.sesion() as s:

            async def borrar_importado() -> None:
                if _RUTA_IMPORTADA in await _blueprints(s):
                    await s.lector.comando({"type": "blueprint/delete",
                                            "domain": "automation",
                                            "path": _RUTA_IMPORTADA})

            s.limpiezas.append(borrar_importado)

            # (1) HA sirve el fichero: si no, el fallo lo dice aquí y no como
            # un `import_failed` sin contexto.
            estado, fichero = await s.lector.rest(
                "GET", "/local/hermes_banco/luz_por_movimiento.yaml")
            self.assertEqual(estado, 200, "HA no sirve /config/www en /local/ "
                                          "(¿falta frontend: o la carpeta www?)")
            self.assertIsInstance(fichero, str)
            self.assertIn("blueprint:", fichero)
            self.assertNotIn(_RUTA_IMPORTADA, await _blueprints(s))

            # (2) Vista previa: lo que HA descargó, entero y con su huella.
            tool = "ha_import_blueprint"
            vista = await s.vista(tool, url=_URL_LOCAL)
            p = vista["preview"]
            self.assertEqual(
                (p["importer"], p["domain"], p["path"], p["exists"], p["source_url"]),
                ("generic", "automation", _RUTA_IMPORTADA, False, _URL_LOCAL))
            self.assertEqual(p["content"], fichero)
            self.assertEqual(p["content_sha256"],
                             hashlib.sha256(fichero.encode("utf-8")).hexdigest())
            self.assertEqual(p["metadata"]["name"], "Luz por movimiento (banco)")
            self.assertEqual([e["name"] for e in p["inputs"]], ["sensor", "luz"])
            self.assertIn("content", p["_third_party_text"]["fields"])
            # La vista previa no ha guardado nada.
            self.assertNotIn(_RUTA_IMPORTADA, await _blueprints(s))

            # Confirmación: HA descarga otra vez, la huella casa y se guarda.
            r = await s.confirmar(tool, vista, url=_URL_LOCAL)
            self.assertEqual((r["result"], r["path"]), ("ok", _RUTA_IMPORTADA))
            guardados = await s.lector.esperar(
                lambda: _blueprints(s), lambda b: _RUTA_IMPORTADA in b,
                descripcion=f"blueprint {_RUTA_IMPORTADA} importado")
            meta = guardados[_RUTA_IMPORTADA]["metadata"]
            self.assertEqual((meta["name"], meta["source_url"]),
                             ("Luz por movimiento (banco)", _URL_LOCAL))

            # Otra vez sin `allow_override`: ya existe, sin token.
            r = await _rechazo(s, tool, url=_URL_LOCAL)
            self.assertEqual(r["error"], "already_exists")
            self.assertNotIn("confirmation_token", r)

            # (3) Se borra con la tool del tramo A.
            vista = await s.vista("ha_delete_blueprint", domain="automation",
                                  path=_RUTA_IMPORTADA)
            r = await s.confirmar("ha_delete_blueprint", vista, domain="automation",
                                  path=_RUTA_IMPORTADA)
            self.assertEqual(r["result"], "ok")
            await s.lector.esperar(lambda: _blueprints(s),
                                   lambda b: _RUTA_IMPORTADA not in b,
                                   descripcion=f"blueprint {_RUTA_IMPORTADA} borrado")
