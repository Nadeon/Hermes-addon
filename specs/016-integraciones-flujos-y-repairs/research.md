# Investigación: integraciones, flujos y Repairs (016)

Fuentes: código de Hermes en la punta `ab5098d` de
`feat/016-integraciones-flujos-y-repairs` (la 011 hasta su tramo 3 en curso),
las ramas de la 010, la 012 y la 028 (leídas con `git show`), y el código de
HA Core 2026.11.1 (solo leído). Rutas de HA relativas a `homeassistant/`.

## Lo que hay hoy (comprobado en el código de Hermes)

- `tools/config_entry_flows.py`: `ha_list_configured_domains`,
  `ha_start_config_entry_flow`, `ha_continue_config_entry_flow`,
  `ha_abort_config_entry_flow`, `ha_get_config_entry_options`,
  `ha_start_options_flow`, `ha_continue_options_flow`. Patrones que la 016
  reutiliza:
  - `_flow_path` valida el `flow_id` con `validate_identifier` antes de
    interpolarlo en la ruta REST;
  - `_NON_AUTOMATABLE_TYPES = {external, external_done, progress,
    progress_done}`: si el resultado es uno de ellos, `_abort_flow` hace el
    `DELETE` (best-effort) y la tool devuelve `{"error": "non_automatable",
    "type", "flow_id", "hint"}`. Es lo que la guía llama «Hermes aborta los
    flujos OAuth e informa»;
  - en `create_entry` se añade `status: "ok"` sin pisar `result`.
  - Ninguna pide token; todas sin `response_max_bytes`.
- `tools/config_entries.py`: lista y lee entradas; ya expone
  `supports_reconfigure` y `num_subentries` (CAP-045 «hoy se leen»).
- `tools/repairs.py`: `ha_list_repairs` (lista blanca `_CAMPOS`,
  `translation_placeholders` redactados con `_redactar`, orden por gravedad) y
  `ha_ignore_repair` (dos pasos con lectura previa, `unchanged`, `not_found`).
  Su docstring de módulo dice que `repairs/get_issue_data` y los flujos de
  reparación quedan «fuera de alcance a propósito»: la 016 lo cambia.
- `tool_families.py`: familias por módulo; `config_entries` agrupa
  `config_entries` y `config_entry_flows`; `diagnostics`, `repairs` y otros.
- `command_table.py`: las siete entradas de CAP-044, CAP-045 y CAP-048 están
  `deny` «pendiente de tool dedicada (spec 016)»; `frontend/get_translations`
  está `deny` como clase B (datos del frontend).
- `tests/test_tools_registration.py::test_flow_handlers_tool_renamed_to_what_it_does`
  exige que `ha_list_flow_handlers` NO exista (ver R-2).
- La tabla solo clasifica comandos WebSocket de Core y rutas del Supervisor:
  las rutas REST de Core que usa la 016 (flow_handlers, flujos de subentries,
  reconfigure, flujos de reparación) no tienen entrada y no la necesitan (las
  genéricas de Core solo hablan WebSocket).

## R-1 — Descubiertas e ignorar (`components/config/config_entries.py`)

- `config_entries/flow/progress` (admin): devuelve los flujos de
  `hass.config_entries.flow.async_progress()` cuya fuente **no** es `user` ni
  `reconfigure`. Cada uno es un `FlowResult` parcial: `flow_id`, `handler`
  (el dominio), `context` (con `source`, y según la fuente `unique_id`,
  `title_placeholders`, `discovery_key`, `entry_id`…) y `step_id` si ya
  tiene paso. Aparecen también los `reauth` y los `import`: la tool los lista
  con su `source` y solo marca `ignorable` los que tienen `unique_id`.
- `title_placeholders` es lo que la interfaz enseña como nombre del
  descubierto (`{"name": …}` y a veces host o modelo). Se devuelve redactado
  con `redact_structure` + `redact_secrets` (puede llevar credenciales en una
  URL de una integración mal escrita). `context` entero NO se devuelve (puede
  llevar datos de descubrimiento internos): solo los campos de data-model.
- `config_entries/ignore_flow` (admin, `flow_id`, `title` obligatorio): busca
  el flujo en `async_progress()`; si no está, `not_found`; si su contexto no
  tiene `unique_id`, error `no_unique_id`; si no, inicia un flujo con fuente
  `ignore` que crea una entrada `source: "ignore"` con ese `unique_id` y título
  y aborta los flujos del mismo `unique_id`. Se deshace borrando esa entrada
  (en la interfaz, «Dejar de ignorar»); con Hermes, `ha_delete_config_entry`
  (token). No pide token en la 008: es reversible y no toca nada en marcha.
- Hermes lee `flow/progress` antes de `ignore_flow` para dar `not_found` y
  `cannot_ignore` sin llamar, y para el título por defecto
  (`title_placeholders.name` o el dominio). Si el flujo desaparece entre la
  lectura y la llamada, HA responde `not_found` y la tool lo devuelve igual.
- Configurar un descubierto no necesita tool nueva: su flujo se continúa con
  `ha_continue_config_entry_flow(flow_id, …)` (es el mismo recurso REST
  `/api/config/config_entries/flow/{flow_id}`). La guía lo explica.

## R-2 — Dominios configurables por flujo (`loader.py`, vista `flow_handlers`)

- `GET /api/config/config_entries/flow_handlers[?type=…]` devuelve la lista de
  dominios con `config_flow` (`async_get_config_flows`: los generados de Core
  más las integraciones personalizadas con `config_flow: true`), filtrable por
  `type_filter` `device`, `helper`, `hub` o `service`. No pide admin.
- **Nombre**: la 008 propone `ha_list_flow_handlers`. En la 1.1.x una tool con
  ese nombre listaba las entradas configuradas y se renombró a
  `ha_list_configured_domains` porque mentía; el test
  `test_flow_handlers_tool_renamed_to_what_it_does` impide que el nombre
  vuelva, y reutilizarlo con otro significado confundiría a quien lo recuerde.
  Se usa **`ha_list_config_flow_domains`** (decisión; los nombres de la 008
  son propuestas). El test no se toca.
- La docstring de `ha_list_configured_domains` dice «No existe un comando HA
  que liste todos los handlers disponibles»: es falso (existe por REST).
  Principio V: se corrige el texto (no el nombre, los argumentos ni las
  anotaciones) para remitir a la tool nueva «si la familia
  `integration_flows` está activa».
- Respuesta ordenada; con `type` desconocido, `invalid_argument` sin llamar
  (HA no valida el valor: devolvería una lista vacía que parece verdad).

## R-3 — Preferencias de una entrada (`config_entries/update`)

- Esquema: `entry_id` y opcionales `title` (str),
  `pref_disable_new_entities` (bool), `pref_disable_polling` (bool). HA aplica
  los cambios con `async_update_entry`; si `pref_disable_polling` cambia y la
  entrada estaba `loaded`, la recarga y, si la recarga falla con
  `failed_unload`, devuelve `require_restart: true`. Responde
  `{config_entry, require_restart}`.
- Efectos reales para la vista previa:
  - sondeo desactivado: la integración deja de pedir datos por su cuenta; sus
    entidades solo se actualizan con `homeassistant.update_entity` (o
    automatizaciones que lo llamen) y por push si la integración lo tiene;
    recarga inmediata si está cargada;
  - entidades nuevas desactivadas: lo que la integración añada a partir de
    ahora entra deshabilitado; lo existente no cambia.
- Token: la 008 lo pide «al desactivar el sondeo o las entidades nuevas»; se
  interpreta como **pasar a `true`** cualquiera de las dos (desactivar). Volver
  a `false` o cambiar el título va sin token. Con token o sin él, el comando es
  el mismo y lleva solo lo que cambia.
- La tool lee antes `config_entries/get_single` (también para `unchanged` y
  para el estado). Un token se ata a `entry_id`, `title` y las dos
  preferencias tal como llegaron.
- Anotación: destructiva por nombre exacto (puede pedir token; el invariante
  de `test_tools_registration.py` lo exige), idempotente (repetir deja lo
  mismo).

## R-4 — Subentries (`config_entries.py`, `components/config/config_entries.py`)

- `config_entries/subentries/list` (admin, `entry_id`): lista
  `{subentry_id, subentry_type, title, unique_id}`; sin datos.
- `config_entries/subentries/update` (admin, `entry_id`, `subentry_id`,
  `title` opcional): solo cambia el título. **Defecto de HA 2026.11.1**: si la
  entrada no existe, `get_entry` ya envió `not_found` y además envía otro error
  con `msg["entry_id"]` como id de mensaje. Hermes comprueba antes la entrada
  y la subentry y no envía el comando si no existen.
- `config_entries/subentries/delete` (admin): `async_remove_subentry` →
  `_async_update_entry(subentries=…)`, que llama a
  `dr.async_clear_config_subentry` y `er.async_clear_config_subentry`: **borra
  los dispositivos cuyo `config_subentry_id` es esa subentry (y sus hijos) y las
  entidades con ese `config_subentry_id`**, y avisa a los `update_listeners`
  de la integración (algunas, como `kitchen_sink`, recargan). Es el efecto que
  la vista previa debe enumerar.
- Para la vista previa: entidades de `config/entity_registry/list` filtradas
  por `config_entry_id` y `config_subentry_id`; dispositivos de
  `config/device_registry/list` filtrados por la entrada y la subentry (campo
  `config_subentry_id`, o `config_entries_subentries[entry_id]` según la forma
  que devuelva HA 2026.11.1; la implementación acepta las dos y lo comprueba
  en el banco). Listas recortadas con recuento total.
- Flujos de subentry (REST, admin con `POLICY_EDIT`):
  `POST /api/config/config_entries/subentries/flow` con
  `handler: [entry_id, subentry_type]` y opcional `subentry_id` (fuente
  `reconfigure`, si no `user`); `GET|POST|DELETE …/subentries/flow/{flow_id}`.
  HA comprueba que el tipo es de `async_get_supported_subentry_types(entry)`
  (`UnknownHandler` → 404 si no). Al terminar en `create_entry`, HA añade la
  subentry; el reconfigure termina normalmente en `abort` con
  `reconfigure_successful` tras `async_update_and_abort`.
- Tipos admitidos: `supported_subentry_types` de la entrada
  (`{tipo: {supports_reconfigure: bool}}`), en `config_entries/get_single`.
  Hermes valida el tipo antes de abrir (y `supports_reconfigure` del tipo si
  viene `subentry_id`).
- Abortar: la 008 no lista `ha_abort_subentry_flow`, pero sin él un flujo
  abierto queda huérfano hasta que HA lo caduque; los flujos de configuración ya
  tienen `ha_abort_config_entry_flow`. Se añade (mismo patrón, sin token).
- Sin token al crear, reconfigurar o renombrar (la 008 solo lo pide al borrar);
  coherente con los flujos de configuración y de opciones de la 1.1.2 (D-2).

## R-5 — Flujos de reparación (`components/repairs/`)

- `repairs/get_issue_data` (`domain`, `issue_id`): `{issue_data: …}` o
  `unknown_issue`. Son datos internos de la integración (por eso la 1.1.2 los
  dejó fuera): se devuelven solo en `ha_get_repair`, redactados por clave y
  por patrón (el `_redactar` de `repairs.py`) y recortados al tope.
- `POST /api/repairs/issues/fix` (`handler` = dominio, `issue_id`): crea el
  flujo. `RepairsFlowManager.async_create_flow` exige que el aviso exista y sea
  reparable (`UnknownStep` → 400 «not found»/«not fixable»); si la integración
  no tiene plataforma `repairs`, usa `ConfirmRepairFlow` (un formulario vacío
  de confirmación cuyo envío termina en `create_entry`). Al terminar en algo
  que no es `abort`, `async_finish_flow` **borra el aviso**.
- `GET|POST|DELETE /api/repairs/issues/fix/{flow_id}`. El `GET` repite el paso
  actual sin datos (`async_configure(flow_id)`); es lo que hace la interfaz al
  reabrir el diálogo y, por convención de HA, un paso sin datos solo enseña el
  formulario. La respuesta NO trae el contexto (no dice a qué aviso
  pertenece): por eso `ha_continue_repair_fix` recibe `domain` e `issue_id`,
  comprueba `handler == domain` (`flow_mismatch` si no) y la vista previa dice
  que la relación la indica quien llama. Confundir dos flujos del mismo dominio
  abiertos a la vez es el único caso que esa comprobación no detecta.
- **Qué paso aplica el arreglo**: no se sabe antes. En `kitchen_sink`,
  `DemoFixFlow` y `ConfirmRepairFlow` aplican al enviar el formulario de
  confirmación; `DemoColdTeaFixFlow` aborta al abrir. Hay flujos con menú y
  varios pasos. Por eso **cada** envío de paso va en dos pasos (FR-055 de la
  008 interpretado del lado seguro).
- **Abrir puede terminar el flujo**: en Core 2026.11.1, `hassio/repairs.py`
  devuelve `create_entry` en el primer paso cuando el aviso del Supervisor ya
  no tiene sugerencias (aviso obsoleto), y HA lo borra; `http/repairs.py` y
  otros abortan al abrir en algunos estados. Abrir no pide token (en HA, abrir
  el diálogo tampoco pide nada y casi siempre solo enseña el primer paso), pero
  la descripción lo dice y la respuesta trae `finished_on_start` (D-3).
- `cloud/repairs.py` usa pasos externos o de progreso: se tratan con
  `_NON_AUTOMATABLE_TYPES` como los flujos de configuración (abortar e
  informar).
- `abort` con `reason`; `create_entry` sin `result` útil. Tras un
  `create_entry`, Hermes relee `repairs/list_issues` y dice
  `issue_still_present` (puede volver a crearse si la causa sigue). Si la
  relectura falla, `issue_still_present: null` con el motivo (no se inventa).
- Errores de esquema: el POST devuelve 400 `{"errors": …}`; `_request_json`
  lo convierte en `HAConnectionError`; la tool devuelve el error (redactado) y
  completa el token con fallo.
- Anotaciones: `ha_get_repair` solo lectura por prefijo; `ha_start_repair_fix`
  no destructiva y no idempotente; `ha_continue_repair_fix` destructiva y no
  idempotente por nombre exacto; `ha_abort_repair_fix` como
  `ha_abort_config_entry_flow`.

## R-6 — Traducciones (`helpers/translation.py`, `components/frontend/__init__.py`)

- `frontend/get_translations` (`language`, `category`, `integration` lista
  opcional, `config_flow` opcional) → `{"resources": {clave: texto}}` con
  claves aplanadas `component.<dominio>.<categoría>.…`. Para Repairs:
  `component.<dominio>.issues.<translation_key>.title|description` y, para los
  pasos, `component.<dominio>.issues.<translation_key>.fix_flow.step.<paso>.title|description`
  y `….fix_flow.abort.<motivo>`.
- HA carga el inglés como respaldo de las claves que falten en el idioma
  pedido (`async_fetch`: «English is the fallback»). Idioma: `get_config` →
  `language` (por defecto `en`). Sin argumento nuevo en las tools (los
  esquemas de la 1.1.2 son la referencia de `test_esquemas_de_la_1_1_2`).
- Clave: el dominio del aviso (`domain`) y `translation_key`; si falta
  `translation_key`, no hay texto (no se adivina con `issue_id`).
- Marcadores `{nombre}`: se sustituyen con `translation_placeholders` ya
  redactados; los que falten se dejan como están (igual que la interfaz).
- Coste: una llamada a `get_config` y una a `get_translations` con solo los
  dominios de los avisos devueltos, por respuesta. Si fallan (o HA no tiene el
  comando), los avisos salen sin texto y con `translations_unavailable`: un
  texto decorativo no puede tumbar una lista que ya funcionaba (FR-020 de la
  008).
- Los textos de integraciones personalizadas los escribe un tercero: se
  devuelven redactados con `redact_secrets` y se marcan con
  `_third_party_text` (patrón del Marketplace) en `ha_get_repair` y en los
  pasos; en `ha_list_repairs` no se añade el marcador por aviso (su forma de la
  1.1.2 no lo tiene) sino una sola vez en la raíz.
- La entrada `frontend/get_translations` de la tabla sigue `deny` (clase B):
  las genéricas no la necesitan; se añade un comentario encima que dice que
  Hermes la usa por dentro (CAP-036). Comentarios no cambian el resultado de
  regenerar (el generador conserva cada entrada tal cual).

## R-7 — Tabla y generador

- Siete entradas a `dedicated`, con la familia de su tool y su CAP:
  `config_entries/flow/progress` → `ha_list_discovered_integrations`;
  `config_entries/ignore_flow` → `ha_ignore_discovery`;
  `config_entries/update` → `ha_update_config_entry`;
  `config_entries/subentries/list` → `ha_list_config_subentries`;
  `config_entries/subentries/update` → `ha_update_subentry`;
  `config_entries/subentries/delete` → `ha_delete_subentry`;
  `repairs/get_issue_data` → `ha_get_repair`.
- El generador (`_DEDICADAS_INICIALES`) solo se usa en la primera generación,
  pero `test_generar_tabla.py` compara su resultado con la tabla: las siete
  claves entran en el mapa y `_clasificar` consulta el mapa para la clase A
  antes de la regla «pendiente». Es el mismo cambio que diseña la 012 (su R-7):
  lo hace la primera de las dos que se implemente; la segunda solo añade sus
  claves (S-03 de la spec).
- `test_clase_a_de_via_dedicada_pendiente_de_su_spec` pasa a admitir
  `dedicated` hacia una tool registrada de una familia `desde="1.2.0"` (mismo
  cambio compartido con la 012).
- El inventario TSV no cambia (la clase y la CAP siguen siendo ciertas).

## R-8 — Familias y guía

- Dos familias, cada una con su tema (FR-011 de la 008: «un tema por cada
  familia nueva»):
  - `integration_flows`: «Discovered integrations, config entry preferences,
    config subentries and reconfigure flows.» Módulos `integration_setup` y
    `config_subentries`.
  - `repair_flows`: «Repairs fix flows (run the fix an integration offers for
    a Repairs issue).» Módulo `repair_flows`.
- Por qué dos y no una: quien no quiere que el agente aplique arreglos puede
  quitar `repair_flows` sin perder la gestión de integraciones, y al revés. Por
  qué no ampliar `config_entries` o `diagnostics`: FR-010 de la 008 exige
  familias nuevas para que desactivar las de la 1.2.0 deje la lista de la
  1.1.2.
- El ayudante `tools/_translations.py` empieza por `_`: no registra tools ni
  necesita familia (como `_common.py`). Lo usan `repairs.py` (familia
  `diagnostics`) y `repair_flows.py`.
- Guía: temas nuevos con sus alias; sección «Helpers por config entry» en
  `helpers` (CAP-037, research de la 008 «helpers por config entry»); una línea
  en `config_entries` y otra en `diagnostics` que remiten a los temas nuevos.

## R-9 — Banco de Core

- El banco monta `tests/banco/ha_config/` en `/config` de HA Core 2026.11.1 sin
  red, sin `default_config` ni hardware: no hay descubrimientos, ni avisos
  reparables, ni integraciones con subentries o reconfigure que se puedan
  crear sin red.
- Opciones: `kitchen_sink` (Core) tiene subentries (`entity`, con
  reconfigure), avisos reparables con flujo (`out_of_blinker_fluid`,
  `bad_psu`, `cold_tea`) y un flujo `reauth` sin `unique_id`, pero carga una
  docena de plataformas demo, entidades y avisos que ven todos los tests del
  banco, y no tiene reconfigure de la entrada ni descubrimiento con
  `unique_id`.
- **Decisión**: integración de prueba propia `banco_flujos` en
  `tests/banco/ha_config/custom_components/banco_flujos/` (manifiesto con
  `config_flow: true`, `version`, sin requisitos): `async_setup` (con
  `banco_flujos:` en `configuration.yaml`) abre un flujo de descubrimiento con
  `unique_id` fijo y crea dos avisos reparables con `translation_key` (uno para
  arreglar y otro para abortar); el
  `ConfigFlow` tiene paso `user` (sin red), `reconfigure` y un tipo de subentry
  (`elemento`) con `user` y `reconfigure` que crea un sensor por subentry
  (`config_subentry_id`) para que borrar la subentry borre una entidad; la
  plataforma `repairs` ofrece un formulario de confirmación; `translations/en.json`
  con textos y marcadores. Es configuración del banco (corre dentro del HA de
  prueba), no código de producto: FR-013 de la 008 se cumple. Se anota para el
  mantenedor (D-7).
- Lector: comprueba el efecto con sus propios comandos WS
  (`config_entries/get` y `get_single`, `config_entries/subentries/list`,
  `config/entity_registry/list`, `repairs/list_issues`,
  `config_entries/flow/progress`) y limpia al terminar (borra las entradas que
  crea).
- Cobertura: `tests/banco/cobertura_016.py` con `PROBADAS_016` (las once de
  FR-023) y `NO_EJECUTABLES_016 = {}`; se suma a la unión de
  `tests/test_banco_cobertura_escrituras.py` (contrato de la 028). Si la 028 no
  está integrada, test propio con la misma forma (S-02).

## R-10 — Pruebas

- Unitarias con `unittest.IsolatedAsyncioTestCase`, `AsyncMock` de
  `ws_send` y `_request_json`, `CONFIRMATIONS_DIR` en un temporal,
  `structlog.testing.capture_logs`, el `DummyMCP` de los tests de flujos.
- Centinelas: `centinela-016` bajo una clave sensible (`password`) y un JWT de
  prueba en `title_placeholders`, `translation_placeholders`, `issue_data`,
  `user_input`, un texto traducido y un error de HA; comprobados en la
  respuesta, la vista previa, el log capturado y los ficheros de
  `CONFIRMATIONS_DIR`.
- Controles negativos enumerados en las tareas de cierre de cada tramo.
