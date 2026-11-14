# Quickstart: validar la política de comandos (011)

Todo con la suite; nada contra una instalación real (las pruebas en vivo
quedan para después de publicar, como en el resto del programa).

## Suite

```bash
export MSYS_NO_PATHCONV=1   # solo en Git Bash de Windows
HERMES_CONFIG_BASE=<carpeta temporal propia> python -m pytest -q -p no:cacheprovider
```

Ficheros nuevos que deben pasar: `tests/test_command_inventory.py`,
`tests/test_command_policy.py`, `tests/test_command_table.py`,
`tests/test_generar_tabla.py`, `tests/test_tool_families.py`,
`tests/test_tools_generic_commands.py`, `tests/test_extractor_inventario.py`,
y los cambios en `tests/test_tools_registration.py`,
`tests/test_tools_guide.py`, `tests/test_config_validation.py`,
`tests/test_run_sh_options.py` y `tests/test_addon_manifest.py`.

## Regenerar con una versión nueva de HA (mantenedor)

1. Descargar el código de Core y del Supervisor de la versión nueva a una
   carpeta local (solo se lee; nunca se ejecuta ni se importa).
2. `python scripts/inventario/extraer.py --core <ruta> --supervisor <ruta>`:
   reescribe los dos TSV de `specs/008-cobertura-total/inventario/`
   conservando las columnas revisadas; las filas nuevas salen sin clase.
3. Clasificar a mano las filas nuevas del inventario (clase, nota, CAP).
4. `python scripts/inventario/generar_tabla.py`: añade a
   `hermes/src/hermes/command_table.py` las filas nuevas como `deny` «sin
   revisar» y quita las desaparecidas; imprime las dos listas.
5. Ejecutar la suite: `test_command_table.py` falla nombrando lo «sin revisar»
   y lo que no cuadra. Clasificar cada entrada en la tabla (y, si tiene tool
   dedicada, `dedicated`).
6. Subir `TABLE_HA_CORE`/`TABLE_SUPERVISOR` con `HA_CORE_LAST_TESTED`.

## Comprobaciones manuales del tramo 3

- Ejecutar el extractor contra el código de Core 2026.11.1 y del Supervisor
  2026.11.0 y comprobar que el diff de los dos TSV es vacío (o solo la
  normalización ya hecha en el tramo 1). Anotarlo en el commit.
- Con `tool_families_disabled: [generic_commands]` en un entorno de desarrollo,
  `tools/list` devuelve las 216 tools de la 1.1.2 (lo cubre también un test).
