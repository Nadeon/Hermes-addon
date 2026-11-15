"""Inventario de la spec 024 en el banco de Core.

Tramo 1 (CAP-059): las dos tools de la familia `cameras` solo leen
(`readOnlyHint`), así que no entran en el invariante de escrituras de la 028;
tienen el suyo (`TestCoberturaDeLa024` en `tests/test_banco_cobertura.py`):
`LECTURAS_EN_BANCO_024` es EXACTAMENTE lo que registran los módulos de
`MODULOS_024`, cada nombre aparece en un `tests/banco/test_banco_*.py`, y el
job exige cada una por ejecución (se suma a `TOOLS_EXIGIDAS_DEL_JOB` en
`cobertura_escrituras.py`).

- `ha_get_camera_snapshot`: cámara `local_file` creada por el lector con el
  JPEG gris de `ha_config/www/hermes_banco/camara.jpg`
  (`tests/banco/test_banco_camaras.py`).
- `ha_get_image_entity`: `image.qr_code` de `kitchen_sink`, en el mismo
  fichero.

Las entradas de la tabla de CAP-059, 065, 066, 067 y 072 van por las
genéricas, que ya exige el job (`PROBADAS_GENERICAS`); su ejecución por CAP
está en `tests/banco/test_banco_menores_datos.py` (los tags, CAP-066, ya los
ejecuta la 011 en `test_banco_genericas.py`).

El tramo 2 añade el módulo `lovelace_reset` y `PROBADAS_024`.
"""

from __future__ import annotations

MODULOS_024: tuple[str, ...] = ("cameras",)

LECTURAS_EN_BANCO_024: frozenset[str] = frozenset({
    "ha_get_camera_snapshot",
    "ha_get_image_entity",
})
