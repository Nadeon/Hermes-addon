# Especificación: Hermes 1.1.1 — correcciones de la 1.1.0

**Directorio de la spec**: `specs/006-correcciones-1-1-1`

**Creada**: 2026-11-14

**Estado**: Implementada

**Entrada**: pruebas en vivo de la 1.1.0 contra HA 2026.11.1 con el
Marketplace. Tres fallos: `ha_hacs_list_updates` (y la tool real,
`ha_marketplace_list_updates`) falla siempre con `ha_error` «WebSocket error
en la conexión de HA.»; `ha_get_states(domain="sensor")` devuelve unos 245 KB
con `response_max_bytes` en 128 KiB, sin recorte ni aviso; y el log sigue
guardando en claro el `pattern` de `fs_search_in_config`, que en la versión
anterior dejó IPs y MACs de la red local.

## Clarificaciones

### Sesión 2026-11-14

Decisiones tomadas con el mantenedor antes de empezar:

- P: ¿Se protege `ha.py` de los mensajes WebSocket demasiado grandes? → R: solo si es imprescindible. Con el catálogo pedido por categorías no lo es (ver S-02).
- P: ¿Redacción de MACs en el log o dejar de registrar el argumento? → R: dejar de registrarlo es mejor si es coherente con el diseño. Se registra solo su longitud (ver S-03).

### Sesión 2026-11-14 (revisión de la 1.1.1)

Una revisión independiente de la 1.1.1 sin publicar (1 bloqueante, 1 alto,
4 medios y 5 bajos) amplía esta spec con la historia 4 y FR-009 a FR-017:

- P: ¿Cómo se recorta una vista previa que no cabe? → R: el guardián nunca quita el `confirmation_token`; sustituye sus campos más grandes por un resumen `_omitted` y lo dice con `preview_truncated: true` (ver S-04).
- P: ¿Se protege ahora `ha.py` de los mensajes WS grandes? → R: sí, lo justo: tope por defecto de 16 MiB, el 4 MiB guardado como defecto heredado y un evento propio para el cierre por tamaño. Sale de «Fuera de alcance».

## Escenarios de usuario y pruebas *(obligatorio)*

### Historia 1 — Actualizaciones del Marketplace (Prioridad: P1)

Quien tiene el Marketplace de HA 2026.11 quiere saber qué repositorios
instalados tienen actualización. Hoy la tool falla siempre y, además, tumba la
conexión WebSocket de Hermes con HA durante unos segundos.

**Prueba independiente**: con un HA simulado que filtra por `categories` como
HA 2026.11.1, `ha_marketplace_list_updates` nunca pide el catálogo entero y
devuelve las actualizaciones de todas las categorías.

**Escenarios de aceptación**:

1. **Dado** el Marketplace, **cuando** el agente llama a `ha_marketplace_list_updates` (o al alias `ha_hacs_list_updates`), **entonces** Hermes pide `marketplace/repositories/list` una vez por categoría, siempre con `categories`, y la respuesta reúne todas.
2. **Dado** lo mismo, **cuando** llama a `ha_marketplace_list_repositories` sin `category` o a `ha_marketplace_get_repository`, **entonces** tampoco se pide el catálogo entero.
3. **Dado** HACS 2.x (HA <= 2026.10), **cuando** se llama a las mismas tools, **entonces** se piden también por categoría, incluidas `appdaemon` y `python_script`.

### Historia 2 — El límite de respuesta vale para todas las tools (Prioridad: P1)

`response_max_bytes` promete el tamaño máximo de la respuesta de una tool.
Hoy solo lo cumplen las tools que recortan por su cuenta; `ha_get_states` y
otras lo ignoran.

**Prueba independiente**: con el servidor MCP de Hermes y todas las tools
registradas, ninguna respuesta pasa de `response_max_bytes`.

**Escenarios de aceptación**:

1. **Dado** `response_max_bytes` = 128 KiB y 465 sensores que ocupan unos 245 KB, **cuando** el agente llama a `ha_get_states(domain="sensor")`, **entonces** la respuesta cabe en 128 KiB, trae `truncated: true`, cuántos devuelve, cuántos había y una pista para filtrar.
2. **Dado** cualquier tool registrada cuya respuesta pase del límite, **cuando** el resultado sale del servidor, **entonces** cabe en el límite: se recorta su lista más grande y se dice, o, si no hay lista que recortar, se devuelve `response_too_large` marcado como error.
3. **Dado** una respuesta que cabe en el límite, **entonces** sale sin ningún cambio.

### Historia 3 — Argumentos libres fuera del log (Prioridad: P2)

Quien pega su log al pedir ayuda no quiere que salgan en él IPs, MACs o
nombres de su casa que escribió dentro de una búsqueda o una plantilla.

**Prueba independiente**: tras `fs_search_in_config` con un patrón que
contiene una IP y una MAC, y `ha_render_template` con un `entity_id`, ninguno
de esos textos aparece en los eventos de log; sí su longitud.

**Escenarios de aceptación**:

1. **Dado** un patrón con una IP y una MAC escapadas, **cuando** la búsqueda acaba bien, se rechaza, vence o falla, **entonces** el evento de log lleva `pattern_len` y no el patrón.
2. **Dado** una plantilla, **cuando** se renderiza bien, falla o vence, **entonces** el log lleva `template_len` y no la plantilla.

### Historia 4 — Lo que ya recortaba sigue dando datos (Prioridad: P1)

Quien pide un historial o unas estadísticas de rango amplio, borra un fichero
grande o lee el log de un add-on que escribe mucho quiere datos útiles con su
aviso, no un `response_too_large`.

**Prueba independiente**: por el servidor MCP en memoria, cada tool que
recorta por su cuenta, con un HA simulado que devuelve más de lo que cabe,
sale con datos, `truncated: true` y recuentos que cuadran; una vista previa
mayor que el tope conserva su token.

**Escenarios de aceptación**:

1. **Dado** `ha_get_history` o `ha_statistics_during_period` con más puntos de los que caben, **entonces** devuelven datos recortados por el final con `truncated: true` y `truncated_at`, sin `response_too_large`.
2. **Dado** `ha_get_logbook` recortado, **entonces** `count` es la longitud de `events` y `truncated_at` es el `when` del último devuelto.
3. **Dado** `fs_delete_file` de un fichero de texto de 200 KB, **entonces** la primera llamada trae `confirmation_token`, `preview_truncated: true` y `current_content` resumido, y la segunda borra el fichero.
4. **Dado** `sv_get_addon_logs` de un log que no cabe, **entonces** devuelve sus últimas líneas con `truncated: true` y `lines_returned`.
5. **Dado** un mensaje de HA mayor que `ha_ws_max_msg_size_bytes`, **entonces** el log trae `ha_ws_message_too_big` y las llamadas que fallan lo dicen.

### Casos límite

- Una categoría que la API no tiene devuelve una lista vacía (HA filtra con `in`): no es un error.
- Un repositorio aparece en una sola categoría: no hay duplicados al juntar.
- Una respuesta que ya venía recortada por su tool pero que el SDK serializa con sangría puede pasar del límite: el guardián la reserializa compacta antes de recortar nada.
- Una respuesta de varias partes (una tool que devuelve una lista Python) se trata como una lista.

## Requisitos *(obligatorio)*

### Requisitos funcionales

- **FR-001**: Las tools del Marketplace no envían nunca `*/repositories/list` sin `categories`; el catálogo completo se pide categoría a categoría (`integration` primero, que decide la API).
- **FR-002**: El resultado de `list_updates`, `list_repositories` sin categoría y `get_repository` es el mismo que antes con el catálogo entero.
- **FR-003**: Todo resultado de una tool pasa por un único guardián en `HermesMCPServer.call_tool` que garantiza `response_max_bytes`, sin depender de cada tool.
- **FR-004**: Si el resultado no cabe, el guardián prueba primero la serialización compacta; si sigue sin caber, recorta la lista más grande del nivel superior (o la propia lista si el resultado es una) con `truncated: true` y `_response_limit` (`list`, `returned`, `total`, `max_bytes`, `hint`); si no hay lista que recortar, devuelve `{"error": "response_too_large", …}`.
- **FR-005**: Un resultado que cabe no se modifica.
- **FR-006**: Un test recorre todas las tools registradas y comprueba que ninguna puede pasar del límite.
- **FR-007**: `fs_search_in_config` y `ha_render_template` no registran en el log su `pattern` ni su `template`; registran `pattern_len` y `template_len`.
- **FR-008**: Versión 1.1.1 en `config.yaml`, `__init__.py` y `HA_CORE_LAST_TESTED_IN_HERMES`; CHANGELOG `## [1.1.1] — 2026-11-14` con Fixed; DOCS y README dicen la verdad sobre el límite; la hoja de ruta recoge el estado y las pruebas manuales pendientes.
- **FR-009**: Las tools que recortan por su cuenta (history, statistics, logbook, registros de entidades y dispositivos, config entries, `fs_read_file`) miden la respuesta ENTERA, envoltorio incluido, y escrita como se mide (`ensure_ascii=False`); el guardián nunca tiene que volver a recortarlas (B-1, M-1).
- **FR-010**: El guardián, sin lista en el nivel superior, recorta un `{id: [puntos]}` (objeto cuyos valores son todos listas) quitando el último punto de la lista más larga; un objeto con más campos no se recorta por dentro (B-1).
- **FR-011**: Al recortar una lista, el guardián pone al día `count`, `returned` y `returned_lines` que la contaban y quita `truncated_at` (M-1).
- **FR-012**: Una respuesta con `confirmation_token` nunca pierde el token: los campos más grandes de `preview` (y luego del nivel superior) se sustituyen por `{"_omitted": true, "bytes", "type", "lines"|"keys"|"items"}` y se marca `preview_truncated: true` con `_response_limit` (A-1).
- **FR-013**: `sv_get_addon_logs` devuelve las últimas líneas que caben, con `truncated`, `lines_returned` y una pista (M-2). La pista de `response_too_large` no dice que se haya recortado nada (L-1).
- **FR-014**: Un test por el servidor real cubre cada tool de FR-009 y FR-013 y `fs_delete_file` con un fichero de 200 KB; el recorrido de todas las tools incluye un `{id: [puntos]}` cerca del tope y una vista previa con token (M-4).
- **FR-015**: `ha_ws_max_msg_size_bytes` vale 16 MiB por defecto (config.py, config.yaml, run.sh); un 4194304 guardado se sustituye y se anota como `config_legacy_default_replaced` con su propia pista; el cierre por mensaje demasiado grande (1009) se registra como `ha_ws_message_too_big` (M-3).
- **FR-016**: Cada resolución CIMD deja `oauth_cimd_document` con `result` (`ok`, `cache`, `error` + `reason`) y solo el host del `client_id`; sin cambios en la lógica SSRF.
- **FR-017**: DOCS, SECURITY, README, CHANGELOG y la hoja de ruta recogen todo lo anterior, la verificación de CIMD con claude.ai y la recomendación `oauth_cimd_allowed_hosts: ["claude.ai"]` para quien solo use Claude (el defecto sigue vacío). Marketplace con HACS: sin reintentos de `marketplace/*` por categoría y el error dice la categoría (L-3).

## Supuestos

- **S-01**: La causa del fallo de updates es el tamaño del mensaje: el catálogo entero del Marketplace pasa de `ha_ws_max_msg_size_bytes` (4 MiB por defecto), aiohttp entrega `WSMsgType.ERROR` y cierra la WebSocket; Hermes falla todas las peticiones pendientes con «WebSocket error en la conexión de HA.» y reconecta. Comprobado en vivo: el listado sin categoría falla y deja un `ha_ws_reconnect_failure` en el log; con `category="integration"` funciona.
- **S-02**: HA 2026.11.1 solo filtra `marketplace/repositories/list` por `categories`; no hay filtro de instalados. La categoría más grande (`integration`) cabe hoy en el tope. No se toca `ha.py`: el cierre ante un mensaje gigante es de aiohttp y ya está documentado junto a la opción. La revisión de la 1.1.1 cambió esta decisión: ver FR-015 y S-05.
- **S-03**: La documentación no promete hoy nada sobre argumentos en el log; quitar los dos argumentos de texto libre es coherente con la redacción de red, que no puede reconocer IPs o MACs escritas como regex.

- **S-04**: Para las vistas previas grandes se elige resumir en el guardián y no que cada tool acote la suya: vale para todas las tools con token (las de hoy y las futuras) en un solo sitio, nunca deja una vista previa recortada a medias (una lista de acciones a medias haría aprobar algo que no se ha visto) y lo dice. El token no depende de la vista previa sino de los argumentos, así que sigue cubriendo exactamente lo que se ejecutará.
- **S-05**: 16 MiB de mensaje WS suponen un pico transitorio de unos 100-160 MB solo cuando llega un mensaje así; frente a eso, con 4 MiB la conexión entera se cierra y fallan todas las llamadas en curso.

## Fuera de alcance

- Redactar MACs en el log (con FR-007 no hace falta para este caso).
- `entity_id` en `auto_classify_restricted` y en otros eventos de log.
- `aliases: [null]` en `ha_get_entity_registry` y los tracebacks de apagado de uvicorn.
- Subir el máximo del esquema de `ha_ws_max_msg_size_bytes` a 64 MiB, `minimal_response` en history y `list_for_display` en el registro de entidades (revisión de 1.1.1, M-3, complementos).
- Restos de texto libre en el log (revisión de 1.1.1, L-4) y los detalles del guardián de L-5: lista de un solo elemento, separadores no compactos y escapado JSON-RPC.

## Criterios de éxito

- **SC-001**: `ha_marketplace_list_updates` funciona con el catálogo real de HA 2026.11.1 sin reconexiones en el log.
- **SC-002**: Ninguna respuesta de ninguna tool pasa de `response_max_bytes`.
- **SC-003**: Ni el patrón ni la plantilla aparecen en el log.
- **SC-004**: La suite completa pasa y cada arreglo tiene su control negativo escrito en el commit.
- **SC-005**: Ninguna tool que ya recortaba devuelve `response_too_large` con datos que se pueden recortar, y ninguna vista previa pierde su token.
