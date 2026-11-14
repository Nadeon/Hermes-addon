# Research: 009 — correcciones pendientes y versión 1.2.0

Fase 0 del plan. Cada apartado compara la CAP de
[research de la 008](../008-cobertura-total/research.md) con el código de la
punta `d75af3f` (rama `feat/cobertura-total`) y fija la decisión.

Línea base de la suite en Windows sobre esa punta: **1925 passed, 16 skipped,
6 failed** (los 6 conocidos de Windows: finales de línea, byte nulo y
symlinks), 523 subtests.

## R-1 — `redact_secrets` cuadrático (CAP-010, FR-001)

**Medido** (30 KB, una pasada de cada expresión de `security.py`):

| Expresión | Forma adversaria | Tiempo |
|---|---|---|
| `_BASIC_AUTH_URL_RE` | letras sin `://` (`a` × n) | 0,39 s |
| `_BASIC_AUTH_URL_RE` | `a.` × n, `a-` × n | 0,20 s |
| `_BASIC_AUTH_URL_RE` | `a://b:c` × n (sin `@`) | 0,55 s |
| `_JWT_RE` | `eyJ` × n | 0,53 s |
| `_JSON_SECRET_RE` | `"` + `password` × n | 0,63 s |
| `_SECRET_KEY_RE`, `_BARE_SECRET_RE` | todas | ≤ 3 ms |

`redact_network` (`logging_setup.py`) es lineal: 1 MiB de las formas
equivalentes tarda ≤ 0,15 s. No entra.

**Causa**: en las tres expresiones, un prefijo que puede empezar en muchas
posiciones de una misma racha (`[a-zA-Z][a-zA-Z0-9+\-.]*`, `eyJ[...]{2,}`,
`"[...]*(?:password|…)[...]*"`) recorre la racha hasta el final desde cada
posición y falla al no encontrar el delimitador (`://` o `@`, `.`, `"`). n
posiciones × n caracteres.

**Decisión**: reescribir esas tres para que cada carácter se examine un número
acotado de veces, **sin cambiar lo que se redacta**. Técnica a elegir en la
implementación, por expresión:

- anclar el inicio con una búsqueda de texto barata (`str.find` de `://`,
  `eyJ`, `"`) y aplicar la expresión solo en una ventana acotada alrededor; o
- un pequeño escáner lineal que reproduce la expresión (por ejemplo, para JWT:
  la primera aparición de `eyJ` en cada racha de `[A-Za-z0-9_-]` seguida de dos
  segmentos `.`).

Las alternativas «trocear la entrada» (propuesta de la CAP) y «cuantificadores
acotados» se descartan: trocear parte secretos en la frontera del trozo, y
acotar `{2,}` a un número dejaría sin redactar JWT largos legítimos o seguiría
siendo cuadrático en la cota. Las lookbehind de frontera
(`(?<![A-Za-z0-9_-])eyJ`) son lineales pero dejan de redactar un JWT pegado a
una letra (`xeyJ…`), que hoy sí se redacta: redactan menos, y eso no se acepta
(principio II, S-01 de la spec).

**Garantía de equivalencia**: test diferencial con las tres expresiones de la
1.1.2 copiadas en el test como referencia, sobre un corpus generado con semilla
fija (fragmentos `eyJ`, `.`, `://`, `:`, `@`, `"`, `password`, `token`,
espacios, letras y dígitos; longitudes cortas para que la referencia
cuadrática no tarde). Más los tests existentes de `tests/test_redact_secrets.py`
y `tests/test_security_regressions.py`, sin tocarlos.

**Test de tiempo**: 1 MiB de cada forma de la tabla, cada una por separado,
`redact_secrets` completo < 1 s medido con `time.perf_counter`. En el CI de
Linux sobra margen (lineal ≈ decenas de ms); el umbral es holgado para no ser
frágil en un runner lento.

## R-2 — `external_url` e `internal_url` en el log (CAP-011, FR-002)

**Hoy**: `configure_network_redaction(enabled, public_hostname)` construye el
estado `_net_state = (enabled, host_re, salt)` con el hostname público; nada
más del lado de HA. Ningún código lee `external_url`/`internal_url`.

**Dónde leerlas**: la propuesta de la CAP es «`get_config` al arrancar». Por
WebSocket no se puede antes de que arranque el bucle de lectura
(`_read_ws_messages`), que es lo último de `_connect_and_watch`: `ws_send`
esperaría una respuesta que nadie lee. El REST `/api/config` (por el proxy del
Supervisor, `HAClient._request_json("GET", "/config")`, el mismo canal que
`_populate_state_cache` usa para `/api/states`) sí se puede llamar ahí.

**Decisión**: en `_connect_and_watch`, tras autenticar y antes de
`ha_ws_connected` y de `_connected_event.set()`, una llamada
`_aprender_urls_de_ha()` que lee `/api/config`, saca el host de cada URL con
`urllib.parse.urlsplit` y llama a una función nueva de `logging_setup`
(`set_ha_url_hosts(external, internal)`) que reconstruye `_net_state` entero
de una vez, como hoy (un hilo que redacta ve el estado viejo o el nuevo). En
cada reconexión se repite, así que un cambio de URLs se recoge al reiniciar HA.

- Excluidos: literales IP (los seudonimiza la redacción de IPs, con clase y
  hash; tapar el nombre perdería esa información), y `localhost`,
  `homeassistant`, `homeassistant.local`, que son valores por defecto y no
  identifican a nadie. `homeassistant` además aparece en el log como dominio
  de servicios (`homeassistant.restart`).
- Mismas fronteras que el patrón del hostname público (no tapar un trozo de un
  nombre más largo). Orden: hostname público primero (si coincide con
  `external_url`, sale como `<public_hostname>`), luego estos dos, luego
  `*.ts.net` e IPs.
- Fallo al leer (cualquier `Exception`: `HAConnectionError`, errores de
  aiohttp, tiempo, forma inesperada; nunca `CancelledError`): aviso
  `ha_url_redaction_unavailable` con el tipo de error y sin valores; la
  conexión sigue. No es fail-closed a propósito: bloquear la conexión con HA
  por no poder tapar dos nombres en el log dejaría la casa sin servicio por un
  asunto de privacidad del log, y el resto de la redacción sigue activa
  (justificado en el plan, principio III).
- Antes de la primera conexión no hay líneas que puedan llevar esas URLs: las
  del arranque (pasos 1–7) no hablan con HA salvo `/core/info` del
  Supervisor, que no las devuelve.

**Alternativas descartadas**: leerlas por el Supervisor (`/core/info` no las
trae); escuchar `core_config_updated` (más código y más superficie; el cambio
de URLs sin reiniciar HA es raro y se recoge en la siguiente reconexión).

## R-3 — `ip-a-b-c-d` (CAP-013, FR-004)

**Hoy**: `_IPV4_RE` exige puntos; `ip-10-0-0-5.ec2.internal` sale en claro.

**Decisión**: patrón nuevo en `redact_network`, después de IPv6 e IPv4:
`(?<![A-Za-z0-9-])ip-(\d{1,3})-(\d{1,3})-(\d{1,3})-(\d{1,3})(?![\w]|-\d)`
(sin distinguir mayúsculas). La sustitución reutiliza `_replace_ip` sobre
`a.b.c.d` (incluida la tolerancia a ceros a la izquierda y el respeto al
loopback), así que la misma IP tiene el mismo seudónimo escrita de las dos
formas. Lineal: el prefijo literal `ip-` ancla cada intento.

## R-4 — `redacted` de `sv_get_addon_logs` (CAP-014, FR-005)

**Hoy** (`tools/addons.py`): `redacted = redact_secrets(raw)`; si es Hermes,
`redact_network(redacted)`; `was_redacted = redacted != raw`. En la prueba en
vivo de la 1.1.1 el log de Hermes ya venía con la red tapada (se redacta al
escribir), no tenía secretos y la tool dijo `redacted: false`.

**Decisión**: dos campos nuevos y `redacted` igual:

- `secrets_redacted`: `redact_secrets(raw) != raw`.
- `network_redacted`: la redacción de red se aplicó a este log
  (`_es_hermes(slug)` y la opción activa), cambie o no el texto. Para saber si
  la opción está activa sin leer el estado privado, `logging_setup` expone
  `network_redaction_enabled() -> bool`.
- `redacted`: como hoy (texto devuelto ≠ texto leído).

Se descarta «documentarlo y ya» (la otra opción de la CAP): el agente seguiría
sin poder distinguir los dos casos.

## R-5 — `ha_marketplace_list_removed` (CAP-016, FR-007)

**Hoy**: `_list_flagged` devuelve todo (`count`, `total`, `truncated`,
`repositories`), recortado solo por bytes; `removal_type` va tal cual (sin
`_trim`) y fuera de `_third_party_text`. En HA 2026.11 cada entrada es
`to_json()` de `RemovedRepository` (`repository` es el `full_name`,
`removal_type` texto libre o `critical`).

**Decisión** (respuesta en [contracts/tools.md](contracts/tools.md)):

- `installed_only: bool = False`: si es verdad, una lectura más de
  `repositories/list` (ya en `_ALLOWED_SUFFIXES`, por la misma API detectada)
  y se filtran los retirados cuyo `repository` coincide, sin distinguir
  mayúsculas, con el `full_name` de un repositorio instalado. Si esa lectura
  falla, se devuelve su error.
- `limit: int | None = None`: 1–500 con `_validate_limit`; `None` = sin tope
  por cantidad (lo de hoy).
- `total` = los que cumplen el filtro; `by_removal_type` se calcula sobre
  ellos, antes de `limit`; top 20 y `by_removal_type_other`.
- `removal_type` con `_trim` y en `_third_party_text.fields`.
- Solo cambia `list_removed`; `list_critical` comparte `_list_flagged` y no
  cambia su respuesta (el parámetro nuevo de `_list_flagged` es opcional).

## R-6 — Barrido de tokens (CAP-018, FR-009)

**Hoy** (`security.py`): `create_confirmation_token` llama a
`_barrer_caducados()` en cada vista previa con documento; lee y parsea todos
los `*.json` del directorio. Con el tope de 16 MiB casi lleno son decenas de
ms en el bucle de eventos por vista previa.

**Decisión**: en el módulo, `_en_uso_bytes` y `_ultimo_barrido` (monotónico).
En `create_confirmation_token`: si han pasado ≥ 1 s desde el último barrido (o
el reloj monotónico no avanza como se espera, o no ha habido ninguno), se
barre y se fija `_en_uso_bytes`; si no, se usa la memoria. Al guardar un
documento, `_en_uso_bytes += tam`. `cleanup_expired_confirmations` (arranque y
limpieza periódica) también fija ambos valores. `complete_confirmation_token`
no descuenta: el total se sobrestima hasta el siguiente barrido, que lo
corrige. Sobrestimar solo puede hacer que un documento no se guarde y haya que
reenviarlo (el comportamiento de la 1.1.1, ya previsto como degradado); nunca
que se pase del tope. Todo síncrono, sin `await` entre leer y actualizar el
total, como el barrido actual.

**Alternativa descartada**: total exacto en memoria (sumar al emitir, restar
al completar y al caducar). Exige restar en tres sitios y reconciliar con el
disco al arrancar; un error en una resta subestima el total y rompe el tope.

## R-7 — Traceback al apagar (CAP-024, FR-011)

**Hoy** (`__main__.py`): SIGTERM → `shutdown_event` → `server.should_exit`;
uvicorn tiene `timeout_graceful_shutdown=3`; luego
`asyncio.wait_for(server_task, 5)` y, si vence, `server_task.cancel()` sin
esperarla. `main()` captura `KeyboardInterrupt`, `SystemExit` y `Exception`.

**Fuentes posibles** (uvicorn 0.54 instalado):

1. Al vencer el plazo de cierre, uvicorn cancela las peticiones en vuelo
   (`Cancel %s running task(s), timeout graceful shutdown exceeded`) y su
   `run_asgi` captura `BaseException` y registra
   `Exception in ASGI application` con `exc_info`: la traza de un
   `CancelledError`. Una petición larga (por ejemplo `ha_wait_for_event`) en
   vuelo al reiniciar el add-on basta.
2. `CancelledError` hereda de `BaseException`: si escapa de `asyncio.run`, el
   `except Exception` de `main()` no lo captura y Python imprime la traza.
3. `server_task.cancel()` sin esperarla deja la cancelación sin recoger.

**Decisión**:

- Un filtro de `logging` en el logger `uvicorn.error` que, si el registro
  trae `exc_info` con un `CancelledError`, lo sustituye por una línea
  informativa `request_cancelled_on_shutdown` sin traza. Solo cancelaciones:
  cualquier otra excepción sigue con su traza (escenario 5 de la Historia 5).
- `main()` captura `asyncio.CancelledError` junto a `KeyboardInterrupt`
  (registra `interrupted`).
- Tras `server_task.cancel()`, esperarla suprimiendo `CancelledError`.

**Test que reproduce antes de arreglar**: un uvicorn real en `127.0.0.1` con un
puerto libre, una app ASGI cuya petición duerme más que un
`timeout_graceful_shutdown` de 0,2 s, una petición en vuelo, `should_exit` y
`capture` del logging estándar: hoy sale `Exception in ASGI application` con
`CancelledError`. Si no se reproduce en el CI, se anota y se mantienen los
arreglos 2 y 3, que se prueban por separado.

## R-8 — Documentación afectada (FR-013)

Revisado con `grep` sobre la punta:

- `README.md`, `README.es.md`, `hermes/DOCS.md`: no mencionan
  `ha_marketplace_list_removed`, `sv_update_addon`, `redacted` ni las URLs de
  HA. Pero la fila de `log_redact_network` de la tabla de opciones **enumera**
  lo que se tapa (`public_hostname`, `*.ts.net`, IPs): se añaden los hosts de
  `external_url`/`internal_url` y los nombres `ip-a-b-c-d` en los dos README y
  en `DOCS.md`, en el mismo cambio. La viñeta «Network redaction» de la
  sección de seguridad de los README es genérica («your hostname and IPs») y
  no cambia.
- `SECURITY.md`: la viñeta «Network redaction» también enumera; se añaden los
  mismos dos elementos.
- `hermes/config.yaml`: no hay traducciones de opciones (`translations/` no
  existe); no cambia salvo la versión.
- `hermes/src/hermes/tools/guide.py`: tema del Marketplace (línea de
  `ha_marketplace_list_critical` y `ha_marketplace_list_removed`) → filtros y
  resumen.
- Docstrings: `sv_get_addon_logs`, `sv_update_addon`,
  `ha_marketplace_list_removed`, `ha_get_history`.
- `docs/HOJA-DE-RUTA.md`: fila 009 → «hecha»; problema 23 → resuelto en
  1.2.0; menores de 009 fuera de «lo que antes estaba pendiente».
- `specs/008-cobertura-total/plan.md`: matriz, columna de test, con el nombre
  del test de cada CAP; `specs/008-cobertura-total/tasks.md`: T002 → `[X]`.

## R-9 — Versión y CHANGELOG (FR-012)

- Tres sitios a `1.2.0`. `tests/test_addon_manifest.py` ya comprueba que
  coinciden; no hace falta otro test de la versión literal (rompería en la
  1.2.1).
- Test nuevo y duradero: la primera entrada `## [` de `hermes/CHANGELOG.md` es
  la de `__version__`. Sin la entrada nueva, cae.
- La cabecera lleva `<fecha de publicación>` por decisión de la 008 (FR-022);
  la constitución (XI) pide `AAAA-MM-DD`. Es la enmienda E-4 propuesta en la
  008, que se decide en la 011; mientras, la desviación se justifica en el
  plan. `etiquetar.yml` busca la sección por `## [<versión>]`, sin mirar la
  fecha, así que no se rompe.
- Secciones: las ocho bloques de la 008 (plan, «Versionado y documentación»).
  Las que no son de la 009 llevan una línea en cursiva «Pendiente: la añade
  la sub-feature que lo implemente.» para que el esqueleto no anuncie nada que
  no existe (principio V aplicado al CHANGELOG).
