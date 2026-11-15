# Investigación: mejoras de tools existentes (018)

Fase 0 del plan. Cada decisión con su porqué y las alternativas descartadas.
Comprobado contra el código de la rama (punta `7870e5b`, la 011 completa) y
contra Core 2026.11.1 (`components/lovelace/websocket.py`,
`components/conversation/services.py`).

## R-0 — Lo que hay hoy

- **`ha_get_lovelace_dashboard(url_path, view_index)`**: con `view_index`
  devuelve `{url_path, view_index, views_total, view, top_level}` (o
  `top_level_keys` si `top_level` no cabe). Sin él, el documento entero o
  `too_large` con `top_level` y la pista de leer por vistas. Errores
  `yaml_mode`, `no_views`, `view_index_out_of_range` (`views_count`,
  `requested`).
- **`ha_save_lovelace_dashboard(url_path, config, confirmation_token,
  remove_top_level_keys)`**: siempre en dos pasos. La vista previa lee el
  actual (`lovelace/config`; fallo distinto de `config_not_found` →
  `preview_unavailable`), se niega con `top_level_keys_missing` si el nuevo no
  trae claves de nivel superior del actual, y devuelve un resumen de recuentos
  (`_summarize_dashboard_diff`). `config` es omitible al confirmar
  (`_OMITIBLES_GUARDAR`, spec 007): se guarda junto al token con un tope
  global. La confirmación guarda `resueltos["config"]` con
  `lovelace/config/save`. Concurrencia: «last-write-wins» documentado.
- **`resolve_confirmation_token(token, tool, args, omitibles=...)`** compara
  `compute_action_hash(tool, resueltos)` con el del token; un fallo no gasta
  el token. `_pistas_de_confirmacion` construye `confirm_with` con **todos**
  los argumentos no guardados: un argumento que no viene del cliente no puede
  ir en `args` sin aparecer en `confirm_with`.
- **`ha_call_service_response(domain, service, service_data)`**: rechaza la
  denylist con `service_in_denylist` y las entidades restringidas con
  `entity_restricted`, siempre, con una pista que manda a `ha_call_service`.
  `ha_call_service` confirma en dos pasos con la vista previa
  `{action: "call_service", domain, service, service_data, reason,
  restricted_entities?}` y `cached_result` `{"called": true}`, pero no
  devuelve la respuesta del servicio.
- **`HAClient.call_service_response`** no tiene la guarda `allow_dangerous`
  de `call_service`: la única barrera es la de la tool. Hallazgo fuera de
  alcance (spec, «Fuera de alcance»).
- **Listas**: la única tool de la 1.2.0 con lista es la pareja de genéricas
  (`_respuesta` en `tools/generic_commands.py`, `{**cabecera, count, items,
  truncated}`). El tope central (`recortar_a_bytes`) ya recorta la lista más
  grande de un objeto, fuerza `truncated: true` y pone al día `count`
  (`_corregir_recuentos`).
- **Instantáneas**: `test_schemas_did_not_change` compara propiedades y
  `required` exactos con `tests/fixtures/esquemas_1_1_2.json`, con la única
  diferencia permitida de `hermes_guide` (+`search`); `test_hints_did_not_change`
  compara anotaciones. `ha_save_lovelace_dashboard` y
  `ha_call_service_response` ya son `-DI-` (destructivas): no cambian.
  `TestDestructiveToolsAskBeforeActing.SIN_TOKEN_A_PROPOSITO` exime hoy a
  `ha_call_service_response` porque no acepta token.
- **Tabla de comandos**: ninguna entrada menciona la 018; `lovelace/config` y
  `lovelace/config/save` ya son `dedicated` hacia las tools de Lovelace;
  `conversation/process` es `deny` «pendiente de tool dedicada (spec 023)». No
  hay nada que pasar a `dedicated`.

## R-1 — Forma del guardado por vista

**Decisión**: dos argumentos opcionales nuevos en `ha_save_lovelace_dashboard`:
`view_index: int | None` y `view: dict | None`. Solo sustituye una vista que
existe.

**Por qué**:
- `view_index` es el mismo índice que devuelve y acepta
  `ha_get_lovelace_dashboard`: el cliente lee la vista N y guarda la vista N.
- Un argumento `view` separado deja intacto el significado de `config` (el
  documento entero), que FR-020 de la 008 exige para los argumentos
  existentes, y permite rechazar las mezclas (`config` + `view_index`).
- `view` es omitible al confirmar, con su propia tupla de omitibles (no la
  de `config`, ver data-model): una vista de un dashboard de
  134 KB puede pesar decenas de KB, y el problema de la 007 (no da tiempo a
  reescribirla antes de que caduque el token) es el mismo.

**Alternativas descartadas**:
- `view_path` (la `path` de la vista): es opcional en Lovelace y puede
  repetirse o faltar; habría que definir qué hacer en esos casos. El índice
  siempre existe, y FR-003 cubre el riesgo de que el índice apunte a otra vista
  porque alguien insertó una antes.
- Reusar `config` como vista cuando hay `view_index`: el mismo argumento con
  dos significados, justo lo que hace que un cliente se equivoque.
- Una tool nueva `ha_save_lovelace_view`: la 008 asigna 0 tools a la 018 y
  pide el cambio en `ha_save_lovelace_dashboard` (FR-063); una tool nueva
  necesitaría además familia nueva.
- Añadir o borrar vistas: no lo pide la 008 (DF-3).

## R-2 — El token atado al estado del dashboard

**Decisión**: `create_confirmation_token` y `resolve_confirmation_token`
aceptan un argumento opcional nuevo, `estado` (un objeto JSON). Al crear, si
llega, se guarda en el fichero del token su huella
(`compute_action_hash("estado", {"estado": estado})`, la misma
canonicalización) como `state_hash`. Al resolver, si el token tiene
`state_hash` o llega `estado`, las dos huellas tienen que coincidir; si no,
se rechaza con un mensaje propio (constante `ESTADO_CAMBIADO` del módulo) sin
cambiar el estado del token. `action_hash`, `confirm_with` y lo guardado no
cambian. El guardado por vista pasa como `estado` el documento actual leído
en la vista previa y, al confirmar, el que lee justo antes de resolver; con
`ESTADO_CAMBIADO`, la tool responde `dashboard_changed`.

**Por qué**:
- La vista previa dice «se conservan las vistas 0 y 2 y las claves X, Y»;
  sin atar el estado, si otro cliente cambió la vista 0 en esos 60 s, la
  confirmación guardaría la vista 0 nueva (porque se fusiona sobre el actual)
  o la vieja (si se fusionara sobre lo leído en la vista previa): en los dos
  casos el resultado no es el previsualizado. Rechazar es lo fail-closed.
- Meter la huella en `args` haría que `_pistas_de_confirmacion` pidiera al
  cliente un argumento que no conoce (`confirm_with`), y con el tope de
  guardados lleno la confirmación sería imposible. Un campo aparte no toca el
  `action_hash` ni las pistas.
- Opcional y con `None` por defecto: las demás tools y los tokens existentes
  (sin `state_hash`) se resuelven exactamente igual (FR-020).
- Un mensaje propio en vez de «does not match» permite decir al cliente qué ha
  pasado (otra vista previa, no un error suyo).

**Alternativas descartadas**:
- Guardar en la vista previa el documento fusionado entero y guardarlo al
  confirmar: pisaría en silencio lo que otro cliente cambió (pérdida de
  datos, justo lo que la CAP quiere evitar).
- Fusionar sobre el actual sin comprobar: el resultado puede no ser el
  previsualizado (principio IV).
- Comparar solo las demás vistas y no las claves: cualquier cambio invalida
  la promesa de la vista previa; comparar todo es más simple y más estricto.

**Ventana residual**: entre la lectura de la confirmación y
`lovelace/config/save` no hay `await` de Hermes que espere a otro cliente,
pero HA no tiene bloqueo: queda el «last-write-wins» de siempre, ahora de
milisegundos en vez de hasta 60 s.

## R-3 — `ha_call_service_response` con confirmación

**Decisión**: argumento opcional nuevo `confirmation_token`. Criterio de
confirmación idéntico al de `ha_call_service` (denylist o entidad
restringida). Sin token: la respuesta de la 1.1.2 (`error` y `hint`) **más**
`confirmation_token`, `expires_in_seconds` y `preview`; la `hint` cambia de
texto para decir cómo confirmar. Con token válido: `call_service_response` una
vez y su respuesta tal cual (pasa por el tope y la redacción centrales como
cualquier respuesta). Token atado a `ha_call_service_response` con
`{domain, service, service_data}` normalizados (los mismos `args` que
`ha_call_service`, otra tool → otro hash). `complete_confirmation_token` con
`{"called": true}`. Sin omitibles.

**Por qué**:
- **Aditivo**: un cliente de la 1.1.2 que lee `error` sigue viendo un rechazo
  y no ejecuta nada (fail-closed). Devolver solo la vista previa (como
  `ha_call_service`) cambiaría la respuesta de una llamada existente, y la
  restricción del programa lo prohíbe (DF-1).
- **Mismo criterio que `ha_call_service`**: «misma vista previa que
  `ha_call_service`» (FR-064 de la 008). Dejar `entity_restricted` sin token
  sería incoherente: el script peligroso que devuelve datos seguiría sin poder
  ejecutarse por la vía que los devuelve.
- **Sin respuesta en el fichero del token**: la de `conversation.process`
  puede llevar datos de la casa; `/data` entra en los backups (principio II).
  Una reconfirmación con el token ya usado recibe «already used», como
  siempre.
- `conversation.process` en Core 2026.11.1 se registra con
  `SupportsResponse.OPTIONAL` (`conversation/services.py`), así que
  `return_response=1` funciona.

**Alternativas descartadas**:
- Una tool nueva `ha_call_service_with_response_confirmed`: duplicaría la
  política y la 008 la pide en la tool existente.
- Que `ha_call_service` devuelva la respuesta con un argumento nuevo: es la
  tool equivocada para leer (su descripción dice que no devuelve datos) y
  cambiaría su contrato.
- Añadir `allow_dangerous` a `HAClient.call_service_response`: defensa en
  profundidad útil, pero no la pide la 008 y cambia una puerta que usan otros
  módulos; se anota fuera de alcance.

## R-4 — Sobre común de listas y su verificación

**Decisión**:
- `sobre_de_lista(items, *, truncated=False, **cabecera)` en
  `tools/_common.py` → `{**cabecera, "count": len(items), "items": items,
  "truncated": truncated}`. Las genéricas (`_respuesta` de
  `generic_commands.py`) lo usan; su respuesta no cambia (los tests de la 011
  lo comprueban).
- Test transversal en `tests/test_sobre_de_lista.py`: toma el registro real
  (`_real_registry` o equivalente), resta las tools de
  `tests/fixtures/esquemas_1_1_2.json`, se queda con las que empiezan por
  `ha_list_` o `sv_list_` y, por AST del módulo que las declara, exige que el
  cuerpo de la función de la tool llame a `sobre_de_lista`; o que la tool esté
  en `EXCEPCIONES_SOBRE` (dict nombre → motivo). Una excepción que ya no existe
  también falla (para que la lista no envejezca). Hoy no hay ninguna tool
  nueva de lista, así que el test pasa vacío: el control negativo se hace con
  una fuente sintética (función decorada con `@mcp.tool()` llamada
  `ha_list_algo` que devuelve una lista suelta) pasada a la misma función de
  comprobación.
- Guía: un párrafo «Listas» en el índice (`_OVERVIEW`).

**Por qué**:
- La 008 pide «una prueba que lo verifica en las tools nuevas» (FR-065) y la
  018 no tiene tools: la prueba tiene que valer para las de las demás
  sub-features, y fallar cuando una se olvide.
- El AST (como `_tools_por_modulo` de `test_tools_registration.py`) no
  necesita simular HA para cada tool, que es lo que hace inviable una prueba
  dinámica transversal.
- El criterio por nombre (`*_list_*`) es el de las convenciones de Hermes
  (FR-018): una tool de lista se llama así. Lo que devuelva una lista con otro
  nombre lo prueba su sub-feature.

**Alternativas descartadas**:
- Comprobar la forma ejecutando cada tool nueva con un cliente simulado
  genérico: cada tool necesita respuestas de HA distintas; frágil.
- Aceptar también un literal `{"count", "items", "truncated"}` en el AST:
  multiplica las formas de cumplir y deja pasar `count` mal calculado.
- Cambiar las listas de la 1.1.2: prohibido en la 1.2.0 (D-07).

**Riesgo**: sub-features que se implementen antes de integrar la 018 no
conocerán el constructor; al integrar, el test las señala y se adaptan (un
cambio de una línea por tool). El mensaje del test dice qué constructor usar,
para que quien lo vea fallar no tenga que buscarlo.

## R-5 — Banco de Core

**Decisión**: `tests/banco/test_banco_mejoras.py` (marca `banco`), con el
mismo `importorskip` de `tests.banco.base_helpers` que la 011 mientras el banco
no esté integrado en la rama:
1. Crea un dashboard de prueba (`ha_create_lovelace_dashboard`), guarda un
   documento de tres vistas con `title` (dos pasos), guarda la vista 1 por
   vista (dos pasos, sin reenviar `view`) y lee con el lector
   (`lovelace/config` directo a Core): vista 1 nueva, 0 y 2 y `title`
   idénticas. Después, vista previa por vista, guardado completo de otra cosa
   y confirmación → `dashboard_changed` y el lector ve lo del guardado
   completo. Borra el dashboard al final.
2. `ha_call_service_response("conversation", "process", {"text": …,
   "language": "en"})`: sin token → `service_in_denylist` con token; con
   token → respuesta con `response`. Sin entidades en el banco, el intent no
   acciona nada: la respuesta es la de «no lo entiendo» o similar, y basta con
   que tenga la forma de `conversation.process`.

La configuración del banco (`tests/banco/ha_config/configuration.yaml`)
necesita `lovelace:` y `conversation:` (sin `default_config:`); como en la 011,
se añaden al integrar la 010 si no están ya.

Las tools no son nuevas, así que no entran en el inventario de cobertura de
la 010 (que es por dominios de helpers); `ha_save_lovelace_dashboard` y
`ha_call_service_response` las cubrirá también la 028 en su inventario.
