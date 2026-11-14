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

## Supuestos

- **S-01**: La causa del fallo de updates es el tamaño del mensaje: el catálogo entero del Marketplace pasa de `ha_ws_max_msg_size_bytes` (4 MiB por defecto), aiohttp entrega `WSMsgType.ERROR` y cierra la WebSocket; Hermes falla todas las peticiones pendientes con «WebSocket error en la conexión de HA.» y reconecta. Comprobado en vivo: el listado sin categoría falla y deja un `ha_ws_reconnect_failure` en el log; con `category="integration"` funciona.
- **S-02**: HA 2026.11.1 solo filtra `marketplace/repositories/list` por `categories`; no hay filtro de instalados. La categoría más grande (`integration`) cabe hoy en el tope. No se toca `ha.py`: el cierre ante un mensaje gigante es de aiohttp y ya está documentado junto a la opción.
- **S-03**: La documentación no promete hoy nada sobre argumentos en el log; quitar los dos argumentos de texto libre es coherente con la redacción de red, que no puede reconocer IPs o MACs escritas como regex.

## Fuera de alcance

- Redactar MACs en el log (con FR-007 no hace falta para este caso).
- `entity_id` en `auto_classify_restricted` y en otros eventos de log.
- `aliases: [null]` en `ha_get_entity_registry` y los tracebacks de apagado de uvicorn.
- Proteger `ha.py` de mensajes WebSocket grandes.

## Criterios de éxito

- **SC-001**: `ha_marketplace_list_updates` funciona con el catálogo real de HA 2026.11.1 sin reconexiones en el log.
- **SC-002**: Ninguna respuesta de ninguna tool pasa de `response_max_bytes`.
- **SC-003**: Ni el patrón ni la plantilla aparecen en el log.
- **SC-004**: La suite completa pasa y cada arreglo tiene su control negativo escrito en el commit.
