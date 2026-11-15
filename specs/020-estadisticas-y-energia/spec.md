# Especificación: Hermes 1.2.0 — estadísticas y energía (sub-feature 020)

**Directorio de la spec**: `specs/020-estadisticas-y-energia`

**Creada**: 2026-11-15

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T018 de su `tasks.md` y cubre **CAP-050**
(mantenimiento de estadísticas, vía D) y **CAP-054** (energía, vía D+T), es
decir, FR-069 y FR-070 de la 008, más los transversales que le tocan (FR-010…
FR-012, FR-015, FR-018…FR-021, FR-023 y FR-024 de la 008). Ola 3, tamaño M.
Depende de la 029 (familia `recorder`, ya integrada).

**Entrada**: `specs/008-cobertura-total/` (spec, plan con la matriz de
trazabilidad, research CAP-050 y CAP-054, `inventario/core-ws.tsv`); lo
integrado en la rama: la 011 (`command_table.py`, `command_policy.py`,
`tool_families.py`, genéricas, generador `scripts/inventario/`), la 029
(`tools/recorder_status.py`, familia y tema `recorder`), la 010 y la 028
(banco de Core y su inventario de escrituras), la 014 (matriz de pruebas), la
018 (`estado` de `create_confirmation_token`, sobre de lista), la 033
(inventario de argumentos atados al token) y el código de Home Assistant Core
2026.11.1 (`components/recorder/websocket_api.py`, `statistics.py`, `core.py`;
`components/energy/websocket_api.py`, `data.py`, `__init__.py`;
`components/kitchen_sink/__init__.py`), leído sin ejecutar nada.

**Fuera de esta sub-feature**: la lectura de estadísticas y el recorder
(`ha_statistics_during_period`, `ha_list_statistic_ids`,
`ha_validate_statistics`, `ha_get_statistics_metadata`,
`ha_get_recorder_info`: 1.1.2 y 029, no cambian); purgar el recorder
(`recorder.purge`, acción de HA de la denylist); excluir entidades del
recorder (`recorder/entity_options/update`, si existiera, no está en
CAP-050); los sensores de coste y las integraciones de previsión solar (son
de cada integración); el panel de energía de la interfaz.

## Clarificaciones

### Sesión 2026-11-15

Decisiones vinculantes (008 y supervisor del programa; no se discuten aquí):
tools dedicadas para CAP-050 (todas en dos pasos: reescriben histórico y solo
se deshacen con un backup) y para leer y guardar las preferencias de energía
(guardar en dos pasos, documento con diferencias, como Lovelace); validación,
información, consumo fósil y previsión solar de energía quedan `read` en la
tabla. El mantenimiento de estadísticas va en la familia `recorder` de la 029;
la energía, en una familia NUEVA `energy`. Lo que borra o reescribe datos
históricos se confirma en dos pasos con una vista previa que dice exactamente
qué estadísticas y qué periodo se tocan, y el token ata todos los argumentos
que cambian la acción. Toda tool nueva que modifica se prueba en el banco de
Core con el lector independiente.

Decisiones tomadas al especificar (justificadas en [research.md](research.md)):

- P: ¿Cuántas tools? → R: **siete**. CAP-050: `ha_clear_statistics`,
  `ha_change_statistics_unit`, `ha_update_statistics_metadata`,
  `ha_adjust_statistics_sum` y `ha_import_statistics` (los nombres del
  research de la 008). CAP-054: `ha_get_energy_prefs` y
  `ha_update_energy_prefs`. Seis modifican y las seis piden token.
- P: ¿Y `recorder/update_statistics_issues`, que está en CAP-050 pero no en
  FR-069 ni tiene tool en el research de la 008? → R: pasa a **`confirm`**
  en la tabla (por `ha_call_ws_command`, con token): no tiene argumentos, no
  toca datos, solo vuelve a crear o quitar los avisos de Repairs de las
  estadísticas. Una tool propia sería una tool más para algo que la genérica
  ya hace con seguridad (research R-3). Queda en `_POR_LA_TABLA` del test de la
  clase A con su porqué.
- P: ¿Qué hace HA de verdad con cada comando? → R: leído en el código de
  2026.11.1 (research R-1): `clear_statistics` y `update_statistics_metadata`
  esperan a que el recorder termine (10 s); `change_statistics_unit`,
  `adjust_sum_statistics` e `import_statistics` **solo encolan** el trabajo y
  responden enseguida. Las tools lo dicen (`queued: true`) en vez de dar por
  hecho lo que aún no está hecho (principio V).
- P: ¿Qué hace HA en silencio que la tool no puede callar? → R:
  `change_statistics_unit` **no hace nada** (solo un aviso en su log, y
  responde éxito) si la estadística no es del recorder (`source` distinto de
  `recorder`) o si `old_unit` no es la unidad actual. Hermes lo comprueba antes
  con los metadatos y rechaza (`not_supported_for_source`, `unit_mismatch`).
  `adjust_sum_statistics` sobre una estadística sin suma no cambia nada:
  Hermes rechaza con `statistic_has_no_sum`. Borrar o editar una estadística
  que no existe no falla en HA: Hermes rechaza con `statistics_not_found` antes
  de emitir el token, para que no se confirme una errata (research R-2).
- P: ¿Qué periodo dice la vista previa de un borrado con rango? → R: el exacto
  de HA, que borra **toda fila cuyo periodo se solape** con el rango: la de una
  hora que empieza antes de `start_time` pero lo cubre también cae. La vista
  previa da el rango pedido y el efectivo de cada tabla (horaria y de 5
  minutos). Sin rango, borra la estadística entera, metadatos incluidos
  (research R-1).
- P: ¿`unit_class` y `mean_type`? → R: obligatorios en las tools (aceptan
  `null` donde HA lo acepta). HA 2026.11 avisa de que llamar sin ellos está
  obsoleto y dejará de funcionar; Hermes no usa el camino obsoleto.
- P: ¿Cómo se guarda la energía? → R: HA reemplaza cada lista de nivel
  superior que recibe (`energy_sources`, `device_consumption`,
  `device_consumption_water`) y conserva las que no recibe.
  `ha_update_energy_prefs` sigue esa semántica con tres argumentos opcionales
  (al menos uno), y la vista previa da, por lista, lo que entra, sale, cambia
  y se conserva. El token se ata a los argumentos y al estado actual de las
  preferencias (`estado` de la 018): si alguien las cambia entre la vista
  previa y la confirmación, `ESTADO_CAMBIADO` (research R-5).
- P: ¿Preferencias de energía sin configurar? → R: HA responde `not_found`
  («No prefs»). `ha_get_energy_prefs` devuelve las listas vacías con
  `configured: false`; no es un error.
- P: ¿Familias y guía? → R: el mantenimiento en un módulo nuevo,
  `tools/statistics_maintenance.py`, dentro de la familia `recorder`, cuya
  descripción deja de decir «read only» (lo anunció la 029). La energía en un
  módulo y una familia nuevos, `energy`. El tema `recorder` de la guía suma el
  mantenimiento y `update_statistics_issues`; tema nuevo `energy`.
- P: ¿Tramos? → R: **tres**, no dos (la 008 decía 2): cinco tools de dos
  pasos con vistas previas distintas, más la energía, no caben con holgura en
  dos agentes. Ver plan.md, «Tramos».

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es el administrador de Home Assistant que trabaja desde un cliente
MCP.

### Historia 1 — Borrar estadísticas malas (Prioridad: P1)

Un contador de energía mandó un pico absurdo una tarde y el panel de energía
enseña un consumo imposible; o una entidad que ya no existe deja una
estadística huérfana. Quien administra quiere borrar ese tramo (o esa
estadística entera) sabiendo exactamente qué se borra.

**Prueba independiente**: con un HA simulado que conoce `sensor.consumo`, la
primera llamada devuelve una vista previa con la estadística, sus metadatos y
el rango efectivo, y no manda `recorder/clear_statistics`; la segunda, con el
token y los mismos argumentos, lo manda con el rango en UTC.

**Escenarios de aceptación**:

1. **Dado** `ha_clear_statistics(["sensor.consumo"], start_time, end_time)`,
   **cuando** se llama sin token, **entonces** la vista previa dice la
   estadística, su unidad y fuente, el rango pedido, el rango efectivo de las
   filas horarias y de 5 minutos, que no se deshace salvo con un backup, y no
   cambia nada en HA.
2. **Dado** el token, **cuando** se confirma con los mismos argumentos,
   **entonces** HA borra solo las filas de ese rango y la tool responde cuando
   el recorder ha terminado.
3. **Dado** un token emitido para un rango, **cuando** se confirma con otro
   rango, otra estadística o sin rango, **entonces** se rechaza y no se borra
   nada.
4. **Dado** un id que HA no conoce, **entonces** `statistics_not_found` con
   esos ids, sin token.
5. **Dado** solo `start_time`, o `start_time` posterior a `end_time`, o una
   fecha sin zona horaria, **entonces** `invalid_argument` sin llamar a HA.

---

### Historia 2 — Arreglar unidades (Prioridad: P1)

Un sensor cambió de Wh a kWh y `ha_validate_statistics` avisa de
`units_changed`. Quien administra quiere o convertir el histórico a la unidad
nueva o solo corregir la unidad guardada, sabiendo qué diferencia hay.

**Prueba independiente**: con metadatos simulados (`source: recorder`, Wh),
`ha_change_statistics_unit(old_unit="Wh", new_unit="kWh")` da una vista previa
que dice que convierte todos los valores; con `old_unit` distinto de la unidad
actual, o con una estadística externa, rechaza sin token.

**Escenarios de aceptación**:

1. **Dado** una estadística del recorder en Wh, **cuando** se pide cambiarla a
   kWh, **entonces** la vista previa dice que convierte media, mínimo,
   máximo, estado y suma de todo el histórico de las dos tablas, y al
   confirmar responde `queued: true`.
2. **Dado** `old_unit` distinto de la unidad guardada, **entonces**
   `unit_mismatch` con la unidad actual, sin token (HA no haría nada y
   respondería éxito).
3. **Dado** una estadística externa (`kitchen_sink:…`), **entonces**
   `not_supported_for_source`.
4. **Dado** `ha_update_statistics_metadata(id, unit_of_measurement="kWh",
   unit_class="energy")`, **entonces** la vista previa dice la unidad y la
   clase actuales y las nuevas, y que los valores NO se convierten.

---

### Historia 3 — Corregir una suma (Prioridad: P2)

Un contador se reinició y la estadística de suma tiene un salto. Quien
administra quiere restar ese salto desde una hora concreta.

**Prueba independiente**: con una estadística con suma, la vista previa da la
suma actual en esa hora y la que quedará; al confirmar, HA recibe el ajuste;
una segunda confirmación con el mismo token se rechaza.

**Escenarios de aceptación**:

1. **Dado** `ha_adjust_statistics_sum(id, start_time, adjustment=-12.5,
   adjustment_unit="kWh")`, **entonces** la vista previa dice que suma
   -12,5 kWh a cada fila desde esa hora en adelante (horaria y de 5 minutos),
   la suma actual en esa hora si la hay, y que repetirlo suma dos veces.
2. **Dado** una estadística sin suma, **entonces** `statistic_has_no_sum`.
3. **Dado** una unidad que no se puede convertir a la de la estadística,
   **entonces** el error de HA (`invalid_units`) redactado, con `ha_code`.

---

### Historia 4 — Importar estadísticas (Prioridad: P2)

Quien migra desde otro sistema quiere cargar un histórico horario de consumo.

**Prueba independiente**: con 24 filas en horas en punto, la vista previa da
el rango, el número de filas, si la estadística ya existe y cuántas filas de
ese rango se sobrescriben; al confirmar se manda `recorder/import_statistics`
con `mean_type` y `unit_class`.

**Escenarios de aceptación**:

1. **Dado** una estadística externa `banco:importada` con `source: banco`,
   **cuando** se importa, **entonces** se previsualiza y, al confirmar,
   responde `queued: true`; el lector la ve después.
2. **Dado** una fila que no empieza en una hora en punto, una fecha sin zona,
   una fuente que no casa con el id o más filas que el tope, **entonces**
   `invalid_argument` sin llamar a HA.
3. **Dado** una estadística que ya existe, **entonces** la vista previa dice
   que se actualizan sus metadatos y se sobrescriben las filas con la misma
   hora.

---

### Historia 5 — Configurar el panel de energía (Prioridad: P1)

Quien monta el panel de energía quiere leer su configuración y cambiarla
(añadir la red, el solar, un dispositivo) sin perder lo que ya tenía.

**Prueba independiente**: con preferencias simuladas, la vista previa de
`ha_update_energy_prefs(device_consumption=[…])` dice qué dispositivos entran
y salen y que las fuentes se conservan; confirmar con las preferencias
cambiadas por otro entre medias da `ESTADO_CAMBIADO`.

**Escenarios de aceptación**:

1. **Dado** un HA sin preferencias, **cuando** se pide `ha_get_energy_prefs`,
   **entonces** devuelve las tres listas vacías y `configured: false`.
2. **Dado** preferencias con dos fuentes, **cuando** se guarda solo
   `device_consumption`, **entonces** la vista previa dice que las fuentes se
   conservan y lista los dispositivos añadidos y quitados.
3. **Dado** una vista previa que quita todas las fuentes, **entonces** lo
   avisa expresamente.
4. **Dado** estadísticas nombradas en el documento que HA no conoce,
   **entonces** la vista previa las lista en `warnings` (HA no lo comprueba al
   guardar).
5. **Dado** `ha_read_ws_command("energy/validate")`, `energy/info`,
   `energy/solar_forecast` o `energy/fossil_energy_consumption`, **entonces**
   responden por la genérica de lectura.

---

### Historia 6 — Nada de lo actual se rompe (Prioridad: P1)

**Prueba independiente**: con `tool_families_disabled: [energy]` no aparece
ninguna tool de energía; con `recorder` desactivada no aparece ninguna de la
029 ni de la 020; los comandos siguen `dedicated` y la genérica los rechaza.

**Escenarios de aceptación**:

1. **Dado** la configuración por defecto, **entonces** aparecen las siete
   tools nuevas y las anteriores siguen con el mismo nombre, anotaciones y
   argumentos.
2. **Dado** `ha_call_ws_command("recorder/clear_statistics", …)`, **entonces**
   `use_dedicated_tool` con `ha_clear_statistics`, sin llegar a HA.
3. **Dado** que se regenera la tabla, **entonces** sale idéntica.

---

### Casos límite

- Core caído: las siete fallan con el error de conexión de siempre.
- Recorder no cargado (`unknown_command` en un comando del recorder):
  `recorder_not_loaded`, como en la 029. Energía no cargada
  (`unknown_command` en `energy/*`): `energy_not_loaded`.
- `clear_statistics` o `update_statistics_metadata` que vencen el plazo de HA
  (10 s; base grande u ocupada): HA responde `timeout`; la tool dice que el
  trabajo puede seguir en la cola del recorder y que se compruebe con
  `ha_get_statistics_metadata`, sin darlo por hecho ni por fallido.
- Una HA más antigua que la de la tabla rechaza claves que no conoce (por
  ejemplo, el rango de `clear_statistics` o `unit_class`) con
  `invalid_format`: error de HA redactado con `ha_code` y la versión de la
  tabla.
- Estadística borrada o cambiada entre la vista previa y la confirmación: el
  token se ata también a sus metadatos; `ESTADO_CAMBIADO` y no se ejecuta.
- `ha_import_statistics` con filas repetidas a la misma hora:
  `invalid_argument` (HA se quedaría con una sin decir cuál).
- `ha_update_energy_prefs` con un documento que HA no acepta (esquema): el
  error de HA (`invalid_format`) redactado; nada cambia.
- Preferencias de energía mayores que el tope de respuesta:
  `response_too_large` (no se recorta un documento de configuración).

## Requisitos *(obligatorio)*

### Requisitos funcionales

Cada FR cita el FR y la CAP de la 008 que cumple.

#### Mantenimiento de estadísticas (CAP-050; FR-069 de la 008)

- **FR-001**: `ha_clear_statistics(statistic_ids, start_time=None,
  end_time=None, confirmation_token=None)` borra estadísticas con
  `recorder/clear_statistics`. 1–100 ids con forma de estadística (sin
  repetidos tras normalizar); `start_time` y `end_time` juntos o ninguno, ISO
  8601 con zona, `start_time < end_time`. Sin rango borra cada estadística
  entera (filas y metadatos); con rango, las filas que se solapan con él. Dos
  pasos siempre (FR-069; CAP-050).
- **FR-002**: `ha_change_statistics_unit(statistic_id, old_unit, new_unit,
  confirmation_token=None)` convierte el histórico con
  `recorder/change_statistics_unit`. Antes del token comprueba que la
  estadística existe, que su `source` es `recorder` (si no,
  `not_supported_for_source`) y que `old_unit` es su unidad actual (si no,
  `unit_mismatch` con la actual): en esos casos HA respondería éxito sin hacer
  nada. `old_unit` igual a `new_unit` → `invalid_argument` (HA tampoco haría
  nada). Responde `queued: true` (FR-069; CAP-050).
- **FR-003**: `ha_update_statistics_metadata(statistic_id,
  unit_of_measurement, unit_class, confirmation_token=None)` cambia la unidad
  y la clase guardadas con `recorder/update_statistics_metadata`, sin convertir
  valores (lo dicen la descripción y la vista previa). Los dos argumentos son
  obligatorios y admiten `null` (FR-069; CAP-050).
- **FR-004**: `ha_adjust_statistics_sum(statistic_id, start_time, adjustment,
  adjustment_unit, confirmation_token=None)` ajusta la suma con
  `recorder/adjust_sum_statistics`: la estadística tiene que existir y tener
  suma (si no, `statistic_has_no_sum`); `adjustment` finito y distinto de
  cero; `start_time` ISO con zona. Responde `queued: true` (FR-069; CAP-050).
- **FR-005**: `ha_import_statistics(metadata, stats=None, confirmation_token=None)`
  importa filas horarias con `recorder/import_statistics`. `metadata`:
  `statistic_id`, `source`, `name`, `unit_of_measurement`, `unit_class`,
  `mean_type` (0, 1 o 2) y `has_sum`, todos obligatorios (`name`,
  `unit_of_measurement` y `unit_class` admiten `null`); `source` es `recorder`
  para un id `dominio.objeto` y el dominio para un id `dominio:objeto`.
  `stats`: 1–5000 filas, cada una con `start` ISO con zona en una hora en
  punto (sin repetidos) y `mean`, `min`, `max`, `state`, `sum` o `last_reset`
  opcionales y finitos. Responde `queued: true`. `stats` es omitible al
  confirmar (se guarda con el token, como el documento de Lovelace)
  (FR-069; CAP-050).
- **FR-006**: La vista previa de las cinco dice **exactamente** qué
  estadísticas y qué periodo se tocan y que solo se deshace con un backup:
  - borrar: cada id con sus metadatos (fuente, unidad, media, suma), si se
    borra entera o el rango pedido y el efectivo por tabla (las filas que se
    solapan: la horaria desde `start_time` menos una hora, exclusiva, y la de
    5 minutos desde `start_time` menos 5 minutos, exclusiva, hasta
    `end_time`);
  - cambiar la unidad: unidad y clase actuales y nuevas, «convierte todo el
    histórico» de las dos tablas;
  - metadatos: lo actual y lo nuevo, «no convierte valores»;
  - ajustar la suma: desde qué hora, el ajuste y su unidad, la suma actual en
    esa hora (si hay fila) y la que quedará, «repetir suma otra vez»;
  - importar: id, si ya existe (y sus metadatos actuales), rango de las filas,
    cuántas son y cuántas filas existentes del rango se sobrescriben (o
    `null` con el motivo si el rango pasa de 31 días).
  (FR-069; CAP-050; principio IV.)
- **FR-007**: El token de cada una ata **todos** los argumentos que cambian la
  acción, normalizados como se envían (ids ordenados y sin repetir, fechas en
  UTC), y el estado de los metadatos de las estadísticas tocadas (`estado` de
  `create_confirmation_token`): si cambian entre la vista previa y la
  confirmación, `ESTADO_CAMBIADO` y nada se ejecuta. El estado nunca es
  `None` (con `None`, `create_confirmation_token` no ataría nada): al importar
  una estadística que no existe se ata la lista vacía de metadatos. Cada tool
  tiene su fila
  en el inventario de argumentos atados (`tests/test_confirmation_args_inventory.py`)
  sin ningún `exento` salvo `confirmation_token` (FR-069; principio IV).
- **FR-008**: Ids que HA no conoce → `statistics_not_found` con la lista,
  antes de emitir token, en las cuatro que actúan sobre estadísticas
  existentes (importar crea) (FR-069; principio III).
- **FR-009**: `recorder/update_statistics_issues` pasa a `confirm` en la
  tabla (por `ha_call_ws_command`, con token), con motivo «vuelve a crear o
  quitar los avisos de Repairs de las estadísticas; no toca datos» y CAP-050;
  la clave va en `_POR_LA_TABLA` de `tests/test_command_table.py` con «spec
  020: …» (FR-069; CAP-050; FR-012 de la 008).

#### Energía (CAP-054; FR-070 de la 008)

- **FR-010**: `ha_get_energy_prefs()` lee `energy/get_prefs` y devuelve
  `{configured, energy_sources, device_consumption,
  device_consumption_water}`; el `not_found` de HA («No prefs») es
  `configured: false` con las listas vacías (FR-070; CAP-054).
- **FR-011**: `ha_update_energy_prefs(energy_sources=None,
  device_consumption=None, device_consumption_water=None,
  confirmation_token=None)` guarda con `energy/save_prefs`. Al menos una de
  las tres listas; cada una que llega reemplaza la de HA entera y las que no
  llegan se conservan (lo dicen la descripción y la vista previa). Hermes
  valida la forma básica (listas de objetos con `type` conocido en las
  fuentes; `stat_consumption` en los dispositivos); el esquema completo lo
  valida HA al guardar. Dos pasos siempre. Devuelve lo que HA guardó (puede
  diferir de lo enviado: HA rellena `stat_rate` de las fuentes con
  `power_config`) (FR-070; CAP-054).
- **FR-012**: La vista previa de `ha_update_energy_prefs` da, por lista,
  cuántos elementos había y habrá, los que entran, salen y cambian
  (identificados por su tipo y sus estadísticas), qué listas se conservan,
  un aviso si se quitan todas las fuentes y `warnings` con las estadísticas
  nombradas que el recorder no conoce (si el recorder no está cargado, el
  aviso lo dice). El token ata las tres listas y el estado actual de las
  preferencias (`estado`; sin preferencias guardadas, el estado es
  `{"configured": false}`, nunca `None`) (FR-070; CAP-054; principio IV).
- **FR-013**: `energy/validate`, `energy/info`, `energy/solar_forecast` y
  `energy/fossil_energy_consumption` pasan a `read` en la tabla (familia
  `generic_commands`, CAP-054), con motivo que dice qué devuelven y, en
  `energy/fossil_energy_consumption`, un `example` de carga revisado contra el
  código de Core. Las cuatro claves en `_POR_LA_TABLA` con «spec 020: …»
  (FR-070; CAP-054; FR-011 de la 008).

#### Familias, tabla, convenciones y documentación (transversales de la 008)

- **FR-014**: Las cinco de CAP-050 en el módulo nuevo
  `tools/statistics_maintenance.py`, familia `recorder` (de la 029; su
  descripción deja de decir «read only» y nombra el mantenimiento con
  confirmación). Familia nueva `energy` (`desde="1.2.0"`, desactivable) con el
  módulo `tools/energy.py`. Con `energy` desactivada, la lista de tools es la
  de antes de la 020 más las cinco de mantenimiento; con `recorder` y `energy`
  desactivadas, exactamente la de antes de la 029 (las tools de la 1.1.2 no
  cambian) (FR-010 de la 008; CAP-004).
- **FR-015**: Siete comandos pasan de `deny` «pendiente de tool dedicada (spec
  020)» a `dedicated`: `recorder/clear_statistics`,
  `recorder/change_statistics_unit`, `recorder/update_statistics_metadata`,
  `recorder/adjust_sum_statistics`, `recorder/import_statistics` (familia
  `recorder`, CAP-050), `energy/get_prefs` y `energy/save_prefs` (familia
  `energy`, CAP-054). Sus claves en `_DEDICADAS_INICIALES` del generador;
  regenerar la tabla la deja idéntica. No queda ninguna entrada con «(spec
  020)» (FR-012 de la 008; CAP-001).
- **FR-016**: Anotaciones honestas: `ha_get_energy_prefs` `R-I-` (prefijo);
  `ha_clear_statistics`, `ha_change_statistics_unit`,
  `ha_update_statistics_metadata`, `ha_import_statistics` y
  `ha_update_energy_prefs` destructivas (`_DESTRUCTIVE_EXACT`) e idempotentes
  (`-DI-`); `ha_adjust_statistics_sum` destructiva y NO idempotente
  (`_NON_IDEMPOTENT_EXACT`, `-D--`: repetirla suma dos veces). Ninguna de
  mundo abierto. Hints y títulos en `_HINTS_NUEVAS_1_2_0`. Las seis que
  modifican piden `confirmation_token` (invariante del registro) (FR-018 de la
  008; principio V).
- **FR-017**: Toda respuesta y vista previa pasa por `redact_structure` +
  `redact_secrets` y por el tope de respuesta (`response_too_large` si un
  documento no cabe; las listas de las vistas previas recortadas con
  `truncated`). Los errores de HA salen redactados con `ha_code`. No hay tools
  de lista nuevas (el sobre común no aplica) (FR-018, FR-019 de la 008).
- **FR-018**: El log de las siete lleva solo el nombre de la tool, el paso
  (vista previa o confirmación), el resultado y recuentos (estadísticas,
  filas, elementos por lista); nunca ids de estadísticas, nombres de
  entidades, valores ni el documento de energía (FR-019, FR-021 de la 008;
  CAP-011).
- **FR-019**: `unknown_command` en un comando del recorder →
  `recorder_not_loaded` (mismo traductor que la 029); en `energy/*` →
  `energy_not_loaded` con una explicación (la energía va en
  `default_config`). Un `timeout` de HA en borrar o editar metadatos se
  traduce a `ha_timeout` con el aviso de que el trabajo puede seguir en la
  cola (FR-020 de la 008; principio V).
- **FR-020**: Descripciones en inglés que dicen lo que hacen y lo que no (qué
  borran, que no se deshace salvo con un backup, `queued`, que la unidad no se
  convierte en metadatos, que energía reemplaza listas enteras). Guía: el tema
  `recorder` suma el mantenimiento y `update_statistics_issues` por la
  genérica (actualizando su texto de la 029, que decía «solo lectura»); tema
  nuevo `energy` con las dos tools, las cuatro lecturas por la genérica con su
  llamada exacta, alias e índice (FR-011, FR-018 de la 008).
- **FR-021**: Las siete tools se ejecutan en el banco de Core contra HA
  2026.11.1 real, cada escritura con su vista previa sin efecto y su efecto
  comprobado por el lector independiente; también `update_statistics_issues`
  por `ha_call_ws_command` y las cuatro lecturas de energía por
  `ha_read_ws_command`. Inventario propio `tests/banco/cobertura_020.py`
  (`PROBADAS_020`, `NO_EJECUTABLES_020` vacío) sumado al invariante de
  escrituras y a lo que el job exige; `ha_get_energy_prefs` también exigida
  por ejecución (FR-014, FR-015 de la 008; CAP-034).
- **FR-022**: Documentación en el mismo cambio: sección «Estadísticas y
  energía» en `## [1.2.0]` del CHANGELOG; estado de la 020 en la tabla del
  programa y seis filas en la matriz de pruebas (`banco de Core`, `ok`) de
  `docs/HOJA-DE-RUTA.md`; recuento y tablas de tools en `README.md`,
  `README.es.md` y `hermes/DOCS.md` (familia `energy` en
  `tool_families_disabled` y descripción nueva de `recorder`); filas CAP-050 y
  CAP-054 de la matriz de la 008 con tools, entradas y tests definitivos
  (FR-023, FR-024 de la 008).

### Entidades clave

- **Estadística de largo plazo**: id (`dominio.objeto` del recorder o
  `fuente:objeto` externa), metadatos (fuente, unidad, clase de unidad, media,
  suma) y filas horarias y de 5 minutos.
- **Operación de mantenimiento**: qué estadísticas, qué periodo, qué cambia y
  si HA la hace al momento o la encola.
- **Preferencias de energía**: tres listas (fuentes, consumo de dispositivos
  eléctricos y de agua) que nombran estadísticas.

## Criterios de éxito *(obligatorio)*

- **SC-001**: Las siete tools aparecen con la configuración por defecto; con
  `energy` desactivada no aparece ninguna de energía y el resto no cambia.
- **SC-002**: Cero entradas de la tabla con «(spec 020)»; siete `dedicated`
  hacia tools registradas, cuatro `read` y una `confirm` de CAP-050/CAP-054;
  regenerar la tabla no cambia ni un byte.
- **SC-003**: En el 100 % de los tests de las seis que modifican, la primera
  llamada no cambia nada en HA (comprobado por el lector en el banco) y una
  confirmación con cualquier argumento distinto se rechaza sin ejecutar.
- **SC-004**: Ningún centinela (secreto en un error de HA o en un nombre de
  estadística) aparece en respuestas, errores ni log; el log no contiene ids
  de estadísticas.
- **SC-005**: El 100 % de las siete tools y de las cinco entradas de la tabla
  de CAP-050/CAP-054 se ha ejecutado en el banco contra HA Core 2026.11.1 real.
- **SC-006**: Suite completa con solo los 6 fallos conocidos en Windows y CI
  (tests, banco de Core, Semgrep) en verde al cerrar cada tramo.

## Supuestos

- La base de la implementación es la rama del programa con la 009, 010, 011,
  028, 014, 013, 018, 029, 012, 033 y 027 integradas (la de esta spec).
- El banco carga ya `recorder:`, `frontend:` y `kitchen_sink:` (029 y 028);
  esta sub-feature añade `energy:`, que no necesita red ni hardware.
- El lector siembra sus propias estadísticas (`recorder/import_statistics`
  directo a Core) para no tocar las de `kitchen_sink`, que leen los tests de
  la 029, y las borra al terminar.

## Dudas para el final

- **D-1**: ¿Debería `ha_change_statistics_unit`, `ha_adjust_statistics_sum` e
  `ha_import_statistics` esperar a que el recorder vacíe su cola (sondeando
  `recorder/info`) antes de responder? Hoy responden `queued: true`, que es la
  verdad de HA; esperar daría «hecho» pero alargaría la llamada sin garantía.
- **D-2**: La 008 da 2 tramos a la 020; esta spec usa 3 (plan.md). Si el
  programa cuenta tramos, sube a 52.
- **D-3**: `update_statistics_issues` queda en la tabla (`confirm`); si el
  programa prefiere una tool dedicada (`ha_update_statistics_issues`), es un
  cambio pequeño en el tramo 2.
