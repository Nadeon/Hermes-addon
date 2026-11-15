# Plan de implementación: configuración del sistema (021)

**Rama**: `feat/021-configuracion-del-sistema` (ya creada) | **Fecha**: 2026-11-15 | **Spec**: [spec.md](spec.md) | **Programa**: [008](../008-cobertura-total/plan.md), sub-feature 021, ola 3

## Resumen

Doce tools dedicadas nuevas en cuatro familias nuevas: `core_config`
(configuración del núcleo, CAP-053), `assistant_exposure` (exposición a
asistentes, CAP-055), `users` (usuarios, CAP-056) y `core_network` (red y
HTTP de Core, CAP-069). Tres leen; nueve escriben, siempre en dos pasos, con
vistas previas que dicen quién o qué cambia, el antes y el después y los
avisos de pérdida de acceso, de administrador nuevo, de último administrador
o de nube. Doce comandos pasan a `dedicated`; `config/core/detect` va a
`read` (FR-071 de la 008); `auth/refresh_tokens` a `deny` revisado (solo da
las sesiones del usuario de la conexión); CAP-074 se queda por la tabla con
`analytics/preferences` marcada de mundo abierto. Siete escrituras se ejecutan
en el banco con el lector; las dos de HTTP, su vista previa y su rechazo real
(aplicar reinicia la HA del banco). Tres tramos: (a) núcleo y exposición; (b)
usuarios; (c) red y HTTP, analytics y labs, y cierre.

## Dependencias y momento de la implementación

La base de la rama (`c4a57bf`) ya tiene todo lo que necesita: la 011 entera
(tabla, genéricas, familias, generador con el mecanismo de `dedicated` de la
012 y la 029), el banco de la 010 y la 028, la matriz de la 014, la 018
(`estado` en el token, `sobre_de_lista`, inventario de `allow_dangerous`), la
033 (inventario de argumentos atados), la 029 (texto de `system_status` que se
actualiza) y la 012. Ninguna dependencia pendiente. Otras sub-features de la
ola 3 tocan los mismos ficheros compartidos (`tool_families.py`,
`tools/__init__.py`, `_annotations.py`, `guide.py`, `command_table.py`,
`generar_tabla.py`, `cobertura_escrituras.py`, README, DOCS, CHANGELOG, hoja
de ruta): la que se integre después resuelve conservando las dos.

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x, aiohttp, structlog (sin dependencias nuevas) · **Almacenamiento**: ninguno nuevo (tokens de confirmación como siempre) · **Tests**: pytest con `unittest.IsolatedAsyncioTestCase`, `AsyncMock` de `ws_send`, `structlog.testing.capture_logs`, `DummyMCP`/`_RecordingMCP`; banco de Core de la 010 con lector independiente · **Plataforma**: add-on de HA OS.

**Restricciones**: fail-closed (III); token atado a argumentos y estado (IV);
anotaciones verdaderas (V); control negativo (VII); repositorio público
(VIII); cambios mínimos (IX); FR-020 de la 008 (nada de lo actual cambia).

**Escala**: 12 tools (9 que modifican, todas con token), 4 módulos, 4 familias,
4 temas de guía, 12 entradas a `dedicated`, 1 a `read`, 1 a `deny` revisado y
1 `open_world` añadido.

## Comprobación de la constitución

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Las nueve escrituras confirman siempre. Usuarios: propietario, usuario de Hermes y usuarios de sistema intocables y nunca cero administradores, comprobado en la vista previa y al confirmar, antes de llamar a HA. Contraseñas, nombres de acceso, MFA y tokens siguen fuera (clase D, D-01). HTTP: avisos de pérdida de acceso, bloqueo de reinicio de `sv_restart_core` y la prueba de 5 minutos de HA. La genérica sigue rechazando los doce comandos (`use_dedicated_tool`), también con su familia apagada. | OK |
| II. Secretos | Ninguna tool acepta ni devuelve una contraseña o un token; `config/auth/list` solo trae el tipo de credencial. Respuestas por `redact_structure` + `redact_secrets`; errores de HA redactados; log sin valores (ni coordenadas, URLs, puertos, nombres ni ids); centinelas en errores de HA y en el fichero del token (SC-006). | OK |
| III. Fail-closed | Validación antes de llamar; `auth/current_user` ilegible → las escrituras de usuarios se niegan; entidad o adaptador inexistente → error, nunca una entrada huérfana; estado cambiado entre vista previa y confirmación → nada; zona horaria primero para no aplicar a medias; los comandos solo pasan a `dedicated` cuando la tool existe. | OK |
| IV. Dos pasos, token atado | Todo lo que escribe. El token ata todos los argumentos (inventario de la 033) y el estado leído (`estado=` de la 018). Las vistas previas no mienten: dicen lo que no hacen (no cambia dónde escucha HA; sin credenciales; no sobrevive a un reinicio con YAML). | OK |
| V. Nombre y descripción | Nombres con prefijos de la casa; `ha_promote_http_config` y `ha_set_*` en `_DESTRUCTIVE_EXACT` con su porqué; mundo abierto donde HA sale a la nube (`ha_set_entity_exposure`, `ha_set_expose_new_entities`, `config/core/detect`, `analytics/preferences`). No hay `ha_list_user_sessions` porque HA no puede dar sesiones de otros usuarios (research R-5). | OK |
| VI. Lo que no se puede probar | Diez tools contra HA 2026.11.1 real en el banco con lector independiente; las dos de HTTP aplicadas reiniciarían la HA del banco: vista previa y rechazo reales en el banco, efecto en la VM (matriz de la 014, pendiente manual). | OK |
| VII. Control negativo | Uno por comportamiento con riesgo en cada tramo (T018, T035, T056): protecciones, último administrador, estado atado, zona horaria primero, fusión del HTTP, bloqueo de reinicio, redacción, tabla, inventarios del banco. Anotados en el commit de cada tramo. | OK |
| VIII. Privacidad | Fixtures con `light.salon`, `lock.puerta`, `Invitada`, `192.0.2.x`, `homeassistant.tailXXXX.ts.net`, `centinela-021`; revisión del diff en cada cierre de tramo. | OK |
| IX. Cambios mínimos | Solo las cinco CAP. No se tocan la red del host (032), las opciones de Core del Supervisor (022), personas ni la nube. El inventario de la 008 no se cambia: `auth/refresh_tokens` va por una excepción documentada del test. | OK |
| X. Comentarios en español | Comentarios y eventos del log en español; descripciones de tools y textos de vista previa en inglés, guía en español, como hoy. | OK |
| XI. Versionado | Sin subir versión (1.2.0 de la 009); sección «Sistema» en `## [1.2.0]`. | OK |
| Flujo, puerta 4 | Suite, banco, Semgrep y CodeQL en verde en el CI al cerrar cada tramo. | OK |

Tras el diseño: sin cambios. Desviaciones justificadas: FR-073 de la 008
pierde «y sus sesiones» (research R-5, duda D-1); `ha_get_expose_new_entities`
se pliega en la lista (research R-3).

## Diseño

Patrón común de las escrituras (en un helper privado de cada módulo, no en
`_common.py`, para no ampliar el alcance):

1. validar argumentos → `invalid_argument` sin llamar a HA;
2. leer el estado del objetivo (y lo necesario para las protecciones);
3. calcular el diff; sin diferencias → `no_changes`;
4. sin token → `create_confirmation_token(tool, args, preview, estado=…)`;
5. con token → releer, volver a comprobar protecciones,
   `resolve_confirmation_token(…, estado=…)`, escribir,
   `complete_confirmation_token`, releer y devolver.

### Tramo a — núcleo y exposición

1. **Familias** `core_config` y `assistant_exposure`.
2. **`tools/core_config.py`**: `ha_get_core_config` (de `get_config`) y
   `ha_update_core_config` (validación local, diff con `ha_get_core_config`,
   avisos, estado = los campos editables; al confirmar, `time_zone` sola y
   primero).
3. **`tools/assistant_exposure.py`**: `ha_list_exposed_entities`,
   `ha_set_entity_exposure` (existencia por `entity_exists`, estado = la
   exposición actual de las entidades pedidas en los asistentes pedidos) y
   `ha_set_expose_new_entities`.
4. **Registro** bajo `_activa("core_config")` y
   `_activa("assistant_exposure")`; anotaciones; `_HINTS_NUEVAS_1_2_0`.
5. **Tabla**: cinco a `dedicated`; `config/core/detect` a `read`
   (`open_world`, `_POR_LA_TABLA`); claves en `_DEDICADAS_INICIALES`;
   regenerar.
6. **Guía**: temas `core_config` (con `config/core/detect`; CAP-074 en el
   tramo c) y `assistant_exposure`.
7. **Banco**: `tests/banco/test_banco_configuracion_sistema.py` (núcleo y
   exposición; lector), `tests/banco/cobertura_021.py` y su suma al
   invariante y al job.
8. **Inventarios**: tres filas de la matriz de la 014, tres entradas del de
   argumentos atados.
9. **Documentación parcial**.

### Tramo b — usuarios

1. **Familia** `users`.
2. **`tools/users.py`**: `ha_list_users`, `ha_create_user`, `ha_update_user`,
   `ha_delete_user`, con un helper `_protecciones(usuario, usuarios,
   id_hermes, cambio)` que devuelve `protected_user`/`last_admin` o nada y se
   llama en la vista previa y al confirmar.
3. **Tabla**: cuatro a `dedicated`; `auth/refresh_tokens` a `deny` revisado
   con `_DENY_TRAS_REVISION` en el test de la clase A.
4. **Guía**: tema `users`.
5. **Banco**: `tests/banco/test_banco_usuarios.py`: ciclo completo de un
   usuario creado por la tool, rechazos del propietario/Hermes reales y vista
   previa sin efecto, todo con el lector.
6. **Inventarios** (tres filas de matriz y tres de argumentos atados) y
   **documentación parcial**.

### Tramo c — red y HTTP, analytics y labs, cierre

1. **Familia** `core_network`.
2. **`tools/core_network.py`**: `ha_update_network_config`,
   `ha_update_http_config` (fusión sobre la configuración activa, quitar
   metadatos, avisos por clave, bloqueo de reinicio con
   `check_restart_allowed_sync`), `ha_promote_http_config`.
3. **Tabla**: tres a `dedicated`; `analytics/preferences` con
   `open_world=True`; ninguna «(spec 021)».
4. **Guía**: tema `core_network`; sección CAP-074 en `core_config`; texto de
   red de `system_status` remite a `core_network`; alias `network` a
   `core_network`.
5. **Banco**: `tests/banco/test_banco_red_http.py` (red con efecto; HTTP vista
   previa y rechazo reales; lector comprueba que `http/config` no cambió) y
   `tests/banco/test_banco_analytics_labs.py` (CAP-074 y `config/core/detect`
   por las genéricas); `NO_EJECUTABLES_021`.
6. **Inventarios**: tres filas de matriz (dos `VM | pendiente` con su tanda en
   `docs/BANCO-SUPERVISOR.md`) y tres de argumentos atados.
7. **Documentación final** y matriz de la 008.

## Estructura de ficheros

```text
hermes/src/hermes/
├── tool_families.py              # core_config, assistant_exposure (a), users (b), core_network (c)
├── command_table.py              # 5 dedicated + detect read (a); 4 dedicated + refresh_tokens (b); 3 dedicated + analytics open_world (c)
└── tools/
    ├── __init__.py               # registro bajo las familias (a, b, c)
    ├── _annotations.py           # _DESTRUCTIVE_EXACT, _OPEN_WORLD (a, b, c)
    ├── guide.py                  # temas nuevos (a, b, c); system_status (c)
    ├── core_config.py            # NUEVO (a)
    ├── assistant_exposure.py     # NUEVO (a)
    ├── users.py                  # NUEVO (b)
    └── core_network.py           # NUEVO (c)
scripts/inventario/generar_tabla.py   # claves en _DEDICADAS_INICIALES (a, b, c)
tests/
├── test_tools_core_config.py          # NUEVO (a)
├── test_tools_assistant_exposure.py   # NUEVO (a)
├── test_tools_users.py                # NUEVO (b)
├── test_tools_core_network.py         # NUEVO (c)
├── test_tools_generic_commands.py     # rechazos de los 12; CAP-074 (a, b, c)
├── test_command_table.py              # test_dedicadas_de_la_021, _POR_LA_TABLA, _DENY_TRAS_REVISION (a, b, c)
├── test_tool_families.py              # las cuatro familias (a, b, c)
├── test_tools_registration.py         # _HINTS_NUEVAS_1_2_0, SC-001 (a, b, c)
├── test_tools_guide.py                # temas, alias, system_status (a, b, c)
├── test_confirmation_args_inventory.py # 9 entradas (a, b, c)
├── test_banco_cobertura_escrituras.py # suma de cobertura_021 (a)
└── banco/
    ├── cobertura_021.py                    # NUEVO (a; b, c lo completan)
    ├── cobertura_escrituras.py             # TOOLS_EXIGIDAS_DEL_JOB (a)
    ├── test_banco_configuracion_sistema.py # NUEVO (a)
    ├── test_banco_usuarios.py              # NUEVO (b)
    ├── test_banco_red_http.py              # NUEVO (c)
    └── test_banco_analytics_labs.py        # NUEVO (c)
docs/HOJA-DE-RUTA.md (matriz de la 014 y tabla del programa), docs/BANCO-SUPERVISOR.md (c),
hermes/CHANGELOG.md, hermes/DOCS.md, README.md, README.es.md,
specs/008-cobertura-total/plan.md   # (a y b parcial, c final)
```

## Trazabilidad

| FR (021) | FR (008) | CAP | Tareas | Test |
|---|---|---|---|---|
| FR-001 | FR-071 | CAP-053 | T004, T008 | `test_tools_core_config.py` |
| FR-002 | FR-071 | CAP-053 | T005, T008 | `test_tools_core_config.py` |
| FR-003 | FR-071 | CAP-053 | T011, T012 | `test_command_table.py`, `test_tools_generic_commands.py` |
| FR-004 | FR-072 | CAP-055 | T006, T009 | `test_tools_assistant_exposure.py` |
| FR-005 | FR-072 | CAP-055 | T006, T009 | `test_tools_assistant_exposure.py` |
| FR-006 | FR-072 | CAP-055 | T006, T009 | `test_tools_assistant_exposure.py` |
| FR-007 | FR-073 | CAP-056 | T021, T024 | `test_tools_users.py` |
| FR-008 | FR-073 | CAP-056 | T022, T024 | `test_tools_users.py` |
| FR-009 | FR-073 | CAP-056 | T023, T024 | `test_tools_users.py` |
| FR-010 | FR-073 | CAP-056 | T022, T023, T024 | `test_tools_users.py` |
| FR-011 | FR-073 | CAP-056 | T022, T023, T024 | `test_tools_users.py` |
| FR-012 | FR-073, FR-019 | CAP-056 | T023, T027, T028 | `test_tools_users.py`, `test_command_table.py` |
| FR-013 | FR-074 | CAP-069 | T038, T041 | `test_tools_core_network.py` |
| FR-014 | FR-074 | CAP-069 | T039, T041 | `test_tools_core_network.py` |
| FR-015 | FR-074 | CAP-069 | T040, T041 | `test_tools_core_network.py` |
| FR-016 | FR-075, FR-015 | CAP-074 | T043, T044, T048 | `test_tools_generic_commands.py`, `test_command_table.py`, `tests/banco/test_banco_analytics_labs.py` |
| FR-017 | FR-010 | CAP-004 | T007, T010, T025, T042 | `test_tool_families.py`, `test_tools_registration.py` |
| FR-018 | FR-012 | CAP-001 | T011, T012, T027, T028, T044, T045 | `test_command_table.py`, `test_generar_tabla.py`, `test_tools_generic_commands.py` |
| FR-019 | FR-018 | — | T007, T010, T025, T042 | `test_tools_registration.py` |
| FR-020 | FR-018, FR-019, FR-020 | — | T004–T006, T021–T023, T038–T040 | `test_tools_*.py` de cada módulo |
| FR-021 | FR-019, FR-021 | CAP-011 | ídem | ídem (log capturado) |
| FR-022 | FR-011, FR-018 | CAP-008 | T013, T029, T046 | `test_tools_guide.py` |
| FR-023 | FR-015 | CAP-034 | T014, T015, T030, T031, T047, T048 | `tests/banco/test_banco_*.py`, `test_banco_cobertura_escrituras.py`, `test_matriz_pruebas.py` |
| FR-024 | FR-016 | CAP-034, CAP-035 | T016, T032, T049 | `test_matriz_pruebas.py`, `test_confirmation_args_inventory.py`, `test_allow_dangerous_inventario.py` |
| FR-025 | FR-023, FR-024 | — | T017, T034, T050, T051 | `TestToolCountInDocs`; revisión |

## Tramos

| Tramo | Tareas | Tools | Tabla |
|---|---|---|---|
| a — núcleo y exposición | T001–T019 | 5 (`ha_get_core_config`, `ha_update_core_config`, `ha_list_exposed_entities`, `ha_set_entity_exposure`, `ha_set_expose_new_entities`) | 5 a `dedicated`; `config/core/detect` a `read` |
| b — usuarios | T020–T036 | 4 (`ha_list_users`, `ha_create_user`, `ha_update_user`, `ha_delete_user`) | 4 a `dedicated`; `auth/refresh_tokens` a `deny` revisado |
| c — red y HTTP, analytics y labs, cierre | T037–T057 | 3 (`ha_update_network_config`, `ha_update_http_config`, `ha_promote_http_config`) | 3 a `dedicated`; `analytics/preferences` `open_world` |

Cada tramo cabe en el contexto de un agente: el a, cinco tools sencillas (dos
escrituras con un mismo patrón); el b, cuatro con la lógica de protecciones
(el más delicado, por eso va solo); el c, tres tools, cuatro entradas ya
revisadas y el cierre de la documentación.

## Riesgos

- **Conflictos con otras sub-features de la ola 3** en los ficheros
  compartidos: cambios en sitios distintos; se conservan los de las dos.
- **La HA del banco no tiene usuarios de sistema**: la protección de los de
  sistema queda en unitarios (casos límite).
- **El banco tiene la ubicación en YAML**: el cambio del núcleo se aplica en
  memoria y se guarda, pero un reinicio lo pisaría; el banco no reinicia y
  cada test restaura en `finally`.
- **`labs/list` vacía en el banco**: se prueba el `not_found` real de
  `labs/update` y se anota.
- **Aplicar HTTP en la VM**: las dos de HTTP quedan pendientes manuales hasta
  la prueba en la VM; su vista previa y su rechazo sí se ven en el banco.
