"""Inventario de las tools de la spec 021 en el banco de Core.

Contrato de la 028 («Regla para las sub-features siguientes»): cada tool
nueva que modifica se ejecuta en el banco y va en `PROBADAS_021`, o en
`NO_EJECUTABLES_021` con un motivo concreto. Las dos listas se suman a la
unión de `tests/test_banco_cobertura_escrituras.py`, y `PROBADAS_021 |
LECTURAS_021` a lo que el job exige por ejecución
(`cobertura_escrituras.TOOLS_EXIGIDAS_DEL_JOB`).

Tramo a (núcleo y exposición a asistentes), en
`tests/banco/test_banco_configuracion_sistema.py`: las tres que escriben y
las dos de lectura. Las de lectura no modifican (`readOnlyHint`) y no entran
en el invariante de escrituras, pero el job también las exige por ejecución
(como las de la 029). Tramo b (usuarios), en `tests/banco/test_banco_usuarios.py`:
las tres que escriben y la lista. Tramo c (red y HTTP), en
`tests/banco/test_banco_red_http.py`: `ha_update_network_config` se ejecuta
con efecto; las dos de HTTP solo con su vista previa y su rechazo real,
porque aplicarlas reiniciaría la HA del banco (research R-8). La vista previa
de `ha_update_http_config` también se exige por ejecución (`VISTA_PREVIA_021`).
"""

from __future__ import annotations

PROBADAS_021: frozenset[str] = frozenset({
    "ha_update_core_config",
    "ha_set_entity_exposure",
    "ha_set_expose_new_entities",
    # Tramo b (usuarios), en `tests/banco/test_banco_usuarios.py`.
    "ha_create_user",
    "ha_update_user",
    "ha_delete_user",
    # Tramo c (red), en `tests/banco/test_banco_red_http.py`.
    "ha_update_network_config",
})

# Research R-8: confirmar `http/config/configure` guarda una pendiente y
# reinicia Core (el job perdería su HA a mitad de sesión), y promover exige
# una pendiente con la que HA ya haya arrancado, es decir, ese reinicio. En el
# banco se prueban su vista previa (fundida sobre el `http/config` real, sin
# cambiarlo) y su rechazo real (`nothing_to_promote`). La confirmación va a
# la VM (matriz de la 014, `VM | pendiente`).
_MOTIVO_HTTP = ("aplicarla reinicia Home Assistant (la del banco se perdería a "
                "mitad del job); en el banco solo su vista previa y su rechazo "
                "real; la confirmación, en la VM (research R-8 de la 021)")
NO_EJECUTABLES_021: dict[str, str] = {
    "ha_update_http_config": _MOTIVO_HTTP,
    "ha_promote_http_config": _MOTIVO_HTTP,
}

# Las de `NO_EJECUTABLES_021` que el job exige igualmente llamar con éxito en
# un test que pasa: la vista previa de `ha_update_http_config`. La de
# `ha_promote_http_config` en el banco solo puede ser su rechazo real
# (`nothing_to_promote`), y un rechazo no cuenta como llamada con éxito
# (`entorno.rechazo`); su test lo comprueba igual.
VISTA_PREVIA_021: frozenset[str] = frozenset({"ha_update_http_config"})

LECTURAS_021: frozenset[str] = frozenset({
    "ha_get_core_config",
    "ha_list_exposed_entities",
    "ha_list_users",
})
