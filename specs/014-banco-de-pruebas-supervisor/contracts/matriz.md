# Contrato: matriz de pruebas en la hoja de ruta (spec 014, FR-002 a FR-004)

Es el contrato entre la hoja de ruta y el resto del programa: qué tiene que
hacer quien añade, quita o prueba una tool que modifica para que el CI siga en
verde.

## Ubicación y formato

En `docs/HOJA-DE-RUTA.md`, dentro de «Programa de cobertura total (spec 008)»,
una subsección `#### Matriz de pruebas: tool → entorno → resultado (014)` con
un párrafo que explica entornos y resultados, enlaza
[`docs/BANCO-SUPERVISOR.md`](../../../docs/BANCO-SUPERVISOR.md) y dice que los
simuladores de la suite normal corren siempre para todas. Después:

```markdown
<!-- matriz-pruebas:inicio -->
| Tool | Entorno | Resultado | Nota |
|---|---|---|---|
| `fs_delete_file` | VM | pendiente | |
| `ha_create_or_update_input_boolean` | banco de Core | ok | |
| `ha_reload_counters` | banco de Core | falla | `counter.reload` no existe en Core 2026.11.1 (spec 033) |
| `sv_reboot_host` | VM | pendiente | instantánea antes |
<!-- matriz-pruebas:fin -->
```

- Filas en orden alfabético de tool (diffs de una línea).
- Una fila por tool; la celda Tool lleva exactamente un nombre entre comillas
  invertidas.
- Celdas Entorno y Resultado en minúsculas, con los valores exactos de
  [data-model.md](../data-model.md).
- La nota no puede contener `|`.

## Test `tests/test_matriz_pruebas.py` (suite normal)

Sin HA, Docker ni red; corre en Windows y en Linux.

| Test | Comprueba | Falla nombrando |
|---|---|---|
| `test_marcadores_y_cabecera` | un solo par de marcadores, en orden, y la cabecera exacta | lo que falta |
| `test_filas_bien_formadas` | cuatro celdas, tool entre comillas, valores del vocabulario | la línea |
| `test_sin_repetidas` | ninguna tool dos veces | las repetidas |
| `test_una_fila_por_tool_que_modifica` | filas == tools sin `readOnlyHint` del registro de producción | las que faltan y las que sobran |
| `test_sv_y_fs_en_la_vm` | toda `sv_*`/`fs_*` de la matriz tiene `VM` | las que no |
| `test_coherente_con_los_inventarios` | reglas de data-model (probadas, fallan, no ejecutables, fuera del banco) | tool, regla y módulo del inventario |
| `test_ok_en_banco_solo_si_probada` | `banco de Core`+`ok` ⇒ en algún `PROBADAS*` | las que no |
| `test_notas_obligatorias` | `falla` con nota; `ok` en `VM`/`instalación real` con versión (`\d+\.\d+\.\d+`) y fecha (`AAAA-MM-DD`) | las que no |
| `test_inventarios_descubiertos` | al menos `tests/banco/cobertura.py`; tipos según la convención | el módulo y la constante |
| `test_hoja_de_ruta_enlaza_el_procedimiento` | enlace a `docs/BANCO-SUPERVISOR.md` y el fichero existe | — |
| `test_casillas_manuales` | en «Pruebas manuales pendientes», una casilla (`- [ ]` o `- [x]`) que contiene cada clave de la lista de abajo, y la de `hassio_role: manager` sin `bashio::config` | la clave que falta |
| `test_procedimiento_con_sus_secciones` | encabezados obligatorios de [procedimiento.md](procedimiento.md) | los que faltan |
| `test_cada_tool_de_la_vm_en_el_procedimiento` | toda tool con entorno `VM` aparece entre comillas invertidas en la sección «Tandas de pruebas» del procedimiento | las que faltan |

Claves de `test_casillas_manuales` (texto que tiene que aparecer en alguna
casilla; SC-011 de la 008 y CAP-035): `Matriz del Supervisor`,
`hassio_role: manager`, `tras publicar`, `sv_get_resolution`, `CIMD con Claude
Code`, `Primer byte tras el proxy`, `Clave \`homeassistant\``, `Funnel en el
8443`, `fs_write_file`, `trazas de un script`. Y cada casilla empieza, tras
la marca, por su entorno entre paréntesis.

Definición de «modifica»: como la 028,
`_build_mcp(HermesConfig(call_service_auto_classify_dangerous=False), MagicMock())._tool_manager.list_tools()`
con `annotations.read_only_hint` falso.

## Regla para las sub-features siguientes

Una sub-feature que añade una tool que modifica añade también su fila:

1. De Core: `banco de Core`, y `ok` en cuanto su inventario
   (`tests/banco/cobertura_<NNN>.py`) la lista como probada.
2. Del Supervisor o de ficheros: `VM` y `pendiente`; y su apartado en
   `docs/BANCO-SUPERVISOR.md` (qué comprobar).
3. Quien ejecute una prueba en la VM o en vivo cambia `pendiente` por `ok` o
   `falla` con la nota que exige el test.

Si no lo hace, el test cae en su rama nombrando la tool.
