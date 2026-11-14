# Quickstart: validar estado del sistema y estadísticas de Core (029)

Todo con la suite y el banco; nada contra una instalación real (las pruebas
en vivo quedan para después de publicar, como en el resto del programa).

## Requisitos previos

- La rama contiene la 009, la 010 y la 011 enteras (T001).
- `.venv` del checkout principal con las dependencias de desarrollo.

## Suite

```bash
export MSYS_NO_PATHCONV=1   # solo en Git Bash de Windows
HERMES_CONFIG_BASE=<carpeta temporal propia> python -m pytest -q -p no:cacheprovider
```

Ficheros nuevos que deben pasar: `tests/test_ha_ws_collect_subscription.py`,
`tests/test_tools_system_status.py`, `tests/test_tools_recorder_status.py`;
y los cambios en `tests/test_tools_generic_commands.py`,
`tests/test_command_table.py`, `tests/test_generar_tabla.py` (si no los hizo
la 012), `tests/test_tool_families.py`, `tests/test_tools_registration.py`,
`tests/test_tools_guide.py` y `tests/test_banco_cobertura.py`. Resultado
esperado en Windows: solo los 6 fallos conocidos.

## Banco de Core

Lo ejecuta el job `banco-core` del CI (`-m banco`) con
`tests/banco/test_banco_estado_sistema.py` y `tests/banco/test_banco_recorder.py`.
Esperado: las ocho tools y las cuatro entradas `read` de CAP-058 y CAP-068
responden contra HA Core 2026.11.1 real (contrato en
[contracts/tools.md](contracts/tools.md)); lo que el banco no pueda ejecutar
queda anotado en el test con su motivo.

## Tabla

```bash
python scripts/inventario/generar_tabla.py
git diff -- hermes/src/hermes/command_table.py   # vacío
```

Ninguna entrada con «(spec 029)» y las nueve de data-model en `dedicated`.

## Comprobaciones a mano

- `hermes_guide(topic="system_status")` y `hermes_guide(topic="recorder")`
  dicen lo que hacen las tools y cómo leer la auditoría, la red y el HTTP.
- Con `tool_families_disabled: [system_status, recorder]` en un entorno de
  desarrollo, `tools/list` no tiene ninguna de las ocho (lo cubre también un
  test).

## Pendiente manual (tras publicar)

En una instalación real con Supervisor y nube: la salud con los dominios
`cloud`, `hassio` y `recorder` completos o con pendientes; el estado con un
reinicio pendiente tras instalar una integración; la validación con
estadísticas que tienen problemas. Se anota en la matriz de entornos de la
hoja de ruta (014).
