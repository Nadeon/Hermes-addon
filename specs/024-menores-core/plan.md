# Plan de implementación: menores de Core (024)

**Rama**: `feat/024-menores-core` (ya creada desde `feat/cobertura-total` en `1752984`) | **Fecha**: 2026-11-15 | **Spec**: [spec.md](spec.md) | **Programa**: [008](../008-cobertura-total/plan.md), sub-feature 024, ola 3

## Resumen

Tres tools dedicadas nuevas en dos familias nuevas: `cameras`
(`ha_get_camera_snapshot` y `ha_get_image_entity`, solo lectura, devuelven
`ImageContent`; CAP-059) y `dashboard_reset`
(`ha_reset_lovelace_dashboard_config`, en dos pasos con la protección del
principal; CAP-071). Un método nuevo del cliente lee imágenes en flujo con
tope. En la tabla: `lovelace/config/delete` pasa a `dedicated`; siete
entradas «pendiente (spec 024)» pasan a `read`/`confirm`; las miniaturas de
`browse_media`/`search_media` se tapan (hallazgo, research R-6); el motivo de
`application_credentials/config_entry` se corrige (R-7); y las 33 entradas
de estas CAP quedan fijadas por tests y con ejecución en el banco por CAP.
Dos tramos: 1 (CAP-059 y las CAP de la tabla de datos: 065, 066, 067, 072) y
2 (CAP-071, CAP-070, CAP-073 y el cierre).

## Dependencias y momento de la implementación

La base (`1752984`) tiene la 009, 010, 011, 012, 013, 014, 015, 016, 018,
019, 027, 028, 029, 030 y 033. No hace falta esperar a nada. Si al empezar un
tramo se ha integrado otra sub-feature en `feat/cobertura-total` (017, 020,
021, 022, 023, 031, 032), se trae primero con `git merge --no-ff` y se anota:
tocan los mismos ficheros comunes (research R-0).

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x (`Image`), aiohttp, structlog; sin dependencias nuevas · **Almacenamiento**: ninguno nuevo · **Tests**: pytest con `unittest.IsolatedAsyncioTestCase`, `AsyncMock` de `ws_send`, servidor aiohttp de prueba para `rest_get_image` (como los tests de `rest_get_text_tail`), `structlog.testing.capture_logs`; banco de Core de la 010 · **Plataforma**: add-on de HA OS.

**Restricciones**: fail-closed (III); anotaciones verdaderas (V); control negativo (VII); repositorio público (VIII); cambios mínimos (IX); FR-020 de la 008.

**Escala**: 3 tools (1 que modifica, con token), 2 módulos nuevos, 1 método nuevo en `HAClient`, 2 familias, 2 temas nuevos de guía y una sección en `lovelace`, 1 entrada a `dedicated`, 7 de `deny` a `read`/`confirm`, 3 con motivo o `redact_extra` corregidos.

## Comprobación de la constitución

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Restablecer pide token y nunca toca el principal ni el panel por defecto; las escrituras de la tabla son `confirm`; la clase D sigue `deny`; ninguna tool usa `hassio/` ni `supervisor/`. | OK |
| II. Secretos | Nunca se devuelve `access_token` ni `entity_picture` de una cámara; `webhook_id`, `client_secret` y las miniaturas firmadas salen tapados; log sin URL ni bytes. Centinelas en cada caso (SC-004). | OK |
| III. Fail-closed | `entity_id` y `max_width` validados antes de pedir; tope de bytes con corte de la lectura; `default_panel_unknown` no borra nada; estado cambiado → no se borra; comando sin tool → `use_dedicated_tool`. | OK |
| IV. Dos pasos, token atado | `ha_reset_lovelace_dashboard_config` ata `url_path` y la configuración leída (`estado`); fila en el inventario de la 033. Las de imagen no aceptan token (invariante de registro). | OK |
| V. Nombre y descripción | `ha_get_*` de lectura; `ha_reset_*` en `_DESTRUCTIVE_EXACT`; las descripciones dicen privacidad, mundo abierto, que Core solo escala JPEG y el tope; los motivos de la tabla dicen lo que se tapa. | OK |
| VI. Lo que no se puede probar | Las tres tools y una entrada por CAP en el banco contra Core 2026.11.1; la reducción con TurboJPEG y una cámara en la nube quedan como prueba manual (research R-9). | OK |
| VII. Control negativo | Uno por comportamiento con riesgo (T013 y T029), anotados en el commit de cada tramo. | OK |
| VIII. Privacidad | Fixtures con `camera.entrada`, `light.salon`, `panel-pruebas`, `centinela-024`; imagen de prueba generada, sin fotos reales; revisión del diff al cerrar cada tramo. | OK |
| IX. Cambios mínimos | Sin Pillow; sin tools para lo que la 008 manda a la tabla; `tools/lovelace.py` se importa, no se cambia; el tema `lovelace` solo gana una sección. | OK |
| X. Comentarios en español | Comentarios y eventos en español; descripciones en inglés, guía en español, como hoy. | OK |
| XI. Versionado | Sin subir versión; sección propia en `## [1.2.0]`. | OK |
| Flujo, puerta 4 | Suite, banco, Semgrep y CodeQL en verde en el CI al cerrar cada tramo. | OK |

Tras el diseño: sin cambios. Ninguna desviación que justificar.

## Diseño

### Tramo 1 — CAP-059 y las CAP de datos por la tabla (065, 066, 067, 072)

1. **Cliente**: `HAClient.rest_get_image` e `ImageTooLargeError` (data-model).
2. **Familia** `cameras` con el módulo `cameras`.
3. **`tools/cameras.py`**: validación, función pura de dimensiones
   (`_dimensiones(bytes) -> (w, h) | (None, None)`), las dos tools, mapa de
   errores, evento de log. Devuelven `[dict, Image]`.
4. **Registro** bajo `cameras`; anotaciones: las dos en `_OPEN_WORLD`;
   `_HINTS_NUEVAS_1_2_0`.
5. **Tabla**: `camera/get_prefs` `read` y `camera/update_prefs` `confirm`
   con `open_world`, a `_POR_LA_TABLA`; `browse_media` y `search_media` con
   `redact_extra=("thumbnail",)`; `TestClasificacionDeLa024` con las entradas
   de CAP-059, 065, 066, 067 y 072; regenerar sin cambios.
6. **Guía**: tema `cameras` (alias `camera`, `cámaras`, `camaras`,
   `snapshot`, `image`, `imagen`) e índice; tema `core_minor` con la parte
   de calendario, tags, medios e imágenes subidas.
7. **Banco**: imagen JPEG de prueba en
   `tests/banco/ha_config/www/hermes_banco/camara.jpg`; `media_source:`,
   `image_upload:` y `media_dirs`; `tests/banco/test_banco_camaras.py` (las
   dos tools) y `tests/banco/test_banco_menores_datos.py` (calendario y
   tareas con `local_calendar`/`local_todo`, `image/list` y `image/delete`
   tras subir por el lector, `browse_media` y `local_source/remove`,
   `camera/get_prefs` y `camera/update_prefs`); `tests/banco/cobertura_024.py`
   con `LECTURAS_EN_BANCO_024` sumado a `TOOLS_EXIGIDAS_DEL_JOB`.
8. **Documentación parcial**: CHANGELOG, recuento de los README y DOCS
   (familia), hoja de ruta «en curso: tramo 1».

### Tramo 2 — CAP-071, CAP-070, CAP-073 y cierre

1. **Familia** `dashboard_reset` con el módulo `lovelace_reset`.
2. **`tools/lovelace_reset.py`**: la tool según data-model, importando
   `_default_panel`, `_get_dashboard_meta_by_url_path` y `_count_cards` de
   `tools/lovelace.py`; `_DESTRUCTIVE_EXACT`; `_HINTS_NUEVAS_1_2_0`; fila en
   `tests/test_confirmation_args_inventory.py`.
3. **Tabla**: `lovelace/config/delete` a `dedicated` (y en
   `_DEDICADAS_INICIALES`); las cinco lecturas de CAP-071 a `read` (en
   `_POR_LA_TABLA`); motivo de `application_credentials/config_entry`;
   `TestClasificacionDeLa024` completo (33 entradas); `grep -c "spec 024"` = 0;
   regenerar sin cambios.
4. **Guía**: sección «Restablecer» en el tema `lovelace` (huella nueva);
   `core_minor` completo (CAP-070, 071 y 073).
5. **Banco**: `tests/banco/test_banco_menores_ui.py` (restablecer con el
   lector y la vista previa sin efecto; `trace/contexts`, `get_themes`,
   `webhook/list` con una automatización de disparador `webhook`,
   `vacuum/get_segments` con un `vacuum` de plantilla, `radio_frequency/list`,
   las lecturas y escrituras de CAP-070 y `application_credentials/*`);
   `PROBADAS_024` en el invariante de escrituras; fila en la matriz de la 014.
6. **Documentación final**: CHANGELOG, hoja de ruta «hecha», README, DOCS,
   `SECURITY.md` (miniaturas y `webhook_id`), filas de la matriz de la 008.

## Estructura de ficheros

```text
hermes/src/hermes/
├── ha.py                          # rest_get_image, ImageTooLargeError (1)
├── tool_families.py               # cameras (1), dashboard_reset (2)
├── command_table.py               # 2 + 5 a read/confirm, 1 dedicated, redact y motivos (1, 2)
└── tools/
    ├── __init__.py                # registro bajo las familias (1, 2)
    ├── _annotations.py            # _OPEN_WORLD (1), _DESTRUCTIVE_EXACT (2)
    ├── guide.py                   # cameras, core_minor (1, 2); lovelace (2)
    ├── cameras.py                 # NUEVO: 2 tools (1)
    └── lovelace_reset.py          # NUEVO: 1 tool (2)
scripts/inventario/generar_tabla.py   # lovelace/config/delete en _DEDICADAS_INICIALES (2)
tests/
├── test_ha_rest_get_image.py           # NUEVO (1)
├── test_tools_cameras.py               # NUEVO (1)
├── test_tools_lovelace_reset.py        # NUEVO (2)
├── test_command_table.py               # _POR_LA_TABLA, TestClasificacionDeLa024 (1, 2)
├── test_tools_generic_commands.py      # redacciones y use_dedicated_tool con la tabla real (1, 2)
├── test_tool_families.py, test_config_validation.py  # familias (1, 2)
├── test_tools_registration.py          # _HINTS_NUEVAS_1_2_0, SC-005 (1, 2)
├── test_tools_guide.py                 # temas, alias, huella de lovelace (1, 2)
├── test_confirmation_args_inventory.py # fila de la tool con token (2)
├── test_banco_cobertura.py, test_banco_cobertura_escrituras.py  # 024 (1, 2)
└── banco/
    ├── cobertura_024.py                # NUEVO (1, 2)
    ├── conftest.py / cobertura_escrituras.py  # exigidas del job (1, 2)
    ├── ha_config/configuration.yaml    # media_source, image_upload, media_dirs (1); application_credentials, vacuum de plantilla (2)
    ├── ha_config/www/hermes_banco/camara.jpg, ha_config/media/banco_borrable.jpg  # NUEVOS (1)
    ├── test_banco_camaras.py           # NUEVO (1)
    ├── test_banco_menores_datos.py     # NUEVO (1)
    └── test_banco_menores_ui.py        # NUEVO (2)
hermes/CHANGELOG.md, hermes/DOCS.md, README.md, README.es.md, SECURITY.md,
docs/HOJA-DE-RUTA.md, specs/008-cobertura-total/plan.md   # (1 parcial, 2)
```

## Trazabilidad

| FR (024) | FR (008) | CAP | Tareas | Test |
|---|---|---|---|---|
| FR-001 | FR-085 | CAP-059 | T004, T007 | `test_tools_cameras.py` |
| FR-002 | FR-085 | CAP-059 | T004, T007 | `test_tools_cameras.py` |
| FR-003 | FR-085, FR-018 | CAP-059 | T003, T006, T007 | `test_ha_rest_get_image.py`, `test_tools_cameras.py` |
| FR-004 | FR-019 | CAP-059 | T004, T005, T007 | `test_tools_cameras.py` (centinela y log) |
| FR-005 | FR-085 | CAP-059 | T009 | `test_command_table.py`, `test_tools_generic_commands.py` |
| FR-006 | FR-086 | CAP-071 | T019, T022 | `test_tools_lovelace_reset.py` |
| FR-007 | FR-086, FR-018 | CAP-071 | T020, T021, T022 | `test_tools_lovelace_reset.py` |
| FR-008 | FR-086, FR-019 | CAP-071 | T017, T024 | `test_command_table.py`, `test_tools_generic_commands.py` |
| FR-009 | FR-087 | CAP-065, 066, 072 | T009, T012 | `test_command_table.py` (`TestClasificacionDeLa024`) |
| FR-010 | FR-087, FR-019 | CAP-067 | T009, T012 | `test_command_table.py`, `test_tools_generic_commands.py` |
| FR-011 | FR-087 | CAP-070 | T017, T024 | `test_command_table.py` |
| FR-012 | FR-088, FR-019 | CAP-073 | T017, T024 | `test_command_table.py`, `test_tools_generic_commands.py` |
| FR-013 | FR-010 | CAP-004 | T002, T018 | `test_tool_families.py`, `test_config_validation.py` |
| FR-014 | FR-012 | CAP-001 | T009, T024 | `test_command_table.py`, `test_generar_tabla.py` |
| FR-015 | FR-018, FR-020 | — | T008, T023 | `test_tools_registration.py` |
| FR-016 | FR-011 | CAP-008 | T010, T025 | `test_tools_guide.py` |
| FR-017 | FR-014, FR-015 | CAP-034 | T011, T026, T027 | `tests/banco/test_banco_*.py`, `test_banco_cobertura*.py` |
| FR-018 | FR-015, FR-018 | — | T023, T026 | `test_confirmation_args_inventory.py`, `test_matriz_pruebas.py`, `test_allow_dangerous_inventario.py` |
| FR-019 | FR-023, FR-024 | — | T014, T030 | `TestToolCountInDocs`; revisión |
| FR-020 | FR-020 | — | T008, T023, T025, T028 | `test_tools_registration.py`, `test_tools_guide.py` |

## Tramos

| Tramo | Tareas | Tools | Entradas de la tabla |
|---|---|---|---|
| 1 — CAP-059 y datos (065, 066, 067, 072) | T001–T015 | 2 | 2 a `read`/`confirm`; 2 con `redact_extra`; 17 fijadas por test |
| 2 — CAP-071, 070, 073 y cierre | T016–T031 | 1 | 1 a `dedicated`; 5 a `read`; 1 motivo; las 33 fijadas |

Cada tramo cabe en el contexto de un agente: el 1 son dos tools de lectura
con un método del cliente y entradas que ya existen; el 2, una tool con el
patrón de `ha_delete_lovelace_dashboard`, cinco lecturas y la documentación.

## Riesgos

- **Envoltorios comunes** que serialicen la lista `[dict, Image]` (tope o
  redacción centrales): se comprueba en T007 con el registro real; si pasa,
  la imagen se devuelve fuera del envoltorio y se anota.
- **El banco sin TurboJPEG o sin alguna integración** (`local_file`,
  `image_upload`, `application_credentials`, `vacuum` de plantilla): la
  prueba de esa parte queda en unitarios y se anota (supuesto de la spec).
- **Conflictos de fusión** con 017, 020, 021, 022, 023, 031 y 032 en los
  ficheros comunes: se conservan los cambios de todas.
