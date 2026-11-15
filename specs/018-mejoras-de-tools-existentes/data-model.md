# Modelo de datos: mejoras de tools existentes (018)

No hay almacenamiento nuevo: todo vive en los ficheros de token de
`/data/pending_confirmations` que ya existen (spec 007) y en la memoria de cada
llamada.

## Guardado por vista (`ha_save_lovelace_dashboard` con `view_index`)

| Campo | Tipo | Origen | Regla |
|---|---|---|---|
| `url_path` | `str \| None` | cliente | Igual que hoy; obligatorio en las dos llamadas |
| `view_index` | `int` | cliente | `0 <= view_index < len(views)`; obligatorio en las dos llamadas; `bool` no vale como entero |
| `view` | `dict` | cliente | Obligatorio en la vista previa; omitible al confirmar (guardado junto al token); sin clave `views` |
| `config` | — | — | Prohibido junto a `view_index` |
| `remove_top_level_keys` | — | — | Prohibido junto a `view_index` |
| estado | `dict` | servidor | El documento de `lovelace/config` leído en cada paso; nunca lo manda el cliente |

**Documento resultante**: `{**actual, "views": actual["views"][:i] + [view] + actual["views"][i+1:]}`;
el resto de claves, sin tocar. Se valida con `_validate_dashboard_config` antes
de guardarlo.

**Argumentos atados por el `action_hash`**: `{"url_path", "view_index", "view"}`
(tool `ha_save_lovelace_dashboard`). Un token de guardado completo
(`{"url_path", "config", …}`) y uno por vista nunca casan entre sí.

**Omitibles**: `("view",)` en el modo por vista (constante nueva
`_OMITIBLES_VISTA`); el modo completo sigue con `("config",)`. No pueden ser
una sola tupla `("config", "view")`: `resolve_confirmation_token` rechaza la
confirmación si falta un omitible que no se guardó, así que una confirmación
completa de la 1.1.2 (sin `view`) se rechazaría («has no stored value for:
view»).

### Transiciones

```text
vista previa ──(lee actual; valida)──► token pendiente {action_hash, state_hash, stored_args.view}
   │ error de validación / lectura ──► respuesta de error, sin token
confirmación ──(lee actual)──► resolve(token, args, omitibles, estado=actual)
   ├─ estado distinto ─────────► dashboard_changed (token sigue pendiente; nada guardado)
   ├─ argumentos distintos ────► «does not match» (token sigue pendiente)
   └─ ok ──► executing ──► lovelace/config/save(documento resultante)
                 ├─ ok ──► completed {result: ok, url_path, view_index}
                 └─ fallo ──► failed (error de HA)
```

## Vista previa por vista

```json
{
  "url_path": "panel-prueba",
  "mode": "single_view",
  "view_index": 1,
  "views_total": 3,
  "view_before": {"title": "Cocina", "path": "cocina", "type": null, "cards": 7, "badges": 0, "sections": 0},
  "view_after":  {"title": "Cocina", "path": "cocina", "type": null, "cards": 8, "badges": 0, "sections": 0},
  "view_unchanged": false,
  "views_kept": [{"index": 0, "title": "Inicio", "path": null}, {"index": 2, "title": "Jardín", "path": "jardin"}],
  "top_level_keys_kept": ["title"],
  "diff": {"views_count_before": 3, "views_count_after": 3, "total_cards_badges_before": 20, "total_cards_badges_after": 21, "theme_changed": false, "title_changed": false, "has_strategy": false},
  "warning": "Only view 1 is replaced. The other 2 views and the top-level keys are kept exactly as they are now; if anything in the dashboard changes before you confirm, the confirmation is refused."
}
```

- `cards` cuenta las tarjetas de la vista y las de sus secciones (como
  `_count_cards`, pero separadas de `badges` y `sections`).
- `title`, `path` y `type` son `null` si la vista no los tiene; si son textos
  largos se recortan a 80 caracteres (son de la configuración del usuario;
  van a la vista previa porque identifican la vista).
- `views_kept` tiene una entrada por vista conservada; con muchas vistas el
  tope central resume la vista previa sin perder el token (spec 006).

## Estado ligado al token (`security.py`)

| Campo del fichero del token | Tipo | Regla |
|---|---|---|
| `state_hash` | `str` (64 hex) | Solo si `create_confirmation_token(..., estado=…)`; huella con la canonicalización de `compute_action_hash` |

`resolve_confirmation_token(..., estado=None)`:

| Token con `state_hash` | `estado` al resolver | Resultado |
|---|---|---|
| no | `None` | Igual que la 1.1.2 |
| sí | igual | Sigue con la comprobación del `action_hash` |
| sí | distinto o `None` | `(False, ESTADO_CAMBIADO, {})`, estado del token sin tocar |
| no | no `None` | `(False, ESTADO_CAMBIADO, {})` (fail-closed: el token no se emitió atado) |

La comprobación del estado va antes que la del `action_hash` y que el paso a
`executing`, en el mismo tramo sin `await`.

## Confirmación de `ha_call_service_response`

| Campo | Regla |
|---|---|
| tool del token | `ha_call_service_response` |
| `args` atados | `{"domain": dominio_normalizado, "service": servicio_normalizado, "service_data": datos}` |
| omitibles | ninguno |
| `cached_result` | `{"called": true}` (nunca la respuesta) |

Respuesta sin token (denylist):

```json
{
  "error": "service_in_denylist",
  "hint": "'conversation.process' is in the service denylist. Repeat this same call with confirmation_token to run it and get its response.",
  "confirmation_token": "…",
  "expires_in_seconds": 60,
  "preview": {
    "action": "call_service_response",
    "domain": "conversation",
    "service": "process",
    "service_data": {"text": "turn on the kitchen light"},
    "reason": "Service 'conversation.process' requires confirmation (denylist match)."
  }
}
```

Con entidad restringida: `error: "entity_restricted"`, `reason` con
`auto-restricted entity` y `preview.restricted_entities` como en
`ha_call_service`.

## Sobre de lista

```json
{"<cabecera>": "…", "count": 2, "items": [{}, {}], "truncated": false}
```

- `count == len(items)` siempre; `truncated: true` solo si la tool recortó o
  lo recortó el tope central (que además añade `_response_limit` y pone al día
  `count`).
- La cabecera son los campos propios de cada tool (por ejemplo `command` y
  `category` en las genéricas); no puede llamarse `count`, `items` ni
  `truncated`.
