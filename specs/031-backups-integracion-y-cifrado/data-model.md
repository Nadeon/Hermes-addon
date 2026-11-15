# Modelo de datos: backups de la integración `backup` y safety backups cifrados (031)

Formas de lo que entra y sale. Todo lo que sale pasa por lista blanca (como
`tools/ha_backups.py`) y después por `redact_structure` + `redact_secrets`. Los
nombres de campo de las respuestas van en inglés, como el resto de Hermes.

## 1. Agente de backup (`ha_list_backup_agents`)

```json
{
  "agents": [
    {"agent_id": "hassio.local", "name": "local", "kind": "local",
     "protected": true, "retention": null, "used_by_automatic_backups": true},
    {"agent_id": "hassio.nas_backups", "name": "nas_backups", "kind": "mount",
     "protected": true, "retention": {"copies": 10, "days": null},
     "used_by_automatic_backups": true},
    {"agent_id": "cloud.cloud", "name": "Home Assistant Cloud", "kind": "remote",
     "protected": true, "retention": null, "used_by_automatic_backups": false}
  ],
  "count": 3
}
```

- `kind`: `local` si `agent_id` ∈ {`backup.local`, `hassio.local`}; `mount`
  si empieza por `hassio.` y no es `hassio.local`; `remote` en el resto.
- `protected`/`retention`: de `backup/config/info` → `config.agents[agent_id]`;
  sin entrada, `protected: true` (el valor por defecto de HA al crear la entrada
  del agente) y `retention: null` (usa la global).
- `used_by_automatic_backups`: `agent_id` ∈ `create_backup.agent_ids`.
- Orden: el de HA. Recorte con `ajustar_lista_a_bytes` (`truncated`).

## 2. Configuración por lista blanca

Es la `_config_permitida` de `tools/ha_backups.py` (sin `password`, con
`password_set`). Se reutiliza tal cual para «actual» y «resultante».

## 3. `ha_update_backup_config`: argumentos y vista previa

Argumentos (todos opcionales; al menos uno):

| Argumento | Forma | Validación |
|---|---|---|
| `schedule` | `{"recurrence": "never"\|"daily"\|"custom_days", "days": ["mon",…], "time": "HH:MM" \| null}` | claves conocidas; `days` sin repetir, de `mon`…`sun`; `time` `HH:MM` o `HH:MM:SS` |
| `retention` | `{"copies": int≥1\|null, "days": int≥1\|null}` | |
| `agents` | `{agent_id: {"protected": bool, "retention": {copies, days}\|null}}` | `agent_id` con forma de id; 1–20 agentes |
| `create_backup` | `{"agent_ids": [...], "include_addons": [...]\|null, "include_all_addons": bool, "include_database": bool, "include_folders": [...]\|null, "name": str\|null}` | `password` → `invalid_argument` (`field: "create_backup.password"`, sin el valor); listas sin repetir, ≤ 100; carpetas de `share`, `addons/local`, `ssl`, `media`; `include_all_addons` con `include_addons` no vacío → `invalid_argument` |
| `automatic_backups_configured` | bool | |

Vista previa:

```json
{
  "action": "update_backup_config",
  "current": {"...": "configuración por lista blanca (sección 2)"},
  "resulting": {"...": "la misma, con la fusión de HA aplicada"},
  "changed": ["schedule.time", "retention.copies", "agents.hassio.nas_backups.protected"],
  "warnings": ["Backups uploaded to hassio.nas_backups will NOT be encrypted."],
  "retention_effect": {
    "estimate": true,
    "detail": "Computed with Home Assistant's retention rules; it depends on what happens until then.",
    "would_delete": [
      {"backup_id": "abc123", "name": "Automatic backup 2026.11.1",
       "date": "2026-11-01T04:30:00+00:00", "agents": ["hassio.local"],
       "when": "after_next_automatic_backup"}
    ],
    "truncated": false
  }
}
```

- Fusión: HA **sustituye** `schedule` y `retention` enteros
  (`BackupSchedule(**schedule)`, `RetentionConfig(**retention)`: lo no pasado
  vuelve al valor por defecto de HA, que en `recurrence` es `never` y en la
  retención es «sin límite»). Pasar solo `{"time": "04:30"}` apagaría los
  backups automáticos. Por eso **Hermes completa** cada uno de esos dos
  documentos (y la `retention` de cada agente, si se pasa como objeto) con los
  valores actuales de los campos que no se pasan, y manda el documento
  completo; un `null` explícito sí se respeta. `create_backup` ya lo funde HA
  (`replace`); `agents`, por agente. La vista previa enseña lo que se manda.
- Estado atado: `{"config": current, "would_delete": [ids]}`.
- Respuesta al confirmar: `{"result": "ok", "changed": [...]}`.

## 4. Estimación de retención (`estimar_retencion`)

Entrada: configuración resultante (retención global, retención por agente),
backups de `backup/info` (por lista blanca: id, nombre, fecha, agentes,
`with_automatic_settings`), `ahora`. Salida: lista de
`{backup_id, name, date, agents, when}` ordenada por fecha.

Reglas (de `backup/config.py` de HA 2026.11.1):

1. Solo backups con `with_automatic_settings: true`.
2. Por días (`when: "within_24h"`): con retención global `days` y sin
   retención por agente, los de `date + days < ahora`. Con retención por
   agente, por cada (backup, agente): el agente con retención propia usa la
   suya (si su `days` es `None`, ese agente no borra por días); el resto, la
   global; el backup entra con los agentes de los que se borraría.
3. Por copias (`when: "after_next_automatic_backup"`): con `copies` global y
   sin retención por agente, de los automáticos ordenados por fecha, todos
   salvo los `copies - 1` más recientes (al sumar el nuevo quedan `copies`).
   Con retención por agente, lo mismo por agente.
4. Un backup que sale por las dos reglas va una vez, con `within_24h`.

## 5. Ajustes previos a actualizar (`hassio/update/config/*`)

```json
{"core_backup_before_update": true, "add_on_backup_before_update": false,
 "add_on_backup_retain_copies": 1}
```

`ha_set_update_backup_settings(core_backup_before_update?,
add_on_backup_before_update?, add_on_backup_retain_copies?)`, al menos uno;
`add_on_backup_retain_copies` entero 1–100. Vista previa
`{"action": "set_update_backup_settings", "current": {...}, "resulting":
{...}, "changed": [...], "warnings": [...]}`; aviso si baja
`add_on_backup_retain_copies`. Estado atado: `current`.

## 6. Clave de cifrado de HA (`hermes/backup_key.py`)

```python
@dataclass(frozen=True)
class ClaveDeBackups:
    clave: str | None         # nunca se registra; __repr__ la tapa
    motivo: str | None        # None con clave; si no, uno de:
                              # "no_key_configured", "backup_integration_unavailable",
                              # "ha_unreachable"

async def leer_clave_de_backups(ha_client) -> ClaveDeBackups
```

- Lee `backup/config/info` (plazo de 10 s: va delante de un safety backup y no
  puede retrasar la escritura los 30 s por defecto de `ws_send`) →
  `config.create_backup.password`. Cadena no vacía →
  clave. `None` o vacía → `no_key_configured`. `unknown_command` o HA anterior
  a 2025.1 → `backup_integration_unavailable`. `HAConnectionError` sin código
  o WebSocket caído → `ha_unreachable`. Cualquier otra respuesta inesperada →
  `backup_integration_unavailable` (fail-closed: sin clave).
- `__repr__` y `__str__` devuelven `ClaveDeBackups(clave=<oculta>, motivo=…)`
  para que un log accidental no la saque. No hay caché.
- `password_source` (vistas previas de restaurar): `provided` (hay
  `password`), `backup_encryption_key` (protegido, sin `password`, hay
  clave), `backup_encryption_key_unavailable` (protegido, sin `password`, sin
  clave; incluye el motivo), `not_needed` (no protegido).

## 7. `ha_create_backup` y `ha_create_automatic_backup`

Vista previa de `ha_create_backup`:

```json
{
  "action": "create_backup",
  "name": "Antes de migrar",
  "agents": [{"agent_id": "hassio.local", "kind": "local", "encrypted": true},
             {"agent_id": "cloud.cloud", "kind": "remote", "encrypted": true}],
  "content": {"homeassistant": true, "database": true,
              "addons": "all" , "folders": ["share", "ssl"]},
  "warnings": []
}
```

- `encrypted` **por agente**: HA cifra o descifra la copia de cada agente
  según su `protected` (`hassio/backup.py`, `manager.py`: sin entrada de
  configuración, cifra). Es `encrypt and protected(agent)`. Un solo
  `encrypted` global mentiría si un agente tiene `protected: false`.
- `addons`: `"all"`, la lista pedida o `[]`.
- Avisos: agente remoto con `encrypted: false` («a copy of the whole
  configuration, including secrets.yaml, is uploaded unencrypted to …»);
  `include_database: false`.
- Apps o carpetas sin el agente `hassio.local` presente (Core sin Supervisor)
  → `invalid_argument` (HA: «Addons and folders are not supported by core
  backup»), sin token.
- Estado atado: `{"agents": [ids disponibles], "key_set": bool}`.
- Respuesta: `{"backup_job_id": "...", "status": "started",
  "follow_with": "ha_list_backups (state returns to idle; last_action_event says completed or failed)"}`.

Vista previa de `ha_create_automatic_backup`: `{"action":
"create_automatic_backup", "agents": [{agent_id, kind, encrypted}],
"content": {...}, "retention_effect": {...sección 4, solo copias...},
"warnings": [...]}`, con `encrypted = password_set and protected(agent)`.
Estado atado: `{"config": configuración por lista blanca, "would_delete":
[ids]}`.

## 8. `ha_restore_backup`

Argumentos: `backup_id` (identificador), `agent_id` (opcional),
`restore_homeassistant` (bool, `true`), `restore_database` (bool o `null`:
igual a `database_included`; con `hassio.local` presente y
`restore_homeassistant`, tiene que ser igual a `database_included`; nunca
`true` sin `restore_homeassistant`), `restore_addons` (lista de slugs, opcional),
`restore_folders` (lista de carpetas, opcional), `password` (opcional,
secreto), `confirmation_token`.

Vista previa:

```json
{
  "action": "restore_backup",
  "backup": {"backup_id": "abc123", "name": "Automatic backup 2026.11.1",
             "date": "2026-11-14T04:30:12+00:00",
             "homeassistant_version": "2026.11.1"},
  "location": {"agent_id": "hassio.nas_backups", "name": "nas_backups",
               "kind": "mount", "protected": true, "size": 734003200,
               "also_in": ["cloud.cloud"]},
  "password_source": "backup_encryption_key",
  "overwrites": {
    "homeassistant_configuration": true,
    "database": true,
    "addons": [{"slug": "core_mosquitto", "name": "Mosquitto broker", "version": "6.5.1"}],
    "folders": ["share"]
  },
  "not_restored": {"addons": [{"slug": "a0d7b954_vscode", "name": "Studio Code Server", "version": "5.19.0"}],
                   "folders": ["media", "ssl"]},
  "warnings": [
    "Everything restored is replaced by its state on 2026-11-14T04:30:12+00:00; changes made since then are LOST.",
    "Home Assistant Core restarts during the restore.",
    "The backup is downloaded from a remote location before restoring."
  ]
}
```

- Avisos condicionales: Core se reinicia (si `restore_homeassistant`); se
  descarga antes (`kind: remote`); Hermes se sustituye (si su slug está en
  `restore_addons`); `password_source:
  backup_encryption_key_unavailable` («the restore will fail unless you pass
  `password`»).
- Estado atado: `{"backup": <campos de backup y location sin also_in>,
  "content": <addons con versión y carpetas del backup>,
  "password_source": str}`.
- Respuestas: `{"result": "completed"}`; `{"status": "restore_started",
  "detail": "...", "check_with": [...]}`; errores `password_incorrect`,
  `backup_not_found`, `restore_failed` (mensaje de HA redactado).

## 9. `ha_delete_backup`

Vista previa:

```json
{
  "action": "delete_backup",
  "backup": {"backup_id": "abc123", "name": "...", "date": "...",
             "homeassistant_version": "2026.11.1", "automatic": true,
             "hermes_safety_backup": false},
  "deleted_from_all_locations": true,
  "locations": [{"agent_id": "hassio.local", "kind": "local", "size": 734003200, "protected": true},
                {"agent_id": "cloud.cloud", "kind": "remote", "size": 734003200, "protected": true}],
  "warnings": ["This is the only backup that includes the Home Assistant configuration."]
}
```

Estado atado: `{"backup_id", "date", "name", "locations": [(agent_id, size,
protected) ordenadas]}`. Respuesta: `{"result": "ok" | "partial",
"deleted_from": [...], "failed": {"<agent_id>": "<error enmascarado>"}}`.

## 10. `last_action_event` en `ha_list_backups`

`{"manager_state": str|null, "state": str|null, "stage": str|null,
"reason": str|null}` o `null`. Solo escalares; el resto de claves del evento
(subidas: `agent_id`, bytes) no se copia.

## 11. Opción `safety_backup_encryption`

| Valor | Con clave | Sin clave |
|---|---|---|
| `auto` (defecto) | cifrado | sin cifrar; `encrypted: false`, `encryption_skipped_reason` |
| `required` | cifrado | no se crea: `encryption_key_unavailable` (bloquea la escritura automática) |
| `off` | sin cifrar | sin cifrar |

- `hermes/config.yaml`: schema `safety_backup_encryption: "list(auto|required|off)?"`,
  opción `safety_backup_encryption: auto`.
- `run.sh` → `HERMES_SAFETY_BACKUP_ENCRYPTION`; `config.py`:
  `safety_backup_encryption: str = "auto"`, un valor fuera de los tres →
  `ValueError` al arrancar (fail-closed, como las demás).
- Respuesta de `sv_create_safety_backup` (nueva clave, siempre presente al
  crear): `"encrypted": bool` y, si es `false` con `auto`,
  `"encryption_skipped_reason"`.

## 12. Anotación de la retención (`safety_backups.json`)

Entrada (campo nuevo `encrypted`, opcional):

```json
{"name": "hermes-safety-20261115T101500Z", "job_id": "…", "launched_at": 1.0,
 "origin": "auto", "slug": "…", "confirmed_by": "job_reference",
 "encrypted": true}
```

`_motivo_exclusion`: `protected` distinto de `false` excluye salvo que
`entrada.get("encrypted") is True` y `protected is True`.

## 13. Entradas de la tabla

```python
"backup/agents/info": E("dedicated", "cubierto por ha_list_backup_agents", "backup_integration", tool="ha_list_backup_agents", cap="CAP-057"),
"backup/config/update": E("dedicated", "cubierto por ha_update_backup_config", "backup_integration", tool="ha_update_backup_config", cap="CAP-057"),
"backup/delete": E("dedicated", "cubierto por ha_delete_backup", "backup_integration", tool="ha_delete_backup"),
"backup/generate": E("dedicated", "cubierto por ha_create_backup", "backup_integration", tool="ha_create_backup"),
"backup/generate_with_automatic_settings": E("dedicated", "cubierto por ha_create_automatic_backup", "backup_integration", tool="ha_create_automatic_backup"),
"backup/restore": E("dedicated", "cubierto por ha_restore_backup", "backup_integration", tool="ha_restore_backup"),
"hassio/update/config/info": E("dedicated", "cubierto por ha_get_update_backup_settings", "backup_integration", tool="ha_get_update_backup_settings", cap="CAP-057"),
"hassio/update/config/update": E("dedicated", "cubierto por ha_set_update_backup_settings", "backup_integration", tool="ha_set_update_backup_settings", cap="CAP-057"),
```

## 14. Anotaciones

| Tool | Código | Cómo |
|---|---|---|
| `ha_list_backup_agents` | `R-I-` | prefijo |
| `ha_get_update_backup_settings` | `R-I-` | prefijo |
| `ha_update_backup_config` | `-DI-` | `_DESTRUCTIVE_EXACT` |
| `ha_set_update_backup_settings` | `-DI-` | `_DESTRUCTIVE_EXACT` |
| `ha_create_backup` | `-D-O` | `_DESTRUCTIVE_EXACT`, `_OPEN_WORLD`; no idempotente por prefijo |
| `ha_create_automatic_backup` | `-D-O` | ídem |
| `ha_restore_backup` | `-DIO` | `_DESTRUCTIVE_EXACT`, `_OPEN_WORLD` |
| `ha_delete_backup` | `-DIO` | prefijo destructivo; `_OPEN_WORLD` |
