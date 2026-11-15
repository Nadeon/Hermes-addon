# Especificación: Hermes 1.2.0 — control de Core y del Supervisor (sub-feature 022)

**Directorio de la spec**: `specs/022-control-de-core-y-supervisor`

**Creada**: 2026-11-15

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T020 de su `tasks.md` y cubre **CAP-084 y la escritura
de CAP-087 con tools dedicadas, y CAP-091, CAP-092 y CAP-094 por la tabla**
(FR-076…FR-080 de la 008). Depende de la 013 (lectura de CAP-087, fixture del
Supervisor simulado) y de la 011 (tabla, genéricas y familias).

**Entrada**: `specs/008-cobertura-total/` (spec, plan con la matriz de
trazabilidad, research CAP-084…CAP-094 y R-4, `inventario/supervisor-rutas.tsv`),
las specs 011, 013, 014, 018 y 033, y el código de Hermes: `tools/supervisor.py`
(`sv_restart_core`, `sv_reboot_host`), `tools/resolution.py`, `tools/addons.py`
(`_es_hermes`), `fs_write.py` (`check_restart_allowed_sync`), `security.py`
(token con `estado`), `health.py`, `ha.py` (`sv_request`), `command_table.py`,
`tool_families.py`, `tools/_annotations.py` y `tools/guide.py`. Contrastado con
el código del Supervisor 2026.11.0 (`api/homeassistant.py`, `api/supervisor.py`,
`api/resolution.py`, `api/docker.py`, `api/os.py`, `api/time.py`,
`api/dns.py`, `api/multicast.py`, `homeassistant/core.py`, `core.py`,
`supervisor.py`, `docker/manager.py`, `resolution/module.py`,
`resolution/fixup.py`, `resolution/fixups/*.py`).

## Clarificaciones

### Sesión 2026-11-15

Decisiones vinculantes del programa (están en la 008, en la 011 y en los
criterios del supervisor del programa):

- CAP-084 y la escritura de CAP-087 van por **tools dedicadas**; CAP-091,
  CAP-092 y CAP-094, **por la tabla** con las genéricas.
- Lo que ya existe o llega en otra sub-feature **no se duplica**:
  `sv_restart_core`, `sv_check_core_config`, `sv_reboot_host`,
  `sv_restart_addon` (1.1.2); actualizaciones (015); diagnósticos (012 y 013);
  tienda de apps (030); montajes y opciones de backup (019); host y red (032).
- Todo lo que **interrumpe el servicio** se confirma en dos pasos con una vista
  previa honesta de qué se corta y durante cuánto, y el token ata todos los
  argumentos que cambian la acción.
- Lo que la 008 dejó en clase D o como candidata D sigue **`deny`**:
  `POST /core/stop` y el `channel` del Supervisor (D-01).
- Las tools nuevas van en **familias nuevas** de la 1.2.0 (FR-010 de la 008).
- Las `sv_*` nuevas se prueban con el **Supervisor simulado** y van a la matriz
  de la 014 como `VM | pendiente`.

Decisiones tomadas al especificar (justificadas en [research.md](research.md)):

- P: ¿Una familia o dos? → R: **dos**: `system_control` (siete tools de Core y
  del Supervisor) y `resolution_fixes` (aplicar sugerencias), para poder
  apagar por separado lo más arriesgado (R-1).
- P: ¿Estadísticas con tool? → R: **no**: FR-076 de la 008 las pone `read` en
  la tabla, aunque su research proponía tools (R-2).
- P: ¿Y `POST /host/reload`, que está en CAP-084 pero no en FR-076? → R:
  **`confirm` por la tabla**, sin tool (R-2).
- P: ¿Qué opciones de Core? → R: lista cerrada: `boot`, `watchdog`,
  `backups_exclude_database`, `duplicate_log_file`, `audio_input`,
  `audio_output`. Nunca `image`, `refresh_token`, `port` ni `ssl` (R-3).
- P: ¿Qué opciones del Supervisor? → R: las cinco de FR-076 (`timezone`,
  `country`, `logging`, `auto_update`, `diagnostics`); el resto, rechazado
  sin llamar (R-4).
- P: ¿Reiniciar o reparar el Supervisor con un job en curso? → R: **rechazo
  sin token** (`jobs_in_progress`): el job se perdería (R-5).
- P: ¿Reconstruir Core con escrituras en `/config` sin validar? → R: el
  **mismo bloqueo** que `sv_restart_core` (R-5).
- P: ¿La política «Hermes nunca aplica sugerencias» de la 1.1.x? → R: **cambia**,
  porque FR-077 de la 008 lo pide; con traducción del efecto, rechazos
  fail-closed y el token atado al estado de la sugerencia (R-6).
- P: ¿Qué sugerencias se rechazan aunque el Supervisor las admita? → R: las
  que no tienen fixup (el Supervisor respondería ok sin hacer nada), las que
  Hermes no sabe traducir, las de disco de datos y las que apuntan al propio
  Hermes (R-6).
- P: ¿Qué hace la 022 con CAP-091, CAP-092 y CAP-094, que la 011 ya
  clasificó? → R: comprobar la clasificación contra el Supervisor 2026.11.0
  (no cambia ninguna entrada) y probarla con el Supervisor simulado, incluida
  la contraseña del registro tapada (R-8).
- P: ¿Tres tramos? → R: **dos**, como dice la 008: el tramo 1 crea las siete
  tools de `system_control` (comparten la ayuda de vista previa y de
  opciones), el tramo 2 la de sugerencias, la tabla y la documentación final.

## Escenarios de usuario y pruebas *(obligatorio)*

Usuario: quien gestiona una instalación de Home Assistant OS a través de un
cliente MCP conectado a Hermes.

### Historia 1 — Recuperar Core sin la interfaz (Prioridad: P1)

Home Assistant no arranca o se quedó parado. El usuario no tiene la interfaz,
pero Hermes sigue vivo (Hermes tolera Core caído). Pide al agente que lo
arranque o, si el contenedor está mal, que lo reconstruya.

**Por qué esta prioridad**: es la recuperación que hoy obliga a entrar por SSH
o por la consola del host.

**Prueba independiente**: con el Supervisor simulado y Core «parado»,
`sv_start_core` da una vista previa y, con el token, llama a `POST /core/start`.

**Escenarios de aceptación**:

1. **Dado** Core parado, **cuando** se llama a `sv_start_core` sin token,
   **entonces** la vista previa dice que Core está parado, qué versión
   arrancará y cuánto suele tardar, y devuelve un token; con el token, Hermes
   llama a `POST /core/start`.
2. **Dado** Core en marcha, **cuando** se llama a `sv_start_core`, **entonces**
   responde `already_running` sin token y sin llamar a `POST /core/start`.
3. **Dado** que hay escrituras en `/config` sin validar, **cuando** se llama a
   `sv_rebuild_core`, **entonces** la vista previa dice que está bloqueado y
   cómo desbloquearlo, y al confirmar no se llama a `POST /core/rebuild`.
4. **Dado** `safe_mode=true` en la vista previa, **cuando** se confirma con
   `safe_mode=false`, **entonces** el token no vale y no se llama al
   Supervisor.
5. **Dado** que el arranque tarda más que el tiempo de espera, **cuando** vence,
   **entonces** la respuesta es `status: "started"` con `verify_with`, nunca
   un ok ni un error inventados.

---

### Historia 2 — Ajustar Core y el Supervisor con una vista previa clara (Prioridad: P2)

El usuario quiere que la base de datos no entre en los backups, desactivar el
arranque automático de Core en una máquina de pruebas, cambiar el país o la
zona horaria del Supervisor, o desactivar sus actualizaciones automáticas.

**Prueba independiente**: con el Supervisor simulado, `sv_set_core_options` y
`sv_set_supervisor_options` enseñan el valor actual y el nuevo de cada clave
y solo envían las claves pedidas.

**Escenarios de aceptación**:

1. **Dado** `{"backups_exclude_database": true}`, **cuando** se llama a
   `sv_set_core_options`, **entonces** la vista previa enseña `false → true`,
   avisa de que los backups ya no llevarán el historial y de que no se
   reinicia nada; con el token, el cuerpo enviado es exactamente esa clave.
2. **Dado** `{"image": "…"}`, `{"refresh_token": "…"}`, `{"port": 8124}` o
   `{"ssl": true}`, **cuando** se llama, **entonces** `not_allowed` con el
   motivo, sin token y sin llamar.
3. **Dado** `{"channel": "beta"}` o `{"debug": true}` en
   `sv_set_supervisor_options`, **entonces** `not_allowed` sin llamar; y
   `sv_call_api("POST", "/supervisor/options", …)` responde
   `use_dedicated_tool`.
4. **Dado** `{"auto_update": false}`, **entonces** la vista previa avisa de
   que, en cuanto salga un Supervisor nuevo, instalar o actualizar apps y
   actualizar Core quedarán bloqueados.
5. **Dado** que entre la vista previa y la confirmación cambió el valor actual
   de una de las claves, **entonces** la confirmación se rechaza sin llamar.
6. **Dado** que nada cambia (los valores pedidos son los actuales),
   **entonces** `no_changes` sin token.

---

### Historia 3 — Reiniciar, recargar o reparar el Supervisor (Prioridad: P2)

El Supervisor se ha quedado en un estado raro, no ve una versión nueva o el
centro de resolución propone reparar.

**Prueba independiente**: con el Supervisor simulado, `sv_reload_supervisor`
llama sin token; `sv_restart_supervisor` y `sv_repair_supervisor` dan vista
previa y se niegan con jobs en curso.

**Escenarios de aceptación**:

1. **Dado** `sv_reload_supervisor`, **entonces** llama a
   `POST /supervisor/reload` sin pedir token y lo dice en su descripción.
2. **Dado** `sv_restart_supervisor` sin token, **entonces** la vista previa
   dice que la API del Supervisor y la conexión de Hermes con Core se cortan
   alrededor de un minuto, que Core y las apps siguen corriendo y que Hermes
   se reconecta solo.
3. **Dado** un job sin terminar en `/jobs/info`, **cuando** se llama a
   `sv_restart_supervisor` o `sv_repair_supervisor`, **entonces**
   `jobs_in_progress` con el nombre de los jobs, sin token y sin llamar.
4. **Dado** que la conexión se corta mientras el Supervisor se reinicia,
   **entonces** la respuesta es `status: "started"` con
   `verify_with: "sv_get_supervisor_info"`.
5. **Dado** `sv_repair_supervisor` sin token, **entonces** la vista previa
   dice que borra imágenes, contenedores parados, caché de builds y volúmenes
   sin usar, que puede descargar imágenes y que puede tardar minutos.

---

### Historia 4 — Aplicar una sugerencia del centro de resolución sabiendo lo que hará (Prioridad: P1)

El centro de resolución propone «reconstruir el contenedor de Core», «borrar
backups completos antiguos» o «reiniciar el host». El usuario quiere que el
agente la aplique, pero solo después de ver qué hará exactamente.

**Prueba independiente**: con el Supervisor simulado, cada par
`(tipo, contexto)` con fixup da una vista previa con `effect`, `interrupts`,
`reversible` y avisos; los rechazos no dan token ni llaman.

**Escenarios de aceptación**:

1. **Dado** una sugerencia `clear_full_backup` con 4 backups completos,
   **entonces** la vista previa lista los 2 que se borrarían (los más
   antiguos) y dice que no se puede deshacer.
2. **Dado** `execute_rebuild`/`core`, **entonces** la vista previa dice que
   Home Assistant se corta unos minutos.
3. **Dado** `execute_remove`/`addon` sobre una app, **entonces** la vista
   previa dice que la app se desinstala con sus datos.
4. **Dado** una sugerencia sobre el propio Hermes, una de disco de datos, una
   sin fixup (`execute_stop`, `registry_login`…) o un uuid inexistente,
   **entonces** el rechazo correspondiente, sin token y sin
   `POST /resolution/suggestion/…`.
5. **Dado** que la sugerencia desaparece o cambia (otra referencia, otra lista
   de backups) entre la vista previa y la confirmación, **entonces** se
   rechaza sin llamar.

---

### Historia 5 — El resto, por la tabla (Prioridad: P3)

Estadísticas de Core y del Supervisor, chequeos del centro de resolución,
plugins (DNS, audio, multicast, observer, CLI), registros y opciones de
Docker, LED de las placas, firmware de la Raspberry Pi y servidores NTP se
manejan con `sv_read_api`/`sv_call_api`.

**Prueba independiente**: con la tabla real y el Supervisor simulado, cada
lectura se ejecuta y cada escritura da vista previa y token.

**Escenarios de aceptación**:

1. **Dado** `sv_read_api("/core/stats")`, **entonces** una llamada `GET` y la
   respuesta redactada.
2. **Dado** `sv_call_api("POST", "/resolution/check/<check>/options",
   {"enabled": false})`, **entonces** vista previa y token; con el token, la
   llamada.
3. **Dado** `sv_call_api("POST", "/docker/registries", {"<host>":
   {"username": "u", "password": <centinela>}})`, **entonces** ni la vista
   previa, ni el log de Hermes, ni un error del Supervisor que repita el
   cuerpo contienen el centinela.
4. **Dado** `sv_call_api("POST", "/core/stop")` o
   `sv_call_api("POST", "/supervisor/options", {"channel": "dev"})`,
   **entonces** el rechazo de la tabla sin llamar.

---

### Historia 6 — Nada de lo que funciona hoy cambia (Prioridad: P1)

**Escenarios de aceptación**:

1. **Dado** las familias de la 1.2.0 desactivadas, **entonces** la lista de
   tools es la de la 1.1.2 (SC-005 de la 011).
2. **Dado** `sv_restart_core`, `sv_reboot_host`, `sv_get_resolution` y las
   dos de descartar, **entonces** sus argumentos, respuestas y anotaciones
   no cambian.

### Casos límite

- Core arrancando (ni parado ni listo): `sv_start_core` lo trata como «en
  marcha» si `/core/stats` responde; si `/core/stats` falla por otra causa,
  el estado es `unknown`, la vista previa lo dice y se puede confirmar (el
  Supervisor no hace nada si ya corre).
- Migración offline de la base de datos: el Supervisor rechaza el rebuild; el
  error vuelve redactado y Hermes no ofrece `force`.
- `sv_set_core_options` con un tipo equivocado (`"boot": "no"`) →
  `invalid_argument` con `field`, sin llamar.
- `timezone` inexistente pero con forma válida: lo rechaza el Supervisor y
  vuelve el error redactado.
- Sugerencia con `reference` vacía en un contexto que la necesita (app,
  montaje, repositorio): la vista previa lo dice; el Supervisor no hará nada
  (`effect` lo avisa).
- `clear_full_backup` con 2 o menos backups completos: la vista previa dice
  que no borrará nada.
- Dos sugerencias `execute_rebuild`/`system` a la vez: cualquiera reconstruye
  todos los contenedores afectados; la vista previa los lista.
- Supervisor que no responde (simulado caído): cada tool devuelve `error`;
  ninguna vista previa se inventa un estado.

## Requisitos *(obligatorio)*

Cada requisito traza a su FR y CAP de la 008 (entre paréntesis).

### Requisitos funcionales

#### Control de Core (CAP-084, FR-076)

- **FR-001**: `sv_start_core(confirmation_token=None)` arranca Core con
  `POST /core/start` en dos pasos. La vista previa lee el estado (en marcha si
  `GET /core/stats` responde; parado si el Supervisor dice que no corre;
  `unknown` si falla de otra forma) y la versión (`/core/info`), y dice cuánto
  suele tardar en estar entero. Con Core en marcha: `already_running` sin
  token y sin llamar; lo mismo si al confirmar ya está en marcha. Si hay
  escrituras sin validar, la vista previa lo avisa sin bloquear (arrancar es
  recuperar). (FR-076, CAP-084)
- **FR-002**: `sv_rebuild_core(safe_mode=False, confirmation_token=None)`
  reconstruye Core con `POST /core/rebuild` (`{"safe_mode": …}`; nunca
  `force`) en dos pasos. La vista previa dice que Home Assistant se corta
  unos minutos, que Hermes sigue vivo y se reconecta, qué significa
  `safe_mode`, y aplica el **mismo bloqueo** que `sv_restart_core` con
  escrituras en `/config` sin validar, en la vista previa y otra vez al
  confirmar. El token ata `safe_mode`. (FR-076, CAP-084)
- **FR-003**: `sv_set_core_options(options, confirmation_token=None)` cambia
  solo `boot`, `watchdog`, `backups_exclude_database`, `duplicate_log_file`
  (booleanos), `audio_input` y `audio_output` (texto o `null`) con
  `POST /core/options` en dos pasos. `image`, `refresh_token`, `port` y `ssl`
  → `not_allowed` con el motivo; cualquier otra clave, `options` vacío o un
  tipo equivocado → `invalid_argument` con `field`; todo sin llamar. La vista
  previa enseña, por clave, el valor actual (`/core/info`) y el nuevo, avisa
  de lo que no tiene efecto hasta el próximo arranque o rebuild, y avisa
  fuerte de `boot=false` y `watchdog=false`. Si nada cambia: `no_changes` sin
  token. El token ata `options` (normalizado) y, como estado, los valores
  actuales de esas claves. (FR-076, CAP-084)

#### Control del Supervisor (CAP-084, FR-076)

- **FR-004**: `sv_reload_supervisor()` llama a `POST /supervisor/reload` **sin
  token** y lo dice en su descripción (FR-076: «salvo recargar»). (FR-076,
  CAP-084)
- **FR-005**: `sv_restart_supervisor(confirmation_token=None)` reinicia el
  Supervisor con `POST /supervisor/restart` en dos pasos. La vista previa
  dice qué se corta (la API del Supervisor y la conexión de Hermes con Core,
  que pasa por él), qué no (Core y las apps), cuánto (alrededor de un minuto)
  y que Hermes se reconecta solo. Con algún job sin terminar en `/jobs/info`:
  `jobs_in_progress` con sus nombres, sin token, en la vista previa y otra vez
  al confirmar. (FR-076, CAP-084)
- **FR-006**: `sv_repair_supervisor(confirmation_token=None)` llama a
  `POST /supervisor/repair` en dos pasos, con la vista previa de lo que hace
  el Supervisor 2026.11.0 (poda de contenedores parados, imágenes, caché de
  builds y volúmenes sin usar; reparación de plugins, apps y Core, que puede
  descargar imágenes; puede tardar minutos) y el mismo rechazo
  `jobs_in_progress`. (FR-076, CAP-084)
- **FR-007**: `sv_set_supervisor_options(options, confirmation_token=None)`
  cambia solo `timezone`, `country`, `logging`, `auto_update` y
  `diagnostics`, con `POST /supervisor/options` en dos pasos y validación de
  forma antes de llamar. `channel`, `debug`, `debug_block`,
  `detect_blocking_io`, `feature_flags`, `addons_repositories` y `wait_boot`
  → `not_allowed` sin llamar. Vista previa con valor actual
  (`/supervisor/info`) y nuevo por clave, avisos de `auto_update=false`,
  `timezone` (también la del host), `diagnostics=true` (informes a un
  tercero) y `logging=debug`; `no_changes` si nada cambia; el token ata
  `options` y, como estado, los valores actuales. (FR-076, CAP-084)
- **FR-008**: las operaciones largas (`start`, `rebuild`, `repair`) esperan
  con un tiempo acotado (600 s, 600 s y 900 s); si vence, o si la conexión se
  corta durante `restart`, la respuesta es `status: "started"` con
  `verify_with`, nunca un ok ni un error inventados. (FR-076, CAP-084;
  principio V)

#### Aplicar sugerencias (CAP-087 escritura, FR-077)

- **FR-009**: `sv_apply_resolution_suggestion(suggestion_uuid,
  confirmation_token=None)` aplica una sugerencia con
  `POST /resolution/suggestion/{uuid}` en dos pasos. La vista previa traduce
  `(type, context)` con la tabla de fixups del Supervisor 2026.11.0 de
  data-model a `effect`, `interrupts`, `duration`, `reversible` y `warnings`,
  e incluye la sugerencia, sus issues y los datos concretos que se pueden leer
  sin escribir (backups que se borrarían, contenedores que se reconstruirían,
  nombre y estado de la app). (FR-077, CAP-087)
- **FR-010**: se rechazan sin token y sin llamar: uuid desconocido
  (`suggestion_not_found`), par sin fixup (`no_fixup`), par que Hermes no
  traduce (`unknown_effect`), `adopt_data_disk` y `rename_data_disk`
  (`not_allowed`), y lo que apunta al propio Hermes (`targets_hermes`). Las
  mismas comprobaciones se repiten al confirmar. (FR-077, CAP-087;
  principio III)
- **FR-011**: el token ata `suggestion_uuid` y, como estado, `type`,
  `context`, `reference` y las listas de la vista previa; si al confirmar algo
  cambió, `suggestion_changed` sin llamar. (FR-077, CAP-087; principio IV)
- **FR-012**: la guarda de `tests/test_tools_resolution.py` pasa de «nadie
  aplica sugerencias» a «solo `tools/resolution_fixes.py` llama a
  `POST /resolution/suggestion/…`»; el docstring de `tools/resolution.py`, el
  tema `diagnostics` de la guía y `README.md`/`README.es.md` dejan de decir que
  Hermes nunca las aplica. (FR-077; principio V)

#### Tabla de clasificación (FR-076…FR-080)

- **FR-013**: las 14 entradas «pendiente de tool dedicada (spec 022)» quedan
  así, con el mecanismo del generador (`_DEDICADAS_INICIALES`) y comprobando
  que la tabla sale idéntica al regenerar: 8 a `dedicated` (las rutas de
  FR-001…FR-007 y FR-009, familia y CAP de su tool); `GET /core/stats` y
  `GET /supervisor/stats` a `read`; `POST /host/reload`,
  `POST /resolution/check/{check}/run`, `/options` y
  `POST /resolution/healthcheck` a `confirm`, estas seis con su porqué en
  `_POR_LA_TABLA`. Ninguna entrada con «spec 022». (FR-076, FR-077; CAP-084,
  CAP-087)
- **FR-014**: `POST /core/stop`, los alias `/homeassistant/*` y, por la tool
  dedicada, el `channel` del Supervisor siguen sin poder usarse por ninguna
  vía; un test lo comprueba. (FR-076; D-01)
- **FR-015**: las rutas de plugins (CAP-091), Docker (CAP-092) y placas y hora
  (CAP-094) mantienen su clasificación de la 011, comprobada contra el
  Supervisor 2026.11.0, y se prueban con la tabla real y el Supervisor
  simulado: cada `read` por `sv_read_api` y cada `confirm` por `sv_call_api`
  con vista previa y token. (FR-078, FR-079, FR-080; CAP-091, CAP-092,
  CAP-094)
- **FR-016**: la contraseña de `POST /docker/registries` no aparece en la
  vista previa, en el log de Hermes ni en un error del Supervisor que la
  repita. (FR-079, CAP-092; principio II)

#### Convenciones, familias, guía y documentación

- **FR-017**: familias nuevas `system_control` y `resolution_fixes` (1.2.0,
  desactivables, en `tool_families_disabled`); con una desactivada, sus tools
  no se registran y la genérica responde `use_dedicated_tool` con
  `family_disabled: true`. (FR-010 y FR-012 de la 008)
- **FR-018**: anotaciones MCP honestas según research R-10 (ninguna
  `readOnly`; destructivas las que cortan o borran; de mundo abierto las que
  descargan). (principio V)
- **FR-019**: cada tool deja un evento de log (`system_control_*` o
  `resolution_fix_*`) con la tool, la ruta, las claves (nunca los valores de
  `audio_*`, `timezone` ni `country`) y el resultado; los errores del
  Supervisor vuelven redactados (`redact_secrets`); las respuestas pasan por
  `redact_structure` y caben en `response_max_bytes`. (principio II)
- **FR-020**: guía: tema nuevo `system_control` con alias; temas
  `diagnostics` y `supervisor` actualizados con sus huellas. (FR-023 de la 008)
- **FR-021**: invariantes del programa: filas en
  `tests/test_confirmation_args_inventory.py` (7 tools con token),
  `FUERA_DEL_BANCO` (8), matriz de la 014 (8 filas `VM | pendiente`) y sus
  líneas en «Tandas de pruebas» de `docs/BANCO-SUPERVISOR.md`; sin
  `allow_dangerous` ni listas nuevas. (FR-016 y FR-017 de la 008)
- **FR-022**: documentación en el mismo cambio: sección «Control de Core y
  del Supervisor» en `## [1.2.0]` de `hermes/CHANGELOG.md`; estado de la 022
  en la tabla del programa de `docs/HOJA-DE-RUTA.md`; familias en
  `hermes/DOCS.md`; `README.md` y `README.es.md` sincronizados; filas CAP-084,
  CAP-087, CAP-091, CAP-092 y CAP-094 de la matriz de
  `specs/008-cobertura-total/plan.md`. (FR-023 de la 008)

### Entidades clave

- **Vista previa de interrupción**: `action`, `interrupts` (qué se corta y
  qué no), `duration`, `hermes` (qué le pasa a Hermes y cómo se recupera),
  `blocked`/`warnings` y los datos leídos (data-model).
- **Diferencia de opciones**: por clave, `current`, `new`, `changes`.
- **Traducción de sugerencia**: `(type, context)` → `effect`, `interrupts`,
  `duration`, `reversible`, `warnings`, `allowed`.

## Fuera de alcance

- Parar Core (`/core/stop`) y el canal del Supervisor: siguen `deny` (D-01).
- Actualizar Core, OS, Supervisor o plugins (015), la tienda (030), montajes y
  opciones de backup (019), host y red (032), `safe_mode` en
  `sv_restart_core` (la 1.1.2 no cambia).
- Opciones de Core de red (`port`, `ssl`; las de HTTP de Core son de la 021),
  `image` y `refresh_token`.
- Probar en el Supervisor real: pendiente en la VM de la 014.

## Supuestos

- La 013 está integrada (fixture `SupervisorSimulado`, `/jobs/info` `read`).
- El Supervisor 2026.11.0 es el de destino; otra versión con fixups nuevos
  da `unknown_effect` hasta que Hermes los traduzca.
- Hermes llega a Core por el proxy del Supervisor (`ha.py`): reiniciar el
  Supervisor corta Core para Hermes.

## Criterios de éxito *(obligatorio)*

- **SC-001**: las 8 tools existen en sus familias, con anotaciones de R-10, y
  las 7 con token tienen su fila en el inventario de argumentos atados.
- **SC-002**: ningún rechazo (`not_allowed`, `invalid_argument`,
  `already_running`, `no_changes`, `jobs_in_progress`, `blocked`,
  `suggestion_not_found`, `no_fixup`, `unknown_effect`, `targets_hermes`,
  `suggestion_changed`) llega al Supervisor con una escritura (tests con el
  simulado que cuentan las llamadas).
- **SC-003**: cada par `(tipo, contexto)` con fixup del Supervisor 2026.11.0
  tiene traducción y test; un par nuevo da `unknown_effect`.
- **SC-004**: `grep -c "spec 022" hermes/src/hermes/command_table.py` = 0 y la
  regeneración no cambia la tabla.
- **SC-005**: con las familias de la 1.2.0 desactivadas, la lista de tools es
  la de la 1.1.2.
- **SC-006**: la suite termina con los 6 fallos conocidos de Windows y ninguno
  más; controles negativos anotados en cada tramo.
- **SC-007**: la matriz de la 014 tiene las 8 tools como `VM | pendiente`.
