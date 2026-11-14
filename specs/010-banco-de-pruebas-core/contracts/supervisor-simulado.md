# Contrato: Supervisor simulado (`tests/banco/supervisor_simulado.py`)

Réplica mínima de lo que el Supervisor 2026.11.0 ofrece a un add-on para
hablar con Core (`supervisor/api/proxy.py`), más las dos rutas que Hermes usa
al arrancar. Escucha solo en `127.0.0.1`, en un puerto libre.

## Filtro de peticiones peligrosas (T039)

Antes que nada (también antes de comprobar el token), como el primer
middleware del real (`block_bad_requests`): si la ruta o la query, decodificadas
hasta que no cambien (`recursive_unquote`), encajan en `FILTERS` de
`supervisor/api/middleware/security.py` del Supervisor 2026.11.0 (copiado tal
cual: `concat(`, `union … select (`, `union all … select`, `<script>`,
`../`, `x=/.//`, `proc/self/environ`) → `400` sin llegar a Core.

## Autenticación

- REST: `Authorization: Bearer <token_addon>`. Sin cabecera o con otro token →
  `401` y cuerpo `{"result": "error", "message": "Unauthorized"}`.
- `/supervisor/ping` no exige token (como el real; `_ping_supervisor` no lo
  manda).
- Hacia Core, siempre `Authorization: Bearer <token_core>`; el token del
  cliente nunca se reenvía.

## Rutas

| Método | Ruta | Respuesta |
|---|---|---|
| GET | `/supervisor/ping` | `200 {"result": "ok", "data": {}}` |
| GET | `/core/info` | `200 {"result": "ok", "data": {"version": "<version_core>", "machine": "banco", "arch": "amd64"}}` |
| GET, POST, DELETE | `/core/api/{ruta}` | proxy a `<core_url>/api/{ruta}` (ver abajo) |
| GET | `/core/api/` | proxy a `<core_url>/api/` |
| GET | `/core/api/websocket`, `/core/websocket` | proxy WebSocket (ver abajo) |
| PUT, PATCH | `/core/api/{ruta}` | `405` (el real no registra esos métodos) |
| cualquiera | cualquier otra ruta | `404 {"result": "error", "message": "Not found: <método> <ruta>"}` |

## Proxy REST

- `{ruta}` que empieza por `hassio/` o `hassio_` → `403` sin llegar a Core (el
  `CORE_API_DENY` del real).
- La ruta se reenvía tal cual llegó (sin decodificar), con la query.
- Cabeceras reenviadas a Core: `Content-Type` y `Accept`. Cuerpo, tal cual.
- Respuesta: estado, `Content-Type` y cuerpo de Core, sin tocar.
- Core inalcanzable → `502`.

## Proxy WebSocket

1. Acepta la conexión y envía `{"type": "auth_required", "ha_version": "<version_core>"}`.
2. Espera como mucho 10 s un mensaje `{"type": "auth", "access_token": …}`
   (también admite `api_password` por compatibilidad, como el real, comparado
   con el mismo token).
   - Token correcto → `{"type": "auth_ok", "ha_version": "<version_core>"}`.
   - Incorrecto → `{"type": "auth_invalid", "message": "Invalid access"}` y
     cierre.
   - Tiempo agotado u otro mensaje → cierre.
3. Abre su propia WebSocket con `<core_url>/api/websocket`, completa la fase
   de auth con `token_core` y empieza a reenviar en los dos sentidos.
4. Del cliente hacia Core, cada mensaje de texto se analiza como JSON (objeto
   o lista de objetos). Si alguno no tiene `type` de texto o su `type` empieza
   por `supervisor/` o `hassio/`, no se reenvía **nada** de ese mensaje y se
   responde al cliente con **una sola** respuesta
   `{"id": <id>, "type": "result", "success": false, "error": {"code": "unauthorized", "message": "Unauthorized"}}`,
   con el `id` del mensaje si es un objeto y `id: null` si es una lista (como
   `_proxy_app_text` del real; corregido al implementar, tramo A).
5. Cierre en cualquiera de los dos lados → cierre del otro.

## Lo que no hace

- `/core/api/stream`, `/addons/*`, `/backups/*`, `/host/*`… Hermes no los usa
  con las tools de helpers; la 028 o la sub-feature que los necesite los
  añade a este contrato.
- No registra cuerpos, cabeceras ni tokens. Sus eventos de log, si los hay,
  llevan solo método, ruta y estado.

## Tests de contrato (suite normal, sin HA)

Contra un doble de Core (`tests/banco/core_doble.py`, servidor `aiohttp` local
que implementa `/api/*`, `/api/websocket`, el onboarding y `/auth/token`):

- peticiones que encajan en `FILTERS` (en la ruta o en la query, también con
  doble codificación) → 400 sin llegar al doble, incluso sin token; consultas
  normales de history y logbook → pasan.
- ping sin token → 200; `/core/info` con token → versión del doble; sin token
  → 401.
- REST `GET`, `POST` y `DELETE` llegan al doble con `token_core` y no con
  `token_addon`; `PUT` → 405; `hassio/…` → 403 sin llegar al doble; ruta
  desconocida → 404.
- WebSocket: `auth_required` con versión, `auth_ok` con el token bueno,
  `auth_invalid` con otro; un comando normal llega al doble y su resultado
  vuelve; `supervisor/info` y `hassio/…` (también dentro de una lista) no
  llegan y devuelven `unauthorized`.
