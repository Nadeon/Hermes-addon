# Especificación: Hermes 1.2.0 — automatización asistida (sub-feature 017)

**Directorio de la spec**: `specs/017-automatizacion-asistida`

**Creada**: 2026-11-14

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T015 de su `tasks.md` y cubre **CAP-046, CAP-051,
CAP-052, CAP-038 y la validación al guardar de CAP-040** (FR-058…FR-062 de la
008), más los transversales que le tocan (FR-010…FR-012, FR-015, FR-018…FR-021
y FR-023 de la 008). Ola 3, tamaño L; la 008 la da en 3 tramos y aquí se parte
en 4 (research R-12).

**Entrada**: `specs/008-cobertura-total/` (spec, plan con la matriz de
trazabilidad, research CAP-038, CAP-040, CAP-046, CAP-051 y CAP-052 e
`inventario/core-ws.tsv`), la sub-feature 011 (tabla `command_table.py`,
`command_policy.py`, `tool_families.py`, generador
`scripts/inventario/generar_tabla.py`), la 012 (`ha_validate_config` en
`tools/core_validation.py` y la regla del generador para la clase A con tool
dedicada), el banco de la 010 con la regla de inventario de escrituras de la
028 y la matriz de pruebas de la 014, el código de Hermes (`security.py`,
`tools/_annotations.py`, `tools/_common.py`, `tools/guide.py`,
`tools/automations.py`, `tools/scripts.py`, `tools/search.py`,
`tools/wait_for_event.py`, `ha.py`) y el código de Home Assistant Core
2026.11.1 (`blueprint`, `device_automation`, `websocket_api/commands.py`,
`websocket_api/automation.py`, `automation`, `script`, `search`, `frontend`),
leído sin ejecutar nada.

**Fuera de esta sub-feature** (otras del programa): `ha_validate_config` y
`ha_test_condition` como tools (012, FR-036; aquí solo se reutiliza su
validación al guardar); las descripciones de triggers y condiciones
(`trigger_platforms/subscribe`, `condition_platforms/subscribe`: suscripciones,
clase B); trazas y depuración de automatizaciones (ya existen en la 1.1.2).

## Clarificaciones

### Sesión 2026-11-14

Decisiones vinculantes de la 008 (no se discuten aquí): tools dedicadas para
las cinco CAP (vía D; CAP-040 es D+X y su parte X, validar al guardar, es de
aquí); dos pasos para importar, sobrescribir y borrar blueprints; importar
marca el contenido como texto de terceros; la espera de trigger tiene el mismo
tope que `ha_wait_for_event`; las tools nuevas en familias nuevas; prueba en el
banco de Core.

Decisiones tomadas al especificar (no había a quién preguntar; se justifican
en [research.md](research.md)):

- P: ¿Quién descarga un blueprint al importarlo? → R: **Home Assistant**, con
  su comando `blueprint/import`, igual que la interfaz. Hermes no abre ninguna
  conexión a la URL: no añade a su contenedor un cliente HTTP hacia internet ni
  una vía de SSRF. `blueprint/import` solo descarga y analiza; guarda
  `blueprint/save` (research R-1).
- P: ¿Qué se guarda al confirmar la importación, si la URL puede cambiar entre
  la vista previa y la confirmación? → R: lo previsualizado, o nada. La vista
  previa da la huella SHA-256 del contenido descargado y el token se ata a
  ella; al confirmar, HA vuelve a descargar y Hermes solo guarda si la huella
  coincide. Si no, error sin guardar y hay que pedir otra vista previa
  (research R-1).
- P: ¿Qué enseña la vista previa de una importación? → R: exactamente qué se
  va a guardar y de dónde viene: la URL, el dominio, la ruta final bajo
  `/config/blueprints/`, si ya existe (y quién usa el existente), los
  metadatos, las entradas, los errores de validación de HA y el YAML entero
  descargado, con su tamaño y su huella. Todo marcado con `_third_party_text`.
  Si el YAML no cabe en el tope de respuesta, no hay token: no se puede
  confirmar lo que no se ha podido enseñar (research R-1).
- P: ¿Cómo se borra un blueprint en uso? → R: no se borra. HA lo rechaza
  («Blueprint in use»), así que la tool no emite token: devuelve
  `blueprint_in_use` con las automatizaciones o scripts que lo usan, sacados
  de `search/related` (la misma fuente que usa HA para negarse). Sin uso, la
  vista previa lo dice y da el token (research R-3).
- P: ¿Guardar un blueprint escrito por el agente pide token? → R: sí, siempre,
  como `ha_create_or_update_automation`: crea un fichero en `/config` y, si
  sobrescribe, HA recarga las automatizaciones o scripts que lo usan. Sin
  `allow_override`, guardar encima de uno existente da `already_exists` sin
  token (research R-2).
- P: ¿Las capacidades de un trigger, condición o acción de dispositivo, tool
  aparte? → R: no: `include_capabilities=true` en las tres tools de lista las
  añade a cada elemento, con un tope de llamadas (research R-6).
- P: ¿Qué es la «resolución de un target»? → R: dos tools: `ha_resolve_target`
  (qué entidades, dispositivos y áreas abarca un target, y qué referencias no
  existen) y `ha_explain_target` (por qué se incluye cada entidad). Y tres más
  que listan los triggers, condiciones y acciones aplicables a un target, que
  son las de «por propósito» (`light.turned_on`…) junto con las de siempre
  (research R-7).
- P: ¿La espera de trigger comparte tope con `ha_wait_for_event`? → R: sí:
  mismo máximo de segundos y el mismo cupo de esperas simultáneas; sale en
  `ha_list_active_waits` y se cancela con `ha_cancel_wait` (research R-8).
- P: ¿Se puede esperar a cualquier trigger? → R: solo a los que se sabe que
  únicamente escuchan (lista cerrada, fail-closed): las plataformas de Core de
  siempre (`state`, `numeric_state`, `event`, `time`…) y los triggers
  `<integración>.<nombre>` y `device` de integraciones incluidas en HA, salvo
  los que hacen algo mientras están activos: `webhook` (abre un endpoint HTTP
  sin autenticación), `conversation` (contesta a las frases de Assist de
  cualquier usuario) y el «encender» de `samsungtv`, `webostv` y `lg_netcast`
  (le dan a la tele la acción de encender). Los de integraciones
  personalizadas se rechazan: Hermes no puede saber qué hacen. Así la
  anotación de solo lectura es verdad (research R-8).
- P: ¿Qué valida `ha_create_or_update_automation` antes de dar el token? → R:
  triggers, condiciones y acciones con `validate_config` de HA (la misma
  función que `ha_validate_config` de la 012); si la configuración usa un
  blueprint, primero se sustituye con `blueprint/substitute` y se valida el
  resultado. Lo que HA no valida por esa vía (`mode`, `alias`…) se dice en
  `not_validated`. Si no se puede validar (HA no responde), no hay token
  (research R-9).
- P: ¿Familias? → R: dos nuevas de la 1.2.0: `blueprints` (las cinco de
  blueprints) y `automation_assist` (dispositivo, targets y espera de
  trigger). La validación al guardar no depende de ninguna familia: va dentro
  de las tools de siempre (research R-10).
- P: ¿Cómo se prueba la importación en el banco, que no tiene internet? → R: la
  HA del banco sirve el blueprint de prueba desde su propia carpeta `www`
  (`/local/…`), y se importa desde `http://127.0.0.1:8123/local/…` dentro del
  contenedor. Es una descarga HTTP real por el mismo código de HA (el
  importador genérico); lo único que no se prueba ahí son los importadores de
  GitHub, gist y foro, que quedan como prueba manual pendiente (research R-11).

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es el administrador de Home Assistant que trabaja desde un cliente
MCP.

### Historia 1 — Usar blueprints sin tocar ficheros (Prioridad: P1)

Quien quiere aprovechar un blueprint publicado quiere verlo, importarlo
sabiendo qué entra en su casa y de dónde, ver qué automatización saldría con
unas entradas concretas y quitarlo cuando ya no lo use, sin romper nada.

**Prueba independiente**: con un HA simulado, `ha_import_blueprint` sin token
llama una vez a `blueprint/import`, devuelve la vista previa con el YAML, la
huella y `_third_party_text` y no llama a `blueprint/save`; con el token y el
mismo contenido, llama a `blueprint/save` una vez con ese YAML.

**Escenarios de aceptación**:

1. **Dado** blueprints de automatización y de script, **cuando** el agente
   llama a `ha_list_blueprints`, **entonces** recibe cada uno con dominio,
   ruta, nombre, descripción, autor, URL de origen y nombres de sus entradas,
   y los que HA no pudo cargar con su error.
2. **Dado** una URL de un blueprint, **cuando** pide importarlo sin token,
   **entonces** recibe una vista previa con la URL, la ruta donde se guardará,
   el YAML entero, su tamaño y su huella, los metadatos y entradas, los errores
   de validación de HA, si ya existe y un token; todo marcado como texto de
   terceros, y nada se guarda.
3. **Dado** esa vista previa, **cuando** confirma con el token y el contenido
   de la URL no ha cambiado, **entonces** el blueprint queda guardado en la
   ruta anunciada con la URL de origen en sus metadatos.
4. **Dado** que el contenido de la URL cambió tras la vista previa, **cuando**
   confirma, **entonces** recibe un error que lo dice y no se guarda nada.
5. **Dado** un blueprint que ya existe en esa ruta, **cuando** pide importarlo
   sin `allow_override`, **entonces** recibe `already_exists` sin token; con
   `allow_override=true`, la vista previa dice que lo sustituye y qué
   automatizaciones o scripts lo usan y se recargarán.
6. **Dado** un blueprint y unas entradas, **cuando** pide
   `ha_preview_blueprint_substitution`, **entonces** recibe la configuración
   resultante sin guardar nada; si falta una entrada, el error de HA.
7. **Dado** un blueprint que usan dos automatizaciones, **cuando** pide
   borrarlo, **entonces** recibe `blueprint_in_use` con las dos y sin token; el
   fichero sigue ahí.
8. **Dado** un blueprint sin uso, **cuando** pide borrarlo sin token,
   **entonces** la vista previa da su ruta, sus metadatos y que no se puede
   deshacer salvo con un backup; con el token, el blueprint desaparece.
9. **Dado** un YAML de blueprint escrito por el agente, **cuando** pide
   `ha_save_blueprint` sin token, **entonces** recibe una vista previa con la
   ruta, los metadatos leídos del YAML, el tamaño y la huella; con el token, HA
   lo guarda (o lo rechaza con su error si no es un blueprint válido).

### Historia 2 — Saber qué se puede automatizar en un dispositivo (Prioridad: P1)

Quien crea una automatización para un dispositivo quiere saber qué triggers,
condiciones y acciones de dispositivo ofrece y qué campos extra admite cada
uno, sin adivinar el formato.

**Prueba independiente**: con HA simulado, `ha_list_device_triggers` envía
`device_automation/trigger/list` y devuelve la lista; con
`include_capabilities=true`, una llamada de capacidades por elemento hasta el
tope.

**Escenarios de aceptación**:

1. **Dado** un dispositivo con triggers, **cuando** los lista, **entonces**
   recibe cada trigger tal como se escribe en una automatización.
2. **Dado** `include_capabilities=true`, **cuando** lista, **entonces** cada
   elemento lleva sus `extra_fields` (por ejemplo, la duración `for`).
3. **Dado** un `device_id` que no existe, **cuando** lista, **entonces**
   recibe `not_found`.
4. **Dado** lo mismo para condiciones y acciones, **entonces** se comporta
   igual con sus comandos.

### Historia 3 — Automatizar por propósito sobre un target (Prioridad: P1)

Quien piensa en «las luces del salón» quiere saber qué entidades son de
verdad, por qué, y qué triggers, condiciones y acciones tienen sentido para
ese conjunto.

**Prueba independiente**: con HA simulado, cada tool envía un solo comando con
el target validado y devuelve el resultado ordenado.

**Escenarios de aceptación**:

1. **Dado** `{"area_id": "salon"}`, **cuando** pide `ha_resolve_target`,
   **entonces** recibe las entidades, dispositivos y áreas que abarca y las
   referencias que no existen.
2. **Dado** el mismo target, **cuando** pide `ha_explain_target`, **entonces**
   recibe por qué entra cada entidad (por el área, por un dispositivo del
   área…) y lo que quitan las exclusiones.
3. **Dado** el mismo target, **cuando** pide los triggers, condiciones o
   acciones aplicables, **entonces** recibe sus nombres
   (`light.turned_on`, `light.turn_on`…), ordenados.
4. **Dado** un target con una clave que HA no admite, **cuando** se llama,
   **entonces** recibe `invalid_argument` sin llamar a HA.

### Historia 4 — Esperar a que ocurra algo concreto (Prioridad: P2)

Quien quiere «avísame cuando se abra la puerta» en esta conversación quiere
describirlo como un trigger de automatización, no como un filtro de eventos.

**Prueba independiente**: con HA simulado, `ha_wait_for_trigger` se suscribe
con `subscribe_trigger`, devuelve el primer disparo y cancela la suscripción.

**Escenarios de aceptación**:

1. **Dado** un trigger de estado, **cuando** espera y el estado cambia,
   **entonces** recibe `matched: true` con los datos del disparo y el tiempo
   esperado.
2. **Dado** que no pasa nada, **cuando** vence el plazo, **entonces** recibe
   `matched: false` con `reason: "timeout"`.
3. **Dado** un plazo mayor que el máximo de `ha_wait_for_event`, **cuando** se
   llama, **entonces** recibe el mismo error que esa tool.
4. **Dado** un trigger inválido, **cuando** se llama, **entonces** recibe el
   error de HA y no queda ninguna espera activa.
5. **Dado** un trigger `webhook`, `conversation`, el de encender de una tele
   o el de una integración personalizada, **cuando** se llama, **entonces**
   recibe `trigger_not_allowed` con el motivo y sin suscribirse.
6. **Dado** una espera en curso, **cuando** se pide `ha_list_active_waits`,
   **entonces** aparece; con `ha_cancel_wait`, termina con
   `reason: "cancelled"`.

### Historia 5 — No pedir un token para algo que HA rechazaría (Prioridad: P1)

Quien guarda una automatización o un script con un error quiere saberlo antes
de confirmar, no después.

**Prueba independiente**: con HA simulado, `ha_create_or_update_automation`
sin token envía `validate_config` y, si una parte es inválida, devuelve el
error sin emitir token ni crear fichero de token.

**Escenarios de aceptación**:

1. **Dado** una automatización con un trigger inválido, **cuando** pide la
   vista previa, **entonces** recibe `invalid_config` con el error de HA para
   esa parte y ningún token.
2. **Dado** una configuración válida, **cuando** pide la vista previa,
   **entonces** la vista previa dice qué partes se validaron y cuáles no
   (`not_validated`), y da el token como hoy.
3. **Dado** una automatización que usa un blueprint, **cuando** pide la vista
   previa, **entonces** Hermes sustituye el blueprint con esas entradas y
   valida el resultado; si falta una entrada, el error de HA sin token.
4. **Dado** un script con `sequence` inválida, **cuando** pide la vista
   previa, **entonces** recibe el error sin token.
5. **Dado** que HA no responde a la validación, **cuando** pide la vista
   previa, **entonces** recibe `validation_unavailable` sin token.

### Historia 6 — Nada se rompe ni se salta una protección (Prioridad: P1)

Quien usa Hermes hoy quiere que estas tools no cambien nada de lo que ya
funciona, ni abran un camino alrededor de la tabla o del sandbox de ficheros.

**Prueba independiente**: tests de registro, de la tabla, de familias y de
anotaciones.

**Escenarios de aceptación**:

1. **Dado** la configuración por defecto, **cuando** arranca, **entonces** las
   tools de antes siguen con los mismos nombres, anotaciones y argumentos, y
   aparecen las 14 nuevas en `blueprints` y `automation_assist`.
2. **Dado** `tool_families_disabled: [blueprints, automation_assist]`,
   **cuando** arranca, **entonces** las 14 no se registran, sus comandos
   siguen `dedicated` en la tabla (la genérica los rechaza con
   `family_disabled`) y `ha_create_or_update_automation` sigue validando.
3. **Dado** la genérica de escritura con `blueprint/delete`, **cuando** se
   llama, **entonces** recibe `use_dedicated_tool` con `ha_delete_blueprint`.

### Casos límite

- URL que HA no sabe importar o que no responde: el error de HA, redactado,
  sin token. La descarga de HA tiene su propio plazo de 10 s.
- Blueprint importado de un dominio que no es `automation`, `script` ni
  `template`, o con
  errores de validación de HA: `invalid_blueprint` con los errores, sin token.
- YAML descargado más grande que lo que cabe en la vista previa:
  `blueprint_too_large` con el tamaño, sin token.
- Contenido que cambia entre vista previa y confirmación: la confirmación no
  casa, no se guarda, y la respuesta pide otra vista previa.
- `path` con `..`, absoluto o con caracteres de control: `invalid_argument`
  sin llamar a HA. Sin `.yaml`, HA lo añade y la vista previa ya lo dice.
- Borrar un blueprint que no existe: `not_found` sin token. La lectura de
  quién lo usa falla: `preview_unavailable` sin token.
- Alguien empieza a usar el blueprint entre la vista previa y la confirmación:
  HA rechaza el borrado y la tool devuelve `blueprint_in_use`.
- Dispositivo sin triggers: lista vacía, no error. Más elementos que el tope de
  capacidades: los primeros con capacidades y `capabilities_truncated`.
- Target vacío: `invalid_argument`. Target con ids que no existen: HA los
  devuelve en `missing_*` y la tool también.
- HA anterior a los comandos de targets (`unknown_command`):
  `ha_version_unsupported` con la versión actual.
- Reconexión de la WebSocket durante una espera de trigger: `matched: false`
  con `reason: "ws_reconnect"` y la nota de comprobar el estado, como
  `ha_wait_for_event`.
- Disparo con estados que llevan atributos sensibles (`access_token` de una
  cámara): redactados.
- Automatización sin triggers, condiciones ni acciones que validar (solo
  `alias`): no se llama a `validate_config`; la vista previa lo dice y HA
  valida el resto al guardar.
- Core caído: el error de conexión de siempre.

## Requisitos *(obligatorio)*

Cada requisito cita entre paréntesis el FR y la CAP de la 008 que cumple.

### Requisitos funcionales

#### Blueprints (FR-058 de la 008, CAP-046)

- **FR-001**: `ha_list_blueprints` lista los blueprints de `automation`,
  `script` y `template` (o de uno con `domain`) con `blueprint/list`: dominio, ruta,
  nombre, descripción, autor, `source_url`, versión mínima de HA y nombres de
  las entradas; los que HA no pudo cargar, con su error redactado. Nombre,
  descripción y autor marcados con `_third_party_text`. Sobre
  `{count, items, truncated}`. Solo lectura (FR-058, CAP-046).
- **FR-002**: `ha_import_blueprint` importa un blueprint desde una URL en dos
  pasos. La descarga la hace HA (`blueprint/import`); Hermes no conecta con la
  URL. La vista previa tiene la URL, el dominio, la ruta final bajo
  `/config/blueprints/<dominio>/` (la sugerida por HA o `path`), si existe y,
  si existe, quién lo usa, los metadatos y las entradas, los errores de
  validación de HA, el YAML entero (redactado, con aviso si algo se tapó), su
  tamaño y su huella SHA-256, y `_third_party_text` sobre todo lo descargado.
  El token se ata a la URL, la ruta, `allow_override` y la huella; al
  confirmar, HA vuelve a descargar y solo se guarda (`blueprint/save` con el
  YAML descargado y `source_url`) si la huella coincide. Sin token si: hay
  errores de validación o el dominio no es `automation`, `script` ni
  `template` (`invalid_blueprint`), ya existe sin `allow_override` (`already_exists`), o
  el YAML no cabe en la vista previa (`blueprint_too_large`). Anotada como de
  mundo abierto (FR-058, CAP-046).
- **FR-003**: `ha_save_blueprint` guarda un blueprint escrito por el agente
  (`domain`, `path`, `yaml`, `allow_override`) en dos pasos con
  `blueprint/save`. La vista previa tiene la ruta final, si existe y quién lo
  usa (se recargarán), los metadatos leídos del YAML (sin resolver
  `!input`), el tamaño y la huella. `yaml` se puede omitir al confirmar (se
  guarda en la vista previa, como `config` en las automatizaciones). YAML que
  no se puede leer, sin clave `blueprint` o de otro dominio: `invalid_argument`
  sin token; el resto lo valida HA al guardar y su error se devuelve redactado
  (FR-058, CAP-046).
- **FR-004**: `ha_delete_blueprint` borra un blueprint (`domain`, `path`) en
  dos pasos con `blueprint/delete`. Antes de dar el token comprueba que existe
  (`not_found`) y quién lo usa con `search/related`
  (`automation_blueprint`/`script_blueprint`); en uso, `blueprint_in_use` con
  la lista y sin token. Para `template`, HA no expone quién lo usa: la vista
  previa lo dice (`used_by: null` con el motivo) y avisa de que HA rechazará
  el borrado si está en uso. La vista previa dice la ruta, los metadatos y que no
  se puede deshacer salvo con un backup. Si HA lo rechaza al confirmar porque
  pasó a estar en uso, `blueprint_in_use` (FR-058, CAP-046).
- **FR-005**: `ha_preview_blueprint_substitution` devuelve la configuración
  que resulta de un blueprint con unas entradas (`blueprint/substitute`), sin
  guardar nada; el error de HA (entrada que falta, blueprint que no existe)
  redactado. Solo lectura (FR-058, CAP-046).

#### Automatizaciones de dispositivo (FR-059 de la 008, CAP-051)

- **FR-006**: `ha_list_device_triggers`, `ha_list_device_conditions` y
  `ha_list_device_actions` devuelven lo que ofrece un dispositivo
  (`device_automation/<tipo>/list`) tal como se escribe en una automatización;
  con `include_capabilities=true`, cada elemento lleva los `extra_fields` de
  `device_automation/<tipo>/capabilities`, como mucho para los 50 primeros
  (`capabilities_truncated` si hay más). Dispositivo inexistente: `not_found`.
  Sobre común. Solo lectura (FR-059, CAP-051).

#### Targets y propósitos (FR-060 de la 008, CAP-052)

- **FR-007**: `ha_resolve_target` (`extract_from_target`) devuelve las
  entidades, dispositivos y áreas que abarca un target y las referencias que
  no existen (`missing_*`); `ha_explain_target` (`explain_target`) devuelve
  por qué entra cada entidad y lo que quitan las exclusiones. El target se
  valida antes (claves `entity_id`, `device_id`, `area_id`, `floor_id`,
  `label_id`, texto o lista de textos, al menos una, y un bloque `exclude`
  opcional con las mismas claves); `expand_group` y
  `primary_entities_only` con los valores por defecto de HA. Solo lectura
  (FR-060, CAP-052).
- **FR-008**: `ha_list_triggers_for_target`, `ha_list_conditions_for_target`
  y `ha_list_actions_for_target` (`get_triggers_for_target`,
  `get_conditions_for_target`, `get_services_for_target`) devuelven, ordenados,
  los nombres de los triggers, condiciones y acciones aplicables a alguna
  entidad del target, incluidos los de «por propósito». `unknown_command` →
  `ha_version_unsupported`. Solo lectura (FR-060, CAP-052).

#### Espera de trigger (FR-061 de la 008, CAP-038)

- **FR-009**: `ha_wait_for_trigger` espera una vez, bloqueando, a que se
  dispare un trigger de automatización (`subscribe_trigger`), con `variables`
  opcionales. Usa el mismo máximo de segundos (`wait_for_event_max_seconds`) y
  el mismo cupo de esperas simultáneas que `ha_wait_for_event`, aparece en
  `ha_list_active_waits` y se cancela con `ha_cancel_wait`; las respuestas
  (`matched`, `timeout`, `cancelled`, `ws_reconnect`) tienen la forma de las de
  esa tool, con los datos del disparo redactados y dentro del tope. Solo
  admite los triggers de la lista cerrada de research R-8 (plataformas de Core
  que escuchan; `<integración>.<nombre>` y `device` de integraciones incluidas
  en HA, comprobado con `manifest/get`, salvo `webhook`, `conversation`,
  `samsungtv`, `webostv` y `lg_netcast`); el resto, `trigger_not_allowed` sin
  suscribirse, y si no se puede comprobar, también (fail-closed). Siempre
  cancela la suscripción al terminar. Solo lectura (FR-061, CAP-038).

#### Validación al guardar (FR-062 de la 008, CAP-040)

- **FR-010**: `ha_create_or_update_automation` y `ha_create_or_update_script`
  validan, al pedir la vista previa, los triggers, condiciones y acciones (o
  `sequence`) con `validate_config` de HA, por la misma función que
  `ha_validate_config`; si la configuración usa un blueprint, primero lo
  sustituyen (`blueprint/substitute`) y validan el resultado. Una parte
  inválida → `invalid_config` con el error de HA por parte, redactado, sin
  token ni fichero de token; sustitución fallida →
  `blueprint_substitution_failed` sin token; validación imposible →
  `validation_unavailable` sin token. Con todo válido, la vista previa añade
  `validation` (partes validadas y `not_validated`) y sigue como hoy. La
  confirmación no cambia (FR-062, CAP-040).

#### Familias, tabla, convenciones y documentación (transversales de la 008)

- **FR-011**: Dos familias nuevas (`desde="1.2.0"`, desactivables):
  `blueprints` con el módulo `blueprints` y `automation_assist` con
  `device_automation`, `targets` y `wait_for_trigger`. Con ellas desactivadas
  no se registra ninguna de las 14; con todas las de la 1.2.0 desactivadas,
  la lista sigue siendo la de la 1.1.2. FR-010 no depende de ninguna familia
  (FR-010 de la 008, CAP-004).
- **FR-012**: En `command_table.py` pasan a `dedicated`, en el mismo cambio
  que su tool y con su familia, las 17 entradas de data-model: las cinco
  `blueprint/*`, las seis `device_automation/*`, `extract_from_target`,
  `explain_target`, `get_triggers_for_target`, `get_conditions_for_target`,
  `get_services_for_target` y `subscribe_trigger`. `subscribe_trigger` se
  reclasifica en `inventario/core-ws.tsv` de clase B a clase A con CAP-038
  (lo pide la research de la 008). El mapa del generador las nombra y
  regenerar la tabla la deja idéntica (FR-012 de la 008, CAP-001).
- **FR-013**: Anotaciones verdaderas: `ha_import_blueprint`,
  `ha_save_blueprint` y `ha_delete_blueprint` destructivas (piden token);
  `ha_import_blueprint` además de mundo abierto (HA descarga de internet);
  `ha_preview_blueprint_substitution`, `ha_resolve_target`,
  `ha_explain_target` y `ha_wait_for_trigger` de solo lectura por nombre
  exacto; las `ha_list_*` por prefijo. Títulos legibles (FR-018 de la 008).
- **FR-014**: `hermes_guide` tiene los temas `blueprints` (alias
  `blueprint`) y `automation_assist` (alias `device_automation`, `targets`,
  `wait_for_trigger`), que explican cuándo usar cada tool, el riesgo del
  contenido de terceros al importar, por qué no se puede borrar un blueprint
  en uso, cómo escribir un trigger por propósito con `target`, y la receta
  «crear una automatización para un dispositivo»; el tema de automatizaciones
  dice que guardar ya valida y remite a `ha_save_blueprint` en vez de
  `fs_write_file` para blueprints (FR-011 de la 008).
- **FR-015**: Ningún secreto que llegue en un YAML descargado o escrito,
  metadatos, errores de HA, capacidades, datos de un disparo o configuraciones
  sustituidas aparece en una respuesta, una vista previa, un error, un
  fichero de token o el log de Hermes (salvo el `yaml` omitible de
  `ha_save_blueprint`, que el fichero del token guarda igual que el `config`
  de las automatizaciones desde la spec 007); el log solo lleva dominios, rutas,
  huellas, recuentos y códigos, nunca YAML, URL con credenciales ni datos de
  estados. Test con centinela por tool (FR-019 de la 008, principio II).
- **FR-016**: Toda respuesta de lista usa el sobre `{count, items, truncated}`
  ajustado a `response_max_bytes`; las vistas previas y las respuestas de
  sustitución y de espera caben en el tope o fallan sin cortar el JSON
  (FR-018 de la 008, CAP-023).
- **FR-017**: Las tres tools que modifican (`ha_import_blueprint`,
  `ha_save_blueprint`, `ha_delete_blueprint`) se ejecutan en el banco de Core
  contra HA 2026.11.1 real con el efecto comprobado por el lector, están en
  `tests/banco/cobertura_017.py` sumada al invariante de escrituras y al plugin
  del job, y tienen su fila en la matriz de pruebas de la 014 (`banco de Core`,
  `ok`). La importación se prueba desde un fichero servido por la propia HA del
  banco; los importadores de GitHub, gist y foro quedan como pendiente manual.
  FR-010 y las lecturas también se ejecutan en el banco (FR-015 de la 008,
  CAP-034).
- **FR-018**: Nada de lo actual cambia salvo FR-010: las tools existentes,
  sus argumentos y anotaciones, la denylist, la forma de los waits de
  `ha_wait_for_event` en `ha_list_active_waits`, y la tabla fuera de las 17
  entradas de FR-012 (FR-020 de la 008).
- **FR-019**: Documentación en el mismo cambio: sección propia en
  `## [1.2.0]` de `hermes/CHANGELOG.md`; estado de la 017 en la tabla del
  programa de `docs/HOJA-DE-RUTA.md` y su línea de pendientes; filas de la
  matriz de pruebas; tools nuevas en `README.md` y `README.es.md`
  sincronizados; familias en `hermes/DOCS.md` si la opción de familias las
  enumera; filas CAP-038, CAP-040, CAP-046, CAP-051 y CAP-052 de la matriz de
  `specs/008-cobertura-total/plan.md` con las tools y los tests (FR-023 de la
  008).
- **FR-020**: Tests, fixtures y documentación solo con marcadores genéricos
  (`light.salon`, `<device_id>`, `https://example.com/…`, centinelas); ningún
  dato de una instalación ni identificador de modelo (FR-021 de la 008,
  principio VIII).

### Entidades clave

- **Blueprint**: fichero YAML bajo `/config/blueprints/<dominio>/<ruta>.yaml`
  con un bloque `blueprint` (nombre, descripción, dominio, autor, entradas,
  `source_url`) y el cuerpo de automatización o script con `!input`.
- **Importación**: lo que devuelve `blueprint/import`: nombre de fichero
  sugerido, YAML en bruto, metadatos, errores de validación y si ya existe.
- **Target**: selección de entidades por `entity_id`, `device_id`, `area_id`,
  `floor_id` y `label_id`.
- **Espera de trigger**: suscripción de un solo disparo, con plazo, cupo y
  cancelación compartidos con las esperas de eventos.

## Fuera de alcance

- `ha_validate_config` y `ha_test_condition` (012).
- Descripciones de los triggers y condiciones por propósito (sus campos
  `options`): solo existen por suscripción (`trigger_platforms/subscribe`,
  `condition_platforms/subscribe`, clase B). La guía remite a
  `ha_validate_config` para comprobar una configuración (duda D-2).
- Leer el YAML de un blueprint guardado: ya se puede con `fs_read_file`.
- Compartir o exportar blueprints.
- Saber quién usa un blueprint de `template`: `search/related` no tiene ese
  tipo en HA 2026.11 (research R-3).
- Suscripciones continuas a triggers: clase B; esto es de un solo disparo.

## Supuestos

- **S-01**: Antes del tramo A la rama tiene integrada la 012 (a través de
  `feat/cobertura-total`): su regla del generador para la clase A con tool
  dedicada y su `tools/core_validation.py`. La 008 pone a la 017 detrás de la
  012. Si no está integrada, la implementación no empieza (T001 lo comprueba).
- **S-02**: La 028 y la 014 están integradas (lo están en la rama de salida):
  el invariante de escrituras suma la lista de la 017 y la matriz de pruebas
  exige sus filas.
- **S-03**: En el banco, la configuración carga `automation:`, `script:` y
  `frontend:` (028), así que HA crea sus blueprints por defecto y sirve
  `/config/www` en `/local/`; `kitchen_sink:` da dispositivos con
  automatizaciones de dispositivo (research R-11).
- **S-04**: HA 2026.11.1 es la referencia; las formas de respuesta están en
  research con el fichero de HA de donde salen.

## Criterios de éxito *(obligatorio)*

- **SC-001**: Con la configuración por defecto se registran las 14 tools
  nuevas y las de antes siguen idénticas (nombres, anotaciones, esquemas).
- **SC-002**: Las 17 entradas de FR-012 son `dedicated` hacia una tool
  registrada de su familia, y regenerar la tabla no cambia ni un byte.
- **SC-003**: El 100 % de las llamadas sin token a las tres tools que
  modifican no envían ninguna escritura a HA; un token no sirve con otros
  argumentos ni con otro contenido descargado.
- **SC-004**: Ningún centinela de secreto aparece en respuestas, vistas
  previas, errores, log de Hermes ni ficheros de token de estas tools (con la
  excepción de FR-015 para el documento omitible de `ha_save_blueprint`).
- **SC-005**: Las tres tools que modifican pasan en el banco con el efecto
  comprobado por el lector; FR-010 rechaza en el banco una automatización
  inválida sin token.
- **SC-006**: Cada FR tiene su test, y cada comportamiento con riesgo, su
  control negativo anotado.
- **SC-007**: La suite pasa en el CI de Linux al final de cada tramo, con
  exactamente los 6 fallos conocidos de Windows en local.
