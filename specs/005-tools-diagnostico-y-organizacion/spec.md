# Especificación: Hermes 1.1.0 — tools de diagnóstico y organización

**Directorio de la spec**: `specs/005-tools-diagnostico-y-organizacion`

**Creada**: 2026-11-14

**Estado**: Lista para implementar (specify, plan, tasks y analyze hechos; sin implementar)

**Base**: Hermes 1.0.12 (`specs/001-correcciones-1-0-12/`). Esta spec da por
hechos el código de error de Home Assistant en las excepciones
(`HAConnectionError.code`), el módulo de versión de Home Assistant
(`ha_version.py`, con `ha_at_least`) y el safety backup corregido (job por su
identificador, anotación pendiente, éxito solo con `done` y sin errores).

**Entrada**: descripción del mantenedor: «1.1.0: CRUD de plantas, etiquetas y
categorías con borrados en dos pasos y preview veraz; diagnóstico (repairs,
trazas resumidas y redactadas, `search/related`); resolución del Supervisor
(leer y descartar, nunca aplicar); estado de los backups de HA con la
contraseña de cifrado siempre redactada; retención de los safety backups de
Hermes (decisión 9) que solo borre los suyos y falle cerrada; mínimos de
versión comprobados; documentación».

Los identificadores entre corchetes remiten al informe de compatibilidad de
noviembre de 2026 (§4 «Oportunidades», grupos 2, 3 y 5) y a la decisión 9 del
mantenedor, resumidos en `docs/HOJA-DE-RUTA.md`.

## Clarificaciones

### Sesión 2026-11-14

No se ha preguntado al mantenedor: estaba ausente y había dejado decisiones
tomadas. Las dudas se resolvieron así:

- P: ¿Se pueden aplicar las sugerencias del Supervisor? → R: **no**; solo leerlas y descartarlas, con confirmación. Aplicarlas queda fuera de alcance (decisión del mantenedor).
- P: ¿Cuántos safety backups se conservan? → R: **N configurable** con la opción `safety_backup_keep` (decisión 9). Valor por defecto 3; 0 desactiva la retención. Ver Supuesto S-08.
- P: ¿Se cifran los safety backups? → R: **no en 1.1.0**; se anota en la hoja de ruta (decisión del mantenedor).
- P: ¿La poda de safety backups pide `confirmation_token`? → R: **no**; es una política del add-on que el dueño activa en su configuración, fuera del canal MCP, y solo toca artefactos de Hermes identificados sin ambigüedad. Se justifica frente al principio IV en plan.md. Ver Supuesto S-09.
- P: ¿Qué pasa si la versión de Home Assistant no se puede leer en una tool de solo lectura que exige un mínimo? → R: decide Home Assistant, y un «comando desconocido» se traduce a un error claro (mismo criterio que la spec 001 para las lecturas). Ver Supuesto S-03.
- P: ¿`ha_ignore_repair` pide confirmación? → R: **sí, cuando cambia el estado** (decisión del mantenedor); si el issue ya está como se pide, responde sin token y sin cambiar nada.

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es quien administra su Home Assistant a través de un cliente MCP
(un modelo de lenguaje) que llama a las tools de Hermes.

### Historia 1 — Organizar la casa por plantas, etiquetas y categorías (Prioridad: P1)

El agente puede asignar `floor_id` a un área y etiquetas a áreas, dispositivos
y entidades, pero no puede listar, crear, renombrar ni borrar plantas,
etiquetas ni categorías: tiene que adivinar los ids o leer `.storage`.

**Por qué esta prioridad**: es la oportunidad «A» del grupo 3 y la base de
muchas peticiones habituales («pon las luces del salón en la planta baja»,
«etiqueta los sensores de seguridad»).

**Prueba independiente**: con Home Assistant simulado, cada tool envía el
comando del registro correspondiente con los campos validados y devuelve la
entrada creada o modificada.

**Escenarios de aceptación**:

1. **Dado** cualquier instalación, **cuando** el agente pide `ha_list_floors`, `ha_list_labels` o `ha_list_categories(scope="automation")`, **entonces** recibe la lista con sus ids, nombres e iconos.
2. **Dado** un nombre nuevo, **cuando** el agente pide `ha_create_floor`, `ha_create_label` o `ha_create_category`, **entonces** se crea sin token y la respuesta trae el id generado.
3. **Dado** un color que no es de tema ni `#rrggbb`, o un `scope` de categoría fuera de `automation`, `script`, `scene` y `helpers`, **cuando** el agente crea o edita, **entonces** Hermes lo rechaza antes de llamar a Home Assistant.
4. **Dado** una planta, etiqueta o categoría existente, **cuando** el agente pide `ha_update_*` sin token, **entonces** recibe una vista previa con el estado actual y los cambios propuestos y un token; con el token, se aplica.
5. **Dado** un id que no existe, **cuando** el agente pide `ha_update_*`, **entonces** recibe `not_found` y ningún token.

---

### Historia 2 — Borrar una planta, etiqueta o categoría sabiendo qué pierde la asignación (Prioridad: P1)

Borrar una planta deja sus áreas sin planta; borrar una etiqueta la quita de
áreas, dispositivos y entidades; borrar una categoría la quita de las
automatizaciones, scripts, escenas o helpers que la tenían. Además, las
automatizaciones que usaban esa planta o etiqueta como destino dejan de
encontrar sus objetivos sin ningún aviso.

**Por qué esta prioridad**: acción destructiva; la vista previa es la única
revisión humana (principio IV).

**Prueba independiente**: la vista previa de cada borrado enumera exactamente
lo que perderá la asignación y lo que dejará de coincidir, y si no se puede
calcular, no se emite token.

**Escenarios de aceptación**:

1. **Dado** una planta con dos áreas y una automatización que la usa como destino, **cuando** el agente pide `ha_delete_floor` sin token, **entonces** la vista previa nombra las dos áreas (que quedarán sin planta) y la automatización (cuyo destino dejará de resolver), y trae un token.
2. **Dado** una etiqueta asignada a un área, dos dispositivos y tres entidades, **cuando** el agente pide `ha_delete_label` sin token, **entonces** la vista previa enumera esas asignaciones por tipo, con sus recuentos, y las automatizaciones, scripts y escenas que la referencian.
3. **Dado** una categoría del scope `automation` asignada a cuatro automatizaciones, **cuando** el agente pide `ha_delete_category` sin token, **entonces** la vista previa enumera esas cuatro entidades.
4. **Dado** que Hermes no puede leer alguno de los registros o la búsqueda de relaciones, **cuando** el agente pide un borrado sin token, **entonces** recibe `preview_unavailable` y ningún token (fail-closed).
5. **Dado** un token válido, **cuando** el agente repite el borrado con él, **entonces** se ejecuta; un token emitido para otro id o para otra tool se rechaza.

---

### Historia 3 — Ver y gestionar los avisos de Repairs (Prioridad: P2)

Home Assistant avisa en Repairs de integraciones rotas y de configuraciones que
dejarán de funcionar en una versión concreta (`breaks_in_ha_version`). El
agente no lo ve.

**Por qué esta prioridad**: diagnóstico de alto valor y bajo riesgo (grupo 2, «A»).

**Prueba independiente**: con Home Assistant simulado, `ha_list_repairs`
devuelve los issues activos resumidos y `ha_ignore_repair` cambia su estado
solo con token.

**Escenarios de aceptación**:

1. **Dado** tres issues activos, uno ignorado, **cuando** el agente pide `ha_list_repairs`, **entonces** recibe los dos no ignorados con dominio, id, gravedad, `breaks_in_ha_version`, si se pueden arreglar y su enlace de ayuda.
2. **Dado** lo mismo, **cuando** el agente pide `ha_list_repairs(include_ignored=true)`, **entonces** recibe los tres, con el ignorado marcado.
3. **Dado** un issue no ignorado, **cuando** el agente pide `ha_ignore_repair` sin token, **entonces** recibe una vista previa (qué issue, su gravedad, que se ocultará y que es reversible) y un token; con el token, el issue queda ignorado.
4. **Dado** un issue que ya está ignorado, **cuando** el agente pide ignorarlo, **entonces** recibe `unchanged` y ningún token.
5. **Dado** un issue inexistente, **cuando** el agente pide ignorarlo, **entonces** recibe `not_found` y ningún token.

---

### Historia 4 — Saber por qué una automatización no hizo lo esperado (Prioridad: P2)

«¿Por qué no saltó mi automatización?» se responde con sus trazas. Las trazas
completas pesan de unos KB a cientos de KB e incluyen estados enteros, con
atributos que pueden llevar tokens (por ejemplo, la URL de la imagen de una
cámara).

**Por qué esta prioridad**: diagnóstico de alto valor (grupo 2, «A»), con
riesgo de agotar el contexto y de filtrar secretos si se devuelve en crudo.

**Prueba independiente**: con Home Assistant simulado, `ha_list_traces`
devuelve las últimas ejecuciones resumidas y `ha_get_trace` devuelve un
resumen redactado que no supera el límite de tamaño.

**Escenarios de aceptación**:

1. **Dado** una automatización con cinco trazas, **cuando** el agente pide `ha_list_traces(domain="automation", entity_id="automation.x", limit=3)`, **entonces** recibe las tres más recientes con su `run_id`, estado, inicio, fin, último paso, disparador y error si lo hubo.
2. **Dado** una traza, **cuando** el agente pide `ha_get_trace` con el detalle por defecto, **entonces** recibe un resumen por paso (ruta, momento, resultado y error) sin la configuración completa ni las variables de cada paso.
3. **Dado** una traza cuyas variables contienen un `access_token` o una URL con `token=…`, **cuando** el agente pide `ha_get_trace(detail="full")`, **entonces** esos valores llegan redactados.
4. **Dado** una traza que, completa, supera el límite de tamaño, **cuando** el agente pide `detail="full"`, **entonces** recibe una respuesta dentro del límite, marcada como truncada y con lo que se ha omitido.
5. **Dado** un `run_id` inexistente, **cuando** el agente pide la traza, **entonces** recibe `not_found`.

---

### Historia 5 — Saber qué usa una entidad, un área o una etiqueta (Prioridad: P2)

Antes de renombrar o borrar algo, el agente quiere saber qué automatizaciones,
scripts, escenas, dispositivos o áreas lo usan.

**Por qué esta prioridad**: evita roturas silenciosas; bajo riesgo (lectura).

**Prueba independiente**: con Home Assistant simulado, `ha_search_related`
envía el tipo y el id y devuelve las relaciones agrupadas por tipo.

**Escenarios de aceptación**:

1. **Dado** una entidad usada por una automatización y una escena, **cuando** el agente pide `ha_search_related(item_type="entity", item_id=…)`, **entonces** recibe ambas agrupadas por tipo.
2. **Dado** un `item_type` que Home Assistant no admite, **cuando** el agente lo pide, **entonces** Hermes lo rechaza antes de llamar a Home Assistant y enumera los válidos.
3. **Dado** Home Assistant anterior a 2026.10, **cuando** el agente pide `include_disabled_entities=true`, **entonces** recibe un error que nombra la versión mínima, sin llamar al comando.

---

### Historia 6 — Ver los problemas que detecta el Supervisor y descartarlos (Prioridad: P2)

El Supervisor marca la instalación como *unhealthy* o *unsupported*, abre
issues (poco espacio, add-on deprecado…) y propone sugerencias (algunas
borran datos o reinician). El agente no lo ve.

**Por qué esta prioridad**: diagnóstico (grupo 2, «A»); aplicar sugerencias es
peligroso y queda fuera.

**Prueba independiente**: con un Supervisor simulado, `sv_get_resolution`
devuelve el estado resumido y los descartes piden token; ninguna tool aplica
sugerencias.

**Escenarios de aceptación**:

1. **Dado** un Supervisor con un issue, una sugerencia y un motivo de *unsupported*, **cuando** el agente pide `sv_get_resolution`, **entonces** recibe las cinco listas (`unsupported`, `unhealthy`, `issues`, `suggestions`, `checks`).
2. **Dado** un issue existente, **cuando** el agente pide `sv_dismiss_resolution_issue` sin token, **entonces** recibe una vista previa (tipo, contexto, referencia y que puede reaparecer en la siguiente comprobación) y un token; con el token, se descarta.
3. **Dado** una sugerencia existente, **cuando** el agente pide `sv_dismiss_resolution_suggestion`, **entonces** ocurre lo mismo y la vista previa deja claro que **descartar no la aplica**.
4. **Dado** cualquier instalación, **cuando** se revisan todas las tools, **entonces** ninguna aplica una sugerencia del Supervisor.

---

### Historia 7 — Ver el estado de los backups de Home Assistant sin exponer la clave de cifrado (Prioridad: P1)

Desde HA 2025.1 la integración `backup` gestiona backups automáticos con
agentes (local, NAS, nube), retención y cifrado. Su configuración devuelve **en
claro** la contraseña de cifrado de los backups automáticos.

**Por qué esta prioridad**: es útil (grupo 5, «A»), pero un fallo de redacción
expondría un secreto de larga duración (principio II), así que se trata como P1.

**Prueba independiente**: con Home Assistant simulado que devuelve una
contraseña centinela, ninguna respuesta de las tools nuevas la contiene.

**Escenarios de aceptación**:

1. **Dado** HA ≥ 2025.1, **cuando** el agente pide `ha_list_backups`, **entonces** recibe los backups (id, nombre, fecha, agentes con tamaño y si están protegidos, qué incluyen) y el estado del último backup automático, sin el identificador de la instalación.
2. **Dado** un backup, **cuando** el agente pide `ha_get_backup(backup_id)`, **entonces** recibe su detalle con la misma forma; un id inexistente da `not_found`.
3. **Dado** una configuración con contraseña de cifrado, **cuando** el agente pide `ha_get_backup_config`, **entonces** recibe la programación, la retención y los agentes, y `password_set: true` en lugar de la contraseña.
4. **Dado** HA anterior a 2025.1, **cuando** el agente pide cualquiera de las tres, **entonces** recibe un error que nombra la versión mínima, sin llamar al comando.
5. **Dado** un Home Assistant sin la integración `backup` (comando desconocido), **cuando** el agente pide cualquiera de las tres, **entonces** recibe `backup_integration_unavailable` con una explicación.

---

### Historia 8 — Que los safety backups de Hermes no llenen el disco (Prioridad: P2)

Con `safety_backup_enabled`, Hermes hace un backup completo (varios GB) antes
de escribir en `/config`, como mucho uno por ventana. La retención automática
de Home Assistant no los toca, así que se acumulan para siempre.

**Por qué esta prioridad**: llena el disco poco a poco; pero borrar backups es
lo más delicado que hace esta spec, así que la regla es «ante la duda, no se
borra».

**Prueba independiente**: con un Supervisor simulado con safety backups de
Hermes, backups del usuario y backups con nombres parecidos, tras un safety
backup automático correcto quedan los N más recientes de Hermes y ningún otro
backup se toca.

**Escenarios de aceptación**:

1. **Dado** `safety_backup_keep: 3` y cinco safety backups registrados por Hermes, **cuando** un safety backup automático termina bien, **entonces** se borran los tres más antiguos de Hermes y quedan los tres más recientes (incluido el nuevo).
2. **Dado** un backup del usuario llamado como un safety backup pero que Hermes no registró, **cuando** se aplica la retención, **entonces** no se borra ni cuenta para N.
3. **Dado** que la lista de backups no se puede leer o llega con una forma inesperada, **cuando** se aplica la retención, **entonces** no se borra nada y la escritura del fichero sigue su curso.
4. **Dado** un safety backup de Hermes que está en más de una ubicación o protegido con contraseña, **cuando** se aplica la retención, **entonces** no se borra.
5. **Dado** `safety_backup_keep: 0`, **cuando** termina un safety backup, **entonces** no se borra nada.
6. **Dado** que un borrado falla, **cuando** se aplica la retención, **entonces** se detiene ahí, lo registra en el log y la escritura sigue.

---

### Historia 9 — Documentación coherente (Prioridad: P3)

Los README, DOCS, la guía del cliente y la hoja de ruta deben reflejar las
tools nuevas y la opción nueva.

**Por qué esta prioridad**: no cambia el comportamiento, pero sin ello no se
puede publicar (principio XI).

**Prueba independiente**: el test de manifiesto confirma que la opción nueva
está declarada con su valor por defecto y el test de registro confirma que
todas las tools nuevas están registradas y bien anotadas.

**Escenarios de aceptación**:

1. **Dado** el README en inglés o en español, **cuando** el usuario busca qué puede hacer Hermes, **entonces** encuentra plantas, etiquetas y categorías, diagnóstico y backups de HA, con el número real de tools.
2. **Dado** la tabla de opciones, **cuando** el usuario busca `safety_backup_keep`, **entonces** encuentra su valor por defecto, qué borra y qué no borra nunca.

---

### Casos límite

- Un `item_id` de traza que es el `entity_id` en lugar del id de configuración: la tool acepta `entity_id` como alternativa y lo traduce; si se pasan los dos, error.
- Una traza sin `trace` o con pasos de forma inesperada: el resumen omite lo que no entiende y lo dice; nunca devuelve el objeto crudo.
- `ha_list_traces` sin `item_id` ni `entity_id`: devuelve las más recientes del dominio, con el mismo `limit`.
- Plantas, etiquetas o categorías con nombre duplicado: Home Assistant lo rechaza y Hermes devuelve su error sin reintentar.
- `ha_delete_label` de una etiqueta que no usa nadie: la vista previa dice cero asignaciones y cero referencias; el token se emite igual.
- Un issue de Repairs con `translation_placeholders` que contienen URLs con credenciales o tokens: se redactan.
- Una sugerencia del Supervisor que desaparece entre la vista previa y la confirmación: la ejecución devuelve el error del Supervisor y el token queda gastado.
- Un safety backup de Hermes cuyo identificador no se ha podido confirmar: no se borra nunca; pasados 7 días sale de la anotación de Hermes y queda como un backup más, fuera de la retención.
- Safety backups anteriores a 1.1.0 (sin registro): no se tocan; la documentación explica cómo borrarlos a mano con `sv_delete_backup`.
- Dos safety backups con la misma fecha: se ordenan por el momento en que Hermes los lanzó.
- La versión de Home Assistant es de desarrollo (`2026.12.0.dev0`): se compara por su número base (como en 1.0.12).

## Requisitos *(obligatorio)*

### Requisitos funcionales

**Plantas, etiquetas y categorías [grupo 3]**

- **FR-001**: DEBEN existir `ha_list_floors`, `ha_list_labels` y `ha_list_categories(scope)`, de solo lectura, que devuelvan las entradas de cada registro con su recuento.
- **FR-002**: DEBEN existir `ha_create_floor(name, level?, icon?, aliases?)`, `ha_create_label(name, color?, icon?, description?)` y `ha_create_category(scope, name, icon?)`, sin token (creación no destructiva), que devuelvan la entrada creada con su id.
- **FR-003**: DEBEN existir `ha_update_floor`, `ha_update_label` y `ha_update_category`, que solo editen entradas existentes (no crean) y exijan `confirmation_token` con vista previa del estado actual y de los cambios; un id inexistente devuelve `not_found` sin token, y si el registro no se puede leer, `preview_unavailable` sin token.
- **FR-004**: DEBEN existir `ha_delete_floor`, `ha_delete_label` y `ha_delete_category`, con `confirmation_token` atado a la tool y a sus argumentos.
- **FR-005**: La vista previa de `ha_delete_floor` DEBE enumerar las áreas que quedarán sin planta y las automatizaciones y scripts que usan la planta como destino (`floor_id`), separadas de lo que `search/related` solo relaciona a través de sus áreas, dispositivos o entidades (incluidas las escenas), que sigue funcionando. *(Corregido tras la revisión de 1.1.0, A-1: `search/related` de una planta incluye todo lo de sus áreas, y presentarlo como «deja de funcionar» exageraba.)*
- **FR-006**: La vista previa de `ha_delete_label` DEBE enumerar, por tipo y con recuentos, las áreas, dispositivos y entidades que perderán la etiqueta, y las automatizaciones y scripts que la usan como destino (`label_id`), separadas de las que solo la llevan o solo están relacionadas, que siguen funcionando. *(Corregido tras la revisión de 1.1.0, A-2: `search/related` de una etiqueta incluye las automatizaciones etiquetadas.)*
- **FR-007**: La vista previa de `ha_delete_category` DEBE enumerar las entidades que perderán esa categoría en su scope.
- **FR-008**: Si cualquiera de los datos que necesita una vista previa de borrado no se puede leer o llega con una forma inesperada, la tool DEBE devolver `preview_unavailable` sin emitir token (fail-closed).
- **FR-009**: Hermes DEBE validar antes de llamar a Home Assistant: `name` no vacío; `color` de etiqueta en la lista de colores de tema de HA o con forma `#rrggbb`; `scope` de categoría en `automation`, `script`, `scene` o `helpers`; `level` entero o nulo; `aliases` lista de textos.
- **FR-010**: Las listas de las vistas previas DEBEN acotarse (como máximo 50 elementos por tipo, con el recuento total y `truncated: true`) para no agotar el contexto, sin dejar de dar el recuento exacto.

**Repairs [grupo 2]**

- **FR-011**: DEBE existir `ha_list_repairs(include_ignored=false, domain?, severity?)`, de solo lectura, que devuelva por issue: dominio, `issue_id`, dominio del issue, gravedad, si se puede arreglar, `breaks_in_ha_version`, fecha de creación, si está ignorado y desde qué versión, clave de traducción, parámetros de traducción y enlace de ayuda; ordenados por gravedad.
- **FR-012**: Los parámetros de traducción de cada issue DEBEN pasar por la redacción de secretos de Hermes antes de devolverse; los datos internos del issue (`issue_data`) NO se exponen.
- **FR-013**: DEBE existir `ha_ignore_repair(domain, issue_id, ignore=true, confirmation_token?)`: si el issue no existe, `not_found` sin token; si ya está en el estado pedido, `{"result": "unchanged"}` sin token; si no, vista previa (issue, gravedad, `breaks_in_ha_version`, efecto y que es reversible con `ignore=false`) y token; con el token, cambia el estado.

**Trazas [grupo 2]**

- **FR-014**: DEBE existir `ha_list_traces(domain, item_id?, entity_id?, limit=10)` con `domain` en `automation` o `script`, de solo lectura, que devuelva las ejecuciones más recientes primero, resumidas (id de ejecución, id del elemento, estado, ejecución, inicio, fin, último paso, disparador, error y `not_triggered` si viene), con `limit` entre 1 y 50.
- **FR-015**: `ha_list_traces` y `ha_get_trace` DEBEN aceptar `entity_id` como alternativa a `item_id` y traducirlo al id que usa Home Assistant (el `unique_id` del registro de entidades); pasar los dos, o un `entity_id` de otro dominio, es un error de validación; un `entity_id` sin entrada en el registro da `not_found`.
- **FR-016**: DEBE existir `ha_get_trace(domain, item_id|entity_id, run_id, detail="summary")`. Con `summary` DEBE devolver la cabecera de la ejecución y, por paso, ruta, momento, resultado recortado, error e id de la ejecución hija, sin la configuración, las entradas de blueprint ni las variables de cada paso.
- **FR-017**: Con `detail="full"`, `ha_get_trace` DEBE añadir las variables cambiadas por paso y la configuración, ambas redactadas (claves sensibles y patrones de secretos en el texto).
- **FR-018**: Ninguna respuesta de `ha_get_trace` DEBE superar el límite de tamaño de las trazas (64 KiB o `response_max_bytes`, el menor). Al superarlo, DEBE omitir primero las variables de los últimos pasos, después la configuración y después los pasos finales, y marcar `truncated: true` con lo omitido.
- **FR-019**: Una ejecución inexistente DEBE devolver `not_found`, decidido por el código de error de Home Assistant.

**Relaciones [grupo 2]**

- **FR-020**: DEBE existir `ha_search_related(item_type, item_id, include_disabled_entities=false)`, de solo lectura, que valide `item_type` contra los tipos de Home Assistant (`area`, `automation`, `automation_blueprint`, `config_entry`, `device`, `entity`, `floor`, `group`, `integration`, `label`, `person`, `scene`, `script`, `script_blueprint`) y devuelva las relaciones agrupadas por tipo con sus recuentos, con como máximo 200 ids por tipo y `truncated` si se recorta.
- **FR-021**: `include_disabled_entities=true` DEBE exigir Home Assistant ≥ 2026.10; con una versión anterior, error `ha_version_unsupported` sin llamar al comando; con `false`, el parámetro no se envía nunca.

**Resolución del Supervisor [grupo 2]**

- **FR-022**: DEBE existir `sv_get_resolution()`, de solo lectura, que devuelva de la información de resolución del Supervisor: `unsupported`, `unhealthy`, `issues` (uuid, tipo, contexto, referencia), `suggestions` (uuid, tipo, contexto, referencia, `auto`) y `checks` (slug, activo), pasados por la redacción de estructuras.
- **FR-023**: DEBEN existir `sv_dismiss_resolution_issue(issue_uuid)` y `sv_dismiss_resolution_suggestion(suggestion_uuid)`, con `confirmation_token`; la vista previa DEBE decir qué se descarta (tipo, contexto, referencia), que puede reaparecer si la condición persiste y, en las sugerencias, que descartar **no** la aplica. Un uuid que no está en la información actual devuelve `not_found` sin token.
- **FR-024**: Ninguna tool de Hermes DEBE aplicar sugerencias del Supervisor; un test DEBE vigilarlo.
- **FR-025**: Los uuid DEBEN validarse como identificadores antes de construir la ruta del Supervisor.

**Backups de Home Assistant [grupo 5]**

- **FR-026**: DEBEN existir `ha_list_backups(limit=20)`, `ha_get_backup(backup_id)` y `ha_get_backup_config()`, de solo lectura, sobre la integración `backup` de Home Assistant.
- **FR-027**: Las tres DEBEN exigir Home Assistant ≥ 2025.1: con una versión anterior, error `ha_version_unsupported` (con la versión mínima y la actual) sin llamar al comando; con la versión desconocida, se llama y un «comando desconocido» se traduce a `backup_integration_unavailable`.
- **FR-028**: `ha_get_backup_config` NUNCA DEBE devolver la contraseña de cifrado: en su lugar, `password_set` (verdadero si hay una contraseña no vacía). Ningún otro valor bajo una clave sensible DEBE salir en claro.
- **FR-029**: Las tres tools DEBEN construir su respuesta con una lista explícita de campos permitidos (no reenviar la respuesta de Home Assistant), sin el identificador de la instalación (`instance_id`), y con los mensajes de error de los agentes recortados y redactados (secretos, IPs y hosts de URL).
- **FR-030**: `ha_list_backups` DEBE devolver los backups del más reciente al más antiguo, con `limit` entre 1 y 100, el recuento total y el estado del último backup automático intentado y completado y del siguiente programado.

**Retención de los safety backups [decisión 9]**

- **FR-031**: DEBE existir la opción `safety_backup_keep`, entera entre 0 y 50, con valor por defecto 3: número de safety backups de Hermes que se conservan; 0 desactiva la retención.
- **FR-032**: Hermes DEBE anotar en su almacenamiento persistente cada safety backup que lanza, por cualquiera de los dos caminos (automático y `sv_create_safety_backup`): nombre, job, momento y origen; y DEBE completar la anotación con el identificador (slug) del backup cuando lo confirme.
- **FR-033**: Un backup es «safety backup de Hermes» solo si se cumplen **todas** estas condiciones: su slug está confirmado en la anotación de Hermes (porque el Supervisor lo devolvió al crearlo, por la referencia del job terminado sin errores o, si nada de eso está disponible, porque es el **único** backup con exactamente el nombre anotado y fecha a menos de 10 minutos del lanzamiento); su nombre coincide con el anotado y con uno de los formatos exactos que genera Hermes; es completo; no está protegido con contraseña; y está en una sola ubicación.
- **FR-034**: Tras cada safety backup automático confirmado como correcto, Hermes DEBE leer la lista de backups del Supervisor y borrar los safety backups de Hermes que excedan los `safety_backup_keep` más recientes, sin superar 5 borrados por ejecución.
- **FR-035**: La retención DEBE fallar cerrada: si la lista no se puede leer o tiene una forma inesperada, si hay ambigüedad o incoherencia en una entrada, o si el número de candidatos no supera N, no borra nada; si un borrado falla, se detiene. Nunca bloquea la escritura en curso.
- **FR-036**: La retención NUNCA DEBE borrar ni contar un backup que no cumpla FR-033, aunque su nombre empiece por `hermes-safety-`.
- **FR-037**: Cada ejecución de la retención DEBE dejar un evento de log con los nombres borrados, los conservados y los motivos de exclusión, sin secretos.
- **FR-038**: La descripción de `sv_create_safety_backup` DEBE decir que sus backups se anotan como de Hermes y entran en la retención, que se aplica tras cada safety backup automático correcto.

**Mínimos de versión, integración y documentación**

- **FR-039**: Las comprobaciones de versión DEBEN usar el módulo de versión de Home Assistant de 1.0.12 en cada llamada (sin caché) y el error común `{"error": "ha_version_unsupported", "feature", "required", "current"}`.
- **FR-040**: Todas las tools nuevas DEBEN estar registradas y llevar anotaciones veraces: de solo lectura las de lectura (incluida `ha_search_related`), destructivas todas las que piden `confirmation_token` (`ha_update_floor`, `ha_update_label`, `ha_update_category`, `ha_ignore_repair`, `sv_dismiss_resolution_issue`, `sv_dismiss_resolution_suggestion` y los tres borrados), y no destructivas las creaciones.
- **FR-041**: `hermes_guide` DEBE explicar las tools nuevas (registros, diagnóstico, backups de HA y retención).
- **FR-042**: README.md y README.es.md DEBEN listar las capacidades nuevas con el número real de tools y documentar `safety_backup_keep`; DOCS.md DEBE mencionar la opción nueva; `docs/HOJA-DE-RUTA.md` DEBE marcar lo hecho y anotar como pendiente el cifrado de los safety backups y la aplicación de sugerencias del Supervisor; el CHANGELOG DEBE recoger los cambios bajo 1.1.0.
- **FR-043** [Principios VI, VII]: Cada tool nueva y la retención DEBEN tener tests escritos antes de su implementación, y cada uno un control negativo documentado (deshacer la guarda y ver caer el test).
- **FR-044** [Principio VIII]: Ningún fichero modificado DEBE contener datos personales ni de ninguna instalación concreta, ni identificadores de modelos de IA.

### Entidades clave

- **Planta (floor)**: `floor_id`, nombre, nivel, icono, alias. Las áreas la referencian con `floor_id`.
- **Etiqueta (label)**: `label_id`, nombre, color, icono, descripción. La llevan áreas, dispositivos y entidades.
- **Categoría**: `category_id`, nombre, icono, dentro de un `scope` (`automation`, `script`, `scene`, `helpers`). La llevan las entidades en su mapa `categories`.
- **Issue de Repairs**: dominio, `issue_id`, gravedad, `breaks_in_ha_version`, si se puede arreglar, si está ignorado.
- **Traza**: ejecución de una automatización o un script (`run_id`), con cabecera, pasos, variables y configuración.
- **Información de resolución del Supervisor**: motivos *unsupported* y *unhealthy*, issues, sugerencias y comprobaciones, cada issue y sugerencia con su uuid.
- **Backup de Home Assistant**: id, nombre, fecha, agentes (ubicación, tamaño, protegido), contenido; configuración de backups automáticos, cuya contraseña es un secreto.
- **Anotación de safety backups de Hermes**: lista de los safety backups que lanzó Hermes, con nombre, job, momento, origen y slug confirmado.

## Criterios de éxito *(obligatorio)*

### Resultados medibles

- **SC-001**: El agente puede crear, listar, renombrar y borrar plantas, etiquetas y categorías sin leer ficheros de `.storage`: 12 operaciones cubiertas, todas probadas.
- **SC-002**: En las pruebas, el 100 % de las vistas previas de borrado enumeran exactamente las asignaciones que pierde Home Assistant al ejecutar; 0 discrepancias; y el 100 % de los casos sin datos completos terminan sin token.
- **SC-003**: Ninguna respuesta de las tools nuevas contiene la contraseña centinela de la configuración de backups, el `instance_id` centinela, ni los tokens centinela sembrados en trazas e issues: 0 apariciones.
- **SC-004**: Ninguna respuesta de `ha_get_trace` supera el límite de tamaño de trazas en las pruebas, incluida una traza sintética de más de 1 MB.
- **SC-005**: En las pruebas de retención, el número de backups que no son safety backups de Hermes borrados es 0, en todos los escenarios (nombres parecidos, sin anotación, protegidos, en varias ubicaciones, lista ilegible, borrado fallido).
- **SC-006**: Tras un safety backup automático correcto con `safety_backup_keep: N`, quedan exactamente N safety backups de Hermes confirmados (o menos si no había más); si sobraban más de 5, se borran 5 en esa ejecución y el resto en las siguientes.
- **SC-007**: Con Home Assistant por debajo del mínimo, el 100 % de las llamadas que lo exigen devuelven `ha_version_unsupported` sin enviar el comando.
- **SC-008**: Cada tool nueva y la retención tienen al menos un test que falla con su guarda deshecha, y el recuento queda escrito en el commit de su bloque.
- **SC-009**: La suite completa pasa tras el bloque de integración, y una búsqueda de datos personales y de identificadores de modelos de IA en el diff da 0 coincidencias.

## Supuestos

- **S-01** (base): se implementa encima de 1.0.12. Si al implementar falta `HAConnectionError.code` o `ha_version.py`, se para y se avisa; no se reimplementan en esta spec.
- **S-02** (versiones): plantas, etiquetas, categorías, Repairs, trazas y `search/related` existen en 2024.10.0 con el mismo esquema, así que no llevan comprobación de versión. Solo la llevan `backup/*` (≥ 2025.1) e `include_disabled_entities` (≥ 2026.10).
- **S-03** (versión desconocida): en las lecturas con mínimo, si la versión no se puede leer, decide Home Assistant y Hermes traduce el código de error (`unknown_command`, `invalid_format`) a un error claro.
- **S-04** (scopes de categorías): Home Assistant no valida el `scope`; el frontend usa `automation`, `script`, `scene` y `helpers`, y Hermes se limita a esos cuatro para no crear categorías invisibles.
- **S-05** (efecto de los borrados): Home Assistant quita la planta de las áreas al borrarla; la etiqueta, de áreas, dispositivos y entidades; la categoría, de las entidades. Las automatizaciones que referencian una planta o etiqueta **no** se editan: sus destinos dejan de resolver. Que Home Assistant limpie también la etiqueta de las áreas se comprueba en su código al implementar; si no lo hiciera, la vista previa lo dirá («conservarán la referencia a una etiqueta inexistente»).
- **S-06** (texto de Repairs): no se piden las traducciones de los issues; se devuelve la clave, los parámetros y el enlace de ayuda. Pedir traducciones queda para otra spec.
- **S-07** (nombres del Supervisor): `sv_get_resolution` devuelve los tipos tal como los da la API v1 que usa Hermes (nombres legados como `deprecated_addon`), sin traducirlos.
- **S-08** (valor por defecto de la retención): 3, la propuesta de la investigación. Con `safety_backup_enabled: false` (por defecto) no hay safety backups automáticos y por tanto no se poda nada; los creados a mano con `sv_create_safety_backup` se anotan y se podan la próxima vez que termine bien un safety backup automático.
- **S-09** (sin token en la poda): la poda la activa el dueño en la configuración del add-on, se limita a los backups de Hermes identificados sin ambigüedad, nunca deja menos de N, está acotada a 5 borrados por ejecución y deja rastro en el log. Mismo precedente que `file_backup_max_per_path`, que ya poda las copias por fichero sin token.
- **S-10** (slug de un safety backup): la referencia de un job de backup del Supervisor terminado es el slug del backup. Se comprueba en el código del Supervisor al implementar; si no lo fuera, solo queda la identificación por nombre único y fecha, que es más estricta en la práctica porque exige un único candidato.
- **S-11** (formatos de nombre): Hermes genera dos formatos, `hermes-safety-AAAAMMDDTHHMMSSZ` (automático) y `hermes-safety-AAAAMMDD-HHMMSS` (`sv_create_safety_backup`); ambos se aceptan y no se unifican en esta spec.
- **S-12** (safety backups anteriores a 1.1.0): no están anotados y no se borran nunca automáticamente; la documentación explica cómo borrarlos con `sv_delete_backup`.
- **S-13** (ubicaciones): un backup en varias ubicaciones (`locations` con más de un elemento) se considera copiado por alguien y no se borra, porque borrarlo sin `location` lo quitaría de todas.
- **S-14** (alcance): quedan fuera aplicar sugerencias del Supervisor, el cifrado de los safety backups, los flujos de reparación de Repairs, `trace/contexts`, `floor_registry/reorder`, validar `labels` y `floor_id` en las tools de asignación existentes, la redacción de red en los logs (decisión 10) y el Marketplace (otra spec de 1.1.0).
- **S-15** (versión): esta spec no sube la versión: 1.1.0 junta varias specs y el número lo sube el mantenedor al publicar (principio XI). El CHANGELOG recoge los cambios bajo la entrada de 1.1.0.
- **S-16** (tamaño de trazas): 64 KiB es un límite propio, por debajo de los límites prácticos de los clientes; la estimación del tamaño real de las trazas es inferida.
