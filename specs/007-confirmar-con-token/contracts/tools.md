# Contratos: confirmar solo con el token (1.1.2)

Solo se listan los cambios. Lo que no aparece, no cambia. Las descripciones
que ve el cliente están en inglés (principio X).

## Firmas (esquema de entrada MCP)

El documento deja de estar en `required`; el destino sigue en él.

```text
ha_save_lovelace_dashboard(url_path: str | None, config: dict | None = None,
                           confirmation_token: str | None = None,
                           remove_top_level_keys: list[str] | None = None)
fs_write_file(path: str, content: str | None = None,
              confirmation_token: str | None = None)
ha_create_or_update_automation(automation_id: str, config: dict | None = None,
                               confirmation_token: str | None = None)
ha_create_or_update_script(script_id: str, config: dict | None = None,
                           confirmation_token: str | None = None)
ha_create_or_update_scene(scene_id: str, config: dict | None = None,
                          confirmation_token: str | None = None)
```

## Vista previa (sin token, con documento)

Campos de siempre más tres nuevos en el primer nivel. Ejemplo de
`ha_save_lovelace_dashboard` con un dashboard ficticio:

```json
{
  "confirmation_token": "…",
  "expires_in_seconds": 60,
  "preview": {"url_path": "panel-ficticio", "diff": {"…": "…"}, "warning": "…"},
  "confirm_with": ["confirmation_token", "url_path"],
  "omit_on_confirm": ["config"],
  "confirm_hint": "To confirm, call ha_save_lovelace_dashboard again with only confirmation_token, url_path. config can be omitted: the server kept the one from this preview. Any argument you do send must be identical to the preview."
}
```

- `confirm_with`: lista ordenada; argumentos de la vista previa que no se han
  guardado, más `confirmation_token`. Incluye `remove_top_level_keys` si se
  usó.
- `omit_on_confirm`: lista ordenada de los omitibles guardados.
- Con el tope lleno (sin documento guardado): sin `omit_on_confirm`;
  `confirm_with` con todos los argumentos y el token; `confirm_hint`: «Repeat
  the same call with all the same arguments plus confirmation_token: the
  server could not keep config this time.»
- El guardián de `response_max_bytes` nunca resume ni quita estos tres campos.
- `fs_write_file` devuelve lo mismo serializado en texto, como hoy.

## Confirmación (con token)

| Llamada | Resultado |
|---|---|
| Destino + token, sin documento | Ejecuta con el documento guardado. |
| Destino + token + documento idéntico | Ejecuta (compatibilidad con 1.1.1). |
| Documento distinto | `{"error": "confirmation_token does not match this action."}`; el token no se gasta. |
| Otro destino (con o sin documento) | Igual que la fila anterior. |
| Argumento que no estaba en la vista previa | Igual que la fila anterior. |
| Token de otra tool | Igual que la fila anterior. |
| Sin documento y el token no lo guardó | `{"error": "confirmation_token has no stored value for: config. Repeat the call with all its arguments."}`; el token no se gasta. |
| Token caducado / perdido / usado | Mensajes de hoy, sin cambios. |

## Sin token y sin documento

```json
{"error": "invalid_argument", "field": "config",
 "detail": "config is required to request a preview; it can only be omitted when confirming with confirmation_token."}
```

(`field: "content"` en `fs_write_file`.) No se emite token. En
`ha_create_or_update_scene` vale igual para la escena nueva, que se crea sin
token.

## Descripciones

Las cinco tools añaden a su docstring una línea como: «When confirming, you
may omit `config`: the server kept the one from the preview (see
`confirm_with` in the preview response).» Las anotaciones no cambian.

## Guía (`hermes/src/hermes/tools/guide.py`)

- `INSTRUCTIONS`, punto 1: deja de decir «Repite la MISMA llamada con los
  MISMOS argumentos»; dice que se repite la llamada con `confirmation_token`,
  que si la respuesta trae `omit_on_confirm` basta con lo de `confirm_with`, y
  que lo que se reenvíe tiene que ser idéntico.
- Temas `security`, `files` (ejemplo de `fs_write_file`) y `workflows`: lo
  mismo, en una frase.

## Log

| Evento | Campos | Cuándo |
|---|---|---|
| `confirmation_args_not_stored` (nuevo, `warning`) | `tool`, `reason` (`storage_cap`), `keys`, `bytes` | El documento no cabe en el tope. |
| `confirmations_cleaned` | sin cambios | Limpieza periódica (cada 60 s), solo si ha limpiado algo (> 0). |

Ningún evento lleva el documento.
