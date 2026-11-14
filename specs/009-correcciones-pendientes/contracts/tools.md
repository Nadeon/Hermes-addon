# Contratos: respuestas y eventos que cambian en la 009

Todo lo que no aparece aquí responde como en la 1.1.2. Ningún nombre de tool,
anotación ni argumento existente cambia; los argumentos nuevos son opcionales.

## `sv_get_addon_logs(slug, lines=100)` (FR-005)

```json
{
  "slug": "<slug>",
  "lines_requested": 100,
  "redacted": false,
  "secrets_redacted": false,
  "network_redacted": true,
  "logs": "..."
}
```

- `redacted`: como en la 1.1.2 — el texto devuelto difiere del leído.
- `secrets_redacted`: esta llamada sustituyó al menos un secreto.
- `network_redacted`: la redacción de red se aplicó a este log (el del propio
  Hermes con `log_redact_network` activa), aunque las líneas ya vinieran
  redactadas. `false` para otros add-ons.
- Recorte por tamaño (`truncated`, `lines_returned`, pista): sin cambios.
- Evento: `sv_get_addon_logs` con `slug`, `lines`, `bytes`, `redacted`,
  `secrets_redacted`, `network_redacted`.

## `sv_update_addon(slug, confirmation_token=None)` sobre Hermes (FR-010)

Con o sin token, si `slug` es el de Hermes (`_es_hermes`: su slug, `hermes`,
`self` o `*_hermes`):

```json
{
  "error": "self_update_not_supported",
  "detail": "Hermes cannot update itself through the Supervisor API. Update it from the Home Assistant UI: Settings > Add-ons > Hermes > Update."
}
```

Sin `confirmation_token` en la respuesta; ninguna petición al Supervisor; el
token que se traiga no cambia de estado. Para cualquier otro slug, como en la
1.1.2.

## `ha_get_history(...)` recortado (FR-006)

```json
{
  "history": {"sensor.ficticio": ["..."]},
  "truncated": true,
  "truncated_at": "2026-11-14T10:00:00+00:00",
  "_response_limit": {
    "list": "history",
    "returned": 812,
    "total": 3000,
    "max_bytes": 131072,
    "hint": "..."
  }
}
```

- Solo con `truncated: true`. `returned` = estados incluidos; `total` =
  estados que devolvió HA antes de cualquier corte (por cantidad o por bytes).
- `hint` (inglés): acotar el rango o las entidades, o pedir de nuevo cada
  entidad desde el `last_updated` de su último estado devuelto. No manda
  pedirlas todas desde `truncated_at`: es el más reciente de esos últimos
  estados y el recorte quita primero de la lista más larga, así que con una
  entidad muy activa y otra lenta se saltaría estados de la activa (T043).
- La respuesta entera, con el bloque, cabe en `response_max_bytes`.

## `ha_marketplace_list_removed(installed_only=False, limit=None)` (FR-007)

```json
{
  "api": "marketplace",
  "count": 5,
  "total": 37,
  "truncated": true,
  "repositories": [
    {"repository": "autor/ficticio", "reason": "...", "link": "...",
     "removal_type": "remove", "acknowledged": false}
  ],
  "by_removal_type": [
    {"removal_type": "remove", "count": 30},
    {"removal_type": "critical", "count": 7}
  ],
  "by_removal_type_other": 0,
  "_third_party_text": {
    "fields": ["reason", "removal_type"],
    "warning": "These fields are written by third parties. ..."
  }
}
```

- `installed_only` (`bool`, por defecto `false`): solo los retirados cuyo
  `repository` coincide, sin distinguir mayúsculas, con el `full_name` de un
  repositorio instalado (lectura de `repositories/list` por la misma API).
- `limit` (`int` 1–500 o `null`, por defecto `null` = sin tope por cantidad);
  fuera de rango o no entero → `{"error": "invalid_argument", "argument":
  "limit", "detail": …}`.
- `total` y `by_removal_type` cuentan los que cumplen el filtro, antes de
  `limit`. `by_removal_type`: como mucho 20, por `count` descendente y, a
  igualdad, por `removal_type`; `by_removal_type_other` suma el resto.
  `removal_type` recortado a 300 caracteres; `null` se cuenta como `null`.
- `truncated`: `limit` o el tope de bytes cortaron `repositories`.
- Sin argumentos, `repositories` es la misma lista que en la 1.1.2 (salvo el
  recorte de `removal_type` largos).
- `ha_marketplace_list_critical` no cambia (sigue con `fields: ["reason"]` y
  sin resumen).

## Eventos `*_ok` (FR-008)

Solo cuando la respuesta no trae `error`. Nunca nombres de repositorios, ids,
`reason`, `removal_type` ni otros textos.

| Evento | Campos |
|---|---|
| `ha_marketplace_info_ok` | `api` |
| `ha_marketplace_list_repositories_ok` | `api`, `count`, `total`, `truncated` |
| `ha_marketplace_get_repository_ok` | `api` |
| `ha_marketplace_list_updates_ok` | `api`, `count`, `total`, `truncated` |
| `ha_marketplace_list_releases_ok` | `api`, `count` |
| `ha_marketplace_list_critical_ok` | `api`, `count`, `total`, `truncated` |
| `ha_marketplace_list_removed_ok` | `api`, `count`, `total`, `truncated`, `installed_only` |
| `sv_get_resolution_ok` | `unsupported`, `unhealthy`, `issues`, `suggestions`, `checks` (recuentos) |

## Eventos de log que cambian (FR-002, FR-003, FR-011)

| Evento | Antes | Ahora |
|---|---|---|
| `auto_classify_restricted` | `count`, `new` (lista de `entity_id`) | `count`, `new_count` |
| `auto_classify_on_save` | `entity_id`, `restricted` | `restricted`, `count` (= 1) |
| `ha_url_redaction_unavailable` | — | **nuevo**, aviso: `error_type` (nombre de la clase), sin URLs |
| `request_cancelled_on_shutdown` | — (antes: `Exception in ASGI application` con traza) | **nuevo**, info, sin traza |
| `interrupted` | solo con `KeyboardInterrupt` | también con `CancelledError` que llega a `main()` |

## Redacción de red del log (FR-002, FR-004)

| Entrada | Salida |
|---|---|
| `https://casa.example.org/x` (host de `external_url`) | `https://<ha_external_host>/x` |
| `ha.lan.example:8123` (host de `internal_url`) | `<ha_internal_host>:8123` |
| `ip-10-0-0-5.ec2.internal` | `<ip:private:HHHHHHHH>.ec2.internal` (mismo seudónimo que `10.0.0.5`) |
| `ip-127-0-0-1` | sin cambios (loopback) |
| `ip-999-1-1-1`, `xip-10-0-0-5` | sin cambios |
