# Investigación: Hermes 1.1.0 — tools de diagnóstico y organización

Fase 0 del plan. Recoge las decisiones técnicas, por qué se toman y qué se
descartó. La evidencia de fondo es la investigación de APIs para 1.1.0 (código
de HA Core 2026.11.1 y de los tags 2024.10.0–2026.10.0, y Supervisor
2026.11.0, leídos en sus fuentes) y el informe de compatibilidad de noviembre
de 2026, resumidos en `docs/HOJA-DE-RUTA.md`. No quedan marcas «NEEDS
CLARIFICATION»; lo que no se pudo verificar está en «Pendiente de verificar al
implementar».

## Transversal

### R-0.1 Base 1.0.12

- **Decisión**: se usan tal cual `HAConnectionError.code` (decidir por código de error WS) y `hermes/src/hermes/ha_version.py` (`ha_core_version`, `ha_at_least` → `True`/`False`/`None`, sin caché, `.devN` por `base_version`).
- **Razón**: son exactamente lo que necesitan los mínimos de versión (FR-021, FR-027, FR-039) y los `not_found` por código (FR-019). Reimplementarlos duplicaría código y rompería el principio IX.
- **Alternativas**: comparar textos de error (frágil; es el fallo D1 que corrigió 1.0.12).

### R-0.2 Error común de versión

- **Decisión**: `{"error": "ha_version_unsupported", "feature": "<qué>", "required": "2025.1.0", "current": "<versión leída>"}`. Se construye en cada módulo (tres líneas) en lugar de añadir un helper compartido.
- **Razón**: los bloques B y C lo necesitan en paralelo; un helper común en `ha_version.py` crearía una dependencia entre bloques para un diccionario. El contrato (contracts/tools.md) fija la forma y los tests de cada bloque la comprueban.
- **Alternativas**: helper en `ha_version.py` en una fase 0 (otra fase secuencial para tres líneas).

### R-0.3 Organización en bloques

- **Decisión**: tres bloques paralelos que no comparten ningún fichero (A organización, B diagnóstico, C Supervisor + backups + retención) y un bloque de integración al final (registro de tools, anotaciones, opción nueva, guía, documentación y tests de manifiesto y registro).
- **Razón**: lo pidió el mantenedor; además, las tools nuevas viven en módulos nuevos, así que los bloques no se pisan. El registro (`tools/__init__.py`) y las anotaciones (`tools/_annotations.py`) son únicos y se tocan una vez.
- **Consecuencia**: hasta la integración, las tools nuevas no están registradas. Dos tests transversales de `tests/test_tools_registration.py` (toda tool declarada está registrada; toda tool con token es destructiva) fallan dentro de cada bloque **por diseño**. Cada bloque valida con sus propios tests y con la suite completa excluyendo ese fichero; la integración deja la suite entera en verde antes de publicar (principio VII: la suite completa pasa antes de cada commit **que se vaya a publicar**; los commits de bloque no se publican, se fusionan con squash).
- **Alternativas**: una fase 0 que registrara módulos vacíos (contradice el reparto pedido y obliga a tocar el registro dos veces).

### R-0.4 Estilo de las tools

- **Decisión**: las `ha_*` nuevas siguen a `tools/registry_area.py`: `@mcp.tool()` + `@ready`, retorno `-> object` con `json.dumps(..., ensure_ascii=False)`, `confirmation_token` con `create_confirmation_token`/`validate_confirmation_token`/`complete_confirmation_token`, y `logger.info("<tool>_ok")`. Las `sv_*` siguen a `tools/backups.py`: retorno de `dict`, sin `@ready`, identificadores validados con `validate_identifier`.
- **Razón**: principio IX (seguir el estilo del fichero vecino) y los tests de contrato de retorno que ya existen.

## Bloque A — Plantas, etiquetas y categorías

### R-A1 Comandos

- **Decisión**: `config/floor_registry/{list,create,update,delete}`, `config/label_registry/{list,create,update,delete}` y `config/category_registry/{list,create,update,delete}` (estos con `scope` obligatorio, también en `list`). Sin `floor_registry/reorder` (≥ 2025.12).
- **Razón**: existen con los mismos campos en 2024.10.0 (mínimo de Hermes desde 1.0.12), así que no necesitan comprobación de versión. Esquemas: floor `name`, `aliases`, `icon`, `level`; label `name`, `color`, `description`, `icon`; category `scope`, `name`, `icon`.

### R-A2 Validación previa

- **Decisión**: Hermes valida `name` no vacío, `level` entero o `None`, `aliases` lista de textos, `color` en los 26 colores de tema de HA (`primary, accent, disabled, red, pink, purple, deep-purple, indigo, blue, light-blue, cyan, teal, green, light-green, lime, yellow, amber, orange, deep-orange, brown, light-grey, grey, dark-grey, blue-grey, black, white`) o `#rrggbb`, y `scope` en `automation`, `script`, `scene`, `helpers`.
- **Razón**: Home Assistant valida casi todo, pero no el `scope` (texto libre): una categoría con un scope que el frontend no usa sería invisible. El resto se valida para dar errores claros sin ida y vuelta.

### R-A3 Vistas previas de borrado

- **Decisión**:
  - `ha_delete_floor`: áreas con `floor_id == X` (de `config/area_registry/list`) + `search/related` con `item_type: "floor"` para `automation`, `script` y `scene`.
  - `ha_delete_label`: áreas, dispositivos y entidades con `X in labels` (de los tres registros) + `search/related` con `item_type: "label"` para `automation`, `script` y `scene`.
  - `ha_delete_category`: entidades con `categories[scope] == X` (de `config/entity_registry/list`).
  - Cualquier lectura que falle o devuelva algo que no sea lista/dict → `preview_unavailable` sin token.
- **Razón**: las asignaciones se calculan de los registros, que son la fuente de verdad de lo que Home Assistant limpiará. Las referencias en destinos de automatizaciones (que HA **no** edita) solo las da `search/related`. Separarlas en la vista previa («perderán la asignación» frente a «dejarán de resolver») es lo que la hace veraz (principio IV).
- **Duplicación aceptada**: la llamada a `search/related` (cinco líneas) se escribe en el bloque A en lugar de importar de `tools/search.py` (bloque B), para no crear dependencias entre bloques paralelos.
- **Alternativas**: solo `search/related` (mezcla asignación y referencia, y no distingue qué limpia HA); solo registros (omite que las automatizaciones dejarán de encontrar sus destinos).

### R-A4 Ediciones con token

- **Decisión**: `ha_update_floor/label/category` exigen token, como `ha_update_area`. Antes de emitirlo leen la entrada actual: si no existe, `not_found`; si la lectura falla, `preview_unavailable`. Los argumentos atados al token son el id (y `scope` en categorías) y los cambios normalizados.
- **Razón**: renombrar una planta o etiqueta cambia cómo responde Assist y lo que ve el usuario en toda la interfaz, igual que renombrar un área (ya marcada destructiva). El invariante «quien pide token se declara destructiva» lo vigila un test.
- **Diferencia con `ha_update_area`**: esa emite token aunque no pueda leer el área (`current: null`). Aquí se falla cerrado; no se cambia `ha_update_area` (principio IX).

## Bloque B — Diagnóstico

### R-B1 Repairs

- **Decisión**: `repairs/list_issues` (resumido y filtrado en Hermes) y `repairs/ignore_issue` `{domain, issue_id, ignore}`. Sin `repairs/get_issue_data` ni flujos de reparación.
- **Razón**: los dos existen en 2024.10.0 y no son `require_admin`. `get_issue_data` son datos internos que pueden contener datos sensibles; los flujos de reparación son escritura con efectos propios de cada integración.
- **Confirmación**: ignorar oculta un aviso que puede anunciar una rotura futura (`breaks_in_ha_version`). La primera llamada lee la lista; si el issue ya está como se pide, `unchanged` sin token; si no, vista previa y token.
- **Redacción**: `translation_placeholders` pasa por `redact_structure` y cada valor de texto por `redact_secrets`.
- **Alternativas**: devolver el texto traducido con `frontend/get_translations` (mecanismo inferido, no verificado; queda para otra spec).

### R-B2 Trazas

- **Decisión**: `trace/list {domain, item_id?}` y `trace/get {domain, item_id, run_id}`. Resumen por defecto; `detail="full"` redactado y con límite.
- **`item_id`**: en automatizaciones es el `id` de la configuración y en scripts la clave del script; en ambos casos coincide con el `unique_id` del registro de entidades. Se acepta `entity_id` y se traduce con `config/entity_registry/get` → `unique_id`.
- **Resumen**: cabecera (`run_id`, `domain`, `item_id`, `state`, `script_execution`, `timestamp.start/finish`, `last_step`, `trigger`, `error`, `not_triggered`) y pasos (`path`, `timestamp`, `result` recortado a 500 caracteres de JSON, `error`, `child_id`). Sin `config`, `blueprint_inputs`, `context` ni `changed_variables`.
- **Completo**: añade `changed_variables` por paso y `config`, con `redact_structure` + `redact_secrets` en cada texto (cubre `access_token` por clave y `?token=` por patrón en la URL de la imagen de una cámara).
- **Límite**: `min(64 KiB, response_max_bytes)`. Orden de recorte: variables de los últimos pasos hacia atrás, después `config`, después pasos finales del resumen; `truncated: true` y `omitted: {"changed_variables_steps": n, "config": bool, "steps": n}`.
- **Lista**: más recientes primero (por `timestamp.start`), `limit` 1–50; `error` y `trigger` recortados a 300 caracteres y redactados.
- **Razón**: una traza completa pesa de KB a cientos de KB y lleva estados con todos sus atributos; un resumen responde casi siempre a «¿por qué no saltó?».
- **Alternativas**: devolver `trace/get` en crudo con truncado bruto (corta JSON a medias y deja pasar secretos).

### R-B3 `search/related`

- **Decisión**: `search/related {item_type, item_id}`; `include_disabled_entities` solo se envía si es `true` y HA ≥ 2026.10 (`ha_at_least(..., "2026.10.0")`): `False` → `ha_version_unsupported`; `None` → se envía y un `invalid_format` se traduce a `ha_version_unsupported` con `current: null`.
- **Razón**: las versiones anteriores rechazan claves extra. Con `false` no se envía nunca: el resultado es el mismo y funciona en todas las versiones.
- **Recorte**: 200 ids por tipo, con `counts` exactos y `truncated`.

## Bloque C — Supervisor, backups de HA y retención

### R-C1 Resolución del Supervisor

- **Decisión**: `GET /resolution/info` (todo en una llamada), `DELETE /resolution/issue/{uuid}` y `DELETE /resolution/suggestion/{uuid}`. Nunca `POST /resolution/suggestion/{uuid}`.
- **Razón**: no hay endpoints separados de issues o sugerencias. Aplicar una sugerencia puede borrar datos o reiniciar (`clear_full_backup`, `execute_remove`, `execute_reset`, `adopt_data_disk`, `execute_reboot`), y está fuera de alcance por decisión del mantenedor.
- **Vista previa**: se busca el uuid en `/resolution/info`; si no está, `not_found` sin token.
- **Nombres**: la API v1 traduce tipos a nombres legados; se devuelven sin traducir (spec S-07).
- **Test de guarda**: un test recorre el código de `hermes/src/hermes/tools/` y falla si alguna llamada combina `POST` con `/resolution/suggestion/`.

### R-C2 Backups de Home Assistant

- **Decisión**: `backup/info`, `backup/details {backup_id}` y `backup/config/info`, con `ha_at_least(..., "2025.1.0")` antes; respuestas construidas por lista blanca.
- **Lista blanca de un backup**: `backup_id`, `name`, `date`, `agents` (`{agent_id: {protected, size}}`), `addons` (`slug`, `name`, `version`), `database_included`, `folders`, `homeassistant_included`, `homeassistant_version`, `failed_agent_ids`, `failed_addons`, `failed_folders`, `with_automatic_settings`. Fuera `extra_metadata` (lleva `instance_id`).
- **Lista blanca de la configuración**: `agents` (`protected`, `retention`), `automatic_backups_configured`, `create_backup` (`agent_ids`, `include_addons`, `include_all_addons`, `include_database`, `include_folders`, `name`, `password_set`), `last_attempted_automatic_backup`, `last_completed_automatic_backup`, `retention` (`copies`, `days`), `schedule`, `next_automatic_backup`, `next_automatic_backup_additional`. `password` **nunca** se copia; `password_set = isinstance(password, str) and password != ""`. El resultado pasa además por `redact_structure` (defensa en profundidad).
- **`agent_errors`**: `{agent_id: mensaje}` con el mensaje recortado a 300 caracteres, `redact_secrets` y una máscara local de IPv4, IPv6 y hosts de URL (`<ip>`, `<host>`), porque pueden nombrar NAS o recursos SMB de la red del usuario.
- **Errores**: `unknown_command` → `backup_integration_unavailable`; `backup/details` con `backup: null` → `not_found`.
- **Razón**: `backup/config/info` devuelve la contraseña de cifrado de los backups automáticos en claro (principio II). Una lista blanca falla cerrada ante campos nuevos.
- **Alternativas**: reenviar con `redact_structure` (la clave `password` sí se redactaría, pero cualquier campo nuevo pasaría tal cual: incumple el principio I).

### R-C3 Retención de los safety backups

- **Decisión**: módulo nuevo `hermes/src/hermes/safety_retention.py` con una anotación propia en `/data/safety_backups.json` y una poda que se ejecuta tras cada safety backup automático confirmado.
- **Anotación**: cada lanzamiento (automático en `fs_write.maybe_trigger_safety_backup`, manual en `sv_create_safety_backup`) añade `{name, job_id, launched_at, origin, slug: null, confirmed_by: null}`. Una respuesta síncrona con `slug` lo confirma en el acto (`confirmed_by: "sync_response"`).
- **Confirmación del slug**: (1) la referencia del job terminado sin errores (`GET /jobs/{job_id}` → `done is True`, `errors` vacío, `reference` texto) → `confirmed_by: "job_reference"`; el camino automático la obtiene al sondear; (2) si el job ya no existe o no trae referencia: el **único** backup de `GET /backups` con exactamente el nombre anotado y `date` a menos de 10 minutos de `launched_at` → `confirmed_by: "unique_name_date"`. Cero o varios candidatos → sin confirmar.
- **Candidato a poda**: entrada confirmada + backup presente en `GET /backups` con el mismo slug y el mismo nombre + nombre con formato exacto (`^hermes-safety-\d{8}T\d{6}Z$` o `^hermes-safety-\d{8}-\d{6}$`) + `type == "full"` + `protected` falso + `locations` con como mucho un elemento (o sin `locations` y un único `location`) + `date` legible. Cualquier incoherencia (mismo slug con otro nombre, fecha ilegible) excluye la entrada y se registra el motivo.
- **Poda**: si `keep == 0`, nada. Si hay más de `keep` candidatos, se ordenan por `date` (desempate por `launched_at`), se conservan los `keep` más recientes y se borran los demás con `DELETE /backups/{slug}`, de más antiguo a más reciente, como mucho 5 por ejecución; el primer fallo detiene la poda. Los borrados salen de la anotación.
- **Limpieza de la anotación**: tras un `GET /backups` correcto, se quitan las entradas confirmadas cuyo slug ya no existe y las no confirmadas de más de 7 días (quedan fuera de la retención para siempre: fail-closed). Máximo 100 entradas (se descartan las más antiguas no confirmadas primero; si todas están confirmadas, las más antiguas, que ya no se podrán podar automáticamente).
- **Cuándo**: tras el éxito confirmado del safety backup automático, tanto si se confirma en el mismo sondeo como si se confirma una anotación pendiente en la llamada siguiente (flujo de 1.0.12). La poda va dentro de un `try` que nunca propaga: un fallo se registra y la escritura continúa.
- **Por qué no en `sv_create_safety_backup`**: la tool vuelve en cuanto el Supervisor acepta el job y su nombre dice «crear»; si podara, sería destructiva sin token (principio V y el invariante de tokens). Sus backups se anotan y se podan en la siguiente poda.
- **Concurrencia**: un `asyncio.Lock` del módulo serializa lecturas y escrituras de la anotación; escritura atómica (`.tmp` + `replace`), como `_save_safety_state`.
- **Opción**: `safety_backup_keep: int(0,50)`, 3 por defecto; variable `HERMES_SAFETY_BACKUP_KEEP`; `register_write(..., safety_backup_keep=3)` la pasa a `maybe_trigger_safety_backup(..., keep=...)`.
- **Razón**: la retención de HA solo poda sus propios backups automáticos (`with_automatic_settings`), y un backup creado directamente en el Supervisor no la lleva. Identificar por el nombre no basta: cualquiera puede crear un backup que se llame igual. La anotación propia es lo que hace la identificación inequívoca; el resto de condiciones cubren lo que un nombre no dice (que alguien lo copió a otra ubicación o lo protegió).
- **Alternativas**: filtrar solo por prefijo `hermes-safety-` (borraría backups ajenos con nombre parecido); podar en `sv_get_job_status` al ver el job terminado (una `get` que borra: principio V); una tarea periódica (más código, otro punto de fallo, sin ventaja).

### R-C4 Cifrado de los safety backups

- **Decisión**: fuera de alcance; se anota en la hoja de ruta (usar la contraseña de HA con `backup/generate` o `password` en `POST /backups/new/full`).

## Integración

### R-I1 Anotaciones

- **Decisión**: en `tools/_annotations.py`, añadir a `_DESTRUCTIVE_EXACT` `ha_update_floor`, `ha_update_label`, `ha_update_category`, `ha_ignore_repair`, `sv_dismiss_resolution_issue` y `sv_dismiss_resolution_suggestion`; añadir `ha_search_related` a `_READ_ONLY_EXACT`. Los prefijos ya clasifican el resto (`ha_list_`, `ha_get_`, `sv_get_` lectura; `ha_delete_` destructiva; `ha_create_` no idempotente y no destructiva).
- **Razón**: principio V y los invariantes de `tests/test_tools_registration.py`.

### R-I2 Recuento de tools

- **Decisión**: el README y DOCS dan el número que devuelve el registro real tras la integración (esta spec añade 23; otras specs de 1.1.0 añaden las suyas). Se calcula, no se suma a mano.

### R-I3 Versión

- **Decisión**: no se toca `version` ni `__version__`; el CHANGELOG añade las entradas bajo `## [1.1.0]` (creando el encabezado con la fecha de publicación pendiente si aún no existe) (spec S-15).

## Pendiente de verificar al implementar

| Qué | Cómo | Si no se cumple |
|---|---|---|
| La `reference` de un job de backup terminado es el slug del backup (spec S-10) | Leer `supervisor/backups/manager.py` del Supervisor 2026.11.0 | Solo queda la confirmación por nombre único y fecha |
| `GET /backups` trae `locations` (lista) además de `location` | Leer `supervisor/api/backups.py` | Se usa `location` y se exige que no sea una lista con más de un elemento |
| Home Assistant quita la etiqueta de las áreas al borrarla (spec S-05) | Leer `helpers/area_registry.py` (listener de `label_registry`) | La vista previa dice que esas áreas conservarán la referencia |
| Forma de `trace/get` en 2024.10.0 frente a 2026.11.1 | Comparar `trace/models.py` entre tags | El resumen omite lo que no reconozca y lo indica |
