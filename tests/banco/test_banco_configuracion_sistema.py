"""Banco de Core: configuración del núcleo y exposición a asistentes (spec 021, tramo a, T014).

Las cinco tools del tramo a contra HA Core real, con el lector independiente
comprobando cada efecto directamente en Core y dejando el banco como estaba:

- **Núcleo**: `ha_get_core_config` coincide con el `get_config` del lector.
  `ha_update_core_config(location_name, radius)`: la vista previa no cambia
  nada y lleva el aviso `yaml_source` (el banco tiene `homeassistant:` en
  YAML); con token, el lector ve los valores nuevos. El lector restaura los
  valores al cerrar, pase lo que pase. Lo único que no puede devolver es
  `config_source`: HA pasa a `storage` al guardar y solo vuelve a `yaml` al
  reiniciar (es lo que dice el aviso); ningún otro test lo mira.
- **Exposición**: un `input_boolean` creado por el lector se expone a
  `conversation` y `cloud.alexa` (sin la nube cargada, HA guarda la
  preferencia igual): la vista previa no cambia nada (lo comprueba el lector
  con `homeassistant/expose_entity/list`), la confirmación sí, la lista de
  Hermes la incluye y ocultarla (sin token, decisión D-4) la quita.
- **Entidades nuevas**: `expose_new` de `conversation` se cambia y se
  restaura por la propia tool (un paso con token y otro sin él), comprobado
  con `homeassistant/expose_new_entities/get` del lector, que también lo
  restaura al cerrar.
- **Tabla**: `config/core/detect` se lee por la genérica (el contenedor no
  tiene salida a internet: HA responde un objeto, vacío) y
  `config/core/update` por la genérica da `use_dedicated_tool`.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo
from tests.banco.entorno import llamar, rechazo

pytestmark = pytest.mark.banco

_CAMPOS = ("location_name", "latitude", "longitude", "elevation", "radius",
           "time_zone", "currency", "country", "language",
           "internal_url", "external_url")


async def _config(s: SesionEscrituras) -> dict[str, Any]:
    return await s.lector.comando({"type": "get_config"})


async def _expuesta(s: SesionEscrituras, entity_id: str) -> dict[str, Any]:
    lista = await s.lector.comando({"type": "homeassistant/expose_entity/list"})
    return lista["exposed_entities"].get(entity_id, {})


async def _nuevas(s: SesionEscrituras, asistente: str) -> bool:
    r = await s.lector.comando(
        {"type": "homeassistant/expose_new_entities/get", "assistant": asistente})
    return r["expose_new"]


class TestConfiguracionDelNucleo(BancoEscrituras):
    async def test_lectura_igual_que_el_lector(self) -> None:
        async with self.sesion() as s:
            leida = await s.accion("ha_get_core_config")
            real = await _config(s)
            for campo in _CAMPOS:
                with self.subTest(campo=campo):
                    self.assertEqual(leida[campo], real[campo])
            self.assertEqual(leida["unit_system"], "metric")
            self.assertEqual(leida["config_source"], real["config_source"])
            self.assertEqual(leida["version"], real["version"])

    async def test_cambiar_y_restaurar(self) -> None:
        tool = "ha_update_core_config"
        async with self.sesion() as s:
            antes = await _config(s)
            original = {"location_name": antes["location_name"], "radius": antes["radius"]}

            async def restaurar() -> None:
                await s.lector.comando({"type": "config/core/update", **original})

            s.limpiezas.append(restaurar)
            # Premisa del aviso: el banco tiene la configuración en YAML.
            self.assertEqual(antes["config_source"], "yaml")

            args = {"location_name": f"Banco 021 {sufijo()}",
                    "radius": antes["radius"] + 25}
            vista = await s.vista(tool, **args)
            p = vista["preview"]
            self.assertEqual(p["changes"]["radius"],
                             {"before": antes["radius"], "after": args["radius"]})
            self.assertEqual(p["changes"]["location_name"]["before"], antes["location_name"])
            self.assertTrue(any(a.startswith("yaml_source:") for a in p["warnings"]), p)
            self.assertTrue(any(a.startswith("location:") for a in p["warnings"]), p)
            # La vista previa no ha cambiado nada.
            ahora = await _config(s)
            self.assertEqual({c: ahora[c] for c in _CAMPOS}, {c: antes[c] for c in _CAMPOS})

            r = await s.confirmar(tool, vista, **args)
            self.assertEqual(r["result"], "ok")
            self.assertEqual(r["applied"], ["location_name", "radius"])
            await s.lector.esperar(
                lambda: _config(s),
                lambda c: (c["location_name"], c["radius"])
                == (args["location_name"], args["radius"]),
                descripcion="configuración del núcleo con los valores nuevos",
            )

            # Restaurar por la propia tool y comprobarlo con el lector.
            vista = await s.vista(tool, **original)
            await s.confirmar(tool, vista, **original)
            final = await _config(s)
            self.assertEqual({c: final[c] for c in _CAMPOS}, {c: antes[c] for c in _CAMPOS})


class TestExposicionAAsistentes(BancoEscrituras):
    async def test_exponer_listar_y_ocultar(self) -> None:
        tool = "ha_set_entity_exposure"
        asistentes = ["cloud.alexa", "conversation"]
        async with self.sesion() as s:
            entidad = await s.input_boolean(f"banco_021_{sufijo()}")
            antes = await _expuesta(s, entidad)
            self.assertNotIn("cloud.alexa", antes)

            args = {"entity_ids": [entidad], "assistants": asistentes, "expose": True}
            vista = await s.vista(tool, **args)
            self.assertEqual(vista["preview"]["by_assistant"]["cloud.alexa"]["change"],
                             [entidad])
            self.assertEqual(await _expuesta(s, entidad), antes)

            r = await s.confirmar(tool, vista, **args)
            self.assertEqual(r["result"], "ok")
            await s.lector.esperar(
                lambda: _expuesta(s, entidad),
                lambda e: e.get("cloud.alexa") is True and e.get("conversation") is True,
                descripcion=f"{entidad} expuesta a Alexa y a Assist",
            )

            lista = await s.accion("ha_list_exposed_entities", domain="input_boolean")
            fila = next(i for i in lista["items"] if i["entity_id"] == entidad)
            self.assertEqual(fila["assistants"], asistentes)
            self.assertIsInstance(lista["expose_new"]["conversation"], bool)

            # Ocultar: a la primera, sin token (D-4).
            r = await s.accion(tool, entity_ids=[entidad], assistants=asistentes,
                               expose=False)
            self.assertEqual(r["changed_entity_ids"], [entidad])
            await s.lector.esperar(
                lambda: _expuesta(s, entidad),
                lambda e: not e.get("cloud.alexa") and not e.get("conversation"),
                descripcion=f"{entidad} oculta a Alexa y a Assist",
            )

    async def test_entidades_nuevas(self) -> None:
        tool = "ha_set_expose_new_entities"
        asistente = "conversation"
        async with self.sesion() as s:
            original = await _nuevas(s, asistente)

            async def restaurar() -> None:
                await s.lector.comando({"type": "homeassistant/expose_new_entities/set",
                                        "assistant": asistente, "expose_new": original})

            s.limpiezas.append(restaurar)

            async def con_token(valor: bool) -> None:
                vista = await s.vista(tool, assistant=asistente, expose_new=valor)
                self.assertEqual(vista["preview"]["before"], not valor)
                self.assertEqual(await _nuevas(s, asistente), not valor)
                await s.confirmar(tool, vista, assistant=asistente, expose_new=valor)

            async def sin_token(valor: bool) -> None:
                r = await s.accion(tool, assistant=asistente, expose_new=valor)
                self.assertEqual(r, {"result": "ok", "assistant": asistente,
                                     "expose_new": valor})

            # Los dos caminos, sea cual sea el valor de partida.
            pasos = (sin_token, con_token) if original else (con_token, sin_token)
            for paso, valor in zip(pasos, (not original, original)):
                await paso(valor)
                await s.lector.esperar(
                    lambda: _nuevas(s, asistente), lambda v, valor=valor: v is valor,
                    descripcion=f"expose_new de {asistente} = {valor}",
                )


class TestTablaDeLa021(BancoEscrituras):
    async def test_detect_por_la_generica_y_update_rechazado(self) -> None:
        async with self.sesion() as s:
            r = await llamar(s.cliente, "ha_read_ws_command", type="config/core/detect")
            self.assertIsInstance(r["result"], dict)
            antes = await _config(s)
            r = await rechazo(s.cliente, "ha_call_ws_command", type="config/core/update",
                              payload={"radius": 1})
            self.assertEqual((r["error"], r["tool"]),
                             ("use_dedicated_tool", "ha_update_core_config"))
            self.assertEqual((await _config(s))["radius"], antes["radius"])
