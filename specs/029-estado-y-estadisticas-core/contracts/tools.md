# Contratos de las tools (029)

Ocho tools nuevas, todas de solo lectura, sin `confirmation_token`. Nombre,
argumentos, hints (código `R`ead-only, `D`estructive, `I`dempotent,
`O`pen world) y lo que la descripción (en inglés) tiene que decir. Formas de
respuesta y errores en [data-model.md](../data-model.md).

## Familia `system_status` (módulo `tools/system_status.py`)

### `ha_get_system_health(domain: str | None = None, timeout_seconds: float = 10) -> str`

- Hints `R-I-`. Comando `system_health/info` (suscripción recogida hasta
  `finish` o el plazo, y cancelada).
- Validación: `domain` con forma `^[a-z0-9_]+$` (≤ 64); `timeout_seconds` en
  [1, 30].
- Descripción: lo que enseña «System information» de HA, por dominio; los
  valores lentos se esperan hasta `timeout_seconds` y los que no llegan salen
  en `pending`; no cambia nada; recorta dominios enteros si no cabe y los
  nombra.

### `ha_get_system_state() -> str`

- Hints `R-I-`. Comando `subscribe_system_state` (primer evento, 10 s,
  cancelada).
- Descripción: si HA o el host necesitan reinicio, por qué y si el aviso se
  pospuso; para reiniciar, `sv_restart_core`; no descarta el aviso.

### `ha_list_integration_setup_times(limit: int = 50, min_seconds: float | None = None) -> str`

- Hints `R-I-`. Comando `integration/setup_info`.
- Validación: `limit` en [1, 500]; `min_seconds` ≥ 0.
- Descripción: segundos que tardó cada integración en arrancar, de la más
  lenta a la más rápida; `total` y `total_seconds` cuentan todas.

### `ha_list_integration_manifests(integrations: list[str] | None = None, custom_only: bool = False) -> str`

- Hints `R-I-`. Comando `manifest/list`.
- Validación: hasta 100 nombres, cada uno con forma de dominio; repetidos se
  ignoran.
- Descripción: resumen de diez campos por integración (las cargadas si no se
  nombran); las que no son de HA llevan `_third_party_text`; para el
  manifiesto entero, `ha_get_integration_manifest`.

### `ha_get_integration_manifest(integration: str) -> str`

- Hints `R-I-`. Comando `manifest/get`.
- Validación: forma de dominio.
- Descripción: el manifiesto completo (dependencias, requisitos, versión,
  propietarios, documentación…); texto de terceros marcado si no es de HA.

## Familia `recorder` (módulo `tools/recorder_status.py`)

### `ha_validate_statistics(statistic_id: str | None = None, issue_type: str | None = None) -> str`

- Hints `R-I-` (por nombre exacto en `_READ_ONLY_EXACT`). Comando
  `recorder/validate_statistics`.
- Validación: `statistic_id` con forma `^[a-z0-9_]+[.:][a-z0-9_]+$`;
  `issue_type` `^[a-z0-9_]+$`.
- Descripción: los problemas que HA detecta en las estadísticas de largo
  plazo (unidad cambiada, sin `state_class`, entidad que ya no existe…); solo
  valida: no corrige nada ni crea avisos en Repairs.

### `ha_get_statistics_metadata(statistic_ids: list[str]) -> str`

- Hints `R-I-`. Comando `recorder/get_statistics_metadata`.
- Validación: 1–100 ids con la forma de arriba; repetidos se piden una vez.
- Descripción: metadatos (fuente, unidades, media, suma) de las estadísticas
  pedidas, y `missing`; para listarlas todas, `ha_list_statistic_ids`.

### `ha_get_recorder_info(entity_id: str | None = None) -> str`

- Hints `R-I-`. Comandos `recorder/info` y, con `entity_id`,
  `recorder/entity_options/get`.
- Validación: `entity_id` con forma de entidad; la entidad tiene que existir.
- Descripción: si el recorder graba, su cola, si migra la base; con
  `entity_id`, si esa entidad se graba y quién lo desactivó.

## Por la tabla (sin tool nueva)

| Comando | Genérica | Carga | Tema de la guía |
|---|---|---|---|
| `logbook/get_action_calls` | `ha_read_ws_command` | `start_time` (obligatorio), `end_time` | `recorder` |
| `network` | `ha_read_ws_command` | ninguna | `system_status` |
| `network/url` | `ha_read_ws_command` | ninguna | `system_status` |
| `http/config` | `ha_read_ws_command` | ninguna | `system_status` |

## Rechazos de la genérica (sin cambiar código de la 011)

`ha_read_ws_command` / `ha_call_ws_command` con cualquiera de los nueve
comandos de la tabla de data-model → `use_dedicated_tool` con su tool; con la
familia desactivada, además `family_disabled: true`. Ninguno llega a HA.
