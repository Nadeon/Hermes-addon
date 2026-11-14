# Especificación: Hermes 1.1.0 — Marketplace de solo lectura

**Directorio de la spec**: `specs/004-marketplace`

**Creada**: 2026-11-14

**Estado**: Lista para implementar (encima de la 1.0.12)

**Entrada**: descripción del mantenedor: «Versión 1.1.0, Marketplace de SOLO LECTURA: tools nuevas `ha_marketplace_*` (información, lista de repositorios, detalle, actualizaciones pendientes con `pending_upgrade`, versiones publicadas, repositorios críticos o retirados); respaldo automático a `hacs/*` en HA ≤ 2026.10 con HACS instalado; `ha_hacs_*` como alias deprecados durante una o dos versiones; categorías válidas corregidas; rutas obsoletas de `fs.py` y `lovelace.py`; escritura fuera de alcance; documentación (README EN/ES, DOCS, hoja de ruta)».

Esta spec parte de la **1.0.12** (`specs/001-correcciones-1-0-12/`), que deja
tres piezas de las que depende:

- `HAConnectionError.code`, con el `code` de los errores WebSocket de Home
  Assistant (`not_found`, `unknown_command`, `not_loaded`…) (001 FR-030).
- `hermes/src/hermes/ha_version.py`, con `ha_core_version()` y `ha_at_least()`,
  que leen la versión de HA en cada llamada, sin caché (001 S-03).
- En `ha_hacs_*`, un mensaje mínimo cuando HACS está integrado en el
  Marketplace (`hacs_moved_to_marketplace` / `hacs_not_installed`), las
  categorías de HACS corregidas y `pending_upgrade` en `ha_hacs_list_updates`
  (001 FR-038, FR-039).

Los identificadores entre corchetes (R3, C5, Decisión 1…) son los de la revisión
de compatibilidad de noviembre de 2026, resumida en `docs/HOJA-DE-RUTA.md`.

## Clarificaciones

### Sesión 2026-11-14

No se ha preguntado al mantenedor: estaba ausente y había dejado decisiones
tomadas. Las dudas se resolvieron así:

- P: ¿Lectura, escritura o ambas en 1.1.0? → R: **solo lectura** (decisión 1). Instalar, actualizar, desinstalar, cambiar de versión y añadir repositorios quedan fuera; solo se documenta que actualizar lo instalado se hace con `update.install`, que Hermes ya permite con confirmación.
- P: ¿Se renombran las tools? → R: **nombres nuevos `ha_marketplace_*`**; las `ha_hacs_*` se quedan como alias deprecados durante una o dos versiones (decisión 5). Ver Supuesto S-04.
- P: `marketplace/repository/info` sale a GitHub y escribe en el storage del Marketplace (quita la marca «nuevo»). ¿Es aceptable en una tool de solo lectura? → R: **no**. El principio V dice que una tool `readOnlyHint` no modifica nada. El detalle de un repositorio se construye con comandos que solo leen y Hermes **nunca** envía `repository/info`. Ver Supuesto S-02.
- P: ¿Cómo se decide entre Marketplace y HACS? → R: por el **código de error**, en cada llamada y sin caché: primero `marketplace/*`; con `unknown_command`, el equivalente `hacs/*`; con `not_loaded`, error sin caer a HACS. La versión de HA solo se consulta para redactar el error cuando no responde ninguna de las dos. Ver Supuesto S-01.
- P: ¿Se abre `.storage/marketplace.*` a `fs_read_file`, como hoy `.storage/hacs.*`? → R: **no** en esta versión (fail-closed): no se ha verificado que no contenga secretos. Ver Supuesto S-07.

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es quien administra su Home Assistant a través de un cliente MCP
(un modelo de lenguaje) que llama a las tools de Hermes.

### Historia 1 — Ver qué tengo instalado del Marketplace y qué se puede actualizar (Prioridad: P1)

En HA ≥ 2026.11, HACS está integrado en Home Assistant como el **Marketplace**
y los comandos `hacs/*` ya no existen. El usuario pregunta «¿qué tengo
instalado del Marketplace y qué tiene actualización?». Hoy Hermes solo puede
responder que HACS se movió y remitir a las entidades `update`.

**Por qué esta prioridad**: es la funcionalidad rota en cualquier instalación al
día (R3) y la que más se usa.

**Prueba independiente**: con un Home Assistant simulado que responde a
`marketplace/*`, `ha_marketplace_info`, `ha_marketplace_list_repositories` y
`ha_marketplace_list_updates` devuelven datos, marcados con `api: "marketplace"`.

**Escenarios de aceptación**:

1. **Dado** HA ≥ 2026.11 con el Marketplace cargado, **cuando** el agente llama a `ha_marketplace_info`, **entonces** recibe la versión, las categorías activas, si hay tareas pendientes, si GitHub está conectado y si el usuario con el que se conecta Hermes aceptó el aviso de riesgos, con `api: "marketplace"`.
2. **Dado** lo mismo, **cuando** el agente llama a `ha_marketplace_list_repositories()` sin argumentos, **entonces** recibe solo los repositorios **instalados**, con un máximo de 50, con el total y si la lista está recortada.
3. **Dado** un repositorio instalado con `pending_upgrade: true` aunque sus versiones coincidan como texto (rama o commit), **cuando** el agente llama a `ha_marketplace_list_updates`, **entonces** aparece en la lista, con su `update_entity_id`.
4. **Dado** un repositorio instalado con `pending_upgrade: false` y versiones distintas como texto, **cuando** el agente llama a `ha_marketplace_list_updates`, **entonces** no aparece.
5. **Dado** HA ≥ 2026.11 sin config entry del Marketplace, **cuando** el agente llama a cualquier `ha_marketplace_*` salvo la de críticos, **entonces** recibe `marketplace_not_loaded` y Hermes **no** envía ningún comando `hacs/*`.

---

### Historia 2 — Lo mismo en HA ≤ 2026.10 con HACS (Prioridad: P1)

Quien sigue en HA ≤ 2026.10 con HACS 2.x quiere las mismas respuestas con las
mismas tools, sin saber qué API hay detrás.

**Por qué esta prioridad**: la versión mínima soportada es 2024.10; romper a
quien no ha actualizado HA sería una regresión respecto a 1.0.12.

**Prueba independiente**: con un HA simulado que responde `unknown_command` a
`marketplace/*` y datos a `hacs/*`, las mismas tools devuelven los mismos campos
con `api: "hacs"`.

**Escenarios de aceptación**:

1. **Dado** HA ≤ 2026.10 con HACS, **cuando** el agente llama a `ha_marketplace_list_repositories`, **entonces** Hermes prueba `marketplace/repositories/list`, recibe `unknown_command`, usa `hacs/repositories/list` y devuelve la lista con `api: "hacs"` y `can_install` en lugar de `can_download`.
2. **Dado** HA ≤ 2026.10 sin HACS, **cuando** el agente llama a cualquier `ha_marketplace_*`, **entonces** recibe `hacs_not_installed`, sin sugerir actualizar Hermes.
3. **Dado** HACS con la categoría `appdaemon`, **cuando** el agente filtra por `appdaemon`, **entonces** la acepta; **dado** el Marketplace, **entonces** la rechaza con `invalid_category` y la lista de categorías del Marketplace.
4. **Dado** un HACS antiguo que no devuelve `pending_upgrade`, **cuando** el agente pide las actualizaciones, **entonces** Hermes compara `installed_version` con `available_version`, como en 1.0.12.

---

### Historia 3 — Consultar un repositorio y sus versiones publicadas (Prioridad: P2)

El agente quiere saber qué versión hay instalada de un repositorio, cuál es la
última, qué versión mínima de HA pide, si es del catálogo o personalizado, qué
entidad `update` lo actualiza y qué versiones hay publicadas.

**Por qué esta prioridad**: completa la lectura; sin ella el agente no puede
proponer a qué versión actualizar.

**Prueba independiente**: `ha_marketplace_get_repository` devuelve el detalle sin
enviar `marketplace/repository/info`; `ha_marketplace_list_releases` devuelve las
versiones publicadas.

**Escenarios de aceptación**:

1. **Dado** un repositorio instalado, **cuando** el agente llama a `ha_marketplace_get_repository(id)`, **entonces** recibe sus campos y su `update_entity_id`, y Hermes no envía `marketplace/repository/info` ni ningún comando que salga a GitHub o escriba.
2. **Dado** un id que no existe, **cuando** el agente lo pide, **entonces** recibe `repository_not_found`.
3. **Dado** un repositorio, **cuando** el agente llama a `ha_marketplace_list_releases(id)`, **entonces** recibe como mucho 10 versiones, cada una con `tag`, `name`, `published_at` y `prerelease`.
4. **Dado** que GitHub limita las peticiones, **cuando** el agente pide las versiones, **entonces** recibe `github_rate_limited` con una explicación, no un error genérico.

---

### Historia 4 — Ver los repositorios críticos y los retirados del catálogo (Prioridad: P2)

El agente quiere saber si algo instalado está marcado como crítico o malicioso,
o si se retiró del catálogo, para avisar al usuario.

**Por qué esta prioridad**: es información de seguridad que el Marketplace ya
tiene y que el usuario puede no haber visto.

**Prueba independiente**: `ha_marketplace_list_critical` y
`ha_marketplace_list_removed` devuelven las listas con solo los campos
documentados.

**Escenarios de aceptación**:

1. **Dado** repositorios críticos guardados, **cuando** el agente llama a `ha_marketplace_list_critical`, **entonces** recibe `repository`, `reason`, `link` y `acknowledged` de cada uno; funciona aunque el Marketplace no tenga config entry.
2. **Dado** repositorios retirados, **cuando** el agente llama a `ha_marketplace_list_removed`, **entonces** recibe `repository`, `reason`, `link`, `removal_type` y `acknowledged`.
3. **Dado** cualquiera de las dos, **cuando** se llama, **entonces** Hermes no marca nada como visto (no envía `critical/acknowledge` ni nada parecido).

---

### Historia 5 — Seguir usando las tools `ha_hacs_*` durante la transición (Prioridad: P2)

Hay clientes y guías propias que llaman a `ha_hacs_*`. Deben seguir funcionando
una o dos versiones más, y avisar de que van a desaparecer.

**Por qué esta prioridad**: cambiar el nombre sin alias rompe a quien ya usa
Hermes; mantenerlos sin aviso los deja para siempre.

**Prueba independiente**: cada `ha_hacs_*` devuelve lo mismo que su `ha_marketplace_*`
más un campo `_deprecated`, y su descripción empieza por el aviso.

**Escenarios de aceptación**:

1. **Dado** HA ≥ 2026.11, **cuando** el agente llama a `ha_hacs_list_updates`, **entonces** recibe lo mismo que con `ha_marketplace_list_updates`, más `_deprecated` con el nombre nuevo; ya no recibe `hacs_moved_to_marketplace`.
2. **Dado** cualquier versión, **cuando** el cliente lista las tools, **entonces** la descripción de cada `ha_hacs_*` empieza diciendo que está deprecada, cuál la sustituye y en qué versión se retira.

---

### Historia 6 — Saber cómo se actualiza y tener la documentación al día (Prioridad: P3)

El usuario pregunta «actualiza esta tarjeta». Hermes no instala nada desde el
Marketplace, pero la vía oficial ya existe: la entidad `update` del repositorio
con `update.install`, que Hermes pide confirmar.

**Por qué esta prioridad**: evita que el agente busque atajos y que la
documentación siga diciendo que el Marketplace no está soportado.

**Prueba independiente**: las descripciones y la guía nombran `update.install` y
la confirmación; los README ya no dicen «todavía no la soportan».

**Escenarios de aceptación**:

1. **Dado** una actualización pendiente, **cuando** el agente lee la respuesta de `ha_marketplace_list_updates`, **entonces** encuentra `update_entity_id` y una indicación de que se actualiza con `update.install` vía `ha_call_service`, con `confirmation_token`.
2. **Dado** que el aviso de riesgos del Marketplace es por usuario, **cuando** `update.install` falla porque el usuario de Hermes no lo aceptó, **entonces** la guía explica que el humano debe hacerlo en la interfaz y que Hermes no lo acepta en su nombre.
3. **Dado** el README en inglés o en español, **cuando** se lee la fila del Marketplace, **entonces** enumera las tools nuevas y los alias deprecados, y no dice que el Marketplace no esté soportado.
4. **Dado** la descripción de `ha_create_lovelace_resource`, **cuando** se lee el ejemplo de URL, **entonces** usa `/local/community/…`.

---

### Casos límite

- `marketplace/info` responde `not_loaded`: HA ≥ 2026.11 sin config entry o con el Marketplace caído. No se cae a HACS (está bloqueado en esas versiones); el error lo dice.
- `marketplace/*` y `hacs/*` responden `unknown_command` y HA es ≥ 2026.11 (por ejemplo, modo de recuperación): `marketplace_unavailable`. Si HA es anterior o la versión no se puede leer: `hacs_not_installed`.
- Un error con otro código (`unauthorized`, `repository_not_found`, `github_rate_limited`, `unknown`…) se devuelve con su código y su mensaje; nunca se cae a HACS por un código que no sea `unknown_command`.
- El catálogo completo tiene miles de entradas: `installed_only=True` y `limit=50` por defecto; `limit` fuera de 1–500 se rechaza sin llamar a HA.
- `category` con `netdaemon` o cualquier valor desconocido: `invalid_category` sin llamar a HA. `appdaemon` y `python_script` solo valen con HACS.
- Un repositorio que el Marketplace no ha descargado nunca (`last_fetched` vacío) no aparece en la lista; `get_repository` responde `repository_not_found`. Es el comportamiento de la propia API.
- El repositorio instalado no tiene entidad `update` en el registro (deshabilitada o aún no creada): `update_entity_id: null`.
- `description`, `name` y `reason` son texto de terceros: se recortan y se marcan como no confiables.
- HA responde con una forma inesperada (no lista, no dict): error `unexpected_response`, sin datos a medias.

## Requisitos *(obligatorio)*

### Requisitos funcionales

**Detección de la API**

- **FR-001** [R3]: Cada tool de esta spec DEBE enviar primero el comando `marketplace/*` que le corresponde y, si responde bien, devolver el resultado con `api: "marketplace"`.
- **FR-002** [R3]: Si el comando `marketplace/*` falla con el código `not_loaded`, la tool DEBE devolver `{"error": "marketplace_not_loaded", …}` y NO DEBE enviar ningún comando `hacs/*`.
- **FR-003** [R3]: Si el comando `marketplace/*` falla con el código `unknown_command`, la tool DEBE enviar el equivalente `hacs/*` y, si responde bien, devolver el resultado con `api: "hacs"`.
- **FR-004** [R3]: Si los dos fallan con `unknown_command`, la tool DEBE devolver `marketplace_unavailable` cuando HA es ≥ 2026.11, y `hacs_not_installed` cuando es anterior o la versión no se puede leer. Ningún mensaje sugiere actualizar Hermes.
- **FR-005** [D1]: La decisión DEBE tomarse por el código del error, nunca por el texto, y DEBE repetirse en cada llamada, sin caché entre llamadas.
- **FR-006**: Cualquier otro error de HA DEBE devolverse como `{"error": <código de HA o "ha_error">, "detail": <mensaje>}`, sin caer a HACS.

**Tools de lectura**

- **FR-007**: `ha_marketplace_info()` DEBE devolver `api`, `version`, `categories`, `stage`, `startup`, `disabled_reason`, `has_pending_tasks`, `lovelace_mode`, `github_connected` y `warning_accepted`. Los dos últimos valen `null` con HACS. La descripción DEBE aclarar que `warning_accepted` se refiere al usuario con el que se conecta Hermes, no al humano.
- **FR-008**: `ha_marketplace_list_repositories(category=None, installed_only=True, search=None, limit=50)` DEBE devolver `{api, total, count, truncated, repositories}`, con los repositorios ordenados por `full_name` y en la forma resumida de FR-016. `search` filtra, sin distinguir mayúsculas, por `full_name`, `name` y `description`.
- **FR-009** [C5]: Las categorías válidas DEBEN ser `integration`, `plugin`, `template` y `theme` con el Marketplace, y además `appdaemon` y `python_script` con HACS. `netdaemon` no es válida en ningún caso. Una categoría que no está en ninguna de las dos listas DEBE rechazarse sin llamar a HA; una que solo vale con HACS, cuando la API resulta ser el Marketplace, DEBE rechazarse con `invalid_category` y las categorías válidas de esa API.
- **FR-010**: `limit` DEBE estar entre 1 y 500, y `search` tener como mucho 100 caracteres; si no, la tool DEBE devolver `invalid_argument` sin llamar a HA.
- **FR-011**: `ha_marketplace_get_repository(repository_id)` DEBE devolver el resumen del repositorio más su `update_entity_id`, usando solo comandos que leen. NO DEBE enviar `marketplace/repository/info` ni `hacs/repository/info`, porque salen a GitHub y escriben en el storage. Un id inexistente DEBE devolver `repository_not_found`.
- **FR-012**: `ha_marketplace_list_updates()` DEBE devolver los repositorios instalados con `pending_upgrade: true`; si un repositorio no trae `pending_upgrade` (HACS antiguo), DEBE comparar `installed_version` con `available_version`. Cada elemento DEBE incluir `update_entity_id` (o `null`) y la respuesta, una indicación de cómo se actualiza (FR-020).
- **FR-013**: `ha_marketplace_list_releases(repository_id, limit=10)` DEBE devolver como mucho `limit` (1–30) versiones con `tag`, `name`, `published_at` y `prerelease`. El código `github_rate_limited` DEBE devolverse como `{"error": "github_rate_limited", …}` con una explicación. La descripción DEBE decir que consulta GitHub y consume su límite de peticiones.
- **FR-014**: `ha_marketplace_list_critical()` DEBE devolver, de cada repositorio crítico, solo `repository`, `reason`, `link` y `acknowledged`.
- **FR-015**: `ha_marketplace_list_removed()` DEBE devolver, de cada repositorio retirado, solo `repository`, `reason`, `link`, `removal_type` y `acknowledged`.

**Seguridad y veracidad**

- **FR-016** [Principio I]: Ninguna respuesta DEBE reenviar el objeto de HA tal cual. El resumen de un repositorio DEBE contener solo `id`, `full_name`, `name`, `category`, `description`, `installed`, `installed_version`, `available_version`, `pending_upgrade`, `can_install` (de `can_download` en HACS), `custom`, `domain`, `homeassistant`, `stars`, `last_updated`, `status` y `new`. Los campos que falten DEBEN salir como `null`.
- **FR-017** [Principio I]: Son texto de terceros `name`, `description` y `reason` (y `name` de las versiones publicadas). `description` y `reason` DEBEN recortarse a 300 caracteres, y cada respuesta que contenga alguno de esos campos DEBE incluir `_third_party_text` con la lista de los que lleva y la advertencia de no seguir instrucciones que aparezcan en ellos.
- **FR-018** [Principios III, V]: Las siete `ha_marketplace_*` y sus alias DEBEN anunciarse como de solo lectura, no destructivas e idempotentes. Solo `ha_marketplace_list_releases` DEBE anunciarse como de mundo abierto (`openWorldHint`); las demás leen datos locales de HA. La clasificación DEBE hacerse por nombre exacto, no por el prefijo `ha_marketplace_`, para que una tool de escritura futura con ese prefijo no se anuncie de solo lectura por accidente.
- **FR-019** [Decisión 1]: Ninguna tool de esta spec DEBE enviar un comando que escriba o salga a GitHub salvo `repository/releases`: en particular, `repository/info`, `install`, `uninstall`, `download`, `remove`, `version`, `beta`, `refresh`, `ignore`, `repositories/add`, `repositories/remove`, `repositories/clear_new`, `critical/acknowledge`, `warning/accept` y `github/connect`.
- **FR-020** [Decisión 1]: La descripción de `ha_marketplace_list_updates` y la guía DEBEN decir que actualizar se hace con `ha_call_service("update", "install", {"entity_id": …})`, que pide `confirmation_token`, y que si HA responde que el aviso del Marketplace no está aceptado, el humano debe aceptarlo en la interfaz: Hermes nunca lo acepta en su nombre.

**Alias**

- **FR-021** [Decisión 5]: `ha_hacs_info`, `ha_hacs_list_repositories`, `ha_hacs_get_repository` y `ha_hacs_list_updates` DEBEN seguir registradas con los mismos parámetros y el mismo comportamiento que `ha_marketplace_info`, `ha_marketplace_list_repositories`, `ha_marketplace_get_repository` y `ha_marketplace_list_updates`. Su descripción DEBE empezar por `DEPRECATED`, nombrar la tool que la sustituye y la versión en que se retira, y su respuesta DEBE incluir `_deprecated`.
- **FR-022**: Las `ha_hacs_*` NO DEBEN devolver ya `hacs_moved_to_marketplace` (de 1.0.12): con el Marketplace funcionan. `hacs_not_installed` se mantiene con el significado de FR-004.

**Rutas obsoletas**

- **FR-023**: El ejemplo de URL de `ha_create_lovelace_resource` DEBE usar `/local/community/…`, la ruta de los recursos del Marketplace; puede mencionar que `/hacsfiles/…` sigue funcionando.
- **FR-024** [Principio III]: La lista de ficheros de `.storage` legibles DEBE explicar que `hacs.*` solo existe en HA ≤ 2026.10 y NO DEBE incluir `marketplace.*` en esta versión. Leer `.storage/marketplace.*` DEBE seguir bloqueado.

**Documentación**

- **FR-025** [Principio XI]: `README.md` y `README.es.md` DEBEN describir la familia Marketplace con las tools nuevas, los alias deprecados y la nota de que es de solo lectura, sin la frase «todavía no la soportan», y con el recuento de tools al día. Los dos DEBEN decir lo mismo.
- **FR-026**: `hermes/DOCS.md` DEBE explicar en un párrafo qué hace Hermes con el Marketplace (solo lectura; las actualizaciones, por las entidades `update` y con confirmación).
- **FR-027**: `docs/HOJA-DE-RUTA.md` DEBE marcar como resuelto el problema de las tools de HACS en HA ≥ 2026.11 y el de sus defectos menores, y dejar la escritura en el Marketplace en 1.2.x o posterior.
- **FR-028**: `hermes_guide` DEBE tener un tema `marketplace` con las tools, la detección automática, cómo actualizar (FR-020) y la advertencia sobre el texto de terceros; el resumen de la guía y el recuento de tools DEBEN estar al día.
- **FR-029** [Principio XI]: `hermes/CHANGELOG.md` DEBE tener una entrada en `## [1.1.0]` con las tools nuevas, los alias deprecados, el cambio de `openWorldHint` de los alias, el cambio de forma de las respuestas (sin `_disclaimer`, con `api`) y `installed_only=True` por defecto.

**Proceso**

- **FR-030** [Principios VI, VII]: Cada requisito con comportamiento DEBE tener un test de regresión escrito antes del código, y un control negativo (deshacer el cambio, ver caer el test) con el recuento escrito en el commit o en el PR.
- **FR-031** [Principio VIII]: Ningún fichero modificado DEBE contener datos personales, de ninguna instalación concreta ni identificadores de modelos de IA. Los ejemplos de repositorios usan `owner/repo` y ids ficticios.

### Entidades clave

- **API detectada**: `marketplace` o `hacs`; se decide en cada llamada a partir del código de error del primer intento.
- **Resumen de repositorio**: proyección fija de 17 campos (FR-016), igual para las dos API.
- **Actualización pendiente**: resumen recortado (id, full_name, name, category, installed_version, available_version) más `update_entity_id`.
- **Versión publicada (release)**: `tag`, `name`, `published_at`, `prerelease`.
- **Repositorio crítico**: `repository`, `reason`, `link`, `acknowledged`.
- **Repositorio retirado**: `repository`, `reason`, `link`, `removal_type`, `acknowledged`.
- **Entidad `update` del repositorio**: entrada del registro de entidades con dominio `update`, plataforma `marketplace` (o `hacs`) y `unique_id` igual al id del repositorio.

## Criterios de éxito *(obligatorio)*

### Resultados medibles

- **SC-001**: En las pruebas con HA ≥ 2026.11 simulado, las 7 tools `ha_marketplace_*` devuelven datos con `api: "marketplace"`; con HA ≤ 2026.10 y HACS simulado, las 7 devuelven los mismos campos con `api: "hacs"`.
- **SC-002**: Con `not_loaded`, el número de comandos `hacs/*` enviados es 0.
- **SC-003**: El conjunto de tipos de comando WS enviados por todas las pruebas de esta spec está contenido en la lista de comandos de lectura permitidos (FR-019); 0 excepciones.
- **SC-004**: `ha_marketplace_list_repositories()` sin argumentos sobre un catálogo simulado de 3000 repositorios devuelve como mucho 50 elementos y su respuesta ocupa menos de 50 KB.
- **SC-005**: El 100 % de las `ha_hacs_*` devuelven lo mismo que su sustituta más `_deprecated`, y su descripción empieza por `DEPRECATED`.
- **SC-006**: Las anotaciones de las 11 tools afectadas coinciden con FR-018 en el test de anotaciones.
- **SC-007**: Cada requisito con comportamiento tiene al menos un test que falla con el cambio deshecho, y el recuento queda escrito.
- **SC-008**: La suite completa pasa.
- **SC-009**: Una búsqueda de datos personales y de identificadores de modelos de IA en el diff da 0 coincidencias.

## Supuestos

- **S-01** (detección): se prueba `marketplace/*` primero y se cae a `hacs/*` solo con `unknown_command`. En HA ≤ 2026.10 eso cuesta un comando fallido por llamada, que HA registra a nivel INFO; a cambio no hay caché que pueda quedar desfasada al actualizar HA sin reiniciar Hermes (001 S-03). La versión de HA solo se pide para redactar el error final.
- **S-02** (`get_repository` sin `repository/info`): se pierde el README (`additional_info`), `issues`, `default_branch`, `selected_tag`, `releases` y `replaces_built_in`. Las versiones se obtienen con `ha_marketplace_list_releases`; el README queda fuera porque además es el vector más probable de prompt injection. `update_entity_id` se obtiene del registro de entidades, que es lo mismo que hace HA.
- **S-03** (escritura en `repository/releases`): se asume, por el código de HA 2026.11.1, que solo consulta GitHub y no escribe en el storage. Por eso es de solo lectura pero de mundo abierto.
- **S-04** (retirada de los alias): se retiran en **1.3.0** («una o dos versiones» después de 1.1.0). Si el mantenedor decide otra versión, solo cambia el texto del aviso.
- **S-05** (forma de las respuestas): los alias adoptan la forma nueva (con `api`, sin `_disclaimer`) y `installed_only=True` por defecto. Es un cambio de contrato para quien llamaba a `ha_hacs_list_repositories` sin argumentos esperando el catálogo entero; se acepta porque ese uso agotaba el contexto, y se anuncia en el CHANGELOG.
- **S-06** (tamaño): el catálogo completo cabe en un mensaje WS por debajo de `ha_ws_max_msg_size_bytes` (4 MiB por defecto), como ya ocurre hoy con `ha_hacs_list_repositories`. No se ha medido en una instalación real.
- **S-07** (`.storage/marketplace.*`): no se ha verificado que no contenga secretos; abrirlo queda para otra spec, tras inspeccionarlo en una instalación de prueba.
- **S-08** (aviso de riesgos): el usuario del Supervisor con el que se conecta Hermes normalmente no habrá aceptado el aviso, así que `update.install` vía Hermes puede fallar con `warning_not_accepted` (inferido, sin probar en vivo). Se documenta; no se automatiza la aceptación.
- **S-09** (versión): esta spec no sube la versión. La subida a 1.1.0 y `HA_CORE_LAST_TESTED_IN_HERMES` los hace la integración de 1.1.0, junto con las demás specs de esa versión; esta solo escribe su parte del CHANGELOG.
- **S-10** (alcance): quedan fuera la escritura (decisión 1), las notas de versión (`update/release_notes`), `marketplace/subscribe`, abrir `.storage/marketplace.*` y la paginación con cursor.
