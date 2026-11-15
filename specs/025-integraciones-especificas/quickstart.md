# Guía rápida: comprobar la 025

## Con tests (sin HA)

```bash
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" python -m pytest -q -p no:cacheprovider \
  tests/test_command_table_clase_c.py \
  tests/test_tools_generic_commands_clase_c.py \
  tests/test_command_table.py \
  tests/test_generar_tabla.py \
  tests/test_tools_guide.py
```

Qué demuestra cada uno:

| Test | Comprueba |
|---|---|
| `test_command_table_clase_c.py` | la categoría y las marcas de cada comando de clase C revisado; que ninguno dice «spec 025»; motivos concretos; nada del proxy del Supervisor |
| `test_tools_generic_commands_clase_c.py` | lecturas, `one_shot`, dos pasos y rechazos por las genéricas; los siete centinelas; la redacción de valor entero |
| `test_command_table.py` | excepciones de verbos, mundo abierto, deriva, estructura |
| `test_generar_tabla.py` | desde cero = tabla en las filas de clase C; la fila C nueva entra «sin revisar» |
| `test_tools_guide.py` | los cuatro temas, sus alias, el cruce con la tabla y las huellas de los demás |

## Regenerar la tabla

```bash
python scripts/inventario/generar_tabla.py
git diff --stat hermes/src/hermes/command_table.py   # sin cambios
```

En su sitio, la tabla no cambia (conserva cada entrada byte a byte). Desde
cero lo comprueba `test_desde_cero_clase_c_igual_que_la_tabla`; para verlo a
mano, generar con `--salida` a un temporal y comparar las filas de clase C.

## Con una versión nueva de HA

1. Regenerar los inventarios y la tabla (quickstart de la 011).
2. Las filas C nuevas entran `deny` «sin revisar»: leer su handler,
   clasificarlas en la tabla Y en `scripts/inventario/clase_c.py`, y añadirlas
   a research.md R-1 o a la research de la sub-feature que las revise.
3. Las filas C que siguen pero cuyo handler cambió (diff de
   `homeassistant/components/<integración>/` entre versiones): volver a leer
   el handler; una lectura que empiece a escribir, o una respuesta que empiece
   a llevar un secreto, se reclasifica.

## En una instalación real (prueba manual tras publicar)

Solo con hardware (Z-Wave, Zigbee, Matter/Thread): pedir a un cliente MCP
«estado de la red Z-Wave», «parámetros del nodo X», «dispositivos Zigbee» y
«ajustes de la red Zigbee», y comprobar que las claves salen
`***REDACTED***`. Va a «Pruebas manuales pendientes» de `docs/HOJA-DE-RUTA.md`
(sin tools nuevas, no hay filas en la matriz de la 014).
