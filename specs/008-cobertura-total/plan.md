# Plan de implementación: Hermes 1.2.0 — cobertura total (paraguas)

**Rama**: `feat/cobertura-total` (no se crea ninguna) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md)

## Resumen

Programa de 24 sub-features (009–032) que lleva Hermes de cubrir 130 comandos
de Core y 37 rutas del Supervisor a cubrir todo lo que HA 2026.11 ofrece a un
administrador, con un modelo **híbrido**: tools dedicadas para lo de prioridad
alta y media-alta y para lo que tiene consecuencias, y cuatro tools genéricas
gobernadas por una **tabla de clasificación** fail-closed para la cola larga y
la clase C. Un **banco de pruebas** con HA Core real en el CI ejecuta de verdad
las escrituras de Core. Todo sale como **una sola 1.2.0**.

Este plan no diseña tools concretas: fija el orden, el tamaño, las
dependencias, la arquitectura común y la trazabilidad. El diseño fino
(data-model, contratos, quickstart) es de cada sub-spec; por eso esta carpeta no
tiene `data-model.md`, `contracts/` ni `quickstart.md`. La fase 0 es
[research.md](research.md).

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x (MCPServer, Streamable HTTP sin estado), aiohttp, structlog, pydantic 2 · **Almacenamiento**: `/data` del add-on (tokens de confirmación, safety backups) · **Tests**: pytest, `unittest.IsolatedAsyncioTestCase`, `DummyMCP`, simuladores de HA y del Supervisor; nuevo: job del CI con HA Core 2026.11.1 en contenedor · **Plataforma**: add-on de Home Assistant OS.

**Restricciones**: fail-closed (III); dos pasos con token atado (IV); anotaciones verdaderas (V); control negativo (VII); repositorio público (VIII); cambios mínimos por sub-feature (IX); una sola versión 1.2.0 (decisión del mantenedor).

**Escala**: 623 comandos y 254 rutas que clasificar; unas 135 tools dedicadas nuevas estimadas (research R-2, antes de agrupar por parámetro) más 4 genéricas; de 216 tools hoy a unas 330–360 con todas las familias activas.

## Comprobación de la constitución

| Principio | Cumplimiento en el programa | Estado |
|---|---|---|
| I. Seguridad primero | Las genéricas solo ejecutan lo que la tabla permite; todo `confirm` va con vista previa; las respuestas pasan por el tope y la redacción (FR-001…FR-009). Las capacidades de riesgo alto tienen tool dedicada con vista previa semántica (FR-018). | OK |
| II. Secretos | Cargas y respuestas con secretos tapados en vista previa, error y log; log de genéricas solo con nombres de claves (FR-008, FR-019); `client_secret`, claves de red y credenciales de registros nunca salen (FR-079, FR-088, FR-089); centinelas por familia (SC-008). | OK |
| III. Fail-closed | Lo no clasificado se rechaza (FR-003); lo pendiente de tool dedicada es `deny` hasta que existe (FR-002); familia desconocida → no arranca (FR-010); comando nuevo de HA → rechazado y señalado por la deriva (FR-005). | OK |
| IV. Dos pasos, token atado | Todo `confirm` de las genéricas va siempre en dos pasos con el token atado al comando y a la carga (FR-006, FR-007). **Matiz**: la vista previa genérica describe exactamente lo que se envía, pero no interpreta su efecto en HA. Se propone aclararlo (enmienda E-1). | OK, con enmienda propuesta |
| V. Nombre y descripción | Genéricas separadas en lectura y escritura para que `readOnlyHint` sea verdad; el test de verbos (FR-004) es la garantía de que la de lectura no escribe. Anotaciones por nombre exacto en lo que pueda heredar un prefijo engañoso (FR-091). **Matiz**: la honestidad de la genérica de lectura depende de la tabla; se propone escribirlo (enmienda E-2). | OK, con enmienda propuesta |
| VI. Lo que no se puede probar | Banco con HA Core real (FR-013…FR-015); lo que no se puede probar en el CI queda en la matriz como pendiente manual (FR-016). «La suite corre contra las mismas versiones que se despliegan» se cumple por primera vez para Core. | OK |
| VII. Control negativo | Cada sub-feature lleva tests de regresión con control negativo anotado (FR-018); las guardas de la tabla también (SC-004). | OK |
| VIII. Privacidad | Fixtures con marcadores genéricos; credenciales del banco generadas en el job y nunca impresas (FR-013, FR-021); revisión del diff en cada commit y al cierre (SC-010). | OK |
| IX. Cambios mínimos | Una spec por sub-feature, un asunto por cambio; lo que no está en el programa se anota como duda (D-01…D-10). Las tools existentes solo cambian donde una CAP lo pide, con argumentos opcionales (FR-020). | OK |
| X. Comentarios en español | Igual que hoy: comentarios y mensajes de arranque en español; nombres de tools, eventos y descripciones al cliente en inglés. | OK |
| XI. Versionado | 1.2.0 en los tres sitios una sola vez (009); una entrada de CHANGELOG. **Matiz**: durante el programa la cabecera lleva `<fecha de publicación>` en vez de `AAAA-MM-DD` hasta publicar; se propone aclararlo (enmienda E-4). | OK, con enmienda propuesta |
| Flujo, puerta 4 (CI en verde) | El job del banco de Core se añade a los checks; se propone que la constitución lo nombre (enmienda E-3). | OK, con enmienda propuesta |

**Enmiendas propuestas** (no se aplican en esta spec; las decide el mantenedor
y, si se aceptan, van en `docs/PRINCIPIOS.md` y en la constitución en el mismo
cambio, en la sub-feature 011 antes de su código, como hizo la 007):

- **E-1 (principio IV, PATCH)**: añadir «En una tool genérica, la vista previa
  describe exactamente el comando o la ruta, el método y la carga que se
  enviarán (con los secretos tapados) y dice que no interpreta su efecto. No
  anuncia efectos que no ocurren ni omite nada de lo que se envía. Lo que
  necesite una vista previa semántica tiene tool dedicada.»
- **E-2 (principio V, PATCH)**: añadir «Una tool que ejecuta comandos según una
  tabla de clasificación es tan honesta como esa tabla: la clasificación forma
  parte de su descripción y se verifica automáticamente (ningún verbo de
  escritura en una categoría de lectura).»
- **E-3 (flujo, puerta 4, MINOR)**: «CI debe quedar en verde (`Tests`,
  `SAST (Semgrep)`, el banco de pruebas de Core y, en el repositorio público,
  `CodeQL`).»
- **E-4 (principio XI, PATCH)**: «Mientras una versión se desarrolla en una
  rama, su entrada del CHANGELOG puede llevar `<fecha de publicación>`; la
  fecha real se pone al publicar y nunca llega a `main` sin ella.»

Tras el diseño: sin cambios en la tabla. Ninguna desviación queda sin
justificar.

## El programa

### Sub-features

Tamaño: S (un tramo corto), M (2 tramos), L (3 tramos). Un tramo es el trabajo
de un agente sin llenar su contexto: unas 6–9 tools nuevas con sus tests o un
cambio transversal acotado. La columna «Ola» es el orden: una ola empieza
cuando terminan sus dependencias; dentro de una ola, las sub-features van en
paralelo.

| N.º | Nombre | CAP | FR | Depende de | Ola | Tools nuevas (est.) | Tamaño | Tramos |
|---|---|---|---|---|---|---|---|---|
| 009 | `correcciones-pendientes` (y versión 1.2.0) | 010–018, 021, 024 | FR-022, FR-025…FR-035 | — | 0 | 0 | M | 2 |
| 010 | `banco-de-pruebas-core` (infraestructura y helpers) | 005, 034 (Core, parte) | FR-013, FR-014 | — | 0 | 0 | M | 2 |
| 011 | `politica-de-comandos` (tabla, genéricas, familias, deriva, guía) | 001, 002, 003, 004, 007, 008 | FR-001…FR-012 | 009, 010 | 1 | 4 | L | 3 |
| 028 | `pruebas-escrituras-core` (resto de escrituras de Core en el banco) | 034 (Core, resto) | FR-014 | 010 | 1 | 0 | M | 2 |
| 012 | `diagnostico-core` | 040, 041, 042, 047 | FR-036…FR-039 | 009, 011 | 2 | ~12 | M | 2 |
| 029 | `estado-y-estadisticas-core` | 043, 049, 058, 068 | FR-040…FR-043 | 011 | 2 | ~7 | M | 2 |
| 013 | `diagnostico-supervisor` | 081, 085, 087 (lectura), 088, 089 | FR-044…FR-048 | 009, 011 | 2 | ~11 | M | 2 |
| 014 | `banco-de-pruebas-supervisor` (procedimiento, matriz, `hassio_role`) | 006, 022, 034 (Supervisor), 035 | FR-016, FR-017 | 010 | 2 | 0 | S | 1 |
| 016 | `integraciones-flujos-y-repairs` | 036, 037, 044, 045, 048 | FR-053…FR-057 | 011 | 2 | ~14 | L | 3 |
| 018 | `mejoras-de-tools-existentes` | 019, 020, 023 | FR-063…FR-065 | 011 | 2 | 0 | M | 2 |
| 027 | `plataforma-y-deprecaciones` | 025, 026, 028, 029, 030, 031, 032, 033 | FR-092…FR-097 | — | 2 | 0 | S | 1 |
| 015 | `actualizaciones-del-sistema` | 064, 080 | FR-049, FR-050 | 013 | 3 | ~7 | M | 2 |
| 030 | `tienda-de-apps` | 082, 093 | FR-051, FR-052 | 011 | 3 | ~9 | M | 2 |
| 017 | `automatizacion-asistida` | 038, 040 (al guardar), 046, 051, 052 | FR-058…FR-062 | 012 | 3 | ~14 | L | 3 |
| 019 | `montajes-y-ajustes-de-backup` | 083 | FR-066 | 011 | 3 | ~9 | M | 2 |
| 031 | `backups-integracion-y-cifrado` | 027, 057 | FR-067, FR-068 | 011 | 3 | ~3 | M | 2 |
| 020 | `estadisticas-y-energia` | 050, 054 | FR-069, FR-070 | 029 | 3 | ~7 | M | 2 |
| 021 | `configuracion-del-sistema` | 053, 055, 056, 069, 074 | FR-071…FR-075 | 011 | 3 | ~12 | L | 3 |
| 022 | `control-de-core-y-supervisor` | 084, 087 (escritura), 091, 092, 094 | FR-076…FR-080 | 013 | 3 | ~8 | M | 2 |
| 032 | `host-y-red-del-host` | 086, 090 | FR-081, FR-082 | 013 | 3 | ~7 | M | 2 |
| 023 | `assist-y-conversacion` | 060, 061, 062, 063 | FR-083, FR-084 | 018 | 3 | ~4 | S | 1 |
| 024 | `menores-core` | 059, 065, 066, 067, 070, 071, 072, 073 | FR-085…FR-088 | 011 | 3 | ~3 | M | 2 |
| 025 | `integraciones-especificas` (clase C por la tabla) | 100–106 | FR-089, FR-090 | 011 | 3 | 0 | M | 2 |
| 026 | `marketplace-escritura` | 075 | FR-091 | 030 | 4 | ~8 | M | 2 |

Totales: 24 sub-features, 49 tramos. Transversales a todas: FR-012, FR-015,
FR-018…FR-021, FR-023, FR-024. Cierre: FR-098.

### Cambios respecto a research R-6

- **Una sola versión**: desaparece la columna de versión; todo es 1.2.0
  (decisión 3). La subida de versión entra en 009.
- **009 ya no es 1.1.3** y añade FR-022 (versión y esqueleto del CHANGELOG).
- **010 se parte** en 010 (infraestructura del banco, Supervisor simulado y las
  escrituras de los 11 dominios de helpers, que siguen un mismo patrón) y **028**
  (automatizaciones, scripts, escenas, registros, Lovelace, flujos de config
  entries, servicios, eventos y temporizadores): unas 100 tools `ha_*`
  modifican y no caben con la infraestructura en dos tramos.
- **011 depende de 009 y 010**: de 009 por la redacción lineal (las genéricas
  devuelven textos grandes) y de 010 para ejecutar las genéricas de verdad.
- **012 se parte** en 012 (validación, logs, diagnósticos, notificaciones) y
  **029** (salud, estadísticas de lectura y las dos CAP que van por la tabla).
- **014 deja de montar una VM** (decisión 2): solo procedimiento, matriz,
  comentario de `hassio_role` y pruebas manuales; ya no bloquea a 015, 019, 022
  ni 026, que se prueban con simuladores y quedan con prueba real pendiente.
- **015 se parte** en 015 (actualizaciones) y **030** (tienda de apps).
- **019 se parte** en 019 (montajes y ajustes del Supervisor) y **031**
  (backups de la integración y cifrado de safety backups).
- **022 se parte** en 022 (control de Core y Supervisor, y lo que va por la
  tabla) y **032** (host y red del host, riesgo alto o muy alto).
- **026 depende de 030**, no de 014: comparte el patrón de textos de terceros y
  backup previo de la tienda.
- **027 no retira nada** (decisión 3): solo documenta fechas y lo bloqueado.
- Los números nuevos (028–032) son los siguientes libres; el orden lo da la
  columna «Ola», no el número.

### Cómo se reparte cada CAP entre dedicada y tabla

Regla (decisión 1): **dedicada** si la CAP es de prioridad alta o media-alta,
o si modifica algo con consecuencias y la vista previa útil necesita entender
el efecto (riesgo medio-alto o más, o reescribe datos). **Tabla** para el resto
de la clase A (lecturas y escrituras de bajo riesgo de prioridad media o baja)
y para toda la clase C. Dentro de una CAP dedicada, sus lecturas menores pueden
ir por la tabla si la sub-spec lo justifica; lo que escribe con consecuencias,
nunca.

## Arquitectura (alto nivel; el detalle es de la spec 011)

1. **Tabla de clasificación**: un módulo de datos neutral (al estilo de
   `service_policy.py`) generado desde los inventarios por un script versionado
   fuera de `hermes/src` y revisado a mano. Claves: comando WS de Core;
   método + plantilla de ruta del Supervisor (con `{app}`, `{slug}`…). Campos:
   categoría, motivo, familia, tool dedicada, CAP, `redact`, `one_shot`. Se
   consulta en memoria; no se lee de disco en cada llamada.
2. **Guardas en orden**: validar forma (tipo de comando o ruta normalizada) →
   buscar en la tabla (si no está: `command_not_classified`) → categoría
   (`dedicated`/`deny` rechazan; `read` solo en la genérica de lectura;
   `confirm` solo en la de escritura) → dos pasos para `confirm` →
   ejecución → tope y redacción → log sin valores.
3. **Genéricas de Core** sobre el cliente WebSocket existente de `ha.py`
   (incluido el patrón `ws_one_shot_subscription` para `one_shot`).
   **Genéricas del Supervisor** sobre `sv_request*`, con la misma validación de
   ruta que `ha.py` y `/core/api*` siempre rechazado.
4. **Familias**: cada módulo de tools declara su familia; `register_all_tools`
   omite las desactivadas; las anotaciones siguen en `tools/_annotations.py`. La
   opción vive en `config.yaml` (esquema y traducciones) con valor por defecto
   «todas activas».
5. **Deriva**: test que carga los dos TSV y la tabla y compara claves; el test
   de verbos recorre la tabla. Con una HA nueva: regenerar inventario → el test
   falla con la lista de diferencias → clasificar → verde.
6. **Banco de Core**: job de GitHub Actions con la imagen de Core por digest
   como servicio; onboarding por REST y token de larga duración por WebSocket
   generados en el job; Supervisor simulado (aiohttp) en `tests/` que responde
   a `/supervisor/ping` y `/core/info` y reenvía `/core/api/*` (REST y
   WebSocket); los tests del banco se marcan para correr solo en ese job.

## Trazabilidad

La matriz siguiente es la fuente de verdad del programa. Cada sub-spec la
actualiza: rellena la columna de tool o entrada de la tabla con los nombres
definitivos y la de test con el fichero. Al cierre (FR-098) no queda ninguna
fila sin test o sin entrada en la hoja de ruta. Vía: **D** = tool dedicada,
**T** = tabla (`read`/`confirm`) con las genéricas, **D+T** = mixta, **X** =
cambio transversal o de una tool existente, **M** = manual o documental.

| CAP | Prio. | Sub-feature | FR | Vía | Test previsto |
|---|---|---|---|---|---|
| CAP-001 | alta | 011 | FR-001…FR-005, FR-012 | X | deriva, verbos, guardas con control negativo |
| CAP-002 | alta | 011 | FR-006, FR-008, FR-009 | X | genéricas de Core en unitarios y banco |
| CAP-003 | media-alta | 011 | FR-007, FR-008 | X | genéricas del Supervisor con simulador; rutas maliciosas |
| CAP-004 | alta | 011 | FR-010 | X | registro con familias; opción inválida no arranca |
| CAP-005 | alta | 010 | FR-013 | X | job del banco en el CI |
| CAP-006 | alta | 014 | FR-016 | M | procedimiento y matriz en la hoja de ruta |
| CAP-007 | media-alta | 011 | FR-005 | X | test de deriva |
| CAP-008 | media | 011 | FR-011 | X | test de la guía y de la consulta de la tabla |
| CAP-010 | alta | 009 | FR-025 | X | test de tiempo |
| CAP-011 | media | 009 | FR-026 | X | log capturado sin URLs |
| CAP-012 | media | 009 | FR-027 | X | log capturado sin `entity_id` |
| CAP-013 | baja | 009 | FR-028 | X | redacción de `ip-a-b-c-d` |
| CAP-014 | baja | 009 | FR-029 | X | campos de redacción de `sv_get_addon_logs` |
| CAP-015 | baja | 009 | FR-030 | X | `_response_limit` en `ha_get_history` |
| CAP-016 | media | 009 | FR-031 | X | `ha_marketplace_list_removed` con filtros |
| CAP-017 | baja | 009 | FR-032 | X | eventos `*_ok` |
| CAP-018 | baja | 009 | FR-033 | X | coste del barrido |
| CAP-019 | alta | 018 | FR-063 | X | guardado por vistas (unitario y banco) |
| CAP-020 | media-alta | 018 | FR-064 | X | denylist con token en `ha_call_service_response` |
| CAP-021 | media | 009 | FR-034 | X | rechazo previo sin token |
| CAP-022 | alta | 014 | FR-017 | M | prueba manual de `manager` (pendiente) |
| CAP-023 | media | 018 | FR-018, FR-065 | X | sobre común en tools nuevas |
| CAP-024 | baja | 009 | FR-035 | X | apagado sin traceback |
| CAP-025 | baja | 027 | FR-092 | M | descripción y guía |
| CAP-026 | baja | 027 | FR-093 | M | hoja de ruta |
| CAP-027 | media | 031 | FR-068 | X | safety backup cifrado y restaurable |
| CAP-028 | baja | 027 | FR-094 | M | hoja de ruta |
| CAP-029 | baja | 027 | FR-095 | X | textos de opciones y descripciones |
| CAP-030 | media | 027 | FR-020, FR-096 | M | sigue registrada y deprecada |
| CAP-031 | media | 027 | FR-020, FR-096 | M | alias siguen con `_deprecated` |
| CAP-032 | baja (bloqueada) | 027 | FR-097 | M | hoja de ruta |
| CAP-033 | baja (bloqueada) | 027 | FR-097 | M | hoja de ruta; deriva |
| CAP-034 | alta | 010, 028, 014 | FR-014…FR-016 | X+M | banco de Core; matriz del Supervisor |
| CAP-035 | media | 014 | FR-016 | M | matriz de pruebas manuales |
| CAP-036 | media | 016 | FR-056 | X | textos traducidos en Repairs |
| CAP-037 | baja | 016 | FR-057 | M | tema de la guía |
| CAP-038 | baja | 017 | FR-061 | D | espera de trigger (banco) |
| CAP-040 | alta | 012, 017 | FR-036, FR-062 | D+X | validación (banco) |
| CAP-041 | alta | 012 | FR-037 | D | logs y niveles (banco) |
| CAP-042 | alta | 012 | FR-038 | D | diagnósticos (banco) |
| CAP-043 | alta | 029 | FR-040 | D | salud y estado (banco) |
| CAP-044 | alta | 016 | FR-053 | D | descubiertas y preferencias (banco) |
| CAP-045 | alta | 016 | FR-054 | D | subentries y reconfigure (banco) |
| CAP-046 | alta | 017 | FR-058 | D | blueprints (banco) |
| CAP-047 | alta | 012 | FR-039 | D | notificaciones (banco) |
| CAP-048 | media-alta | 016 | FR-055 | D | flujos de reparación (unitario; banco si hay issue reproducible) |
| CAP-049 | media-alta | 029 | FR-041 | D | estadísticas de lectura (banco) |
| CAP-050 | media-alta | 020 | FR-069 | D | mantenimiento de estadísticas (banco) |
| CAP-051 | media-alta | 017 | FR-059 | D | automatizaciones de dispositivo (banco) |
| CAP-052 | media-alta | 017 | FR-060 | D | targets (banco) |
| CAP-053 | media | 021 | FR-071 | D+T | configuración del núcleo (banco) |
| CAP-054 | media | 020 | FR-070 | D+T | energía (banco) |
| CAP-055 | media | 021 | FR-072 | D | exposición (banco) |
| CAP-056 | media | 021 | FR-073 | D | usuarios (banco; protecciones con control negativo) |
| CAP-057 | media | 031 | FR-067 | D+T | backups de la integración (banco) |
| CAP-058 | media | 029 | FR-042 | T | entrada `read` (banco) |
| CAP-059 | media | 024 | FR-085 | D+T | instantánea con cámara simulada (banco) |
| CAP-060 | media-alta | 023 | FR-083 | D | conversación (banco) |
| CAP-061 | baja | 023 | FR-084 | T | entradas de pipelines (banco) |
| CAP-062 | baja | 023 | FR-084 | T | entradas de motores (banco) |
| CAP-063 | baja | 023 | FR-084 | T | entradas de satélites (unitario) |
| CAP-064 | media-alta | 015 | FR-050 | D | notas e instalación de `update` (banco con entidad simulada) |
| CAP-065 | baja | 024 | FR-087 | T | calendario y tareas (banco con `local_calendar`/`local_todo`) |
| CAP-066 | baja | 024 | FR-087 | T | tags (banco) |
| CAP-067 | baja | 024 | FR-087 | T | medios (banco) |
| CAP-068 | media | 029 | FR-043 | T | red y HTTP lectura (banco) |
| CAP-069 | baja | 021 | FR-074 | D | red y HTTP escritura (unitario; banco solo vista previa) |
| CAP-070 | baja | 024 | FR-087 | T | registros (banco) |
| CAP-071 | baja | 024 | FR-086 | D+T | restablecer dashboard (banco; protección del principal) |
| CAP-072 | baja | 024 | FR-087 | T | imágenes subidas (banco) |
| CAP-073 | baja | 024 | FR-088 | T | credenciales sin `client_secret` (centinela) |
| CAP-074 | baja | 021 | FR-075 | T | analytics y labs (banco) |
| CAP-075 | baja | 026 | FR-091 | D | Marketplace escritura (unitario; en vivo pendiente) |
| CAP-080 | alta | 015 | FR-049 | D | actualizaciones (simulador; VM pendiente) |
| CAP-081 | alta | 013 | FR-044 | D | logs del sistema (simulador) |
| CAP-082 | alta | 030 | FR-051 | D | tienda (simulador) |
| CAP-083 | alta | 019 | FR-066 | D | montajes (simulador; centinela CIFS) |
| CAP-084 | media | 022 | FR-076 | D+T | control de Core y Supervisor (simulador) |
| CAP-085 | media-alta | 013 | FR-045 | D | disco y OS (simulador) |
| CAP-086 | media | 032 | FR-081 | D | host y OS escritura (simulador) |
| CAP-087 | media | 013, 022 | FR-046, FR-077 | D+T | jobs y resolución (simulador) |
| CAP-088 | media | 013 | FR-047 | T | entradas de hardware (simulador) |
| CAP-089 | media | 013 | FR-048 | T | entradas de red del host (simulador) |
| CAP-090 | baja | 032 | FR-082 | D | red del host escritura (simulador; interfaz propia rechazada) |
| CAP-091 | baja | 022 | FR-078 | T | plugins (simulador) |
| CAP-092 | baja | 022 | FR-079 | T | registros Docker (centinela) |
| CAP-093 | media | 030 | FR-052 | D+X | rebuild y validación de opciones (simulador) |
| CAP-094 | baja | 022 | FR-080 | T | placas y hora (simulador) |
| CAP-100 | media | 025 | FR-089, FR-090 | T | Z-Wave por la tabla (unitario) |
| CAP-101 | media | 025 | FR-089, FR-090 | T | ZHA por la tabla (unitario) |
| CAP-102 | baja | 025 | FR-089, FR-090 | T | Matter por la tabla (unitario) |
| CAP-103 | baja | 025 | FR-089, FR-090 | T | Thread/OTBR; clave de red `deny` (unitario) |
| CAP-104 | media | 025 | FR-089, FR-090 | T | MQTT por la tabla (banco con MQTT si es viable) |
| CAP-105 | baja | 025 | FR-089, FR-090 | T | USB por la tabla (unitario) |
| CAP-106 | baja | 025 | FR-089, FR-090 | T | resto; secretos `deny` (unitario) |

95 CAP, todas con sub-feature y FR. Ninguna CAP queda excluida: lo excluido es
la clase B y la clase D (spec, «Exclusiones»), que no tiene CAP.

## Banco de pruebas: qué se prueba dónde

| Entorno | Qué | Cuándo |
|---|---|---|
| Suite unitaria (simuladores de HA y del Supervisor) | Todo, como hoy; todas las `sv_*` y guardas | Cada commit |
| Banco de Core en el CI (HA Core 2026.11.1 real + Supervisor simulado) | Escrituras `ha_*` de la 1.1.2 (010, 028), tools nuevas de Core y una entrada por familia de la tabla (FR-015) | Cada PR y push a la rama |
| VM con HAOS (procedimiento de 014) | `sv_*` que reinician, apagan, restauran, desinstalan; actualizaciones; `hassio_role: manager` | Manual, al final |
| Instalación real tras publicar | Pruebas en vivo de las tools nuevas | Manual, tras publicar |

## Versionado y documentación

- 009 sube la versión a 1.2.0 y abre `## [1.2.0] — <fecha de publicación>` con
  una sección por bloque (Diagnóstico, Integraciones, Automatización,
  Supervisor, Sistema, Política y genéricas, Banco de pruebas, Correcciones).
- Cada sub-feature añade su parte del CHANGELOG, la guía, `README.md` y
  `README.es.md`, `DOCS.md` y `SECURITY.md` cuando le toca (FR-023), y pasa su
  fila de la hoja de ruta de «pendiente» a «hecha».
- El cierre pone la fecha, revisa todo y abre el PR; fusionar y publicar es del
  mantenedor.

## Riesgos

- **Una mala clasificación abre una puerta**: mitigado por fail-closed, el
  test de verbos, la revisión manual y `deny` «pendiente» para lo que tendrá
  tool dedicada.
- **Programa largo sin publicar** (research R-5 c): decisión del mantenedor;
  mitigado con PRs por sub-feature contra la rama, el banco en cada PR y el
  CHANGELOG al día.
- **Coste de contexto** (~350 KB de lista con todo activo): familias
  desactivables; duda D-04.
- **Imagen de Core grande o lenta en el CI**: fijada por digest y cacheada; si
  el job tarda demasiado, los tests del banco se reparten en varios jobs.
- **Deriva con HA 2026.12**: el inventario se regenera y el test la señala; no
  bloquea la 1.2.0 si se publica antes.

## Ficheros de este paraguas

- `specs/008-cobertura-total/`: `spec.md`, `plan.md`, `tasks.md`,
  `research.md`, `checklists/requirements.md`, `inventario/core-ws.tsv`,
  `inventario/supervisor-rutas.tsv`.
- `docs/HOJA-DE-RUTA.md`: correcciones de research R-1 y sección del programa.
- Las sub-features crean `specs/NNN-nombre/` y tocan código, tests y docs según
  su propio plan.
