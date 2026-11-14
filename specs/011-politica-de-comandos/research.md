# Investigación: política de comandos, genéricas y familias (011)

Fase 0 del plan. Cada apartado: decisión, porqué y alternativas descartadas.
Las referencias a código son de la rama del programa sobre la 1.1.2. El
contexto general (inventarios, clases A–D, opciones de arquitectura) está en
`specs/008-cobertura-total/research.md` y no se repite.

## Lo que hay hoy (comprobado en el código)

- **Registro**: `tools/__init__.py`, `register_all_tools(mcp, ha_client, …)`
  llama a mano al `register()` de 44 módulos (216 tools, más `test_progress`
  con `HERMES_DEV`). No hay noción de grupo. Un test (`test_tools_registration`)
  compara las tools declaradas con `@mcp.tool()` (por AST) con las registradas,
  y `_HINTS_SNAPSHOT` guarda nombre y anotaciones de las 216.
- **Anotaciones**: `tools/_annotations.py` las aplica al final del registro por
  prefijo y por nombre exacto. `ha_read_*` y `sv_read_*` no encajan con ningún
  prefijo de lectura (`ha_get_`, `ha_list_`, `sv_get_`, `sv_list_`…), así que
  las genéricas tienen que ir por nombre exacto; `title_for` ya escribe `ws`
  como `WS`, pero no `api` como `API`.
- **Confirmación**: `security.py`, `create_confirmation_token(tool, args,
  preview, *, omitibles=())` y `resolve_confirmation_token(...)` (1.1.2): hash
  canónico de tool + argumentos, un fichero por token en `/data`, 60 s, un solo
  uso, estado `executing` sin `await` entre leer y escribir. Con omitibles, el
  documento se guarda en el fichero del token. `complete_confirmation_token`
  guarda `cached_result` en el fichero: lo que se pase ahí acaba en disco.
- **Denylist**: `service_policy.py` es un módulo neutral (no importa nada de
  Hermes) que usan `ha.py` y las tools. Es el modelo de la tabla.
- **Tope y redacción**: `HermesMCPServer.call_tool` aplica `response_max_bytes`
  a toda tool con `recortar_a_bytes`, que recorta la lista más grande del
  primer nivel, nunca corta una vista previa con token y, si no hay nada que
  recortar, devuelve `response_too_large`. `redact_structure` tapa valores de
  texto bajo claves sensibles por subcadena (`_SENSITIVE_KEY_MARKERS`);
  `redact_secrets` tapa patrones en texto libre; `redact_network`
  (`logging_setup.py`) seudonimiza IPs y hosts en los logs de add-ons.
- **Core**: `HAClient.ws_send(payload, timeout)` pone el `id`, espera el
  `result` y convierte `success: false` en `HAConnectionError` con el `code` de
  HA; `ws_one_shot_subscription(payload, event_timeout_seconds)` espera la
  confirmación y el primer evento y **siempre** cancela.
- **Supervisor**: `HAClient.sv_request(method, path, json_body, params,
  timeout)` y `sv_request_text(path)`; los dos pasan por
  `_assert_safe_request_path` (empieza por `/`, sin control, sin `%`, `#` ni
  `?`, sin `..` ni codificado). La autoprotección de Hermes está en
  `tools/addons.py`, `_es_hermes(slug)` (`self`, el slug del hostname, `hermes`
  o terminado en `_hermes`).
- **Opciones**: `hermes/config.yaml` (esquema y opciones) → `run.sh` las
  exporta como `HERMES_*` → `config.py` (`HermesConfig`, `validate()` lanza
  `ValueError` y el arranque se detiene) → `__main__.py` las pasa a
  `register_all_tools`.
- **Inventarios**: `core-ws.tsv` tiene 623 filas, una por comando, todas con
  forma `^[a-z0-9_-]+(/[a-z0-9_-]+)*$` (dos con guion: `dynalite/get-config` y
  `dynalite/save-config`); `supervisor-rutas.tsv` tiene 217 filas para 254
  rutas (alias y variantes de log agrupados en una fila, p. ej. `GET
  /dns/logs, /dns/logs/latest, /dns/logs/boots/{b} (3)`).
- **Recuento de la clase A por vía** (matriz de la 008): Core, 72 comandos de
  CAP con vía D, 53 de vía T, 20 de D+T y 2 de D+X; Supervisor, 57 filas de vía
  D, 40 de T, 16 de D+T y 2 de D+X. Las 339 filas A/C de Core y las 115 A del
  Supervisor tienen CAP.

## R-1 — Dónde vive la tabla

**Decisión**: módulo Python de datos `hermes/src/hermes/command_table.py`,
generado y revisado a mano, con dos diccionarios (`CORE_WS: dict[str,
Entrada]`, `SUPERVISOR: dict[tuple[str, str], Entrada]`) y las constantes de
versión (`TABLE_HA_CORE = "2026.11.1"`, `TABLE_SUPERVISOR = "2026.11.0"`). La
lógica (tipo `Entrada`, búsqueda, casado de plantillas, decisión de las
guardas, resumen de la carga) va en `hermes/src/hermes/command_policy.py`, que
solo importa de `hermes.security` y de la biblioteca estándar.

**Porqué**:
- Es lo que pide la arquitectura de la 008 («módulo de datos neutral al estilo
  de `service_policy.py`… se consulta en memoria»).
- Un error de sintaxis o de tipo en la tabla se ve al importar, en el primer
  test, y no en producción al leer un fichero.
- Una línea por entrada: el diff de una reclasificación es una línea, fácil de
  revisar; las excepciones llevan un comentario con el porqué (principio X).
- El ejemplo de carga (FR-022) es un `dict` literal; en un TSV sería JSON
  dentro de una columna.
- El Dockerfile copia `src/` entero: no hay que declarar ficheros de datos ni
  cambiar el empaquetado.

**Alternativas**: TSV o JSON empaquetado y leído con `importlib.resources`
(parseo en cada arranque, errores en tiempo de ejecución, sin comentarios);
leer los inventarios en tiempo de ejecución (mezcla datos de investigación con
decisiones de seguridad y los inventarios no van en la imagen); una sola
estructura en `service_policy.py` (mezcla dos políticas distintas y lo hace
enorme).

## R-2 — Cómo se genera, se revisa y se valida

**Decisión**:
- `scripts/inventario/generar_tabla.py` (fuera de `hermes/src`, no va en la
  imagen) lee los dos inventarios y, si existe, la tabla actual, y escribe
  `command_table.py` ordenado y determinista.
  - **Primera vez** (sin tabla): aplica las reglas de FR-002. Para lo cubierto
    usa un mapa revisado a mano comando/ruta → tool dedicada que vive en el
    propio generador (`_DEDICADAS_INICIALES`); una fila cubierta sin tool en el
    mapa sale como `deny` «sin revisar».
  - **Siguientes veces**: conserva tal cual toda entrada cuya clave sigue en el
    inventario, añade las filas nuevas como `deny` con motivo «sin revisar
    (nuevo en <versión>)» y quita las que ya no están; imprime las dos listas.
- Después de generar, la tabla es la fuente de verdad: se revisa y se edita a
  mano.
- Validación por tests (sin ejecutar scripts): deriva en los dos sentidos,
  verbos, CAP de A/C, `dedicated` → tool existente y misma familia, ninguna
  entrada «sin revisar», marcas coherentes (`one_shot` solo con `read`; ninguna
  `read` de mundo abierto; `response="text"` solo en el Supervisor), recuentos
  623/254 y versiones de la tabla iguales a `HA_CORE_LAST_TESTED`.

**Porqué**: añadir lo nuevo como `deny` hace que, aunque nadie ejecute los
tests, la genérica lo rechace (fail-closed), y el test de «sin revisar» obliga
a clasificarlo antes de cerrar. Conservar lo revisado evita que regenerar
pise decisiones manuales.

**Alternativas**: un fichero de decisiones aparte del que se deriva la tabla
(dos fuentes de verdad que se desincronizan); que el generador no toque la
tabla y solo informe (el primer volcado de 877 entradas habría que escribirlo a
mano); añadir lo nuevo sin entrada (el test de deriva falla igual, pero la
diferencia entre «falta» y «está pendiente» se pierde en el diff).

## R-3 — Inventario del Supervisor por ruta

**Decisión**: normalizar `specs/008-cobertura-total/inventario/supervisor-rutas.tsv`
a una fila por método + plantilla (254 filas de datos), conservando
`area`, `cobertura`, `clase`, `rol_admin`, `nota` y `cap` de la fila agrupada de
la que sale. Los métodos múltiples (`GET/POST`) se separan; las listas de rutas
y las variantes con corchetes (`/logs[/follow,/latest,…]`) se expanden. Un
test comprueba que hay 254 claves únicas y que cada una tiene método válido y
plantilla con forma de ruta. El inventario sigue donde lo dejó la 008
(decisión del supervisor: la tabla se genera desde ahí).

**Porqué**: la tabla y el test de deriva necesitan una clave por ruta; expandir
los grupos en el generador o en el test con reglas ad hoc sería frágil y no
revisable.

**Alternativas**: dejar el TSV agrupado y expandir en código (reglas para cada
notación); mover los inventarios a `scripts/inventario/` (contradice la
decisión de generar desde la carpeta de la 008; queda como duda para el
final).

## R-4 — Clasificación inicial

**Decisión** (FR-002), por fila:

| Fila del inventario | Entrada |
|---|---|
| `cobertura` `si`, `si-equivalente`, `si-rest` o `accion-generica` (clase «cubierto») | `dedicated` con la tool que la cubre (acción genérica → `ha_call_service`); suscripciones que usa el cliente de Hermes → la tool que las expone (`subscribe_events` → `ha_wait_for_event`); si ninguna tool la expone (arranque, `ping`, bashio), `deny` «uso interno de Hermes» |
| clase B | `deny`, motivo = grupo de la nota (suscripción, frontend, alias legado…) |
| clase D | `deny`, motivo de la nota |
| clase A, CAP con vía D, D+T o D+X | `deny` «pendiente de tool dedicada (spec NNN)» con la sub-feature de la matriz |
| clase A, CAP con vía T | `read` si solo lee; `confirm` si escribe o tiene un verbo de escritura; revisado uno a uno; suscripciones `deny` salvo las de un solo mensaje marcadas `one_shot` |
| clase C | `deny` «pendiente de revisión (spec 025)» |
| `/core/api*`, `/homeassistant/api*` | `deny` (además de la guarda de FR-012); prevalece sobre las demás reglas, también sobre «cubierto» |

**Porqué**: la clase C la clasifica la 025 «uno a uno» (FR-089 de la 008). Una
heurística por verbo pondría en `confirm` comandos que borran la red Z-Wave,
restauran NVM o necesitan un PIN, y en `read` alguno que devuelve una clave de
red (`thread/get_dataset_tlv`, `esphome/get_encryption_key`). `deny` hasta
revisarla es fail-closed (principio III) y no cuesta nada: la 1.2.0 sale entera
(S-02 de la 008). Lo de vía D queda `deny` por la decisión de la 008 (nunca
abrir, ni de forma transitoria, una vía sin la vista previa semántica).

**Alternativas**: clasificar la clase C por verbo aquí y revisarla en la 025
(abre puertas durante el programa y duplica la revisión); dejar también la vía
T en `deny` (el MVP de la 008 —«la cola larga alcanzable por las
genéricas»— no se cumpliría).

## R-5 — Familias

**Decisión**: módulo neutral `hermes/src/hermes/tool_families.py` con un
`Familia(nombre, descripcion, desde, desactivable, modulos)` por familia y la
lista `FAMILIAS`. Catálogo de la 1.1.2 (por área, como los temas de la guía):

| Familia | Módulos de `hermes/tools/` | Tools |
|---|---|---|
| `base` (no desactivable) | `ping`, `guide` | `ping`, `test_progress` (solo `HERMES_DEV`), `hermes_guide` |
| `services` | `ha` | 5 |
| `automations` | `automations`, `scripts`, `scenes` | 21 |
| `helpers` | `input_boolean`, `input_button`, `input_datetime`, `input_number`, `input_select`, `input_text`, `counter`, `timer`, `schedule`, `zones`, `persons` | 69 |
| `events` | `events`, `wait_for_event` | 4 |
| `data` | `templates`, `history`, `logbook`, `statistics` | 5 |
| `registries` | `registry_area`, `registry_category`, `registry_device`, `registry_entity`, `registry_floor`, `registry_label` | 26 |
| `diagnostics` | `repairs`, `traces`, `search`, `resolution` | 8 |
| `config_entries` | `config_entries`, `config_entry_flows` | 13 |
| `filesystem` | `filesystem`, `filesystem_write` | 11 |
| `supervisor` | `addons`, `supervisor` | 18 |
| `backups` | `backups`, `ha_backups` | 13 |
| `lovelace` | `lovelace` | 10 |
| `marketplace` | `marketplace`, `hacs` | 11 |

Familia nueva de la 1.2.0: `generic_commands` (`generic_commands`: las cuatro
genéricas). Cada sub-feature posterior añade su familia o familias con
`desde="1.2.0"`. `register_all_tools` envuelve cada bloque de registro en una
comprobación de familia (cambio mínimo: no se reescribe el registro en un
bucle) y un test por AST comprueba que cada módulo con `@mcp.tool()` está en
exactamente una familia y que cada familia nombra módulos que existen.

**Opción**: `tool_families_disabled: []`, esquema `- "str?"` (como
`call_service_denylist_extra`), validada en `config.py` contra
`tool_families.FAMILIAS` y no en el esquema del Supervisor: una sola lista de
nombres, en Python, y un error que dice qué nombre falla y cuáles valen.

**Porqué**: módulo neutral para que `config.py` lo importe sin importar las
tools (evita ciclos); familias por área para que el usuario entienda qué
desactiva; `base` fija porque sin `hermes_guide` el cliente no sabe usar el
resto y `ping` es la sonda de salud del cliente.

**Alternativas**: una familia por módulo (44 nombres, demasiado fino); el
enumerado de nombres en el esquema de `config.yaml` (el Supervisor rechazaría
guardar la opción con un nombre mal escrito, pero habría que mantener dos
listas, y la 008 pide que Hermes no arranque y lo diga en el log); activar o
desactivar por sesión (Hermes no tiene estado entre llamadas: research R-5 de
la 008).

## R-6 — Las genéricas

**Decisión**:
- Módulo `hermes/src/hermes/tools/generic_commands.py`, `register(mcp,
  ha_client, *, response_max_bytes, familias_desactivadas)`, cuatro tools
  `@ready`.
- Orden de las guardas (008, arquitectura 2): forma de los argumentos →
  validación de ruta (Supervisor: forma y proxy de Core) → búsqueda en la
  tabla (en el Supervisor, casado de plantilla y después `self_target`)
  (`command_not_classified`) → categoría (`deny` → `command_denied`;
  `dedicated` → `use_dedicated_tool` con `family_disabled`; categoría de la
  otra genérica → `wrong_generic_tool`; familia desactivada →
  `family_disabled`) → dos pasos si es `confirm` → ejecución → redacción → log
  sin valores. La decisión es una función pura de `command_policy` (testable
  con tablas inyectadas); la tool solo la aplica.
- **Ejecución**: Core con `ws_send({"type": type, **payload})`, o con
  `ws_one_shot_subscription` si la entrada es `one_shot`, con un tope de 10 s;
  Supervisor con `sv_request(method, path, json_body=body)` o, si la entrada es
  `response="text"`, `sv_request_text(path)`.
- **Forma de la respuesta**: `{"command", "category", "result"}` para un
  objeto o escalar; `{"command", "category", "count", "items", "truncated"}`
  para una lista, para que el tope central la pueda recortar (un objeto con la
  lista dentro de `result` daría `response_too_large`). En el Supervisor,
  `method`, `path` (la concreta) y `route` (la plantilla) en vez de `command`.
  Texto: `{"route", "category", "count", "lines", "truncated"}` con las
  últimas líneas que caben.
- **Confirmación**: `create_confirmation_token(tool, args, preview)` y
  `resolve_confirmation_token(token, tool, args)` sin omitibles; `args` =
  `{"type", "payload"}` (Core) o `{"method", "path", "body"}` (Supervisor);
  `complete_confirmation_token(..., result={"executed": True})`.
- **Resumen de la carga** (FR-010): recorrido en profundidad con ruta
  `a.b[0].c`; la sensibilidad se hereda (si `credentials` es sensible, todo lo
  de dentro también). Se reutiliza `_looks_sensitive` de `security.py` (se
  expone como función pública `es_clave_sensible` sin cambiar su
  comportamiento).
- **Log**: evento `generic_command` con `tool`, `command`/`route`, `method`,
  `category`, `outcome` (`executed`, `preview`, `rejected:<código>`,
  `failed`), `payload_keys` (claves de primer nivel, ordenadas) y
  `payload_bytes`.

**Porqué**: reutiliza cada pieza existente (cliente, tokens, tope, redacción) y
deja la decisión de seguridad en un solo sitio, sin red ni HA, donde se prueba
con controles negativos.

**Alternativas**: una sola genérica por servidor con un argumento de modo
(`readOnlyHint` no podría ser verdad); guardar la carga como omitible (escribe
secretos en `/data`); devolver el resultado de HA dentro del token
(`cached_result` en disco).

## R-7 — Rutas del Supervisor

**Decisión**: casado de la ruta concreta con las plantillas de la tabla
segmento a segmento; un literal solo casa consigo mismo; un `{parámetro}` casa
con un segmento de 1–64 caracteres de `[A-Za-z0-9._-]` que no sea `.` ni `..`;
entre varias plantillas que casan gana la de más literales; empate →
`command_not_classified`. Antes, `_assert_safe_request_path` (la de `ha.py`,
reutilizada) más: sin `\`, sin `//` ni segmentos vacíos, sin barra final, sin
esquema ni host. Siempre fuera: `/core/api*` y `/homeassistant/api*`, y
`{app}` igual al propio Hermes. Para esto último se reutiliza `_es_hermes` de
`tools/addons.py` sin moverla ni cambiarla: la tool se la pasa a la función de
decisión de `command_policy` como predicado, para que el módulo neutral no
importe tools.

**Porqué**: con `hassio_role: admin`, una ruta mal casada llega a cualquier
endpoint del Supervisor; el proxy de Core saltaría la denylist y las guardas de
las tools `ha_*`; parar o reconfigurar Hermes por la genérica se saltaría la
autoprotección de `tools/addons.py`.

**Alternativas**: expresiones regulares por plantilla (más difíciles de
revisar); permitir `?` para parámetros de consulta (fuera de alcance; las rutas
que los necesitan tendrán tool dedicada).

## R-8 — Guía

**Decisión**: tema `generic_commands` (alias `commands`, `generic`, `ws`,
`api`, `table`) y argumento opcional `search: str | None = None` en
`hermes_guide`. Con `topic="generic_commands"` y `search`, la guía lista hasta
50 entradas que casan (subcadena, sin distinguir mayúsculas, en el comando o la
plantilla, la integración o área, la CAP o la familia) como tabla Markdown:
clave, categoría, tool dedicada o motivo, ejemplo de carga si la tabla lo
tiene; si hay más, lo dice y pide afinar. Sin `search`, el texto del tema. Las
`INSTRUCTIONS` dejan de decir «~216 tools» (sería falso con las genéricas y
cambiaría con las familias) y mencionan las genéricas en una línea.

**Porqué**: un argumento opcional se ve en el esquema de la tool (el cliente lo
descubre) y no cambia nada para quien no lo usa (FR-020 de la 008).

**Alternativas**: una tool nueva de consulta (otra tool más en la lista, de una
familia más); sintaxis dentro de `topic` (`commands/tag`, poco descubrible).

## R-9 — Enmiendas de la constitución

**Decisión**: texto de E-1…E-4 tal como lo propone el plan de la 008:

- **E-1 (IV, PATCH)**: «En una tool genérica, la vista previa describe
  exactamente el comando o la ruta, el método y la carga que se enviarán (con
  los secretos tapados) y dice que no interpreta su efecto. No anuncia efectos
  que no ocurren ni omite nada de lo que se envía. Lo que necesite una vista
  previa semántica tiene tool dedicada.»
- **E-2 (V, PATCH)**: «Una tool que ejecuta comandos según una tabla de
  clasificación es tan honesta como esa tabla: la clasificación forma parte de
  su descripción y se verifica automáticamente (ningún verbo de escritura en
  una categoría de lectura).»
- **E-3 (flujo, puerta 4, MINOR)**: «CI debe quedar en verde (`Tests`,
  `SAST (Semgrep)`, el banco de pruebas de Core y, en el repositorio público,
  `CodeQL`).»
- **E-4 (XI, PATCH)**: «Mientras una versión se desarrolla en una rama, su
  entrada del CHANGELOG puede llevar `<fecha de publicación>`; la fecha real se
  pone al publicar y nunca llega a `main` sin ella.»

E-1 y E-2 tocan principios I–VI: van en `docs/PRINCIPIOS.md` y en la
constitución en el mismo cambio. E-3 y E-4, solo en la constitución (VII–XI y
el flujo no están en `PRINCIPIOS.md`). Versión de la constitución: **1.1.0 →
1.2.0** (MINOR por E-3, que amplía una puerta; las demás son PATCH y quedan
absorbidas). `Last Amended` a la fecha del commit.

**Cómo encaja E-1 con el resumen de FR-010**: el resumen nombra **todas** las
claves con su tipo y tamaño y tapa solo valores; nada de lo que se envía queda
fuera. Si la lista completa no cabe en la respuesta, no hay token
(`preview_too_large`) en vez de una vista previa recortada.

## R-10 — Pruebas

- Unitarios con `DummyMCP`/`_RecordingMCP` y un `ha_client` simulado
  (`AsyncMock` de `ws_send`, `ws_one_shot_subscription`, `sv_request`,
  `sv_request_text`): la mayoría de las garantías son «no se llamó a HA».
- Guardas con tablas inyectadas (no dependen de cómo quede clasificado un
  comando concreto en la tabla real) y, además, con entradas reales de cada
  categoría para comprobar el cableado.
- Log capturado con structlog (`structlog.testing.capture_logs`), como en los
  tests de la 007.
- Banco de Core (010): una lectura y una escritura reales por la genérica.
- Extractor: árboles mínimos de código de ejemplo dentro de
  `tests/fixtures/inventario/` (un componente con `@websocket_command`, una
  constante importada, una colección de almacenamiento; un `api/__init__.py`
  del Supervisor con `web.get`/`web.post`). Nunca el código real de HA en el
  CI.
