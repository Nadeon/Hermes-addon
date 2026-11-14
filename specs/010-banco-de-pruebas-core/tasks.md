---

description: "Tareas del banco de pruebas de Core (spec 010)"
---

# Tareas: banco de pruebas de Core (infraestructura y helpers)

**Entrada**: `specs/010-banco-de-pruebas-core/` (spec.md, plan.md,
research.md, data-model.md, contracts/supervisor-simulado.md,
contracts/job-banco.md, quickstart.md).

**Tests**: obligatorios y antes del código (principios VI y VII). Estilo de la
suite: `unittest.IsolatedAsyncioTestCase`, servidores `aiohttp` locales en
`127.0.0.1`, cliente MCP en memoria. Datos genéricos (principio VIII). Los
tests de la suite normal corren en Windows y en Linux; los de `tests/banco/`
solo en el job `banco de Core`.

**Cómo se ejecuta la suite en local** (Git Bash, desde la raíz del worktree):
`export MSYS_NO_PATHCONV=1` y
`HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" <venv>/Scripts/python.exe -m pytest -q -p no:cacheprovider`.
Referencia: fallan exactamente los 6 tests conocidos de Windows.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 HA real y conexión como en producción, US2 escrituras
de helpers, US3 sin Docker, US4 sin credenciales en los logs.

## Tramos de implementación

Cada tramo lo hace un agente nuevo. Al terminar su tramo: suite local con
exactamente los 6 fallos conocidos; push de la rama y CI en verde
(`gh run watch`); un commit propio (o varios, pero el tramo se puede
revertir de una vez) con los recuentos de los controles negativos.

| Tramo | Tareas | Resultado |
|---|---|---|
| **A — infraestructura y humo** | T001–T022 | Job `banco de Core` en verde ejecutando los tests de humo; simulado, onboarding, entorno y lector probados en la suite normal |
| **B — helpers** | T023–T035 | Las 47 tools de helpers ejecutadas en el banco; inventario de cobertura; documentación final |

---

# TRAMO A — infraestructura y humo (T001–T022)

## Fase 1: Preparación

- [x] T001 Línea base: ejecutar la suite completa en local sobre la punta de `feat/010-banco-de-pruebas-core` (esperado: los 6 fallos conocidos de Windows) y, si la rama ya se empujó, comprobar con `gh run list --branch feat/010-banco-de-pruebas-core` el último CI; anotar los recuentos para el commit
- [x] T002 [P] Registrar el marcador en `pytest.ini`: `markers = banco: test contra HA Core real; solo corre en el job banco-core del CI`, con un comentario del porqué (plan §9)
- [x] T003 [P] Crear `tests/banco/ha_config/configuration.yaml` según research R-2: `homeassistant:` con nombre genérico, la ubicación de ejemplo de HA, `time_zone: Etc/UTC`, `unit_system: metric`, `country`, `currency`; `http:`, `api:`, `websocket_api:`, `config:`, `onboarding:`, `logger: {default: warning}`; y `input_boolean:`, `input_button:`, `input_datetime:`, `input_number:`, `input_select:`, `input_text:`, `counter:`, `timer:`, `schedule:`, `zone:`, `person:`. Comentario de cabecera: por qué no hay `default_config:` y que las sub-features añaden aquí sus dominios (FR-002)

## Fase 2: Fundacional — piezas del banco probadas sin HA (bloquea US1 y US2)

- [x] T004 Crear el doble de Core `tests/banco/core_doble.py` (plan §2): servidor `aiohttp` en `127.0.0.1` con `GET /api/onboarding`, `POST /api/onboarding/users` (devuelve `auth_code`; responde 403 «User step already done» la segunda vez), `POST /auth/token` (formulario), `POST /api/onboarding/{core_config,analytics,integration}` (exigen Bearer), `GET /api/config` (con `state` configurable: `NOT_RUNNING` durante N sondeos y luego `RUNNING`), `GET /api/`, `GET|POST|DELETE /api/eco/{ruta}` (devuelve método, ruta, query, `Content-Type` y token recibido), y `/api/websocket` con fase de auth, `auth/long_lived_access_token` y eco de cualquier otro comando. Guarda en una lista los tokens y comandos recibidos para que los tests los comprueben (nunca los cuerpos de `/api/onboarding/users` ni de `/auth/token`)
- [x] T005 Tests en `tests/test_banco_onboarding.py` contra el doble (deben fallar al principio): (a) `preparar_core` hace los pasos en el orden de research R-3 y termina con un token de larga duración; (b) `client_id` es la URL base con barra final y `redirect_uri` tiene el mismo esquema y `netloc`; (c) espera a `state: RUNNING` y, con el doble en `NOT_RUNNING` más allá del tope (tope bajo en el test), lanza `BancoNoDisponible` que nombra el paso; (d) un paso que devuelve 403 lanza `BancoNoDisponible` con el paso y el estado y sin el cuerpo; (e) con el log capturado (`structlog.testing.capture_logs` y `caplog`) y el mensaje de la excepción, ni la contraseña generada ni ningún token aparecen (centinela: se parchea `secrets.token_urlsafe` para conocer los valores); (f) `repr(CredencialesCore)` no contiene el token (FR-003, FR-012)
- [x] T006 Implementar `tests/banco/onboarding.py` (plan §3, research R-3): `preparar_core(core_url, *, timeout_http=300, timeout_running=180) -> CredencialesCore`, `BancoNoDisponible(paso, estado)`; credenciales con `secrets.token_urlsafe`; sondeo cada 2 s; sin `print`; comentarios con el porqué (cuatro pasos por FR-013 de la 008, token de larga duración porque el de acceso caduca a los 30 min). Pasan los tests de T005
- [x] T007 Control negativo de T005/T006: (1) sin la espera a `RUNNING` cae (c); (2) registrando el cuerpo de la respuesta en el error cae (e); (3) con `client_id` sin barra final cae (b). Restaurar y anotar los recuentos
- [x] T008 Tests de contrato en `tests/test_banco_supervisor_simulado.py` contra el doble, todos los de la sección «Tests de contrato» de `contracts/supervisor-simulado.md`: ping sin token; `/core/info` con y sin token (forma `{"result": "ok", "data": {"version": …}}`); REST `GET`/`POST`/`DELETE` llegan al doble con el token de Core y **no** con el de add-on; `PUT` y `PATCH` → 405; `hassio/…` y `hassio_…` → 403 sin llegar al doble; ruta desconocida → 404 con `result: error`; WebSocket: `auth_required` con `ha_version`, `auth_ok`/`auth_invalid`, comando normal ida y vuelta, `supervisor/info`, `hassio/x` y una lista JSON que contiene uno de ellos → `unauthorized` y nada llega al doble; cierre del cliente cierra el lado de Core (FR-004)
- [x] T009 Implementar `tests/banco/supervisor_simulado.py` (plan §4) según el contrato: `crear_app(core_url, token_addon, token_core, version_core)` y un arrancador en puerto libre de `127.0.0.1`; comentarios que citan `supervisor/api/proxy.py` del Supervisor 2026.11.0 (`CORE_API_DENY`, `DENIED_WS_TYPE_PREFIXES`, auth de 10 s, métodos del proxy). Pasan los tests de T008
- [x] T010 Control negativo de T008/T009: (1) sin la comprobación del token de add-on caen los de 401/`auth_invalid`; (2) sin el filtro de `supervisor/`/`hassio/` caen los de `unauthorized`; (3) aceptando `PUT` cae el de 405; (4) reenviando el token del cliente a Core cae el de «llega con el token de Core». Restaurar y anotar
- [x] T011 Tests en `tests/test_banco_entorno.py` (FR-007, tabla de `data-model.md`): sin `HERMES_BANCO_HA_URL` → `skipTest` cuyo motivo nombra `HERMES_BANCO_HA_URL` y el job `banco-core`; con `HERMES_BANCO_OBLIGATORIO=1` y sin URL → fallo con el mismo motivo; con URL a un puerto cerrado de `127.0.0.1` (topes bajos en el test) → fallo, nunca salto; con URL y onboarding que falla (doble devolviendo 500) → fallo, nunca salto, y una segunda petición del entorno repite el mismo fallo sin reintentar el onboarding; con el doble sano, `obtener_entorno()` devuelve el mismo objeto en dos llamadas y su `repr` no contiene tokens. Entorno parcheado con `unittest.mock.patch.dict(os.environ, …)`
- [x] T012 Implementar `tests/banco/entorno.py` (plan §5): `motivo_sin_banco`, `exigir_banco(test_case)`, `obtener_entorno()` (hilo con su bucle, cerrojo, `atexit`), `EntornoBanco` sin tokens en `repr`, `hermes_conectado(entorno)` (HAClient con `supervisor_url` y `token_addon`, `start(timeout_seconds=30)`, `__main__._build_mcp(HermesConfig(), ha_client)`, `mcp.Client` en memoria) y `llamar`/`confirmar`. Implementar `tests/banco/lector.py` (plan §6, `data-model.md`): `listar`, `estado`, `esperar` (0,25 s, tope 10 s, falla con el último valor visto), `servicios_llamados`, `crear`, `borrar`. Pasan los tests de T011
- [x] T013 Control negativo de T011/T012: (1) con la obligatoriedad ignorada cae el de «falla en vez de saltarse»; (2) reintentando el onboarding en cada llamada cae el de «mismo fallo sin reintentar»; (3) con el token en `repr` cae el suyo. Restaurar y anotar

## Fase 3: Historia 1 — El CI arranca una HA real y Hermes se conecta como en producción (P1) 🎯 MVP

**Objetivo**: job `banco de Core` en verde con HA Core 2026.11.1 y los tests de humo.
**Prueba independiente**: push → el job arranca HA, hace el onboarding y pasa el humo.

- [x] T014 [US1] Tests en `tests/test_banco_workflow.py` (suite normal; deben fallar al principio): cargar `.github/workflows/tests.yml` con `yaml.safe_load`; existe el job `banco-core` con `name: banco de Core`, sin `continue-on-error`, con `timeout-minutes` ≤ 20, `runs-on: ubuntu-latest`; `env.HA_IMAGEN` casa con `^ghcr\.io/home-assistant/home-assistant:(?P<tag>[0-9.]+)@sha256:[0-9a-f]{64}$` y `tag == HA_CORE_LAST_TESTED` de `hermes.config`; algún paso ejecuta `pytest -m banco` con `--timeout=120`, `HERMES_BANCO_HA_URL` y `HERMES_BANCO_OBLIGATORIO: "1"` en su `env`; el paso de descarga reintenta `docker pull` (al menos 3 intentos); hay un paso `if: failure()` con `docker logs` y uno `if: always()` que elimina el contenedor; y `pytest.ini` declara el marcador `banco` (FR-001, FR-010, FR-011)
- [x] T015 [US1] Añadir el job `banco-core` a `.github/workflows/tests.yml` exactamente según `contracts/job-banco.md` (14 pasos, `HA_IMAGEN` con el digest de research R-1, red `hermes-banco` sin salida con la regla de `DOCKER-USER` sobre la subred leída de `docker network inspect`, comprobación de red con el `python3` de la imagen, espera de 300 s, `pytest -m banco tests/banco -q -p no:cacheprovider --timeout=120`, comprobación de `/data`, logs de HA solo si falla, limpieza siempre). Comentarios en español con el porqué de cada decisión. El job `pytest` no cambia. Pasan los tests de T014
- [x] T016 [US1] Control negativo de T014: (1) `HA_IMAGEN` solo con etiqueta, sin digest → cae; (2) etiqueta `2026.11.0` → cae (desfase con `HA_CORE_LAST_TESTED`); (3) `continue-on-error: true` → cae; (4) sin `HERMES_BANCO_OBLIGATORIO` en el paso → cae. Restaurar y anotar
- [x] T017 [US1] Tests de humo en `tests/banco/test_banco_humo.py` (`pytestmark = pytest.mark.banco`; cada clase llama a `exigir_banco` en `setUpClass`): (a) `network._ping_supervisor(supervisor_url, token_addon)` es `True`; (b) `smoke_check_ha_core_version(supervisor_url, token_addon, HA_CORE_MIN_SUPPORTED, HA_CORE_LAST_TESTED)` devuelve `HA_CORE_LAST_TESTED`; (c) con `hermes_conectado`, `ha_client.ready` y `ha_get_states` por MCP devuelve una lista no vacía (al menos la persona del usuario de onboarding); (d) `ha_list_services` incluye el dominio `input_boolean`; (e) el lector crea un `input_boolean` genérico, `ha_call_service` (`input_boolean.turn_on`) por MCP lo enciende y el lector lo ve `on`; limpieza en `asyncTearDown`; (f) REST con token de add-on erróneo → 401 y WebSocket → `auth_invalid` (contra el simulado del entorno); (g) por la WebSocket del simulado, `supervisor/info` → `unauthorized` (FR-004, FR-005, FR-008 parte de humo)
- [x] T018 [US4] En `tests/banco/test_banco_humo.py`, test de privacidad: con el log capturado (`structlog.testing.capture_logs` y `caplog`) durante un `hermes_conectado` completo con una llamada a tool, ni `token_addon` ni `token_core` aparecen; y `repr(obtener_entorno())` tampoco los muestra (FR-012, SC-005)
- [x] T019 [US3] Comprobar en local: la suite completa da los 6 fallos conocidos y los tests de `tests/banco/` saltados con el motivo de FR-007 (`pytest -rs`); con `HERMES_BANCO_OBLIGATORIO=1` fallan (SC-004). Anotar el recuento
- [x] T020 [US1] Push de la rama y `gh run watch` del workflow `Tests`: `pytest (3.12)`, `pytest (3.13)` y `banco de Core` en verde; en el log del banco, los tests de humo ejecutados y ninguno saltado, la comprobación de red superada, ninguna credencial; anotar la duración del job (SC-006). Si falla, `gh run view --log-failed`, corregir y repetir
- [x] T021 [US1] Control negativo del banco en CI (research R-9): en la rama desechable `prueba/010-control-a`, el simulado deja de reenviar los mensajes de la WebSocket de Core al cliente; push, `gh run watch` hasta ver en rojo el job `banco de Core` con los tests de humo de (c)–(e) caídos; borrar la rama remota y la local. Anotar el resultado
- [x] T022 Documentación parcial y commit del tramo A: `CONTRIBUTING.md` y `CONTRIBUTING.es.md` (en «CI tiene que quedar en verde» y en la sección de la suite: el check `banco de Core`, qué hace, que en local se salta con motivo y cómo reproducirlo con Docker según `quickstart.md`); `docs/HOJA-DE-RUTA.md`, fila 010 → «en curso (tramo A: infraestructura y humo)»; `hermes/CHANGELOG.md`, sección «Banco de pruebas» en `## [1.2.0] — <fecha de publicación>` (si la entrada no existe aún en la base, crearla con esa cabecera exacta y solo esta sección; ver plan §10) con la infraestructura. Revisar el diff buscando datos personales e identificadores de modelos; `git add` por ruta; commit con los recuentos de T007, T010, T013, T016 y T021

### Notas del tramo A (al implementar)

- **T001, línea base**: 6 fallos conocidos de Windows, 1925 pasados, 16
  saltados; la rama no estaba empujada. Al terminar el tramo: los mismos 6
  fallos, 1970 pasados, 25 saltados (los 9 del banco, con su motivo).
- **Disparadores**: el job corre en los mismos eventos que el resto de
  `tests.yml` (push, pull request y la ejecución semanal), sin filtro propio,
  como decidió el supervisor del programa.
- **Contrato del simulado**: a una lista JSON con un comando reservado el
  Supervisor real responde **una sola vez** con `id: null` (no una por
  comando); el simulado replica al real y el contrato se corrigió.
- **`exigir_banco()`** no recibe el caso de test: lanza `SkipTest` o
  `AssertionError`, que valen igual en `setUpClass` y en `setUp`, y devuelve el
  entorno.
- **Comprobación de red** del job, fail-closed: solo un error de red cuenta
  como «sin salida»; si falta `python3` o el script falla por otra cosa, el
  paso falla.
- **T021 en la propia rama**: el encargo no permitía empujar otras ramas, así
  que el push de control fue un commit en `feat/010-banco-de-pruebas-core`
  revertido en el commit siguiente (run 43633707844: `banco de Core` en rojo
  con 4 de 9 tests del humo caídos por `HAConnectionError`; los jobs `pytest`,
  en rojo con 3 tests de contrato del simulado).
- **Duración del job** `banco de Core`: unos 60 s (descarga de la imagen,
  ~25 s; los 9 tests, ~3 s).

---

# TRAMO B — helpers (T023–T035)

## Fase 4: Historia 2 — Las escrituras de helpers se ejecutan de verdad (P1)

**Objetivo**: las 47 tools de `data-model.md` ejecutadas en el banco con su efecto comprobado.
**Prueba independiente**: el job del banco ejecuta los 47 casos; el invariante de cobertura pasa en la suite normal.

- [x] T023 [US2] Tests en `tests/test_banco_cobertura.py` (suite normal; deben fallar al principio): para cada módulo de `MODULOS_HELPERS`, llamar a su `register(mcp, ha_client)` con un `DummyMCP` que recoge los nombres y un `MagicMock` como cliente, y quedarse con las que no son `ha_list_*` ni `ha_get_*`; comprobar que todas están también en el registro de producción (`__main__._build_mcp(HermesConfig(), MagicMock())`); comprobar que es exactamente `PROBADAS_EN_BANCO ∪ NO_EJECUTABLES`, que las dos partes son disjuntas, que cada `NO_EJECUTABLES` tiene un motivo no vacío y que hay 47; el mensaje de fallo nombra las tools que sobran o faltan. Comprobar además que cada nombre de `PROBADAS_EN_BANCO` aparece en algún `tests/banco/test_banco_helpers_*.py` (FR-009)
- [x] T024 [US2] Crear `tests/banco/cobertura.py` con `DOMINIOS_HELPERS`, `MODULOS_HELPERS`, `PROBADAS_EN_BANCO` (las 47 de `data-model.md`) y `NO_EJECUTABLES = {}`, con un comentario que explica el invariante y que la 028 tendrá su propia lista
- [x] T025 [P] [US2] `tests/banco/test_banco_helpers_input.py` (`pytestmark = pytest.mark.banco`), 23 tools de `input_boolean`, `input_button`, `input_datetime`, `input_number`, `input_select` e `input_text` según la tabla de `data-model.md`: por dominio, crear en dos pasos (tras la vista previa el lector no ve nada; tras confirmar ve la configuración pedida), editar en dos pasos (el lector ve el elemento **reemplazado**), cada acción sobre el valor con su estado esperado (por `lector.esperar`), y borrar en dos pasos; nombres `banco_<dominio>_<hex>`; limpieza con `lector.borrar` en `asyncTearDown`
- [x] T026 [P] [US2] `tests/banco/test_banco_helpers_tiempo.py`, 18 tools de `counter`, `timer` y `schedule`: igual que T025; además `ha_reload_counters`, `ha_reload_timers` y `ha_reload_schedules` en dos pasos con `lector.servicios_llamados()` viendo `<dominio>.reload` y el helper todavía en la lista; `ha_finish_timer` con el evento `timer.finished` visto en el bus; `ha_change_timer` sobre un temporizador activo con `remaining` cambiado en el sentido pedido
- [x] T027 [P] [US2] `tests/banco/test_banco_helpers_lugares.py`, 6 tools de `zone` y `person`: zona con coordenadas de ejemplo; `ha_reload_zones` como en T026; persona con nombre inventado (`ha_create_person` sin token, `ha_update_person` y `ha_delete_person` en dos pasos); la persona del usuario de onboarding sigue en `person/list` al terminar
- [x] T028 [US2] Control negativo local del inventario (T023/T024): quitar una tool de `PROBADAS_EN_BANCO` → cae y la nombra; añadir a `NO_EJECUTABLES` una tool que no existe → cae; vaciar el motivo de una entrada de prueba → cae. Restaurar y anotar
- [x] T029 [US2] Push y `gh run watch`: los tres jobs en verde; en el log del banco, humo más los tests de las 47 tools ejecutados y ninguno saltado; anotar la duración del job (SC-001, SC-002, SC-006). Si falla, `gh run view --log-failed`, corregir y repetir
- [x] T030 [US2] Control negativo del banco en CI (research R-9): en la rama desechable `prueba/010-control-b`, `ha_increment_counter` llama a `counter.decrement` en `hermes/src/hermes/tools/counter.py`, y la vista previa de `ha_create_or_update_input_boolean` crea el helper sin esperar al token (llamando al create antes de devolver la vista previa); push, `gh run watch` hasta ver en rojo los dos tests correspondientes del job `banco de Core`; borrar la rama remota y la local. Este cambio de producto nunca entra en la rama de la sub-feature. Anotar el resultado

## Fase 5: Documentación y cierre

- [x] T031 [P] `docs/HOJA-DE-RUTA.md`: fila 010 → «hecha»; la frase de la cabecera sobre las 124 tools dice que, además de las de dashboards, las 47 de helpers se ejecutan en el CI contra HA Core 2026.11.1 real; lista de las 47 tools ejecutadas en el banco y lista (vacía) de no ejecutables con motivo (FR-008, FR-009, FR-013)
- [x] T032 [P] `hermes/CHANGELOG.md`: completar la sección «Banco de pruebas» de `## [1.2.0]` (job `banco de Core`, HA Core 2026.11.1 por digest, Supervisor simulado, 47 tools de helpers ejecutadas, cómo se salta en local); `specs/008-cobertura-total/plan.md`: en la matriz de trazabilidad, filas CAP-005 y CAP-034, la columna de test con `tests/banco/test_banco_humo.py` y `tests/banco/test_banco_helpers_*.py` (FR-013)
- [ ] T033 (PENDIENTE DEL MANTENEDOR) Tarea del mantenedor, no la ejecutan los agentes: añadir el check `banco de Core` a los checks obligatorios del ruleset del repositorio; la constitución lo nombrará con la enmienda E-3 en la 011. El agente del tramo B la deja escrita en el mensaje del commit como pendiente (FR-010)
- [x] T034 Verificación final: `git diff --stat <base>..HEAD -- hermes/` solo muestra `hermes/CHANGELOG.md` (SC-003); suite local con los 6 fallos conocidos y los del banco saltados con motivo (SC-004); revisión del diff completo de la sub-feature buscando datos personales, rutas locales e identificadores de modelos (FR-012, principio VIII)
- [x] T035 Commit del tramo B (`git add` por ruta) con los recuentos de T028 y T030, la duración del job y la tarea pendiente T033

### Notas del tramo B (al implementar)

- **Resultado**: run 43635462583 en verde (`pytest (3.12)`, `pytest (3.13)` y
  `banco de Core`); en el banco, 20 tests pasados y 1 `xfail` (los 9 del humo
  más 11 de helpers), ninguno saltado. Job de unos 65 s (los tests, ~6 s).
  Suite local: los 6 fallos conocidos de Windows, 1979 pasados, 37 saltados
  (los 21 del banco con su motivo).
- **HALLAZGO**: `ha_reload_counters` falla contra HA real. HA Core 2026.11.1 no
  registra `counter.reload` (solo `increment`, `decrement`, `reset` y
  `set_value`); Core responde 400 y la tool acaba en «Error executing tool».
  Sigue en `PROBADAS_EN_BANCO` (se ejecuta) y está aislada en
  `TestCounter.test_recarga` como `xfail` estricto. No se toca el producto en
  este tramo; anotado en la hoja de ruta para decidir dónde se arregla.
  Quedan probadas en verde 46 de las 47.
- **Datos del banco que HA impone**: `counter.set_value` exige un múltiplo del
  `step` (si no, 500); el `timer` guarda la duración como `H:MM:SS`. Los tests
  usan esos formatos.
- **Arnés**: `llamar` falla si la tool devuelve `is_error` y reconstruye las
  listas (una llamada a servicio devuelve los estados cambiados, un bloque de
  contenido por elemento, a menudo ninguno); la sesión de helpers saca el error
  del `ExceptionGroup` del cliente MCP. El lector gana `eventos(tipo)` para ver
  `timer.finished`. Cada test abre lector y Hermes en un único `async with`
  (anyio exige abrir y cerrar el grupo de tareas en la misma tarea).
- **T028**: (1) quitar `ha_reset_counter` de `PROBADAS_EN_BANCO` → cae
  `test_inventario_exacto` y la nombra; (2) `NO_EJECUTABLES` con
  `ha_no_existe` → cae el mismo test («declaradas que no existen»); (3) motivo
  vacío → cae `test_motivos_no_vacios`. Restaurado: 6 pasados.
- **T030 en la propia rama**, como T021: el encargo no permite empujar otras
  ramas. Commit de control 0ad04b9 revertido en el siguiente; run 43635629062:
  `banco de Core` en rojo con exactamente `TestInputBoolean` y `TestCounter`;
  los `pytest`, con `test_tools_counter.py::test_increment`. La vista previa
  que crea sin token no la detecta ningún test de la suite normal; solo el
  banco.
- **T033** queda para el mantenedor: añadir `banco de Core` a los checks
  obligatorios del ruleset.

---

## Dependencias

- T002 y T003 en paralelo; T004 antes que T005, T008 y T011.
- Fase 2: T005 → T006 → T007; T008 → T009 → T010; T011 → T012 → T013. T012
  usa `onboarding.py` (T006) y `supervisor_simulado.py` (T009).
- US1: T014 → T015 → T016; T017 y T018 dependen de T012; T019 tras T017;
  T020 tras T015, T017 y T018; T021 tras T020; T022 cierra el tramo A.
- Tramo B depende del tramo A entero (entorno, lector y job).
- US2: T023 → T024; T025, T026 y T027 en paralelo tras T024 (ficheros
  distintos); T028 tras T024; T029 tras T025–T027; T030 tras T029.
- T031 y T032 en paralelo tras T029; T034 y T035 al final. T033 queda para el
  mantenedor.

## Paralelismo

- Tramo A: T002 ∥ T003; tras T004, las tres parejas de test e implementación
  (T005/T006, T008/T009, T011/T012) pueden ir en paralelo hasta que T012
  necesita las otras dos; T014 ∥ T017.
- Tramo B: T025 ∥ T026 ∥ T027; T031 ∥ T032.

## Estrategia

MVP = tramo A: con él, el CI ya arranca una HA real y Hermes se conecta a ella
como en producción, y la 011 y la 028 pueden empezar a añadir tests al banco.
El tramo B cierra la parte de helpers de FR-014 de la 008. La enmienda E-3 y
el check obligatorio del ruleset quedan fuera de los tramos (011 y
mantenedor).
