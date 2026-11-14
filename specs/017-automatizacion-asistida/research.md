# Research: automatización asistida (017)

Decisiones de diseño con su porqué. Todo lo que se cita de Home Assistant es de
Core 2026.11.1, leído (no ejecutado) en la copia de `fuentes/core/`. Las rutas
son relativas a `homeassistant/`.

## R-1 — Importar un blueprint: quién descarga, qué se enseña y qué se guarda

**Lo que hace HA**:

- `blueprint/import` (`components/blueprint/websocket_api.py`,
  `ws_import_blueprint`) solo DESCARGA y analiza: `importer.fetch_blueprint_from_url`
  con un plazo de 10 s y devuelve `suggested_filename`, `raw_data` (el YAML en
  bruto), `blueprint.metadata`, `validation_errors` (`Blueprint.validate()`,
  p. ej. `!input` sin declarar) y `exists` (si ya hay un fichero en la ruta
  sugerida). No guarda nada. Errores: `not_supported` (URL que ningún
  importador acepta), `invalid_format` («Unsupported domain»: el dominio del
  blueprint no tiene `DomainBlueprints` cargado), `timeout`, y `unknown_error`
  para los fallos HTTP de aiohttp.
- Los importadores (`components/blueprint/importer.py`, `FETCH_FUNCTIONS`, en
  orden): foro (`community.home-assistant.io/t/…`, pide el JSON del tema),
  GitHub (`github.com/<repo>/blob/<ruta>` → `raw.githubusercontent.com`), gist
  (`gist.github.com/…`, API de GitHub), web de HA (`www.home-assistant.io/blueprints/…`)
  y genérico (cualquier URL; el nombre sugerido es `<host>/<último segmento sin .yaml>`).
  Todos ponen `source_url` = la URL pedida.
- Guardar es `blueprint/save` (`ws_save_blueprint`): `domain`, `path`, `yaml`
  (texto), `source_url` opcional y `allow_override`. HA analiza el YAML, crea
  `Blueprint(…, expected_domain=domain, schema=BLUEPRINT_SCHEMA)` (falla con
  `invalid_format` si no es válido o es de otro dominio), añade `.yaml` si
  falta, y escribe `blueprint.yaml()`: **vuelve a serializar** el YAML
  analizado, con `source_url` dentro de `blueprint:`. Si ya existe y no hay
  `allow_override`, `already_exists`. Si sobrescribe, recarga las
  automatizaciones (o scripts, o plantillas) que lo usan
  (`DomainBlueprints.async_add_blueprint` → `_reload_blueprint_consumers`).

**Decisión**:

1. **HA descarga, Hermes no.** `ha_import_blueprint` llama a `blueprint/import`
   y nunca abre la URL. Así Hermes no gana un cliente HTTP hacia internet ni
   una vía de SSRF desde su contenedor, y el resultado es exactamente el de la
   interfaz de HA. La tool sí es de mundo abierto (la anotación habla del
   efecto de la llamada, no de quién abre el socket).
2. **Vista previa = qué se guarda y de dónde.** URL tal cual, tipo de
   importador deducido de la URL con los mismos patrones de HA (solo
   informativo), dominio, ruta final (`<dominio>/<ruta>.yaml` bajo
   `/config/blueprints/`; `path` del agente o la sugerida por HA), si existe y,
   si existe, quién usa el existente (R-3), metadatos (nombre, descripción,
   autor, versión mínima de HA), entradas (aplanando las secciones de entradas
   de HA: `input: {sección: {input: {…}}}`), `validation_errors`, el YAML
   entero, su tamaño en bytes y su SHA-256, y la nota de que HA lo vuelve a
   serializar al guardar y añade `source_url`. Todo lo descargado va en
   `_third_party_text` (el mismo aviso que el Marketplace): nombre,
   descripción, descripciones de las entradas y el YAML pueden contener texto
   escrito para manipular al agente.
3. **Fail-closed antes del token**: `validation_errors` no vacío o dominio que
   no es `automation`, `script` ni `template` → `invalid_blueprint`; existe sin
   `allow_override` → `already_exists`; la vista previa no cabe en
   `response_max_bytes` → `blueprint_too_large` con el tamaño (no se puede
   confirmar lo que no se ha enseñado entero). El recorte genérico de vistas
   previas de `_common.py` NO se aplica al YAML: cortaría justo lo que hay que
   ver.
4. **Lo previsualizado o nada.** El token se ata a `url`, `path` (la final),
   `allow_override` y `content_sha256`. Al confirmar, la tool vuelve a llamar
   a `blueprint/import`, recalcula la ruta y la huella, y valida el token con
   esos valores: si el contenido o la ruta sugerida cambiaron, el token no
   casa y la respuesta es `content_changed` («request a new preview»), sin
   guardar. Si casa, `blueprint/save` con el `raw_data` recién descargado (que
   es idéntico byte a byte al previsualizado: misma huella), `source_url=url`
   y `allow_override`. Alternativa descartada: guardar el YAML en el fichero
   del token como los `omitibles` (spec 007). El tope de memoria de los
   omitibles hace que el documento a veces no se guarde (fail-closed: el
   cliente reenvía), y aquí el cliente no tiene nada que reenviar; además
   escribiría en `/data` contenido de terceros. Volver a descargar cuesta una
   petición y da la misma garantía con la huella.
5. **Redacción**: el YAML y los metadatos que se enseñan pasan por
   `redact_secrets`; si algo se tapó, `content_redacted: true` y la nota de
   que lo guardado es el original, no la versión tapada. Lo que se guarda no
   se toca (sería guardar otra cosa que lo que hay en la URL). La URL se
   redacta en el log (puede llevar credenciales en `user:pass@`) y el log
   solo lleva dominio, ruta, tamaño y huella.

## R-2 — Guardar un blueprint escrito por el agente

`ha_save_blueprint(domain, path, yaml, allow_override=False, confirmation_token=None)`:

- Siempre en dos pasos, como `ha_create_or_update_automation`: crea un fichero
  en `/config` y, si sobrescribe, HA recarga a sus consumidores. Con la regla
  «pide token ⇔ destructiva» del registro, es destructiva.
- Antes del token: `path` validado (R-5); `domain` en los tres admitidos;
  `yaml` hasta 256 KiB, leído con un `SafeLoader` que acepta `!input` (y
  cualquier otra etiqueta como valor opaco) solo para sacar los metadatos de la
  vista previa: tiene que ser un mapa con `blueprint.domain` igual a `domain`,
  si no `invalid_argument`. Lo demás (esquema de entradas, selectores) lo valida
  HA al guardar; su error se devuelve redactado y el token se completa con
  fallo.
- Existencia con `blueprint/list` del dominio: existe y sin `allow_override` →
  `already_exists` sin token; con `allow_override`, la vista previa lista
  quién lo usa (R-3) y dice que HA los recargará.
- `yaml` es omitible al confirmar (mecanismo de la spec 007, mismo motivo que
  `config` en automatizaciones: un documento grande que el cliente no tiene que
  reescribir en 60 s). El hash del token lleva todos los argumentos.
- Vista previa: dominio, ruta final, `exists`, `used_by`, metadatos leídos,
  tamaño y SHA-256. No repite el YAML: lo ha escrito el agente.

## R-3 — Borrar un blueprint y quién lo usa

**Lo que hace HA**: `blueprint/delete` → `DomainBlueprints.async_remove_blueprint`
comprueba `_blueprint_in_use` y lanza `BlueprintInUse` («Blueprint in use»);
como no es `OSError`, el manejador genérico de la WebSocket lo devuelve con
código `home_assistant_error` y ese mensaje. Fichero inexistente: `OSError` →
`unknown_error`. Para `automation`, «en uso» es
`automations_with_blueprint` (`components/automation/__init__.py`), que mira
`referenced_blueprint` de cada entidad, incluidas las no disponibles por
configuración inválida (`components/automation/entity.py`,
`UnavailableAutomationEntity.referenced_blueprint`, que lee el
`use_blueprint` de la configuración en bruto). Igual para `script`. `search/related`
(`components/search/__init__.py`, `_async_search_automation_blueprint` y
`_async_search_script_blueprint`) usa esas MISMAS funciones con
`item_type` `automation_blueprint`/`script_blueprint` e `item_id` = la ruta del
blueprint (`homeassistant/motion_light.yaml`). `template` también comprueba el
uso (`components/template/helpers.py`), pero `search/related` no tiene tipo
para él.

**Decisión**: la vista previa de `ha_delete_blueprint` pregunta a
`search/related` (la fuente que usará HA para negarse) y, si hay alguno,
devuelve `blueprint_in_use` con la lista (y recuentos) **sin token**: el
borrado fallaría y lo útil es saber qué automatizaciones o scripts lo usan.
Para `template`, `used_by: null` con el motivo y el aviso de que HA rechazará
el borrado si está en uso. Si `search/related` falla → `preview_unavailable`
sin token (fail-closed: sin saber quién lo usa no hay vista previa honesta).
Existencia previa con `blueprint/list` → `not_found` sin token. Al confirmar,
`home_assistant_error` con «in use» se traduce a `blueprint_in_use` (carrera:
alguien lo empezó a usar), y el token se completa con fallo. La vista previa
dice que el fichero se borra de `/config/blueprints/<dominio>/<ruta>` y que
solo vuelve con un backup.

## R-4 — Listar y sustituir

- `blueprint/list` (`ws_list_blueprints`) recibe `domain` y devuelve
  `{ruta: {"metadata": …}}` o `{ruta: {"error": "…"}}`; con un dominio no
  cargado, `{}`. Sin `domain` en la tool se piden los tres dominios (tres
  llamadas) y se juntan; un dominio sin blueprints no es error.
- `blueprint/substitute` (`ws_substitute_blueprint`): `domain`, `path`, `input`
  → `{"substituted_config": …}`; errores `unknown_error` con el mensaje de
  HA (entrada que falta: `MissingInput`; blueprint que no existe:
  `FailedToLoad`). La tool devuelve la configuración tal cual (es la que el
  usuario ya tiene o va a tener), con el tope de respuesta y `redact_structure`
  sobre los valores (una entrada puede ser una contraseña).
- Los blueprints por defecto que copia HA al cargar `automation` y `script`
  (`DomainBlueprints.async_populate`, carpeta `homeassistant/`) existen en el
  banco.

## R-5 — Rutas de blueprint

`path` es relativa a `/config/blueprints/<dominio>/`; HA la valida con
`cv.path` y le añade `.yaml`. Hermes valida antes, sin llamar a HA: texto de 1 a
255 caracteres, sin `..` como segmento, sin empezar por `/` ni `\`, sin `:` (unidad
de Windows en los tests), sin caracteres de control, solo segmentos
`[A-Za-z0-9._ -]` separados por `/`. Es más estricto que HA a propósito (no
hay motivo para otra cosa en una ruta de blueprint) y evita que una ruta rara
llegue al sistema de ficheros de HA. La ruta final (con `.yaml`) es la que se
enseña y la que ata el token.

## R-6 — Automatizaciones de dispositivo

`components/device_automation/__init__.py`:

- `device_automation/{trigger,condition,action}/list` con `device_id` →
  lista de diccionarios listos para una automatización (`platform`/`trigger`,
  `domain`, `device_id`, `entity_id`, `type`, `metadata`…). Dispositivo que
  no existe: `handle_device_errors` → `not_found` «Device not found».
- `…/capabilities` con `trigger`, `condition` o `action` (el elemento de la
  lista) → `{"extra_fields": [...]}` serializado con `probatio.to_field_list`
  (lista vacía si no hay).
- Decisión: tres tools de lista con `include_capabilities=False`. Con `true`,
  una llamada de capacidades por elemento, en serie (no se satura la
  WebSocket), para los 50 primeros; si hay más, `capabilities_truncated: true`
  y los demás sin `capabilities`. Una tool aparte de capacidades obligaría al
  agente a reenviar cada elemento: más llamadas y más contexto para lo mismo.
  Las capacidades fallidas de un elemento llevan `capabilities_error`, no
  tumban la lista.

## R-7 — Targets y triggers/condiciones por propósito

`components/websocket_api/commands.py` y `components/websocket_api/automation.py`:

- `extract_from_target(target, expand_group=False, primary_entities_only=True)`
  → `referenced_entities`, `referenced_devices`, `referenced_areas`,
  `missing_devices`, `missing_areas`, `missing_floors`, `missing_labels`.
- `explain_target(target, expand_group=True, primary_entities_only=True)` →
  `includes` (tipo, id, entidades, áreas y dispositivos referenciados) y
  `excludes` (lo que quita cada exclusión). Admite `ENTITY_SERVICE_FIELDS`;
  los demás, `TARGET_FIELDS` (`helpers/config_validation.py`). Los dos
  esquemas tienen las cinco claves (`entity_id`, `device_id`, `area_id`,
  `floor_id`, `label_id`) y un bloque opcional `exclude` con las mismas.
- `get_triggers_for_target`, `get_conditions_for_target`,
  `get_services_for_target` (`target`, `expand_group=True`) → conjunto de
  nombres (`light.turned_on`, `light.brightness_crossed_threshold`,
  `light.turn_on`…) aplicables a alguna entidad del target (las de propósito
  vienen de `components/<dominio>/trigger.py` y `condition.py`; p. ej.
  `components/light/trigger.py`, `TRIGGERS`).
- Decisión: `ha_resolve_target` y `ha_explain_target` devuelven las listas
  ordenadas; las tres de lista, el sobre común con los nombres ordenados.
  `target` se valida en Hermes (claves admitidas, valores texto o lista de
  textos no vacíos, al menos una de las cinco claves fuera de `exclude`,
  `exclude` opcional con las mismas claves; es la regla
  `exclude_requires_target` de HA) para dar un error útil sin gastar llamada.
  Los argumentos
  `expand_group` y `primary_entities_only` existen con los valores por defecto
  de HA de cada comando.
- Las descripciones de cada trigger o condición (sus `options` y campos)
  solo salen por `trigger_platforms/subscribe` y
  `condition_platforms/subscribe` (suscripciones, clase B, `deny`). No se
  tocan: la guía explica la forma general (`trigger: light.turned_on` con
  `target:`) y remite a `ha_validate_config` (duda D-2).
- `unknown_command` (HA anterior) → `ha_version_unsupported` con la versión
  (`ha_core_version`, como `ha_search_related`).

## R-8 — Espera de trigger

`subscribe_trigger` (`commands.py`, `handle_subscribe_trigger`, requiere
admin): valida `trigger` con `cv.TRIGGER_SCHEMA` (errores `invalid_format` o
`home_assistant_error`), inicializa los triggers y manda un evento
`{"variables": {"trigger": …}, "context": …}` por cada disparo, hasta
`unsubscribe_events`.

Decisiones:

1. **Cliente**: `HAClient.ws_subscribe_queue(payload)` generaliza
   `ws_subscribe_events_queue` (mismo montaje y misma limpieza si falla la
   confirmación); `ws_subscribe_events_queue(event_type)` pasa a llamarla con
   `{"type": "subscribe_events", "event_type": …}` sin cambiar su
   comportamiento (sus tests siguen igual). Un error de HA en la confirmación
   llega como `HAConnectionError` con su `code`.
2. **Mismo tope**: `_WaitManager` pasa a crearse una vez en `register_all_tools`
   y se entrega a `wait_for_event.register` y a `wait_for_trigger.register`;
   ambos usan `wait_for_event_max_seconds`. Las esperas de trigger salen en
   `ha_list_active_waits` con `kind: "trigger"` y `trigger_platform`; las de
   eventos conservan exactamente su forma actual (sin claves nuevas). Si la
   familia `events` está desactivada, la espera de trigger sigue funcionando
   pero no se puede listar ni cancelar desde otra llamada; la guía lo dice.
   `wait_for_event.register` sigue aceptando no recibir gestor (crea el suyo),
   para no tocar sus tests.
3. **Solo escuchar, con lista cerrada (fail-closed)**. Un trigger activo no
   siempre se limita a observar. Leyendo los `trigger.py` de
   `components/` de 2026.11.1: `webhook/trigger.py` registra un endpoint HTTP
   sin autenticación; `conversation/trigger.py` registra frases y contesta a
   quien las diga en Assist; `samsungtv`, `webostv` y `lg_netcast` (`turn_on`,
   también como trigger de dispositivo) enganchan una `PluggableAction` que da
   a la tele la acción de encender mientras el trigger existe. Los de
   integraciones personalizadas pueden hacer cualquier cosa. Una lista negra
   dejaría pasar lo que aún no se conoce; el principio III pide lo contrario.
   Regla, para cada elemento de la lista de triggers (clave `trigger` o
   `platform`):
   - sin punto: solo `state`, `numeric_state`, `event`, `time`,
     `time_pattern`, `template`, `sun`, `zone`, `geo_location`,
     `homeassistant`, `mqtt`, `tag`, `calendar`, `persistent_notification` y
     `device` (este, con la regla de abajo sobre su `domain`);
   - `<integración>.<nombre>` (los de propósito, `light.turned_on`, y los de
     integración, `zwave_js.value_updated`) y `device` con `domain`: la
     integración tiene que estar incluida en HA (`manifest/get` →
     `is_built_in: true`; una personalizada que sobrescribe una incluida da
     `false`) y no ser `webhook`, `conversation`, `samsungtv`, `webostv` ni
     `lg_netcast`;
   - lo demás, o si `manifest/get` falla: `trigger_not_allowed` con el motivo
     y sin suscribirse; la pista dice que para eso se cree una automatización.
   `manifest/get` es de la 029 (CAP-043, pendiente de tool dedicada); aquí se
   usa por dentro, solo para leer, como `search/related` en los blueprints.
   Con esto, la anotación de solo lectura es verdad. La lista se revisa al
   subir la versión de HA de referencia (duda D-3).
4. **Respuesta**: `{"matched": true, "trigger": <variables.trigger>, "waited_seconds"}`,
   con `redact_structure` (un estado puede llevar `access_token` de una
   cámara) y el tope de respuesta: si no cabe, se quitan `from_state` y
   `to_state` y se marca `truncated`. `timeout`, `cancelled` y `ws_reconnect`
   como `ha_wait_for_event`. Error de validación de HA → `invalid_trigger` con
   el mensaje redactado; la espera no queda registrada. `report_progress`
   cada 15 s como la otra.

## R-9 — Validar al guardar una automatización o un script

- La 012 deja en `tools/core_validation.py` la lógica de `ha_validate_config`
  dentro de `register`. El tramo D la saca a funciones de módulo
  (`partes_de_config(config)` y `async validar_partes(ha_client, partes)`),
  que usa la tool de la 012 sin cambiar su comportamiento (sus tests siguen
  igual) y que usan `ha_create_or_update_automation` y `_script`.
- Configuración con `use_blueprint`: `validate_config` no la entiende (no hay
  partes). Se sustituye antes con `blueprint/substitute` (dominio
  `automation` o `script`, `path`, `input`) y se validan las partes del
  resultado. Error de sustitución → `blueprint_substitution_failed` sin token.
- Validación en la vista previa, no al confirmar: lo que se confirma es lo
  previsualizado (spec 007) y HA vuelve a validar todo al guardar
  (`/api/config/automation/config/<id>` llama a `async_validate_config_item` y
  responde 400). Validar otra vez al confirmar solo añadiría una llamada.
- Fail-closed: si `validate_config` no responde o responde algo inesperado →
  `validation_unavailable` sin token. La 008 dice «una configuración que HA
  rechazaría se devuelve como error sin token»; dar un token sin haber podido
  validar lo incumpliría en silencio.
- Honestidad: `validate_config` solo valida triggers, condiciones y
  acciones. La vista previa añade `validation: {"validated": [...],
  "not_validated": [...]}`; `mode`, `alias`, `fields`… los valida HA al
  guardar.
- Sin partes que validar (solo `alias`): no se llama a HA; `validation`
  lo dice.
- No depende de la familia `core_diagnostics` (la función es de módulo, no la
  tool), ni de `blueprints`.

## R-10 — Familias

Dos familias nuevas de la 1.2.0, desactivables:

- `blueprints` (`blueprints`): cinco tools; incluye la única de mundo abierto.
  Quien no quiera que su agente pueda importar contenido de internet la apaga
  sin perder el resto.
- `automation_assist` (`device_automation`, `targets`, `wait_for_trigger`):
  nueve tools de solo lectura que ayudan a escribir automatizaciones.

Una sola familia mezclaría la tool de mundo abierto con ocho lecturas
inocuas. `wait_for_trigger` no va en `events` porque FR-010 de la 008 pide
familias nuevas para tools nuevas.

## R-11 — Banco de Core

- Las tres tools que modifican se prueban contra HA 2026.11.1 real con el
  lector (`blueprint/list` por la WebSocket del lector).
- **Importación sin internet**: con `frontend:` cargado (028), HA sirve
  `/config/www` en `/local/` sin autenticación si la carpeta existe al
  arrancar (`components/frontend/__init__.py`, `StaticPathConfig("/local", …)`).
  Se añade `tests/banco/ha_config/www/hermes_banco/luz_por_movimiento.yaml`
  (un blueprint de automatización mínimo, escrito para el banco) y se importa
  desde `http://127.0.0.1:8123/local/hermes_banco/luz_por_movimiento.yaml`:
  dentro del contenedor, 127.0.0.1 es la propia HA, así que la regla que
  corta la salida (tráfico de la subred hacia fuera) no la toca. Es una
  descarga HTTP real por el importador genérico de HA
  (`fetch_blueprint_from_generic_url`); la ruta sugerida es
  `127.0.0.1/luz_por_movimiento`. Los importadores de GitHub, gist, foro y web
  de HA no se pueden probar sin internet: en la matriz de la 014 la fila de
  `ha_import_blueprint` es `banco de Core / ok` con esa salvedad en la nota, y
  la prueba con una URL de GitHub queda en los pendientes manuales de la hoja
  de ruta. Alternativas descartadas: un contenedor auxiliar con un servidor
  HTTP (otra imagen y otra regla de red en el workflow) o un servidor en el
  proceso de pytest (el contenedor tendría que alcanzar el host: más
  configuración de red y más frágil).
- Que el contenido cambie entre vista previa y confirmación no se puede
  provocar en el banco sin escribir en `www` desde el test; se prueba en
  unitarios.
- En uso: el test crea una automatización con `use_blueprint` del blueprint
  por defecto `homeassistant/motion_light.yaml` y comprueba `blueprint_in_use`
  sin token y que el fichero sigue; luego borra la automatización.
- Dispositivo: `kitchen_sink` crea dispositivos con entidades; las listas de
  dispositivo y de target se ejecutan contra uno de ellos (lectura, no
  exigida por el invariante, pero da las formas reales).
- Espera de trigger: un trigger de estado sobre un `input_boolean` del banco;
  el lector lo cambia mientras la tool espera.
- FR-010: `ha_create_or_update_automation` con un trigger inválido → error sin
  token y `automations.yaml` sin cambios (lector).

## R-12 — Tramos

La 008 da 3 tramos: (a) blueprints; (b) dispositivo y targets; (c) espera de
trigger y validación al guardar. El (a) tiene tres tools con vista previa no
trivial, la importación con huella y el montaje del banco: no cabe con
holgura. Se parte en cuatro:

| Tramo | Contenido | Tools |
|---|---|---|
| A | Base de la sub-feature (familia `blueprints`, rutas, lector YAML tolerante) y blueprints locales: listar, sustituir, guardar, borrar | 4 (2 modifican) |
| B | Importar (vista previa de terceros, huella, banco con `www`) | 1 (modifica) |
| C | Familia `automation_assist`, dispositivo y targets | 8 (lectura) |
| D | Espera de trigger, validación al guardar, documentación final | 1 (lectura) + FR-010 |

B depende de A (ruta, `used_by`, `blueprint/save`); C de nada de la 017 (puede
ir en paralelo con B si no tocan a la vez los ficheros comunes); D de A
(sustitución) y de la 012.

## R-13 — Tabla de comandos

- Las 17 entradas pasan a `E("dedicated", "cubierto por <tool>", <familia>, tool=…, cap=…)`.
  Hoy son `deny` «pendiente de tool dedicada (spec 017)», salvo
  `subscribe_trigger` (`deny` de clase B).
- El generador ya consulta `_DEDICADAS_INICIALES` para la clase A (regla de la
  012). Para `subscribe_trigger` se cambia la fila de
  `specs/008-cobertura-total/inventario/core-ws.tsv` a clase `A`, nota
  «Esperar a un trigger (un solo disparo)» y CAP-038: es la reclasificación que
  propone la research de la 008 (CAP-038 y la tabla de clase B, «se propone
  reclasificar»), y `MATRIZ` del generador ya tiene CAP-038 con vía D. El
  extractor conserva las columnas manuales de las filas existentes.
- `search/related` sigue `dedicated` a `ha_search_related`; la 017 lo usa por
  dentro en las vistas previas.
- `validate_config` y `test_condition` son de la 012.
