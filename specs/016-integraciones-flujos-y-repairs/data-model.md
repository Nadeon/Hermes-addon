# Modelo de datos: integraciones, flujos y Repairs (016)

Formas de entrada y salida de las tools. Las firmas y anotaciones están en
[contracts/tools.md](contracts/tools.md). Todo texto que venga de HA pasa por
`redact_secrets`; toda estructura con claves, por `redact_structure` y después
`redact_secrets` en cada texto (el `_redactar` de `tools/repairs.py`).

## Módulos y familias

| Familia (`desde="1.2.0"`, desactivable) | Módulo | Tools |
|---|---|---|
| `integration_flows` | `integration_setup` | `ha_list_discovered_integrations`, `ha_ignore_discovery`, `ha_list_config_flow_domains`, `ha_update_config_entry` |
| `integration_flows` | `config_subentries` | `ha_list_config_subentries`, `ha_start_subentry_flow`, `ha_continue_subentry_flow`, `ha_abort_subentry_flow`, `ha_update_subentry`, `ha_delete_subentry`, `ha_start_reconfigure_flow`, `ha_continue_reconfigure_flow` |
| `repair_flows` | `repair_flows` | `ha_get_repair`, `ha_start_repair_fix`, `ha_continue_repair_fix`, `ha_abort_repair_fix` |
| (sin familia: no registra) | `_translations` | ayudante de CAP-036 |
| `diagnostics` (1.1.2, sin cambios de familia) | `repairs` | `ha_list_repairs`, `ha_ignore_repair` (ganan campos) |

Descripciones (en inglés, las ve el usuario en DOCS.md y en el log):

- `integration_flows`: "Discovered integrations, config entry preferences,
  config subentries and reconfigure flows."
- `repair_flows`: "Repairs fix flows: run the fix an integration offers for a
  Repairs issue."

## Descubrimiento (`ha_list_discovered_integrations`)

Entrada: `domain: str | None` (forma de dominio: `^[a-z0-9_]+$`, si no
`invalid_argument`).

```json
{"count": 2, "truncated": false, "items": [
  {"flow_id": "<flow_id>", "domain": "hue", "source": "zeroconf",
   "step_id": "confirm", "name": "Hue Bridge", "title_placeholders": {"name": "Hue Bridge"},
   "ignorable": true},
  {"flow_id": "<flow_id>", "domain": "banco_flujos", "source": "reauth",
   "step_id": "reauth_confirm", "name": null, "title_placeholders": null,
   "ignorable": false}
]}
```

- `name`: `title_placeholders.name` si existe; si no, `null`.
- Orden: por `domain` y después `flow_id` (estable).
- `ignorable`: `unique_id` presente en el contexto (el valor NO se devuelve).
- Respuesta que no es lista → `{"error": "unexpected_response"}`, nunca lista
  vacía.

## Ignorar (`ha_ignore_discovery`)

Entrada: `flow_id: str` (validado con `validate_identifier`), `title: str | None`
(si viene, no vacío y como mucho 255 caracteres).

Salida:

```json
{"result": "ok", "flow_id": "<flow_id>", "domain": "hue", "title": "Hue Bridge",
 "undo_hint": "HA created an ignored config entry (source 'ignore') for this device. To stop ignoring it, delete that entry with ha_delete_config_entry; HA will rediscover it."}
```

Errores: `not_found` (no está entre los descubiertos, antes o al llamar),
`cannot_ignore` (`reason: "no_unique_id"`, sin llamar), `invalid_argument`.

## Dominios configurables (`ha_list_config_flow_domains`)

Entrada: `type: str | None` ∈ {`device`, `helper`, `hub`, `service`}.

```json
{"count": 3, "truncated": false, "type": "helper",
 "items": ["derivative", "group", "template"]}
```

## Preferencias (`ha_update_config_entry`)

Entrada: `entry_id`, `title: str | None`, `pref_disable_polling: bool | None`,
`pref_disable_new_entities: bool | None`, `confirmation_token`.

Validación (sin llamar a HA): `entry_id` con `validate_identifier`; al menos uno
de los tres; `title` no vacío ni solo espacios y ≤ 255; booleanos de verdad.

Lectura previa: `config_entries/get_single` → `not_found`; si nada cambia →
`{"result": "unchanged"}`.

¿Token? Si `pref_disable_polling` pasa de `false` a `true` o
`pref_disable_new_entities` pasa de `false` a `true`. Vista previa:

```json
{"confirmation_token": "…", "expires_in_seconds": 60, "preview": {
  "entry_id": "<entry_id>", "domain": "banco_flujos", "state": "loaded",
  "title": {"current": "Banco", "new": "Banco"},
  "pref_disable_polling": {"current": false, "new": true},
  "pref_disable_new_entities": {"current": false, "new": false},
  "effects": [
    "Home Assistant reloads this integration now (it is loaded): its entities are unavailable for a moment.",
    "The integration stops polling: its entities only update when something calls homeassistant.update_entity, or by push if the integration supports it."
  ]}}
```

- Con la entrada no cargada, el primer efecto dice que no se recarga ahora.
- Efecto de entidades nuevas: "New devices and entities this integration adds
  from now on are created disabled. Existing ones do not change."
- El comando lleva solo los campos que cambian.

Salida (con o sin token): `{"result": "ok", "config_entry": {…campos de
ha_get_config_entry…}, "require_restart": bool, "reloaded": bool}`.
`reloaded` es verdadero si el sondeo cambió (en cualquier sentido) y la entrada
estaba `loaded`: es la regla de `config_entry_update` en HA 2026.11.1.

## Subentries

### `ha_list_config_subentries`

```json
{"entry_id": "<entry_id>", "domain": "banco_flujos",
 "supported_subentry_types": {"elemento": {"supports_reconfigure": true}},
 "count": 1, "truncated": false,
 "items": [{"subentry_id": "<subentry_id>", "subentry_type": "elemento",
            "title": "Elemento 1", "unique_id": null}]}
```

### `ha_start_subentry_flow` / `ha_continue_subentry_flow` / `ha_abort_subentry_flow`

- Entrada de start: `entry_id`, `subentry_type` (forma `^[a-z0-9_]+$`),
  `subentry_id: str | None`.
- Comprobaciones previas: entrada (`not_found`); tipo en
  `supported_subentry_types` (`subentry_type_not_supported` con `supported`);
  con `subentry_id`: existe (`not_found`), es de ese tipo
  (`invalid_argument`) y el tipo `supports_reconfigure`
  (`reconfigure_not_supported`).
- Cuerpo: `{"handler": [entry_id, subentry_type]}` y, si viene,
  `"subentry_id"`.
- Salida: el `FlowResult` de HA tal cual (como `ha_start_config_entry_flow`),
  con `status: "ok"` en `create_entry`; `external`/`progress` →
  `{"error": "non_automatable", "type", "flow_id", "hint"}` y `DELETE` del
  flujo. Abort: `{"result": "ok"}`.

### `ha_update_subentry`

Entrada: `entry_id`, `subentry_id`, `title` (no vacío, ≤ 255). Lectura previa
de la entrada y de la subentry (`not_found`); `unchanged` si es el mismo
título. Salida: `{"result": "ok", "subentry_id", "title"}`.

### `ha_delete_subentry`

Vista previa:

```json
{"confirmation_token": "…", "expires_in_seconds": 60, "preview": {
  "entry": {"entry_id": "<entry_id>", "domain": "banco_flujos", "title": "Banco"},
  "subentry": {"subentry_id": "<subentry_id>", "subentry_type": "elemento", "title": "Elemento 1"},
  "entities": {"count": 1, "items": [{"entity_id": "sensor.elemento_1", "name": "Elemento 1"}], "truncated": false},
  "devices": {"count": 0, "items": [], "truncated": false},
  "effect": "Deletes this subentry. Home Assistant also deletes the entities and devices listed here (devices that belong to this subentry, and their child devices). The integration may reload. Not reversible: to get it back, create the subentry again with its flow."}}
```

- Listas recortadas a 50 elementos cada una con `count` total; la vista previa
  completa cabe en `response_max_bytes`.
- Si la lectura de los registros falla: `preview_unavailable` sin token (sin
  la lista de lo que se borra, la vista previa mentiría por omisión).
- Salida: `{"result": "ok"}`; `not_found` si desapareció.

### `ha_start_reconfigure_flow`

Entrada: `entry_id`. Lectura previa de la entrada (`not_found`,
`reconfigure_not_supported` si `supports_reconfigure` es falso). Cuerpo:
`{"handler": <dominio>, "entry_id": <entry_id>}`. Salida como
`ha_start_config_entry_flow` (con los secretos del formulario tapados, ver
abajo), más `entry: {entry_id, domain, title}` y, si el flujo queda abierto,
`continue_with: "ha_continue_reconfigure_flow (two steps on every step:
preview, then confirmation_token)"`. Con `form` o `menu`, el `flow_id` entra
en el registro.

### Registro de reconfigures (decisión del supervisor, tramo B)

En memoria del proceso de Hermes (`tools/_reconfigure.py`), por `flow_id`:
`entry_id`, `domain`, `title` y el instante del último uso. Caduca a la hora
del último uso; los caducados se abortan en HA (`DELETE …/flow/{flow_id}`) al
abrir o continuar otro reconfigure, y salen del registro cuando el abort sale
o HA responde 404. Mientras están, `ha_continue_config_entry_flow` los
rechaza:

```json
{"error": "use_dedicated_tool", "tool": "ha_continue_reconfigure_flow",
 "flow_id": "<flow_id>",
 "detail": "This is a reconfigure flow opened by Hermes: every step needs a preview and a confirmation token."}
```

### `ha_continue_reconfigure_flow`

Entrada: `flow_id`, `user_input` (objeto), `confirmation_token`. `flow_id` que
no está en el registro → `{"error": "not_a_reconfigure_flow", "flow_id",
"hint"}` sin llamar a HA. Vista previa (lee `GET …/flow/{flow_id}`):

```json
{"confirmation_token": "…", "expires_in_seconds": 60, "preview": {
  "entry": {"entry_id": "<entry_id>", "domain": "banco_flujos", "title": "Banco"},
  "flow_id": "<flow_id>", "step_id": "reconfigure",
  "user_input": {"host": "192.0.2.10", "password": "***REDACTED***"},
  "secret_fields": ["password"],
  "unknown_fields": [],
  "effect": "Submits this step of the reconfigure flow of this config entry. When the flow finishes, the integration usually saves the new data (which may include credentials or connection details) and Home Assistant reloads it: its entities are unavailable for a moment, and wrong data can leave it failing to load. Home Assistant does not say in advance whether this step is the last one."}}
```

- Secretos tapados: por clave (`redact_structure`), por campo de contraseña
  del formulario (`selector.text.type == "password"`) y por patrón
  (`redact_secrets`). `secret_fields` nombra los tapados por el formulario o
  por la clave. `unknown_fields`: claves que el paso actual no pide (HA las
  rechazará).
- El token se ata a `flow_id`, `step_id` y `user_input` (sin omitibles: no
  se guarda en disco).
- `user_input` con `***REDACTED***` en algún valor → `invalid_argument` sin
  llamar a HA (también en `ha_continue_subentry_flow`): los formularios salen
  con los secretos sugeridos tapados, y reenviar el marcador lo guardaría
  como contraseña.
- Confirmación: vuelve a leer el paso; si el `step_id` cambió, el token no
  vale y no se envía nada. Un solo `POST`. Salida: el resultado de HA con
  `data_schema` y `description_placeholders` tapados (en un campo secreto,
  `default` y `description.suggested_value`); `abort` con
  `reconfigure_successful` o `create_entry` → `status: "ok"` y el flujo sale
  del registro; otro `abort` → sale del registro, sin `status`; `form`/`menu`
  → `continue_with` (otra vista previa). HTTP 400 con `errors` → error
  redactado y token completado con fallo.
- 404 en la lectura o en el `POST` → `not_found` y sale del registro.

## Repairs

### Aviso con texto (`ha_list_repairs`, `ha_get_repair`)

Cada aviso de `ha_list_repairs` gana dos campos (los de la 1.1.2 siguen):

```json
{"domain": "banco_flujos", "issue_id": "aviso_reparable", "…": "…",
 "title": "Banco: something to fix",
 "description": "The value {value} must be confirmed. …",
 "description_truncated": false}
```

- Raíz de `ha_list_repairs`: `{"count", "issues"}` como en la 1.1.2, más
  `"language": "es"`, `"translations_unavailable": false` y
  `"_third_party_text": …` (los textos de traducción los escribe cada
  integración).
- Descripción en listas: recortada a 1000 caracteres.

`ha_get_repair(domain, issue_id)`:

```json
{"issue": {…resumen de ha_list_repairs, con title y description enteros…},
 "issue_data": {…redactado…}, "issue_data_truncated": false,
 "language": "es", "translations_unavailable": false,
 "_third_party_text": …}
```

- `issue_data` que no cabe: se sustituye por `{"keys": [...], "size_bytes": n}`
  con `issue_data_truncated: true` (nunca un JSON cortado).
- Busca el aviso en `repairs/list_issues` (también ignorados); `not_found` si
  no está.

### `ha_start_repair_fix`

Comprobaciones: aviso existe (`not_found`), `is_fixable` (`not_fixable`), sin
llamar al POST. Salida:

```json
{"flow_id": "<flow_id>", "type": "form", "step_id": "confirm",
 "data_schema": [], "errors": null, "description_placeholders": null,
 "issue": {"domain": "banco_flujos", "issue_id": "aviso_reparable", "title": "…"},
 "step_text": {"title": "…", "description": "…", "source": "fix_flow"},
 "finished_on_start": false,
 "continue_with": "ha_continue_repair_fix (two steps: preview, then confirmation_token)"}
```

- `step_text.source`: `fix_flow` (texto del paso) o `issue` (no hay texto del
  paso; se usa el del aviso, como hace la interfaz en la confirmación).
- Si termina al abrirse: `finished_on_start: true`, `type` y, en
  `create_entry`, `issue_still_present`; en `abort`, `reason` y
  `reason_text` si hay traducción.

### `ha_continue_repair_fix`

Entrada: `domain`, `issue_id`, `flow_id`, `user_input: dict | None` (por
defecto `{}`), `confirmation_token`. Vista previa:

```json
{"confirmation_token": "…", "expires_in_seconds": 60, "preview": {
  "issue": {"domain": "banco_flujos", "issue_id": "aviso_reparable", "title": "…", "severity": "warning"},
  "flow_id": "<flow_id>", "step_id": "confirm",
  "step_text": {"title": "…", "description": "…", "source": "fix_flow"},
  "user_input": {"password": "**REDACTED**"},
  "effect": "Submits this step of the fix flow offered by the integration. It may apply the fix now: Home Assistant does not say in advance whether this is the last step. When the flow finishes, Home Assistant removes the issue (it comes back if the cause remains).",
  "note": "Home Assistant's flow API does not say which issue a flow belongs to; the issue shown is the one given in this call. The flow is checked to belong to the same integration."}}
```

- El token se ata a `domain`, `issue_id`, `flow_id` y `user_input`. No se
  guarda `user_input` en el fichero del token (sin omitibles).
- Confirmación: un solo `POST /repairs/issues/fix/{flow_id}`; salida =
  resultado de HA con `status: "ok"` en `create_entry` e
  `issue_still_present` (`true`, `false` o `null` con `issue_check_error`); en
  `form`/`menu`, el paso siguiente con su `step_text` y la indicación de que
  hace falta otra vista previa.

### `ha_abort_repair_fix`

Entrada: `flow_id`. Salida `{"result": "ok"}` o `not_found`.

## Errores comunes

| Código | Cuándo |
|---|---|
| `invalid_argument` (`field`, `detail`) | forma o valor inválido; nada pedido |
| `not_found` | entrada, subentry, flujo, descubrimiento o aviso inexistente |
| `unchanged` (como `result`) | el cambio no cambia nada |
| `cannot_ignore` (`reason`) | descubrimiento sin `unique_id` |
| `subentry_type_not_supported` (`supported`) | tipo no admitido por la entrada |
| `reconfigure_not_supported` | entrada o tipo de subentry sin reconfigure |
| `not_a_reconfigure_flow` | `ha_continue_reconfigure_flow` con un `flow_id` que Hermes no abrió como reconfigure |
| `use_dedicated_tool` (`tool`) | `ha_continue_config_entry_flow` con un reconfigure registrado |
| `not_fixable` | aviso no reparable |
| `flow_mismatch` (`flow_domain`) | el flujo es de otro dominio |
| `non_automatable` (`type`, `flow_id`, `hint`) | paso externo o de progreso; flujo abortado |
| `preview_unavailable` (`detail`) | falla una lectura previa a una vista previa |
| `unexpected_response` | forma de respuesta inesperada |
| errores de token de siempre | caducado, usado, de otros argumentos |

Cualquier `detail` que venga de HA pasa por `redact_secrets`.

## Entradas de la tabla (FR-018)

| Comando | Categoría | Familia | Tool | CAP |
|---|---|---|---|---|
| `config_entries/flow/progress` | `dedicated` | `integration_flows` | `ha_list_discovered_integrations` | CAP-044 |
| `config_entries/ignore_flow` | `dedicated` | `integration_flows` | `ha_ignore_discovery` | CAP-044 |
| `config_entries/update` | `dedicated` | `integration_flows` | `ha_update_config_entry` | CAP-044 |
| `config_entries/subentries/list` | `dedicated` | `integration_flows` | `ha_list_config_subentries` | CAP-045 |
| `config_entries/subentries/update` | `dedicated` | `integration_flows` | `ha_update_subentry` | CAP-045 |
| `config_entries/subentries/delete` | `dedicated` | `integration_flows` | `ha_delete_subentry` | CAP-045 |
| `repairs/get_issue_data` | `dedicated` | `repair_flows` | `ha_get_repair` | CAP-048 |
| `frontend/get_translations` | `deny` (sin cambio) | `generic_commands` | — | (comentario CAP-036) |

Motivo de las `dedicated`: «cubierto por <tool>», como el resto de la tabla.

## Log de Hermes

Eventos `<tool>_ok`, `<tool>_ws_error`, `<tool>_rest_error`,
`<tool>_token_invalid`, `<tool>_non_automatable`, `<tool>_preview_read_failed`,
con `entry_id`, `subentry_id`, `flow_id`, `domain`, `issue_id`,
`subentry_type`, `flow_type`, recuentos y nombres de los campos cambiados.
Nunca `user_input`, títulos, `title_placeholders`, datos internos, textos
traducidos ni el contenido de los errores de HA sin redactar.
