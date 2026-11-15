# Quickstart: validar el diagnóstico de Core (012)

Todo con la suite y el banco; nada contra una instalación real (las pruebas en
vivo quedan para después de publicar, como en el resto del programa).

## Suite

```bash
export MSYS_NO_PATHCONV=1   # solo en Git Bash de Windows
HERMES_CONFIG_BASE=<carpeta temporal propia> python -m pytest -q -p no:cacheprovider
```

Ficheros nuevos que deben pasar: `tests/test_ha_rest_text_tail.py`,
`tests/test_tools_core_logs.py`, `tests/test_tools_core_validation.py`,
`tests/test_tools_integration_diagnostics.py`,
`tests/test_tools_persistent_notifications.py` y, si la 028 no está
integrada, `tests/test_banco_cobertura_012.py`; y los cambios en
`tests/test_tool_families.py`, `tests/test_tools_registration.py`,
`tests/test_command_table.py`, `tests/test_generar_tabla.py`,
`tests/test_tools_generic_commands.py` y `tests/test_tools_guide.py`.

Esperado en Windows: exactamente los 6 fallos conocidos. Los tests de
`tests/banco/` aparecen saltados sin `HERMES_BANCO_HA_URL`.

## Tabla

```bash
python scripts/inventario/generar_tabla.py
git diff --exit-code -- hermes/src/hermes/command_table.py   # sin cambios
```

## Banco

Como en el quickstart de la 010 (contenedor de HA Core 2026.11.1 con la
configuración de `tests/banco/ha_config/`, que ya incluye `system_log:` y
`diagnostics:`):

```bash
HERMES_BANCO_HA_URL=http://127.0.0.1:8123 HERMES_BANCO_OBLIGATORIO=1 \
  python -m pytest -m banco tests/banco/test_banco_core_logs.py \
  tests/banco/test_banco_core_diagnostico.py -q -p no:cacheprovider
```

En el CI, el job del banco de la rama tiene que quedar en verde.

## Comprobaciones manuales (después de publicar; a la matriz de la 014)

- En HA OS real, `ha_get_error_log` devuelve `error_log_unavailable` con
  `duplicate_log_file` desactivado y líneas con la opción activada.
- `ha_get_device_diagnostics` con un dispositivo de una integración que tenga
  diagnóstico de dispositivo (Z-Wave, ZHA, Matter, MQTT…).
- `ha_set_log_level` con `persistence="once"` y `"permanent"` sobrevive a un
  reinicio como dice la vista previa.
