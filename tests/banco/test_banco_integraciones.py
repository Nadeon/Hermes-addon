"""Banco de Core: descubiertos, dominios configurables y preferencias (spec 016, tramo A).

Contra HA Core 2026.11.1 real, con la integración de prueba `banco_flujos`
(`tests/banco/ha_config/custom_components/banco_flujos/`, research R-9):

- `TestEntornoBancoFlujos` (T012): el lector ve que la integración cargó, con
  su descubrimiento inicial y sus dos avisos reparables.
- `TestDescubiertos` (T013): `ha_list_discovered_integrations` y
  `ha_ignore_discovery` sobre un descubrimiento propio del test.
- `TestDominiosConfigurables` (T013): `ha_list_config_flow_domains`.
- `TestPreferencias` (T013): `ha_update_config_entry` sobre una entrada que
  crea el lector por el flujo `user`; la vista previa no cambia nada y el
  token sí.

- `TestSubentries` (T027): crear, reconfigurar, abortar, renombrar y borrar
  (con token) una subentry `elemento`; el lector ve la subentry y su sensor.
- `TestReconfigure` (T027, decisión del supervisor): reconfigure de la entrada
  con token en cada paso; la tool general lo rechaza; el campo de contraseña
  (nombre inocente, selector de contraseña) sale tapado.
- `TestReauth` (tramo C, decisión del supervisor): reautenticación de una
  entrada por `ha_continue_config_entry_flow`, con token en cada paso; la
  vista previa no cambia nada y tapa la clave. Y (T046) `ha_ignore_discovery`
  rechaza ignorar un `reauth` de una entrada con `unique_id`, que sigue ahí.

Hermes hace; el lector independiente comprueba en Core y limpia lo suyo.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo
from tests.banco.lector import ErrorCore

pytestmark = pytest.mark.banco

DOMINIO = "banco_flujos"
_RUTA_FLUJOS = "/api/config/config_entries/flow"


async def _descubiertos(s: SesionEscrituras) -> list[dict[str, Any]]:
    """Flujos de `banco_flujos` que no abrió un usuario, según el lector."""
    return [
        f
        for f in await s.lector.comando({"type": "config_entries/flow/progress"})
        if f.get("handler") == DOMINIO
    ]


async def _entradas(s: SesionEscrituras) -> list[dict[str, Any]]:
    return await s.lector.comando({"type": "config_entries/get", "domain": DOMINIO})


async def _entrada(s: SesionEscrituras, entry_id: str) -> dict[str, Any] | None:
    try:
        respuesta = await s.lector.comando(
            {"type": "config_entries/get_single", "entry_id": entry_id}
        )
    except ErrorCore as exc:
        if exc.codigo == "not_found":
            return None
        raise
    return respuesta["config_entry"]


def _borrar_entrada(s: SesionEscrituras, entry_id: str) -> None:
    async def borrar() -> None:
        await s.lector.rest("DELETE", f"/api/config/config_entries/entry/{entry_id}")

    s.limpiezas.append(borrar)


async def _descubrimiento_propio(s: SesionEscrituras) -> tuple[str, str]:
    """Abre con el servicio de la integración un descubrimiento con unique_id
    aleatorio y devuelve `(flow_id, nombre)`.

    Un descubrimiento ignorado no vuelve (la integración no redescubre al
    borrar la entrada `ignore`), así que cada test abre el suyo y no depende
    del inicial ni del orden de los tests.
    """
    marca = sufijo()
    unique_id, nombre = f"banco-{marca}", f"Banco {marca}"
    await s.lector.comando(
        {
            "type": "call_service",
            "domain": DOMINIO,
            "service": "descubrir",
            "service_data": {"unique_id": unique_id, "name": nombre},
        }
    )
    flujos = await s.lector.esperar(
        lambda: _descubiertos(s),
        lambda fs: any(f["context"].get("unique_id") == unique_id for f in fs),
        descripcion=f"descubrimiento {unique_id} de banco_flujos en flow/progress",
    )
    flow_id = next(f["flow_id"] for f in flujos if f["context"].get("unique_id") == unique_id)

    async def abortar() -> None:
        # Si el test falla antes de ignorarlo, que no quede abierto.
        await s.lector.rest("DELETE", f"{_RUTA_FLUJOS}/{flow_id}")

    s.limpiezas.append(abortar)
    return flow_id, nombre


class TestEntornoBancoFlujos(BancoEscrituras):
    async def test_banco_flujos_cargada(self) -> None:
        """T012: la integración de prueba cargó con lo que necesitan los tramos."""
        async with self.sesion() as s:
            # El descubrimiento inicial se abre cuando HA termina de arrancar.
            await s.lector.esperar(
                lambda: _descubiertos(s),
                lambda fs: any(
                    f["context"].get("unique_id") == "banco-flujos-inicial"
                    and f["context"].get("source") == "integration_discovery"
                    for f in fs
                ),
                descripcion=(
                    "entorno del banco: descubrimiento inicial de banco_flujos (ver "
                    "tests/banco/ha_config/custom_components/banco_flujos/)"
                ),
            )
            avisos = await s.lector.esperar(
                lambda: s.lector.comando({"type": "repairs/list_issues"}),
                lambda r: {"aviso_reparable", "aviso_para_abortar"}
                <= {i["issue_id"] for i in r["issues"] if i["domain"] == DOMINIO},
                descripcion="entorno del banco: los dos avisos reparables de banco_flujos",
            )
            propios = [i for i in avisos["issues"] if i["domain"] == DOMINIO]
            for aviso in propios:
                self.assertTrue(aviso["is_fixable"], aviso)
                self.assertEqual(aviso["translation_key"], aviso["issue_id"])
            estado, dominios = await s.lector.rest(
                "GET", "/api/config/config_entries/flow_handlers"
            )
            self.assertEqual(estado, 200)
            self.assertIn(DOMINIO, dominios)


class TestDescubiertos(BancoEscrituras):
    async def test_listar_e_ignorar(self) -> None:
        async with self.sesion() as s:
            flow_id, nombre = await _descubrimiento_propio(s)

            listado = await s.accion("ha_list_discovered_integrations", domain=DOMINIO)
            item = next(i for i in listado["items"] if i["flow_id"] == flow_id)
            self.assertEqual(
                (item["domain"], item["source"], item["name"], item["ignorable"]),
                (DOMINIO, "integration_discovery", nombre, True),
            )
            self.assertEqual(item["step_id"], "discovery_confirm")
            # Hermes no devuelve el unique_id ni el contexto entero.
            self.assertNotIn("context", item)

            hecho = await s.accion("ha_ignore_discovery", flow_id=flow_id)
            self.assertEqual((hecho["result"], hecho["title"]), ("ok", nombre))

            # El lector ve la entrada `ignore` con ese título y el
            # descubrimiento ya no está.
            ignoradas = await s.lector.esperar(
                lambda: _entradas(s),
                lambda es: any(e["source"] == "ignore" and e["title"] == nombre for e in es),
                descripcion=f"entrada ignore «{nombre}» de banco_flujos",
            )
            entrada = next(e for e in ignoradas if e["source"] == "ignore" and e["title"] == nombre)
            _borrar_entrada(s, entrada["entry_id"])
            self.assertFalse(any(f["flow_id"] == flow_id for f in await _descubiertos(s)))

            # Deshacer como dice la respuesta: borrar la entrada `ignore`.
            # `banco_flujos` no redescubre (no tiene claves de descubrimiento):
            # no vuelve el flujo, y así se anota.
            estado, _ = await s.lector.rest(
                "DELETE", f"/api/config/config_entries/entry/{entrada['entry_id']}"
            )
            self.assertEqual(estado, 200)
            self.assertIsNone(await _entrada(s, entrada["entry_id"]))


class TestDominiosConfigurables(BancoEscrituras):
    async def test_catalogo_y_helpers(self) -> None:
        async with self.sesion() as s:
            todos = await s.accion("ha_list_config_flow_domains")
            self.assertIn(DOMINIO, todos["items"])
            self.assertEqual(todos["items"], sorted(todos["items"]))
            helpers = await s.accion("ha_list_config_flow_domains", type="helper")
            self.assertIn("template", helpers["items"])
            # `banco_flujos` es de tipo `hub`: no es un helper.
            self.assertNotIn(DOMINIO, helpers["items"])


async def _entrada_nueva(s: SesionEscrituras) -> str:
    """El lector crea una entrada de `banco_flujos` por el flujo `user`."""
    estado, paso = await s.lector.rest("POST", _RUTA_FLUJOS, {"handler": DOMINIO})
    assert (estado, paso["type"], paso["step_id"]) == (200, "form", "user"), paso
    estado, hecho = await s.lector.rest(
        "POST", f"{_RUTA_FLUJOS}/{paso['flow_id']}", {"valor": f"banco-{sufijo()}"}
    )
    assert (estado, hecho["type"]) == (200, "create_entry"), hecho
    entry_id = hecho["result"]["entry_id"]
    _borrar_entrada(s, entry_id)
    await s.lector.esperar(
        lambda: _entrada(s, entry_id),
        lambda e: e is not None and e["state"] == "loaded",
        descripcion=f"entrada {entry_id} de banco_flujos en estado loaded",
    )
    return entry_id


class TestPreferencias(BancoEscrituras):
    async def _entrada_nueva(self, s: SesionEscrituras) -> str:
        return await _entrada_nueva(s)

    async def test_titulo_y_preferencias(self) -> None:
        tool = "ha_update_config_entry"
        async with self.sesion() as s:
            entry_id = await self._entrada_nueva(s)

            # Título: sin token.
            titulo = f"Banco {sufijo()}"
            hecho = await s.accion(tool, entry_id=entry_id, title=titulo)
            self.assertNotIn("confirmation_token", hecho)
            self.assertEqual((hecho["result"], hecho["reloaded"]), ("ok", False))
            self.assertEqual((await _entrada(s, entry_id))["title"], titulo)

            # Desactivar el sondeo: la vista previa no cambia nada.
            vista = await s.vista(tool, entry_id=entry_id, pref_disable_polling=True)
            self.assertEqual(vista["preview"]["state"], "loaded")
            self.assertEqual(
                vista["preview"]["pref_disable_polling"], {"current": False, "new": True}
            )
            self.assertFalse((await _entrada(s, entry_id))["pref_disable_polling"])
            hecho = await s.confirmar(tool, vista, entry_id=entry_id, pref_disable_polling=True)
            self.assertEqual((hecho["result"], hecho["reloaded"]), ("ok", True))
            despues = await s.lector.esperar(
                lambda: _entrada(s, entry_id),
                lambda e: e is not None and e["pref_disable_polling"] and e["state"] == "loaded",
                descripcion=f"entrada {entry_id} sin sondeo y cargada de nuevo",
            )
            self.assertTrue(despues["pref_disable_polling"])

            # Desactivar las entidades nuevas: igual.
            vista = await s.vista(tool, entry_id=entry_id, pref_disable_new_entities=True)
            self.assertFalse((await _entrada(s, entry_id))["pref_disable_new_entities"])
            await s.confirmar(tool, vista, entry_id=entry_id, pref_disable_new_entities=True)
            self.assertTrue((await _entrada(s, entry_id))["pref_disable_new_entities"])

            # Volver a activar las dos: sin token.
            hecho = await s.accion(
                tool, entry_id=entry_id, pref_disable_polling=False, pref_disable_new_entities=False
            )
            self.assertNotIn("confirmation_token", hecho)
            final = await _entrada(s, entry_id)
            self.assertEqual(
                (final["pref_disable_polling"], final["pref_disable_new_entities"]), (False, False)
            )

            # Sin cambios: ni token ni llamada.
            self.assertEqual(
                await s.accion(tool, entry_id=entry_id, title=titulo), {"result": "unchanged"}
            )


# ── Tramo B (T027) ────────────────────────────────────────────────────────────

_TAPADO = "***REDACTED***"


async def _subentries(s: SesionEscrituras, entry_id: str) -> list[dict[str, Any]]:
    return await s.lector.comando(
        {"type": "config_entries/subentries/list", "entry_id": entry_id}
    )


async def _entidades_de(s: SesionEscrituras, entry_id: str, subentry_id: str) -> list[str]:
    return [
        e["entity_id"]
        for e in await s.lector.comando({"type": "config/entity_registry/list"})
        if e.get("config_entry_id") == entry_id and e.get("config_subentry_id") == subentry_id
    ]


async def _datos_de_la_entrada(s: SesionEscrituras, entry_id: str) -> dict[str, Any]:
    """Los datos guardados de la entrada, vistos por el lector.

    `config_entries/get_single` no trae `data`: el lector abre su propio
    reconfigure, lee los valores por defecto del formulario (los actuales,
    en claro: el lector habla con Core directamente) y lo aborta.
    """
    estado, paso = await s.lector.rest(
        "POST", _RUTA_FLUJOS, {"handler": DOMINIO, "entry_id": entry_id}
    )
    assert (estado, paso.get("step_id")) == (200, "reconfigure"), paso
    await s.lector.rest("DELETE", f"{_RUTA_FLUJOS}/{paso['flow_id']}")
    return {c["name"]: c.get("default") for c in paso["data_schema"]}


async def _rechazo(s: SesionEscrituras, tool: str, **args: Any) -> dict[str, Any]:
    """Llama a una tool que DEBE rechazar y devuelve su `{"error": …}`.

    Como en `test_banco_genericas.py`: Hermes marca con `isError` toda
    respuesta `{"error": …}`, y `llamar` lo convertiría en fallo del test.
    """
    resultado = await s.cliente.call_tool(tool, args)
    assert getattr(resultado, "is_error", False), f"{tool}: se esperaba un rechazo"
    return json.loads(resultado.content[0].text)


async def _paso_del_flujo(s: SesionEscrituras, flow_id: str) -> tuple[int, Any]:
    return await s.lector.rest("GET", f"{_RUTA_FLUJOS}/{flow_id}")


class TestSubentries(BancoEscrituras):
    async def test_ciclo_de_una_subentry(self) -> None:
        async with self.sesion() as s:
            entry_id = await _entrada_nueva(s)

            listado = await s.accion("ha_list_config_subentries", entry_id=entry_id)
            self.assertIn("elemento", listado["supported_subentry_types"])
            self.assertTrue(listado["supported_subentry_types"]["elemento"]["supports_reconfigure"])
            self.assertEqual(listado["count"], 0)

            # Crear: el lector ve la subentry y su sensor.
            nombre = f"Elemento {sufijo()}"
            paso = await s.accion(
                "ha_start_subentry_flow", entry_id=entry_id, subentry_type="elemento"
            )
            self.assertEqual((paso["type"], paso["step_id"]), ("form", "user"), paso)
            hecho = await s.accion(
                "ha_continue_subentry_flow",
                flow_id=paso["flow_id"],
                user_input={"nombre": nombre, "valor": "7"},
            )
            self.assertEqual((hecho["type"], hecho["status"]), ("create_entry", "ok"), hecho)
            subs = await s.lector.esperar(
                lambda: _subentries(s, entry_id),
                lambda ss: any(x["title"] == nombre for x in ss),
                descripcion=f"subentry «{nombre}» de la entrada {entry_id}",
            )
            subentry_id = next(x["subentry_id"] for x in subs if x["title"] == nombre)
            sensores = await s.lector.esperar(
                lambda: _entidades_de(s, entry_id, subentry_id),
                lambda es: len(es) == 1,
                descripcion=f"sensor de la subentry {subentry_id}",
            )

            # Reconfigurarla por su flujo (sin token).
            nombre2 = f"Elemento {sufijo()}"
            paso = await s.accion(
                "ha_start_subentry_flow",
                entry_id=entry_id, subentry_type="elemento", subentry_id=subentry_id,
            )
            self.assertEqual(paso["step_id"], "reconfigure", paso)
            hecho = await s.accion(
                "ha_continue_subentry_flow",
                flow_id=paso["flow_id"],
                user_input={"nombre": nombre2, "valor": "8"},
            )
            self.assertEqual((hecho["type"], hecho["reason"]), ("abort", "reconfigure_successful"))
            await s.lector.esperar(
                lambda: _subentries(s, entry_id),
                lambda ss: [x["title"] for x in ss] == [nombre2],
                descripcion=f"subentry {subentry_id} reconfigurada como «{nombre2}»",
            )

            # Abrir otro flujo y abortarlo: no aparece ninguna subentry nueva.
            paso = await s.accion(
                "ha_start_subentry_flow", entry_id=entry_id, subentry_type="elemento"
            )
            self.assertEqual(
                await s.accion("ha_abort_subentry_flow", flow_id=paso["flow_id"]),
                {"result": "ok"},
            )
            self.assertEqual(len(await _subentries(s, entry_id)), 1)

            # Renombrar (sin token).
            nombre3 = f"Elemento {sufijo()}"
            hecho = await s.accion(
                "ha_update_subentry", entry_id=entry_id, subentry_id=subentry_id, title=nombre3
            )
            self.assertEqual(hecho["result"], "ok")
            self.assertEqual([x["title"] for x in await _subentries(s, entry_id)], [nombre3])

            # Borrar: la vista previa enumera el sensor y su dispositivo, y no
            # borra nada; con el token, el lector ya no ve ni la subentry ni
            # el sensor.
            tool = "ha_delete_subentry"
            vista = await s.vista(tool, entry_id=entry_id, subentry_id=subentry_id)
            enumeradas = [e["entity_id"] for e in vista["preview"]["entities"]["items"]]
            self.assertEqual(enumeradas, sensores)
            self.assertEqual(vista["preview"]["devices"]["count"], 1, vista["preview"])
            self.assertEqual(len(await _subentries(s, entry_id)), 1)
            self.assertEqual(await _entidades_de(s, entry_id, subentry_id), sensores)
            hecho = await s.confirmar(tool, vista, entry_id=entry_id, subentry_id=subentry_id)
            self.assertEqual(hecho, {"result": "ok"})
            self.assertEqual(await _subentries(s, entry_id), [])
            await s.lector.esperar(
                lambda: _entidades_de(s, entry_id, subentry_id),
                lambda es: es == [],
                descripcion=f"sin entidades de la subentry borrada {subentry_id}",
            )


class TestReconfigure(BancoEscrituras):
    async def test_reconfigure_con_token_en_cada_paso(self) -> None:
        async with self.sesion() as s:
            entry_id = await _entrada_nueva(s)
            antes = await _datos_de_la_entrada(s, entry_id)

            inicio = await s.accion("ha_start_reconfigure_flow", entry_id=entry_id)
            self.assertEqual((inicio["type"], inicio["step_id"]), ("form", "reconfigure"), inicio)
            self.assertIn("ha_continue_reconfigure_flow", inicio["continue_with"])
            flow_id = inicio["flow_id"]

            async def abortar() -> None:
                await s.lector.rest("DELETE", f"{_RUTA_FLUJOS}/{flow_id}")

            s.limpiezas.append(abortar)
            nuevo = {"valor": f"banco-{sufijo()}", "clave": f"clave-{sufijo()}"}

            # La tool general lo rechaza y el flujo sigue donde estaba.
            rechazo = await _rechazo(
                s, "ha_continue_config_entry_flow", flow_id=flow_id, user_input=nuevo
            )
            self.assertEqual(
                (rechazo.get("error"), rechazo.get("tool")),
                ("use_dedicated_tool", "ha_continue_reconfigure_flow"),
            )
            estado, paso = await _paso_del_flujo(s, flow_id)
            self.assertEqual((estado, paso.get("step_id")), (200, "reconfigure"), paso)

            # Vista previa: el campo de contraseña (nombre inocente) sale
            # tapado porque el formulario de HA lo marca con su selector; la
            # vista previa no cambia nada.
            tool = "ha_continue_reconfigure_flow"
            vista = await s.vista(tool, flow_id=flow_id, user_input=nuevo)
            p = vista["preview"]
            self.assertEqual(p["step_id"], "reconfigure")
            self.assertEqual(p["user_input"], {"valor": nuevo["valor"], "clave": _TAPADO})
            self.assertEqual(p["secret_fields"], ["clave"])
            self.assertNotIn(nuevo["clave"], str(vista))
            estado, paso = await _paso_del_flujo(s, flow_id)
            self.assertEqual((estado, paso.get("step_id")), (200, "reconfigure"), paso)

            # Con el token: HA guarda los datos y recarga la entrada.
            hecho = await s.confirmar(tool, vista, flow_id=flow_id, user_input=nuevo)
            self.assertEqual(
                (hecho["type"], hecho["reason"], hecho["status"]),
                ("abort", "reconfigure_successful", "ok"),
            )
            estado, _ = await _paso_del_flujo(s, flow_id)
            self.assertEqual(estado, 404)
            await s.lector.esperar(
                lambda: _entrada(s, entry_id),
                lambda e: e is not None and e["state"] == "loaded",
                descripcion=f"entrada {entry_id} recargada tras el reconfigure",
            )
            despues = await _datos_de_la_entrada(s, entry_id)
            self.assertNotEqual(despues["valor"], antes["valor"])
            self.assertEqual((despues["valor"], despues["clave"]), (nuevo["valor"], nuevo["clave"]))

            # Otro reconfigure: la contraseña actual llega de HA como valor
            # por defecto del formulario, y Hermes la tapa.
            otro = await s.accion("ha_start_reconfigure_flow", entry_id=entry_id)
            campos = {c["name"]: c for c in otro["data_schema"]}
            self.assertEqual(campos["clave"].get("default"), _TAPADO)
            self.assertNotIn(nuevo["clave"], str(otro))
            self.assertEqual(
                await s.accion("ha_abort_config_entry_flow", flow_id=otro["flow_id"]),
                {"result": "ok"},
            )
            estado, _ = await _paso_del_flujo(s, otro["flow_id"])
            self.assertEqual(estado, 404)


# ── Tramo C: reautenticación con token (decisión del supervisor) ──────────────


async def _reauth_en_curso(s: SesionEscrituras, entry_id: str) -> list[dict[str, Any]]:
    return [
        f
        for f in await _descubiertos(s)
        if f["context"].get("source") == "reauth" and f["context"].get("entry_id") == entry_id
    ]


class TestReauth(BancoEscrituras):
    async def test_reauth_con_token_por_la_tool_general(self) -> None:
        async with self.sesion() as s:
            entry_id = await _entrada_nueva(s)
            await s.lector.comando(
                {
                    "type": "call_service",
                    "domain": DOMINIO,
                    "service": "pedir_reauth",
                    "service_data": {"entry_id": entry_id},
                }
            )
            flujos = await s.lector.esperar(
                lambda: _reauth_en_curso(s, entry_id),
                lambda fs: len(fs) == 1,
                descripcion=f"reauth de la entrada {entry_id} en flow/progress",
            )
            flow_id = flujos[0]["flow_id"]

            async def abortar() -> None:
                await s.lector.rest("DELETE", f"{_RUTA_FLUJOS}/{flow_id}")

            s.limpiezas.append(abortar)

            # Hermes lo ve entre lo descubierto, con su `source`.
            listado = await s.accion("ha_list_discovered_integrations", domain=DOMINIO)
            item = next(i for i in listado["items"] if i["flow_id"] == flow_id)
            self.assertEqual((item["source"], item["step_id"]), ("reauth", "reauth_confirm"))

            # Vista previa: la clave sale tapada y no se envía nada.
            tool = "ha_continue_config_entry_flow"
            nuevo = {"clave": f"clave-{sufijo()}"}
            vista = await s.vista(tool, flow_id=flow_id, user_input=nuevo)
            p = vista["preview"]
            self.assertEqual((p["source"], p["entry_id"], p["step_id"]),
                             ("reauth", entry_id, "reauth_confirm"))
            self.assertEqual(p["user_input"], {"clave": _TAPADO})
            self.assertNotIn(nuevo["clave"], str(vista))
            estado, paso = await _paso_del_flujo(s, flow_id)
            self.assertEqual((estado, paso.get("step_id")), (200, "reauth_confirm"), paso)

            # Con el token: HA guarda la clave nueva y recarga la entrada.
            hecho = await s.confirmar(tool, vista, flow_id=flow_id, user_input=nuevo)
            self.assertEqual(
                (hecho["type"], hecho["reason"], hecho["status"]),
                ("abort", "reauth_successful", "ok"),
            )
            await s.lector.esperar(
                lambda: _entrada(s, entry_id),
                lambda e: e is not None and e["state"] == "loaded",
                descripcion=f"entrada {entry_id} recargada tras la reautenticación",
            )
            self.assertEqual((await _datos_de_la_entrada(s, entry_id))["clave"], nuevo["clave"])

    async def test_no_se_puede_ignorar_un_reauth(self) -> None:
        """T046 (convergencia, hallazgo ALTO): ignorar un `reauth` se rechaza.

        Escenario real: una entrada CON `unique_id` (la de un descubrimiento
        confirmado) pide reautenticación; el contexto del `reauth` lleva ese
        `unique_id`. Si Hermes mandara `config_entries/ignore_flow`, HA crearía
        una entrada `ignore` con él y BORRARÍA la entrada real. El lector
        comprueba que la entrada sigue ahí, cargada, y que no hay ninguna
        `ignore` nueva.
        """
        async with self.sesion() as s:
            flujo_descubierto, _ = await _descubrimiento_propio(s)
            unique_id = next(
                f["context"]["unique_id"]
                for f in await _descubiertos(s)
                if f["flow_id"] == flujo_descubierto
            )
            estado, hecho = await s.lector.rest(
                "POST", f"{_RUTA_FLUJOS}/{flujo_descubierto}", {}
            )
            self.assertEqual((estado, hecho["type"]), (200, "create_entry"), hecho)
            entry_id = hecho["result"]["entry_id"]
            _borrar_entrada(s, entry_id)
            await s.lector.esperar(
                lambda: _entrada(s, entry_id),
                lambda e: e is not None and e["state"] == "loaded",
                descripcion=f"entrada {entry_id} (descubierta) en estado loaded",
            )
            ignoradas_antes = [e["entry_id"] for e in await _entradas(s) if e["source"] == "ignore"]

            await s.lector.comando(
                {
                    "type": "call_service",
                    "domain": DOMINIO,
                    "service": "pedir_reauth",
                    "service_data": {"entry_id": entry_id},
                }
            )
            flujos = await s.lector.esperar(
                lambda: _reauth_en_curso(s, entry_id),
                lambda fs: len(fs) == 1,
                descripcion=f"reauth de la entrada {entry_id} en flow/progress",
            )
            flow_id = flujos[0]["flow_id"]

            async def abortar() -> None:
                await s.lector.rest("DELETE", f"{_RUTA_FLUJOS}/{flow_id}")

            s.limpiezas.append(abortar)
            # El escenario peligroso es real: el reauth lleva el unique_id de
            # la entrada.
            self.assertEqual(flujos[0]["context"].get("unique_id"), unique_id)

            listado = await s.accion("ha_list_discovered_integrations", domain=DOMINIO)
            item = next(i for i in listado["items"] if i["flow_id"] == flow_id)
            self.assertFalse(item["ignorable"])

            rechazo = await _rechazo(s, "ha_ignore_discovery", flow_id=flow_id)
            self.assertEqual(
                (rechazo.get("error"), rechazo.get("reason"), rechazo.get("source")),
                ("cannot_ignore", "not_a_discovery", "reauth"),
            )

            # El lector: la entrada real sigue, cargada; ninguna `ignore`
            # nueva; el reauth sigue abierto.
            entrada = await _entrada(s, entry_id)
            self.assertIsNotNone(entrada)
            self.assertEqual(entrada["state"], "loaded")
            ignoradas = [e["entry_id"] for e in await _entradas(s) if e["source"] == "ignore"]
            self.assertEqual(sorted(ignoradas), sorted(ignoradas_antes))
            self.assertEqual(len(await _reauth_en_curso(s, entry_id)), 1)
