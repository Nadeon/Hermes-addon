# Modelo de datos: escritura en el Marketplace (026)

Formas de lo que leen, envían y devuelven las nueve tools. Nombres de campos y
errores en inglés (los ve el cliente); los ejemplos usan datos ficticios
(`ejemplo/tarjeta`, id `"123456"`).

## Repositorio leído

De `marketplace/repositories/list` con `{"categories": [<c>]}`, una categoría
por mensaje (`_list_catalog` de `tools/marketplace.py`), proyectado con
`_summary` (17 campos de la 004). Para escribir, Hermes busca por `id` (texto)
y usa: `id`, `full_name`, `name`, `category`, `custom`, `installed`,
`installed_version`, `available_version`, `can_install`, `homeassistant`,
`domain`, `status`. Además, solo para la vista previa de instalar y
desinstalar, `config_flow` del objeto de HA (no está en el resumen de la 004:
se lee del bruto, sin ampliar `SUMMARY_FIELDS`).

## Comandos que se envían (lista cerrada de escritura)

`_WRITE_SUFFIXES` en `tools/_marketplace_write.py`; la guarda lanza
`RuntimeError` con cualquier otro sufijo antes de enviar.

| Sufijo | Carga que construye Hermes |
|---|---|
| `critical/acknowledge` | `{"repository": <full_name>}` |
| `repository/ignore` | `{"repository": <id>}` |
| `repositories/remove` | `{"repository": <id>}` |
| `repository/refresh` | `{"repository": <id>}` |
| `repositories/detect` | `{"repository": <owner/repo>}` |
| `repositories/add` | `{"repository": <owner/repo>, "category": <c>}` |
| `repository/install` | `{"repository": <id>}` + `"version"` si se pidió + `"confirm_replace_built_in": true` solo con `replace_built_in` |
| `repository/uninstall` | `{"repository": <id>}` |
| `repository/version` | `{"repository": <id>, "version": <v>}` |
| `repository/beta` | `{"repository": <id>, "show_beta": <bool>}` |

Las cargas las construye una función pública por comando
(`carga_<accion>(...)`), que usan las tools y el test de contrato del banco.

## Validación de argumentos (sin llamar a HA)

| Argumento | Regla | Error |
|---|---|---|
| `repository_id` | texto (o entero no booleano, convertido) con `_REPOSITORY_ID_RE` | `invalid_argument`, `field: "repository_id"` |
| `version` | texto no vacío, ≤ 200, sin `?`, `#`, `%`, `\`, espacios ni segmentos que empiezan por `.` (`valid_ref` de HA) | `invalid_argument`, `field: "version"` |
| `show_beta`, `backup`, `replace_built_in` | `bool` estricto | `invalid_argument` |
| `category` | `integration`, `plugin`, `template`, `theme` | `invalid_category` con `valid` |
| `repository` (añadir) | ver «URL de repositorio» | `invalid_argument`, `field: "repository"`, sin copiar el valor |
| `repository` (reconocer) | `owner/repo` (`[A-Za-z0-9-]{1,39}/[\w.-]{1,100}`), ≤ 140 | `invalid_argument` |

## URL de repositorio (añadir)

- Forma corta: `owner/repo`.
- Forma URL: `https://[usuario[:clave]@](www.)github.com[:puerto]/owner/repo[.git][/]`,
  sin consulta ni fragmento, puerto vacío o numérico, ≤ 2048 caracteres,
  espacios de los extremos quitados.
- Resultado: `owner/repo` en minúsculas (lo que se envía) y la URL completa
  (lo que ata el token).
- `credentials_hidden`: verdadero si hay parte de usuario; esa parte sale
  como `***REDACTED***` (`tapar_credenciales`).

## Estado atado (`estado` de `create_confirmation_token`)

| Tool | Argumentos atados | `estado` releído al confirmar |
|---|---|---|
| `ha_marketplace_acknowledge_critical` | `repository` | `{"entry": {repository, reason, link, acknowledged}}` |
| `ha_marketplace_ignore_repository` | `repository_id` | `{"full_name", "removed": {repository, removal_type}}` |
| `ha_marketplace_remove_repository` | `repository_id` | `{"full_name", "custom", "installed"}` |
| `ha_marketplace_refresh_repository` | `repository_id` | `{"full_name"}` |
| `ha_marketplace_add_repository` | `repository` (URL completa), `category` | `{"full_name", "already_added": false}` (se relee la lista; la detección no se repite al confirmar: saldría otra vez a GitHub, y HA vuelve a validar la categoría al añadir) |
| `ha_marketplace_install` | `repository_id`, `version`, `replace_built_in`, `backup` | `{"full_name", "category", "installed_version", "available_version"}` |
| `ha_marketplace_uninstall` | `repository_id`, `backup` | `{"full_name", "category", "installed_version"}` |
| `ha_marketplace_set_version` | `repository_id`, `version` | `{"full_name", "category"}` |
| `ha_marketplace_set_beta` | `repository_id`, `show_beta` | `{"full_name", "category"}` |

## Vistas previas

Todas: `{"confirmation_token", "preview": {...}}` con `preview.action`,
`preview.repository` (resumen: `id`, `full_name`, `name`, `category`,
`custom`, `installed`, `installed_version`, `available_version`),
`preview.effect` (texto), `preview.backup` y `_third_party_text`.

### Vista previa de instalar

```json
{
  "action": "install | reinstall | change_version",
  "repository": {"id": "123456", "full_name": "ejemplo/tarjeta", "name": "…",
                  "category": "integration", "custom": false,
                  "installed": false, "installed_version": null,
                  "available_version": "1.2.3", "domain": "ejemplo"},
  "target_version": "1.2.3",
  "version_check": {"checked": true, "in_releases": true, "prerelease": false},
  "third_party": true,
  "warning": "Third-party code: … not reviewed by Home Assistant nor by Hermes … runs inside Home Assistant …",
  "replaces_built_in": false,
  "restart": {"likely": true, "reason": "…", "after": "restart Core with sv_restart_core; Hermes does not restart it"},
  "backup": {"will_create": true, "kind": "partial backup of the Home Assistant configuration, without the database",
             "name": "hermes_marketplace_install_20261115T120000Z"}
}
```

`version_check` solo con `version` distinta de `available_version`; si no,
`null`. Si las versiones no se pueden consultar: `{"checked": false,
"reason": …}`.

### Vista previa de desinstalar

`action: "uninstall"`, `removes` (qué se borra: «the repository files under
/config» y, en `plugin`, «and its Lovelace resource»), `restart`, `backup`.

### Vistas previas sin ficheros

`set_version`: `installed_version` y `available_version` del resumen (la
versión seleccionada no sale en `repositories/list`, solo en
`repository/info`, que es clase B; `available_version` es la que HA ofrece
ahora), `new_selection` (`version`) y la nota de que, si es la rama por
defecto del repositorio, HA quita la selección en vez de fijarla (la rama por
defecto tampoco sale en `repositories/list`),
`installs_nothing: true`, `next` (`ha_marketplace_install` o la entidad
`update`). `set_beta`: `show_beta`, el mismo `installs_nothing` y `next`.
`refresh`: `contacts_github: true`. `ignore`: `removed` (`reason`,
`removal_type`, `link`) y `reversible: false`. `acknowledge_critical`:
`entry` y `reversible: false`. `remove_repository`: `effect`. `add_repository`:
`repository` (URL tapada), `full_name`, `credentials_hidden`,
`credentials_sent: false`, `detected_categories`, `category`,
`third_party`, `warning`. En todas, `backup: {"will_create": false,
"reason": "this action changes no files under /config"}`.

## Respuestas con token

- `ok` comunes: `{"result": "ok", "repository": {…releído…}}` (o `null` y
  `hint` si no se pudo releer).
- Instalar: `restart_required` (`status == "pending-restart"`),
  `backup: {"slug"}` o `{"created": false}`.
- Desinstalar: `restart_required`, `backup`.
- Reconocer: `entry` tal como queda.
- Añadir: el repositorio añadido releído por `full_name`.

## Errores (códigos estables)

| Código | Cuándo | Token |
|---|---|---|
| `invalid_argument`, `invalid_category` | validación | — |
| `marketplace_not_loaded` | HA responde `not_loaded` | no |
| `marketplace_write_unsupported` | HA no conoce `marketplace/*` | no |
| `marketplace_warning_not_accepted` | `warning_accepted` no es `true` (vista previa) o HA responde `warning_not_accepted` | no / fallido |
| `github_not_connected` | añadir sin GitHub | no / fallido |
| `github_rate_limited` | HA responde `github_rate_limited` | no / fallido |
| `repository_not_found` | id que no está en la lista | no |
| `cannot_install` | `can_install: false` | no |
| `replaces_built_in` | integración de HA sin `replace_built_in` (o HA lo responde) | no / fallido |
| `repository_not_installed` | desinstalar uno no instalado | no |
| `repository_in_use` | integración con entradas del `domain` | no |
| `repository_installed` | quitar uno instalado | no |
| `not_custom_repository` | quitar uno del catálogo por defecto | no |
| `repository_not_removed`, `critical_repository` | ignorar | no |
| `not_critical`, `already_acknowledged` | reconocer | no |
| `repository_already_added`, `category_not_detected`, `core_repository`, `app_repository` | añadir | no |
| `repository_busy` | HA está instalando ese repositorio | fallido |
| `backup_failed` | el backup previo falló o no terminó (`job_id` si lo hay) | fallido |
| `ha_error` | cualquier otro error de HA, con `detail` redactado | fallido |

## Evento de log

`marketplace_write` con `tool`, `outcome` y `category` (o `null`). Nada más.

## Familias

| Familia | Desde | Desactivable | Módulos | Descripción (inglés) |
|---|---|---|---|---|
| `marketplace_manage` | 1.2.0 | sí | `marketplace_manage` | «Marketplace catalogue and notices: add and remove custom repositories, refresh, ignore removed ones, acknowledge critical ones.» |
| `marketplace_install` | 1.2.0 | sí | `marketplace_install` | «Install, uninstall and pin versions of Marketplace (HACS) repositories: third-party code.» |

## Tabla (`command_table.py`)

Las 10 entradas «pendiente de tool dedicada (spec 026)» a `dedicated`,
`cap="CAP-075"`:

| Comando | Tool | Familia | Tramo |
|---|---|---|---|
| `marketplace/critical/acknowledge` | `ha_marketplace_acknowledge_critical` | `marketplace_manage` | 1 |
| `marketplace/repository/ignore` | `ha_marketplace_ignore_repository` | `marketplace_manage` | 1 |
| `marketplace/repositories/remove` | `ha_marketplace_remove_repository` | `marketplace_manage` | 1 |
| `marketplace/repository/refresh` | `ha_marketplace_refresh_repository` | `marketplace_manage` | 1 |
| `marketplace/repositories/add` | `ha_marketplace_add_repository` | `marketplace_manage` | 1 |
| `marketplace/repositories/detect` | `ha_marketplace_add_repository` (`_ConMatiz`: «la usa su vista previa para saber las categorías») | `marketplace_manage` | 1 |
| `marketplace/repository/install` | `ha_marketplace_install` | `marketplace_install` | 2 |
| `marketplace/repository/uninstall` | `ha_marketplace_uninstall` | `marketplace_install` | 2 |
| `marketplace/repository/version` | `ha_marketplace_set_version` | `marketplace_install` | 2 |
| `marketplace/repository/beta` | `ha_marketplace_set_beta` | `marketplace_install` | 2 |
