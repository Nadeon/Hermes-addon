# Plan de implementación: automatización asistida (017)

**Rama**: `feat/017-automatizacion-asistida` (no se crea ninguna) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md) | **Programa**: [008](../008-cobertura-total/plan.md), sub-feature 017, ola 3

## Resumen

Catorce tools dedicadas nuevas en dos familias nuevas y un cambio en dos tools
existentes, para escribir automatizaciones con ayuda de Home Assistant:

- **Blueprints** (`blueprints`): listar, importar desde una URL (la descarga la
  hace HA; la vista previa enseña el YAML entero y su huella, como texto de
  terceros, y solo se guarda lo previsualizado), guardar, borrar (nunca uno en
  uso: la vista previa dice quién lo usa) y ver la configuración que sale de
  unas entradas.
- **Ayuda para automatizar** (`automation_assist`): triggers, condiciones y
  acciones de un dispositivo con sus capacidades; resolver y explicar un
  target; los triggers, condiciones y acciones aplicables a un target (los de
  «por propósito»); y esperar una vez a un trigger, con el mismo tope que
  `ha_wait_for_event`.
- **Validar al guardar**: `ha_create_or_update_automation` y `_script` validan
  con HA antes de dar el token (también lo que viene de un blueprint).

Tres tools modifican (guardar, importar y borrar blueprints) y van en dos
pasos. Diecisiete comandos de la tabla de la 011 pasan a `dedicated`. Todo se
prueba en unitarios y en el banco de Core, incluida la importación, desde un
fichero que sirve la propia HA del banco. Cuatro tramos (research R-12).

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x, aiohttp, structlog, PyYAML (ya está en `requirements.txt`; sin dependencias nuevas) · **Almacenamiento**: los ficheros de token de `/data/pending_confirmations` (como hoy; `yaml` de `ha_save_blueprint` como omitible) · **Tests**: pytest con `unittest.IsolatedAsyncioTestCase`, `AsyncMock` de `ws_send`, cola de suscripción simulada para la espera; banco de Core de la 010 · **Plataforma**: add-on de HA OS.

**Restricciones**: fail-closed (III); dos pasos con token atado a todos los argumentos y, en la importación, a la huella del contenido (IV); anotaciones verdaderas, incluida la de mundo abierto (V); control negativo (VII); repositorio público (VIII); cambios mínimos (IX).

**Escala**: 14 tools (3 modifican), 4 módulos nuevos, 2 tools existentes con validación, 17 entradas de la tabla, 1 fila del inventario reclasificada, 1 método nuevo en `HAClient`, 2 familias, 2 temas de guía, 3 filas de la matriz de pruebas.

## Comprobación de la constitución

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Lo que modifica va con vista previa que describe el efecto real: qué fichero se crea, se sustituye o se borra, quién lo usa y se recargará, y, al importar, el contenido exacto y su origen. El contenido de internet lo descarga HA, no Hermes (sin cliente HTTP nuevo ni SSRF desde el add-on), y se marca como texto de terceros. Rutas validadas antes de llegar a HA. La espera de trigger rechaza los triggers que abrirían algo mientras dura. | OK |
| II. Secretos | YAML, metadatos, errores de HA, capacidades, configuraciones sustituidas y datos de disparo pasan por `redact_secrets`/`redact_structure` antes de salir; la URL se redacta en el log; el log solo lleva dominio, ruta, tamaño, huella, recuentos y códigos; test con centinela por tool, incluido el fichero del token (FR-015). El YAML importado no se guarda en el token (research R-1). | OK |
| III. Fail-closed | Sin token si: hay errores de validación del blueprint, ya existe sin `allow_override`, la vista previa no cabe, no se sabe quién usa el blueprint, falla una lectura previa o no se puede validar una automatización. Contenido distinto al confirmar → no se guarda. Forma de respuesta inesperada → error, nunca «vacío». Las entradas de la tabla solo pasan a `dedicated` cuando la tool existe. | OK |
| IV. Dos pasos, token atado | Importar ata `url`, ruta final, `allow_override` y `content_sha256`; guardar ata `domain`, ruta final, `yaml` (omitible) y `allow_override`; borrar ata `domain` y ruta. La vista previa de la importación enseña el YAML entero o no hay token. La validación al guardar no cambia el token de las automatizaciones (lo previsualizado es lo confirmado). | OK |
| V. Nombre y descripción | Destructivas las tres que piden token; de mundo abierto la de importar; de solo lectura por nombre exacto las cuatro sin prefijo de lectura. Las respuestas dicen lo que no hacen: `not_validated`, `used_by: null` con motivo para `template`, `saved: false` en la sustitución, que HA re-serializa el YAML al guardar, y que las listas por target dan nombres sin opciones. | OK |
| VI. Lo que no se puede probar | Las tres que modifican, en el banco contra HA 2026.11.1 real (la importación por el importador genérico desde `/local/`); FR-010 y las lecturas también. Lo que el banco no puede (importadores de GitHub, gist y foro; contenido que cambia en la URL) queda en unitarios y como pendiente manual en la matriz de la 014. | OK |
| VII. Control negativo | Uno por comportamiento con riesgo, enumerados en las tareas de cierre de cada tramo (T016, T025, T037, T054) y anotados en el commit. | OK |
| VIII. Privacidad | Fixtures con `light.salon`, `<device_id>`, `https://example.com/…`, centinelas; el blueprint del banco es propio y genérico; revisión del diff en cada cierre de tramo. | OK |
| IX. Cambios mínimos | Solo las cinco CAP; `ha_validate_config` sigue siendo de la 012 (se extrae su lógica sin cambiar su comportamiento); `ha_wait_for_event` y `ws_subscribe_events_queue` sin cambios visibles; lo que no es de aquí, a dudas. | OK |
| X. Comentarios en español | Comentarios y eventos del log como hoy; nombres y descripciones de tools en inglés. | OK |
| XI. Versionado | Sin subir versión (la 1.2.0 la fijó la 009); sección propia en `## [1.2.0]` del CHANGELOG. | OK |
| Flujo, puerta 4 | Suite y banco en verde en el CI al cerrar cada tramo. | OK |

Tras el diseño: sin cambios. Ninguna desviación que justificar.

## Diseño

### Tramo A — base y blueprints locales (CAP-046, parte)

1. **Familia** `blueprints` en `tool_families.py` con `("blueprints",)`.
2. **`tools/blueprints.py`**, helpers de módulo: `_validar_dominio`,
   `_validar_ruta` (R-5; devuelve la ruta final con `.yaml`),
   `_cargar_yaml_blueprint` (`SafeLoader` que acepta `!input` y cualquier
   etiqueta desconocida como valor opaco; tope de 256 KiB), `_metadatos`
   (nombre, descripción, autor, `source_url`, versión mínima, entradas
   aplanadas), `_listar_dominio(ha_client, dominio)` (`blueprint/list`),
   `_usado_por(ha_client, dominio, ruta)` (`search/related`; `None` para
   `template`), `_third_party`.
3. **Tools**: `ha_list_blueprints`, `ha_preview_blueprint_substitution`,
   `ha_save_blueprint`, `ha_delete_blueprint` según contracts y data-model.
4. **Registro** dentro de `if _activa("blueprints")` con
   `response_max_bytes`; anotaciones (`_READ_ONLY_EXACT` para la sustitución,
   `_DESTRUCTIVE_EXACT` para guardar y borrar).
5. **Tabla**: `blueprint/list`, `blueprint/save`, `blueprint/delete`,
   `blueprint/substitute` a `dedicated` y en `_DEDICADAS_INICIALES`;
   regenerar → `git diff` vacío en `command_table.py`.
6. **Guía**: tema `blueprints` (lo del tramo) con su alias.
7. **Banco**: `tests/banco/cobertura_017.py` (dos probadas) enganchado al
   invariante, al plugin del job y a la matriz; `tests/banco/test_banco_blueprints.py`
   (listar, sustituir, guardar, borrar en uso y sin uso).
8. **Documentación parcial**: sección «Automatización asistida (spec 017)» en
   `## [1.2.0]` del CHANGELOG; fila 017 «en curso (tramo A)»; filas de la
   matriz de pruebas de las dos tools.

### Tramo B — importar (CAP-046, resto)

1. `ha_import_blueprint` en `tools/blueprints.py`: `_importador_de(url)`
   (patrones de `importer.py`), `_vista_previa_importacion`, huella con
   `hashlib.sha256` sobre `raw_data` en UTF-8, confirmación con nueva descarga
   y `validate_confirmation_token` con la huella nueva (R-1).
2. Anotaciones: `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD`.
3. Tabla: `blueprint/import` a `dedicated`; generador; regenerar idéntico.
4. Guía: la parte de importar del tema `blueprints`.
5. Banco: `tests/banco/ha_config/www/hermes_banco/luz_por_movimiento.yaml`
   con comentario de por qué está ahí; prueba de importación en
   `test_banco_blueprints.py`; `ha_import_blueprint` a `PROBADAS_017`; su fila
   de la matriz con la nota de lo no probado; pendiente manual en la hoja de
   ruta.
6. CHANGELOG del tramo.

### Tramo C — dispositivo y targets (CAP-051, CAP-052)

1. Familia `automation_assist` con `("device_automation", "targets")` (D
   añade `wait_for_trigger`).
2. **`tools/device_automation.py`**: una función común
   `_listar(tipo, device_id, include_capabilities)` y tres tools finas (R-6).
3. **`tools/targets.py`**: `_validar_target`, y las cinco tools (R-7);
   `unknown_command` → `ha_version_unsupported` con `ha_core_version`.
4. Registro, anotaciones (`_READ_ONLY_EXACT` para resolver y explicar).
5. Tabla: las 11 entradas; generador; regenerar idéntico.
6. Guía: tema `automation_assist` (dispositivo y targets).
7. Banco (lectura): `tests/banco/test_banco_automatizacion_asistida.py` con
   las listas de dispositivo y de target contra `kitchen_sink`.
8. CHANGELOG del tramo.

### Tramo D — espera de trigger, validación al guardar y cierre (CAP-038, CAP-040)

1. **Cliente**: `HAClient.ws_subscribe_queue(payload)`;
   `ws_subscribe_events_queue` delega en él sin cambiar comportamiento.
2. **Gestor compartido**: `register_all_tools` crea un `_WaitManager` y se lo
   pasa a `wait_for_event.register` (parámetro opcional nuevo) y a
   `wait_for_trigger.register`; `_ActiveWait` gana `kind` y
   `trigger_platform` y `list_active` solo añade esas claves a las esperas de
   trigger.
3. **`tools/wait_for_trigger.py`** con `ha_wait_for_trigger` (R-8).
4. **Validación al guardar**: en `tools/core_validation.py` (de la 012),
   `partes_de_config` y `validar_partes` a nivel de módulo, usadas por
   `ha_validate_config` sin cambiar su comportamiento; en `tools/blueprints.py`
   (o un helper compartido), `sustituir(ha_client, dominio, use_blueprint)`;
   en `automations.py` y `scripts.py`, la llamada en la rama de vista previa
   (R-9).
5. Tabla: `subscribe_trigger` a clase A con CAP-038 en
   `inventario/core-ws.tsv` y a `dedicated`; generador; regenerar idéntico.
6. Guía: espera de trigger en `automation_assist`; línea en el tema de
   automatizaciones.
7. Banco: espera de trigger y validación al guardar en
   `test_banco_automatizacion_asistida.py`.
8. **Documentación final**: CHANGELOG completo, hoja de ruta «hecha» (fila del
   programa y línea de pendientes), README y README.es (tools por área y
   recuento si lo llevan), DOCS (familias), matriz de la 008 (filas CAP-038,
   CAP-040, CAP-046, CAP-051, CAP-052).

## Estructura de ficheros

```text
hermes/src/hermes/
├── ha.py                          # + ws_subscribe_queue (D)
├── tool_families.py               # + blueprints (A), automation_assist (C, D)
├── command_table.py               # 17 entradas a dedicated (A: 4, B: 1, C: 11, D: 1)
└── tools/
    ├── __init__.py                # registro bajo las familias; gestor de esperas compartido (A, C, D)
    ├── _annotations.py            # nombres exactos (A, B, C, D)
    ├── guide.py                   # temas blueprints y automation_assist (A, B, C, D)
    ├── blueprints.py              # nuevo (A, B; sustitución compartida en D)
    ├── device_automation.py       # nuevo (C)
    ├── targets.py                 # nuevo (C)
    ├── wait_for_trigger.py        # nuevo (D)
    ├── wait_for_event.py          # gestor inyectable; kind en las de trigger (D)
    ├── core_validation.py         # funciones de módulo (D; fichero de la 012)
    ├── automations.py             # validación en la vista previa (D)
    └── scripts.py                 # validación en la vista previa (D)
scripts/inventario/generar_tabla.py  # _DEDICADAS_INICIALES (A, B, C, D)
specs/008-cobertura-total/inventario/core-ws.tsv  # subscribe_trigger a clase A (D)
tests/
├── test_tools_blueprints.py       # nuevo (A, B)
├── test_tools_device_automation.py# nuevo (C)
├── test_tools_targets.py          # nuevo (C)
├── test_tools_wait_for_trigger.py # nuevo (D)
├── test_ha_ws_subscribe_queue.py  # nuevo (D)
├── test_tools_validacion_al_guardar.py # nuevo (D)
├── test_tool_families.py, test_tools_registration.py, test_command_table.py,
│   test_generar_tabla.py, test_tools_guide.py, test_tools_generic_commands.py,
│   test_tools_wait_for_event.py   # ampliados
└── banco/
    ├── ha_config/www/hermes_banco/luz_por_movimiento.yaml  # nuevo (B)
    ├── cobertura_017.py                     # nuevo (A, B)
    ├── test_banco_blueprints.py             # nuevo (A, B)
    └── test_banco_automatizacion_asistida.py# nuevo (C, D)
tests/test_banco_cobertura_escrituras.py, tests/banco/obligatorio.py  # una línea cada uno (A)
hermes/CHANGELOG.md, docs/HOJA-DE-RUTA.md, README.md, README.es.md,
hermes/DOCS.md, specs/008-cobertura-total/plan.md
```

## Trazabilidad (FR de la 017 → FR/CAP de la 008 → tareas → test)

| FR 017 | FR 008 | CAP | Tareas | Test |
|---|---|---|---|---|
| FR-001 | FR-058 | CAP-046 | T004, T008, T013 | `test_tools_blueprints.py`; banco |
| FR-002 | FR-058 | CAP-046 | T003, T017–T019, T023 | `test_tools_blueprints.py` (`TestImportar`); banco |
| FR-003 | FR-058 | CAP-046 | T003, T006, T008, T013 | `test_tools_blueprints.py` (`TestGuardar`); banco |
| FR-004 | FR-058 | CAP-046 | T007, T008, T013 | `test_tools_blueprints.py` (`TestBorrar`); banco |
| FR-005 | FR-058 | CAP-046 | T005, T008, T013 | `test_tools_blueprints.py` (`TestSustituir`); banco |
| FR-006 | FR-059 | CAP-051 | T027, T029, T034 | `test_tools_device_automation.py`; banco |
| FR-007 | FR-060 | CAP-052 | T028, T030, T034 | `test_tools_targets.py`; banco |
| FR-008 | FR-060 | CAP-052 | T028, T030, T034 | `test_tools_targets.py`; banco |
| FR-009 | FR-061 | CAP-038 | T038–T042, T047 | `test_ha_ws_subscribe_queue.py`, `test_tools_wait_for_event.py`, `test_tools_wait_for_trigger.py`; banco |
| FR-010 | FR-062 | CAP-040 | T043, T044, T047 | `test_tools_validacion_al_guardar.py`, tests de `ha_validate_config` de la 012 sin cambios; banco |
| FR-011 | FR-010 | CAP-004 | T002, T009, T026, T031, T042, T043 | `test_tool_families.py`, `test_tools_registration.py` |
| FR-012 | FR-012 | CAP-001 | T010, T021, T032, T045 | `test_command_table.py`, `test_generar_tabla.py`, `test_tools_generic_commands.py` |
| FR-013 | FR-018 | — | T009, T020, T031, T042 | `test_tools_registration.py` |
| FR-014 | FR-011 | — | T011, T022, T033, T046 | `test_tools_guide.py` |
| FR-015 | FR-019 | — | T004–T007, T017, T018, T027, T040, T043 | centinelas en cada fichero de test |
| FR-016 | FR-018 | CAP-023 | T004, T005, T017, T027, T028, T040 | ídem |
| FR-017 | FR-015 | CAP-034 | T009, T012, T013, T020, T023, T034, T047 | banco, `test_banco_cobertura_escrituras.py`, `test_matriz_pruebas.py` |
| FR-018 | FR-020 | — | T009, T015, T036, T038, T039, T048 | `test_tools_registration.py`, `test_tool_families.py`, tests existentes sin tocar |
| FR-019 | FR-023 | — | T014, T024, T035, T049–T052 | revisión en el cierre |
| FR-020 | FR-021 | — | T016, T025, T037, T054 | revisión del diff |

## Riesgos

- **La 012 sin integrar** (S-01): bloquea el inicio (T001). La 008 ya lo
  ordena así.
- **Ficheros comunes** (`_annotations.py`, `guide.py`, `command_table.py`,
  `tools/__init__.py`, CHANGELOG, hoja de ruta) los tocan otras
  sub-features de la ola 3: cada tramo cambia lo mínimo y se resuelven al
  integrar (orden de olas de la 008).
- **`/local/` en el banco**: si una versión futura de HA dejara de servir
  `www` sin autenticación, la prueba de importación fallaría en el CI, no en
  silencio. El test comprueba primero que el fichero se descarga (petición
  directa a `/local/…` desde el lector) para que el fallo diga la causa.
