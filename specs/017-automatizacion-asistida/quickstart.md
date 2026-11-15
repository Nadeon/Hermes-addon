# Quickstart: automatización asistida (017)

Cómo comprobar la sub-feature al cerrar cada tramo. Sin la instalación real y
sin llamar a las tools MCP de Hermes: todo es suite, generador y banco del CI.

## Suite local (Windows, Git Bash)

```bash
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" \
  /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

Resultado esperado: los 6 fallos conocidos de Windows y nada más. Los
ficheros de esta sub-feature, por separado:

```bash
python -m pytest -q -p no:cacheprovider \
  tests/test_tools_blueprints.py tests/test_tools_device_automation.py \
  tests/test_tools_targets.py tests/test_tools_wait_for_trigger.py \
  tests/test_ha_ws_subscribe_queue.py tests/test_tools_validacion_al_guardar.py \
  tests/test_tool_families.py tests/test_tools_registration.py \
  tests/test_command_table.py tests/test_generar_tabla.py \
  tests/test_tools_generic_commands.py tests/test_tools_guide.py \
  tests/test_banco_cobertura_escrituras.py tests/test_matriz_pruebas.py
```

## Tabla idéntica al regenerar

```bash
python scripts/inventario/generar_tabla.py
git diff --exit-code -- hermes/src/hermes/command_table.py
```

Sin diferencias. `grep "spec 017" hermes/src/hermes/command_table.py` no
devuelve nada al cerrar el tramo D.

## Banco de Core (CI)

El job `banco-core` de `.github/workflows/tests.yml` ejecuta
`tests/banco/test_banco_blueprints.py` y
`tests/banco/test_banco_automatizacion_asistida.py` contra HA 2026.11.1 sin
salida a internet. La importación usa el blueprint de
`tests/banco/ha_config/www/hermes_banco/` que la propia HA sirve en
`http://127.0.0.1:8123/local/hermes_banco/luz_por_movimiento.yaml`. El plugin
del job exige que `ha_save_blueprint`, `ha_delete_blueprint` y
`ha_import_blueprint` se hayan llamado con éxito en un test que pasa.

## Recorrido manual de una importación (cliente MCP contra una HA de pruebas)

Solo en una instalación de pruebas, nunca en la del mantenedor sin su permiso:

1. `ha_import_blueprint(url="https://github.com/<repo>/blob/<rama>/<fichero>.yaml")`
   → vista previa: `importer: github`, `path`, `content` entero,
   `content_sha256`, `_third_party_text`.
2. Leer el YAML y enseñárselo al usuario. Repetir la llamada con
   `confirmation_token`.
3. `ha_list_blueprints(domain="automation")` lo lista con `source_url`.
4. `ha_delete_blueprint` → vista previa o `blueprint_in_use`.

Es la prueba pendiente de los importadores con internet (GitHub, gist, foro):
anotarla en la matriz de pruebas de `docs/HOJA-DE-RUTA.md` al hacerla.
