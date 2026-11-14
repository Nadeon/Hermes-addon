# Modelo de datos: plataforma y deprecaciones (027)

La 027 no añade tools, familias, opciones ni entradas de la tabla. Estos son
los datos nuevos o cambiados.

## Error de un sub-job (`child_errors`, FR-002)

Sale de `supervisor_jobs.child_job_errors(data) -> tuple[list[dict], bool]`.

| Campo | Tipo | Origen | Regla |
|---|---|---|---|
| `job` | `str \| null` | `child_jobs[i].name` | tal cual si es texto; `null` si no |
| `message` | `str` | `child_jobs[i].errors[j].message` | `"unknown error"` si falta o no es texto; recortado a 500 (`JOB_ERROR_MAX_CHARS`); `redact_secrets` |

- Recorrido en profundidad, en el orden de la respuesta del Supervisor.
- Tope: 20 entradas (`CHILD_ERRORS_MAX`) y 5 niveles (`CHILD_JOBS_MAX_DEPTH`).
  Si se pasa de cualquiera, el segundo valor es `True` y la tool añade
  `child_errors_truncated: true` (sin ese campo cuando es `False`).
- `child_jobs` que no es lista, entradas que no son objetos o `errors` que no
  es lista: se ignoran; nunca se inventa un error.
- `job_errors` (los del job consultado) no cambia.

## Plataforma del Supervisor (FR-011)

Sale de `supervisor_platform.comprobar_plataforma(ha_client, environ) -> dict`.

| Campo | Tipo | Regla |
|---|---|---|
| `transport` | `"tcp"` | siempre en la 1.2.0 |
| `unix_socket_offered` | `bool` | `environ.get("SUPERVISOR_SOCKET", "").strip() != ""` |
| `api_v2_enabled` | `bool \| null` | `GET /supervisor/info` → `feature_flags.supervisor_v2_api is True`; `false` si la respuesta es un objeto sin `feature_flags` o sin la clave; `null` si la lectura falla, tarda más de 10 s o no es un objeto |

Eventos del log (structlog, nombres en inglés como el resto):

| Evento | Nivel | Cuándo | Campos |
|---|---|---|---|
| `supervisor_platform` | info | siempre, una vez por arranque | los tres de arriba |
| `supervisor_unix_socket_offered` | warning | `unix_socket_offered` | `message` (Hermes sigue por TCP) |
| `supervisor_api_v2_enabled` | warning | `api_v2_enabled is True` | `message` (Hermes sigue con la V1, que sigue disponible) |
| `supervisor_platform_check_failed` | debug | `api_v2_enabled is None` | `reason` (`error`, `timeout`, `unexpected_response`); sin el texto del error |

Nunca se escribe la ruta del socket ni otro valor del entorno.

## Error `command_removed_in_ha` (FR-009)

Respuesta de `ha_remove_device_from_config_entry` al confirmar cuando HA
responde `unknown_command` (`HAConnectionError.code`):

```json
{
  "error": "command_removed_in_ha",
  "command": "config/device_registry/remove_config_entry",
  "replacement": "ha_remove_device",
  "detail": "Home Assistant no longer has this command (deprecated, removed in 2027.9). Nothing was changed. Use ha_remove_device to delete the device."
}
```

El token se completa con `success=False`. No se envía ningún otro comando.

## Traducción de opciones (FR-006)

`hermes/translations/<idioma>.yaml`, con `<idioma>` en `en` y `es`:

```yaml
configuration:
  <opción>:            # cada clave de `schema` en config.yaml, ni más ni menos
    name: <texto>      # obligatorio, no vacío
    description: <texto>   # opcional para el Supervisor; aquí obligatorio y no vacío
```

Forma que acepta el Supervisor 2026.11.0 (`apps/validate.py`,
`SCHEMA_TRANSLATION_CONFIGURATION` y `SCHEMA_APP_TRANSLATIONS`). Sin la
palabra «add-on» ni «addon» (sin distinguir mayúsculas).
