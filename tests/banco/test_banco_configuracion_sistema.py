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
- **Tabla**: `config/core/detect` se lee por la genérica y
  `config/core/update` por la genérica da `use_dedicated_tool`. `detect`
  consulta un servicio externo de geolocalización y el contenedor no tiene
  salida a internet: HA suele responder enseguida con un objeto vacío, pero a
  veces la consulta se cuelga más que el plazo de Hermes (falló así una vez
  en el CI). Por eso se aceptan dos resultados, los dos comprobados al
  detalle por `comprobar_detect`: la respuesta de HA o un error limpio y
  honesto de Hermes (plazo agotado o fallo de HA). Una excepción sin tratar o
  un resultado que mienta hace fallar el test; no es un salto.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo
from tests.banco.entorno import _decodificar, llamar, rechazo

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


# Claves que puede devolver `websocket_detect_config` en HA 2026.11.1
# (`homeassistant/components/config/core.py`); ninguna más.
_CLAVES_DETECT = frozenset({"unit_system", "latitude", "longitude", "time_zone",
                            "currency", "country"})
# El mensaje de `HATimeoutError` de `ws_send` (`hermes/ha.py`), que la genérica
# devuelve con la forma de siempre de un fallo de conexión: `{"error": texto}`.
_PLAZO_DETECT = "Timeout waiting for HA WS response for command config/core/detect"


def comprobar_detect(resultado: Any) -> str:
    """Valida la respuesta MCP de `ha_read_ws_command(type="config/core/detect")`.

    Devuelve el camino que salió (`"respuesta"`, `"plazo"` o `"fallo_ha"`) y
    lanza `AssertionError` si no es uno de los honestos:

    - sin `isError`: la forma de lectura de la genérica con un objeto de HA
      que solo trae claves de `detect` (ni un `error` escondido dentro);
    - con `isError`: JSON con el error genérico del plazo agotado de ESTE
      comando, o `ha_command_failed` con el `ha_code` de HA. Un texto que no
      es JSON es una excepción sin tratar dentro de la tool (FastMCP la
      convierte en `Error executing tool …`): no se acepta.

    Control negativo (en `tests/test_banco_detect_robusto.py`): cada rama
    rechaza su resultado mentiroso.
    """
    if not getattr(resultado, "is_error", False):
        r = _decodificar(resultado)
        assert isinstance(r, dict), f"respuesta que no es un objeto: {r!r}"
        assert set(r) == {"command", "category", "result"}, f"forma inesperada: {r!r}"
        assert (r["command"], r["category"]) == ("config/core/detect", "read"), r
        assert isinstance(r["result"], dict), f"result no es un objeto: {r!r}"
        sobra = set(r["result"]) - _CLAVES_DETECT
        assert not sobra, f"claves que detect no devuelve: {sorted(sobra)}"
        return "respuesta"
    texto = " ".join(getattr(c, "text", "") for c in resultado.content)
    try:
        r = json.loads(texto)
    except ValueError:
        raise AssertionError(f"excepción sin tratar en la tool: {texto}") from None
    assert isinstance(r, dict) and "error" in r, f"error sin forma de error: {r!r}"
    if r == {"error": _PLAZO_DETECT}:
        return "plazo"
    if r["error"] == "ha_command_failed":
        assert set(r) == {"error", "detail", "ha_code"}, f"forma inesperada: {r!r}"
        assert isinstance(r["ha_code"], str) and r["ha_code"], r
        # `detect` existe en HA 2026.11.1: «no existe» sería mentira.
        assert r["ha_code"] != "unknown_command", f"detect sí existe en HA: {r!r}"
        return "fallo_ha"
    raise AssertionError(f"error que no es plazo agotado ni fallo de HA: {r!r}")


class TestTablaDeLa021(BancoEscrituras):
    async def test_detect_por_la_generica_y_update_rechazado(self) -> None:
        async with self.sesion() as s:
            # Ni `llamar` (convertiría el plazo agotado en fallo) ni un salto:
            # la respuesta, sea cual sea, la valida `comprobar_detect`. No suma
            # la tool a las probadas: `ha_read_ws_command` la exige ya
            # `test_banco_genericas.py` (`cobertura_lecturas.py`).
            camino = comprobar_detect(await s.cliente.call_tool(
                "ha_read_ws_command", {"type": "config/core/detect"}))
            self.assertIn(camino, ("respuesta", "plazo", "fallo_ha"))
            antes = await _config(s)
            r = await rechazo(s.cliente, "ha_call_ws_command", type="config/core/update",
                              payload={"radius": 1})
            self.assertEqual((r["error"], r["tool"]),
                             ("use_dedicated_tool", "ha_update_core_config"))
            self.assertEqual((await _config(s))["radius"], antes["radius"])
