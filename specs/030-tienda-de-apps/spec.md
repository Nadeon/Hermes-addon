# Especificación: Hermes 1.2.0 — tienda de apps (sub-feature 030)

**Directorio de la spec**: `specs/030-tienda-de-apps`

**Creada**: 2026-11-14

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T014 de su `tasks.md` y cubre **CAP-082** (tienda:
repositorios, recarga, changelog, documentación, disponibilidad y versión) y
**CAP-093** (reconstruir una app y validar sus opciones), es decir, FR-051 y
FR-052 de la 008. Depende de la 011 (tabla, genéricas y familias) y comparte
patrón con la 026, que depende de esta (textos de terceros).

**Entrada**: `specs/008-cobertura-total/` (spec, plan con la matriz de
trazabilidad, research CAP-082 y CAP-093 e `inventario/supervisor-rutas.tsv`),
la spec 011 (`command_table.py`, `tool_families.py`), la 014 (matriz de
pruebas y `docs/BANCO-SUPERVISOR.md`) y el código de Hermes:
`tools/addons.py` (`sv_install_addon`, `sv_update_addon`,
`sv_set_addon_options`, `_es_hermes`, `_self_warning`, `_track_job`),
`tools/marketplace.py` (`_third_party`, `_THIRD_PARTY_WARNING`),
`tools/_common.py` (sobre común y recortes), `security.py`
(`create_confirmation_token` con `estado`, `redact_secrets`,
`redact_structure`), `ha.py` (`sv_request`, `sv_request_text`),
`tools/_annotations.py` y `tools/guide.py`. Contrastado con el código del
Supervisor 2026.11.0: `supervisor/api/__init__.py` (`_register_store`),
`api/store.py`, `api/apps.py` (`options_validate`, `rebuild`),
`apps/manager.py` (`install`, `update`, `rebuild`), `apps/app.py`
(`rebuild`), `apps/model.py` (disponibilidad), `store/__init__.py`
(`add_repository`, `remove_repository`, `reload`), `store/repository.py`,
`store/git.py` (`reset`), `store/const.py` (`BuiltinRepository`) y
`validate.py` (`RE_REPOSITORY`).

## Clarificaciones

### Sesión 2026-11-14

Decisiones vinculantes del programa (ya están en la 008 y en la 011):

- CAP-082 es de prioridad **alta** y CAP-093 **media**: las dos van por
  **tools dedicadas** (decisión 1 de la 008); añadir o quitar un repositorio
  y reconstruir una app piden **confirmación en dos pasos**.
- Las tools nuevas van en una **familia nueva** de la 1.2.0 (FR-010 de la
  008); con las familias de la 1.2.0 desactivadas, la lista de tools vuelve a
  ser la de la 1.1.2.
- El changelog, la documentación y los nombres de repositorios y apps son
  **texto de terceros** y se marcan con `_third_party_text` (008, CAP-082).
- Los iconos y logos de la tienda son **clase B** (binario para la interfaz)
  y siguen `deny` (008, «Clase B»; research R-4 de la 008).
- En el banco de la 010 el Supervisor es **simulado** (solo reenvía a Core):
  las tools `sv_*` de esta sub-feature se prueban con un Supervisor simulado
  en unitarios, y las que modifican van a la matriz de la 014 como
  «VM / pendiente».

Decisiones tomadas al especificar (no había a quién preguntar; se justifican
en [research.md](research.md)):

- P: ¿Cómo se llaman las tools? → R: prefijo `sv_` y el sustantivo de las
  tools que ya existen: `addon` para una app (`sv_get_addon_changelog`,
  `sv_rebuild_addon`, como `sv_install_addon`) y `store_repository` /
  `store` para la tienda (`sv_list_store_repositories`, `sv_reload_store`,
  como el `store` de `sv_list_addons`). Las descripciones dicen «app
  (add-on)» la primera vez y «app» después, como la 027. La disponibilidad
  es `sv_get_addon_availability` (no `sv_check_…`, que proponía la 008) para
  heredar `readOnlyHint` del prefijo `sv_get_` (research R-1).
- P: ¿Una familia o dos? → R: **una**, `app_store` («desde» 1.2.0,
  desactivable), con dos módulos: `store_repositories` (repositorios y
  recarga, tramo 1) y `store_apps` (fichas, disponibilidad y reconstrucción,
  tramo 2). Un tema de guía, `app_store` (research R-1).
- P: ¿Se puede instalar o actualizar una **versión concreta**? → R: **no**. El
  Supervisor 2026.11.0 registra `POST /store/addons/{app}/install/{version}`
  y `…/update/{version}`, pero el manejador no lee `{version}`: instala o
  actualiza siempre la versión que hay en la tienda. Lo mismo `GET
  /store/addons/{app}/{version}`, que devuelve la ficha actual. Un argumento
  `version` mentiría (principio V). Esas tres rutas pasan a `dedicated`
  apuntando a la tool sin versión que hace lo mismo, con el motivo; las tools
  no ganan argumentos. Es una **desviación de FR-051 de la 008** impuesta por
  la versión de destino (research R-2).
- P: ¿Qué gana entonces CAP-082 en las tools de la 1.1.2? → R: las vistas
  previas. `sv_install_addon` comprueba antes del token si la app ya está
  instalada y si está disponible en este sistema (arquitectura, máquina y
  versión de HA); `sv_update_addon` añade a su vista previa el principio del
  changelog (texto de terceros) y la disponibilidad. Ninguna gana argumentos
  ni cambia lo que hace con el token. La 015 deja expresamente a la 030 la
  mejora de la vista previa de `sv_update_addon` (research R-3).
- P: ¿Añadir un repositorio sale a internet desde Hermes? → R: **no**. La
  vista previa no descarga nada: dice la URL exacta que se enviará (con la
  contraseña de una URL con credenciales tapada), la rama si la lleva, y
  advierte de que el código no está revisado por Home Assistant ni por Hermes
  y de que sus apps pasarán a poder instalarse. Es el Supervisor quien clona,
  al confirmar (research R-4).
- P: ¿Qué pasa al quitar un repositorio con apps instaladas? → R: el
  Supervisor 2026.11.0 lo rechaza («It's used by installed apps»). La vista
  previa lo dice **sin emitir token** (`repository_in_use`), con la lista de
  apps instaladas de ese repositorio y la pista de desinstalarlas antes con
  `sv_uninstall_addon`. Los repositorios integrados (`core`, `local` y los
  tres de URL fija) tampoco se pueden quitar (`builtin_repository`, sin
  token). El token se ata además al estado leído (`estado` de la 018)
  (research R-5).
- P: ¿Reparar y recargar piden confirmación? → R: **no**. Recargar actualiza
  los clones de la tienda; reparar vuelve a clonar un repositorio en una
  carpeta temporal y solo sustituye el clon si la descarga sale bien. Ninguna
  instala, borra datos ni para nada (research R-6).
- P: ¿Qué se valida en la vista previa de `sv_set_addon_options`? → R: las
  **opciones finales** (las actuales con los cambios encima) con `POST
  /addons/{slug}/options/validate`. Si no son válidas, **no hay token**
  (`invalid_options`, con el mensaje del Supervisor redactado). Si la
  validación no se puede hacer (error de red o de la ruta), la vista previa
  lo dice (`validation.checked: false`) y el token se emite como en la 1.1.2:
  el Supervisor vuelve a validar al guardar (research R-7).
- P: ¿Qué hace `sv_rebuild_addon` con una app de imagen? → R: el Supervisor
  solo reconstruye apps que se construyen en local; con `force=true`
  reconstruye cualquiera (en una app de imagen, vuelve a descargar la imagen).
  La vista previa lo dice y rechaza sin token lo que el Supervisor rechazaría:
  app no instalada, desligada de la tienda, con una versión distinta de la de
  la tienda, o de imagen sin `force` (research R-8).
- P: ¿Se redactan el changelog y la documentación? → R: **sí**, con
  `redact_secrets` (una app local puede llevar cualquier cosa en su DOCS), y
  la respuesta dice `secrets_redacted`. Se devuelven por trozos (`offset`,
  `max_chars`) dentro de `response_max_bytes` (research R-9).

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es el administrador de Home Assistant que gestiona sus apps
(add-ons) desde un cliente MCP.

### Historia 1 — Gestionar los repositorios de la tienda (Prioridad: P1)

Quien quiere instalar una app de un repositorio de la comunidad necesita
añadir ese repositorio, ver qué hay en la tienda, recargarla cuando el autor
publica algo y quitar lo que ya no usa, sin abrir la interfaz.

**Prueba independiente**: con un Supervisor simulado, listar, añadir (vista
previa y confirmación), quitar (vista previa, rechazo por apps instaladas y
confirmación), reparar y recargar llaman a las rutas correctas y nunca
emiten token para algo que el Supervisor rechazaría.

**Escenarios de aceptación**:

1. **Dado** una tienda con los repositorios integrados y uno de la comunidad,
   **cuando** el agente llama a `sv_list_store_repositories`, **entonces**
   recibe cada repositorio con su `slug`, nombre, URL, si es integrado,
   cuántas apps ofrece y cuáles están instaladas, con los campos de texto
   marcados como de terceros.
2. **Dado** una URL de repositorio nueva, **cuando** el agente llama a
   `sv_add_store_repository` sin token, **entonces** recibe una vista previa
   con la URL exacta que se enviará y el aviso de código no revisado, y un
   token; el Supervisor no recibe nada.
3. **Dado** ese token, **cuando** el agente repite la llamada con él,
   **entonces** Hermes envía `POST /store/repositories` con esa URL y devuelve
   el repositorio añadido.
4. **Dado** un repositorio que ya está en la tienda, una URL mal formada o
   con un esquema que no es `http`/`https`, **cuando** se pide añadirlo,
   **entonces** hay un error sin token y sin llamada de escritura.
5. **Dado** un repositorio con una app instalada, **cuando** el agente pide
   quitarlo, **entonces** recibe `repository_in_use` con la lista de apps
   instaladas y ningún token.
6. **Dado** un repositorio sin apps instaladas, **cuando** el agente lo quita
   con confirmación, **entonces** Hermes envía
   `DELETE /store/repositories/{slug}`; si entre la vista previa y la
   confirmación se instala una app suya, el token no vale.
7. **Dado** un repositorio con el clon roto, **cuando** el agente llama a
   `sv_repair_store_repository`, **entonces** Hermes pide la reparación sin
   token y devuelve el resultado.
8. **Dado** un autor que acaba de publicar, **cuando** el agente llama a
   `sv_reload_store`, **entonces** la tienda se recarga sin token.

### Historia 2 — Leer la ficha de una app antes de instalarla o actualizarla (Prioridad: P1)

Antes de instalar o actualizar, el usuario quiere saber qué cambia, cómo se
configura y si la app funciona en su sistema.

**Prueba independiente**: con un Supervisor simulado, el changelog y la
documentación llegan redactados, marcados como de terceros, por trozos, y
los textos de error que el Supervisor devuelve con un 200 no se presentan
como changelog o documentación.

**Escenarios de aceptación**:

1. **Dado** una app de la tienda, **cuando** el agente llama a
   `sv_get_addon_changelog`, **entonces** recibe el changelog de la versión
   de la tienda, con `_third_party_text`, `secrets_redacted` y, si no cabe,
   `truncated` y `next_offset`.
2. **Dado** una app sin changelog, **cuando** se pide, **entonces** recibe
   `changelog_not_found`, no el texto «No changelog found…» como si fuera el
   changelog.
3. **Dado** una app con documentación larga, **cuando** el agente llama a
   `sv_get_addon_documentation` con `offset`, **entonces** recibe el trozo
   pedido y dónde sigue.
4. **Dado** una app para otra arquitectura o que exige una versión de HA más
   nueva, **cuando** el agente llama a `sv_get_addon_availability`,
   **entonces** recibe `available: false` y el motivo del Supervisor.
5. **Dado** esa misma app, **cuando** el agente pide instalarla con
   `sv_install_addon`, **entonces** recibe `addon_not_available` con el
   motivo y ningún token.
6. **Dado** una app instalada con actualización, **cuando** el agente pide
   `sv_update_addon` sin token, **entonces** la vista previa lleva el
   principio del changelog marcado como de terceros y la disponibilidad.

### Historia 3 — Reconstruir una app y no guardar opciones inválidas (Prioridad: P2)

Quien mantiene una app local (que se construye en el propio sistema) necesita
reconstruirla tras cambiar su código; quien cambia opciones quiere saber
antes de confirmar si el Supervisor las aceptará.

**Prueba independiente**: con un Supervisor simulado, `sv_rebuild_addon`
rechaza sin token lo que el Supervisor rechazaría y, con token, llama a
`POST /addons/{slug}/rebuild` con `force`; `sv_set_addon_options` valida las
opciones finales antes de emitir el token.

**Escenarios de aceptación**:

1. **Dado** una app local instalada, **cuando** el agente llama a
   `sv_rebuild_addon` sin token, **entonces** la vista previa dice que se
   borran el contenedor y la imagen y se vuelven a construir, que las
   opciones y `/data` se conservan y que, si la construcción falla, la app
   queda sin arrancar; y emite un token.
2. **Dado** una app de imagen, **cuando** se pide reconstruirla sin `force`,
   **entonces** recibe `rebuild_not_supported` sin token; con `force=true`,
   la vista previa dice que se volverá a descargar la imagen.
3. **Dado** una app con una actualización pendiente (versión instalada
   distinta de la de la tienda), **cuando** se pide reconstruirla,
   **entonces** recibe `rebuild_version_changed` sin token.
4. **Dado** unas opciones que no cumplen el esquema de la app, **cuando** el
   agente llama a `sv_set_addon_options` sin token, **entonces** recibe
   `invalid_options` con el mensaje del Supervisor (redactado) y ningún
   token.
5. **Dado** unas opciones válidas, **cuando** se llama sin token,
   **entonces** la vista previa lleva `validation: {checked: true, valid:
   true}` y el token; si el Supervisor avisa de una contraseña filtrada
   (`pwned`), la vista previa lo dice.

### Historia 4 — Nada de lo que funciona hoy cambia (Prioridad: P1)

**Prueba independiente**: con la familia `app_store` desactivada, la lista
de tools es la de la 1.1.2; las tools de la 1.1.2 que cambian
(`sv_install_addon`, `sv_update_addon`, `sv_set_addon_options`) conservan
su esquema de entrada y lo que hacen con un token válido.

**Escenarios de aceptación**:

1. **Dado** `tool_families_disabled: [app_store]`, **cuando** arranca
   Hermes, **entonces** no se registra ninguna de las nueve tools nuevas y el
   resto es igual.
2. **Dado** un token válido de `sv_install_addon` o `sv_update_addon`,
   **cuando** se confirma, **entonces** la petición al Supervisor es la de la
   1.1.2 (`/store/addons/{slug}/install` o `/update` con `background: true`).
3. **Dado** `sv_read_api("/store/repositories")` o
   `sv_call_api("POST", "/store/reload")`, **cuando** se llaman, **entonces**
   responden `use_dedicated_tool` con la tool nueva y no llaman al
   Supervisor.

### Casos límite

- El Supervisor devuelve el changelog y la documentación con un 200 y
  `text/plain` aunque falle: si la app no existe, el texto es el mensaje de
  error; si no tiene, «No changelog found for app {slug}!». Hermes comprueba
  antes la ficha de la app en la tienda y reconoce esos textos exactos.
- Para una app instalada, el changelog y la documentación son los de la
  **versión de la tienda**, no los de la instalada; la respuesta lo dice
  (`version_latest`).
- Una URL de repositorio con credenciales (`https://usuario:clave@…`): la
  clave no aparece en la vista previa, en las respuestas ni en el log; sí se
  envía tal cual al Supervisor al confirmar (es lo que pidió el usuario).
- La URL de un repositorio se compara sin distinguir mayúsculas, como hace el
  Supervisor (el `slug` de un repositorio es el SHA-1 de la URL en
  minúsculas).
- Añadir un repositorio que el Supervisor no puede clonar o que no es un
  repositorio de apps: el Supervisor lo borra y responde con error; Hermes
  devuelve el error redactado y el token se consume como fallido.
- Quitar un repositorio que tiene apps instaladas es imposible en el
  Supervisor 2026.11.0; la app de Hermes también cuenta (si Hermes vino de
  ese repositorio, `repository_in_use` la nombra).
- Reparar el repositorio `local` no está soportado en el Supervisor
  (`StoreRepositoryLocalCannotReset`): Hermes lo rechaza antes con
  `not_supported`.
- Reconstruir el propio Hermes: la vista previa lleva el aviso de
  autoprotección (`_self_warning`); Hermes deja de responder mientras dura.
- La validación de opciones con un conjunto final vacío (`{}`): el Supervisor
  valida entonces las opciones guardadas, no las enviadas; Hermes lo dice en
  `validation` en vez de afirmar que validó el conjunto vacío.
- El mensaje de validación del Supervisor (`humanize_error`) puede repetir
  el valor rechazado («Got …»): se redacta, y cualquier valor que
  `redact_structure` tapa en las opciones finales se sustituye por el
  marcador si aparece literal en el mensaje.
- `POST /store/reload`, añadir un repositorio y reconstruir una app pueden
  tardar minutos: se llaman con la espera larga de las operaciones de apps
  (`_LONG_OP_TIMEOUT`, 300 s); si vence, el error dice que la operación puede
  seguir en el Supervisor y cómo comprobarlo.
- Un `offset` fuera del texto devuelve un trozo vacío con `truncated: false`,
  no un error.

## Requisitos *(obligatorio)*

Cada FR traza a su FR y CAP de la 008 entre paréntesis.

### Requisitos funcionales

#### Repositorios y recarga de la tienda (CAP-082, módulo `store_repositories`)

- **FR-001**: `sv_list_store_repositories(repository=None)` devuelve los
  repositorios de la tienda (`GET /store/repositories`) en el sobre común
  `{count, items, truncated}`. Cada elemento lleva `slug`, `name`, `source`,
  `url`, `maintainer`, `builtin` (si es uno de los integrados del Supervisor
  2026.11.0), `apps_count` y `installed_apps` (slugs de las apps instaladas
  de ese repositorio, calculados con `GET /store/addons`), y la respuesta
  lleva `_third_party_text` con `name`, `url` y `maintainer`. Con
  `repository` (un `slug` validado), devuelve solo ese
  (`GET /store/repositories/{repository}`) o `repository_not_found` (008
  FR-051; CAP-082).
- **FR-002**: `sv_add_store_repository(repository, confirmation_token=None)`
  añade un repositorio con confirmación en dos pasos. Antes del token:
  valida la forma (la de `RE_REPOSITORY` del Supervisor: URL sin espacios y
  `#rama` opcional, esquema `http` o `https`, con servidor), quita los
  espacios de los extremos y rechaza sin token (`invalid_argument`) lo que
  no la cumple; lee los repositorios y rechaza sin token
  (`repository_already_added`) uno que ya está (comparación sin distinguir
  mayúsculas, como el Supervisor). La vista previa lleva la URL exacta que
  se enviará (con la contraseña de las credenciales tapada), la rama si la
  hay, el servidor, `credentials_hidden` si la URL lleva una contraseña, y
  un aviso de que el código es de terceros, no está
  revisado por Home Assistant ni por Hermes, y de que sus apps pasarán a
  poder instalarse (sin instalarse nada todavía); Hermes no descarga nada
  para la vista previa. Con token válido: `POST /store/repositories` con
  `{"repository": <url>}` y la espera larga; la respuesta lleva el
  repositorio añadido (leído de nuevo) con `_third_party_text` (008 FR-051;
  CAP-082).
- **FR-003**: `sv_remove_store_repository(repository, confirmation_token=None)`
  quita un repositorio con confirmación en dos pasos. Antes del token:
  `repository_not_found` si no existe, `builtin_repository` si es integrado,
  `repository_in_use` con la lista de apps instaladas (slug y nombre) y la
  pista de `sv_uninstall_addon` si tiene alguna instalada; en los tres casos,
  sin token. La vista previa lleva el repositorio (con `_third_party_text`),
  cuántas apps ofrece y que dejarán de poder instalarse; el token se ata al
  estado leído (repositorio y apps instaladas de él). Con token válido:
  `DELETE /store/repositories/{repository}` (008 FR-051; CAP-082).
- **FR-004**: `sv_repair_store_repository(repository)` pide
  `POST /store/repositories/{repository}/repair` sin confirmación;
  `repository_not_found` si no existe y `not_supported` para `local` (el
  Supervisor no lo admite), sin llamada de escritura (008 FR-051; CAP-082).
- **FR-005**: `sv_reload_store()` pide `POST /store/reload` sin
  confirmación, con la espera larga, y devuelve `{"result": "ok"}` con la
  pista de `sv_list_addons(installed_only=false)` para ver lo nuevo (008
  FR-051; CAP-082).

#### Ficha de una app (CAP-082, módulo `store_apps`)

- **FR-006**: `sv_get_addon_changelog(slug, offset=0, max_chars=20000)`
  lee la ficha de la app en la tienda (`GET /store/addons/{slug}`; si no
  existe, `addon_not_found`) y después el changelog
  (`GET /store/addons/{slug}/changelog`, texto). Si el texto es exactamente
  «No changelog found for app {slug}!», responde `changelog_not_found`.
  Devuelve `slug`, `name`, `version_latest`, `text` (el trozo pedido, tras
  `redact_secrets`), `secrets_redacted`, `total_chars`, `offset`,
  `truncated`, `next_offset` (si sigue) y `_third_party_text` con `name` y
  `text`; el trozo se acorta para que la respuesta quepa en
  `response_max_bytes` (008 FR-051; CAP-082).
- **FR-007**: `sv_get_addon_documentation(slug, offset=0, max_chars=20000)`
  igual que FR-006 con `GET /store/addons/{slug}/documentation`; si la ficha
  dice `documentation: false` responde `documentation_not_found` sin pedir
  el texto, y reconoce también el texto exacto «No documentation found for
  app {slug}!» (008 FR-051; CAP-082).
- **FR-008**: `sv_get_addon_availability(slug)` combina la ficha de la
  tienda (`available`, `arch`, `homeassistant`, `stage`, `advanced`,
  `build`, `installed`, `version`, `version_latest`, `repository`) y
  `GET /store/addons/{slug}/availability`: `available: true` si responde
  bien; `available: false` y `reason` (el mensaje del Supervisor, redactado)
  si responde 400; `addon_not_found` si la app no está en la tienda (008
  FR-051; CAP-082).
- **FR-009**: La vista previa de `sv_install_addon` comprueba, antes de
  emitir el token, la ficha de la tienda y la disponibilidad (FR-008):
  `addon_not_found`, `already_installed` o `addon_not_available` (con el
  motivo) se devuelven sin token. Si hay token, la vista previa añade
  `name`, `version_latest`, `repository`, `build` y
  `third_party_repository: true` con el aviso de terceros cuando el
  repositorio no es integrado. Sin argumentos nuevos y con la misma
  petición al confirmar (008 FR-051; CAP-082).
- **FR-010**: La vista previa de `sv_update_addon` añade la disponibilidad
  (`available`, `reason`) y `changelog_excerpt`: los primeros 4000
  caracteres del changelog de la versión de la tienda tras `redact_secrets`,
  con `changelog_truncated` y `_third_party_text`; si el changelog no se
  puede leer, `changelog_excerpt: null` y el motivo, sin impedir el token.
  El rechazo previo sobre Hermes (009) y la petición al confirmar no cambian;
  sin argumentos nuevos (008 FR-051; CAP-082).
- **FR-011**: Ninguna tool acepta una versión concreta. Las descripciones de
  `sv_install_addon` y `sv_update_addon` dicen que instalan o actualizan a la
  versión que ofrece la tienda, y la guía explica que el Supervisor 2026.11.0
  no permite elegir otra (vuelta atrás: restaurar un backup parcial de la
  app). Desviación de FR-051 de la 008 (research R-2) (008 FR-051; CAP-082).

#### Reconstruir una app y validar opciones (CAP-093)

- **FR-012**: `sv_rebuild_addon(slug, force=False, confirmation_token=None)`
  reconstruye una app con confirmación en dos pasos. Antes del token lee
  `GET /addons/{slug}/info` y rechaza sin token: `addon_not_found` (404),
  `addon_not_installed` (el Supervisor responde con la ficha de la tienda,
  `installed: false`), `addon_not_in_store` (`detached`), `rebuild_version_changed` (versión
  instalada distinta de `version_latest`, con la pista de actualizar antes) y
  `rebuild_not_supported` (`build: false` sin `force`, con la pista de
  `force=true`). La vista previa lleva `slug`, `name`, `version`, `state`,
  `build`, `force`, qué se hará (construir en local o volver a descargar la
  imagen), que se conservan opciones y `/data`, que la app se para y vuelve a
  su estado anterior, que si falla queda sin imagen, y el aviso de
  autoprotección si es Hermes. Con token válido:
  `POST /addons/{slug}/rebuild` con `{"force": force}` y la espera larga
  (008 FR-052; CAP-093).
- **FR-013**: La vista previa de `sv_set_addon_options` valida las opciones
  finales con `POST /addons/{slug}/options/validate` (cuerpo: las opciones,
  sin envolver) antes de emitir el token. `valid: false` → `invalid_options`
  sin token, con `message` redactado (FR-018) y las rutas cambiadas; `valid:
  true` → `validation: {checked: true, valid: true}` en la vista previa;
  `pwned: true` → aviso en la vista previa; `pwned: null` → que no se pudo
  comprobar; error al validar → `validation: {checked: false, reason}` y
  token como en la 1.1.2; opciones finales vacías → `validation: {checked:
  false, reason: "empty_options"}`. La confirmación no cambia (008 FR-052;
  CAP-093).

#### Tabla de clasificación (CAP-082, CAP-093)

- **FR-014**: Las 15 entradas «pendiente de tool dedicada (spec 030)» de
  `command_table.py` pasan a `dedicated` con su tool, su familia y su CAP
  (data-model): 11 a las tools nuevas; `POST
  /addons/{app}/options/validate` a `sv_set_addon_options`; `POST
  /store/addons/{app}/install/{version}`, `…/update/{version}` y `GET
  /store/addons/{app}/{version}` a `sv_install_addon`, `sv_update_addon` y
  `sv_get_addon` con el motivo «el Supervisor 2026.11.0 ignora `{version}`».
  `GET /store` a `sv_list_store_repositories` («repositorios; las apps, con
  `sv_list_addons`»). Iconos, logos y alias legados siguen `deny`. Regenerar
  la tabla con `scripts/inventario/generar_tabla.py` no cambia nada; ninguna
  entrada queda con «spec 030» (008 FR-051, FR-052; CAP-082, CAP-093).

#### Convenciones, familia, guía, banco y documentación

- **FR-015**: Las nueve tools nuevas van en la familia `app_store` (1.2.0,
  desactivable) con los módulos `store_repositories` y `store_apps`; con la
  familia desactivada no se registran y las entradas `dedicated` que apuntan
  a ellas responden como las de cualquier familia desactivada en las
  genéricas (008 FR-010, FR-012).
- **FR-016**: Anotaciones honestas (contracts/tools.md): las cuatro de
  lectura con `readOnlyHint`; `sv_add_store_repository`,
  `sv_remove_store_repository` y `sv_rebuild_addon`, destructivas (piden
  token); `sv_add_store_repository`, `sv_repair_store_repository`,
  `sv_reload_store` y `sv_rebuild_addon`, de mundo abierto (provocan
  descargas); todas idempotentes. Las anotaciones de las tools de la 1.1.2 no
  cambian (008 FR-018, FR-020).
- **FR-017**: Límite de respuesta: listas con el sobre común y
  `ajustar_lista_a_bytes`; textos por trozos (FR-006, FR-007); ninguna
  respuesta supera `response_max_bytes` (008 FR-018).
- **FR-018**: Redacción: el changelog, la documentación, los motivos de
  disponibilidad, los mensajes de validación y los errores del Supervisor
  pasan por `redact_secrets`; la contraseña de una URL con credenciales se
  tapa en vista previa, respuestas (`source`, `url`) y errores; el evento de
  log `app_store_action` lleva `tool`, `outcome`, el `slug` del repositorio
  o de la app y bytes o recuentos, nunca la URL completa, textos de la app ni
  opciones (008 FR-019).
- **FR-019**: Textos de terceros con el formato y el aviso de
  `tools/marketplace.py` (`_third_party_text: {fields, warning}`), en todas
  las respuestas y vistas previas que llevan nombre de repositorio o app,
  `maintainer`, `url`, changelog o documentación (008 CAP-082).
- **FR-020**: Guía: tema `app_store` (repositorios, recarga, fichas,
  disponibilidad, reconstrucción, por qué no hay versión concreta, el aviso
  de terceros) con alias; el tema `supervisor` remite a él y menciona la
  validación de opciones y las vistas previas nuevas de instalar y
  actualizar; el índice lo nombra (008 FR-011, FR-018).
- **FR-021**: Las descripciones dicen «app (add-on)» la primera vez y «app»
  después, como la 027; los nombres siguen el prefijo `sv_` (decisión
  inicial; 008 FR-018).
- **FR-022**: Banco y matriz: las cinco tools que modifican
  (`sv_add_store_repository`, `sv_remove_store_repository`,
  `sv_repair_store_repository`, `sv_reload_store`, `sv_rebuild_addon`) entran
  en `FUERA_DEL_BANCO` (`tests/banco/cobertura_escrituras.py`) con un motivo
  de tienda, en la matriz de la 014 de `docs/HOJA-DE-RUTA.md` como `VM` /
  `pendiente`, y en la sección «Tools nuevas del programa» de
  `docs/BANCO-SUPERVISOR.md` con su pauta (008 FR-016).
- **FR-023**: Documentación en el mismo cambio: sección «Tienda de apps» en
  `## [1.2.0]` de `hermes/CHANGELOG.md` (con la desviación de la versión
  concreta); estado de la 030 en la tabla del programa de
  `docs/HOJA-DE-RUTA.md`; `hermes/DOCS.md` con la familia en la lista de
  `tool_families_disabled`; `README.md` y `README.es.md` sincronizados
  (recuento de tools, familia); `SECURITY.md`, una viñeta en «Defence in
  depth» sobre añadir repositorios de la tienda (confirmación, URL exacta,
  credenciales tapadas, texto de terceros); filas CAP-082 y CAP-093 de la
  matriz de `specs/008-cobertura-total/plan.md` con tools y tests (008
  FR-022, FR-023).

### Entidades clave

- **Repositorio de la tienda**: `slug`, `name`, `source` (lo que se añadió),
  `url` (la que declara el repositorio), `maintainer`, `builtin`,
  `apps_count`, `installed_apps`.
- **Ficha de una app en la tienda**: la de `GET /store/addons/{slug}`
  (`name`, `available`, `arch`, `homeassistant`, `build`, `installed`,
  `version`, `version_latest`, `repository`, `documentation`, `stage`,
  `advanced`).
- **Trozo de texto de terceros**: `text`, `offset`, `total_chars`,
  `truncated`, `next_offset`, `secrets_redacted`, `_third_party_text`.
- **Validación de opciones**: `checked`, `valid`, `message`, `pwned`,
  `reason`.
- **Entrada de la tabla**: la de la 011; cambian categoría, motivo, familia y
  tool (data-model).

## Fuera de alcance

- Instalar, actualizar o leer una **versión concreta** (el Supervisor
  2026.11.0 no lo permite; FR-011).
- Iconos y logos de las apps (clase B, binario).
- Los alias legados `/addons/reload`, `/addons/{app}/{install,update,
  changelog,documentation,icon,logo}` (clase B) y la API `/v2`
  (`/store/apps/*`).
- Actualizaciones de Core, OS, Supervisor y entidades `update` (015); la
  opción `backup` de `sv_update_addon` (no la pide la 008).
- Escritura en el Marketplace de Core (026) y HACS.
- Seguridad de una app (`/addons/{app}/security`, CAP-091, 022) y
  `stdin` (clase D).
- La prueba en vivo contra un Supervisor real (VM de la 014 y cierre).

## Supuestos

- **S-01**: La 011 completa y la 014 (matriz y procedimiento) están
  integradas en la rama (lo están en `feat/cobertura-total` en `02beafc`).
- **S-02**: Las formas de respuesta del Supervisor simulado salen del código
  del Supervisor 2026.11.0 leído (no de una instalación real) y usan datos
  ficticios (`https://example.com/repo-ficticio`, `<slug>`, `abcd1234`).
- **S-03**: Hermes llama a la API v1 del Supervisor (`/store/addons/...`).
- **S-04**: La 027 cambia las descripciones de `tools/addons.py` («app
  (add-on)»); al integrar, las descripciones de las tres tools que toca esta
  sub-feature combinan los dos cambios (riesgo de fusión anotado en el plan).
- **S-05**: Si al integrar la 015 ya ha movido el formato de
  `_third_party_text` a un módulo común, se usa desde ahí; si no, se importa
  de `tools/marketplace.py`.

## Criterios de éxito *(obligatorio)*

- **SC-001**: Las nueve tools nuevas están registradas con la configuración
  por defecto, con las anotaciones de contracts/tools.md, y ninguna con
  `app_store` desactivada.
- **SC-002**: Las 15 entradas de FR-014 son `dedicated` y apuntan a una tool
  registrada; ninguna entrada queda «pendiente de tool dedicada (spec
  030)»; regenerar la tabla no cambia nada.
- **SC-003**: En el 100 % de los casos probados que el Supervisor rechazaría
  (repositorio ya añadido, integrado, en uso o inexistente; app no
  disponible, ya instalada, no instalada, desligada, con versión cambiada o
  de imagen sin `force`; opciones inválidas) no se emite token ni hay
  llamada de escritura.
- **SC-004**: Ningún centinela de secreto (en el changelog, la
  documentación, la URL con credenciales, el mensaje de validación o un
  error) aparece en respuestas, vistas previas ni log.
- **SC-005**: Con las familias de la 1.2.0 desactivadas, la lista de tools
  es la de la 1.1.2 con las mismas anotaciones y los mismos esquemas de
  entrada; con un token válido, `sv_install_addon`, `sv_update_addon` y
  `sv_set_addon_options` hacen la misma petición que en la 1.1.2.
- **SC-006**: La suite pasa en el CI de Linux al final de cada tramo, con
  los mismos 6 fallos conocidos de Windows en local y ninguno más; cada tramo
  deja anotado su control negativo con recuentos.
- **SC-007**: Las cinco tools que modifican tienen fila `VM` / `pendiente` en
  la matriz de la 014 y línea en el procedimiento; la hoja de ruta lista la
  prueba en vivo como pendiente.
