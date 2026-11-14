# Investigación: banco de pruebas de Core (spec 010)

**Fecha**: 2026-11-14 · **Fuentes**: spec 008 (FR-013, FR-014, CAP-005,
CAP-034, research «b) Banco de pruebas»); código de Hermes
(`hermes/src/hermes/ha.py`, `network.py`, `config.py`, `__main__.py`,
`tools/_common.py`, `tests/_ha_fixture.py`, `tests/conftest.py`,
`.github/workflows/tests.yml`); código de Core 2026.11.1
(`components/onboarding/views.py`, `components/auth/__init__.py`,
`components/auth/indieauth.py`) y del Supervisor 2026.11.0
(`supervisor/api/proxy.py`, `supervisor/api/__init__.py`), leídos sin
ejecutarlos; manifiesto de la imagen en el registro de GitHub.

## R-1 — Imagen y etiqueta

- **Decisión**: `ghcr.io/home-assistant/home-assistant:2026.11.1@sha256:6785d1eca68747a524c156faae1b139ed415c07357386ae6fe17291986e59e82`.
  Es el digest del **índice multiplataforma** (OCI image index) de la
  etiqueta `2026.11.1`, leído del registro el 2026-11-14. Para amd64 resuelve
  al manifiesto `sha256:1e25a28cb9ee48dbcd33b65cbdcf2919d01991fe11f71cdae0a09c9fc3017ebb`
  (unos 640 MiB de capas comprimidas). Se fija el del índice, no el de amd64,
  para que el mismo valor sirva si algún día el job corre en arm64.
- **Por qué**: la etiqueta sola se puede mover (un republicado de la misma
  versión cambiaría lo que se prueba sin que nadie lo vea); el digest no. La
  etiqueta se deja delante del digest porque Docker ignora la etiqueta cuando
  hay digest, pero la deja legible para el test de FR-001, que la compara con
  `HA_CORE_LAST_TESTED`.
- **Alternativas**: Docker Hub (`homeassistant/home-assistant`), descartado
  por los límites de descargas anónimas desde runners compartidos; `ghcr.io` es
  el registro de origen del proyecto. Solo etiqueta, descartado (FR-013 de la
  008 pide digest).
- **Actualizar**: al subir `HA_CORE_LAST_TESTED`, se cambia la etiqueta y el
  digest en el mismo commit (el test de FR-001 lo exige). El digest se obtiene
  con `docker buildx imagetools inspect ghcr.io/home-assistant/home-assistant:<versión>`
  (campo `Digest` del índice).

## R-2 — Configuración de HA del banco

- **Decisión**: un `configuration.yaml` mínimo versionado en
  `tests/banco/ha_config/`, sin `default_config:`. Carga: `homeassistant:`
  (nombre genérico, ubicación de ejemplo de HA, zona horaria `Etc/UTC`,
  sistema métrico, `country`, `currency`), `http:` (sin `server_host`
  especial), `api:`, `websocket_api:`, `config:`, `onboarding:`, `auth`
  implícito, `logger:` con nivel `warning`, y los 11 dominios de helpers
  (`input_boolean:`, `input_button:`, `input_datetime:`, `input_number:`,
  `input_select:`, `input_text:`, `counter:`, `timer:`, `schedule:`, `zone:`,
  `person:`). El job la copia a un directorio temporal del runner y monta esa
  copia en `/config`, para no ensuciar el checkout.
- **Por qué**: `default_config` arrastra integraciones que buscan hardware o
  red (`bluetooth`, `dhcp`, `ssdp`, `zeroconf`, `usb`, `cloud`, `go2rtc`…):
  más tiempo de arranque, avisos y fallos que no tienen nada que ver con
  Hermes. Los helpers solo existen si su dominio está cargado (sus comandos
  `<dominio>/list|create|update|delete` los registra la propia integración).
  Con un `configuration.yaml` propio, HA no detecta la ubicación por internet
  al crear la configuración por defecto.
- **Alternativas**: `default_config:` (más fiel a una instalación típica, pero
  ruido y dependencia de red); configuración generada en el job (no se puede
  revisar en el diff). La 028 y las siguientes añadirán dominios a este fichero
  cuando los necesiten (por ejemplo `automation:`, `script:`, `scene:`,
  `lovelace:` o `template:`).
- **Privacidad**: la ubicación es la de ejemplo de la configuración por
  defecto de HA, no la de nadie; el nombre de la instancia es genérico.

## R-3 — Onboarding y tokens sin intervención humana

Leído en `components/onboarding/views.py` y `components/auth/__init__.py` de
Core 2026.11.1.

- **Decisión**, en este orden y desde Python, dentro del proceso de tests:
  1. Esperar a que `GET /api/onboarding` responda 200 (vista sin auth).
  2. `POST /api/onboarding/users` con `client_id`, `name`, `username`,
     `password` y `language` (`en`) → `{"auth_code": …}`. Crea el usuario
     administrador, su persona (si `person` está cargado: lo está) y las áreas
     por defecto.
  3. `POST /auth/token` (formulario) con `grant_type=authorization_code`,
     `code` y `client_id` → `access_token` (caduca a los 30 min) y
     `refresh_token`.
  4. Con `Authorization: Bearer <access_token>`:
     `POST /api/onboarding/core_config` (sin cuerpo),
     `POST /api/onboarding/analytics` (sin cuerpo) y
     `POST /api/onboarding/integration` con `client_id` y `redirect_uri`.
  5. Esperar a `GET /api/config` con `state: "RUNNING"`.
  6. Por WebSocket (`/api/websocket`, autenticada con el `access_token`):
     `{"type": "auth/long_lived_access_token", "client_name": "hermes-banco",
     "lifespan": 1}` → token de larga duración (1 día).
- `client_id` es la URL base del banco con barra final y `redirect_uri` la
  misma con `?auth_callback=1`: mismo esquema y `netloc`, que es lo que exige
  `indieauth.verify_redirect_uri`, y el host coincide con el de la petición.
- **Credenciales**: `username`, `password` y el token de add-on se generan con
  `secrets.token_urlsafe` en el proceso de tests. Nunca se escriben en disco,
  ni en variables de entorno, ni en el log; los errores dicen el paso y el
  código HTTP, nunca el cuerpo (FR-012).
- **Por qué completar los cuatro pasos**: FR-013 de la 008 lo pide y deja la
  instancia como una instalación real recién configurada (con persona del
  usuario, áreas por defecto y onboarding terminado). Para la API bastaría el
  primero, pero entonces el banco probaría contra una HA que nadie tiene.
- **Salida a internet cortada**: el paso `core_config` arranca en segundo plano
  flujos de `met`, `radio_browser` y `google_translate`, que salen a internet.
  El contenedor va en una red Docker propia y el job añade una regla en la
  cadena `DOCKER-USER` que rechaza lo que sale de esa subred hacia fuera de
  ella (la subred se lee de `docker network inspect`, no se escribe a mano).
  El puerto publicado en `127.0.0.1` sigue funcionando porque ese tráfico no
  pasa por `FORWARD`. Un paso del job comprueba desde dentro del contenedor que
  no llega a un host público. Esas integraciones quedan sin configurar o en
  reintento; los tests no cuentan con ellas ni con que la lista de config
  entries esté vacía.
- **Alternativas**: dejar el onboarding a medias tras el primer paso
  (determinista, pero contradice FR-013 de la 008); `hass --script auth` para
  crear el usuario (no crea un usuario de HA con grupo de administradores ni
  termina el onboarding); sembrar `.storage/` con ficheros internos de HA
  (formato interno, se rompe con cualquier versión); token de acceso de 30 min
  en vez de uno de larga duración (el job puede acercarse a ese tiempo).

## R-4 — Cómo conecta Hermes

Leído en `ha.py` y `network.py`.

- `HAClient(supervisor_base_url, supervisor_token, health_server, …)` construye
  `<base>/core/api` (REST) y `<base>/core/api/websocket` (WebSocket,
  sustituyendo `http://` por `ws://`). No lee el entorno: la URL entra como
  argumento.
- Al arrancar, `__main__._boot` llama a `resolve_supervisor_base_url` (que
  resuelve el nombre `supervisor` o la IP fija y hace
  `GET /supervisor/ping` por `_ping_supervisor`) y a
  `smoke_check_ha_core_version(base, token, mín, último probado)` (que hace
  `GET /core/info` con `Authorization: Bearer`).
- **Decisión** (opción 1 de la 008): Supervisor simulado en `tests/banco/` y,
  en el proceso de tests, `_ping_supervisor(url_simulado, token)`,
  `smoke_check_ha_core_version(url_simulado, token_addon, HA_CORE_MIN_SUPPORTED,
  HA_CORE_LAST_TESTED)`, `HAClient(url_simulado, token_addon, HealthServer())`
  con `start()`, y las tools por `__main__._build_mcp(HermesConfig(),
  ha_client)` llamadas con `mcp.Client` en memoria. **Sin cambiar código de
  producto.**
- `resolve_supervisor_base_url` no se ejecuta en el banco: depende del nombre
  `supervisor` en el DNS del host o de una IP fija de la red de HAOS, y ya
  tiene sus tests unitarios. Probarlo exigiría tocar `/etc/hosts` del runner y
  escuchar en el puerto 80; no aporta nada sobre la conexión con Core.
- **Alternativas** (de la 008): variable de entorno que cambie la URL base
  (cambio de producto y una puerta más en producción: descartada por FR-013);
  el contenedor del add-on entero con alias de red `supervisor` (más fiel en el
  arranque, pero necesita el mismo simulado, construir la imagen del add-on y
  hablar MCP por HTTP con OAuth: fase posterior, fuera de alcance).

## R-5 — Fidelidad del Supervisor simulado

Leído en `supervisor/api/proxy.py` y las rutas de `supervisor/api/__init__.py`
del Supervisor 2026.11.0.

- Rutas reales del proxy: `GET /core/api/websocket`, `GET /core/websocket`,
  `GET /core/api/stream`, y `/core/api/{path}` solo con `GET`, `POST` y
  `DELETE`. `GET /core/info` es de la API del Supervisor, con la forma
  `{"result": "ok", "data": {"version": …, …}}`. `/supervisor/ping` responde
  `{"result": "ok", "data": {}}`.
- WebSocket real: el Supervisor hace **su propia fase de autenticación** con el
  add-on (`auth_required` con `ha_version` → espera `auth` hasta 10 s →
  `auth_ok` con `ha_version` o `auth_invalid` y cierre) y después abre su
  propia WebSocket con Core con su token, y reenvía mensajes en los dos
  sentidos. Filtra los comandos del add-on cuyo `type` empieza por
  `supervisor/` o `hassio/` y los mal formados (también dentro de una lista
  JSON), respondiendo con un error y sin reenviarlos.
- REST real: rechaza rutas que empiezan por `hassio/` o `hassio_` (`CORE_API_DENY`)
  y reenvía el resto con el token del Supervisor, devolviendo estado, cabeceras
  de contenido y cuerpo de Core.
- **Decisión**: el simulado replica exactamente eso (rutas, métodos, fase de
  auth, filtros, formas de respuesta), salvo `/core/api/stream` (Hermes no lo
  usa). Todo lo demás, 404 con `{"result": "error", "message": …}`. El simulado
  valida el token de add-on y usa hacia Core el token de larga duración.
- **Por qué**: si el simulado fuera más permisivo que el real (por ejemplo,
  aceptar `PUT`), el banco daría por buena una llamada que en producción falla.

## R-6 — Tiempos, esperas y reintentos

- Descarga de la imagen: `docker pull` con hasta 3 intentos y esperas de 10 s
  y 30 s. Sin caché de la imagen: guardar y restaurar ~1,5 GB descomprimidos
  con `actions/cache` no es más rápido que descargar de `ghcr.io` dentro de la
  red de GitHub. Si la descarga pasa de 3 minutos de forma sostenida, se
  reconsidera (anotado en `checklists/requirements.md`).
- Arranque: el job espera a que `GET /api/onboarding` responda 200, sondeando
  cada 2 s durante como mucho 300 s. El proceso de tests espera además a
  `state: RUNNING` (como mucho 180 s), porque el HTTP responde antes de que
  terminen de cargarse las integraciones.
- Tests: tope de 120 s por test con `pytest-timeout` (solo en el job del
  banco), tope del job de 20 min. Ningún test se reintenta: un fallo
  intermitente del banco es un fallo que hay que entender, no esconder.
- Efectos: las comprobaciones sondean al lector independiente cada 0,25 s hasta
  10 s; nunca `sleep` fijos.
- Diagnóstico: si el job falla, un paso con `if: failure()` muestra
  `docker logs --tail 200` del contenedor (HA no registra contraseñas ni
  tokens) y el contenedor se elimina siempre al final.

## R-7 — Alcance de helpers (47 tools)

- Los 11 dominios son los que usan las f-strings `{domain}/list|create|update|delete`
  de `ha.py` (research de la 008, «Comprobación de falsos huecos»):
  `input_boolean`, `input_button`, `input_datetime`, `input_number`,
  `input_select`, `input_text`, `counter`, `timer`, `schedule`, `zone`,
  `person`.
- Tools que modifican en esos módulos (`tools/{counter,input_*,schedule,timer,zones,persons}.py`),
  es decir, todas menos `ha_list_*` y `ha_get_*`: 47 (lista en
  [data-model.md](data-model.md)). Piden token: los `create_or_update`, los
  `delete`, los `reload` y `ha_update_person`.
- Ninguna toca el Supervisor: `guarded_reload` es una llamada a
  `<dominio>.reload`; no hay safety backups en estas tools. Por eso el simulado
  de R-5 basta y la lista de no ejecutables queda vacía.
- Cómo se comprueba el efecto (lector independiente, directo a Core):
  crear/editar/borrar con `<dominio>/list` por WebSocket; acciones sobre el
  valor con `GET /api/states/<entity_id>`; recargas con una suscripción a
  `call_service` en el bus que ve `<dominio>.reload`, y además que lo creado
  sigue existiendo.

## R-8 — Ejecución en local

- Dos variables, ambas las pone el job: `HERMES_BANCO_HA_URL` (URL base de HA,
  `http://127.0.0.1:8123`) y `HERMES_BANCO_OBLIGATORIO=1`.
- Sin `HERMES_BANCO_HA_URL` y sin obligatoriedad: `skipTest` con el motivo
  «banco de Core no configurado: falta HERMES_BANCO_HA_URL. Estos tests corren
  en el job `banco-core` del CI (ver specs/010-banco-de-pruebas-core/quickstart.md)».
- Sin `HERMES_BANCO_HA_URL` y con obligatoriedad: fallo con el mismo motivo.
- Con la URL: cualquier problema (HA inalcanzable, onboarding fallido,
  `RUNNING` que no llega) es un fallo, nunca un salto.
- Quien tenga Docker en local (Linux, macOS o WSL) puede reproducir el job con
  los comandos de [quickstart.md](quickstart.md).
- En la suite normal se prueban sin HA, con dobles locales (servidores
  `aiohttp` en `127.0.0.1`): el Supervisor simulado, el onboarding, la lógica
  de salto, el test de la imagen del workflow y el inventario de cobertura.
  Funcionan igual en Windows y en Linux.

## R-9 — Control negativo de los tests del banco

- Los tests de la suite normal tienen su control negativo en local, como
  siempre (deshacer, ver rojo, restaurar, anotar).
- Los del banco solo se ejecutan en el CI. Su control negativo es un **push de
  control** a una rama desechable (`prueba/010-control-a`,
  `prueba/010-control-b`) con el cambio que debe ponerlos en rojo (tramo A: el
  simulado deja de reenviar la WebSocket; tramo B: una tool de helpers manda el
  servicio equivocado), `gh run watch` hasta ver el rojo en el job del banco y
  borrar la rama remota. El enlace o el recuento se anota en el commit del
  tramo. Ese cambio de producto temporal no llega nunca a la rama de la
  sub-feature.

## R-10 — Workflow

- **Decisión**: un job nuevo `banco-core` (nombre de check `banco de Core`) en
  `.github/workflows/tests.yml`, con los mismos disparadores (push, pull
  request y la ejecución semanal). Va en el mismo workflow porque es parte de
  «Tests» y así la puerta 4 de la constitución lo cubre con el mismo nombre de
  workflow; con nombre de job propio para que sea un check aparte en el ruleset.
- Python 3.13 (la del add-on), las mismas dependencias que el job `pytest`
  más `pytest-timeout`. Ejecuta `pytest -m banco tests/banco -q --timeout=120`
  con `HERMES_CONFIG_BASE` en el temporal del runner, y la misma comprobación
  de «la suite no debe escribir fuera del árbol» que el job `pytest`.
- Acciones con la misma forma que el resto de `tests.yml` (`actions/checkout@v5`,
  `actions/setup-python@v5`); la imagen de HA, por digest.
- **Check obligatorio**: el ruleset del repositorio («Hermes Protegido») tiene
  una lista de checks obligatorios; añadir `banco de Core` es un cambio de
  configuración del repositorio que hace el mantenedor (tarea manual en
  tasks.md). El texto de la puerta 4 lo cambia la enmienda E-3 en la 011.
- **Alternativas**: un workflow aparte (`banco.yml`), descartado porque la
  puerta 4 nombra workflows y E-3 habla del banco como parte del CI de tests;
  contenedor como `services:` del job, descartado porque los servicios arrancan
  antes del checkout y no pueden montar la configuración versionada.

## R-11 — Estructura de los tests

- Marcador `banco` registrado en `pytest.ini`; los módulos del banco llevan
  `pytestmark = pytest.mark.banco`. La suite normal los recoge y se saltan
  (R-8); el job del banco los selecciona con `-m banco`.
- El estilo de la suite es `unittest.IsolatedAsyncioTestCase` (un bucle por
  test). Por eso el Supervisor simulado y el onboarding corren una sola vez por
  proceso en un **hilo con su propio bucle** (`tests/banco/entorno.py`, con un
  acceso único protegido por cerrojo), y cada test crea en su propio bucle su
  `HAClient`, su servidor MCP y su lector independiente.
- Nombres de fichero de test únicos en todo `tests/` (el modo de importación
  `prepend` de pytest no admite dos con el mismo nombre): `test_banco_*.py`.
- Cada test crea helpers con nombres únicos (`banco_<dominio>_<hex>`) y los
  borra en `asyncTearDown` con el lector independiente, aunque falle.
