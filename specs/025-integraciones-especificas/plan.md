# Plan de implementación: integraciones específicas por la tabla (025)

**Rama**: `feat/025-integraciones-especificas` (ya creada desde `feat/cobertura-total`, `806a764`) | **Fecha**: 2026-11-15 | **Spec**: [spec.md](spec.md) | **Programa**: [008](../008-cobertura-total/plan.md), sub-feature 025, ola 3

## Resumen

Los 192 comandos de clase C (integraciones concretas, CAP-100…CAP-106), hoy
todos `deny` «pendiente de revisión (spec 025)», se clasifican uno a uno con
el handler de HA leído: **73 `read`, 57 `confirm`, 62 `deny`** (research.md,
R-1). Sin tools ni familias nuevas: todo va por `ha_read_ws_command` y
`ha_call_ws_command`. Tres piezas de mecanismo: (1) `redact_extra` tapa el
valor entero aunque sea un objeto o una lista (hallazgo H-1; necesario para las
claves de red de ZHA); (2) un mapa revisado de la clase C para que el
generador dé desde cero la misma tabla; (3) los tests de clasificación,
centinelas y «ninguna pendiente de la 025». Cuatro temas nuevos en la guía.
Tres tramos: Z-Wave JS con el mecanismo; ZHA, Matter y Thread; el resto y el
cierre.

## Dependencias y momento de la implementación

La rama sale de `feat/cobertura-total` en `806a764`, que ya tiene la 009, la
010, la 011 entera, la 033 y la 017 (307 tools). No depende de ninguna otra
sub-feature en curso. Comparte ficheros con las que estén en paralelo en la
ola 3 (`command_table.py`, `test_command_table.py`, `generar_tabla.py`,
`test_generar_tabla.py`, `guide.py`, `test_tools_guide.py`, CHANGELOG, hoja
de ruta): las líneas de la clase C no las toca nadie más; el resto son
añadidos en sitios distintos y se resuelven conservando los de las dos.

Línea base en Windows al especificar (2026-11-15, `806a764`): **3835 passed,
126 skipped, 6 failed** (los 6 conocidos).

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: ninguna nueva · **Almacenamiento**: ninguno · **Tests**: pytest con `unittest`, `AsyncMock` de `ws_send` y `ws_one_shot_subscription`, `structlog.testing.capture_logs`, generación de la tabla en un temporal (como `test_generar_tabla.py`); banco de Core de la 010 para `usb` · **Plataforma**: add-on de HA OS.

**Restricciones**: fail-closed (III); motivos y guía que no mienten (V);
ningún `hassio/*` ni `supervisor/*` en `read`/`confirm` (proxy del
Supervisor; ninguno es de clase C); FR-020 de la 008 (nada de lo actual
cambia: la única entrada con `redact_extra` hoy recibe escalares).

**Escala**: 192 entradas de la tabla (130 a `read`/`confirm`, 62 con motivo
concreto de `deny`), 1 módulo de datos del generador, 1 cambio de 3 líneas en
`_redactar`, 4 temas de guía, 0 tools.

## Comprobación de la constitución

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Nada que destruya la red, toque firmware, necesite una acción física o un PIN, o no tenga vista previa posible (`invoke_cc_api`) pasa de `deny`. Lo que escribe va en dos pasos con la vista previa de la 011. La genérica sigue rechazando sin llamar a HA. | OK |
| II. Secretos | Lo que devuelve claves de red, DSK, códigos de emparejamiento, tokens o la clave de ESPHome es `deny`; lo que solo las lleva en parte se tapa (`redact_extra` de valor entero, R-5) con centinela de extremo a extremo (respuesta y log). Lo que introduce credenciales es `deny`. | OK |
| III. Fail-closed | Cada entrada se clasifica a mano; lo no revisado sigue `deny`. Una fila C nueva de otra versión entra `deny` «sin revisar» y el test la nombra. Las suscripciones dudosas, `deny`. | OK |
| IV. Dos pasos, token atado | Las 57 `confirm` usan el mecanismo de la 011 (token atado al comando y la carga). Sin tools nuevas: el inventario de argumentos atados no cambia. | OK |
| V. Nombre y descripción | Cada motivo dice lo que hace el comando o por qué se rechaza, incluidos los efectos no evidentes (`network_neighbors` apaga la radio; `dynalite/save-config` reemplaza todo). Las genéricas ya se anuncian de mundo abierto; `TestMundoAbierto` incluye `zwave_js/check_for_config_updates`. La guía solo cita como disponible lo que la tabla permite (test). | OK |
| VI. Lo que no se puede probar | Sin hardware, el banco no carga estas integraciones; `usb` se intenta en el banco. Todo lo demás, unitario con respuestas reales tomadas del código de HA; anotado en la matriz de la 008. | OK |
| VII. Control negativo | Uno por mecanismo: redacción de valor entero, mapa del generador, test de «pendiente», centinelas, `one_shot`, cruce guía-tabla. Anotados en el test o en el commit. | OK |
| VIII. Privacidad | IEEE, `device_id`, `entry_id` y claves ficticias (`00:11:22:33:44:55:66:77`, `<device_id>`, `centinela-025`); revisión del diff en cada cierre de tramo. | OK |
| IX. Cambios mínimos | Sin tools ni familias. El cambio de `_redactar` es el mínimo para tapar objetos de `redact_extra`; `redact_structure` no se toca (D-2). Los temas existentes no cambian. | OK |
| X. Comentarios en español | Motivos, comentarios y guía en español, como el resto de la tabla. | OK |
| XI. Versionado | Sin subir versión; sección propia en `## [1.2.0]`. | OK |
| Flujo, puerta 4 | Suite, banco, Semgrep y CodeQL en verde en el CI al cerrar cada tramo. | OK |

Tras el diseño: sin cambios. Desviaciones respecto a las notas de CAP de la
008, justificadas en research.md R-3 (FR-089 manda).

## Diseño

### Mecanismo (tramo 1)

1. **Redacción de valor entero** (`tools/generic_commands.py`, `_redactar`):
   antes de recorrer un `Mapping` o una lista, si `clave.lower()` está en
   `extra`, devolver `REDACTED_MARKER` (el objeto o la lista enteros). Los
   escalares siguen como hoy: texto no vacío y cualquier otro valor distinto
   de `None`, tapados; la cadena vacía y `None`, tal cual. Se actualiza
   el comentario del campo `redact_extra` de `Entrada` en `command_policy.py`
   («tapa su valor entero, sea del tipo que sea»). FR-008.
2. **Mapa revisado** (`scripts/inventario/clase_c.py`, nuevo): `CLASE_C:
   dict[str, dict[str, object]]`, una entrada por línea y en orden de clave,
   con `category`, `reason` y las marcas que tenga. `generar_tabla.py`
   importa `CLASE_C` y la rama `if clase == "C"` de `_clasificar` hace
   `if clave in CLASE_C: return {**base, **CLASE_C[clave]}`; si no, `deny`
   «pendiente de revisión (spec 025)» (tramos 1 y 2) o «sin revisar»
   (tramo 3). La docstring del generador cambia la viñeta de la clase C.
   FR-012.
3. **Tests de la tabla** (`tests/test_command_table_clase_c.py`, nuevo):
   - `_ESPERADO: dict[str, tuple[str, dict]]` por integración (comando →
     categoría y marcas), escrito a mano desde R-1, y `_REVISADAS`, el
     conjunto de prefijos ya revisados (`zwave_js/` en el tramo 1; se suma
     ZHA, Matter, Thread y OTBR en el 2; todos en el 3).
   - `test_clasificacion`: para cada comando de `_ESPERADO` de una
     integración revisada, la tabla tiene esa categoría y esas marcas
     (`one_shot`, `redact_extra`, `open_world`, `example is not None`), con
     subtest por comando (cada `read`/`confirm` nombrado; FR-009).
   - `test_ninguna_pendiente_de_la_025`: ninguna entrada de una integración
     revisada dice «spec 025»; en el tramo 3, ninguna en toda la tabla, sin
     filtro (FR-011).
   - `test_motivos_concretos`: ningún motivo de clase C revisada contiene
     «pendiente» ni «sin revisar», y ninguno de `read` dice que escribe.
   - `test_ningun_proxy`: ninguna entrada `hassio/*` o `supervisor/*` de
     clase C en `read`/`confirm` (redundante con `TestProxyDelSupervisor`,
     pero nombra la regla de la 025).
   - `test_esperado_completo`: cada fila C del inventario de un prefijo
     revisado está en `_ESPERADO`, y al revés.
4. **Tests existentes que cambian** (`tests/test_command_table.py`):
   `test_clase_c_pendiente_de_la_025` pasa a exigir «pendiente» solo en las
   integraciones NO revisadas (tramos 1 y 2) y se borra en el tramo 3 (lo
   sustituye `test_ninguna_pendiente_de_la_025`); `_EXCEPCIONES_VERBOS` gana
   las tres lecturas `zwave_js/*firmware_update*` con su justificación (y un
   comentario encima de cada entrada en la tabla); `_READ_QUE_SALEN` gana
   `zwave_js/check_for_config_updates`. FR-010, FR-015.
5. **Generador** (`tests/test_generar_tabla.py`): `test_clase_c` sigue con la
   fila `demo/radio/reset` del fixture (no está en el mapa → `deny`); un
   test nuevo con `mock.patch.dict(gt.CLASE_C, {...})` comprueba que una fila
   C del mapa sale con sus marcas; `test_desde_cero_clase_c_igual_que_la_tabla`
   genera desde cero con los inventarios reales y compara las filas C de las
   integraciones revisadas (todas en el tramo 3) en `category`, `reason`,
   `family`, `tool`, `cap`, `one_shot`, `redact_extra`, `open_world` y
   `example`, y que el recuento de filas comparadas no baja.

### Ejecución por las genéricas (todos los tramos)

`tests/test_tools_generic_commands_clase_c.py` (nuevo), con el `DummyMCP` y
los `AsyncMock` de `tests/test_tools_generic_commands.py`:

- por integración, una lectura que llega a `ws_send` con `{"type": …,
  **carga}`; una `confirm` que sin token devuelve `preview` y
  `confirmation_token` sin llamar a HA y con token llama una vez; una `deny`
  de cada grupo de motivos que se rechaza con `command_denied` sin llamar a
  HA por ninguna de las dos genéricas;
- cada `one_shot` llega a `ws_one_shot_subscription`, nunca a `ws_send`;
- los siete centinelas de R-6, respuesta y log;
- la redacción de valor entero (FR-008), con control negativo.

Las respuestas simuladas copian la forma que construye el handler de HA
leído (p. ej. `zha/network/settings` → `{"radio_type", "device",
"settings": {"network_info": {"network_key": {"key": …}, …}, "node_info":
…}}`).

### Guía (tramos 1, 2 y 3)

Temas `zwave` (tramo 1), `zigbee` y `matter_thread` (tramo 2) y
`other_integrations` (tramo 3), con el contenido de research.md R-7, alias,
una línea cada uno en `_OVERVIEW` y su nombre en la docstring de
`hermes_guide`. `tests/test_tools_guide.py`, clase `TestTemasDeIntegraciones`:
el tema y sus alias existen; nombra sus comandos clave; cruce con la tabla
(un comando entre comillas invertidas en la sección de disponibles está en
`read`/`confirm`; en la de rechazados, en `deny`); los temas existentes no
cambian (`test_sin_search_los_temas_de_la_1_1_2_no_cambian` y las huellas
siguen en verde sin tocarlas). Las secciones de cada tema llevan títulos
fijos («POR LA GENÉRICA», «RECHAZADO», «OTRA VÍA») para que el cruce sepa
dónde mirar.

### Banco (tramo 3)

`usb:` en `tests/banco/ha_config/configuration.yaml` y
`tests/banco/test_banco_integraciones_c.py` con `usb/list_serial_ports` y
`usb/list_serial_integrations` por `ha_read_ws_command` (comprueba una lista,
sin exigir puertos). Si `usb` no arranca en el contenedor, `xfail` estricto
con el fallo concreto (hallazgo), anotado en la matriz.

## Estructura de ficheros

```text
hermes/src/hermes/
├── command_table.py              # 192 entradas de clase C (tramos 1–3)
├── command_policy.py             # comentario de `redact_extra` (tramo 1)
└── tools/
    ├── generic_commands.py       # `_redactar`: valor entero (tramo 1)
    └── guide.py                  # 4 temas, alias, índice, docstring (1–3)
scripts/inventario/
├── clase_c.py                    # NUEVO: mapa revisado (tramos 1–3)
└── generar_tabla.py              # rama de la clase C (tramos 1 y 3)
tests/
├── test_command_table_clase_c.py           # NUEVO (1–3)
├── test_tools_generic_commands_clase_c.py  # NUEVO (1–3)
├── test_command_table.py         # test de la 025, verbos, mundo abierto (1, 3)
├── test_generar_tabla.py         # mapa y desde cero (1–3)
├── test_tools_guide.py           # TestTemasDeIntegraciones (1–3)
└── banco/
    ├── ha_config/configuration.yaml        # `usb:` (3)
    └── test_banco_integraciones_c.py       # NUEVO (3)
hermes/CHANGELOG.md               # sección «Integraciones específicas» (1–3)
docs/HOJA-DE-RUTA.md              # estado de la 025 (1–3)
SECURITY.md                       # viñeta de las genéricas (3)
specs/008-cobertura-total/plan.md # matriz, filas CAP-100…CAP-106 (3)
```

## Trazabilidad

| FR (025) | FR (008) | CAP | Tareas | Test |
|---|---|---|---|---|
| FR-001 | FR-089, FR-019 | CAP-100 | T006, T007, T009, T010 | `test_command_table_clase_c.py`, `test_tools_generic_commands_clase_c.py` |
| FR-002 | FR-089, FR-019 | CAP-101 | T019, T020, T022 | ídem |
| FR-003 | FR-089, FR-019 | CAP-102 | T019, T020, T023 | ídem |
| FR-004 | FR-089, FR-019 | CAP-103 | T019, T020, T023 | ídem |
| FR-005 | FR-089 | CAP-104, CAP-105 | T031, T032, T034 | ídem |
| FR-006 | FR-089, FR-019 | CAP-106 | T031, T032, T035 | ídem |
| FR-007 | FR-089, FR-009 | CAP-100…CAP-106 | T006, T019, T031, T036 | `test_command_table_clase_c.py` (`test_motivos_concretos`) |
| FR-008 | FR-019, FR-020 | CAP-101 | T002, T003 | `test_tools_generic_commands_clase_c.py` (`TestRedaccionValorEntero`) |
| FR-009 | FR-019, FR-009 | CAP-100…CAP-106 | T007, T020, T032 | `test_tools_generic_commands_clase_c.py` |
| FR-010 | FR-004 | CAP-100 | T008, T011 | `test_command_table.py` (`TestVerbos`) |
| FR-011 | FR-002 | CAP-100…CAP-106 | T006, T019, T036 | `test_command_table_clase_c.py`, `test_command_table.py` |
| FR-012 | FR-001, FR-002, FR-005 | CAP-100…CAP-106 | T004, T005, T012, T024, T037 | `test_generar_tabla.py` |
| FR-013 | FR-090, FR-011 | CAP-100…CAP-106 | T013, T014, T025, T026, T038, T039 | `test_tools_guide.py` (`TestTemasDeIntegraciones`) |
| FR-014 | FR-011 | CAP-100…CAP-106 | T009, T021, T033 | `test_command_table_clase_c.py`, `test_tools_guide.py` |
| FR-015 | FR-010, FR-018, FR-020 | — | T008, T011 | `test_command_table.py` (`TestMundoAbierto`), `test_tools_registration.py` |
| FR-016 | FR-015 | CAP-105 | T040, T041 | `tests/banco/test_banco_integraciones_c.py` |
| FR-017 | FR-021, FR-023, FR-024 | — | T016, T028, T042, T043, T044 | revisión |

## Tramos

| Tramo | Tareas | Entradas | Guía | Otros |
|---|---|---|---|---|
| 1 — mecanismo y Z-Wave JS | T001–T017 | 55 (`zwave_js/*`) | `zwave` | redacción de valor entero, mapa del generador, tests nuevos, verbos y mundo abierto |
| 2 — ZHA, Matter, Thread y OTBR | T018–T029 | 50 | `zigbee`, `matter_thread` | centinelas de claves de red |
| 3 — resto y cierre | T030–T046 | 87 | `other_integrations` | banco de `usb`, test estricto, «sin revisar» en el generador, documentación y matriz |

Cada tramo cabe en el contexto de un agente: transcribir R-1 a la tabla y al
mapa es una línea por comando; los tests son tablas de datos; un tema de guía
por tramo (dos en el 2).

## Riesgos

- **Conflictos de integración** con otras sub-features de la ola 3 en los
  ficheros compartidos: las líneas de la clase C son solo de la 025; el
  resto, añadidos en sitios distintos.
- **La forma real de una respuesta difiere de la simulada** (sin hardware no
  se puede ver): los tests copian lo que construye el handler de HA; donde la
  forma la da una biblioteca externa (zigpy, python-matter-server), se tapa
  por la clave de arriba (`stack_specific` entero) para no depender del
  interior.
- **`usb` no arranca en el banco**: se anota como hallazgo y queda en
  unitarios.
- **Una versión nueva de HA cambia un handler** (p. ej. una lectura empieza a
  escribir): la tabla se regenera en su sitio y conserva la entrada; la
  revisión de la versión nueva (quickstart de la 011) debe volver a leer los
  handlers de la clase C que cambien. Anotado en el CHANGELOG.
