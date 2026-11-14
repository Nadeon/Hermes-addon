# Plan de implementación: banco de pruebas de Core (infraestructura y helpers)

**Rama**: `feat/010-banco-de-pruebas-core` (no se crea ninguna) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md) | **Programa**: [008](../008-cobertura-total/plan.md), sub-feature 010, ola 0

## Resumen

Un job nuevo del CI, `banco de Core`, arranca HA Core 2026.11.1 (imagen fijada
por digest) en un contenedor sin salida a internet, con una configuración
mínima versionada. Desde pytest, un onboarding automático crea el usuario y un
token de larga duración; un **Supervisor simulado** en `tests/banco/` replica
el proxy del Supervisor real hacia Core; Hermes se conecta a él exactamente
como en producción (`HAClient` con la URL del Supervisor y un token de add-on)
y las tools se invocan por el servidor MCP real. El efecto de cada escritura lo
comprueba un **lector independiente** que habla directamente con Core. En este
cambio se ejecutan las 47 tools que modifican de los 11 dominios de helpers.
Sin cambios en el código de producto: en `hermes/` solo cambia `CHANGELOG.md`.

Decisiones y alternativas en [research.md](research.md); piezas en
[data-model.md](data-model.md); contratos del job y del simulado en
[contracts/](contracts/); validación en [quickstart.md](quickstart.md).

## Contexto técnico

**Lenguaje**: Python 3.13 (job del banco); la suite normal, 3.12 y 3.13 · **Dependencias**: las de `hermes/requirements.txt` (aiohttp, `mcp` 2.x, structlog…) y las de test del CI (pytest, pytest-asyncio, aioresponses); nueva solo en el job del banco: `pytest-timeout` · **Almacenamiento**: ninguno nuevo; el contenedor de HA vive lo que dura el job · **Tests**: `unittest.IsolatedAsyncioTestCase`, dobles `aiohttp` locales, cliente MCP en memoria (`mcp.Client`) · **Plataforma**: GitHub Actions `ubuntu-latest` con Docker; en local, cualquier sistema (los tests del banco se saltan).

**Restricciones**: sin cambios en `hermes/` salvo `CHANGELOG.md` (FR-006); credenciales solo en memoria (II, VIII); fail-closed en el job: un salto es un fallo (III); el simulado no puede ser más permisivo que el Supervisor real (research R-5).

**Escala**: unos 9 ficheros nuevos en `tests/` y `tests/banco/`, una configuración de HA, un job en `tests.yml`, `pytest.ini`, cuatro documentos.

**Imagen**: `ghcr.io/home-assistant/home-assistant:2026.11.1@sha256:6785d1eca68747a524c156faae1b139ed415c07357386ae6fe17291986e59e82` (índice multiplataforma; research R-1).

## Comprobación de la constitución

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | El banco no añade ninguna vía a producción: la URL base sigue entrando solo como argumento interno y no hay variable de entorno nueva en el add-on (FR-006). El simulado replica los filtros del Supervisor real (`supervisor/`, `hassio/`, `hassio_`), para no dar por buena una llamada que el real rechaza. | OK |
| II. Secretos | Contraseña y tokens generados con `secrets`, solo en memoria; `__repr__` sin tokens; errores con paso y código, nunca cuerpos; test con el log capturado sobre un arranque completo (FR-003, FR-012). | OK |
| III. Fail-closed | En el job, falta de configuración, HA caída u onboarding fallido son fallos, nunca saltos; pytest sin tests recogidos (código 5) falla; ruta desconocida del simulado → 404 visible (FR-007, FR-011). | OK |
| IV. Dos pasos, token atado | Las tools con token se ejecutan en sus dos pasos contra HA real y se comprueba que la vista previa no cambia nada (FR-008). No cambia la confirmación. | OK |
| V. Nombre y descripción | No cambia ninguna tool. El banco es la primera comprobación automática, contra HA real, de que las 47 tools hacen lo que dice su descripción. | OK |
| VI. Lo que no se puede probar | Es el objetivo: «la suite corre contra las mismas versiones que se despliegan» se cumple para Core; un test ata la versión de la imagen a `HA_CORE_LAST_TESTED` (FR-001). | OK |
| VII. Control negativo | Locales para la suite normal; para el banco, push de control a una rama desechable que el CI pone en rojo, una vez por tramo, anotado en el commit (FR-014, research R-9). | OK |
| VIII. Privacidad | Configuración de HA y datos de prueba genéricos (ubicación de ejemplo de HA, `banco_<dominio>_<hex>`); subred de Docker leída en el job, no escrita; diff revisado antes de cada commit. | OK |
| IX. Cambios mínimos | Solo helpers (el resto, 028); el simulado solo con las rutas que se usan; nada de la 014 ni de la 011. Lo que necesiten otras sub-features lo añaden ellas (contrato del job). | OK |
| X. Comentarios en español | Comentarios del simulado, del onboarding y del workflow con el porqué (fidelidad con el real, salida a internet, esperas). | OK |
| XI. Versionado | No sube versión (lo hace la 009). Sección «Banco de pruebas» en la entrada `## [1.2.0] — <fecha de publicación>` del CHANGELOG (FR-013). **Desviación transitoria**: la constitución pide `AAAA-MM-DD`; la cabecera provisional es la que fija FR-022 de la 008 para todo el programa y la cubre la enmienda E-4, que aplica la 011. La 010 solo la crea si la 009 aún no lo ha hecho, con el mismo texto exacto, y la fecha real se pone al publicar. | Justificada, depende de 011 (E-4) |
| Flujo, puerta 4 | **Desviación transitoria**: el job nuevo es un check más del CI, pero la puerta 4 todavía no lo nombra. Se justifica: la enmienda E-3 de la 008 lo añade y se aplica en la 011, antes de su código; hasta entonces el job ya falla en rojo y bloquea igual en la práctica. Añadirlo a los checks obligatorios del ruleset es una acción del mantenedor (T033). | Justificada, depende de 011 |

Tras el diseño: sin cambios en la tabla.

## Diseño

### 1. Configuración de HA — `tests/banco/ha_config/configuration.yaml`

Según research R-2: núcleo con ubicación de ejemplo y `Etc/UTC`; `http:`,
`api:`, `websocket_api:`, `config:`, `onboarding:`, `logger:` (`warning`) y los
11 dominios de helpers. Un comentario de cabecera dice por qué no hay
`default_config:` y que las sub-features añaden dominios aquí.

### 2. Doble de Core — `tests/banco/core_doble.py` (solo suite normal)

Servidor `aiohttp` local que imita lo justo de Core para probar sin Docker el
simulado y el onboarding: `/api/onboarding`, `/api/onboarding/{users,core_config,analytics,integration}`,
`/auth/token`, `/api/config` (con `state` configurable para probar la
espera), `/api/` y una ruta REST de eco, y `/api/websocket` con fase de auth,
`auth/long_lived_access_token` y eco de comandos. Registra lo que recibe (sin
cuerpos de credenciales) para que los tests comprueben qué token llegó.

### 3. Onboarding — `tests/banco/onboarding.py`

`async def preparar_core(core_url, *, timeout_http=300, timeout_running=180) -> CredencialesCore`
con los pasos de research R-3. `CredencialesCore` solo expone `token_core` y
`version_core`; `__repr__` sin token. Excepción propia `BancoNoDisponible(paso,
estado)` con mensaje «onboarding: paso <paso> devolvió <estado>». Sin `print`;
log con `structlog` solo con paso y estado.

### 4. Supervisor simulado — `tests/banco/supervisor_simulado.py`

`aiohttp.web.Application` con las rutas del
[contrato](contracts/supervisor-simulado.md). `ClientSession` propia hacia
Core con `token_core`. Comentarios que citan el comportamiento del real que
replica (`CORE_API_DENY`, `DENIED_WS_TYPE_PREFIXES`, fase de auth de 10 s,
métodos del proxy).

### 5. Entorno — `tests/banco/entorno.py`

- `motivo_sin_banco() -> str | None` y `exigir_banco(test_case)`: aplican la
  tabla de salto/fallo de [data-model.md](data-model.md) (`skipTest` o `fail`).
- `obtener_entorno() -> EntornoBanco`: la primera llamada arranca un hilo con
  su propio bucle, corre `preparar_core` y levanta el simulado en un puerto
  libre de `127.0.0.1`; las siguientes devuelven el mismo objeto (o el mismo
  fallo, sin reintentar). Protegido con `threading.Lock`. Al final del proceso
  (`atexit`) para el simulado.
- `async def hermes_conectado(entorno)`: contexto asíncrono que, en el bucle
  del test, crea `HAClient(entorno.supervisor_url, entorno.token_addon,
  HealthServer())`, hace `start(timeout_seconds=30)`, monta el servidor con
  `hermes.__main__._build_mcp(HermesConfig(), ha_client)`, abre `mcp.Client`
  en memoria y al salir lo cierra todo y llama a `ha_client.stop()`.
- Helper `llamar(cliente, tool, **args) -> dict`: `call_tool`, decodifica el
  JSON y, si la respuesta trae `confirmation_token`, permite confirmar con
  `confirmar(cliente, tool, respuesta, **args)` (misma llamada con el token).

### 6. Lector independiente — `tests/banco/lector.py`

Según [data-model.md](data-model.md): sesión `aiohttp` propia a `core_url` con
`token_core`; `listar`, `estado`, `esperar`, `servicios_llamados` (suscripción
a `call_service` abierta antes de la acción y cerrada después), `crear` y
`borrar` (preparar y limpiar sin pasar por Hermes).

### 7. Tests

Suite normal (en `tests/`, sin marcador, corren en Windows y en Linux):

- `test_banco_supervisor_simulado.py`: los tests de contrato del simulado
  contra el doble de Core.
- `test_banco_onboarding.py`: orden de pasos, `client_id`/`redirect_uri`,
  token de larga duración, espera a `RUNNING` (con el doble en `NOT_RUNNING`
  un rato), error con paso y código, y ninguna credencial en el log capturado
  ni en el mensaje de error (centinela).
- `test_banco_entorno.py`: la tabla de salto/fallo (con `monkeypatch` del
  entorno) y que `EntornoBanco` no muestra tokens en `repr`.
- `test_banco_workflow.py`: en `.github/workflows/tests.yml` existe el job
  `banco-core` con nombre `banco de Core`, sin `continue-on-error`, con
  `timeout-minutes`, y `HA_IMAGEN` tiene la forma
  `ghcr.io/home-assistant/home-assistant:<etiqueta>@sha256:<64 hex>` con
  `<etiqueta> == HA_CORE_LAST_TESTED`; y `pytest.ini` registra el marcador
  `banco`. Lectura del YAML con `yaml.safe_load` (PyYAML ya es dependencia del
  add-on).
- `test_banco_cobertura.py` (tramo B): el invariante de FR-009 sobre el
  registro real de tools.

Banco (en `tests/banco/`, `pytestmark = pytest.mark.banco`):

- `test_banco_humo.py` (tramo A): ping; `smoke_check_ha_core_version` devuelve
  `HA_CORE_LAST_TESTED`; `HAClient` conecta y `ready`; `ha_get_states` y
  `ha_list_services` por MCP devuelven datos de la HA real; `ha_call_service`
  de un servicio inocuo (`input_boolean.turn_on` sobre un helper creado por el
  lector) y su efecto visto por el lector; token de add-on incorrecto → 401 y
  `auth_invalid`; un comando `supervisor/…` por el proxy → `unauthorized`;
  credenciales ausentes del log capturado del arranque (FR-012).
- `test_banco_helpers_input.py`, `test_banco_helpers_tiempo.py` y
  `test_banco_helpers_lugares.py` (tramo B; 23, 18 y 6 tools): una clase por
  dominio con el ciclo completo de [data-model.md](data-model.md); se parten en
  tres ficheros para poder escribirlos en paralelo. `PROBADAS_EN_BANCO` vive en
  `tests/banco/cobertura.py`.

### 8. Workflow — `.github/workflows/tests.yml`

Job `banco-core` según [contracts/job-banco.md](contracts/job-banco.md), con
comentarios del porqué (digest, red sin salida, obligatoriedad, tiempos). El
job `pytest` no cambia: sus tests del banco se saltan con motivo.

### 9. `pytest.ini`

`markers = banco: test contra HA Core real; solo corre en el job banco-core del CI`.

### 10. Documentación

- `hermes/CHANGELOG.md`: sección «Banco de pruebas» en `## [1.2.0] — <fecha de
  publicación>`. Si la entrada aún no existe en la base de la rama (la crea la
  009 en paralelo), se crea con esa cabecera exacta y solo esta sección; al
  integrar se fusionan en una sola entrada (FR-022 de la 008).
- `docs/HOJA-DE-RUTA.md`: fila 010 → «hecha» (tramo B; «en curso» tras el A);
  frase de la cabecera sobre las 124 tools; lista de las 47 tools de helpers
  ejecutadas en el banco.
- `CONTRIBUTING.md` y `CONTRIBUTING.es.md`: el check `banco de Core`, qué hace
  y cómo correrlo en local (resumen de quickstart).

## Código de producto

Ninguno. Comprobado contra el código: `HAClient` recibe la URL y el token como
argumentos; `_ping_supervisor` y `smoke_check_ha_core_version` reciben la URL;
`_build_mcp` recibe la configuración y el cliente. Si durante la
implementación apareciera un cambio imprescindible, se para el tramo y se
justifica aquí antes de hacerlo (FR-006).

## Tramos

Cada tramo lo hace un agente nuevo, deja la suite local con exactamente los 6
fallos conocidos de Windows, el CI de la rama en verde (`gh run watch`) y
termina en su propio commit.

- **Tramo A — infraestructura y humo** (T001–T022): configuración de HA,
  doble de Core, onboarding, Supervisor simulado, entorno, lector, workflow,
  marcador, tests de humo, control negativo de CI y documentación parcial.
  Termina con el job `banco de Core` en verde ejecutando el humo.
- **Tramo B — helpers** (T023–T035): inventario de cobertura, tests de las 47
  tools, control negativo de CI, documentación final y cierre. Termina con el
  job en verde ejecutando humo y helpers.

## Dependencias con otras sub-features

- **011**: aplica la enmienda E-3 (la puerta 4 nombra el banco) y usa el banco
  para sus genéricas (FR-015 de la 008). Depende de la 010.
- **028**: añade al banco el resto de escrituras de Core; extiende la
  configuración de HA y, si hace falta, el simulado. Depende de la 010.
- **009**: crea la entrada `## [1.2.0]` del CHANGELOG; posible conflicto
  trivial al integrar (ver Documentación).
- **014**: la matriz tool → entorno toma de aquí la lista de tools ejecutadas
  en el banco.

## Riesgos

- **Imagen grande o registro lento**: reintentos y tope; si la descarga pasa
  de 3 min de forma sostenida, caché de la imagen (anotado).
- **La regla de `iptables` no corta la salida** (cambio en los runners): el
  paso 9 del job lo detecta y falla.
- **Core tarda más en `RUNNING`** con versiones futuras: los topes están en un
  solo sitio (`tests/banco/onboarding.py` y el job) y el error dice cuál se
  agotó.
- **Intermitencias del banco**: no se reintentan; se investigan. Las esperas
  son por sondeo y cada test usa nombres únicos.
- **El simulado diverge del Supervisor real** en una versión nueva: sus
  comentarios citan el fichero y la versión del Supervisor que replican; la
  matriz manual de la 014 en la VM es la comprobación real.

## Ficheros

- Nuevos: `tests/banco/ha_config/configuration.yaml`, `tests/banco/core_doble.py`,
  `tests/banco/onboarding.py`, `tests/banco/supervisor_simulado.py`,
  `tests/banco/entorno.py`, `tests/banco/lector.py`, `tests/banco/cobertura.py`,
  `tests/banco/test_banco_humo.py`, `tests/banco/test_banco_helpers_input.py`,
  `tests/banco/test_banco_helpers_tiempo.py`, `tests/banco/test_banco_helpers_lugares.py`,
  `tests/test_banco_supervisor_simulado.py`, `tests/test_banco_onboarding.py`,
  `tests/test_banco_entorno.py`, `tests/test_banco_workflow.py`,
  `tests/test_banco_cobertura.py`.
- Modificados: `.github/workflows/tests.yml`, `pytest.ini`,
  `hermes/CHANGELOG.md`, `docs/HOJA-DE-RUTA.md`, `CONTRIBUTING.md`,
  `CONTRIBUTING.es.md`.
- Sin tocar: todo `hermes/src/`, `hermes/config.yaml`, `README*.md`,
  `hermes/DOCS.md`.
