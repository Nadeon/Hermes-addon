# Modelo de datos: banco de pruebas de Core (spec 010)

No hay datos persistentes nuevos en Hermes. Lo que sigue son las piezas del
banco y sus reglas.

## Variables de entorno del banco

| Variable | Quién la pone | Valor | Efecto |
|---|---|---|---|
| `HERMES_BANCO_HA_URL` | job `banco-core` | URL base de HA en el runner (`http://127.0.0.1:8123`) | Sin ella, los tests del banco se saltan o fallan (ver abajo) |
| `HERMES_BANCO_OBLIGATORIO` | job `banco-core` | `1` | Convierte la falta de `HERMES_BANCO_HA_URL` en un fallo |

Ninguna credencial viaja por variables de entorno.

**Reglas de salto y fallo** (FR-007):

| `HERMES_BANCO_HA_URL` | `HERMES_BANCO_OBLIGATORIO` | HA responde y el onboarding termina | Resultado |
|---|---|---|---|
| ausente | ausente o distinto de `1` | — | salto con motivo |
| ausente | `1` | — | fallo con el mismo motivo |
| presente | cualquiera | sí | los tests corren |
| presente | cualquiera | no | fallo con el paso y el código |

## Entorno del banco (`tests/banco/entorno.py`)

Objeto único por proceso, creado la primera vez que un test lo pide.

| Campo | Tipo | Regla |
|---|---|---|
| `core_url` | str | `HERMES_BANCO_HA_URL` sin barra final |
| `supervisor_url` | str | `http://127.0.0.1:<puerto libre>` del Supervisor simulado |
| `token_addon` | str | `secrets.token_urlsafe(32)`; lo que Hermes usa como `SUPERVISOR_TOKEN` |
| `token_core` | str | token de larga duración de Core (R-3); lo usan el simulado y el lector |
| `version_core` | str | `version` de `GET /api/config` |

- `__repr__` y `__str__` no muestran ningún token (FR-012).
- Estados: `sin_crear` → `creando` → `listo` | `fallido`. Un `fallido` guarda el
  motivo (paso y código) y lo repite a cada test que lo pida, sin reintentar
  el onboarding (un segundo intento daría 403 «already done» y escondería el
  primer error).

## Credenciales efímeras

| Credencial | Vida | Dónde vive |
|---|---|---|
| usuario y contraseña de onboarding | lo que dura el proceso | variables locales de la función de onboarding; se descartan tras obtener el código |
| `access_token` / `refresh_token` | 30 min (no se renuevan) | locales del onboarding; solo para los pasos 4–6 |
| token de larga duración | 1 día (el contenedor muere antes) | `token_core` del entorno |
| token de add-on | lo que dura el proceso | `token_addon` del entorno |

## Supervisor simulado (`tests/banco/supervisor_simulado.py`)

Contrato completo en [contracts/supervisor-simulado.md](contracts/supervisor-simulado.md).

| Campo | Regla |
|---|---|
| `core_url` | destino de los proxys |
| `token_addon` | único token aceptado de los clientes |
| `token_core` | token con el que habla con Core |
| `version_core` | lo que devuelve `/core/info` (se lee de Core al arrancar) |

## Lector independiente (`tests/banco/lector.py`)

Cliente directo a Core (`core_url` + `token_core`), sin `HAClient` ni el
simulado.

| Operación | Cómo |
|---|---|
| `listar(dominio)` | WebSocket `<dominio>/list` |
| `estado(entity_id)` | REST `GET /api/states/<entity_id>` (404 → `None`) |
| `esperar(condición, timeout=10)` | sondeo cada 0,25 s; al agotar, falla con el último valor visto |
| `servicios_llamados()` | suscripción a `call_service` en el bus; devuelve los `(dominio, servicio)` vistos |
| `crear(dominio, datos)` | WebSocket `<dominio>/create`; devuelve el elemento (para preparar un caso sin pasar por Hermes, como el humo de `ha_call_service`) |
| `borrar(dominio, id)` | WebSocket `<dominio>/delete`, sin error si no existe (limpieza) |

## Inventario de cobertura (`tests/banco/cobertura.py`)

| Campo | Tipo | Regla |
|---|---|---|
| `DOMINIOS_HELPERS` | tupla | los 11 dominios |
| `MODULOS_HELPERS` | tupla | `counter`, `input_boolean`, `input_button`, `input_datetime`, `input_number`, `input_select`, `input_text`, `schedule`, `timer`, `zones`, `persons` |
| `PROBADAS_EN_BANCO` | frozenset | las 47 tools de la tabla siguiente |
| `NO_EJECUTABLES` | dict tool → motivo | vacío hoy |

Invariante (FR-009): tools registradas por `MODULOS_HELPERS` que no son
`ha_list_*` ni `ha_get_*` = `PROBADAS_EN_BANCO` ∪ claves de `NO_EJECUTABLES`,
y las dos partes son disjuntas.

### Las 47 tools y cómo se comprueba su efecto

«2P» = se ejecuta en dos pasos y se comprueba que la vista previa no cambia HA.

| Dominio | Tool | 2P | Efecto comprobado por el lector |
|---|---|---|---|
| input_boolean | `ha_create_or_update_input_boolean` | sí | aparece en `input_boolean/list` con la configuración pedida; al editar, cambia |
| input_boolean | `ha_set_input_boolean` | no | estado `on`/`off` |
| input_boolean | `ha_toggle_input_boolean` | no | estado invertido |
| input_boolean | `ha_delete_input_boolean` | sí | desaparece de la lista |
| input_button | `ha_create_or_update_input_button` | sí | en la lista |
| input_button | `ha_press_input_button` | no | el estado (marca de tiempo) cambia |
| input_button | `ha_delete_input_button` | sí | fuera de la lista |
| input_datetime | `ha_create_or_update_input_datetime` | sí | en la lista con `has_date`/`has_time` |
| input_datetime | `ha_set_input_datetime` | no | estado igual al valor pedido |
| input_datetime | `ha_delete_input_datetime` | sí | fuera de la lista |
| input_number | `ha_create_or_update_input_number` | sí | en la lista con `min`/`max`/`step` |
| input_number | `ha_set_input_number` | no | estado igual al valor |
| input_number | `ha_increment_input_number` | no | estado + `step` |
| input_number | `ha_decrement_input_number` | no | estado − `step` |
| input_number | `ha_delete_input_number` | sí | fuera de la lista |
| input_select | `ha_create_or_update_input_select` | sí | en la lista con sus `options` |
| input_select | `ha_set_input_select` | no | estado igual a la opción |
| input_select | `ha_cycle_input_select` | no | estado = opción siguiente |
| input_select | `ha_set_input_select_options` | no | atributo `options` igual a las nuevas |
| input_select | `ha_delete_input_select` | sí | fuera de la lista |
| input_text | `ha_create_or_update_input_text` | sí | en la lista |
| input_text | `ha_set_input_text` | no | estado igual al texto |
| input_text | `ha_delete_input_text` | sí | fuera de la lista |
| counter | `ha_create_or_update_counter` | sí | en la lista con `initial`/`step` |
| counter | `ha_increment_counter` | no | estado + `step` |
| counter | `ha_decrement_counter` | no | estado − `step` |
| counter | `ha_set_counter_value` | no | estado igual al valor |
| counter | `ha_reset_counter` | no | estado = `initial` |
| counter | `ha_reload_counters` | sí | HALLAZGO (convergencia, T038): Core 2026.11.1 no tiene `counter.reload`; en `FALLAN_EN_BANCO`, no cuenta como probada; `xfail` estricto que solo admite el 400 de ese servicio ausente (arreglo en la spec 033) |
| counter | `ha_delete_counter` | sí | fuera de la lista |
| timer | `ha_create_or_update_timer` | sí | en la lista con su `duration` |
| timer | `ha_start_timer` | no | estado `active` |
| timer | `ha_pause_timer` | no | estado `paused` |
| timer | `ha_change_timer` | no | atributo `remaining` cambia en el sentido pedido |
| timer | `ha_cancel_timer` | no | estado `idle` |
| timer | `ha_finish_timer` | no | estado `idle` y evento `timer.finished` visto en el bus |
| timer | `ha_reload_timers` | sí | `timer.reload` visto; el temporizador sigue |
| timer | `ha_delete_timer` | sí | fuera de la lista |
| schedule | `ha_create_or_update_schedule` | sí | en la lista con sus franjas |
| schedule | `ha_reload_schedules` | sí | `schedule.reload` visto; el horario sigue |
| schedule | `ha_delete_schedule` | sí | fuera de la lista |
| zone | `ha_create_or_update_zone` | sí | en `zone/list` con `latitude`/`longitude`/`radius` |
| zone | `ha_reload_zones` | sí | `zone.reload` visto; la zona sigue |
| zone | `ha_delete_zone` | sí | fuera de la lista |
| person | `ha_create_person` | no | en `person/list` con su nombre |
| person | `ha_update_person` | sí | el cambio aparece en `person/list` |
| person | `ha_delete_person` | sí | fuera de la lista; la persona del usuario de onboarding sigue |

Total: 47 (input_boolean 4, input_button 3, input_datetime 3, input_number 5,
input_select 5, input_text 3, counter 7, timer 8, schedule 3, zone 3,
person 3).

Notas:

- `ha_create_or_update_*` se prueba en sus dos usos (crear y editar un helper
  existente), porque al editar HA **reemplaza** el elemento (comentario de
  `FakeCollectionStore` en `tests/_ha_fixture.py`) y eso solo lo confirma una
  HA real.
- Los datos de prueba son genéricos (`banco_<dominio>_<hex>`, zona en
  coordenadas de ejemplo, nombres de persona inventados).
