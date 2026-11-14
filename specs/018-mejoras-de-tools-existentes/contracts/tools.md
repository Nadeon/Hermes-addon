# Contratos: mejoras de tools existentes (018)

Solo cambian dos tools de la 1.1.2, y solo con argumentos opcionales. Sin
ellos, su esquema de entrada, su respuesta y su comportamiento son los de la
1.1.2 (FR-020 de la 008). Anotaciones sin cambios: las dos siguen `-DI-`
(`destructiveHint`, `idempotentHint`). Ninguna tool nueva, ninguna familia
nueva, ninguna entrada de la tabla de comandos cambia.

## `ha_save_lovelace_dashboard`

```text
ha_save_lovelace_dashboard(
    url_path: str | None,                     # sin cambios (obligatorio)
    config: dict | None = None,               # sin cambios
    confirmation_token: str | None = None,    # sin cambios
    remove_top_level_keys: list[str] | None = None,  # sin cambios
    view_index: int | None = None,            # NUEVO
    view: dict | None = None,                 # NUEVO
)
```

### Modo completo (sin `view_index` ni `view`)

Idéntico a la 1.1.2 (incluidos los textos, los errores y las pistas de
confirmación).

### Modo por vista (`view_index` y `view`)

| Paso | Entrada | Salida |
|---|---|---|
| Vista previa | `url_path`, `view_index`, `view` | `{confirmation_token, expires_in_seconds, preview, confirm_with: ["confirmation_token", "url_path", "view_index"], omit_on_confirm: ["view"], confirm_hint}`; `preview` según [data-model](../data-model.md#vista-previa-por-vista) |
| Confirmación | `url_path`, `view_index`, `confirmation_token` (y `view` idéntico, opcional) | `{"result": "ok", "url_path": …, "view_index": n}` |

Si la vista no se pudo guardar junto al token (tope lleno), `confirm_with`
incluye `view` y la pista dice que hay que reenviarla, como en la 1.1.2.

### Errores nuevos o reutilizados en modo por vista (sin token, sin escribir)

| Código | Cuándo |
|---|---|
| `invalid_argument` (`field`: `view_index`, `view`, `config` o `remove_top_level_keys`) | Mezcla con `config` o `remove_top_level_keys`; `view` sin `view_index` o al revés en la vista previa; `view` no es objeto o trae `views`; `view_index` no es entero |
| `view_index_out_of_range` (`views_count`, `requested`) | Índice negativo o `>= len(views)` |
| `no_views` | El dashboard no tiene configuración guardada o no tiene lista `views` (estrategia) |
| `yaml_mode` | Dashboard en modo YAML (como hoy) |
| `preview_unavailable` | No se pudo leer el dashboard actual en la vista previa |
| `dashboard_changed` (`detail`) | Al confirmar, el dashboard no es el que se leyó en la vista previa. No se guarda nada; pedir otra vista previa |

Al confirmar, un fallo de lectura de `lovelace/config` devuelve el error de
conexión y deja el token pendiente.

## `ha_call_service_response`

```text
ha_call_service_response(
    domain: str,                              # sin cambios
    service: str,                             # sin cambios
    service_data: dict | None = None,         # sin cambios
    confirmation_token: str | None = None,    # NUEVO
)
```

| Caso | Sin token | Con token válido |
|---|---|---|
| Fuera de denylist y sin entidad restringida | Ejecuta y devuelve la respuesta (1.1.2) | Igual (el token se ignora) |
| Denylist | `{error: "service_in_denylist", hint, confirmation_token, expires_in_seconds, preview}`; no ejecuta | Ejecuta una vez y devuelve la respuesta de HA |
| Entidad restringida | `{error: "entity_restricted", hint, confirmation_token, expires_in_seconds, preview}`; no ejecuta | Ejecuta una vez y devuelve la respuesta de HA |
| `service_data` inseguro | `unsafe_service_data` (1.1.2), sin token | Igual |
| Token inválido, caducado, usado, de otra tool o de otros argumentos | — | `{"error": <mensaje de siempre>}`; no ejecuta |
| Fallo de HA al ejecutar | — | `{"error": "ha_call_service_response_failed", "details": …}` (1.1.2); token `failed` |

`preview`: `{action: "call_service_response", domain, service, service_data,
reason, restricted_entities?}` (los mismos campos que `ha_call_service`).

## Sobre de lista (tools nuevas de la 1.2.0)

```text
sobre_de_lista(items: list, *, truncated: bool = False, **cabecera) -> dict
# → {**cabecera, "count": len(items), "items": items, "truncated": truncated}
```

Contrato para el cliente (guía, índice): toda tool de lista nueva de la 1.2.0
devuelve `count`, `items` y `truncated`; si `truncated` es `true`, la lista se
cortó por el final (y, si la cortó el tope central, `_response_limit` dice
cuántos había). Las tools anteriores conservan su forma.

Contrato para las sub-features: toda tool nueva `ha_list_*` o `sv_list_*`
llama a `sobre_de_lista` en su función, o figura en `EXCEPCIONES_SOBRE` de
`tests/test_sobre_de_lista.py` con su motivo.
