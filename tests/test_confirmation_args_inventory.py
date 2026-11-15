"""Inventario de argumentos atados al `confirmation_token` (spec 033, FR-003).

El token de una tool en dos pasos solo protege lo que ata: un argumento que
cambia el efecto y queda fuera del hash permite previsualizar una cosa y
confirmar otra (principio IV). Así pasó con `variables` en `ha_run_script` y
`ha_trigger_automation` hasta la 033.

Aquí cada argumento de cada tool con `confirmation_token` está clasificado:

- `"atado"`: entra en el dict que se pasa a `create_confirmation_token` y a
  `validate_confirmation_token` / `resolve_confirmation_token` (normalizado
  si la tool lo normaliza antes de enviarlo, u omitible en la confirmación si
  la tool lo resuelve desde lo guardado; en los dos casos el hash lo cubre);
- `"exento: <motivo>"`: no entra en el hash, con el motivo escrito.

El test comprueba por AST, sin importar nada, que el inventario cubre
EXACTAMENTE las funciones decoradas con `mcp.tool()` de
`hermes/src/hermes/tools/*.py` que tienen `confirmation_token`, y en cada una
EXACTAMENTE los argumentos de su firma. Es documental: no prueba el hash por
sí solo (eso lo hacen los tests de comportamiento de cada tool), pero obliga a
quien añade una tool con token, o un argumento a una que ya lo tiene, a decidir
y escribir si queda atado.

Regla para las sub-features siguientes: una tool nueva con
`confirmation_token` añade aquí su entrada, con todos sus argumentos, en el
mismo cambio. Si no lo hace, este test cae en su rama nombrando la tool o el
argumento.

Control negativo (T007), permanente en `TestControlNegativo`: sobre una copia
temporal de `tools/`, una tool nueva con token sin entrada y un argumento
nuevo en `ha_run_script` hacen que la comprobación falle nombrando los dos.

Contraste con el registro real (T037): el descubrimiento por AST se compara
además con las tools que publican `confirmation_token` en un `MCPServer` real
(`_real_registry()`), así que una tool con token registrada de otra forma
(`mcp.add_tool`, un subpaquete) tampoco se escapa.

Recuento: 86 tools. La auditoría de la spec (research R-1) contaba 79 sobre
la punta de entonces; la 011 integró después `ha_call_ws_command` y
`sv_call_api`, que atan todo lo que envían, y el tramo 2 de la 033 dio token
a `ha_create_scene_from_current` (FR-006). Al integrar la 033 en la rama del
programa entraron las que llegaron después de su base, comprobadas en el
código: `ha_call_service_response` con token (018), `view_index` y `view` de
`ha_save_lovelace_dashboard` (guardado por vista, 018) y las tres de la 012
que confirman (`ha_set_log_level`, `ha_clear_system_log` y
`ha_dismiss_persistent_notification`). Todas atan todo lo que cambia la
acción; ningún hallazgo.
"""

from __future__ import annotations

import ast
import shutil
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
TOOLS = RAIZ / "hermes" / "src" / "hermes" / "tools"

A = "atado"
TOKEN = "exento: es el propio token; no puede formar parte de su hash"

# Grupos para no repetir; el dict final se arma abajo.
_RECARGAS = (
    "ha_reload_automations",
    "ha_reload_counters",
    "ha_reload_scenes",
    "ha_reload_schedules",
    "ha_reload_scripts",
    "ha_reload_timers",
    "ha_reload_zones",
    "sv_reboot_host",
    "sv_restart_core",
)
_HELPERS = (
    "counter",
    "input_boolean",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "schedule",
    "timer",
    "zone",
)
_ADDONS = (
    "sv_install_addon",
    "sv_restart_addon",
    "sv_start_addon",
    "sv_stop_addon",
    "sv_uninstall_addon",
    "sv_update_addon",
)

INVENTARIO: dict[str, dict[str, str]] = {
    # ── servicios, comandos genéricos, scripts y automatizaciones ───────
    "ha_call_service": {"domain": A, "service": A, "service_data": A},
    # Spec 018: mismo hash que `ha_call_service` (normalizado en minúsculas),
    # pero atado a ESTA tool.
    "ha_call_service_response": {"domain": A, "service": A, "service_data": A},
    "ha_call_ws_command": {"type": A, "payload": A},
    "sv_call_api": {"method": A, "path": A, "body": A},
    # `variables` atadas desde la 033 (`guarded_entity_invoke`).
    "ha_run_script": {"script_id": A, "variables": A},
    "ha_trigger_automation": {"automation_id": A, "variables": A},
    "ha_create_or_update_automation": {"automation_id": A, "config": A},
    "ha_create_or_update_script": {"script_id": A, "config": A},
    "ha_create_or_update_scene": {"scene_id": A, "config": A},
    "ha_delete_automation": {"automation_id": A},
    "ha_delete_script": {"script_id": A},
    "ha_delete_scene": {"scene_id": A},
    # Spec 033 (FR-006): el token solo hace falta para reemplazar una escena
    # temporal. `scene_id` va normalizado (sin `scene.`), como se envía.
    "ha_create_scene_from_current": {
        "scene_id": A,
        "entity_ids": A,
        "name": "exento: con valor se rechaza (name_not_supported) antes de emitir o validar el token",
    },
    # ── helpers y personas (colecciones) ────────────────────────────────
    **{f"ha_create_or_update_{h}": {"entity_id": A, "config": A} for h in _HELPERS},
    **{f"ha_delete_{h}": {"entity_id": A} for h in _HELPERS},
    "ha_update_person": {"entity_id": A, "config": A},
    "ha_delete_person": {"entity_id": A},
    # ── recargas y reinicios: no tienen más argumento que el token ──────
    **{t: {} for t in _RECARGAS},
    # ── Lovelace ─────────────────────────────────────────────────────────
    # Spec 018: en el guardado por vista atan `url_path`, `view_index` y
    # `view` (omitible al confirmar), y además el documento leído (`estado`).
    # `config` y `remove_top_level_keys` no se pueden mezclar con la vista
    # (`invalid_argument` antes de tocar el token).
    "ha_save_lovelace_dashboard": {
        "url_path": A,
        "config": A,
        "remove_top_level_keys": A,
        "view_index": A,
        "view": A,
    },
    "ha_update_lovelace_dashboard_metadata": {"url_path": A, "updates": A},
    "ha_delete_lovelace_dashboard": {"url_path": A},
    "ha_create_lovelace_resource": {"url": A, "res_type": A},
    "ha_update_lovelace_resource": {"resource_id": A, "updates": A},
    "ha_delete_lovelace_resource": {"resource_id": A},
    # ── registros ───────────────────────────────────────────────────────
    "ha_update_area": {"area_id": A, "updates": A},
    "ha_delete_area": {"area_id": A},
    "ha_update_floor": {"floor_id": A, "updates": A},
    "ha_delete_floor": {"floor_id": A},
    "ha_update_label": {"label_id": A, "updates": A},
    "ha_delete_label": {"label_id": A},
    "ha_update_category": {"scope": A, "category_id": A, "updates": A},
    "ha_delete_category": {"scope": A, "category_id": A},
    "ha_update_device": {"device_id": A, "updates": A},
    "ha_remove_device": {"device_id": A},
    "ha_remove_device_from_config_entry": {"device_id": A, "config_entry_id": A},
    "ha_update_entity_registry": {"entity_id": A, "updates": A},
    "ha_remove_entity_registry": {"entity_id": A},
    # ── config entries y reparaciones ───────────────────────────────────
    "ha_disable_config_entry": {"entry_id": A},
    "ha_delete_config_entry": {"entry_id": A},
    "ha_ignore_repair": {"domain": A, "issue_id": A, "ignore": A},
    # ── diagnóstico de Core (spec 012) ──────────────────────────────────
    # `level` va normalizado (en mayúsculas) antes de atarlo.
    "ha_set_log_level": {"level": A, "integration": A, "module": A, "persistence": A},
    "ha_clear_system_log": {},
    "ha_dismiss_persistent_notification": {"notification_id": A},
    # ── Supervisor ──────────────────────────────────────────────────────
    **{t: {"slug": A} for t in _ADDONS},
    "sv_set_addon_options": {"slug": A, "options": A},
    "sv_delete_backup": {"slug": A},
    "sv_restore_backup_full": {"slug": A, "password": A},
    "sv_restore_backup_partial": {
        "slug": A,
        "addons": A,
        "folders": A,
        "password": A,
        "include_homeassistant": A,
    },
    "sv_dismiss_resolution_issue": {"issue_uuid": A},
    "sv_dismiss_resolution_suggestion": {"suggestion_uuid": A},
    # ── ficheros ────────────────────────────────────────────────────────
    "fs_write_file": {"path": A, "content": A},
    "fs_delete_file": {"path": A},
    "fs_move_file": {"src": A, "dst": A, "overwrite": A},
    "fs_restore_file_backup": {"path": A, "timestamp": A},
    "fs_set_secret": {"key": A, "value": A},
}
# `confirmation_token` está en todas y nunca entra en su propio hash.
for _args in INVENTARIO.values():
    _args["confirmation_token"] = TOKEN


def _es_tool(funcion: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    return any(ast.unparse(d).startswith("mcp.tool") for d in funcion.decorator_list)


def firmas_con_token(carpeta: Path) -> dict[str, list[str]]:
    """Tool → argumentos de su firma, para las que tienen `confirmation_token`."""
    firmas: dict[str, list[str]] = {}
    for fichero in sorted(carpeta.glob("*.py")):
        arbol = ast.parse(fichero.read_text(encoding="utf-8"), filename=str(fichero))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, (ast.AsyncFunctionDef, ast.FunctionDef)) and _es_tool(nodo):
                a = nodo.args
                nombres = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs]
                if "confirmation_token" in nombres:
                    firmas[nodo.name] = nombres
    return firmas


def problemas(carpeta: Path, inventario: dict[str, dict[str, str]]) -> list[str]:
    """Diferencias entre las firmas de `carpeta` y el inventario, legibles."""
    firmas = firmas_con_token(carpeta)
    salida: list[str] = []
    for tool in sorted(set(firmas) - set(inventario)):
        salida.append(f"{tool}: tiene confirmation_token y no está en el inventario")
    for tool in sorted(set(inventario) - set(firmas)):
        salida.append(f"{tool}: está en el inventario y no es una tool con confirmation_token")
    for tool in sorted(set(firmas) & set(inventario)):
        firma, inv = set(firmas[tool]), set(inventario[tool])
        for arg in sorted(firma - inv):
            salida.append(f"{tool}.{arg}: argumento sin clasificar (atado o exento con motivo)")
        for arg in sorted(inv - firma):
            salida.append(f"{tool}.{arg}: en el inventario pero no en la firma")
    for tool, args in sorted(inventario.items()):
        for arg, valor in sorted(args.items()):
            if valor == A:
                continue
            motivo = valor.removeprefix("exento:").strip() if valor.startswith("exento:") else ""
            if not motivo:
                salida.append(f"{tool}.{arg}: {valor!r} no es «atado» ni «exento: <motivo>»")
    return salida


def firmas_publicadas(registro: dict) -> dict[str, list[str]]:
    """Tool → argumentos de su esquema publicado, para las que publican
    `confirmation_token`, sobre el registro real de un `MCPServer`."""
    firmas: dict[str, list[str]] = {}
    for nombre, tool in registro.items():
        propiedades = list((tool.parameters or {}).get("properties", {}))
        if "confirmation_token" in propiedades:
            firmas[nombre] = propiedades
    return firmas


def diferencias_con_el_registro(
    por_ast: dict[str, list[str]], publicadas: dict[str, list[str]]
) -> list[str]:
    """Lo que el descubrimiento por AST no ve del registro real, y al revés."""
    salida: list[str] = []
    for tool in sorted(set(publicadas) - set(por_ast)):
        salida.append(f"{tool}: publica confirmation_token y el AST no la encuentra")
    for tool in sorted(set(por_ast) - set(publicadas)):
        salida.append(f"{tool}: el AST la encuentra y el registro no publica su token")
    for tool in sorted(set(por_ast) & set(publicadas)):
        # `ctx` lo inyecta el SDK y no sale en el esquema publicado.
        ast_args = set(por_ast[tool]) - {"ctx"}
        if ast_args != set(publicadas[tool]):
            salida.append(
                f"{tool}: argumentos distintos (AST {sorted(ast_args)}, "
                f"registro {sorted(publicadas[tool])})"
            )
    return salida


class TestInventarioDeArgumentosAtados(unittest.TestCase):
    def test_cubre_exactamente_las_tools_con_token_y_sus_argumentos(self) -> None:
        self.assertEqual(problemas(TOOLS, INVENTARIO), [])

    def test_recuento(self) -> None:
        # 79 de la auditoría de la 033 + 2 genéricas de la 011 + la escena
        # desde el estado actual (tramo 2 de la 033) + `ha_call_service_response`
        # (018) + las tres de la 012 que confirman.
        self.assertEqual(len(firmas_con_token(TOOLS)), 86)

    def test_el_token_siempre_exento_y_lo_demas_atado_o_con_motivo(self) -> None:
        for tool, args in INVENTARIO.items():
            self.assertEqual(args.get("confirmation_token"), TOKEN, tool)

    def test_el_ast_ve_lo_mismo_que_el_registro_real(self) -> None:
        # T037 (B1 de la revisión): el inventario descubre las tools por AST
        # de `tools/*.py` y decoradores `mcp.tool…`. Una tool con token
        # registrada de otra forma (`mcp.add_tool`, un subpaquete, otro
        # módulo) se le escaparía; el registro real de un `MCPServer` no.
        # Control negativo, comprobado y restaurado: registrando
        # `ha_create_scene_from_current` con `registrar = mcp.tool` y
        # `@registrar()`, el AST deja de verla y este test cae nombrándola.
        from tests.test_tools_registration import _real_registry

        publicadas = firmas_publicadas(_real_registry())
        self.assertEqual(
            diferencias_con_el_registro(firmas_con_token(TOOLS), publicadas), []
        )
        self.assertEqual(len(publicadas), 86)

    def test_las_variables_de_las_entidades_restringidas_quedan_atadas(self) -> None:
        # El hallazgo que origina este inventario (spec 033, FR-001).
        self.assertEqual(INVENTARIO["ha_run_script"]["variables"], A)
        self.assertEqual(INVENTARIO["ha_trigger_automation"]["variables"], A)


class TestControlNegativo(unittest.TestCase):
    """T007: el inventario cae, nombrándolos, ante una tool nueva con token sin
    entrada y ante un argumento nuevo de una tool existente."""

    def test_tool_y_argumento_nuevos_sin_clasificar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copia = Path(tmp) / "tools"
            shutil.copytree(TOOLS, copia)
            scripts = copia / "scripts.py"
            fuente = scripts.read_text(encoding="utf-8")
            viejo = "        variables: dict[str, Any] | None = None,\n        confirmation_token"
            self.assertEqual(fuente.count(viejo), 1)
            fuente = fuente.replace(
                viejo,
                "        variables: dict[str, Any] | None = None,\n"
                "        modo: str | None = None,\n"
                "        confirmation_token",
            )
            scripts.write_text(fuente, encoding="utf-8")
            (copia / "zz_nueva.py").write_text(
                "def register(mcp):\n"
                "    @mcp.tool()\n"
                "    async def ha_tool_ficticia(entity_id: str,"
                " confirmation_token: str | None = None) -> object:\n"
                "        return None\n",
                encoding="utf-8",
            )
            salida = problemas(copia, INVENTARIO)
        self.assertEqual(
            salida,
            [
                "ha_tool_ficticia: tiene confirmation_token y no está en el inventario",
                "ha_run_script.modo: argumento sin clasificar (atado o exento con motivo)",
            ],
        )

    def test_tool_registrada_fuera_del_ast(self) -> None:
        # T037: control negativo permanente de la comparación con el
        # registro. Una tool con token que solo está en el registro (como si
        # se hubiera registrado con `mcp.add_tool`) y un argumento que solo
        # está en el esquema publicado salen nombrados.
        por_ast = firmas_con_token(TOOLS)
        publicadas = {t: list(a) for t, a in por_ast.items()}
        publicadas["ha_tool_por_add_tool"] = ["entity_id", "confirmation_token"]
        publicadas["ha_run_script"].append("modo")
        self.assertEqual(
            diferencias_con_el_registro(por_ast, publicadas),
            [
                "ha_tool_por_add_tool: publica confirmation_token y el AST no la encuentra",
                "ha_run_script: argumentos distintos (AST "
                f"{sorted(por_ast['ha_run_script'])}, registro "
                f"{sorted(publicadas['ha_run_script'])})",
            ],
        )

    def test_motivo_vacio(self) -> None:
        inventario = {t: dict(a) for t, a in INVENTARIO.items()}
        inventario["ha_run_script"]["variables"] = "exento:  "
        salida = problemas(TOOLS, inventario)
        self.assertEqual(len(salida), 1)
        self.assertIn("ha_run_script.variables", salida[0])


if __name__ == "__main__":
    unittest.main()
