# Contratos: tools de la tienda de apps (030)

Descripciones, errores y respuestas al cliente en inglés (como el resto de
tools); comentarios del código en español.

## Firmas (esquema de entrada MCP)

```python
# Módulo store_repositories (familia app_store), tramo 1
sv_list_store_repositories(repository: str | None = None)
sv_add_store_repository(repository: str, confirmation_token: str | None = None)
sv_remove_store_repository(repository: str, confirmation_token: str | None = None)
sv_repair_store_repository(repository: str)
sv_reload_store()

# Módulo store_apps (familia app_store), tramo 2
sv_get_addon_changelog(slug: str, offset: int = 0, max_chars: int = 20000)
sv_get_addon_documentation(slug: str, offset: int = 0, max_chars: int = 20000)
sv_get_addon_availability(slug: str)
sv_rebuild_addon(slug: str, force: bool = False, confirmation_token: str | None = None)

# Existentes (familia supervisor): MISMO esquema de entrada que la 1.1.2
sv_install_addon(slug, confirmation_token=None)      # vista previa nueva
sv_update_addon(slug, confirmation_token=None)       # vista previa nueva
sv_set_addon_options(slug, options, confirmation_token=None)  # valida en la vista previa
```

`repository` en quitar, reparar y listar es el `slug` del repositorio
(validado con `validate_slug`: `invalid_identifier` si no); en añadir es la
URL.

## Anotaciones

| Tool | readOnly | destructive | idempotent | openWorld | Cómo |
|---|---|---|---|---|---|
| `sv_list_store_repositories` | sí | no | sí | no | prefijo `sv_list_` |
| `sv_get_addon_changelog` | sí | no | sí | no | prefijo `sv_get_` |
| `sv_get_addon_documentation` | sí | no | sí | no | prefijo `sv_get_` |
| `sv_get_addon_availability` | sí | no | sí | no | prefijo `sv_get_` |
| `sv_add_store_repository` | no | sí | sí | sí | `_DESTRUCTIVE_EXACT`, `_OPEN_WORLD` |
| `sv_remove_store_repository` | no | sí | sí | no | `_DESTRUCTIVE_EXACT` |
| `sv_repair_store_repository` | no | no | sí | sí | `_OPEN_WORLD` |
| `sv_reload_store` | no | no | sí | sí | `_OPEN_WORLD` |
| `sv_rebuild_addon` | no | sí | sí | sí | `_DESTRUCTIVE_EXACT`, `_OPEN_WORLD` |

Por qué: añadir y reconstruir piden token y el invariante de la 1.1.2 exige
que lo que se hace confirmar no se anuncie inofensivo; añadir mete código de
terceros (cadena de suministro) y quitar deja apps sin poder instalarse.
Añadir, reparar, recargar y reconstruir provocan descargas (clonar, `git
pull`, imágenes base); leer el changelog o la documentación lee el clon
local. Repetir cualquiera deja el mismo estado (añadir dos veces da «ya
añadido»). Las tools de la 1.1.2 no cambian de anotación.

## Descripciones (lo que tienen que decir)

- Todas: «app (add-on)» la primera vez, «app» después (027).
- `sv_list_store_repositories`: qué es un repositorio de la tienda; que
  `builtin` no se puede quitar; que `installed_apps` impide quitarlo; que
  `name`, `url` y `maintainer` son de terceros.
- `sv_add_store_repository`: es código de terceros sin revisar; dos pasos;
  la vista previa no descarga nada; formato `https://…[#rama]`; no instala
  apps (para eso `sv_install_addon`).
- `sv_remove_store_repository`: rechazado si es integrado o tiene apps
  instaladas (desinstalar antes); dos pasos.
- `sv_repair_store_repository`: vuelve a clonar el repositorio si su copia
  local está rota; solo sustituye la copia si la descarga sale bien; no vale
  para `local`.
- `sv_reload_store`: actualiza todos los repositorios y el catálogo; no
  instala ni actualiza apps; puede tardar.
- `sv_get_addon_changelog` / `_documentation`: el de la versión de la
  tienda (no la instalada); texto de terceros redactado; por trozos con
  `offset`/`max_chars`.
- `sv_get_addon_availability`: arquitectura, tipo de máquina y versión de HA.
- `sv_rebuild_addon`: borra contenedor e imagen y los rehace con la misma
  versión; solo apps que se construyen en local salvo `force`; conserva
  opciones y `/data`; si falla, la app queda sin imagen; dos pasos; tarda.
- `sv_install_addon` / `sv_update_addon`: instalan o actualizan **a la
  versión que ofrece la tienda**; no se puede elegir otra; la vista previa
  comprueba la disponibilidad (y en actualizar, enseña el changelog).
- `sv_set_addon_options`: la vista previa valida las opciones finales con el
  Supervisor y no da token si no son válidas.

## Respuestas

```json
// sv_list_store_repositories()
{"count": 2, "truncated": false, "items": [
  {"slug": "core", "name": "Official apps", "source": "core", "url": "https://home-assistant.io/apps", "maintainer": "HomeAssistant", "builtin": true, "apps_count": 40, "installed_apps": ["core_ejemplo"]},
  {"slug": "abcd1234", "name": "Repo ficticio", "source": "https://example.com/repo-ficticio", "url": "https://example.com/repo-ficticio", "maintainer": "Nadie <nadie@example.com>", "builtin": false, "apps_count": 1, "installed_apps": []}],
 "_third_party_text": {"fields": ["name", "url", "maintainer"], "warning": "…"}}

// sv_add_store_repository con token
{"result": "ok", "repository": {"slug": "abcd1234", "name": "…", "url": "…", "maintainer": "…"},
 "_third_party_text": {"fields": ["repository.name", "repository.url", "repository.maintainer"], "warning": "…"},
 "next": "Install its apps with sv_install_addon after reviewing them."}

// sv_remove_store_repository con token
{"result": "ok", "repository": "abcd1234"}

// sv_repair_store_repository / sv_reload_store
{"result": "ok", "repository": "abcd1234"}
{"result": "ok", "hint": "List the catalog with sv_list_addons(installed_only=false)."}

// sv_get_addon_changelog
{"slug": "abcd1234_ejemplo", "name": "Ejemplo", "version_latest": "2.0.0",
 "text": "## 2.0.0\n- …", "total_chars": 51234, "offset": 0, "truncated": true,
 "next_offset": 20000, "secrets_redacted": false,
 "_third_party_text": {"fields": ["name", "text"], "warning": "…"}}

// sv_get_addon_availability
{"slug": "abcd1234_ejemplo", "name": "Ejemplo", "available": false,
 "reason": "App abcd1234_ejemplo not supported on this platform, supported architectures: armv7",
 "installed": false, "version": null, "version_latest": "2.0.0", "arch": ["armv7"],
 "homeassistant": null, "stage": "stable", "advanced": false, "build": false,
 "repository": "abcd1234", "_third_party_text": {"fields": ["name"], "warning": "…"}}

// sv_rebuild_addon con token
{"result": "ok", "slug": "local_ejemplo", "force": false}
```

## Errores

```json
{"error": "invalid_argument", "field": "repository", "detail": "repository must be an http(s) URL of a git repository, optionally followed by #branch."}
{"error": "repository_already_added", "repository": "abcd1234", "detail": "This repository is already in the store."}
{"error": "repository_not_found", "detail": "No store repository with that slug. List them with sv_list_store_repositories."}
{"error": "builtin_repository", "detail": "Built-in repositories cannot be removed."}
{"error": "repository_in_use", "installed_apps": [{"slug": "abcd1234_ejemplo", "name": "Ejemplo"}],
 "detail": "The Supervisor refuses to remove a repository with installed apps. Uninstall them first with sv_uninstall_addon."}
{"error": "not_supported", "detail": "The local repository cannot be repaired."}
{"error": "addon_not_found", "detail": "No app with that slug in the store."}
{"error": "already_installed", "detail": "The app is already installed. Use sv_update_addon to update it."}
{"error": "addon_not_available", "reason": "…", "detail": "The app cannot be installed on this system."}
{"error": "changelog_not_found", "detail": "The app has no changelog."}
{"error": "documentation_not_found", "detail": "The app has no documentation."}
{"error": "addon_not_installed", "detail": "The app is not installed. Install it with sv_install_addon."}
{"error": "addon_not_in_store", "detail": "The app is no longer in any store repository and cannot be rebuilt."}
{"error": "rebuild_version_changed", "version": "1.0.0", "version_latest": "1.1.0", "detail": "Update the app first with sv_update_addon."}
{"error": "rebuild_not_supported", "detail": "The app uses a prebuilt image. Pass force=true to download the image again."}
{"error": "invalid_options", "message": "…", "changed_paths": ["…"]}
{"error": "<mensaje del Supervisor redactado, contraseña de la URL tapada>"}
```

Ningún `detail` copia el valor rechazado.

## Log

Ver data-model («Evento de log»).

## Genéricas (tabla)

- `sv_read_api("/store/repositories")`, `sv_read_api("/store")`,
  `sv_read_api("/store/addons/<slug>/changelog")` → `use_dedicated_tool` con
  la tool de data-model, sin llamada.
- `sv_call_api("POST", "/store/repositories", …)`,
  `sv_call_api("POST", "/store/addons/<slug>/install/1.0.0")`,
  `sv_call_api("POST", "/addons/<slug>/rebuild")` → `use_dedicated_tool`,
  sin llamada.
- `sv_read_api("/store/addons/<slug>/icon")` → `deny` (clase B), sin
  llamada.
- Con `app_store` desactivada, las entradas `dedicated` a sus tools
  responden como la 011 define para una familia desactivada
  (`family_disabled: true`).

## Guía

Tema `app_store` (en español, como los demás). Primera línea: es la tienda
de apps del Supervisor, no el Marketplace de Core (`marketplace`). Después:
las nueve tools; añadir
un repositorio es meter código de terceros (revisar antes, dos pasos, la URL
exacta); quitar exige desinstalar antes sus apps; reparar frente a recargar;
el changelog y la documentación son de la versión de la tienda y por
trozos; disponibilidad; reconstruir (local frente a `force`, qué se pierde
si falla); que no se puede elegir versión y la vuelta atrás con un backup
parcial. Alias: `store`, `tienda`, `repositories`, `repository`,
`repositorios`, `changelog`, `documentation`, `rebuild`, `availability`.
El tema `supervisor` remite a `app_store` y dice que la vista previa de
`sv_set_addon_options` valida, que la de `sv_install_addon` comprueba la
disponibilidad y que la de `sv_update_addon` enseña el changelog. El índice
nombra el tema y, como `system_diagnostics`, sale en las instrucciones del
servidor solo con la familia activa.
