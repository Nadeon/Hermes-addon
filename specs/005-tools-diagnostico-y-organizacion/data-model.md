# Modelo de datos: Hermes 1.1.0 — diagnóstico y organización

Solo las estructuras que esta spec crea o necesita entender. Las de Home
Assistant y del Supervisor se describen con los campos que Hermes usa.

## Registros de Home Assistant

| Entidad | Campos que usa Hermes | Relación | Al borrarla, Home Assistant… |
|---|---|---|---|
| Planta (`floor`) | `floor_id`, `name`, `level` (int\|null), `icon`, `aliases` [str], `created_at`, `modified_at` | Área → `floor_id` | pone `floor_id: null` en sus áreas |
| Etiqueta (`label`) | `label_id`, `name`, `color`, `icon`, `description`, `created_at`, `modified_at` | Área, dispositivo y entidad → `labels` [str] | la quita de dispositivos y entidades (y de áreas, a verificar: research) |
| Categoría (`category`) | `category_id`, `name`, `icon`, `created_at`, `modified_at`; vive en un `scope` | Entidad → `categories: {scope: category_id}` | la quita de las entidades |

Las automatizaciones, scripts y escenas pueden **referenciar** una planta o
etiqueta en sus destinos (`target: {floor_id | label_id}`). Home Assistant no
las edita al borrar: esas referencias dejan de resolver.

### Validación de entrada (Hermes)

| Campo | Regla |
|---|---|
| `name` | texto no vacío tras `strip()` |
| `level` | entero o `null` (no booleano) |
| `aliases` | lista de textos; se descartan vacíos |
| `color` | uno de los 26 colores de tema de HA o `^#[0-9a-fA-F]{6}$`, o `null` |
| `scope` | `automation`, `script`, `scene` o `helpers` |
| `floor_id`, `label_id`, `category_id` | identificador (`validate_identifier`) |

## Vista previa de borrado

```text
impact = {
  "assignments_removed": {          # lo que HA limpiará
    "areas":    {"count": n, "ids": [...≤50], "truncated": bool},
    "devices":  {...},              # solo etiquetas
    "entities": {...}               # etiquetas y categorías
  },
  "references_unresolved": {        # lo que HA NO edita (planta y etiqueta)
    "automation": {"count": n, "ids": [...]},
    "script":     {...},
    "scene":      {...}
  }
}
```

Estados de la primera llamada (sin token):

```text
leer entrada ──(no existe)──▶ not_found (sin token)
leer entrada ──(error / forma rara)──▶ preview_unavailable (sin token)
leer impacto ──(cualquier lectura falla / forma rara)──▶ preview_unavailable (sin token)
leer impacto ──(ok)──▶ preview + confirmation_token
```

## Issue de Repairs (resumen que devuelve Hermes)

| Campo | Origen | Nota |
|---|---|---|
| `domain`, `issue_id`, `issue_domain` | `repairs/list_issues` | |
| `severity` | ídem | `critical` > `error` > `warning` para ordenar |
| `is_fixable`, `breaks_in_ha_version`, `created`, `learn_more_url` | ídem | |
| `ignored`, `dismissed_version` | ídem | `ignored` filtra con `include_ignored` |
| `translation_key` | ídem | |
| `translation_placeholders` | ídem | redactado (`redact_structure` + `redact_secrets`) |

Transiciones de `ha_ignore_repair`:

```text
no existe ──▶ not_found (sin token)
ignored == ignore ──▶ {"result": "unchanged"} (sin token)
ignored != ignore ──▶ preview + token ──(token válido)──▶ repairs/ignore_issue ──▶ ok
```

## Traza

| Parte | `summary` | `full` |
|---|---|---|
| Cabecera: `run_id`, `domain`, `item_id`, `state`, `script_execution`, `timestamp`, `last_step`, `trigger`, `error`, `not_triggered` | sí (textos recortados y redactados) | sí |
| Pasos: `path`, `timestamp`, `result` (≤500 car.), `error`, `child_id` | sí | sí |
| `changed_variables` por paso | no | sí, redactado |
| `config` | no | sí, redactada |
| `blueprint_inputs`, `context` | no | no |

Límite: `min(65536, response_max_bytes)` bytes del JSON serializado. Orden de
recorte en `full`: `changed_variables` del último paso hacia el primero →
`config` → pasos del final. Marca: `truncated: true` y `omitted`.

## Información de resolución del Supervisor

```text
{unsupported: [str], unhealthy: [str],
 issues:      [{uuid, type, context, reference, reference_extra}],
 suggestions: [{uuid, type, context, reference, reference_extra, auto}],
 checks:      [{slug, enabled}]}
```

`uuid`: 32 hexadecimales, estable para `(type, context, reference,
reference_extra)`. Descartar es `DELETE`; un issue o sugerencia descartado
puede reaparecer si la condición persiste.

## Backup de Home Assistant (lista blanca)

```text
backup = {backup_id, name, date,
          agents: {agent_id: {protected, size}},
          addons: [{slug, name, version}], folders: [str],
          database_included, homeassistant_included, homeassistant_version,
          failed_agent_ids, failed_addons, failed_folders, with_automatic_settings}

config = {agents: {agent_id: {protected, retention}},
          automatic_backups_configured,
          create_backup: {agent_ids, include_addons, include_all_addons,
                          include_database, include_folders, name, password_set},
          last_attempted_automatic_backup, last_completed_automatic_backup,
          retention: {copies, days}, schedule,
          next_automatic_backup, next_automatic_backup_additional}
```

Nunca salen: `create_backup.password`, `extra_metadata` (con `instance_id`),
ni ningún campo que no esté en la lista.

## Anotación de safety backups de Hermes (`/data/safety_backups.json`)

Nueva. Independiente de `/data/last_safety_backup.json` (ventana y pendiente
de 1.0.12), que no cambia.

```json
{
  "version": 1,
  "entries": [
    {
      "name": "hermes-safety-20261114T083000Z",
      "job_id": "<uuid del job>",
      "launched_at": 1794644400.0,
      "origin": "auto",
      "slug": "<slug del backup> | null",
      "confirmed_by": "job_reference | unique_name_date | sync_response | null"
    }
  ]
}
```

| Campo | Regla |
|---|---|
| `origin` | `auto` (antes de escribir en `/config`) o `tool` (`sv_create_safety_backup`) |
| `slug` | `null` hasta confirmarlo; nunca se rellena por prefijo de nombre |
| Tamaño | como mucho 100 entradas |
| Fichero corrupto o ilegible | se trata como anotación vacía: no hay candidatos, no se borra nada (fail-closed); se registra `safety_backup_ledger_unreadable` y **no** se sobrescribe hasta el siguiente lanzamiento |

Ciclo de vida de una entrada:

```text
lanzada (slug null)
  ──(respuesta síncrona con slug)──────────────▶ confirmada (sync_response)
  ──(job done, sin errores, reference)─────────▶ confirmada (job_reference)
  ──(único backup con ese nombre, ±10 min)─────▶ confirmada (unique_name_date)
  ──(job con errores)───────────────────────────▶ eliminada de la anotación
  ──(7 días sin confirmar)──────────────────────▶ eliminada (queda fuera de la retención)
confirmada
  ──(su slug ya no está en /backups)────────────▶ eliminada
  ──(poda: sobra respecto a keep)───────────────▶ DELETE /backups/{slug} ──▶ eliminada
```

Candidato a poda = confirmada **y** presente con el mismo slug y nombre **y**
nombre con formato exacto **y** `type: "full"` **y** no `protected` **y** una
sola ubicación **y** `date` legible.

Poda (tras un safety backup automático correcto):

```text
keep == 0 ──▶ nada
GET /backups falla o forma rara ──▶ nada (log)
candidatos ≤ keep ──▶ nada
candidatos > keep ──▶ ordenar por date desc (desempate launched_at)
                     conservar keep, borrar el resto del más antiguo al más reciente,
                     máx. 5, parar en el primer fallo (log)
```

## Opción del add-on

| Opción | Schema | Por defecto | Variable de entorno | Campo de `Config` |
|---|---|---|---|---|
| `safety_backup_keep` | `int(0,50)?` | `3` | `HERMES_SAFETY_BACKUP_KEEP` | `safety_backup_keep: int = 3` |
