# Contratos: tools de escritura del Marketplace (026)

> **DESVIACIÓN DV-1** (spec.md, «Requisitos»): `ha_marketplace_install`,
> `ha_marketplace_set_version`, `ha_marketplace_set_beta` y
> `ha_marketplace_add_repository` no existen (HA exige el aviso de riesgos
> aceptado por el usuario de Hermes, que no puede aceptarlo); lo que aquí se
> dice de ellas, de la URL de repositorio y de `marketplace/info` no aplica.
> Sus comandos quedan en `deny` con el motivo de la duda D-29.

Descripciones, errores y respuestas al cliente en inglés (como el resto de
tools); comentarios del código en español.

## Firmas (esquema de entrada MCP)

```python
# Módulo marketplace_manage (familia marketplace_manage), tramo 1
ha_marketplace_acknowledge_critical(repository: str, confirmation_token: str | None = None)
ha_marketplace_ignore_repository(repository_id: str, confirmation_token: str | None = None)
ha_marketplace_remove_repository(repository_id: str, confirmation_token: str | None = None)
ha_marketplace_refresh_repository(repository_id: str, confirmation_token: str | None = None)
ha_marketplace_add_repository(repository: str, category: str, confirmation_token: str | None = None)

# Módulo marketplace_install (familia marketplace_install), tramo 2
ha_marketplace_install(repository_id: str, version: str | None = None,
                       replace_built_in: bool = False, backup: bool = True,
                       confirmation_token: str | None = None)
ha_marketplace_uninstall(repository_id: str, backup: bool = True,
                         confirmation_token: str | None = None)
ha_marketplace_set_version(repository_id: str, version: str,
                           confirmation_token: str | None = None)
ha_marketplace_set_beta(repository_id: str, show_beta: bool,
                        confirmation_token: str | None = None)

# Existentes (familia marketplace, 1.1.2): MISMO esquema, anotaciones y comandos
ha_marketplace_list_updates()      # solo cambia la descripción y how_to_update
ha_hacs_list_updates()             # solo cambia la descripción
```

`repository_id` es el `id` de `ha_marketplace_list_repositories` (como en las
tools de lectura). `repository` en reconocer es el `full_name` de
`ha_marketplace_list_critical`; en añadir, `owner/repo` o una URL de GitHub.

## Anotaciones (todas por nombre exacto)

| Tool | readOnly | destructive | idempotent | openWorld | Cómo |
|---|---|---|---|---|---|
| `ha_marketplace_acknowledge_critical` | no | sí | sí | no | `_DESTRUCTIVE_EXACT` |
| `ha_marketplace_ignore_repository` | no | sí | sí | no | `_DESTRUCTIVE_EXACT` |
| `ha_marketplace_remove_repository` | no | sí | sí | no | `_DESTRUCTIVE_EXACT` |
| `ha_marketplace_refresh_repository` | no | sí | sí | sí | `_DESTRUCTIVE_EXACT`, `_OPEN_WORLD` |
| `ha_marketplace_add_repository` | no | sí | sí | sí | `_DESTRUCTIVE_EXACT`, `_OPEN_WORLD` |
| `ha_marketplace_install` | no | sí | sí | sí | `_DESTRUCTIVE_EXACT`, `_OPEN_WORLD` |
| `ha_marketplace_uninstall` | no | sí | sí | sí | `_DESTRUCTIVE_EXACT`, `_OPEN_WORLD` |
| `ha_marketplace_set_version` | no | sí | sí | sí | `_DESTRUCTIVE_EXACT`, `_OPEN_WORLD` |
| `ha_marketplace_set_beta` | no | sí | sí | sí | `_DESTRUCTIVE_EXACT`, `_OPEN_WORLD` |

Por qué: las nueve piden `confirmation_token` y el invariante de la 1.1.2 exige
que lo que se hace confirmar no se anuncie inofensivo. Ninguna entra en
`_READ_ONLY_EXACT` (que sigue nombrando solo las siete de lectura) y ningún
prefijo `ha_marketplace_` da `readOnlyHint` (test que lo comprueba con una
tool ficticia `ha_marketplace_xyz`: queda sin `readOnlyHint`). `openWorld`: HA
habla con GitHub (descarga, consulta o, al desinstalar con GitHub conectado,
refresca). Repetir cualquiera deja el mismo estado o da «ya hecho».

## Descripciones (lo que tienen que decir)

- Todas: dos pasos (vista previa y token); «Marketplace (HACS before Home
  Assistant 2026.11)»; que no funcionan con HACS 2.x.
- `ha_marketplace_install`, `set_version`, `set_beta`, `add_repository`:
  primero, la condición: «Requires the Marketplace risk warning to be
  accepted by the Home Assistant user Hermes connects as (the Supervisor
  user). Hermes never accepts it, and nobody can accept it for that user in
  the UI, so with Home Assistant 2026.11 this normally answers
  marketplace_warning_not_accepted: do it from the Marketplace UI.»
  `add_repository`, además, GitHub conectado.
- `ha_marketplace_install`: THIRD-PARTY CODE not reviewed by Home Assistant
  nor by Hermes, runs inside Home Assistant; what the preview shows
  (repository, versions, replaces built-in, restart, backup); `version`
  (tag, branch or commit; default the available one); `replace_built_in`;
  `backup` (partial backup of the configuration without the database, made
  before installing; no install if it fails); Hermes does not restart Core
  (`sv_restart_core`).
- `ha_marketplace_uninstall`: deletes the repository files from /config (a
  card also loses its Lovelace resource); an integration with config entries
  must have them deleted first (`ha_delete_config_entry`); backup as above;
  restart.
- `ha_marketplace_set_version` / `set_beta`: change what the Marketplace
  tracks and offers as update; install nothing; then
  `ha_marketplace_install` or the `update` entity.
- `ha_marketplace_add_repository`: only GitHub repositories (`owner/repo` or
  `https://github.com/owner/repo`); credentials in the URL are shown as
  `***REDACTED***` and never sent to Home Assistant; the category must be one
  Home Assistant detects; adding installs nothing.
- `ha_marketplace_remove_repository`: only custom repositories that are not
  installed.
- `ha_marketplace_refresh_repository`: Home Assistant asks GitHub (uses its
  rate limit); installs nothing.
- `ha_marketplace_ignore_repository`: only a repository removed from the
  catalogue (not critical): Home Assistant stops warning about the removal
  and keeps it; cannot be undone through the API.
- `ha_marketplace_acknowledge_critical`: marks a critical repository as seen
  and clears its Repairs issue; cannot be undone; installs or uninstalls
  nothing.
- `ha_marketplace_list_updates` (y `how_to_update`, y `ha_hacs_list_updates`):
  «Install with ha_marketplace_install (two steps) or
  ha_call_service('update', 'install', …) with a confirmation_token. Both
  need the Marketplace warning accepted by the Home Assistant user Hermes
  connects as; Hermes never accepts it.» Conserva «update», «install»,
  «confirmation_token» y «never accepts» (test de la 004).

## Respuestas

Ver data-model («Vistas previas», «Respuestas con token», «Errores»). Toda
respuesta pasa por `tapar_en_estructura` (credenciales de URL) y los errores
por `redactar_mensaje`; los textos de terceros llevan `_third_party_text`.
