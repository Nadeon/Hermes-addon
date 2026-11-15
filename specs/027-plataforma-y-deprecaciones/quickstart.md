# Comprobación rápida: plataforma y deprecaciones (027)

Todo se comprueba con la suite (sin tocar ninguna instalación real). Desde la
raíz del worktree, en Git Bash:

```
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta temporal propia>)" <python del .venv> -m pytest -q -p no:cacheprovider \
  tests/test_supervisor_jobs.py tests/test_supervisor_platform.py \
  tests/test_deprecaciones.py tests/test_translations.py \
  tests/test_sdk_deprecaciones.py tests/test_tools_supervisor.py \
  tests/test_tools_registry_device.py tests/test_tools_guide.py \
  tests/test_main_wiring.py tests/test_tools_registration.py
```

Qué mirar:

1. **Jobs** (`tests/test_supervisor_jobs.py` y `tests/test_tools_supervisor.py`,
   `TestJobStatusSubJobs`): un job
   con error en un sub-job da `success: false` y `child_errors` con ese error
   (D-1); un centinela en el mensaje sale tapado; y el sondeo del safety
   backup (`TestSondeoSubJobs`) rechaza la escritura.
2. **Plataforma** (`tests/test_supervisor_platform.py`): las cuatro
   combinaciones de socket y `/v2`, y los fallos de `/supervisor/info`, dan el
   evento correcto; la URL base del cliente no cambia y ninguna petición va a
   `/v2`.
3. **Deprecaciones** (`tests/test_deprecaciones.py`): los cinco nombres
   deprecados siguen registrados con sus anotaciones; `unknown_command` da
   `command_removed_in_ha`; dispositivos sin `config_entries` ni
   `primary_config_entry` cuentan igual.
4. **Traducciones** (`tests/test_translations.py`): claves iguales a las del
   esquema en los dos idiomas, forma del Supervisor, sin «add-on».
5. **SDK** (`tests/test_sdk_deprecaciones.py`): ningún aviso deprecado de
   `mcp`/`mcp_types` al registrar todas las tools; solo `ping` y
   `hermes_guide` declaran `outputSchema`; `mcp<3` en `requirements.txt`.
6. **Tabla**: regenerar con `scripts/inventario/generar_tabla.py` y comprobar
   que `git diff hermes/src/hermes/command_table.py` sale vacío.

En una instalación real (opcional, manual, lo hace el mantenedor): tras
actualizar, el log del add-on tiene una línea `supervisor_platform` con
`transport: tcp`, `unix_socket_offered: false`, `api_v2_enabled: false`, y la
página de configuración de Hermes enseña nombres y descripciones traducidos.
