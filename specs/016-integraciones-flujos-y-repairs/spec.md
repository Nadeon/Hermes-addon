# Especificación: Hermes 1.2.0 — integraciones: flujos y Repairs (sub-feature 016)

**Directorio de la spec**: `specs/016-integraciones-flujos-y-repairs`

**Creada**: 2026-11-14

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T010 de su `tasks.md` y cubre **CAP-044, CAP-045,
CAP-048, CAP-036 y CAP-037** (FR-053…FR-057 de la 008), más los transversales
que le tocan (FR-010…FR-012, FR-015, FR-018…FR-021 y FR-023 de la 008). Ola 2,
tamaño L, 3 tramos.

**Entrada**: `specs/008-cobertura-total/` (spec, plan con la matriz de
trazabilidad, research CAP-036, CAP-037, CAP-044, CAP-045 y CAP-048 e
`inventario/core-ws.tsv`), la sub-feature 011 (tabla `command_table.py`,
`command_policy.py`, `tool_families.py`, generador
`scripts/inventario/generar_tabla.py`), el banco de la 010 y la regla de
inventario de escrituras de la 028, el código de Hermes
(`tools/config_entry_flows.py`, `tools/config_entries.py`, `tools/repairs.py`,
`security.py`, `tools/_annotations.py`, `tools/_common.py`, `tools/guide.py`) y
el código de Home Assistant Core 2026.11.1 (`components/config/config_entries.py`,
`config_entries.py`, `data_entry_flow.py`, `helpers/data_entry_flow.py`,
`components/repairs/`, `helpers/translation.py`, `components/frontend/`,
`loader.py`, `helpers/device_registry.py`, `helpers/entity_registry.py` y
`components/kitchen_sink/` como ejemplo), leídos sin ejecutar nada.

**Fuera de esta sub-feature** (otras del programa): diagnósticos de
integraciones, log y notificaciones (012); blueprints y automatizaciones de
dispositivo (017); credenciales de aplicación OAuth (024, por la tabla); los
comandos propios de cada integración (025).

## Clarificaciones

### Sesión 2026-11-14

Decisiones vinculantes de la 008 (no se discuten aquí): tools dedicadas para
CAP-044, CAP-045 y CAP-048 (vía D); CAP-036 es un cambio de las tools de
Repairs existentes (vía X) y CAP-037 solo guía (vía M); confirmación al
desactivar el sondeo o las entidades nuevas de una entrada, al borrar una
subentry y en el paso que aplica un arreglo de Repairs; las tools nuevas en
familias nuevas; prueba en el banco de Core.

Decisiones tomadas al especificar (no había a quién preguntar; se justifican
en [research.md](research.md)):

- P: ¿`ha_list_flow_handlers`, como propone la 008? → R: **no se puede**: ese
  nombre lo retiró la 1.1.x porque prometía el catálogo de integraciones y
  devolvía las ya configuradas, y un test (`test_flow_handlers_tool_renamed_to_what_it_does`)
  impide que vuelva. La tool nueva se llama **`ha_list_config_flow_domains`**:
  lista los dominios que se pueden configurar con un flujo (integraciones y
  helpers), con filtro opcional por tipo. La docstring de
  `ha_list_configured_domains` deja de decir que «no existe» esa lista
  (principio V) (research R-2).
- P: ¿Qué pide token en `ha_update_config_entry`? → R: solo **pasar a `true`**
  `pref_disable_polling` o `pref_disable_new_entities`. Cambiar el título o
  volver a activar el sondeo o las entidades nuevas va sin token. Si nada
  cambia, `unchanged` sin llamar a HA. La tool se anuncia destructiva porque
  puede pedir token (invariante «pide token ⇔ destructiva») (research R-3).
- P: ¿Ignorar un descubrimiento pide token? → R: **no** (la 008 no lo pide):
  es reversible borrando la entrada `ignore` que crea HA. Antes de llamar,
  Hermes comprueba que el flujo está entre los descubiertos y tiene
  `unique_id`; si no, `not_found` o `cannot_ignore` sin llamar a HA (research
  R-1).
- P: ¿Qué paso de un flujo de reparación «aplica el arreglo»? → R: HA no lo
  dice por adelantado: cualquier envío de un paso puede terminar el flujo y
  aplicar el arreglo. Por eso **todo envío de un paso** (`ha_continue_repair_fix`)
  va en dos pasos, con una vista previa que lo explica. Abrir el flujo
  (`ha_start_repair_fix`) no pide token: en HA solo muestra el primer paso; la
  excepción conocida (el flujo de los avisos del Supervisor sin sugerencias,
  que termina al abrirse y retira el aviso) se dice en la descripción y en la
  respuesta (`finished_on_start`) (research R-5).
- P: ¿Cómo sabe la vista previa de un paso a qué aviso pertenece el flujo? → R:
  la API de HA no lo devuelve (`GET /api/repairs/issues/fix/{flow_id}` no trae
  el contexto). `ha_continue_repair_fix` recibe `domain` e `issue_id` además de
  `flow_id`; Hermes comprueba que el flujo es de ese dominio y que el aviso
  existe y es reparable, y la vista previa dice que la relación aviso–flujo la
  afirma quien llama (research R-5).
- P: ¿Reconfigurar una entrada o editar una subentry por su flujo pide token?
  → R: **no**, igual que los flujos de configuración y de opciones de la 1.1.2
  y como dice la 008 (que solo pide token al borrar una subentry). Se anota
  como duda para el final (D-2).
- P: ¿En qué idioma salen los textos traducidos de Repairs? → R: en el idioma
  configurado en HA (`get_config` → `language`), con el inglés como respaldo de
  HA para las claves que falten. **Sin argumento nuevo** en `ha_list_repairs`
  ni en `ha_ignore_repair`: sus esquemas quedan como en la 1.1.2 (FR-020 de la
  008). Si las traducciones no se pueden leer, los avisos salen igual, con
  `title`/`description` nulos y `translations_unavailable: true` (research R-6).
- P: ¿Familias? → R: dos nuevas, `integration_flows` (descubiertas,
  preferencias, subentries y reconfigure) y `repair_flows` (flujos de
  reparación), cada una con su tema de la guía. Las traducciones de CAP-036 son
  un cambio de `ha_list_repairs` y `ha_ignore_repair`, que siguen en
  `diagnostics` (research R-8).
- P: ¿Cómo se prueba en el banco sin red ni hardware? → R: con una integración
  de prueba propia (`banco_flujos`) en `tests/banco/ha_config/custom_components/`
  que, al cargar, abre un flujo de descubrimiento con `unique_id` y crea
  avisos reparables, y que admite reconfigure y un tipo de subentry. Es
  configuración del banco, no código de producto (research R-9).

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es el administrador de Home Assistant que trabaja desde un cliente
MCP.

### Historia 1 — Atender lo que HA ha descubierto (Prioridad: P1)

Quien ve en la interfaz «Descubierto» quiere que el agente le diga qué
dispositivos o servicios ha encontrado HA y, según el caso, configurarlos o
ignorarlos para siempre.

**Prueba independiente**: con HA simulado que devuelve flujos en curso de
varias fuentes, `ha_list_discovered_integrations` lista solo los descubiertos
con su dominio, fuente y nombre; `ha_ignore_discovery` comprueba el flujo y
envía un solo `config_entries/ignore_flow`.

**Escenarios de aceptación**:

1. **Dado** flujos en curso de descubrimiento (zeroconf, dhcp, hassio…) y de
   reautenticación, **cuando** el agente llama a
   `ha_list_discovered_integrations`, **entonces** recibe cada uno con
   `flow_id`, `domain`, `source`, `step_id`, el nombre que HA enseña y si se
   puede ignorar (tiene `unique_id`).
2. **Dado** un descubierto con `unique_id`, **cuando** pide
   `ha_ignore_discovery(flow_id)`, **entonces** HA crea su entrada ignorada y
   el descubrimiento deja de aparecer; la respuesta dice cómo deshacerlo.
3. **Dado** un flujo de reautenticación o sin `unique_id`, **cuando** pide
   ignorarlo, **entonces** recibe `cannot_ignore` sin que HA reciba nada.
4. **Dado** que quiere configurar el descubierto, **cuando** sigue la guía,
   **entonces** continúa el flujo con `ha_continue_config_entry_flow` y su
   `flow_id`.

### Historia 2 — Ajustar una integración sin reinstalarla (Prioridad: P1)

Quien tiene una integración que sondea demasiado, que crea entidades que no
quiere o cuya IP ha cambiado quiere cambiar su título y sus preferencias, o
reconfigurarla, sabiendo qué va a pasar.

**Prueba independiente**: con HA simulado, `ha_update_config_entry` sin token
y desactivando el sondeo devuelve una vista previa con el estado actual, el
nuevo y el efecto (recarga), y no envía nada; con el token, envía un solo
`config_entries/update`.

**Escenarios de aceptación**:

1. **Dado** una entrada, **cuando** cambia solo su título, **entonces** HA lo
   aplica sin token y la respuesta trae la entrada actualizada.
2. **Dado** una entrada cargada con sondeo, **cuando** pide
   `pref_disable_polling=true` sin token, **entonces** recibe una vista previa
   que dice que HA recargará la integración y que sus entidades dejarán de
   actualizarse solas, y un token; con el token, el cambio se aplica y la
   respuesta trae `require_restart`.
3. **Dado** `pref_disable_new_entities=true`, **entonces** la vista previa dice
   que lo que la integración añada a partir de ahora entrará deshabilitado.
4. **Dado** valores iguales a los actuales, **entonces** `unchanged` sin token
   ni llamada.
5. **Dado** una integración que admite reconfigure, **cuando** pide
   `ha_start_reconfigure_flow(entry_id)`, **entonces** recibe el primer paso
   del flujo y lo sigue con `ha_continue_config_entry_flow`; si no lo admite,
   `reconfigure_not_supported` sin abrir nada.
6. **Dado** `ha_list_config_flow_domains(type="helper")`, **entonces** recibe
   los dominios de helpers que se crean por flujo (por ejemplo, `template`,
   `group`, `utility_meter`).

### Historia 3 — Gestionar las subentries de una integración (Prioridad: P1)

Quien usa integraciones con subentries (un agente de conversación por modelo,
un sensor por parámetro…) quiere verlas, añadir una, cambiarla, renombrarla y
borrarla sabiendo qué entidades y dispositivos se llevan por delante.

**Prueba independiente**: con HA simulado, `ha_delete_subentry` sin token
devuelve una vista previa con la subentry, sus entidades y sus dispositivos, y
no envía nada; con el token, envía un solo `config_entries/subentries/delete`.

**Escenarios de aceptación**:

1. **Dado** una entrada con subentries, **cuando** pide
   `ha_list_config_subentries(entry_id)`, **entonces** recibe cada subentry con
   su id, tipo, título y `unique_id`, y los tipos que la entrada admite crear.
2. **Dado** un tipo admitido, **cuando** pide
   `ha_start_subentry_flow(entry_id, subentry_type)`, **entonces** recibe el
   formulario y lo completa con `ha_continue_subentry_flow`; al terminar, la
   subentry existe. Con `subentry_id`, el mismo flujo la reconfigura.
3. **Dado** un tipo que la entrada no admite, **entonces**
   `subentry_type_not_supported` con los tipos admitidos, sin abrir nada.
4. **Dado** una subentry, **cuando** pide `ha_update_subentry(…, title=…)`,
   **entonces** cambia su título.
5. **Dado** una subentry con entidades y dispositivos, **cuando** pide
   borrarla sin token, **entonces** la vista previa los enumera y dice que se
   borran; con el token, la subentry desaparece.
6. **Dado** un flujo de subentry abierto que ya no quiere, **cuando** pide
   `ha_abort_subentry_flow`, **entonces** el flujo se cierra.

### Historia 4 — Arreglar lo que señala Repairs (Prioridad: P2)

Quien tiene avisos reparables en el panel Reparaciones quiere entender cada
uno y aplicar el arreglo que HA ofrece, viendo antes qué se va a enviar.

**Prueba independiente**: con HA simulado, `ha_continue_repair_fix` sin token
devuelve una vista previa con el aviso, el paso actual y lo que se envía, y no
hace el POST; con el token, hace un solo POST al flujo.

**Escenarios de aceptación**:

1. **Dado** un aviso, **cuando** pide `ha_get_repair(domain, issue_id)`,
   **entonces** recibe su resumen, el título y la descripción traducidos, sus
   datos internos redactados y si es reparable.
2. **Dado** un aviso reparable, **cuando** pide `ha_start_repair_fix`,
   **entonces** recibe el primer paso con su texto traducido; si no es
   reparable, `not_fixable` sin abrir nada.
3. **Dado** el flujo abierto, **cuando** envía un paso sin token,
   **entonces** la vista previa dice qué aviso, qué paso, qué datos se envían
   (redactados) y que el envío puede aplicar el arreglo; con el token, se
   envía, y si el flujo termina la respuesta dice si el aviso sigue o ya no.
4. **Dado** un flujo que no quiere terminar, **cuando** pide
   `ha_abort_repair_fix`, **entonces** se cierra sin cambiar nada.
5. **Dado** un flujo que pide interacción externa, **entonces** Hermes lo
   aborta y responde `non_automatable`, como en los flujos de configuración.

### Historia 5 — Leer los avisos como en la interfaz (Prioridad: P2)

Quien lista los avisos quiere el texto que ve en la interfaz, no solo una
clave de traducción.

**Prueba independiente**: con HA simulado que devuelve traducciones,
`ha_list_repairs` añade `title` y `description` a cada aviso con los
marcadores sustituidos y redactados; si la traducción falla, la lista sale
igual con `translations_unavailable`.

**Escenarios de aceptación**:

1. **Dado** avisos de dos integraciones, **cuando** los lista, **entonces**
   cada aviso trae `title` y `description` en el idioma de HA, con los
   marcadores sustituidos.
2. **Dado** un marcador con un secreto, **entonces** el texto sale con el
   secreto tapado.
3. **Dado** que HA no devuelve traducciones, **entonces** la lista sale con
   los mismos campos de la 1.1.2 y `title`/`description` nulos.
4. **Dado** `ha_ignore_repair` sin token, **entonces** su vista previa trae el
   título traducido del aviso.

### Historia 6 — Crear helpers por config entry (Prioridad: P3)

Quien quiere un helper de plantilla, un grupo o un contador de consumo quiere
que el agente sepa que se crean con los flujos existentes.

**Prueba independiente**: test de la guía.

**Escenarios de aceptación**:

1. **Dado** `hermes_guide("helpers")`, **entonces** explica cómo listar los
   helpers por flujo, crear uno con `ha_start_config_entry_flow`, editarlo con
   los flujos de opciones y listarlos con `ha_list_config_entries(type_filter="helper")`.

### Historia 7 — Nada se rompe ni se salta una protección (Prioridad: P1)

Quien usa Hermes hoy quiere que estas tools no cambien nada de lo que ya
funciona ni abran un camino alrededor de la tabla.

**Prueba independiente**: tests de registro, de la tabla y de anotaciones.

**Escenarios de aceptación**:

1. **Dado** la configuración por defecto, **entonces** las tools de antes
   siguen con los mismos nombres, anotaciones y argumentos, y aparecen las 15
   nuevas en `integration_flows` y `repair_flows`.
2. **Dado** `tool_families_disabled: [integration_flows, repair_flows]`,
   **entonces** las 15 no se registran y sus comandos siguen `dedicated` en la
   tabla (la genérica los rechaza con `family_disabled`).
3. **Dado** la genérica de escritura con `config_entries/subentries/delete`,
   **entonces** recibe `use_dedicated_tool` con `ha_delete_subentry`.

### Casos límite

- Entrada, subentry, flujo o aviso inexistente: `not_found` sin token y sin la
  llamada que modifica.
- `ignore_flow` sobre un flujo que dejó de existir entre la lectura y la
  llamada: HA responde `not_found`; la tool lo devuelve igual.
- `config_entries/subentries/update` con una entrada inexistente: HA 2026.11.1
  responde el error con un id de mensaje equivocado (research R-4); Hermes
  comprueba antes que la entrada existe y no depende de esa respuesta.
- Desactivar el sondeo en una entrada no cargada: HA no recarga; la vista
  previa lo dice según el estado leído.
- Subentry cuya entrada no tiene entidades ni dispositivos vinculados: la vista
  previa dice «ninguno» en lugar de omitir el campo.
- Borrar una subentry de una integración que recarga al cambiar sus subentries
  (por ejemplo, `kitchen_sink`): la vista previa lo avisa de forma genérica
  («la integración puede recargarse»), sin inventar si lo hará.
- Flujo de reparación que termina en el primer paso (`create_entry` o `abort`
  al abrir): `ha_start_repair_fix` lo dice con `finished_on_start` y, si es
  `create_entry`, si el aviso sigue.
- Paso de reparación rechazado por el esquema (HTTP 400 con `errors`): la
  tool devuelve los errores; el token queda consumido con fallo y hay que
  pedir otra vista previa.
- Flujo de reparación de otro dominio que el indicado: `flow_mismatch` sin
  token.
- Varios avisos con la misma clave de traducción en dominios distintos: la
  traducción se busca por el dominio del aviso.
- Traducción con un marcador que el aviso no da: se deja tal cual (`{name}`),
  como hace la interfaz.
- Descripción traducida muy larga en una lista: se recorta con
  `description_truncated`; `ha_get_repair` la da entera.
- Core caído: el error de conexión de siempre.

## Requisitos *(obligatorio)*

Cada requisito cita entre paréntesis el FR y la CAP de la 008 que cumple.

### Requisitos funcionales

#### Descubiertas, dominios configurables y preferencias (FR-053 de la 008, CAP-044)

- **FR-001**: `ha_list_discovered_integrations` devuelve los flujos en curso
  que no ha abierto el usuario (`config_entries/flow/progress`): `flow_id`,
  `domain`, `source`, `step_id`, el nombre que enseña HA
  (`title_placeholders`, redactado) e `ignorable` (tiene `unique_id`), con
  filtro opcional `domain`; sobre común `{count, items, truncated}`. Solo
  lectura (FR-053, CAP-044).
- **FR-002**: `ha_ignore_discovery(flow_id, title=None)` ignora un
  descubrimiento con `config_entries/ignore_flow`. Antes comprueba que el flujo
  está en la lista de FR-001 (`not_found` si no) y que tiene `unique_id`
  (`cannot_ignore` si no), sin llamar a `ignore_flow`. El título por defecto es
  el nombre que enseña HA o el dominio. La respuesta dice cómo deshacerlo
  (borrar la entrada `ignore`). Sin token (FR-053, CAP-044).
- **FR-003**: `ha_list_config_flow_domains(type=None)` lista los dominios que
  se pueden configurar con un flujo (`GET /api/config/config_entries/flow_handlers`),
  con `type` opcional (`device`, `helper`, `hub`, `service`), ordenados; sobre
  común. Solo lectura. La docstring de `ha_list_configured_domains` deja de
  decir que no existe esa lista y remite a esta tool (FR-053, CAP-044;
  principio V).
- **FR-004**: `ha_update_config_entry(entry_id, title=None,
  pref_disable_polling=None, pref_disable_new_entities=None,
  confirmation_token=None)` cambia título y preferencias con
  `config_entries/update`. Lee antes la entrada (`config_entries/get_single`):
  `not_found` si no existe; `unchanged` sin llamar si nada cambia;
  `invalid_argument` si no se pide nada o el título está vacío. Pide token solo
  si una de las dos preferencias pasa a `true`; la vista previa tiene el
  título y las preferencias actuales y nuevas, el estado de la entrada y el
  efecto (recarga si el sondeo cambia y está cargada; entidades sin
  actualización automática; lo nuevo entra deshabilitado). El token se ata a
  los cuatro argumentos. La respuesta trae la entrada actualizada,
  `require_restart` y `reloaded` (si HA recargó la integración: el sondeo
  cambió en cualquier sentido con la entrada cargada; volver a activarlo
  también recarga, sin token, como `ha_reload_config_entry`) (FR-053,
  CAP-044).

#### Subentries y reconfigure (FR-054 de la 008, CAP-045)

- **FR-005**: `ha_list_config_subentries(entry_id)` devuelve las subentries de
  una entrada (`config_entries/subentries/list`: `subentry_id`,
  `subentry_type`, `title`, `unique_id`) y los tipos que la entrada admite
  crear (`supported_subentry_types` de `config_entries/get_single`); sobre
  común. `not_found` si la entrada no existe. Solo lectura (FR-054, CAP-045).
- **FR-006**: `ha_start_subentry_flow(entry_id, subentry_type,
  subentry_id=None)` abre un flujo de subentry
  (`POST /api/config/config_entries/subentries/flow`, `handler: [entry_id,
  subentry_type]`; con `subentry_id`, reconfigura esa subentry). Comprueba
  antes la entrada y el tipo (`not_found`, `subentry_type_not_supported` con
  los admitidos) y, con `subentry_id`, que la subentry existe y es de ese tipo.
  Los resultados `external`/`progress` se abortan y se devuelve
  `non_automatable`, como en `ha_start_config_entry_flow` (FR-054, CAP-045).
- **FR-007**: `ha_continue_subentry_flow(flow_id, user_input)` envía un paso
  (`POST …/subentries/flow/{flow_id}`) y `ha_abort_subentry_flow(flow_id)` lo
  cierra (`DELETE`). `flow_id` validado como en los flujos existentes; mismo
  tratamiento de `external`/`progress` y de `create_entry` (FR-054, CAP-045).
- **FR-008**: `ha_update_subentry(entry_id, subentry_id, title)` cambia el
  título de una subentry (`config_entries/subentries/update`). Comprueba antes
  la entrada y la subentry (`not_found`); `unchanged` si el título es el mismo.
  Sin token (FR-054, CAP-045).
- **FR-009**: `ha_delete_subentry(entry_id, subentry_id, confirmation_token=None)`
  borra una subentry (`config_entries/subentries/delete`) en dos pasos. La
  vista previa tiene la entrada (dominio y título), la subentry (tipo y
  título), las entidades (`entity_id`, nombre) y los dispositivos (id,
  nombre) vinculados a esa subentry, que HA borra con ella, y que la
  integración puede recargarse. El token se ata a `entry_id` y `subentry_id`.
  Si ya no existe al confirmar, `not_found` (FR-054, CAP-045).
- **FR-010**: `ha_start_reconfigure_flow(entry_id)` abre el flujo de
  reconfigure de una entrada (`POST /api/config/config_entries/flow` con
  `handler` y `entry_id`). Comprueba antes que la entrada existe y que
  `supports_reconfigure` es verdadero (`reconfigure_not_supported` sin abrir
  nada si no). Se continúa y se aborta con `ha_continue_config_entry_flow` y
  `ha_abort_config_entry_flow`; `external`/`progress` se abortan como en
  FR-006 (FR-054, CAP-045).

#### Flujos de reparación (FR-055 de la 008, CAP-048)

- **FR-011**: `ha_get_repair(domain, issue_id)` devuelve el resumen del aviso
  (los campos de `ha_list_repairs`, también si está ignorado), su título y su
  descripción traducidos (FR-015) y sus datos internos
  (`repairs/get_issue_data`) redactados por clave y por patrón y recortados al
  tope (`issue_data_truncated`). `not_found` si no existe. Solo lectura
  (FR-055, CAP-048).
- **FR-012**: `ha_start_repair_fix(domain, issue_id)` abre el flujo de
  reparación (`POST /api/repairs/issues/fix` con `handler` e `issue_id`).
  Comprueba antes que el aviso existe (`not_found`) y es reparable
  (`not_fixable`). Devuelve el primer paso con el título y la descripción
  traducidos del paso (o, si no los hay, los del aviso, dicho). Si el flujo
  termina al abrirse, `finished_on_start: true` y, para `create_entry`, si el
  aviso sigue en la lista. `external`/`progress` → abortado y
  `non_automatable`. Sin token (FR-055, CAP-048).
- **FR-013**: `ha_continue_repair_fix(domain, issue_id, flow_id,
  user_input=None, confirmation_token=None)` envía un paso del flujo en dos
  pasos. Sin token: lee el paso actual (`GET /api/repairs/issues/fix/{flow_id}`),
  comprueba que el flujo es de `domain` (`flow_mismatch` si no) y que el aviso
  existe, y devuelve una vista previa con el aviso (título traducido), el paso
  (`step_id`, texto traducido), los datos que se envían (redactados) y el
  efecto («enviar este paso puede aplicar el arreglo; HA no dice antes si es
  el último»), con la nota de que la relación aviso–flujo la indica quien
  llama. El token se ata a los cinco argumentos. Con token: un solo POST; si
  termina en `create_entry`, la respuesta dice si el aviso sigue
  (`issue_still_present`). Errores de esquema de HA → devueltos, token
  completado con fallo (FR-055, CAP-048).
- **FR-014**: `ha_abort_repair_fix(flow_id)` cierra un flujo de reparación sin
  aplicar nada (`DELETE`). Sin token (FR-055, CAP-048).

#### Textos traducidos de Repairs (FR-056 de la 008, CAP-036)

- **FR-015**: `ha_list_repairs`, `ha_get_repair`, la vista previa de
  `ha_ignore_repair` y las respuestas de FR-012 y FR-013 traen `title` y
  `description` del aviso en el idioma configurado en HA, leídos por dentro con
  `frontend/get_translations` (categoría `issues`, solo los dominios de los
  avisos devueltos, una sola llamada por respuesta), con los
  `translation_placeholders` (redactados) sustituidos y marcados como texto de
  terceros (`_third_party_text`: los escribe cada integración). En las listas,
  la descripción se recorta con `description_truncated`. Si la lectura falla o no
  hay texto, `title`/`description` nulos y `translations_unavailable: true`;
  el resto de la respuesta no cambia. Sin argumentos nuevos (FR-056, CAP-036).

#### Guía de helpers por config entry (FR-057 de la 008, CAP-037)

- **FR-016**: El tema `helpers` de `hermes_guide` explica los helpers que se
  crean por config entry: listar los dominios con
  `ha_list_config_flow_domains(type="helper")` (o, con la familia desactivada,
  probar el dominio directamente), crear con `ha_start_config_entry_flow` y
  `ha_continue_config_entry_flow`, listar con
  `ha_list_config_entries(type_filter="helper")`, editar con los flujos de
  opciones y borrar con `ha_delete_config_entry`; con un ejemplo de un helper
  `template` (FR-057, CAP-037).

#### Familias, tabla, convenciones y documentación (transversales de la 008)

- **FR-017**: Dos familias nuevas, desactivables y `desde="1.2.0"`:
  `integration_flows` con los módulos `integration_setup` (FR-001…FR-004) y
  `config_subentries` (FR-005…FR-010), y `repair_flows` con el módulo
  `repair_flows` (FR-011…FR-014). El ayudante de traducciones
  (`tools/_translations.py`) no registra tools. Con las familias de la 1.2.0
  desactivadas, la lista sigue siendo la de la 1.1.2 (FR-010 de la 008,
  CAP-004).
- **FR-018**: En `command_table.py` pasan a `dedicated`, en el mismo cambio que
  su tool y con su familia: `config_entries/flow/progress`,
  `config_entries/ignore_flow` y `config_entries/update` (CAP-044);
  `config_entries/subentries/list`, `config_entries/subentries/update` y
  `config_entries/subentries/delete` (CAP-045); y `repairs/get_issue_data`
  (CAP-048). `frontend/get_translations` sigue `deny` (clase B) con un
  comentario que dice que Hermes lo usa por dentro (CAP-036). El mapa del
  generador nombra las siete y regenerar la tabla la deja idéntica. El test que
  exige «pendiente de tool dedicada» para la clase A de vía D admite
  `dedicated` hacia una tool que existe (FR-012 de la 008, CAP-001).
- **FR-019**: Anotaciones verdaderas en `tools/_annotations.py`:
  `ha_update_config_entry` y `ha_continue_repair_fix` destructivas por nombre
  exacto (piden token); `ha_delete_subentry` destructiva por su prefijo;
  `ha_start_subentry_flow`, `ha_continue_subentry_flow`,
  `ha_start_reconfigure_flow`, `ha_start_repair_fix` y `ha_continue_repair_fix`
  no idempotentes por nombre exacto (cada llamada abre o avanza un flujo);
  ninguna de mundo abierto; las de prefijo `ha_list_`/`ha_get_`, de solo
  lectura; títulos legibles. Las tools de la 1.1.2 no cambian de hints (FR-018
  de la 008).
- **FR-020**: `hermes_guide` tiene los temas `integration_flows` (alias
  `discovery`, `discovered`, `subentries`, `subentry`, `reconfigure`) y
  `repair_flows` (alias `repair_fix`, `fix`), que explican cuándo usar cada
  tool, qué pide token y por qué, el caso OAuth (abortado e informado), cómo
  configurar un descubierto con los flujos existentes y la receta «arreglar un
  aviso de Repairs»; `config_entries` y `diagnostics` remiten a ellos (FR-011 de
  la 008).
- **FR-021**: Ningún secreto que llegue en `title_placeholders`,
  `translation_placeholders`, datos internos de un aviso, `user_input`, textos
  traducidos, esquemas de formulario, errores de HA o títulos aparece en una
  respuesta, una vista previa, un error, el log de Hermes o el fichero del
  token; el log de estas tools lleva ids, dominios, tipos de resultado y
  recuentos, nunca `user_input`, datos internos ni textos. Test con centinela
  por tool que reciba o devuelva esos datos (FR-019 de la 008, principio II).
- **FR-022**: Toda respuesta de lista de las tools nuevas usa el sobre
  `{count, items, truncated}` ajustado a `response_max_bytes`; las vistas
  previas caben en el tope (las listas de entidades y dispositivos de FR-009 se
  recortan con recuento total). `ha_list_repairs` conserva su forma de la 1.1.2
  (FR-018 de la 008, CAP-023).
- **FR-023**: Las tools que modifican (`ha_ignore_discovery`,
  `ha_update_config_entry`, `ha_start_subentry_flow`,
  `ha_continue_subentry_flow`, `ha_abort_subentry_flow`, `ha_update_subentry`,
  `ha_delete_subentry`, `ha_start_reconfigure_flow`, `ha_start_repair_fix`,
  `ha_continue_repair_fix`, `ha_abort_repair_fix`) se ejecutan en el banco de
  Core contra HA 2026.11.1 real con el efecto comprobado por el lector, y están
  en `tests/banco/cobertura_016.py` sumada al invariante de escrituras; las de
  lectura y las traducciones también se ejecutan ahí. Lo que no se pueda
  ejecutar queda con su motivo (FR-015 de la 008, CAP-034).
- **FR-024**: Nada de lo actual cambia: las tools existentes conservan
  nombres, argumentos, anotaciones y forma de respuesta (`ha_list_repairs` y
  `ha_ignore_repair` solo ganan campos); los flujos de configuración y de
  opciones siguen como en la 1.1.2; la tabla solo cambia en las siete entradas
  de FR-018 y el comentario de `frontend/get_translations` (FR-020 de la 008).
- **FR-025**: Documentación en el mismo cambio: sección propia en
  `## [1.2.0]` de `hermes/CHANGELOG.md`; estado de la 016 en la tabla del
  programa de `docs/HOJA-DE-RUTA.md`; tools nuevas en `README.md` y
  `README.es.md` sincronizados; familias en `hermes/DOCS.md` si la opción de
  familias las enumera; filas CAP-036, CAP-037, CAP-044, CAP-045 y CAP-048 de
  la matriz de `specs/008-cobertura-total/plan.md` con las tools y los tests
  (FR-023 de la 008).
- **FR-026**: Tests, fixtures, la integración de prueba del banco y la
  documentación solo con marcadores genéricos (`<entry_id>`, `banco_flujos`,
  `light.salon`, centinelas de texto); ningún dato de una instalación ni
  identificador de modelo (FR-021 de la 008, principio VIII).

### Entidades clave

- **Descubrimiento**: flujo de configuración en curso que no abrió el usuario
  (fuente `zeroconf`, `dhcp`, `ssdp`, `hassio`, `bluetooth`, `discovery`…, o
  `reauth`); se ignora creando una entrada con fuente `ignore` si tiene
  `unique_id`.
- **Preferencias de una entrada**: título, `pref_disable_polling` (la
  integración deja de sondear; HA la recarga si está cargada) y
  `pref_disable_new_entities` (lo nuevo entra deshabilitado).
- **Subentry**: parte de una entrada con id, tipo, título, `unique_id` y
  datos propios; sus entidades y dispositivos se borran con ella. Se crea y se
  reconfigura por un flujo propio; solo el título se cambia directamente.
- **Flujo de reparación**: flujo de datos de HA asociado a un aviso reparable;
  al terminar en `create_entry`, HA borra el aviso; en `abort`, no.
- **Texto traducido de un aviso**: `component.<dominio>.issues.<clave>.title`
  y `.description`, con marcadores `{nombre}`; los pasos del flujo, en
  `….fix_flow.step.<paso>.title|description`.

## Fuera de alcance

- Diagnósticos de integraciones, log y notificaciones (012).
- Credenciales de aplicación OAuth y completar flujos `external` (OAuth): se
  siguen abortando e informando (clase D en la tabla para crear credenciales).
- Borrar o «des-ignorar» una entrada ignorada con una tool propia: ya se hace
  con `ha_delete_config_entry` (token).
- Mover dispositivos o entidades entre subentries (no hay API pública de
  administración para ello en 2026.11.1 más allá de los registros).
- Reautenticar una integración (los flujos `reauth` aparecen en la lista de
  FR-001 y se continúan con `ha_continue_config_entry_flow` si no son OAuth).
- Suscripciones (`config_entries/flow/subscribe`, `config_entries/subscribe`):
  clase B, `deny`.
- Cambiar los hints de las tools de flujos de la 1.1.2 (D-4).

## Supuestos

- **S-01**: Antes del tramo A la rama tiene integradas la 009 (redacción
  lineal y la entrada `## [1.2.0]`), la 010 (banco) y la 011 entera
  (genéricas, opción de familias y registro por familias; hoy la rama de la
  016 sale de la 011 con su tramo 3 en curso). **La implementación espera a la
  011 integrada.** Si la 010 no lo está, las tareas del banco quedan pendientes
  con una nota en el commit y en la hoja de ruta, y el tramo sigue.
- **S-02**: Si la 028 está integrada, su invariante de escrituras suma la lista
  de la 016; si no, la 016 trae su propio test del invariante para sus once
  tools y la unión se hace al integrar.
- **S-03**: Si la 012 ya cambió el generador para consultar
  `_DEDICADAS_INICIALES` en la clase A y el test de la vía D, la 016 solo añade
  sus claves; si no, lo hace la 016 con el mismo diseño (research R-7).
- **S-04**: El HA del banco carga integraciones de `custom_components/` de su
  `/config` (es lo normal en HA Core) y lee sus traducciones de
  `translations/`. Si no fuese así, el camino feliz de ignorar, reconfigurar,
  subentries y reparación queda en unitarios y como pendiente manual en la
  matriz de la 014, con el motivo.
- **S-05**: HA 2026.11.1 es la referencia; las formas de respuesta están en
  research con el fichero de HA de donde salen.

## Criterios de éxito *(obligatorio)*

- **SC-001**: Con la configuración por defecto se registran las 15 tools
  nuevas y las de antes siguen idénticas (nombres, anotaciones, esquemas).
- **SC-002**: Las siete entradas de FR-018 son `dedicated` hacia una tool
  registrada de su familia, y regenerar la tabla no cambia ni un byte.
- **SC-003**: El 100 % de las llamadas sin token a `ha_delete_subentry`,
  `ha_continue_repair_fix` y a `ha_update_config_entry` cuando desactiva el
  sondeo o las entidades nuevas no envían nada que modifique HA; un token no
  sirve con otros argumentos.
- **SC-004**: Ningún centinela de secreto aparece en respuestas, vistas
  previas, errores, log de Hermes ni ficheros de token de estas tools.
- **SC-005**: Las once tools que modifican pasan en el banco con el efecto
  comprobado por el lector, y las de lectura y las traducciones devuelven
  datos reales.
- **SC-006**: Cada FR tiene su test, y cada comportamiento con riesgo, su
  control negativo anotado.
- **SC-007**: La suite pasa en el CI de Linux al final de cada tramo, con
  exactamente los 6 fallos conocidos de Windows en local.
