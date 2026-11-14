# Investigación: diagnóstico de Core (012)

Todo lo de HA está leído del código de Core 2026.11.1 y del Supervisor
2026.11.0 (solo lectura, sin ejecutar nada). Las rutas son relativas a
`homeassistant/` del árbol de Core.

## Lo que hay hoy (comprobado en el código de Hermes, punta `ab8c888`)

- Ninguna tool lee el log del sistema, el log de errores, los niveles de log,
  los diagnósticos ni las notificaciones persistentes.
- `service_policy.py` tiene en la denylist, bajo «Ofuscación de rastros»,
  `logger.set_level`, `system_log.clear`, `persistent_notification.dismiss` y
  `persistent_notification.dismiss_all`: por `ha_call_service` piden token.
  No cambia (FR-020).
- `command_table.py` (011): `validate_config`, `test_condition`,
  `system_log/list`, `logger/log_info`, `logger/log_level`,
  `logger/integration_log_level`, `diagnostics/list`, `diagnostics/get` y
  `persistent_notification/get` son `deny` «pendiente de tool dedicada (spec
  012)». `logger/integration_log_level` es la única de clase «cubierto» en el
  inventario (por `logger.set_level`), sin CAP, y el generador la mapea a
  `ha_call_service`.
- `tests/test_command_table.py::test_clase_a_de_via_dedicada_pendiente_de_su_spec`
  exige `deny` «pendiente» para toda la clase A de vía D: la 012 es la primera
  sub-feature que pasa algo de ahí a `dedicated`, así que el test tiene que
  admitirlo (R-7).
- Patrones a reutilizar: dos pasos y lectura previa del estado en
  `tools/repairs.py` (`ha_ignore_repair`); últimas líneas que caben en
  `tools/addons.py` (`sv_get_addon_logs`, `_ultimas_lineas_que_caben`); sobre
  y recorte en `tools/_common.py` (`ajustar_lista_a_bytes`, `tam_json`);
  redacción por clave y por patrón (`redact_structure` + `redact_secrets`,
  como `_redactar` de `repairs.py`); texto de terceros en
  `tools/marketplace.py` (`_third_party`); dueña de un dispositivo en
  `tools/registry_device.py` (`config_entry_id`).
- `HAClient` no tiene lectura REST de texto para Core: `_request_json` parsea
  JSON y `sv_request_text` es del Supervisor. Hace falta un método nuevo
  (R-2).
- Línea base de la suite en Windows (2026-11-14, `ab8c888`): 2021 passed, 16
  skipped, 6 failed (los 6 conocidos).

## R-1 — Validación (`websocket_api/commands.py`)

- `validate_config`: claves opcionales `triggers`, `conditions`, `actions`
  (`cv.match_all`). Para cada una presente valida con el esquema y el
  validador dinámico y devuelve `{clave: {"valid": bool, "error": str|None}}`.
  No necesita administrador. No guarda nada.
- `test_condition`: `condition` (esquema de condición) y `variables`
  opcionales; requiere administrador. Devuelve `{"result": bool}` y, si hubo
  errores de plantilla, `template_errors`. Formato inválido → error
  `invalid_format`; error de HA → `home_assistant_error`.
- Decisión: `ha_validate_config` acepta las partes o `config`. Mapeo de
  `config`: `triggers` o `trigger` → `triggers`; `conditions` o `condition` →
  `conditions`; `actions`, `action` o `sequence` → `actions`. Si están las dos
  formas de una parte (`trigger` y `triggers`), `invalid_argument`: HA las
  rechazaría al guardar y no sabríamos cuál validar. Las demás claves
  (`alias`, `mode`, `id`, `fields`…) van a `not_validated` para que la
  respuesta no sugiera que se comprobó todo (principio V).
- Alternativas descartadas: validar en Hermes con esquemas propios (mentiría
  sobre lo que acepta HA); guardar en una automatización temporal (escribe).

## R-2 — Log de errores (`api/__init__.py`, `bootstrap.py`)

- `APIErrorLog` (`GET /api/error_log`, admin) es un `FileResponse` del fichero
  de log y **solo se registra si hay fichero** (`DATA_LOGGING in hass.data`).
- `bootstrap._log_file_disabled_reason`: con la variable `SUPERVISOR` en el
  entorno y sin `HA_DUPLICATE_LOG_FILE`, **no hay fichero**. El Supervisor
  pone `HA_DUPLICATE_LOG_FILE=1` solo si la opción de Core
  `duplicate_log_file` está activa (`supervisor/docker/homeassistant.py`,
  `api/homeassistant.py`). Es decir: en HA OS y Supervised, por defecto,
  `/api/error_log` da 404. En el banco (contenedor sin Supervisor) sí hay
  fichero.
- Decisión: `ha_get_error_log` existe porque la 008 la pide y sirve donde hay
  fichero; un 404 se traduce a `error_log_unavailable` con `detail` que lo
  explica y una pista: activar `duplicate_log_file` en las opciones de Core, o
  leer el log de Core por el Supervisor (tema `core_diagnostics` de la guía,
  que la 013 completará con su tool). No se cae al journal del Supervisor
  automáticamente: `GET /core/logs` es `deny` «pendiente de tool dedicada
  (spec 013)» y es CAP-081. **Duda D-1** para el final: si, cuando exista la
  tool de la 013, `ha_get_error_log` debe caer a ella.
- Lectura: el fichero puede tener cientos de MB (crece hasta el reinicio). Un
  método nuevo `HAClient.rest_get_text_tail(path, lines, max_line_bytes)` lee
  el cuerpo en flujo (`resp.content`), conserva en un `deque(maxlen=lines)` las
  últimas líneas (cada una recortada a `max_line_bytes`, dicho en la línea) y
  falla con el estado HTTP como `HAConnectionError(status=…)`. Pasa por
  `_assert_safe_request_path`. Tiempo total acotado (30 s, como el resto de
  REST). No se usa `Range`: no consta que el proxy del Supervisor lo reenvíe y
  un fichero comprimido al vuelo no da bytes estables.
- Redacción: `redact_secrets` línea a línea (lineal desde la 009, CAP-010).
  No se aplica `redact_network`: es para el log del propio Hermes; el log de
  HA conserva sus IPs, que suelen ser lo que se diagnostica (mismo criterio
  que los add-ons ajenos en `sv_get_addon_logs`).

## R-3 — Niveles de log (`logger/websocket_api.py`, `logger/helpers.py`)

- `logger/log_info` (sin admin): lista `{domain, level}` de las integraciones
  cargadas, de los flujos de descubrimiento en curso y de las que tienen
  ajuste guardado; `level` es el nivel **efectivo** numérico del logger
  `homeassistant.components.<domain>`.
- `logger/integration_log_level` (admin): `integration`, `level` ∈
  `LOGSEVERITY` (CRITICAL, FATAL, ERROR, WARNING, WARN, INFO, DEBUG, NOTSET),
  `persistence` ∈ {none, once, permanent}. Si la integración no existe →
  `not_found`. Aplica el nivel a todos los loggers de la integración.
- `logger/log_level` (admin): igual con `module` (un logger cualquiera).
  **Escribe**; el inventario de la 008 lo agrupaba con las lecturas, pero su
  nota no dice que lea. No hay forma por API de leer el nivel de un módulo
  (solo `.storage/core.logger`, que no se toca).
- Persistencia (`LoggerSettings`): `none` no se guarda (dura hasta el
  reinicio); `once` se guarda y, al cargar en el siguiente arranque, pasa a
  `none` (se aplica en ese arranque y después desaparece); `permanent` se
  guarda siempre. `NOTSET` quita el ajuste guardado.
- Niveles admitidos por Hermes: DEBUG, INFO, WARNING, ERROR, CRITICAL, NOTSET
  (sin los alias WARN y FATAL, para que la vista previa no enseñe dos nombres
  del mismo nivel), sin distinguir mayúsculas; se envían en mayúsculas.
- Nombre del nivel desde el número: 10 DEBUG, 20 INFO, 30 WARNING, 40 ERROR,
  50 CRITICAL, 0 NOTSET; otro número → `"LEVEL <n>"`.
- `logger.set_level` (acción) sigue en la denylist y no persiste: no se usa.

## R-4 — Log del sistema (`system_log/__init__.py`, `system_log/services.py`)

- `system_log/list` (admin) devuelve `records.to_list()`: por entrada `name`,
  `message` (lista de hasta 5 mensajes distintos), `level`, `source`
  (`[fichero, línea]`), `timestamp` y `first_occurred` (epoch en segundos),
  `exception` (texto de la traza, puede ser vacío) y `count`. HA ya agrupa por
  `(logger, origen, nivel?)` y guarda 50 por defecto (`max_entries`).
- `system_log.clear` (acción) vacía `records` en memoria; no toca el fichero
  ni el journal. `system_log.write` escribe (lo usa el banco para sembrar).
- `system_log` lo carga `default_config` y está entre los
  `LOGGING_AND_HTTP_DEPS_INTEGRATIONS` de `bootstrap.py`; en una configuración
  mínima sin él, el comando no existe (`unknown_command`).
- Decisión de forma: `timestamp`/`first_occurred` en ISO 8601 UTC (`last_seen`,
  `first_seen`) para que el agente no convierta epochs; se ordena por
  `last_seen` descendente. `integration` filtra por `name` igual a
  `homeassistant.components.<x>` o `custom_components.<x>` o que empiece por
  ellos más `.`.

## R-5 — Diagnósticos (`diagnostics/__init__.py`)

- `diagnostics/list` y `diagnostics/get` (admin): `{domain, handlers:
  {config_entry: bool, device: bool}}`; `get` de un dominio sin plataforma →
  `not_found` («Domain not supported»).
- `GET /api/diagnostics/config_entry/{entry_id}` y
  `…/config_entry/{entry_id}/device/{device_id}` (admin): JSON con
  `home_assistant` (información del sistema), `custom_components`,
  `integration_manifest`, `setup_times`, `data` y, si hay, `issues` (los de
  Repairs de ese dominio). 404 si la entrada no existe, si su integración no
  tiene plataforma o no tiene ese tipo, si el dispositivo no existe, si es
  compuesto o si no es de esa entrada (`device.config_entry_id`). La
  integración redacta lo suyo con `async_redact_data`; Hermes añade
  `redact_structure` + `redact_secrets` porque la redacción de cada integración
  es una lista de claves que puede quedarse corta.
- Decisión: comprobar antes con `config_entries/get_single` (el comando que
  usa `ha_get_config_entry`) y con `diagnostics/get` del dominio, para devolver `not_found` o `diagnostics_not_supported` sin
  descargar y sin depender de un 404 ambiguo. Las rutas pasan por
  `validate_path_segment`.
- Tamaño: el diagnóstico de Z-Wave o ZHA puede ocupar varios MB. El tope
  central no sabe recortar un objeto de objetos (da error); por eso la tool
  recorta por su cuenta: si no cabe, `response_too_large` con `data_keys:
  [{key, bytes}]` y la pista de pedir `keys=[…]`.

## R-6 — Notificaciones (`persistent_notification/`)

- Integración de núcleo (`CORE_INTEGRATIONS` de `bootstrap.py`): siempre
  cargada.
- `persistent_notification/get` (sin admin): lista de `{notification_id,
  title, message, created_at}`.
- Acciones `dismiss` (`notification_id`) y `dismiss_all`; descartar un id que
  no existe no falla. No hay comando WS de descarte.
- Decisión: la vista previa lee antes (`not_found` sin token si no está);
  confirma con `call_service("persistent_notification", "dismiss", …)`
  (Hermes la llama directamente, no por `ha_call_service`, así que la denylist
  no interviene: la protección equivalente es el propio token). Tras
  confirmar, si la notificación ya no estaba en una relectura previa a la
  llamada, `already_dismissed`.
- Mensaje recortado en la vista previa a 2000 caracteres con
  `message_truncated: true`, para que una notificación enorme no se coma el
  tope de la vista previa ni el fichero del token.

## R-7 — Tabla y generador

- Las nueve claves pasan a `dedicated` con `family="core_diagnostics"`,
  `tool=` su tool, motivo «cubierto por <tool>» y la CAP del inventario
  (`logger/integration_log_level` sin CAP, como en el inventario). El comentario
  que hoy precede a `logger/integration_log_level` se sustituye por el porqué
  de la dedicada (valida el logger, lee el nivel previo y persiste).
- El generador conserva cada entrada existente byte a byte, así que regenerar
  tras editar la tabla a mano la deja idéntica. Para que una generación desde
  cero dé lo mismo, `_DEDICADAS_INICIALES` nombra las nueve claves y
  `_clasificar` consulta el mapa también para la clase A (hoy solo para
  «cubierto») antes de la regla «pendiente de tool dedicada»; test nuevo en
  `tests/test_generar_tabla.py` con una fila A de vía D que está en el mapa.
- `test_clase_a_de_via_dedicada_pendiente_de_su_spec` pasa a admitir, para una
  fila A de vía D/D+T/D+X, `dedicated` con una tool de una familia de la 1.2.0
  (la existencia de la tool ya la comprueba `test_tool_existe_y_familia_coincide`).
  Una `read` o `confirm` sigue fallando.

## R-8 — Banco de Core

- `tests/banco/ha_config/configuration.yaml` de la 010 no carga
  `default_config`; hay que añadir `system_log:` y `diagnostics:` (comentados).
  `logger:` ya está; `persistent_notification` es de núcleo.
- Siembra con el lector: `system_log.write` (mensaje con un centinela),
  `persistent_notification.create`. Efecto: `system_log/list` vacío tras
  limpiar; `logger/log_info` con el nivel nuevo (y restaurado a NOTSET al
  cerrar); `persistent_notification/get` sin el id.
- Diagnóstico de entrada sin red: candidatas con `diagnostics.py` y flujo de
  configuración sin hardware ni cuenta, p. ej. `local_calendar` (solo pide un
  nombre) o `derivative`/`utility_meter` (piden una entidad de origen, que
  puede ser un helper del lector). El tramo B elige la que cargue en la imagen
  del banco y lo anota; si ninguna, el camino feliz queda en unitarios y en la
  matriz de la 014 como pendiente manual.
- Diagnóstico de dispositivo: ninguna integración sin hardware ni nube lo
  ofrece en 2026.11.1 (las que lo tienen son Z-Wave, ZHA, Matter, MQTT…). En el
  banco se prueba el camino `diagnostics_not_supported` con un dispositivo de
  la integración anterior o de `kitchen_sink` si la 028 está integrada.
- Inventario: `tests/banco/cobertura_012.py` con `PROBADAS_012`
  (`ha_set_log_level`, `ha_clear_system_log`,
  `ha_dismiss_persistent_notification`) y `NO_EJECUTABLES_012` vacío, según el
  contrato de la 028 («Regla para las sub-features siguientes»).

## R-9 — Familia y guía

- Una familia, `core_diagnostics`, en vez de cuatro: es un área (el
  diagnóstico de Core) y un tema de guía; partirla daría opciones que nadie
  pediría. No colisiona con `diagnostics` (1.1.2: Repairs, trazas, relaciones
  y resolución del Supervisor), que no cambia.
- Tema de la guía `core_diagnostics` con alias `logs`, `log`, `notifications`
  y `validation`; el tema `diagnostics` de la 1.1.2 gana una línea que remite
  al nuevo (cambio de texto de guía, no de tool).

## R-10 — Pruebas

- Unitarios con el estilo de siempre: `unittest.IsolatedAsyncioTestCase`,
  `AsyncMock` de `ws_send`, `call_service`, `_request_json` y del método de
  texto nuevo, `CONFIRMATIONS_DIR` en un temporal, `structlog.testing.capture_logs`.
- El método de texto se prueba con un servidor aiohttp local de los tests
  (como los de `HAClient` existentes) para el flujo y el 404.
- Centinelas: `password=centinela-012`, un JWT de prueba y `{"token":
  "centinela-012"}` en mensajes, trazas, líneas, diagnósticos, errores de HA y
  notificaciones.
- Controles negativos previstos (tasks.md): quitar la redacción, no leer antes
  de emitir token, atar el token sin `level`, no comprobar el handler antes de
  descargar, devolver el JSON entero sin mirar el tope, aceptar `config` y
  partes a la vez, quitar una tool de su familia, dejar una entrada en `deny`.
