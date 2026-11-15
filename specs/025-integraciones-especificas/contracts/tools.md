# Contratos: integraciones específicas por la tabla (025)

Sin tools nuevas. Lo que cambia para el cliente MCP es lo que ejecutan las
genéricas de Core y lo que dice la guía.

## `ha_read_ws_command(type, payload)` — sin cambios de firma ni anotaciones

Ejecuta, además de lo de hoy, las 73 entradas `read` de research.md R-1.

- Respuesta: la de la 011 (`{"command", "category", "result"}` o el sobre de lista),
  con la redacción de la 011 más la de valor entero de `redact_extra`.
- Las cinco `one_shot` (R-2) devuelven el primer evento de la suscripción y la
  cancelan siempre; si no llega en 10 s, error de plazo (011).
- Anotaciones: `readOnlyHint: true`, `openWorldHint: true` (ya lo era por
  `media_source/*`; ahora también por `zwave_js/check_for_config_updates`).

Ejemplo:

```json
// ha_read_ws_command("zha/network/settings", {})
{
  "command": "zha/network/settings",
  "category": "read",
  "result": {
    "radio_type": "ezsp",
    "device": {"path": "/dev/ttyUSB0"},
    "settings": {
      "network_info": {
        "channel": 15,
        "pan_id": "1A2B",
        "network_key": "***REDACTED***",
        "tc_link_key": "***REDACTED***",
        "key_table": "***REDACTED***",
        "stack_specific": "***REDACTED***"
      },
      "node_info": {"ieee": "00:11:22:33:44:55:66:77"}
    }
  }
}
```

## `ha_call_ws_command(type, payload, confirmation_token=None)` — sin cambios de firma ni anotaciones

Ejecuta, además de lo de hoy, las 57 entradas `confirm` de R-1, siempre en dos
pasos con la vista previa de la 011 (comando, categoría, motivo, CAP y
resumen de la carga). `openWorldHint: true` (ya lo era).

## Rechazos

Las 62 entradas `deny` de R-1 responden `command_denied` con su `reason`, por
cualquiera de las dos genéricas, sin llamar a HA (011). Un comando de clase C
pedido por la genérica equivocada responde `wrong_generic_tool` (011).

## Redacción de valor entero (FR-008)

Para una entrada con `redact_extra=("k",)`:

| Respuesta de HA | Respuesta de Hermes |
|---|---|
| `{"k": "abc"}` | `{"k": "***REDACTED***"}` (como hoy) |
| `{"k": 1234}` | `{"k": "***REDACTED***"}` (como hoy) |
| `{"k": {"key": "abc", "n": 1}}` | `{"k": "***REDACTED***"}` (antes: `{"k": {"key": "abc", "n": 1}}`) |
| `{"k": [{"key": "abc"}]}` | `{"k": "***REDACTED***"}` (antes: la lista en claro) |
| `{"k": null}` | `{"k": null}` (como hoy) |
| `{"k": ""}` | `{"k": ""}` (como hoy: la cadena vacía no revela nada) |

## `hermes_guide(topic)`

Temas nuevos `zwave`, `zigbee`, `matter_thread`, `other_integrations` y sus
alias (data-model.md). Los temas existentes devuelven exactamente el mismo
texto. `hermes_guide("generic_commands", search="zwave_js")` lista las 50
primeras de las 55 entradas de Z-Wave con su categoría, motivo y ejemplo
(tope de filas de la 011).
