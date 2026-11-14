# Modelo de datos: Hermes 1.0.12

Solo las estructuras que cambian o que este cambio necesita entender.

## Estado del safety backup (`/data/last_safety_backup.json`)

| Clave | Tipo | Significado |
|---|---|---|
| `last_safety_backup_at` (`_MARCA`) | float (epoch) | Último safety backup **correcto** (o lanzado a mano con `sv_create_safety_backup`, comportamiento sin cambios). |
| `last_backup_name` | str | Nombre del último backup correcto. |
| `last_job_id`, `last_slug`, `backup_name` | str | Los escribe `sv_create_safety_backup`; sin cambios. |
| `pending_job_id` | str \| ausente | **Nuevo.** Job de un safety backup automático lanzado y aún no resuelto. |
| `pending_started_at` | float \| ausente | **Nuevo.** Cuándo se lanzó; cuenta para el límite duro de 60 s. |
| `pending_backup_name` | str \| ausente | **Nuevo.** Nombre del backup pendiente. |

Transiciones del safety backup automático (`maybe_trigger_safety_backup`):

```text
sin pendiente ──(ventana vencida y ≥60 s desde el último intento)──▶ lanzar backup
lanzar backup ──(Supervisor devuelve job_id)──▶ PENDIENTE (se guarda en el acto)
PENDIENTE ──(sondeo: done y errors vacío)──▶ OK: _MARCA = ahora, borrar pendiente, escribir
  (si se resuelve en una escritura posterior: _MARCA = pending_started_at; si es más
   antiguo que la ventana → safety_backup_stale sin escribir. En curso > 2 h →
   safety_backup_state_unknown y se borra el pendiente. Revisión independiente, M2/M3)
PENDIENTE ──(sondeo: done con errors)──▶ FALLO: borrar pendiente, error, no escribir
PENDIENTE ──(plazo agotado)──▶ sigue PENDIENTE: error con job_id, no escribir
PENDIENTE (llamada siguiente) ──(job terminado sin errores)──▶ OK y escribir
PENDIENTE (llamada siguiente) ──(job en curso)──▶ error safety_backup_in_progress
PENDIENTE (llamada siguiente) ──(errores / 404 / forma rara)──▶ borrar pendiente, error, no escribir
```

Respuesta síncrona sin `job_id` (backup ya hecho): `_MARCA = ahora`, como hoy.

## Job del Supervisor (`GET /jobs/{uuid}`)

Campos que usa Hermes: `name`, `reference`, `uuid`, `progress`, `stage`,
`done` (bool; también `True` si falló), `errors` (lista de
`{type, message, stage}`), `child_jobs`.

Derivados que expone Hermes:

- `errors`: lista de textos (`message` saneado y recortado).
- `success`: `True` si `done` y sin errores; `False` si `done` con errores; `None` si no ha terminado.

## Registro local de jobs (`/data/pending_jobs.json`)

| Clave | Valores |
|---|---|
| `status` | `running` → `done` \| **`failed`** (nuevo) |
| `reference` | slug u otro identificador del resultado |

## Entrada del registro de entidad

- `aliases`: lista cuyos elementos son texto o `null`. `null` = nombre calculado (desde HA 2026.4); su posición marca el orden. La lista sustituye a la anterior. `aliases: null` (sin lista) no es válido.
- `name`: desde HA 2026.11, solo la parte de la entidad; Home Assistant antepone el nombre del dispositivo.
- `area_id`: propia; si es nula, la entidad hereda el área efectiva de su dispositivo.

## Dispositivo

| Campo | Normal | Hijo (HA ≥ 2026.9) |
|---|---|---|
| `id`, `name`, `name_by_user`, `area_id`, `disabled_by`, `labels`, `identifiers` | sí | sí |
| `config_entry_id` | sí (primario) | sí |
| `config_entries`, `config_entries_subentries` | sí, retirables en 2027.8 | **no** |
| `manufacturer`, `model`, `via_device_id`, `connections` | sí | **no** |
| `parent_device_id` | no | sí |

Área efectiva: `area_id` propio; si es nulo y hay `parent_device_id`, el área
efectiva del padre; máximo 8 saltos; un ciclo da «sin área».

Integraciones de un dispositivo (para el camino antiguo de `ha_remove_device`):
la unión de `config_entry_id` y `config_entries`, sin repetidos.

## Dashboard de Lovelace

- Protegidos contra el borrado: `url_path` nulo, `"lovelace"` y el `url_path` igual al panel por defecto (`default_panel` de los datos de sistema del frontend).
- En la lista, si existe `lovelace`, es el único con `is_default: true` y no hay «Default» sintético.

## Versión de Home Assistant

`ha_at_least(minimo)` → `True` | `False` | `None` (desconocida). Umbrales usados:

| Umbral | Para qué |
|---|---|
| 2026.9.0 | `ha_remove_device`: `remove` frente a `remove_config_entry` |
| 2026.3.0 | `period: "year"` en estadísticas |
| 2026.11.0 | Mensaje de HACS: Marketplace frente a «no instalado» |
| 2024.10.0 | Versión mínima de arranque (`HA_CORE_MIN_SUPPORTED`, comprobada al arrancar, no con este helper) |
