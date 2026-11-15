# Contratos: tools de diagnóstico de Core (012)

Las formas de respuesta están en [data-model.md](../data-model.md). Aquí:
firmas, anotaciones, errores, guía y lo que pasa a la tabla.

## Firmas (esquema de entrada MCP)

| Tool | Argumentos | Modifica | Token |
|---|---|---|---|
| `ha_list_system_log` | `level: str \| None = None`, `integration: str \| None = None`, `include_tracebacks: bool = False` | no | no |
| `ha_get_error_log` | `lines: int = 100` | no | no |
| `ha_get_log_levels` | `domain: str \| None = None` | no | no |
| `ha_set_log_level` | `level: str`, `integration: str \| None = None`, `module: str \| None = None`, `persistence: str = "none"`, `confirmation_token: str \| None = None` | sí | sí |
| `ha_clear_system_log` | `confirmation_token: str \| None = None` | sí | sí |
| `ha_validate_config` | `config: dict \| None = None`, `triggers: Any = None`, `conditions: Any = None`, `actions: Any = None` | no | no |
| `ha_test_condition` | `condition: dict`, `variables: dict \| None = None` | no | no |
| `ha_list_diagnostics_handlers` | `domain: str \| None = None` | no | no |
| `ha_get_config_entry_diagnostics` | `entry_id: str`, `keys: list[str] \| None = None`, `include_system_info: bool = False` | no | no |
| `ha_get_device_diagnostics` | `device_id: str`, `keys: list[str] \| None = None`, `include_system_info: bool = False` | no | no |
| `ha_list_persistent_notifications` | — | no | no |
| `ha_dismiss_persistent_notification` | `notification_id: str`, `confirmation_token: str \| None = None` | sí | sí |

Todas con `@ready` (`requires_ready`). Docstrings en inglés que dicen lo que
hacen y lo que no (p. ej. que la limpieza no toca el fichero ni el journal, que
la validación no guarda, que el diagnóstico de dispositivo elige la
integración dueña).

## Anotaciones (`tools/_annotations.py`)

| Tool | readOnly | destructive | idempotent | openWorld | Dónde |
|---|---|---|---|---|---|
| `ha_list_*`, `ha_get_*` (7) | sí | no | sí | no | prefijo (ya cubierto) |
| `ha_validate_config`, `ha_test_condition` | sí | no | sí | no | `_READ_ONLY_EXACT`, con comentario |
| `ha_set_log_level` | no | sí | sí | no | `_DESTRUCTIVE_EXACT`, con comentario |
| `ha_clear_system_log` | no | sí | sí | no | `_DESTRUCTIVE_EXACT` |
| `ha_dismiss_persistent_notification` | no | sí | sí | no | `_DESTRUCTIVE_EXACT` |

Comentario de las tres destructivas: piden token y ocultan rastro (bajar un
nivel o vaciar un log esconde lo que pasó; descartar una notificación borra un
aviso que no se recupera): es la misma razón por la que sus acciones están en
la denylist. El invariante «pide token ⇔ destructiva» de
`tests/test_tools_registration.py` las cubre.

## Errores

| Código | Cuándo | Llama a HA |
|---|---|---|
| `invalid_argument` (`field`, `detail`) | argumento con forma o valor inválido; combinación imposible | no |
| `not_found` | entrada, dispositivo, notificación o integración (al confirmar el nivel) que no existe | lectura previa sí; acción no |
| `diagnostics_not_supported` (`domain`, `kind`, `reason`) | sin handler del tipo, o dispositivo sin dueña única | lectura previa sí; descarga no |
| `diagnostics_unavailable` / `system_log_unavailable` (`ha_code`) | HA no tiene el comando (`unknown_command`) | sí |
| `error_log_unavailable` (`detail`, `hint`) | `/api/error_log` da 404 | sí |
| `invalid_condition` / `condition_error` (`detail` redactado) | `invalid_format` / `home_assistant_error` de `test_condition` | sí |
| `response_too_large` (`data_keys`, `max_bytes`, `hint`) | diagnóstico que no cabe | sí |
| `preview_unavailable` (`detail`) | falla la lectura previa a una vista previa | sí (lectura) |
| errores de token de siempre | token caducado, usado, de otros argumentos | no |

Cualquier `detail` que venga de HA pasa por `redact_secrets`.

## Guía (`tools/guide.py`)

Tema nuevo `core_diagnostics` (y alias `logs`, `log`, `notifications`,
`validation`) con:

- Cuándo usar `ha_list_system_log` (errores agrupados, primera opción) frente a
  `ha_get_error_log` (líneas en bruto, solo si hay fichero de log); el caso de
  HA OS sin `duplicate_log_file` y que el log de Core también se lee por el
  Supervisor.
- `ha_get_log_levels` / `ha_set_log_level`: integración frente a módulo,
  persistencias, `NOTSET` para volver atrás; recordar bajar el nivel al
  terminar.
- `ha_validate_config` antes de `ha_create_or_update_automation`/`_script`;
  `ha_test_condition` para depurar una condición.
- Diagnósticos: `ha_list_diagnostics_handlers` → `ha_get_config_entry_diagnostics`
  o `ha_get_device_diagnostics`; `keys` si no cabe.
- Notificaciones: listar y descartar (token); descartar todas sigue por
  `ha_call_service` con token.
- Receta «¿por qué falla esta integración?»: log del sistema filtrado por
  `integration` → subir a DEBUG con `persistence="none"` → reproducir → leer →
  `NOTSET` → diagnósticos si hace falta.

El tema `diagnostics` de la 1.1.2 añade una línea que remite al nuevo.

## Tabla (`command_table.py`)

Las nueve entradas de data-model pasan a `dedicated`. La genérica de lectura y
la de escritura las rechazan con `use_dedicated_tool` y el nombre de la tool;
con la familia desactivada, con `family_disabled: true` (comportamiento de la
011, sin cambios).

## Banco

`tests/banco/cobertura_012.py`:

```python
PROBADAS_012: frozenset[str] = frozenset({
    "ha_set_log_level", "ha_clear_system_log",
    "ha_dismiss_persistent_notification",
})
NO_EJECUTABLES_012: dict[str, str] = {}
```

Sumada a la unión de `test_todas_las_escrituras_clasificadas` y a
`test_listas_disjuntas` (028), o, si la 028 no está integrada, a un
`tests/test_banco_cobertura_012.py` propio con el mismo invariante limitado a
los módulos de la familia `core_diagnostics`.
