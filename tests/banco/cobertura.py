"""Inventario de cobertura del banco de Core para los helpers (spec 010, FR-009).

Invariante que comprueba `tests/test_banco_cobertura.py` en la suite normal:
las tools de escritura de estos dominios (sin `readOnlyHint` en el registro de
producción, las registre el módulo que las registre) son exactamente
`PROBADAS_EN_BANCO` ∪ `NO_EJECUTABLES` ∪ `FALLAN_EN_BANCO`, sin solaparse.
Así, una tool de escritura nueva en estos dominios no puede entrar sin
ejecutarse contra HA real o sin decir por qué no se puede.

«Probada» quiere decir ejecutada: en el job, el plugin de
`tests/banco/obligatorio.py` exige que cada tool de `PROBADAS_EN_BANCO` se haya
llamado con éxito dentro de un test que ha pasado (que es donde el lector
comprueba su efecto). Nombrarla en un fichero no basta.

Las lecturas quedan fuera a propósito: lo que la 010 garantiza es que lo que
MODIFICA HA se ha visto funcionar en una HA de verdad (el efecto lo comprueba
el lector independiente, no Hermes).

Este inventario es de los helpers y, desde la 011, de las genéricas
(`PROBADAS_GENERICAS` y `NO_EJECUTABLES_GENERICAS`, al final). La 028
(dashboards) y las demás sub-features que añadan tests al banco llevan su
propia lista.
"""

from __future__ import annotations

DOMINIOS_HELPERS: tuple[str, ...] = (
    "input_boolean",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "counter",
    "timer",
    "schedule",
    "zone",
    "person",
)

# Módulos de `hermes.tools` que registran las tools de esos dominios. Zona y
# persona viven en `zones` y `persons`.
MODULOS_HELPERS: tuple[str, ...] = (
    "counter",
    "input_boolean",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "schedule",
    "timer",
    "zones",
    "persons",
)

# 46 de las 47 tools de la tabla de data-model.md; cada una la llama algún
# `tests/banco/test_banco_helpers_*.py` y comprueba su efecto con el lector.
# La que falta, `ha_reload_counters`, está en `NO_EJECUTABLES` (spec 033).
PROBADAS_EN_BANCO: frozenset[str] = frozenset(
    {
        # input_boolean (4)
        "ha_create_or_update_input_boolean",
        "ha_set_input_boolean",
        "ha_toggle_input_boolean",
        "ha_delete_input_boolean",
        # input_button (3)
        "ha_create_or_update_input_button",
        "ha_press_input_button",
        "ha_delete_input_button",
        # input_datetime (3)
        "ha_create_or_update_input_datetime",
        "ha_set_input_datetime",
        "ha_delete_input_datetime",
        # input_number (5)
        "ha_create_or_update_input_number",
        "ha_set_input_number",
        "ha_increment_input_number",
        "ha_decrement_input_number",
        "ha_delete_input_number",
        # input_select (5)
        "ha_create_or_update_input_select",
        "ha_set_input_select",
        "ha_cycle_input_select",
        "ha_set_input_select_options",
        "ha_delete_input_select",
        # input_text (3)
        "ha_create_or_update_input_text",
        "ha_set_input_text",
        "ha_delete_input_text",
        # counter (6; ha_reload_counters está en NO_EJECUTABLES)
        "ha_create_or_update_counter",
        "ha_increment_counter",
        "ha_decrement_counter",
        "ha_set_counter_value",
        "ha_reset_counter",
        "ha_delete_counter",
        # timer (8)
        "ha_create_or_update_timer",
        "ha_start_timer",
        "ha_pause_timer",
        "ha_change_timer",
        "ha_cancel_timer",
        "ha_finish_timer",
        "ha_reload_timers",
        "ha_delete_timer",
        # schedule (3)
        "ha_create_or_update_schedule",
        "ha_reload_schedules",
        "ha_delete_schedule",
        # zone (3)
        "ha_create_or_update_zone",
        "ha_reload_zones",
        "ha_delete_zone",
        # person (3)
        "ha_create_person",
        "ha_update_person",
        "ha_delete_person",
    }
)

# Tool → motivo por el que no se puede ejecutar en el banco. Un motivo vacío
# no vale (lo comprueba el test del invariante).
NO_EJECUTABLES: dict[str, str] = {
    # Spec 033 (FR-004, research R-2): era el hallazgo de la 010 (llamaba a
    # `counter.reload`, que Core no tiene, y Core respondía 400). Ahora
    # responde `not_supported` sin llamar a HA: no modifica nada, así que no
    # hay efecto que probar. Su test del banco (`TestCounter.test_recarga`) es
    # un canario que comprueba que Core sigue sin `counter.reload` y que la
    # tool no llama a ningún servicio.
    "ha_reload_counters": (
        "HA Core 2026.11.1 no tiene `counter.reload`: la tool responde "
        "`not_supported` sin llamar a HA (deprecada, se retira en la 1.3.0); no "
        "modifica nada que se pueda comprobar. Canario en TestCounter.test_recarga"
    ),
}

# Tool → hallazgo. Se ejecuta en el banco, pero falla contra HA real, así que
# NO cuenta como probada. Cada una tiene su test con `xfail` estricto que
# espera ese fallo concreto, en `XFAIL_PERMITIDOS`. Vacío desde la spec 033,
# que arregló el único (`ha_reload_counters`).
FALLAN_EN_BANCO: dict[str, str] = {}

# Los únicos `xfail` que el job admite: id del test (como lo escribe pytest
# desde la raíz del repositorio) → tool de `FALLAN_EN_BANCO` que documenta.
# Cualquier otro `xfail`, o uno de estos que no se vea fallar, pone el job en
# rojo (`tests/banco/obligatorio.py`). Vacío desde la spec 033.
XFAIL_PERMITIDOS: dict[str, str] = {}


# ── Genéricas (spec 011, T027) ─────────────────────────────────────────────
# Mismo invariante para la familia `generic_commands`: sus tools sin
# `readOnlyHint` (las de escritura) son exactamente
# `PROBADAS_GENERICAS` ∪ `NO_EJECUTABLES_GENERICAS`, sin solaparse
# (`tests/test_banco_cobertura.py`). Las probadas las exige el job igual que
# las de los helpers (`tests/banco/conftest.py`).
FAMILIA_GENERICAS = "generic_commands"

# `tests/banco/test_banco_genericas.py`: `tag/create` y `tag/delete` en dos
# pasos, con la vista previa sin efecto comprobada por el lector.
PROBADAS_GENERICAS: frozenset[str] = frozenset({"ha_call_ws_command"})

# El Supervisor del banco de Core es un simulado que solo replica el proxy
# hacia Core y las dos rutas que Hermes usa al arrancar: ejecutar contra él una
# ruta de escritura del Supervisor no probaría nada. Se prueba en la VM con Supervisor real (spec 014).
NO_EJECUTABLES_GENERICAS: dict[str, str] = {
    "sv_call_api": "Supervisor simulado; se prueba en la VM (spec 014)",
}
