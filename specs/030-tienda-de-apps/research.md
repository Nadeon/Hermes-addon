# Investigación: tienda de apps (030)

Todo lo de este documento sale de leer el código de Hermes en la rama (punta
`02beafc` de `feat/cobertura-total`) y el del Supervisor 2026.11.0 de la
carpeta de fuentes. No se ha llamado a ninguna instalación real.

## Lo que hay hoy (comprobado en el código)

### Hermes

- `tools/addons.py` (familia `supervisor`, 1.1.2):
  - `sv_list_addons(installed_only=False)` lee `GET /store/addons`: el
    catálogo de apps ya está cubierto. No hay nada de repositorios.
  - `sv_get_addon(slug)` lee `GET /addons/{slug}/info`; para una app no
    instalada el Supervisor reenvía a la ficha de la tienda.
  - `sv_install_addon` emite el token sin mirar nada: su vista previa solo
    dice `slug`, `action` y una nota. Si la app no está disponible en el
    sistema o ya está instalada, el token sirve para un error del
    Supervisor.
  - `sv_update_addon` lee `/addons/{slug}/info` para la vista previa
    (versión actual, última, `update_available`) y rechaza a Hermes antes
    (009). No dice qué cambia.
  - `sv_set_addon_options` mezcla los cambios con las opciones actuales y
    enseña todo redactado; no valida contra el esquema antes del token.
  - `_es_hermes`, `_self_warning`, `_track_job` y `_LONG_OP_TIMEOUT` (300 s)
    son reutilizables.
- `tools/marketplace.py` define el formato de texto de terceros:
  `_third_party(fields) → {"fields": [...], "warning": _THIRD_PARTY_WARNING}`.
- `security.create_confirmation_token(tool, args, preview, *, estado=…)` ata
  el token a los argumentos y, desde la 018, opcionalmente al estado leído.
- `ha.py`: `sv_request` (JSON, extrae `data`, error con `status`) y
  `sv_request_text` (GET de texto plano; error si `status >= 400`).
- `tools/_common.py`: sobre común (`sobre_de_lista`), `ajustar_lista_a_bytes`,
  `tam_json`.
- `command_table.py`: 15 entradas «pendiente de tool dedicada (spec 030)»
  (lista en data-model). Iconos, logos y alias legados ya son `deny` de
  clase B.
- `tests/banco/cobertura_escrituras.py`: `FUERA_DEL_BANCO` lista las `sv_*`
  que modifican con su motivo (`_SV_ADDONS` para las de apps).
- `docs/HOJA-DE-RUTA.md`: matriz de la 014 entre
  `<!-- matriz-pruebas:inicio -->` y `fin`; `tests/test_matriz_pruebas.py`
  exige una fila por tool sin `readOnlyHint` y que toda `sv_*` esté en `VM`
  y nombrada en «Tandas de pruebas» de `docs/BANCO-SUPERVISOR.md`.
- `tests/test_rutas_supervisor_rol.py`: toda ruta que llama Hermes tiene que
  caber en el rol `manager`. `/store.*` y `/addons/{slug}/(rebuild|options/
  validate)` caben (patrón `"/addons(?:/" + RE_SLUG + "/(?!security).+…"` y
  `"/store.*"` de `api/middleware/security.py`).

### Supervisor 2026.11.0

- `api/__init__.py`, `_register_store`: en v1, `GET /store`,
  `/store/addons[/{app}[/icon|logo|changelog|documentation|availability]]`,
  `POST /store/addons/{app}/install[/{version}]`,
  `POST /store/addons/{app}/update[/{version}]`,
  `GET /store/addons/{app}/{version}`; compartidas: `POST /store/reload`,
  `GET|POST /store/repositories`, `GET|DELETE /store/repositories/{r}`,
  `POST /store/repositories/{r}/repair`. Alias legados en `/addons/...`.
- `api/store.py`:
  - `apps_app_install` y `apps_app_update` **no leen `{version}`**: llaman a
    `sys_apps.install(app.slug)` / `update(app.slug, backup=…)`, que
    instalan la versión de la tienda. `apps_app_info` tampoco: devuelve la
    ficha actual.
  - `apps_app_changelog` y `apps_app_documentation` son `api_process_raw`
    de texto y, «porque el frontend no sabe tratar un error aquí», devuelven
    **200** con el mensaje: el de `StoreAppNotFoundError` si la app no
    existe, o «No changelog found for app {slug}!» / «No documentation
    found for app {slug}!».
  - Para una app instalada, `_extract_app` devuelve su `app_store`: el
    changelog y la documentación son los de la versión de la tienda.
  - `apps_app_availability` llama a `validate_availability()`: arquitectura,
    tipo de máquina y versión mínima de HA (`apps/model.py`). Si falla,
    `api_process` responde error con el mensaje.
  - `repositories_list` / `_info`: `slug`, `name`, `source`, `url`,
    `maintainer`. `add_repository` valida con `validate_repository`
    (`RE_REPOSITORY = ^(?P<url>[^#\s]+)(?:#(?P<branch>[\w\-./]+))?$` y
    `vol.Url()` sobre la URL) y llama a `store.add_repository`.
  - `repositories_repository_repair`: `repository.reset()` y descarta el
    aviso `EXECUTE_RESET` del centro de resolución si lo había.
- `store/__init__.py`:
  - `_add_repository`: las URLs de `home-assistant/apps` y
    `home-assistant/addons` se traducen a `core`; si el `slug` ya está,
    `StoreRepositoryAlreadyAddedError`; clona; si falla o no es un
    repositorio de apps válido, borra el clon y lanza el error; si va bien,
    lo guarda y recarga las apps.
  - `remove_repository`: rechaza los integrados («Can't remove built-in
    repositories!») y los que tienen apps instaladas («Can't remove
    '{source}'. It's used by installed apps»).
  - `reload`: `repo.update()` de todos los repositorios en paralelo
    (`git pull`), y relee las apps.
- `store/repository.py` y `store/utils.py`: el `slug` de un repositorio
  propio es `sha1(url.lower())[:8]`; los integrados tienen `slug` fijo:
  `core`, `local`, `a0d7b954` (comunidad), `5c53de3b` (ESPHome) y
  `d5369777` (Music Assistant) (`store/const.py`, `BuiltinRepository`).
  `RepositoryLocal.reset` lanza `StoreRepositoryLocalCannotReset`.
- `store/git.py`, `reset`: clona en una carpeta temporal y solo si sale bien
  borra el clon viejo y mueve el nuevo.
- `api/apps.py`:
  - `options_validate`: cuerpo = las opciones (sin envolver), o las
    guardadas si el cuerpo está vacío (`await request.json() or
    app.options`); responde `{message, valid, pwned}`; el mensaje es
    `humanize_error(options, ex)`, que incluye el valor rechazado; con la
    comprobación de contraseñas filtradas activa, `pwned` es `true`, `false`
    o `null` (error al comprobar), y con `force_security` invalida.
  - `rebuild`: cuerpo `{"force": bool}` (por defecto `false`); llama a
    `sys_apps.rebuild(slug, force=…)` y espera a que arranque. No tiene
    `background`.
  - `info` lleva `version`, `version_latest`, `detached`, `build`, `state`,
    `repository`, `available`.
- `apps/manager.py`, `rebuild`: `AppNotInstalledError`, `AppNotInStoreError`
  (desligada), `AppRebuildVersionChangedError` (versión instalada ≠ de la
  tienda) y `AppRebuildImageBasedError` (`need_build` falso sin `force`).
  `apps/app.py`, `rebuild`: quita contenedor e imagen y vuelve a instalar la
  misma versión (construye o descarga); si falla, `AppBuildFailedUnknownError`
  y la app queda sin imagen.

## R-1 — Nombres, familia y módulos

**Decisión**: prefijo `sv_` con el sustantivo de las tools existentes
(`addon` para una app, `store`/`store_repository` para la tienda). Nueve
tools:

| Tool | Ruta | Modifica | Token |
|---|---|---|---|
| `sv_list_store_repositories` | `GET /store/repositories[/{r}]`, `GET /store/addons` | no | no |
| `sv_add_store_repository` | `POST /store/repositories` | sí | sí |
| `sv_remove_store_repository` | `DELETE /store/repositories/{r}` | sí | sí |
| `sv_repair_store_repository` | `POST /store/repositories/{r}/repair` | sí | no |
| `sv_reload_store` | `POST /store/reload` | sí | no |
| `sv_get_addon_changelog` | `GET /store/addons/{a}`, `…/changelog` | no | no |
| `sv_get_addon_documentation` | `GET /store/addons/{a}`, `…/documentation` | no | no |
| `sv_get_addon_availability` | `GET /store/addons/{a}`, `…/availability` | no | no |
| `sv_rebuild_addon` | `GET /addons/{a}/info`, `POST /addons/{a}/rebuild` | sí | sí |

Una familia `app_store` con dos módulos (`store_repositories`,
`store_apps`), uno por tramo, para que `test_cada_familia_nombra_modulos_que_existen`
pase en cada tramo (como la 013). Un tema de guía.

**Por qué**: la 027 decidió cambiar el término en las descripciones, no en
los nombres (las tools de la 1.1.2 se llaman `sv_*_addon`); una tool nueva
`sv_rebuild_app` junto a `sv_restart_addon` sería incoherente. La 008
proponía `sv_check_addon_availability`; `sv_get_` hereda `readOnlyHint` del
prefijo sin tocar la lista exacta de `_annotations.py`, y es una lectura.
`sv_rebuild_addon` va en `app_store` y no en `supervisor` porque las tools
nuevas tienen que ir en familias de la 1.2.0 (FR-010 de la 008), y solo
reconstruye apps que vienen de la tienda (una desligada no se puede).

**Alternativas**: una sola tool `sv_get_store_info` para `GET /store`
(repositorios + catálogo): duplica `sv_list_addons(installed_only=False)`.
Una tool por repositorio (`sv_get_store_repository`): el filtro
`repository` de la lista lo cubre con una tool menos.

## R-2 — Versión concreta: no

**Decisión**: ninguna tool acepta `version`. Las rutas con `{version}` pasan
a `dedicated` apuntando a la tool sin versión, con el motivo «el Supervisor
2026.11.0 ignora `{version}`».

**Por qué**: comprobado en `api/store.py` (los manejadores no leen
`match_info["version"]`) y en `apps/manager.py` (`install(slug)` y
`update(slug, backup)` no tienen parámetro de versión; instalan
`App(...).install()` con la versión de la tienda). Un argumento `version`
haría creer al usuario que instala la 1.2.3 cuando instala la última
(principio V). La única vuelta atrás que da el Supervisor es restaurar un
backup parcial de la app (`sv_restore_backup_partial`), que la guía nombra.

**Desviación**: FR-051 de la 008 pedía «instalar o actualizar una versión
concreta». Se anota en el CHANGELOG, en la matriz de la 008 (fila CAP-082) y
en el informe.

**Alternativas**: dejar las rutas `deny` con un motivo propio. Se descarta
porque una genérica respondería «denegado» a algo que sí se puede hacer
(con la tool sin versión); `use_dedicated_tool` lleva al camino correcto.

## R-3 — Mejoras de vista previa en tools de la 1.1.2

**Decisión**:

- `sv_install_addon`: antes del token, ficha de la tienda
  (`GET /store/addons/{slug}`) y disponibilidad. Sin token:
  `addon_not_found` (404/400 de la ficha), `already_installed`
  (`installed: true`), `addon_not_available` (con el motivo). Con token: la
  vista previa gana `name`, `version_latest`, `repository`, `build` y, si el
  repositorio no es integrado, `third_party_repository: true` y el aviso.
- `sv_update_addon`: la vista previa gana `available`/`reason` y
  `changelog_excerpt` (4000 caracteres como máximo, redactado, con
  `_third_party_text`). Si algo de eso no se puede leer, se dice y el token
  se emite como antes (la vista previa de la 1.1.2 tampoco exigía nada).

Ninguna cambia su esquema de entrada ni la petición con token: la
instantánea `esquemas_1_1_2.json` sigue igual.

**Por qué**: la vista previa de instalar daba un token que el Supervisor
iba a rechazar (principio IV: la vista previa no miente). «Changelog antes
de actualizar» es justo el uso que el inventario da a esa ruta, y la 015 deja
a la 030 la vista previa de `sv_update_addon`.

**Alternativas**: rechazar `sv_update_addon` sin token si no hay
actualización (el Supervisor lanza `AppNoUpdateAvailableError`). Queda fuera:
la 008 no lo pide y cambiaría una conducta de la 1.1.2 que alguien puede
estar usando (principio IX). Se anota como posible mejora.

## R-4 — Añadir un repositorio: la cadena de suministro

**Decisión**:

1. Validación local antes de leer nada: `strip()`, la forma de
   `RE_REPOSITORY`, esquema `http`/`https` y servidor no vacío
   (`urllib.parse`); si no, `invalid_argument`. Se exige `http(s)` aunque
   `vol.Url` admita más: es lo que un repositorio de apps usa y evita
   `file://` u otros esquemas que el Supervisor no está pensado para clonar.
2. Lectura de `GET /store/repositories`; `repository_already_added` si el
   `source` coincide sin distinguir mayúsculas, o si la URL es la de
   `home-assistant/apps` o `home-assistant/addons` (el Supervisor la traduce
   a `core`).
3. Vista previa:
   - `repository`: la cadena exacta que se enviará, con la contraseña de las
     credenciales tapada (`https://usuario:***REDACTED***@servidor/…`);
   - `host` y `branch` (o `null`);
   - `warning`: código de terceros, sin revisar por Home Assistant ni por
     Hermes; sus apps podrán instalarse y, una vez instaladas, se ejecutan
     con los permisos que declaren; añadirlo no instala nada; el Supervisor
     lo clonará al confirmar y lo rechazará si no es un repositorio de apps;
   - `_third_party_text` no hace falta aún (no hay texto del repositorio).
4. Con token: `POST /store/repositories` con la URL tal cual (credenciales
   incluidas: es lo que pidió el usuario) y espera larga; después
   `GET /store/repositories` para devolver el añadido (`slug`, `name`, `url`,
   `maintainer`, con `_third_party_text`). Si no aparece, `result: ok` con
   `repository: null` y la pista de `sv_list_store_repositories`.

**Por qué**: es la vía de entrada de código ajeno. Hermes no descarga nada
para la vista previa (no sale a internet por su cuenta y el agente no puede
«revisar» un repositorio por leer su `repository.yaml`). Las credenciales de
un repositorio privado son un secreto: no van a la vista previa, a la
respuesta ni al log (principio II).

## R-5 — Quitar un repositorio

**Decisión**: lectura de `GET /store/repositories/{r}` (404 →
`repository_not_found`) y de `GET /store/addons` (apps de ese repositorio y
las instaladas). Sin token: `builtin_repository` si el `slug` es `core`,
`local`, `a0d7b954`, `5c53de3b` o `d5369777`; `repository_in_use` si alguna
app instalada tiene `repository == slug` (lista con `slug` y `name`, y la
pista de desinstalarlas con `sv_uninstall_addon`). Vista previa: el
repositorio, `apps_count`, que sus apps dejarán de poder instalarse y que se
puede volver a añadir. Token con `estado = {repo, installed_apps}`; al
confirmar se vuelve a leer y, si cambió, el token no vale.

**Por qué**: el Supervisor rechaza los dos casos; emitir un token sería
mentir. La lista de apps instaladas es lo que el usuario necesita para
decidir. Los `slug` integrados son constantes públicas del Supervisor
2026.11.0; si una versión futura añade otro, el Supervisor seguirá
rechazándolo y Hermes devolverá su error (fail-closed por el lado del
Supervisor).

## R-6 — Reparar y recargar, sin token

**Decisión**: sin confirmación, idempotentes, de mundo abierto, no
destructivas. Reparar `local` → `not_supported` antes de llamar.

**Por qué**: recargar es `git pull` de los repositorios ya añadidos y releer
las apps (no instala ni actualiza nada). Reparar clona en una carpeta
temporal y solo sustituye el clon si la descarga sale bien (`store/git.py`).
Pedir token para algo sin consecuencias acostumbra a confirmar sin leer.

## R-7 — Validar opciones en la vista previa

**Decisión**: en la vista previa de `sv_set_addon_options`, después de
mezclar, `POST /addons/{slug}/options/validate` con `json_body = finales`.

- `valid: false` → `{"error": "invalid_options", "message": …,
  "changed_paths": …}` sin token. El mensaje pasa por `redact_secrets` y,
  además, cada valor de texto que `redact_structure(finales)` taparía se
  sustituye por el marcador si aparece literal (el `humanize_error` del
  Supervisor repite el valor: «Got 'mi-clave'»).
- `valid: true` → `validation: {checked: true, valid: true, pwned: …}`.
- `pwned: true` → `warning_pwned`; `pwned: null` → `pwned_check: "failed"`.
- `HAConnectionError` → `validation: {checked: false, reason: "<error
  redactado>"}` y token.
- `finales == {}` → no se llama (el Supervisor validaría las guardadas) y
  `validation: {checked: false, reason: "empty_options"}`.

**Por qué**: FR-052 de la 008. Fail-closed cuando el Supervisor dice que no
es válido (el `POST /options` lo rechazaría igual); fail-open cuando no se
pudo validar porque la escritura vuelve a validar y la 1.1.2 ya funcionaba
así. La comprobación de contraseñas filtradas la hace el Supervisor contra
Have I Been Pwned por k-anonimato si el usuario la tiene activa; ocurre
igual al guardar.

## R-8 — Reconstruir

**Decisión**: una lectura de `GET /addons/{slug}/info` basta para los cuatro
rechazos (ver spec FR-012). `force` booleano, por defecto `false`, atado al
token. Espera larga sin `background` (la ruta no lo admite); si vence, el
error lleva la pista de que la reconstrucción puede seguir en el Supervisor
y de mirar el estado con `sv_get_addon`. Hermes: aviso
de autoprotección (no se rechaza; el Supervisor lo permite y la 1.1.2 avisa
igual en `sv_restart_addon`).

**Por qué**: el Supervisor quita contenedor e imagen antes de construir; si
falla, la app queda sin imagen. Es destructivo (interrumpe el servicio) y lo
dice la vista previa. Con `force` en una app de imagen el efecto real es
volver a descargar la imagen de la misma versión: la descripción lo dice.

## R-9 — Changelog y documentación

**Decisión**: dos lecturas (ficha + texto) para distinguir «no existe» de
«no tiene» (el Supervisor responde 200 con un mensaje en ambos casos).
Textos exactos reconocidos: «No changelog found for app {slug}!» y «No
documentation found for app {slug}!». Además, para la documentación, la
ficha trae `documentation` (si es `false`, no se pide). Recorte por trozos:
`offset` (≥ 0) y `max_chars` (1…100000, por defecto 20000) sobre el texto ya
redactado; el trozo se acorta hasta que la respuesta quepa en
`response_max_bytes`. `redact_secrets` sobre el texto completo antes de
cortar (para no partir un secreto entre dos trozos).

**Por qué**: la documentación de algunas apps pasa de 50 KB; devolverla
entera gastaría contexto (FR-021 de la 008). Redactar un texto público es
casi siempre inocuo, y una app local puede llevar cualquier cosa.

## R-10 — Errores

Convención de la 013 (su R-8): un `HAConnectionError` se devuelve como
`{"error": <mensaje redactado>}`, como hoy en `tools/addons.py`; los casos
que Hermes reconoce llevan código propio: 404 en la ficha o en el
repositorio → `addon_not_found` / `repository_not_found` con `detail`. Un
argumento inválido → `{"error": "invalid_argument", "field", "detail"}` sin
llamar (el `detail` no copia el valor); un `slug` inválido sigue dando
`invalid_identifier` (`_bad_slug`). En una escritura confirmada que falla,
el token se completa como fallido (`complete_confirmation_token(success=
False)`). La URL con credenciales se tapa también en los mensajes de error
(el Supervisor repite la URL en «Can't retrieve data from …»).

## R-11 — Pruebas

- Unitarios con un `MockHAClient` (patrón de `tests/test_tools_supervisor.py`)
  que hace de Supervisor simulado con respuestas de la forma de 2026.11.0
  (fixture `tests/fixtures/supervisor_tienda.py`, datos ficticios).
- Las cinco tools que modifican no se pueden ejecutar en el banco de Core
  (su Supervisor solo reenvía a Core): `FUERA_DEL_BANCO` con un motivo
  `_SV_TIENDA`, matriz `VM` / `pendiente` y su línea en la tanda 2 del
  procedimiento. Las cuatro de lectura no entran en la matriz (tienen
  `readOnlyHint`).
- Las genéricas: `sv_read_api` y `sv_call_api` con las rutas nuevas
  `dedicated` responden `use_dedicated_tool` sin llamar (test de tabla).
- El test de rutas del rol `manager` las incluye solo (extractor AST).
