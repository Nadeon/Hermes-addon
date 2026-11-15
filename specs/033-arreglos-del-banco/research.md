# Research: 033 — arreglos de tools existentes destapados por el banco

Fuentes: el código de Hermes en la punta de `feat/cobertura-total` (`cc478d4`,
con la 009 y la 010 integradas), el de HA Core 2026.11.1 (solo lectura) y los
informes de revisión de la 010 (F3) y de la 028 (H3, «sospechas que pasaron a
otra sub-feature» y «fuera de alcance»). Rutas de HA relativas a la raíz de
`homeassistant/`.

Línea base de la suite en Windows sobre `cc478d4`: 2080 passed, 38 skipped,
6 failed (los 6 conocidos).

## R-1 — Argumentos que el token deja fuera (FR-001…FR-003)

**Fallo confirmado.** `guarded_entity_invoke` (`tools/_common.py`) ata
`args = {"entity_id", "service"}` y manda a HA
`{"entity_id", **extra_data}`, con `extra_data = {"variables": variables}`.
Lo que llega a HA incluye `variables`; lo que ata el token, no. La vista previa
tampoco las enseña. Lo usan `ha_trigger_automation` (`automation.trigger`) y
`ha_run_script` (`script.turn_on`).

**Auditoría del resto.** Se recorrieron por AST las 79 tools registradas con
`confirmation_token` y los ayudantes comunes, comparando la firma con el dict
que se pasa a `create_confirmation_token` / `validate_confirmation_token` /
`resolve_confirmation_token` y con lo que se envía a HA o al Supervisor:

| Grupo | Atado | Veredicto |
|---|---|---|
| `collection_update_flow` (los `ha_create_or_update_*` de helpers y `ha_update_person`) | `entity_id`, `config` normalizada (la misma que se envía) | bien |
| `collection_delete_flow` (borrados de helpers y personas) | `entity_id` | bien |
| `guarded_reload` (7 `ha_reload_*`) | `domain` (no hay más argumentos) | bien |
| `guarded_entity_invoke` | `entity_id`, `service` | **falta `variables`** |
| `ha_call_service` | `domain`, `service`, `service_data` | bien |
| `ha_create_or_update_automation` / `_script` / `_scene` | id y `config` normalizada (omitible por hash) | bien |
| `ha_delete_automation` / `_script` / `_scene` | id | bien |
| `ha_save_lovelace_dashboard` | `url_path`, `config` (omitible), `remove_top_level_keys` | bien |
| `ha_update_lovelace_dashboard_metadata` | `url_path`, `dashboard_id`, `updates` | bien |
| `ha_create/update/delete_lovelace_resource`, `ha_delete_lovelace_dashboard` | todos sus argumentos | bien |
| registros (`ha_update_*`/`ha_delete_*` de área, planta, etiqueta, categoría, dispositivo, entidad; `ha_remove_device*`) | id y `updates` normalizados (los mismos que se envían) | bien |
| `ha_disable_config_entry`, `ha_delete_config_entry`, `ha_ignore_repair` | todos | bien |
| `sv_*` (add-ons, backups, `sv_restart_core`, `sv_reboot_host`, resolución) | todos (incluida `password` y las listas de la restauración parcial) | bien |
| `fs_*` | rutas normalizadas, `content` (omitible), `overwrite`, `timestamp`, `key`/`value` | bien |

`ha_fire_event` y las tools de flujos de config entries no tienen
confirmación (fuera de esta auditoría por definición). Conclusión: solo
`guarded_entity_invoke`. Para que no vuelva a pasar, FR-003 convierte esta
tabla en un test de inventario (R-8).

**Decisión de diseño.** Atar `{"entity_id", "service", "variables"}` con
`variables` tal como llega (`None` si no llega). Más estricto que «atar lo que
se envía» (que trataría `None` y `{}` igual), y más simple de razonar. La
vista previa añade `"variables": variables`. Ningún otro cambio: la entidad no
restringida sigue en un paso.

Alternativas descartadas: atar el `payload` entero (equivalente, pero acopla
el hash a cómo se construye el payload); quitar `variables` cuando la entidad
está restringida (rompe a quien las usa bien).

## R-2 — `ha_reload_counters` (FR-004)

`components/counter/services.py` registra solo `increment`, `decrement`,
`reset` y `set_value`. `components/counter/__init__.py` carga la
`YamlCollection` una vez en `async_setup` y no registra ningún servicio admin
de recarga (a diferencia de `input_*`, `timer`, `schedule` y `zone`, que usan
`async_register_admin_service(..., SERVICE_RELOAD, ...)`). El REST de Core
responde 400 a `/api/services/counter/reload` (`components/api/__init__.py`:
`has_service` falso → `HTTPBadRequest`). Lo comprobó el banco (010, F3).

Otras vías: `homeassistant.reload_all` recarga las integraciones que tienen
recarga, no los contadores; `homeassistant.reload_core_config` tampoco. Los
contadores de la colección de almacenamiento (UI, Hermes) se aplican al
guardar y no necesitan recarga; los de YAML solo se releen al reiniciar.
**No hay una recarga correcta que proponer.**

Decisión (del supervisor): la tool se queda, responde `not_supported` siempre
(con o sin token, sin emitir ni gastar tokens, sin llamar a HA), con
`_deprecated` como los alias `ha_hacs_*` y retirada en la 1.3.0. Nombre,
argumentos (`confirmation_token` sigue, ignorado) y anotaciones (`-DI-`) no
cambian (FR-020 de la 008). El test «toda tool destructiva acepta token» sigue
cumpliéndose por la firma.

En el banco no puede ser «probada» (no modifica nada). Va a `NO_EJECUTABLES`
con el motivo, y su test del banco es un **canario**: comprueba que Core sigue
sin `counter.reload` en `get_services` (si un HA futuro lo añade, el test cae y
avisa de que la tool puede volver a hacer su trabajo) y que la tool responde
`not_supported` sin que el lector vea ninguna llamada de servicio.

## R-3 — `ha_wait_for_event` y `ctx` (FR-005)

`tools/wait_for_event.py` declara `ctx: Any`. El SDK (`mcp/server/mcpserver`,
`utilities/context_injection.py`, `find_context_parameter`) solo inyecta un
parámetro cuya anotación resuelta sea subclase de `Context`; con `Any`,
`context_kwarg` queda en `None` y `ctx` entra en el esquema como argumento
obligatorio (lo vio la revisión de la 028: `"ctx"` en `required`). El
keepalive usa `hasattr(ctx, "report_progress")`, que con el `dict` que manda
el cliente es falso: el aviso nunca sale.

Arreglo: `from mcp.server.mcpserver import Context` y `ctx: Context` en la
misma posición (primer argumento; sin valor por defecto porque `event_type` no
lo tiene), como hace `tools/ping.py` (`test_progress`). Los tests actuales
llaman a la función con `None` como primer argumento y siguen valiendo. `find_context_parameter`
usa `typing.get_type_hints`, que sigue `__wrapped__` para las globales, así que
el envoltorio de `requires_ready` (`functools.wraps`) no lo estorba (S-02; lo
fija un test del registro: `context_kwarg == "ctx"` y `ctx` fuera del esquema).

Compatibilidad: el modelo de argumentos del SDK (`ArgModelBase`, pydantic) no
prohíbe claves extra, así que un cliente que siga mandando `ctx` no recibe
error (test). Es la única propiedad que desaparece del esquema: el argumento
era obligatorio y no tenía un valor con sentido, así que ningún cliente pierde
nada. Excepción escrita en el test de la instantánea (R-8).

## R-4 — `ha_create_scene_from_current` (FR-006)

`components/homeassistant/scene.py`:

- `CREATE_SCENE_SCHEMA` admite `scene_id` (slug), `entities` y
  `snapshot_entities`; no `name`. Una clave sobrante se rechaza: hoy, con
  `name`, HA responde 400 siempre (revisión 028, H3).
- `create_service`: las entidades de `snapshot_entities` que no existen se
  saltan con un aviso; si no queda ninguna, «Empty scenes are not allowed» y
  vuelve **sin error**. Si `scene.<id>` existe y es una `HomeAssistantScene`
  con `from_service`, la quita y crea la nueva (reemplazo en silencio); si es
  de otro origen, avisa en el log y vuelve **sin error** sin crear nada.
- La escena creada tiene `unique_id` `None` (no entra en el registro de
  entidades) y su atributo `entity_id` es la lista de entidades capturadas;
  `id` solo aparece en las escenas con `id` de configuración.
- `reload_config` llama a `platform.async_reset()`: toda recarga de escenas
  (incluida la del `post_write_hook` de `config/scene.py` al guardar o borrar
  una escena) **borra las temporales**; reiniciar HA también.

Diseño (patrón de `ha_create_or_update_scene`: crear sin token, reemplazar con
token):

1. `name` presente → `name_not_supported` (sin HA). El nombre no se puede
   poner: la escena no está en el registro, así que tampoco se puede renombrar
   después. Ignorarlo en silencio daría por buena una petición que no se
   cumple.
2. Entidades inexistentes (lectura de estado de cada una) →
   `entity_not_found` con la lista.
3. Estado de `scene.<id>`:
   - no existe → `scene.create` directo;
   - existe con `id` en atributos, o con entrada en el registro de entidades →
     `scene_exists` (HA no haría nada);
   - existe sin `id` y sin registro → temporal: dos pasos; vista previa con
     `current_entities` (atributo `entity_id` actual), `new_entities`, y el
     efecto («HA reemplaza la escena temporal; las escenas temporales se
     pierden al reiniciar HA o recargar escenas»). Token atado a `scene_id`
     normalizado y `entity_ids`.
4. Después de `scene.create`, leer `scene.<id>` y comparar su atributo
   `entity_id` con lo pedido; si no coincide → `scene_not_created` con lo
   visto (cubre la escena de `configuration.yaml` sin `id`, S-03).

Anotaciones: hoy `----` por el prefijo `ha_create_`; pasa a `-D--` (destructiva
porque puede reemplazar, no idempotente como hoy) entrando en
`_DESTRUCTIVE_EXACT` de `tools/_annotations.py`. Gana `confirmation_token`
opcional; los dos tests de coherencia token/destructiva del registro siguen en
verde.

## R-5 — Dónde se guardan las escenas (FR-007)

`components/config/scene.py` usa `SCENE_CONFIG_PATH` (`scenes.yaml`) como
fichero de la vista de configuración. `tools/scenes.py` dice
`.storage/core.scene_*` en tres docstrings (`ha_get_scene`,
`ha_create_or_update_scene`, `ha_delete_scene`) y la segunda afirma además que
ve las escenas creadas con `scene.create`, que no están en `scenes.yaml`. El
banco de la 028 lo vio en la práctica. Solo cambia texto.

## R-6 — `ha_get_config_entry_options` (FR-008)

`config_entries/get_single` (`components/config/config_entries.py`) devuelve
`{"config_entry": entry.as_json_fragment}`; `ConfigEntry.as_json_fragment`
(`config_entries.py`) no incluye `options` ni `data`. Búsqueda de otras vías en
Core 2026.11.1:

- WebSocket `config_entries/get`, `subscribe`, `subentries/list`: misma forma
  sin `options`.
- REST `/api/config/config_entries/entry`: igual.
- Diagnósticos (`diagnostics/get`, descarga REST): solo lo que cada
  integración decida devolver, redactado por ella; no es general.
- Un flujo de opciones (`ha_start_options_flow`) devuelve un formulario que
  en muchas integraciones trae los valores actuales como sugeridos, pero
  depende de la integración y deja un flujo abierto que hay que abortar.
- `.storage/core.config_entries` sí las tiene, pero `.storage` está vetado en
  las `fs_*` (y debe seguir así).

**No hay vía correcta.** La tool responde `not_supported` con lo que sí puede
dar (`entry_id`, `domain`, `title`, `supports_options`), el motivo y la
indicación del flujo de opciones (diciendo que depende de la integración), y
`_deprecated` con retirada en la 1.3.0 (misma decisión que R-2, por coherencia:
una tool que no puede hacer su trabajo no se mantiene para siempre). Se quita
la clave `options`: devolver `{}` era la mentira. `not_found` y los errores de
conexión no cambian.

## R-7 — `amount` en los contadores (FR-009)

`components/counter/entity.py`, `async_set_value`: `ValueError` si el valor
pasa de `maximum`, baja de `minimum` o `value % step != 0`. El REST de Core
(`components/api/__init__.py`) solo captura `probatio.Invalid`,
`ServiceNotFound`, `ServiceValidationError` y `HomeAssistantError`: el
`ValueError` sale como 500 genérico. **Sospecha confirmada en el código** para
`step` ≠ 1 (aunque `amount` sea múltiplo del `step`, si el valor actual no lo
es: el banco de la 010 usa un contador con `initial` 5 y `step` 3) y para
resultados fuera de los límites (con `step` 1 también). Con `step` 1 y sin
límites, `amount` funciona.

`increment`/`decrement` no fallan: `compute_next_state` recorta a los límites.
Los atributos del estado traen `step`, `minimum` y `maximum`
(`extra_state_attributes`).

Diseño: `_bulk_adjust` ya lee el estado; añade la comprobación con esos
atributos antes de `set_value` y responde `invalid_amount` con `reason`
(`not_multiple_of_step` o `out_of_range`), `current`, `target`, `step` y
límites, y una indicación (usar la tool sin `amount`, o `ha_set_counter_value`
con un valor válido). `amount` sigue significando «se suma al valor actual».

Descartado: repetir `increment` `amount/step` veces (no atómico, N llamadas, y
cambia el significado si `amount` no es múltiplo); recortar a los límites como
`increment` (cambia el significado sin avisar).

El banco lo confirma en el tramo 2 antes de arreglar: test con `step` 3 desde
5 → hoy 500 (rojo) → tras el arreglo `invalid_amount` y estado intacto.

Ampliación del alcance (extra del supervisor en el tramo 2, T040): la spec
dejaba fuera `ha_set_counter_value`, que tiene el mismo 500 con un valor fuera
de límites o que no es múltiplo del `step`. Se hizo con el mismo ayudante
(`_value_problem`) y responde `invalid_value`, con test unitario y de banco.

## R-8 — Banco, inventario de tokens e instantáneas (FR-003, FR-010, FR-011)

- **Banco (010)**: `tests/banco/cobertura.py` (`PROBADAS_EN_BANCO`,
  `NO_EJECUTABLES`, `FALLAN_EN_BANCO`, `XFAIL_PERMITIDOS`) y el plugin
  `tests/banco/obligatorio.py`, que en el job exige ejecución real y no admite
  `xfail` fuera de la lista. El `xfail` de `TestCounter.test_recarga`
  (`tests/banco/test_banco_helpers_tiempo.py`) es estricto: en cuanto la tool
  deja de dar el 400, el test «pasa» y el job se pone en rojo; por eso el
  arreglo y la retirada del `xfail` van en el mismo commit.
- **Banco (028)**: `tests/banco/cobertura_escrituras.py` (`PROBADAS_028`,
  `HALLAZGOS_028`, `XFAIL_PERMITIDOS_028`) y `tests/banco/base_escrituras.py`.
  La convergencia de la 028 añade (T032) un `xfail` `HALLAZGO` para
  `ha_create_scene_from_current` con `name` y (T033) un script y una
  automatización restringidos inocuos (acción `input_boolean.reload`) que este
  tramo 1 reutiliza. Si al implementar no están integrados, ver S-01.
- **Inventario de argumentos atados (FR-003)**: test de la suite normal con un
  dict `tool → {argumento: "atado" | "exento: <motivo>"}` y una comprobación
  por AST de que cubre exactamente las tools con `confirmation_token` y todos
  los argumentos de su firma. Es documental y no prueba el hash por sí solo;
  por eso las tools que se arreglan llevan además tests de comportamiento, y
  un test genérico por muestreo: para cada tool del grupo `guarded_entity_invoke`,
  vista previa con un valor y confirmación con otro.
- **Instantáneas (011)**: `tests/test_tools_registration.py`
  (`_HINTS_SNAPSHOT`, `test_hints_did_not_change`; y, desde la 011,
  `test_esquemas_de_la_1_1_2` con `tests/fixtures/esquemas_1_1_2.json`). Las
  excepciones se escriben como la de `hermes_guide` de la 011: modificando el
  esperado en el test, con el porqué al lado. `_HINTS_SNAPSHOT` cambia una
  línea (`ha_create_scene_from_current`) con el comentario de FR-011.

## R-9 — Documentación (FR-012)

- `hermes/CHANGELOG.md`, `## [1.2.0]` → `### Correcciones`: subsección
  «Arreglos destapados por el banco (033)», una viñeta por tool.
- `tools/guide.py`: tema de automatizaciones y escenas (variables atadas,
  escena temporal, `name`), tema de helpers (contadores: sin recarga, regla de
  `amount`), tema de integraciones (opciones no publicadas), aviso de
  `ha_wait_for_event` sin cambios de texto.
- `docs/HOJA-DE-RUTA.md`: fila 033 de la tabla del programa (este cambio la
  añade como «pendiente»; el cierre la pasa a «hecha») y tabla de
  deprecaciones con `ha_reload_counters`, `ha_get_config_entry_options` y el
  argumento `name` de `ha_create_scene_from_current`, retirada en la 1.3.0.
- `README.md`/`README.es.md`: sin cambios (no cambia el número de tools ni
  ninguna opción). `hermes/DOCS.md`: sin cambios. `SECURITY.md`: sin cambios
  (R-1).
