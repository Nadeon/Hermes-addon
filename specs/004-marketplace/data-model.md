# Modelo de datos: Hermes 1.1.0 — Marketplace de solo lectura

Hermes no guarda nada nuevo: todo se lee de Home Assistant en cada llamada.
Aquí están las formas que circulan y las reglas de validación.

## API detectada

| Valor | Cuándo |
|---|---|
| `marketplace` | El comando `marketplace/*` respondió bien. |
| `hacs` | `marketplace/*` respondió `unknown_command` y `hacs/*` respondió bien. |

No se guarda entre llamadas (research R-01).

### Transiciones de una llamada

```text
marketplace/<cmd>
  ├─ éxito ────────────────────────────► api = "marketplace"
  ├─ code = not_loaded ────────────────► error marketplace_not_loaded (fin; sin hacs/*)
  ├─ code = unknown_command ─► hacs/<cmd>
  │                              ├─ éxito ──────────────► api = "hacs"
  │                              ├─ code = unknown_command ─► ha_at_least("2026.11.0")
  │                              │                              ├─ True ─► marketplace_unavailable
  │                              │                              └─ False/None ─► hacs_not_installed
  │                              └─ otro código ─► error con ese código
  └─ otro código / sin código ─► error con ese código (o ha_error)
```

## Resumen de repositorio (`RepositorySummary`)

Proyección fija, igual para las dos API. Un campo que no venga sale como `null`.

| Campo | Tipo | Origen Marketplace | Origen HACS |
|---|---|---|---|
| `id` | str | `id` | `id` (convertido a str) |
| `full_name` | str | `full_name` | `full_name` |
| `name` | str \| null | `name` | `name` |
| `category` | str | `category` | `category` |
| `description` | str \| null | `description`, recortada a 300 | igual |
| `installed` | bool | `installed` | `installed` |
| `installed_version` | str \| null | `installed_version` | `installed_version` |
| `available_version` | str \| null | `available_version` | `available_version` |
| `pending_upgrade` | bool \| null | `pending_upgrade` | `pending_upgrade` (null en HACS antiguos) |
| `can_install` | bool \| null | `can_install` | `can_download` |
| `custom` | bool \| null | `custom` | `custom` |
| `domain` | str \| null | `domain` | `domain` |
| `homeassistant` | str \| null | `homeassistant` (versión mínima de HA) | igual |
| `stars` | int \| null | `stars` | `stars` |
| `last_updated` | str \| null | `last_updated` | `last_updated` |
| `status` | str \| null | `status` | `status` |
| `new` | bool \| null | `new` | `new` |

Elementos que no son dict se descartan.

## Actualización pendiente (`PendingUpdate`)

`id`, `full_name`, `name`, `category`, `installed_version`, `available_version`,
`update_entity_id` (str \| null).

Regla: `installed` es verdadero **y** (`pending_upgrade is True` **o**, si
`pending_upgrade` no viene, `installed_version` y `available_version` existen y
son distintos).

## Versión publicada (`Release`)

`tag` (str), `name` (str \| null), `published_at` (str \| null), `prerelease`
(bool \| null). Orden: el que da HA (más reciente primero).

## Repositorio crítico (`CriticalRepository`)

`repository` (str), `reason` (str \| null, recortado a 300), `link` (str \| null),
`acknowledged` (bool \| null).

## Repositorio retirado (`RemovedRepository`)

`repository`, `reason` (recortado a 300), `link`, `removal_type`, `acknowledged`.

## Entidad `update` de un repositorio

Entrada de `config/entity_registry/list` con `entity_id` que empieza por
`update.`, `platform` igual a la API (`marketplace` o `hacs`) y `unique_id` igual
al `id` del repositorio (comparados como texto). Si el registro no se puede leer,
`update_entity_id` es `null` y la tool no falla.

## Validación de argumentos (antes de llamar a HA)

| Argumento | Regla | Error |
|---|---|---|
| `category` | `None` o una de `appdaemon`, `integration`, `plugin`, `python_script`, `template`, `theme` | `invalid_category` |
| `category` (tras detectar el Marketplace) | no puede ser `appdaemon` ni `python_script` | `invalid_category` |
| `installed_only` | bool | (tipado por el SDK) |
| `search` | `None` o texto de 1 a 100 caracteres | `invalid_argument` |
| `limit` (lista) | entero 1–500 | `invalid_argument` |
| `limit` (releases) | entero 1–30 | `invalid_argument` |
| `repository_id` | texto 1–64 caracteres de `[A-Za-z0-9_-]` | `invalid_argument` |

## Umbral de versión

| Umbral | Para qué |
|---|---|
| 2026.11.0 | Solo para elegir entre `marketplace_unavailable` y `hacs_not_installed` cuando ninguna API responde. |
