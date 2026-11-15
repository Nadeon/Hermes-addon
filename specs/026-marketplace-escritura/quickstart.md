# Quickstart: escritura en el Marketplace (026)

Cómo se comprueba cada tramo. Desde la raíz del worktree, en Git Bash:

```bash
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta-temporal-propia>)" \
  /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

Línea base (punta `f108af0`, Windows): 3955 passed, 133 skipped, 6 failed (los
6 conocidos). Al cerrar cada tramo: los mismos 6 fallos y ninguno más.

## Tramo 1

```bash
python -m pytest -q -p no:cacheprovider \
  tests/test_marketplace_write_comun.py tests/test_tools_marketplace_manage.py \
  tests/test_command_table.py tests/test_generar_tabla.py \
  tests/test_tools_registration.py tests/test_tool_families.py \
  tests/test_tools_guide.py tests/test_confirmation_args_inventory.py \
  tests/test_banco_cobertura_escrituras.py tests/test_matriz_pruebas.py
grep -c "spec 026" hermes/src/hermes/command_table.py   # 4
python scripts/inventario/generar_tabla.py && git diff --exit-code hermes/src/hermes/command_table.py
```

Banco (CI): `tests/banco/test_banco_marketplace.py` reconoce el crítico
sembrado y el lector ve `acknowledged: true`; el contrato de las seis cargas
del tramo 1 recibe errores del manejador, nunca `invalid_format` ni
`unknown_command`.

## Tramo 2

```bash
python -m pytest -q -p no:cacheprovider \
  tests/test_marketplace_write_comun.py tests/test_tools_marketplace_install.py \
  tests/test_tools_marketplace.py tests/test_tools_hacs.py \
  tests/test_command_table.py tests/test_generar_tabla.py \
  tests/test_tools_registration.py tests/test_tools_guide.py \
  tests/test_confirmation_args_inventory.py tests/test_matriz_pruebas.py
grep -c "spec 026" hermes/src/hermes/command_table.py   # 0
```

## En vivo (pendiente, tras publicar)

Con internet y el Marketplace configurado: desinstalar un repositorio de
prueba (con backup), quitar uno personalizado, refrescar, ignorar un retirado,
reconocer un crítico si lo hay, y comprobar que instalar responde
`marketplace_warning_not_accepted` (research R-2).
