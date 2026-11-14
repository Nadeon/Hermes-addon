# Especificación: Hermes 1.0.12 — correcciones frente a HA 2026.11

**Directorio de la spec**: `specs/001-correcciones-1-0-12`

**Creada**: 2026-11-14

**Estado**: Lista para planificar

**Entrada**: descripción del mantenedor: «Versión 1.0.12, solo arreglos: safety backup y estado de jobs (R1, R2), alias de entidades (P1, R6), borrado de dispositivos (P2), dashboard principal (P3, C2), `trace` en scripts (R5), versión mínima (R4, C8), errores por código (D1, C6), avisos de plantillas (D2), dispositivos hijo (D3), campos del Supervisor (D4), `lovelace/resources/list`, mensaje claro de HACS (R3), filtro de `ha_list_services` (D5), docstrings y guía (C1, C3, C4, C5) y documentación (Funnel en 8443/10000, CHANGELOG, versión, hoja de ruta)».

Los identificadores entre corchetes (P1, R1, D1, C1…) son los de la revisión de
compatibilidad de noviembre de 2026, resumida en `docs/HOJA-DE-RUTA.md`. Cada
requisito funcional cita el suyo para que se pueda trazar.

## Clarificaciones

### Sesión 2026-11-14

No se ha preguntado al mantenedor: estaba ausente y había dejado decisiones
tomadas. Las dudas se resolvieron así:

- P: ¿Se sube la versión mínima de Home Assistant o se normaliza la configuración según la versión? → R: se sube a **2024.10.0** (decisión del mantenedor).
- P: ¿La protección del dashboard principal admite una opción para saltársela? → R: **no**; se protege siempre y sin opción (decisión del mantenedor). Quien quiera borrarlo tiene la interfaz de HA.
- P: ¿Se cambia el comportamiento de `ha_remove_device_from_config_entry` o se crea una tool nueva? → R: tool nueva **`ha_remove_device`**; la antigua se mantiene, deprecada y con una descripción veraz, hasta antes de HA 2027.9 (decisión del mantenedor).
- P: ¿Se migran las tools de HACS al Marketplace? → R: **no en 1.0.12**; solo un mensaje claro. La migración es de 1.1.0 (decisión del mantenedor).
- P: ¿En qué puerto se recomienda publicar Hermes con Tailscale Funnel? → R: **8443 o 10000**, no 443 (decisión del mantenedor).
- P: ¿Qué pasa con la escritura si el safety backup no termina en el plazo? → R: la escritura en curso se bloquea (fail-closed), pero el backup lanzado queda anotado para no lanzar otro en la siguiente escritura. Ver Supuesto S-01.
- P: ¿Qué hace `ha_remove_device` en un HA anterior a 2026.9, donde no existe el comando de borrado? → R: usa el comando antiguo con la única integración del dispositivo; si tiene varias, se niega. Ver Supuesto S-02.

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es quien administra su Home Assistant a través de un cliente MCP
(un modelo de lenguaje) que llama a las tools de Hermes. Las historias están
ordenadas por gravedad del fallo que corrigen.

### Historia 1 — Escribir ficheros con el safety backup activado (Prioridad: P1)

Quien activa `safety_backup_enabled` quiere que, antes de cada escritura de
fichero, Hermes haga una copia completa y que, si la copia sale bien, la
escritura se haga. Hoy ninguna escritura llega a ejecutarse, cada intento tarda
unos 5 minutos y deja un backup completo nuevo en disco. Además, al consultar un
job que ha fallado, Hermes lo da por bueno.

**Por qué esta prioridad**: el fallo inutiliza una función de seguridad, llena
el disco y puede llevar al usuario a creer que tiene un backup que no existe
justo antes de una acción destructiva.

**Prueba independiente**: con un Supervisor simulado que devuelve un `job_id` y
después el estado real del job, una escritura de fichero se completa cuando el
job termina sin errores y se rechaza, con el motivo, cuando termina con errores.

**Escenarios de aceptación**:

1. **Dado** `safety_backup_enabled: true` y ningún safety backup en la ventana, **cuando** el agente escribe un fichero y el job del backup termina sin errores, **entonces** el fichero se escribe y queda anotado el backup.
2. **Dado** lo mismo, **cuando** el job termina con errores, **entonces** el fichero no se escribe y la respuesta incluye los mensajes de error del job.
3. **Dado** un backup que no termina en el plazo, **cuando** el agente vuelve a escribir dentro de la ventana, **entonces** Hermes no lanza un segundo backup completo: informa de que hay uno en curso o, si ya terminó bien, escribe.
4. **Dado** un job del Supervisor que ha fallado, **cuando** el agente consulta `sv_get_job_status`, **entonces** la respuesta dice `success: false` y trae los errores, y `sv_list_pending_jobs` lo marca como `failed`.

---

### Historia 2 — Editar los alias y el nombre de una entidad sin estropearla (Prioridad: P1)

El agente lee la entrada de una entidad, añade un alias y la guarda. Hoy el
marcador de «nombre calculado» (`null`) se guarda como el texto `"None"` y la
entidad deja de responder a su nombre por voz.

**Por qué esta prioridad**: corrompe datos en silencio, sin error, en el flujo
más natural (leer, modificar, guardar).

**Prueba independiente**: enviar `aliases: [null, "lámpara"]` y comprobar que a
Home Assistant le llega exactamente `[null, "lámpara"]`.

**Escenarios de aceptación**:

1. **Dado** una entidad con `aliases: [null]`, **cuando** el agente envía `aliases: [null, "lámpara"]`, **entonces** Home Assistant recibe `[null, "lámpara"]`.
2. **Dado** cualquier entidad, **cuando** el agente envía `aliases: null`, **entonces** Hermes lo rechaza antes de llamar a Home Assistant y explica que se use `[]` para vaciar o `[null]` para dejar solo el nombre calculado.
3. **Dado** una entidad que no existe, **cuando** el agente pide su entrada del registro, **entonces** recibe `{"error": "not_found", "entity_id": …}` y no el texto crudo de Home Assistant.

---

### Historia 3 — Borrar un dispositivo sabiendo lo que se borra (Prioridad: P1)

El agente quiere quitar un dispositivo fantasma. Hoy la única tool para ello
anuncia que «desasocia» el dispositivo de una integración, pero en HA ≥ 2026.9
lo borra entero. Además, los dispositivos hijo (HA 2026.9) quedan fuera de los
filtros por área y de los recuentos que ven las vistas previas.

**Por qué esta prioridad**: la vista previa es la única revisión humana antes de
una acción destructiva; si miente, la confirmación no protege.

**Prueba independiente**: la vista previa de `ha_remove_device` dice que borra
el dispositivo y cuántas entidades se van con él, y la ejecución confirmada
envía el comando de borrado adecuado a la versión de HA.

**Escenarios de aceptación**:

1. **Dado** HA ≥ 2026.9, **cuando** el agente pide `ha_remove_device(device_id)`, **entonces** la vista previa anuncia el borrado del dispositivo del registro junto con sus entidades, y la ejecución confirmada usa el comando de borrado de dispositivos.
2. **Dado** HA < 2026.9 y un dispositivo con una sola integración, **cuando** se confirma `ha_remove_device`, **entonces** Hermes usa el comando antiguo con esa integración, y la vista previa lo dice.
3. **Dado** HA < 2026.9 y un dispositivo con varias integraciones, **cuando** se pide `ha_remove_device`, **entonces** Hermes se niega sin ejecutar nada y explica por qué.
4. **Dado** cualquier versión, **cuando** se pide `ha_remove_device_from_config_entry`, **entonces** su descripción y su vista previa dicen que la tool está deprecada, que en HA ≥ 2026.9 borra el dispositivo entero y que se use `ha_remove_device`.
5. **Dado** un dispositivo hijo sin área propia cuyo padre está en el área X, **cuando** el agente filtra dispositivos por el área X, **entonces** el hijo aparece.
6. **Dado** una integración con dispositivos hijo, **cuando** el agente pide la vista previa de deshabilitarla o borrarla, **entonces** el recuento de dispositivos los incluye.

---

### Historia 4 — Que el dashboard principal no se pueda borrar (Prioridad: P1)

En las instalaciones cuyo dashboard principal se migró en HA 2026.2, ese
dashboard aparece dos veces en la lista y se puede borrar con un token. Sus
vistas solo se recuperan de un backup.

**Por qué esta prioridad**: pérdida de datos, inducida por la propia
documentación de la tool, que dice que el principal no se puede borrar.

**Prueba independiente**: pedir el borrado del dashboard `lovelace` y del panel
por defecto siempre devuelve un error y nunca un token.

**Escenarios de aceptación**:

1. **Dado** un dashboard `lovelace`, **cuando** el agente pide borrarlo, **entonces** Hermes lo rechaza sin emitir token, con o sin token previo.
2. **Dado** un panel por defecto configurado con otro dashboard, **cuando** el agente pide borrar ese dashboard, **entonces** Hermes lo rechaza.
3. **Dado** que no se puede saber cuál es el panel por defecto, **cuando** el agente pide borrar cualquier dashboard, **entonces** Hermes lo rechaza y explica el motivo (fail-closed).
4. **Dado** un dashboard `lovelace`, **cuando** el agente lista los dashboards, **entonces** el principal aparece una sola vez, marcado como `is_default`.
5. **Dado** cualquier instalación, **cuando** el agente lista los recursos de Lovelace, **entonces** Hermes usa el comando vigente, no el alias deprecado.

---

### Historia 5 — Guardar scripts y automatizaciones en las versiones declaradas (Prioridad: P2)

Un script con `trace` no se puede volver a guardar; con HA 2024.1–2024.9 no se
puede guardar ninguna automatización aunque Hermes declare compatibilidad; y
`period: "year"` en estadísticas falla con un error de esquema en HA < 2026.3.

**Por qué esta prioridad**: funcionalidad rota, sin pérdida de datos.

**Prueba independiente**: leer y reescribir un script con
`trace: {stored_traces: 20}` funciona; Hermes no arranca con HA < 2024.10.

**Escenarios de aceptación**:

1. **Dado** un script con `trace: {"stored_traces": 20}`, **cuando** el agente lo guarda, **entonces** pasa la validación de Hermes y llega a Home Assistant.
2. **Dado** HA 2024.9, **cuando** Hermes arranca, **entonces** se detiene con el mensaje de versión mínima 2024.10.0.
3. **Dado** HA 2026.2, **cuando** el agente pide estadísticas con `period: "year"`, **entonces** recibe un error claro que nombra la versión mínima, no un error de esquema.

---

### Historia 6 — Respuestas veraces en errores, plantillas, servicios y HACS (Prioridad: P2)

Borrar un helper inexistente da un error genérico; una plantilla que solo genera
un aviso pierde su resultado; el timeout de una plantilla en HA no se reconoce;
`ha_list_services` devuelve unos 100 KB sin filtro; y las tools de HACS en HA ≥
2026.11 dicen «Unknown command» y sugieren actualizar Hermes.

**Por qué esta prioridad**: degradan la experiencia y hacen que el agente tome
decisiones con información falsa, pero no rompen datos.

**Prueba independiente**: con Home Assistant simulado, cada caso devuelve la
forma documentada (`not_found`, `warnings` junto al resultado,
`template_timeout`, lista filtrada, mensaje del Marketplace).

**Escenarios de aceptación**:

1. **Dado** un helper inexistente, **cuando** el agente lo borra con token, **entonces** recibe `not_found`.
2. **Dado** una plantilla con una variable indefinida y `strict=false`, **cuando** el agente la renderiza, **entonces** recibe el resultado y los avisos en `warnings`.
3. **Dado** una plantilla que agota el tiempo en Home Assistant, **cuando** el agente la renderiza, **entonces** recibe `template_timeout`.
4. **Dado** cualquier instalación, **cuando** el agente pide `ha_list_services(domain="light")`, **entonces** solo recibe los servicios de `light`.
5. **Dado** HA ≥ 2026.11, **cuando** el agente llama a una tool `ha_hacs_*`, **entonces** recibe un error que explica que HACS se integró en el Marketplace y que use las entidades `update`.

---

### Historia 7 — Información del sistema correcta (Prioridad: P3)

`sv_get_supervisor_info` y `sv_get_host_info` devuelven siempre `null` en la
máquina, la versión de Docker y el kernel; varias descripciones de tools
prometen campos que no existen.

**Por qué esta prioridad**: degradación menor y documentación.

**Prueba independiente**: con un Supervisor simulado con las claves reales, los
tres campos llegan rellenos.

**Escenarios de aceptación**:

1. **Dado** un Supervisor con `machine` y `docker` en `GET /info` y `kernel` en `GET /host/info`, **cuando** el agente pide la información, **entonces** `machine`, `docker_version` y `kernel_version` vienen rellenos.
2. **Dado** que `GET /info` falla, **cuando** el agente pide la información del Supervisor, **entonces** recibe el resto de campos y esos dos a `null`, no un error.

---

### Historia 8 — Documentación y publicación coherentes (Prioridad: P3)

Quien instala Hermes con Tailscale y además publica Home Assistant con
`share_homeassistant: funnel` choca en el puerto 443. La guía de Hermes enseña
sintaxis heredada. La versión, el CHANGELOG y la hoja de ruta deben reflejar la
1.0.12.

**Por qué esta prioridad**: no cambia el comportamiento del código, pero sin
ello la versión no se puede publicar (principio XI).

**Prueba independiente**: el test de coherencia de versiones pasa y los README
recomiendan 8443/10000.

**Escenarios de aceptación**:

1. **Dado** el README en inglés o en español, **cuando** el usuario sigue la opción de Tailscale Funnel, **entonces** se le recomienda 8443 o 10000, con `public_hostname` acabado en `:8443` o `:10000`.
2. **Dado** el repositorio, **cuando** se ejecuta la suite, **entonces** la versión es 1.0.12 en `config.yaml`, en `__init__.py` y en `HA_CORE_LAST_TESTED_IN_HERMES`.

---

### Casos límite

- El job del safety backup desaparece del Supervisor (404) mientras se sondea: se trata como estado indeterminado; la escritura se bloquea y la marca pendiente se invalida.
- `errors` del job trae objetos sin `message` o tipos inesperados: se devuelve un texto genérico por error, nunca el objeto crudo (principio I).
- `aliases` con elementos que no son texto ni `null` (números, listas): los números se convierten a texto como hasta ahora; listas y diccionarios se rechazan.
- La versión de Home Assistant no se puede leer (WebSocket caído, respuesta rara, versión de desarrollo): las decisiones que protegen datos fallan cerradas (`ha_remove_device` se niega); las de solo lectura dejan decidir a Home Assistant.
- Cadena de dispositivos padre-hijo con un ciclo o más profunda de lo razonable: la resolución del área efectiva se corta y no cuenta el área como coincidente.
- El panel por defecto apunta a un panel que no es un dashboard (por ejemplo, `map` o `energy`): la protección se aplica igual al `url_path` que coincida, si lo hay.
- `ha_list_services` con un dominio inexistente: lista vacía.
- HACS en HA < 2026.11 responde «Unknown command»: el mensaje dice que HACS no está instalado, sin hablar del Marketplace.

## Requisitos *(obligatorio)*

### Requisitos funcionales

**Supervisor, jobs y safety backup**

- **FR-001** [R1]: El safety backup automático DEBE consultar el estado del job en la ruta que existe en el Supervisor (el job por su identificador), no en una ruta inexistente.
- **FR-002** [R1]: El safety backup DEBE considerarse correcto solo si el job está terminado (`done`) y su lista de errores (`errors`) está vacía; un job terminado con errores DEBE bloquear la escritura y devolver los mensajes de error saneados.
- **FR-003** [R1]: Hermes DEBE anotar el safety backup en cuanto el Supervisor acepta el job, como pendiente y con su identificador, de modo que un timeout no provoque otro backup completo en la escritura siguiente dentro de la ventana.
- **FR-004** [R1]: Con una anotación pendiente, la escritura siguiente DEBE consultar ese job: si terminó sin errores, la anotación pasa a correcta y la escritura sigue; si sigue en curso, la escritura se rechaza con `safety_backup_in_progress`; si terminó con errores o no se puede consultar, la anotación se invalida y la escritura se rechaza sin lanzar otro backup en esa misma llamada.
- **FR-005** [R1]: Si el plazo de espera se agota, la escritura en curso DEBE bloquearse (fail-closed) con un error que incluya el identificador del job para consultarlo con `sv_get_job_status`.
- **FR-006** [R2]: `sv_get_job_status` DEBE devolver `errors` (lista de mensajes saneados) y `success` (`true` solo si el job está terminado y sin errores; `false` si terminó con errores; `null` si no ha terminado).
- **FR-007** [R2]: El registro local de jobs DEBE marcar como `failed` un job terminado con errores, y `sv_list_pending_jobs` DEBE mostrarlo así.
- **FR-008** [D4]: `sv_get_supervisor_info` DEBE rellenar `machine` y `docker_version` con los valores reales del Supervisor (la información general del sistema), conservando los nombres de campo actuales; si esa lectura falla, esos campos van a `null` y el resto de la respuesta se mantiene.
- **FR-009** [D4]: `sv_get_host_info` DEBE rellenar `kernel_version` con la clave real del kernel, y su descripción DEBE decir que `boot_timestamp` es un entero en microsegundos y que `disk_*` va en GiB.
- **FR-010** [C3]: Las descripciones de `sv_get_addon_stats` (`blk_read`/`blk_write` en lugar de `disk_*`) y de `sv_list_backups` (`location: null` significa almacenamiento local; `protected` es el de la primera ubicación) DEBEN coincidir con la respuesta real.

**Registros de entidades y dispositivos**

- **FR-011** [P1]: Al actualizar el registro de una entidad, cada `null` dentro de `aliases` DEBE llegar a Home Assistant como `null`; los textos, como texto.
- **FR-012** [R6]: Hermes DEBE rechazar `aliases: null` (sin lista) antes de llamar a Home Assistant, con un mensaje que indique `[]` para vaciar y `[null]` para dejar solo el nombre calculado.
- **FR-013** [P1, R6]: La descripción de `ha_update_entity_registry` DEBE explicar que `null` dentro de `aliases` es el nombre calculado, que la lista sustituye a la anterior y que, para añadir un alias, hay que conservar el `null` leído.
- **FR-014** [C1]: La descripción de `ha_update_entity_registry` DEBE avisar de que, desde HA 2026.11, `name` es solo la parte de la entidad y Home Assistant antepone el nombre del dispositivo.
- **FR-015** [C6, D1]: `ha_get_entity_registry` de una entidad inexistente DEBE devolver `{"error": "not_found", "entity_id": …}`, decidido por el código de error de Home Assistant, no por el texto.
- **FR-016** [P2]: DEBE existir la tool `ha_remove_device(device_id)`, destructiva y con `confirmation_token`, cuya vista previa diga que borra el dispositivo del registro junto con sus entidades del registro, cuántas entidades son, que la integración debe permitir el borrado manual y que puede volver a aparecer si la integración lo redescubre.
- **FR-017** [P2]: `ha_remove_device` DEBE usar el comando de borrado de dispositivos si la versión de Home Assistant es ≥ 2026.9; si es anterior, el comando antiguo con la única integración del dispositivo, y negarse si tiene varias. La vista previa DEBE decir cuál de los dos caminos se va a usar.
- **FR-018** [P2]: Si no se puede determinar la versión de Home Assistant, `ha_remove_device` DEBE negarse (fail-closed) sin emitir token.
- **FR-019** [P2]: `ha_remove_device_from_config_entry` DEBE seguir existiendo con el mismo comportamiento de envío, pero su descripción y su vista previa DEBEN decir que está deprecada, que se retirará antes de HA 2027.9, que en HA ≥ 2026.9 borra el dispositivo entero si la integración es la suya y que se use `ha_remove_device`.
- **FR-020** [D3]: El filtro por área de `ha_list_devices` DEBE usar el área efectiva: la propia o, en un dispositivo hijo sin área, la de su padre (recursivamente, con límite y protección frente a ciclos).
- **FR-021** [D3]: El filtro por área de `ha_list_entities_registry` DEBE incluir las entidades sin área propia cuyo dispositivo tiene esa área efectiva.
- **FR-022** [D3]: El recuento de dispositivos de la vista previa de `ha_delete_area` DEBE usar el área efectiva.
- **FR-023** [D3]: Los recuentos de dispositivos por integración (vistas previas de deshabilitar y borrar una integración) DEBEN usar `config_entry_id` y, como respaldo, `config_entries`, sin contar dos veces el mismo dispositivo, de forma que sigan funcionando cuando HA retire `config_entries` (2027.8).
- **FR-024** [D3]: La descripción de `ha_list_devices` DEBE decir que los dispositivos hijo no tienen fabricante y quedan fuera del filtro `manufacturer`, y DEBE nombrar `config_entry_id` como el campo vigente.

**Lovelace**

- **FR-025** [P3]: `ha_delete_lovelace_dashboard` DEBE rechazar siempre, sin emitir token y sin opción para saltárselo, el borrado del dashboard principal: `url_path` nulo, `lovelace` y el dashboard que sea el panel por defecto.
- **FR-026** [P3]: Si Hermes no puede determinar el panel por defecto (error de lectura o respuesta con forma inesperada), DEBE rechazar el borrado (fail-closed). Si la versión de Home Assistant no tiene esa información (comando desconocido), la protección se limita a `url_path` nulo y `lovelace`.
- **FR-027** [P3]: Las descripciones de `ha_delete_lovelace_dashboard` y `ha_list_lovelace_dashboards` DEBEN decir qué dashboards están protegidos y por qué.
- **FR-028** [C2]: Si existe el dashboard `lovelace`, `ha_list_lovelace_dashboards` NO DEBE añadir el «Default» sintético y DEBE marcar `lovelace` con `is_default: true`.
- **FR-029** [lovelace/resources]: `ha_list_lovelace_resources` DEBE usar el comando vigente de listado de recursos, no el alias deprecado.

**Automatizaciones, scripts, plantillas, errores, servicios, estadísticas y HACS**

- **FR-030** [D1]: Los errores que devuelve Home Assistant por WebSocket DEBEN conservar su código (`not_found`, `unknown_command`, `invalid_format`…) para que las tools decidan por código.
- **FR-031** [D1]: Borrar un helper, zona o persona inexistente DEBE devolver `not_found`, decidido por el código de error.
- **FR-032** [R5]: La validación de scripts DEBE aceptar `trace` como diccionario y rechazar una lista.
- **FR-033** [D2]: `ha_render_template` DEBE devolver el resultado junto con los avisos de nivel `WARNING` en `warnings`, en lugar de convertir el primer aviso en error.
- **FR-034** [D2]: `ha_render_template` DEBE devolver `template_timeout` también cuando el timeout lo informa Home Assistant.
- **FR-035** [D5]: `ha_list_services` DEBE aceptar un parámetro `domain` opcional que limite la respuesta a ese dominio; un dominio inexistente devuelve una lista vacía. Su descripción DEBE recomendar usar el filtro.
- **FR-036** [C8]: `ha_statistics_during_period` con `period: "year"` y Home Assistant < 2026.3 DEBE devolver un error claro que nombre la versión mínima; si la versión no se puede determinar, decide Home Assistant.
- **FR-037** [C3]: La descripción de `ha_list_statistic_ids` DEBE enumerar los campos reales (`display_unit_of_measurement`, `statistics_unit_of_measurement`, `unit_class`, `mean_type`, `has_sum`…) y avisar de que `has_mean` está deprecado.
- **FR-038** [R3]: Las tools `ha_hacs_*` DEBEN devolver, cuando Home Assistant responde «comando desconocido» y su versión es ≥ 2026.11, un error que explique que HACS está integrado en el Marketplace y que las actualizaciones se ven con las entidades `update`; con una versión anterior, que HACS no está instalado. Ninguno de los dos mensajes sugiere actualizar Hermes.
- **FR-039** [C5]: Las categorías válidas de HACS DEBEN ser las reales (con `template`, sin `netdaemon`), y `ha_hacs_list_updates` DEBE usar `pending_upgrade` cuando HACS lo devuelve.
- **FR-040** [C4]: El comentario sobre `perform_action` y su test DEBEN dejar de afirmar que es un alias de Home Assistant; la clave se conserva en la detección como defensa en profundidad.

**Integración, versión y documentación**

- **FR-041** [R4]: La versión mínima de Home Assistant DEBE ser 2024.10.0, en el código y en los README (requisitos y tabla de problemas).
- **FR-042** [C4]: La guía de Hermes DEBE enseñar la sintaxis vigente de automatizaciones (`triggers`/`trigger:`, `actions`/`action:`) y mencionar `ha_remove_device`.
- **FR-043** [Decisión 12]: Los README en inglés y en español DEBEN recomendar publicar Hermes con Tailscale Funnel en 8443 o 10000 en lugar de 443, con el `public_hostname` correspondiente, y explicar cómo pasar de 443 a 8443.
- **FR-044** [Principio XI]: La versión DEBE ser 1.0.12 en `config.yaml`, en `__init__.py` y en `HA_CORE_LAST_TESTED_IN_HERMES`, con entrada `## [1.0.12] — 2026-11-14` en el CHANGELOG.
- **FR-045** [Principio XI]: `docs/HOJA-DE-RUTA.md` DEBE reflejar qué problemas corrige la 1.0.12 y cuáles quedan para 1.1.0 o después.
- **FR-046** [Principios VI, VII]: Cada arreglo DEBE tener un test de regresión que falle sin el arreglo, y ese control negativo DEBE quedar documentado.
- **FR-047** [Principio VIII]: Ningún fichero modificado DEBE contener datos personales ni de ninguna instalación concreta, ni identificadores de modelos de IA.

### Entidades clave

- **Anotación del safety backup**: momento y nombre del último safety backup correcto y, aparte, el backup pendiente (identificador del job, momento en que se lanzó y nombre). Vive en el almacenamiento persistente del add-on.
- **Job del Supervisor**: identificador, nombre, progreso, etapa, `done`, `errors` (lista de mensajes), referencia y jobs hijos.
- **Registro local de jobs**: los jobs que lanzó Hermes en la última hora, con su operación y su estado (`running`, `done`, `failed`).
- **Entrada del registro de entidad**: `aliases` (lista de textos y `null`, donde `null` es el nombre calculado), `name`, `area_id`, `device_id`.
- **Dispositivo**: normal o hijo; el hijo tiene `parent_device_id`, `config_entry_id` y no tiene fabricante ni `config_entries`. Área efectiva = la propia o la del padre.
- **Dashboard**: `url_path`, `id`, `mode`, `is_default`. Protegidos: el de `url_path` nulo, `lovelace` y el panel por defecto.
- **Versión de Home Assistant**: la que informa el propio Home Assistant en tiempo de ejecución; condiciona el camino de `ha_remove_device`, `period: "year"` y el mensaje de HACS.

## Criterios de éxito *(obligatorio)*

### Resultados medibles

- **SC-001**: Con el safety backup activado y un backup que termina bien, el 100 % de las escrituras de fichero de las pruebas se ejecutan en el primer intento, y nunca se lanza más de un backup completo por ventana.
- **SC-002**: El 100 % de los jobs fallidos simulados aparecen como `success: false`, con sus errores, tanto en el safety backup como en `sv_get_job_status` y `sv_list_pending_jobs`.
- **SC-003**: Tras leer y reenviar los alias de una entidad, el número de alias `"None"` creados es 0.
- **SC-004**: Las tres acciones destructivas afectadas (borrado de dispositivo por las dos tools y borrado de dashboard) anuncian en su vista previa exactamente el efecto que ejecutan; 0 discrepancias en las pruebas.
- **SC-005**: El 100 % de los intentos de borrar el dashboard principal (nulo, `lovelace`, panel por defecto o panel por defecto indeterminado) se rechazan sin emitir token.
- **SC-006**: Cada uno de los arreglos de esta spec tiene al menos un test que falla con el arreglo deshecho, y el número de tests que caen queda escrito en el commit o en el PR.
- **SC-007**: Con `domain`, la respuesta de `ha_list_services` contiene solo el dominio pedido; en las pruebas, menos del 10 % del tamaño de la respuesta completa.
- **SC-008**: La suite completa pasa y el test de coherencia de versiones confirma 1.0.12 en los tres sitios.
- **SC-009**: Una búsqueda de datos personales y de identificadores de modelos de IA en el diff de la versión da 0 coincidencias.

## Supuestos

- **S-01** (safety backup): la anotación se escribe al lanzar el job, como pendiente. La escritura que agota el plazo se bloquea. La siguiente consulta el job pendiente y no lanza otro backup en la misma llamada aunque el pendiente haya fallado, para no encadenar backups completos; el siguiente intento ya puede lanzarlo, respetando el límite duro de 60 s y la ventana.
- **S-02** (`ha_remove_device` en HA < 2026.9): el comando antiguo con la única integración del dispositivo hace que Home Assistant lo borre al quedarse sin integraciones. Con varias integraciones no hay forma de borrarlo con un solo comando veraz, así que la tool se niega y remite a la tool antigua por integración.
- **S-03** (versión de HA): se lee en tiempo de ejecución del propio Home Assistant cada vez que una tool la necesita, sin caché, porque HA se puede actualizar sin reiniciar Hermes. Las versiones de desarrollo se comparan por su número base.
- **S-04** (panel por defecto): se lee de los datos de sistema del frontend (`frontend/get_system_data`, clave `core`, campo `default_panel`; existe desde HA 2025.12). El formato exacto de la respuesta se comprueba contra el código de HA al implementar; cualquier forma inesperada falla cerrada.
- **S-05** (borrado de dispositivo): al borrar un dispositivo del registro, Home Assistant borra también las entradas del registro de sus entidades; la vista previa las cuenta con el registro de entidades.
- **S-06** (D4): se conservan los nombres de campo `machine`, `docker_version` y `kernel_version` para no romper a clientes existentes; solo cambia de dónde se leen.
- **S-07** (C3 backups): `sv_list_backups` solo cambia su descripción; no traduce `null` a `.local` ni añade campos, para no cambiar la forma de la respuesta en una versión de arreglos.
- **S-08** (fabricante): los dispositivos hijo no heredan el fabricante del padre, porque pueden ser de otro fabricante; quedan fuera del filtro y la descripción lo dice.
- **S-09** (`perform_action`): no es una clave de Home Assistant, pero se mantiene en la detección de servicios peligrosos; solo puede dar falsos positivos.
- **S-10** (Funnel en 8443): `public_hostname` ya admite `:puerto`, así que no hace falta cambiar código. Se supone, sin haberlo verificado, que los clientes MCP aceptan URL con puerto distinto de 443. Quien no publique Home Assistant con `share_homeassistant: funnel` puede seguir en 443, y los README lo dicen.
- **S-11** (`HA_CORE_LAST_TESTED`): sigue en 2026.11.1. No se repite la prueba en vivo; solo se actualiza la pareja `HA_CORE_LAST_TESTED_IN_HERMES`.
- **S-12** (alcance): quedan fuera C7 (formas distintas de las respuestas de lista: cambiarlas rompe el contrato), C9 (log y redacción de red: decisión 10 pendiente), los riesgos de §2.5 del informe (borrado de backups en todas las ubicaciones, retención de safety backups, etc.), la migración al Marketplace (1.1.0), y todo lo de CI, `Dockerfile` y `build.yaml`, que trata la spec 002.
- **S-13** (`ha_list_services`): sin `domain`, la respuesta no cambia, para no romper a clientes existentes.
- **S-14** (`ha_list_entities_registry`): el área efectiva de una entidad incluye la heredada de su dispositivo, también de dispositivos normales. Es la semántica de Home Assistant; antes Hermes solo miraba el área propia de la entidad.
