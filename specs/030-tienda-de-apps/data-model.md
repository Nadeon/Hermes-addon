# Modelo de datos: tienda de apps (030)

## Repositorio (`sv_list_store_repositories`)

| Campo | De dónde | Nota |
|---|---|---|
| `slug` | `GET /store/repositories` | `sha1(url.lower())[:8]` o el fijo de un integrado |
| `name` | ídem | texto de terceros |
| `source` | ídem | lo que se añadió; contraseña de credenciales tapada |
| `url` | ídem | la que declara el repositorio (o `source`); texto de terceros, contraseña tapada |
| `maintainer` | ídem | texto de terceros |
| `builtin` | Hermes | `slug` ∈ {`core`, `local`, `a0d7b954`, `5c53de3b`, `d5369777`} (Supervisor 2026.11.0, `BuiltinRepository`) |
| `apps_count` | `GET /store/addons` | apps con `repository == slug` |
| `installed_apps` | ídem | slugs con `installed: true`, ordenados |

Respuesta: `{count, items, truncated, _third_party_text: {fields: ["name",
"url", "maintainer"], warning}}`, ordenada por `builtin` (primero) y `slug`.
Con `repository`: `{repository: {...}, _third_party_text}` o
`{"error": "repository_not_found", "detail": …}`.

Si `GET /store/addons` falla, la lista sale igual con `apps_count` e
`installed_apps` a `null` y `apps_unavailable: <error redactado>`: la lista
de repositorios no depende del catálogo.

## Forma de una URL de repositorio (`sv_add_store_repository`)

1. `repository.strip()`; vacío → `invalid_argument`.
2. `^(?P<url>[^#\s]+)(?:#(?P<branch>[\w\-./]+))?$` (la de `RE_REPOSITORY`).
3. `urlsplit(url)`: `scheme` ∈ {`http`, `https`}, `hostname` no vacío.
4. Longitud ≤ 2048.

`detail` del error, sin copiar el valor: «repository must be an http(s) URL
of a git repository, optionally followed by #branch.»

Ya añadido si `url.lower()` coincide con algún `source.lower()`, o si es
`https://github.com/home-assistant/apps` o `…/addons` (equivalen a `core`).

Tapado de credenciales: si `urlsplit(url).password` existe, se sustituye por
`***REDACTED***` (`REDACTED_MARKER`) en la URL que se muestra; el usuario se
conserva. Función pura, reutilizada en lista, vista previa, respuesta y
errores (en estos, sustitución literal de la contraseña por el marcador).

## Vistas previas

### `sv_add_store_repository`

```json
{
  "action": "add_store_repository",
  "repository": "https://example.com/repo-ficticio#main",
  "host": "example.com",
  "branch": "main",
  "credentials_hidden": false,
  "warning": "Third-party code: …",
  "note": "Nothing is downloaded until you confirm. …"
}
```

### `sv_remove_store_repository`

```json
{
  "action": "remove_store_repository",
  "repository": {"slug": "abcd1234", "name": "…", "source": "…", "url": "…", "maintainer": "…"},
  "apps_count": 3,
  "effect": "Its apps will no longer be installable. You can add it again later.",
  "_third_party_text": {"fields": ["repository.name", "repository.url", "repository.maintainer"], "warning": "…"}
}
```

`estado` del token: `{"repository": <el objeto leído>, "installed_apps": [...]}`.

### `sv_rebuild_addon`

```json
{
  "action": "rebuild_addon",
  "slug": "local_ejemplo",
  "name": "…",
  "version": "1.0.0",
  "state": "started",
  "build": true,
  "force": false,
  "effect": "Removes the app container and image and builds the image again locally. …",
  "keeps": "Options and the app's /data are kept.",
  "on_failure": "If the build fails, the app is left without an image and cannot start until it is rebuilt or reinstalled.",
  "_third_party_text": {"fields": ["name"], "warning": "…"}
}
```

Con `force=true` y `build=false`, `effect` dice que vuelve a descargar la
imagen de la misma versión. Con Hermes, `critical_warning` de
`_self_warning(slug, "rebuilding")`.

### `sv_install_addon` (añadidos)

`name`, `version_latest`, `repository`, `build` y, si el repositorio no es
integrado, `third_party_repository: true` y `warning` (terceros);
`_third_party_text` con `name`. Los campos de la 1.1.2 (`slug`, `action`,
`note`) siguen.

### `sv_update_addon` (añadidos)

`available`, `reason` (si no), `changelog_excerpt` (≤ 4000 caracteres),
`changelog_truncated`, `changelog_unavailable` (motivo, si no se pudo leer) y
`_third_party_text` con `changelog_excerpt`. Los campos de la 1.1.2 siguen.

### `sv_set_addon_options` (añadidos)

`validation`: `{checked: true, valid: true, pwned: false|true|null}` o
`{checked: false, reason: "empty_options"|<error redactado>}`;
`warning_pwned` si `pwned` es `true`. Error sin token:
`{"error": "invalid_options", "message": <redactado>, "changed_paths": [...]}`.

## Trozo de texto (`sv_get_addon_changelog`, `sv_get_addon_documentation`)

| Campo | Nota |
|---|---|
| `slug`, `name`, `version_latest` | de la ficha de la tienda |
| `text` | `redactado[offset : offset + n]`, con `n ≤ max_chars` y la respuesta dentro de `response_max_bytes` |
| `total_chars` | longitud del texto redactado |
| `offset` | el pedido |
| `truncated` | `offset + len(text) < total_chars` |
| `next_offset` | `offset + len(text)` si `truncated` |
| `secrets_redacted` | si `redact_secrets` cambió algo |
| `_third_party_text` | `fields: ["name", "text"]` |

Argumentos: `offset` entero ≥ 0; `max_chars` entero de 1 a 100000 (por
defecto 20000); fuera de rango → `invalid_argument` sin llamada.

## Disponibilidad (`sv_get_addon_availability`)

`{slug, name, available, reason, installed, version, version_latest, arch,
homeassistant, stage, advanced, build, repository, _third_party_text:
{fields: ["name"]}}`. `available` sale de la ruta `availability` (no del
campo de la ficha, que se calcula igual pero puede estar en caché); `reason`
es el mensaje del Supervisor redactado o `null`.

## Error

Ver research R-10. Códigos propios: `invalid_argument`, `invalid_identifier`,
`repository_not_found`, `repository_already_added`, `builtin_repository`,
`repository_in_use`, `not_supported`, `addon_not_found`,
`already_installed`, `addon_not_available`, `changelog_not_found`,
`documentation_not_found`, `addon_not_installed`, `addon_not_in_store`,
`rebuild_version_changed`, `rebuild_not_supported`, `invalid_options`.

## Evento de log

`app_store_action` con `tool`, `outcome` (`ok`, `preview`, `rejected:<código>`,
`error`), `repository` (slug) o `slug` (app), y `bytes`/`count` cuando hay
texto o lista. Nunca: la URL de un repositorio, el texto del changelog o la
documentación, opciones ni mensajes de validación.

## Entradas de la tabla que cambian (15, todas a `dedicated`)

| Clave | Tool | Familia | CAP | Motivo |
|---|---|---|---|---|
| `GET /store` | `sv_list_store_repositories` | `app_store` | CAP-082 | cubierto por `sv_list_store_repositories` (repositorios) y `sv_list_addons` (apps) |
| `GET /store/repositories` | `sv_list_store_repositories` | `app_store` | CAP-082 | cubierto por `sv_list_store_repositories` |
| `GET /store/repositories/{repository}` | `sv_list_store_repositories` | `app_store` | CAP-082 | cubierto por `sv_list_store_repositories(repository=…)` |
| `POST /store/repositories` | `sv_add_store_repository` | `app_store` | CAP-082 | cubierto por `sv_add_store_repository` |
| `DELETE /store/repositories/{repository}` | `sv_remove_store_repository` | `app_store` | CAP-082 | cubierto por `sv_remove_store_repository` |
| `POST /store/repositories/{repository}/repair` | `sv_repair_store_repository` | `app_store` | CAP-082 | cubierto por `sv_repair_store_repository` |
| `POST /store/reload` | `sv_reload_store` | `app_store` | CAP-082 | cubierto por `sv_reload_store` |
| `GET /store/addons/{app}/changelog` | `sv_get_addon_changelog` | `app_store` | CAP-082 | cubierto por `sv_get_addon_changelog` |
| `GET /store/addons/{app}/documentation` | `sv_get_addon_documentation` | `app_store` | CAP-082 | cubierto por `sv_get_addon_documentation` |
| `GET /store/addons/{app}/availability` | `sv_get_addon_availability` | `app_store` | CAP-082 | cubierto por `sv_get_addon_availability` |
| `GET /store/addons/{app}/{version}` | `sv_get_addon` | `supervisor` | CAP-082 | el Supervisor 2026.11.0 ignora `{version}` y devuelve la ficha actual: cubierto por `sv_get_addon` |
| `POST /store/addons/{app}/install/{version}` | `sv_install_addon` | `supervisor` | CAP-082 | el Supervisor 2026.11.0 ignora `{version}` e instala la de la tienda: cubierto por `sv_install_addon` |
| `POST /store/addons/{app}/update/{version}` | `sv_update_addon` | `supervisor` | CAP-082 | el Supervisor 2026.11.0 ignora `{version}` y actualiza a la de la tienda: cubierto por `sv_update_addon` |
| `POST /addons/{app}/options/validate` | `sv_set_addon_options` | `supervisor` | CAP-093 | cubierto por `sv_set_addon_options` (valida en la vista previa) |
| `POST /addons/{app}/rebuild` | `sv_rebuild_addon` | `app_store` | CAP-093 | cubierto por `sv_rebuild_addon` |

Tramo 1: las siete primeras filas (repositorios y recarga). Tramo 2: las
ocho restantes.

### Sin cambios, con test nuevo

`GET /store/addons/{app}/icon|logo` y los alias legados `/addons/{app}/icon|
logo|changelog|documentation|install|update` y `/addons/reload` siguen `deny`
(clase B).

## Familia

`Familia("app_store", "App store: repositories, store reload, app changelog,
documentation and availability, and app rebuild.", "1.2.0", True,
("store_repositories", "store_apps"))`. El tramo 1 la crea solo con
`store_repositories` (y una descripción que solo habla de repositorios y
recarga); el tramo 2 añade `store_apps` y completa la descripción.
