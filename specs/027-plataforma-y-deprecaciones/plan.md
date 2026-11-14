# Plan de implementación: plataforma y deprecaciones (027)

**Rama**: `feat/027-plataforma-y-deprecaciones` (no se crea ninguna) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md) | **Programa**: [008](../008-cobertura-total/plan.md), sub-feature 027, ola 2

## Resumen

Sin tools nuevas. La 027 deja la 1.2.0 preparada para lo que HA y el
Supervisor van a cambiar y documenta lo que solo se puede decidir más
adelante: `sv_get_job_status` explica qué significa `success`, enseña los
errores de los sub-jobs (`child_errors`), que hoy se pierden, y los cuenta
como fallo, igual que el sondeo de los safety backups (D-1); la tool
deprecada `ha_remove_device_from_config_entry` da un error claro el día que HA
retire su comando; tests fijan la forma de los dispositivos de HA 2027.8 y
2027.10 y que nada deprecado se retira en la 1.2.0; Hermes detecta al arrancar
el socket Unix y la API `/v2` del Supervisor y lo anota sin usarlos; una
guarda hace fallar la suite si Hermes usa algo deprecado del SDK `mcp`; las
opciones tienen traducciones en inglés y español y las tools de apps hablan de
«apps»; y la hoja de ruta recoge los hosts CIMD, la investigación de
`outputSchema` y de la vía nativa de MCP, la tabla de deprecaciones al día y
lo que hará falta para el socket y la `/v2`. Dos tramos cortos: A (código y
tests) y B (textos y documentación).

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x, aiohttp, structlog, PyYAML (ya en `requirements.txt`; sin dependencias nuevas) · **Almacenamiento**: ninguno nuevo · **Tests**: pytest con `unittest.IsolatedAsyncioTestCase`, `AsyncMock` del cliente, `structlog.testing.capture_logs`, `DummyMCP` y un `MCPServer` real para el registro · **Plataforma**: add-on de HA OS.

**Restricciones**: no retirar ni activar nada en la 1.2.0 (decisión del
supervisor y decisión 3 de la 008); fail-closed (III); anotaciones y
descripciones verdaderas (V); control negativo (VII); repositorio público
(VIII); cambios mínimos (IX).

**Escala**: 0 tools nuevas; 2 tools con cambio de comportamiento aditivo
(`sv_get_job_status`, `ha_remove_device_from_config_entry`); 12 descripciones
de texto; 1 módulo nuevo (`supervisor_platform.py`); 1 función nueva en
`supervisor_jobs.py`; 2 ficheros de traducción; 5 ficheros de tests nuevos y
4 ampliados; 0 entradas de la tabla.

## Dependencias y orden

- **La implementación espera a la integración.** Esta rama tiene la 011 hasta
  su tramo 3 y **no** tiene la 009 ni la 010. Antes del tramo A hay que
  integrar (T001): la 009 (la entrada `## [1.2.0]` del CHANGELOG con su
  esqueleto y la versión 1.2.0), la 010 (banco de Core) y la 011 completa,
  desde `feat/cobertura-total` o desde sus ramas, según lo que esté integrado
  cuando empiece el tramo. Hoy `feat/cobertura-total` ya tiene la 009 y la
  010; la 011 completa está en `feat/011-politica-de-comandos`.
- Ninguna otra sub-feature depende de la 027 (ola 2, sin dependencias en la
  008). Coordinación: la 028 prueba `ha_remove_device_from_config_entry` en el
  banco; FR-009 solo toca el camino de `unknown_command`, que HA 2026.11.1 no
  da (S-02). La 013 puede tocar `tools/supervisor.py`; la 027 no lo toca.
- Si la 010 no está integrada cuando empiece el tramo A, no bloquea: la 027 no
  añade tools que modifiquen ni pruebas de banco.

## Comprobación de la constitución

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Nada se activa: el socket y la `/v2` solo se detectan (FR-011); la tool deprecada no cambia de comando ni reintenta con otro al fallar (FR-009); `success` deja de dar por bueno un job con sub-jobs fallidos (FR-002, D-1). Ninguna tool nueva, ninguna entrada de la tabla cambia, la denylist no cambia. | OK |
| II. Secretos | `child_errors` pasa por `redact_secrets` y el recorte de `job_errors`, con test de centinela (FR-016); el evento del arranque solo lleva booleanos, nunca la ruta del socket ni el texto del error (FR-011). | OK |
| III. Fail-closed | La detección es solo informativa y un fallo da `null`, nunca «no hay `/v2`» por omisión (FR-011); `child_errors` ignora entradas raras sin inventar errores ni ocultarlos en `errors` (FR-002); un error en un sub-job, o un recorrido recortado, da `success: false` y hace fallar el sondeo del safety backup: no se escribe sin un backup válido (FR-017, D-1); `unknown_command` se reconoce por el código, nunca por el texto (FR-009). Traducciones: un fichero mal formado lo ignora el Supervisor sin efecto en el arranque, y el test impide publicarlo. | OK |
| IV. Dos pasos, token atado | Sin cambios en ningún flujo de confirmación; la tool deprecada gasta su token como fallido al recibir `unknown_command` y no lo reutiliza para otro comando. Los dos pasos siguen siendo la única vía (FR-004). | OK |
| V. Nombre y descripción | Es el objetivo de FR-001 y FR-007: la descripción de `sv_get_job_status` dice lo que de verdad significa `success`, y deja de esconder los sub-jobs; las tools de apps usan el término del Supervisor sin cambiar de nombre; ninguna anotación cambia (test de FR-008 y FR-014). | OK |
| VI. Lo que no se puede probar | El socket para apps y la `/v2` estable no existen: se prueban contra el comportamiento que documenta el código del Supervisor 2026.11.0 con un cliente simulado, citando el fichero (research R-2, R-3); la retirada de `remove_config_entry` y la forma de los dispositivos de 2027.8, igual con HA simulado (R-4). La comprobación en una instalación real queda en quickstart como manual opcional. | OK |
| VII. Control negativo | Uno por comportamiento con riesgo: `child_errors` (quitar el recorrido), `success` con sub-jobs (no mirar `child_errors`), sondeo del safety backup (no mirar los sub-jobs), `command_removed_in_ha` (quitar la traducción), detección (forzar `api_v2_enabled` a `False` ante un fallo), guarda del SDK (emitir un aviso deprecado de prueba), traducciones (borrar una clave). Enumerados en T003, T005, T005b, T007, T009, T011, T015 y T018 y anotados en el commit. | OK |
| VIII. Privacidad | Fixtures con `<slug>`, `<uuid>`, `light.salon`, centinelas; traducciones sin hostnames ni ejemplos reales (los de `DOCS.md` ya son genéricos: `homeassistant.tailXXXX.ts.net`, `claude.ai`); revisión del diff al cerrar cada tramo. | OK |
| IX. Cambios mínimos | Solo lo que piden las CAP; las dos ampliaciones (`child_errors`, `command_removed_in_ha`) son aditivas y necesarias, y el cambio de `success` con sub-jobs es un arreglo (D-1), necesario para que las descripciones no mientan o para preparar lo anunciado. Los «add-on» del resto de textos no se tocan; lo que no es de la 027 va a dudas o al informe (research R-9). | OK |
| X. Comentarios en español | Comentarios y mensajes del log en español; nombres de eventos en inglés. Las descripciones al cliente que se editan (`sv_get_job_status`, las doce de apps, la guía) están hoy en español: las líneas nuevas siguen el idioma de su texto y traducirlas enteras no es de la 027 (IX); queda como duda D-6. Los errores nuevos (`command_removed_in_ha`) y `en.yaml`, en inglés; `es.yaml`, en español. | OK, con duda D-6 |
| XI. Versionado | Sin subir versión (la 1.2.0 la fija la 009); sección propia en `## [1.2.0]` del CHANGELOG. | OK |
| Flujo, puerta 4 | Suite en verde en el CI al cerrar cada tramo; la 027 no añade nada al banco. | OK |

Tras el diseño: sin cambios. Desviación justificada abajo.

## Desviaciones respecto a la 008

| Qué | 008 | 027 | Por qué |
|---|---|---|---|
| Tramos | 1 (S) | 2 cortos | Código y textos en ficheros distintos; juntos llenan el contexto de un agente (research R-10) |
| FR-092 | Documentar «cualquier `errors` → `false`» | Documentarlo, añadir `child_errors` y contarlos en `success` y en el sondeo del safety backup | Los errores de los sub-jobs no suben al padre; sin esto, `success: true` mentía con un backup incompleto (research R-1; D-1, decisión del supervisor) |
| FR-097 | Documentar lo bloqueado | Documentar y detectar al arrancar | Decisión del supervisor del programa: preparar con detección y avisos sin activar nada (research R-2, R-3) |
| CAP-029 | «traducciones de las opciones» | Crearlas (no existían) | research R-5 |

## Diseño

### Tramo A — código y tests (FR-001 parte de código, FR-002, FR-004 test, FR-005, FR-008…FR-011, FR-014)

1. **`supervisor_jobs.py`**: `CHILD_ERRORS_MAX = 20`,
   `CHILD_JOBS_MAX_DEPTH = 5` y `child_job_errors(data) -> tuple[list[dict],
   bool]` (data-model). Recorrido iterativo con pila para no depender de la
   recursión; reutiliza `JOB_ERROR_MAX_CHARS` y `redact_secrets`.
   `job_errors` no cambia.
2. **`tools/backups.py`, `sv_get_job_status`**: añade `child_errors` (y
   `child_errors_truncated` si hace falta) al resultado; `success` es `false`
   si cualquiera de los dos dice que hubo (o pudo haber) errores en sub-jobs,
   y el seguimiento local (`pending_jobs.json`) lo marca `failed`. Nueva
   descripción (FR-001, FR-002, contrato; D-1).
   **`fs_write.py`, `_evaluar_job`** (sondeo del safety backup): cuenta los
   errores de los sub-jobs como fallo, con su mensaje `"<sub-job>: <mensaje>"`,
   y un recorrido recortado también (FR-017, D-1). `safety_retention.py` no
   cambia.
3. **`tools/registry_device.py`, `ha_remove_device_from_config_entry`**: en el
   `except HAConnectionError` del segundo paso, si `exc.code ==
   "unknown_command"`, devolver `command_removed_in_ha` (data-model) tras
   `complete_confirmation_token(..., success=False, error="command_removed_in_ha")`;
   el log `ha_remove_device_from_config_entry_ws_error` añade `code`.
4. **`supervisor_platform.py`** (módulo nuevo, sin dependencias de las tools):
   `SOCKET_ENV = "SUPERVISOR_SOCKET"`, `TIMEOUT_S = 10`,
   `socket_ofrecido(environ) -> bool`, `api_v2_activada(info) -> bool | None`
   y `async comprobar_plataforma(ha_client, environ) -> dict`, que usa
   `ha_client.sv_request("GET", "/supervisor/info", timeout_seconds=…)` dentro
   de `asyncio.wait_for`, captura cualquier excepción salvo
   `asyncio.CancelledError`, escribe los eventos y devuelve el dict.
5. **`__main__.py`**: tras el paso 8 (`_connect_ha_ws`) y antes del paso 9,
   `await comprobar_plataforma(ha_client, os.environ)`, con un comentario del
   porqué (preparar sin activar). No es un paso numerado nuevo: el estado de
   salud y los pasos no cambian.
6. **Guardas de SDK** (`tests/test_sdk_deprecaciones.py`): sin cambios de
   código; si al escribirlas aparece un aviso deprecado real, se corrige el uso
   en Hermes en el mismo tramo (sería parte de FR-005).
7. **Tests de deprecaciones** (`tests/test_deprecaciones.py`): registro real de
   las tools con la configuración por defecto; anotaciones de los cinco
   nombres deprecados comparadas con las que tienen hoy (copiadas en el test);
   forma de dispositivo de 2027.8/2027.10 en `_count_config_entry_dependents`
   (por `ha_delete_config_entry`) y en el plan de `ha_remove_device` (HA
   anterior a 2026.9, que usa `device_config_entries`); búsqueda en el código
   de `primary_config_entry` y `config_entries_subentries` (ningún uso).
8. **FR-014**: la lista de tools con la configuración por defecto, igual que
   antes del tramo (el test de registro existente y el de esquemas de la 1.1.2
   siguen sin tocarse); regenerar la tabla y comprobar que no cambia.

### Tramo B — textos, traducciones y documentación (FR-001 guía, FR-003, FR-004, FR-005 fila, FR-006, FR-007, FR-012, FR-013, FR-015)

1. **Traducciones**: `hermes/translations/en.yaml` y `es.yaml` (data-model),
   textos a partir de la tabla de opciones de `DOCS.md`, con «app».
   `tests/test_translations.py`.
2. **Descripciones de `tools/addons.py`**: «app (add-on)» en la primera línea
   de cada una de las doce; resto del texto igual salvo «add-on» → «app» donde
   hable del objeto. Test en `tests/test_tools_supervisor.py`.
3. **Guía** (`tools/guide.py`): instrucciones del servidor (apartado 4), temas
   `supervisor` y `backups` (contrato). Tests en `tests/test_tools_guide.py`.
   Si `docs/` o los README reproducen las instrucciones del servidor, se
   sincronizan.
4. **`hermes/DOCS.md`, `README.md`, `README.es.md`**: descripciones de las
   opciones con «app» donde dicen «add-on» hablando del objeto (no del nombre
   del repositorio ni de los enlaces); una línea sobre las traducciones.
5. **Hoja de ruta** (`docs/HOJA-DE-RUTA.md`): tabla de deprecaciones (research
   R-8); en «Programa de cobertura total», el estado de la 027 y los puntos
   «Distinguir errores fatales…», «`outputSchema`…» y
   «`oauth_cimd_allowed_hosts`» con lo hecho; en «1.3.0 y posteriores», un
   apartado «Socket Unix y API `/v2` del Supervisor: qué hará falta» con la
   tabla de rutas de research R-3 y los pasos de R-2; hosts CIMD conocidos
   (R-7); resumen de `outputSchema` y de la vía nativa (R-6).
6. **CHANGELOG**: sección `### Plataforma y deprecaciones` en `## [1.2.0]`.
7. **Matriz de la 008** (`specs/008-cobertura-total/plan.md`): filas CAP-025,
   CAP-026 y CAP-028…CAP-033 con los tests y las entradas de la hoja de ruta.

## Estructura del proyecto

### Documentación (esta sub-feature)

```text
specs/027-plataforma-y-deprecaciones/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/tools.md
├── checklists/requirements.md
└── tasks.md
```

### Código (raíz del repositorio)

```text
hermes/
├── translations/en.yaml               # nuevo (B)
├── translations/es.yaml               # nuevo (B)
├── DOCS.md                            # B
├── CHANGELOG.md                       # B
└── src/hermes/
    ├── supervisor_platform.py         # nuevo (A)
    ├── supervisor_jobs.py             # A
    ├── __main__.py                    # A
    └── tools/
        ├── backups.py                 # A (sv_get_job_status)
        ├── registry_device.py         # A
        ├── addons.py                  # B (descripciones)
        └── guide.py                   # B
tests/
├── test_supervisor_jobs.py            # nuevo (A)
├── test_supervisor_platform.py        # nuevo (A)
├── test_deprecaciones.py              # nuevo (A)
├── test_sdk_deprecaciones.py          # nuevo (A)
├── test_translations.py               # nuevo (B)
├── test_tools_supervisor.py           # A (sub-jobs) y B (descripciones)
├── test_tools_registry_device.py      # A
├── test_main_wiring.py                # A
└── test_tools_guide.py                # B
docs/HOJA-DE-RUTA.md                   # B
README.md, README.es.md                # B
specs/008-cobertura-total/plan.md      # B (matriz)
```

## Trazabilidad

| FR (027) | FR (008) | CAP | Tramo | Test o entrada |
|---|---|---|---|---|
| FR-001 | FR-092 | 025 | A (descripción), B (guía) | `TestJobStatusSubJobs.test_descripcion_*` (`tests/test_tools_supervisor.py`); `TestGuiaJobs` (`tests/test_tools_guide.py`) |
| FR-002 | FR-092, FR-020 | 025 | A | `TestChildJobErrors` (`tests/test_supervisor_jobs.py`), `TestJobStatusSubJobs` (`tests/test_tools_supervisor.py`) |
| FR-003 | FR-093 | 026 | B | hoja de ruta; `TestCimdPorDefecto` (`tests/test_deprecaciones.py`) |
| FR-004 | FR-094 | 028 | A (test), B (texto) | `TestOutputSchemaDeclarado` (`tests/test_sdk_deprecaciones.py`); research R-6 y hoja de ruta |
| FR-005 | FR-094, FR-020 | 028 | A | `TestSinDeprecacionesDelSdk` (`tests/test_sdk_deprecaciones.py`) |
| FR-006 | FR-095 | 029 | B | `tests/test_translations.py` |
| FR-007 | FR-095, FR-020 | 029 | B | `TestTerminologiaApps` (`tests/test_tools_supervisor.py`), `TestGuiaApps` (`tests/test_tools_guide.py`) |
| FR-008 | FR-096, FR-020 | 030, 031 | A (tests), B (hoja de ruta) | `TestDeprecadasSiguen` (`tests/test_deprecaciones.py`) |
| FR-009 | FR-096 | 030 | A | `TestComandoRetiradoEnHA` (`tests/test_tools_registry_device.py`) |
| FR-010 | FR-096, FR-020 | 030 | A | `TestDispositivosSinCamposDeprecados` (`tests/test_deprecaciones.py`) |
| FR-011 | FR-097 | 032, 033 | A | `tests/test_supervisor_platform.py`; `TestArranqueComprobarPlataforma` (`tests/test_main_wiring.py`) |
| FR-012 | FR-097 | 032, 033 | B | hoja de ruta («1.3.0 y posteriores») |
| FR-013 | FR-096, FR-097 | 030–033 | B | hoja de ruta («Deprecaciones con fecha») |
| FR-014 | FR-020 | — | A | test de registro y de esquemas existentes; regenerar la tabla |
| FR-015 | FR-023, FR-024 | — | B | CHANGELOG, hoja de ruta, DOCS, README, matriz |
| FR-017 | FR-092 | 025 | A | `TestSondeoSubJobs` (`tests/test_supervisor_jobs.py`) |
| FR-016 | FR-018, FR-019, FR-021 | — | A y B | centinela en `TestChildJobErrors`; controles negativos en los commits |

## Seguimiento de complejidad

Sin violaciones de la constitución que justificar.
