"""Inventario de cobertura del banco de Core para los helpers (spec 010, FR-009).

Invariante que comprueba `tests/test_banco_cobertura.py` en la suite normal:
las tools que registran `MODULOS_HELPERS` y no son `ha_list_*` ni `ha_get_*`
son exactamente `PROBADAS_EN_BANCO` ∪ `NO_EJECUTABLES`, sin solaparse. Así,
una tool de escritura nueva en estos dominios no puede entrar sin ejecutarse
contra HA real o sin decir por qué no se puede.

Las lecturas quedan fuera a propósito: lo que la 010 garantiza es que lo que
MODIFICA HA se ha visto funcionar en una HA de verdad (el efecto lo comprueba
el lector independiente, no Hermes).

Este inventario es solo de los helpers. La 028 (dashboards) y las demás
sub-features que añadan tests al banco llevan su propia lista.
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

# Las 47 tools de la tabla de data-model.md; cada una la llama algún
# `tests/banco/test_banco_helpers_*.py` y comprueba su efecto con el lector.
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
        # counter (7)
        "ha_create_or_update_counter",
        "ha_increment_counter",
        "ha_decrement_counter",
        "ha_set_counter_value",
        "ha_reset_counter",
        "ha_reload_counters",
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

# Tool → motivo por el que no se puede ejecutar en el banco. Vacío: las 47 se
# ejecutan. Un motivo vacío no vale (lo comprueba el test del invariante).
NO_EJECUTABLES: dict[str, str] = {}
