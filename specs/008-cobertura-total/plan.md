# Plan de implementación: Hermes 1.2.0 — cobertura total (paraguas)

**Rama**: `feat/cobertura-total` (no se crea ninguna) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md)

## Resumen

Programa de 25 sub-features (009–033) que lleva Hermes de cubrir 130 comandos
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
| 033 | `arreglos-del-banco` (tools de la 1.1.2 rotas o deshonestas que destapa el banco) | 039 | FR-099 | 011, 028 | 2 | 0 | M | 2 |
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
| 025 | `integraciones-especificas` (clase C por la tabla) | 100–106 | FR-089, FR-090 | 011 | 3 | 0 | L | 3 |
| 026 | `marketplace-escritura` | 075 | FR-091 | 030 | 4 | ~8 | M | 2 |

Totales: 25 sub-features, 52 tramos (la 025 pasó de 2 a 3 tramos: research R-9 de la 025). Transversales a todas: FR-012, FR-015,
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
- **033 se añade después** (no estaba en R-6): arregla las tools de la 1.1.2
  que el banco de Core y las revisiones de la 010 y la 028 muestran rotas o
  deshonestas (CAP-039, FR-099). Depende de 011 (instantánea de esquemas) y de
  028 (banco de automatizaciones, scripts y escenas).
- Los números nuevos (028–033) son los siguientes libres; el orden lo da la
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
| CAP-001 | alta | 011 | FR-001…FR-005, FR-012 | X | `hermes/src/hermes/command_table.py` y `command_policy.py`: `TestDeriva`, `TestVerbos`, `TestEstructura`, `TestDedicadas`, `TestReglasDeLaClasificacionInicial` (`tests/test_command_table.py`); `TestDecidir`, `TestValidarRuta`, `TestCasarRuta`, `TestBuscarCore`, `TestResumirCarga` (`tests/test_command_policy.py`) |
| CAP-002 | alta | 011 | FR-006, FR-008, FR-009 | X | `ha_read_ws_command`, `ha_call_ws_command`: `TestLecturaCore`, `TestEscrituraCore` y sus `…TablaReal` (`tests/test_tools_generic_commands.py`); banco: `tests/banco/test_banco_genericas.py` |
| CAP-003 | media-alta | 011 | FR-007, FR-008 | X | `sv_read_api`, `sv_call_api`: `TestSupervisor`, `TestSupervisorTablaReal` (`tests/test_tools_generic_commands.py`), `TestValidarRuta` (`tests/test_command_policy.py`) |
| CAP-004 | alta | 011 | FR-010 | X | `tool_families.py` y `tool_families_disabled`: `TestCatalogo`, `TestValidarDesactivadas`, `TestAliasDeFamilias` (`tests/test_tool_families.py`), `TestToolFamiliesDisabled` (`tests/test_config_validation.py`), `TestRegistroPorFamilias` con SC-005 (`tests/test_tools_registration.py`), `TestFamiliasDesactivadasInyectadas`, `TestFamiliasDesdeElRegistro` (`tests/test_tools_generic_commands.py`) |
| CAP-005 | alta | 010 | FR-013 | X | job del banco en el CI: `tests/test_banco_workflow.py`, `tests/banco/test_banco_humo.py` |
| CAP-006 | alta | 014 | FR-016 | M | procedimiento `docs/BANCO-SUPERVISOR.md` y matriz en la hoja de ruta: `tests/test_matriz_pruebas.py` (`test_procedimiento_con_sus_secciones`) |
| CAP-007 | media-alta | 011 | FR-005 | X | `scripts/inventario/extraer.py` y `generar_tabla.py`: `TestDeriva` (`tests/test_command_table.py`), `tests/test_command_inventory.py`, `tests/test_generar_tabla.py`, `tests/test_extractor_inventario.py` |
| CAP-008 | media | 011 | FR-011 | X | `hermes_guide(topic="generic_commands", search=…)`: `TestTemaGenericCommands` (`tests/test_tools_guide.py`), `TestRegistro.test_la_guia_que_citan_existe_y_busca` (`tests/test_tools_generic_commands.py`) |
| CAP-010 | alta | 009 | FR-025 | X | `TestRedaccionLineal` y `TestRedaccionDiferencial` (`tests/test_redact_secrets.py`) |
| CAP-011 | media | 009 | FR-026 | X | `TestHostsDeLasUrlsDeHA` (`tests/test_log_redact_network.py`), `TestUrlsDeHAAlConectar` (`tests/test_ha_ws_reliability.py`) |
| CAP-012 | media | 009 | FR-027 | X | `TestClasificacionSinEntityId` (`tests/test_call_service_security.py`) |
| CAP-013 | baja | 009 | FR-028 | X | `TestIpConGuiones` (`tests/test_log_redact_network.py`) |
| CAP-014 | baja | 009 | FR-029 | X | `TestQueRedactoElLog` (`tests/test_tools_supervisor.py`) |
| CAP-015 | baja | 009 | FR-030 | X | `TestLimiteDeRespuestaDelHistorial` (`tests/test_tools_history_logbook.py`), `test_history_con_tope_justo_cabe_con_el_bloque` (`tests/test_response_limit.py`) |
| CAP-016 | media | 009 | FR-031 | X | `TestRetiradosConFiltros` (`tests/test_tools_marketplace.py`) |
| CAP-017 | baja | 009 | FR-032 | X | `TestEventosOk` (`tests/test_tools_marketplace.py`), `TestEventoOk` (`tests/test_tools_resolution.py`) |
| CAP-018 | baja | 009 | FR-033 | X | `TestBarridoAcotado` (`tests/test_security.py`) |
| CAP-019 | alta | 018 | FR-063 | X | `ha_save_lovelace_dashboard` con `view_index` y `view`: `TestGuardarPorVista` (`tests/test_tools_lovelace.py`), `TestTokenAtadoAlEstado` (`tests/test_security.py`); banco: `TestGuardadoPorVista` (`tests/banco/test_banco_mejoras.py`) |
| CAP-020 | media-alta | 018 | FR-064 | X | `ha_call_service_response` con `confirmation_token`: `TestCallServiceResponseConfirmacion` y `TestGuardaDeClienteConRespuesta` (`tests/test_call_service_security.py`); banco: `TestRespuestaConfirmada` (`tests/banco/test_banco_mejoras.py`) |
| CAP-021 | media | 009 | FR-034 | X | `TestNoSeActualizaASiMismo` (`tests/test_tools_supervisor.py`) |
| CAP-022 | alta | 014 | FR-017 | X+M | `tests/test_addon_manifest.py` (`TestComentarioDelRol`), `tests/test_rutas_supervisor_rol.py`; prueba manual de `manager` (pendiente) |
| CAP-023 | media | 018 | FR-018, FR-065 | X | `sobre_de_lista` (`tools/_common.py`): `TestConstructor`, `TestGenericasSinCambios`, `TestTransversal` y `TestControlSintetico` (`tests/test_sobre_de_lista.py`) |
| CAP-024 | baja | 009 | FR-035 | X | `TestApagadoSinTraza` (`tests/test_boot_shutdown_diagnostics.py`) |
| CAP-025 | baja | 027 | FR-092 | X | `sv_get_job_status` (`child_errors`, `success` con los sub-jobs, `child_jobs` redactado) y sondeo del safety backup: `TestChildJobErrors`, `TestSondeoSubJobs` (`tests/test_supervisor_jobs.py`), `TestJobStatusSubJobs` (`tests/test_tools_supervisor.py`); guía: `TestGuiaJobs` (`tests/test_tools_guide.py`); hoja de ruta, «Distinguir errores fatales de avisos» |
| CAP-026 | baja | 027 | FR-093 | M | hoja de ruta, «Hosts CIMD conocidos»; valor por defecto: `TestCimdPorDefecto` (`tests/test_deprecaciones.py`) |
| CAP-027 | media | 031 | FR-068 | X | `sv_create_safety_backup`, el safety backup automático de `fs_write` (`maybe_trigger_safety_backup`), `safety_retention` (`encrypted` en la anotación) y la opción `safety_backup_encryption` (`auto`/`required`/`off`); `sv_restore_backup_*` con la clave de HA: `tests/test_safety_backup_encryption.py`, `TestRetencionDeCifrados` (`tests/test_safety_retention.py`), `tests/test_sv_restore_backup_key.py`, `tests/test_backup_key.py`, `TestSafetyBackupEncryption` (`tests/test_config_validation.py`); **desviación de FR-068** (D-031-1, aceptada por el supervisor del programa): se cifran con la clave de los backups de HA (la del kit de emergencia), que Hermes lee en cada uso y no guarda, y no con una contraseña generada y guardada en `/data`, que solo Hermes conocería y viajaría dentro del propio backup; cumple la intención (cifrados, nunca devuelta ni registrada, restaurables, también con Hermes roto). En vivo, pendiente (VM de la 014, después instalación real) |
| CAP-028 | baja | 027 | FR-094 | M | hoja de ruta, «`outputSchema` y alternativas nativas de MCP»; `TestSinDeprecacionesDelSdk`, `TestTopeDelSdk` (`tests/test_sdk_deprecaciones.py`); `tests/test_tareas_aplazadas.py` |
| CAP-029 | baja | 027 | FR-095 | X | `translations/en.yaml` y `es.yaml`: `tests/test_translations.py`; descripciones de las tools de apps: `TestTerminologiaApps` (`tests/test_tools_supervisor.py`); guía: `TestGuiaApps` (`tests/test_tools_guide.py`) |
| CAP-030 | media | 027 | FR-020, FR-096 | X | `ha_remove_device_from_config_entry` sigue registrada y deprecada: `TestDeprecadasSiguen`, `TestDispositivosSinCamposDeprecados` (`tests/test_deprecaciones.py`); `command_removed_in_ha`: `TestComandoRetiradoEnHA` (`tests/test_tools_registry_device.py`); hoja de ruta, «Deprecaciones con fecha» |
| CAP-031 | media | 027 | FR-020, FR-096 | M | alias `ha_hacs_*` siguen con `_deprecated` hasta la 1.3.0: `TestDeprecadasSiguen` (`tests/test_deprecaciones.py`), `tests/test_tools_hacs.py`; hoja de ruta, «Deprecaciones con fecha» |
| CAP-032 | baja (bloqueada) | 027 | FR-097 | M | detección al arrancar: `TestSocketOfrecido`, `TestComprobarPlataforma` (`tests/test_supervisor_platform.py`), `test_boot_comprueba_la_plataforma_tras_conectar_y_antes_del_mcp` (`tests/test_main_wiring.py`); hoja de ruta, «Socket Unix y API `/v2` del Supervisor: qué hará falta» |
| CAP-033 | baja (bloqueada) | 027 | FR-097 | M | detección al arrancar: `TestApiV2Activada`, `TestComprobarPlataforma` (`tests/test_supervisor_platform.py`); deriva de la V1: `TestDeriva` (`tests/test_command_table.py`); hoja de ruta, «Socket Unix y API `/v2` del Supervisor: qué hará falta» |
| CAP-034 | alta | 010, 028, 014 | FR-014…FR-016 | X+M | banco de Core: `tests/banco/test_banco_humo.py`, `tests/banco/test_banco_helpers_*.py`, `tests/test_banco_cobertura.py` (010); `tests/banco/test_banco_escrituras_*.py`, `tests/test_banco_cobertura_escrituras.py` (028); matriz del Supervisor: `tests/test_matriz_pruebas.py` (014) |
| CAP-035 | media | 014 | FR-016 | M | casillas de pruebas manuales con su entorno: `tests/test_matriz_pruebas.py` (`test_casillas_manuales`) |
| CAP-036 | media | 016 | FR-056 | X | `ha_list_repairs` y `ha_ignore_repair` con textos (`tools/_translations.py`): `tests/test_tools_translations.py`, `TestTextosDeLosAvisos` (`tests/test_tools_repairs.py`); banco: `TestTextosDeRepairs` (`tests/banco/test_banco_repairs.py`); `frontend/get_translations` sigue `deny` con comentario |
| CAP-037 | baja | 016 | FR-057 | M | sección «Helpers por config entry» del tema `helpers`: `TestTemaIntegrationFlows.test_helpers_por_config_entry` (`tests/test_tools_guide.py`) |
| CAP-038 | baja | 017 | FR-061 | D | `ha_wait_for_trigger` (familia `automation_assist`; `subscribe_trigger` reclasificado de B a A y `dedicated`): `tests/test_tools_wait_for_trigger.py`, `tests/test_ha_ws_subscribe_queue.py`, `TestGestorCompartido` (`tests/test_tools_wait_for_event.py`), `TestEsperaDeTriggerRegistration` (`tests/test_tools_registration.py`), `TestDedicadaDeLa017TramoD` (`tests/test_tools_generic_commands.py`), `test_dedicada_de_la_017_tramo_d` (`tests/test_command_table.py`), `test_subscribe_trigger_es_clase_a` (`tests/test_generar_tabla.py`); banco: `TestEsperaDeTrigger` (`tests/banco/test_banco_automatizacion_asistida.py`) |
| CAP-039 | alta | 033 | FR-099 | X | token atado a `variables`: `tests/test_security_regressions.py` (`TestRestrictedEntityVariables`), `tests/test_tools_scripts.py`, `tests/test_tools_automations.py`, inventario `tests/test_confirmation_args_inventory.py` y banco `tests/banco/test_banco_escrituras_automatizacion.py` (`test_el_token_ata_las_variables`, tramo 1); tramo 2: `not_supported` de `ha_reload_counters` (`tests/test_tools_counter.py`, `test_reload_no_soportada`) y canario de `counter.reload` (`tests/banco/test_banco_helpers_tiempo.py`, `TestCounter.test_recarga`); `amount` y `ha_set_counter_value` (`TestValorDeContadorValido`; banco `TestCounter.test_valores_que_ha_rechaza`); esquema sin `ctx` (`tests/test_tools_registration.py`, `TestEsperaSinCtxEnElEsquema`, `test_esquemas_de_la_1_1_2`; `tests/test_tools_wait_for_event.py`, `TestContextoDeLaEspera`; banco `TestEsperarEvento`); escenas (`tests/test_tools_scenes.py`, `TestEscenaDesdeElEstadoActual` y `TestDescripcionesDeEscenas`; banco `TestEscena.test_escena_desde_el_estado_*`); opciones (`tests/test_tools_config_entry_flows.py`, `TestGetConfigEntryOptions`; banco `TestOpcionesNoPublicadas`); banco sin `xfail` (`tests/test_banco_cobertura.py`, `test_ningun_xfail_en_el_banco_fuera_de_la_lista`) |
| CAP-040 | alta | 012, 017 | FR-036, FR-062 | D+X | `ha_validate_config`, `ha_test_condition` (012): `tests/test_tools_core_validation.py`; banco: `TestValidacion` (`tests/banco/test_banco_core_diagnostico.py`). Validación al guardar en `ha_create_or_update_automation` y `_script` (017): `tests/test_tools_validacion_al_guardar.py`; banco: `TestValidacionAlGuardar` (`tests/banco/test_banco_automatizacion_asistida.py`) |
| CAP-041 | alta | 012 | FR-037 | D | `ha_list_system_log`, `ha_get_error_log`, `ha_get_log_levels`, `ha_set_log_level`, `ha_clear_system_log`: `tests/test_tools_core_logs.py`, `tests/test_ha_rest_text_tail.py`; banco: `tests/banco/test_banco_core_logs.py` |
| CAP-042 | alta | 012 | FR-038 | D | `ha_list_diagnostics_handlers`, `ha_get_config_entry_diagnostics`, `ha_get_device_diagnostics`: `tests/test_tools_integration_diagnostics.py`; banco: `TestDiagnosticos` (`tests/banco/test_banco_core_diagnostico.py`, entrada de `local_calendar`); camino feliz del de dispositivo, prueba manual pendiente (ninguna integración sin hardware ni nube lo ofrece) |
| CAP-043 | alta | 029 | FR-040 | D | `ha_get_system_health`, `ha_get_system_state`, `ha_list_integration_setup_times`, `ha_list_integration_manifests`, `ha_get_integration_manifest` (familia `system_status`; entradas `dedicated` de `system_health/info`, `subscribe_system_state`, `integration/setup_info`, `manifest/list`, `manifest/get`): `tests/test_tools_system_status.py`, `tests/test_ha_ws_collect_subscription.py`, `TestDedicadasDeLa029` (`tests/test_tools_generic_commands.py`), `test_dedicadas_de_la_029` (`tests/test_command_table.py`); banco: `tests/banco/test_banco_estado_sistema.py` |
| CAP-044 | alta | 016 | FR-053 | D | `ha_list_discovered_integrations`, `ha_ignore_discovery`, `ha_list_config_flow_domains`, `ha_update_config_entry`; tabla `config_entries/flow/progress`, `…/ignore_flow`, `…/update` → `dedicated`: `tests/test_tools_integration_setup.py`; reautenticación con token en `ha_continue_config_entry_flow`: `tests/test_tools_config_entry_flows_reauth.py`; banco: `TestDescubiertos`, `TestDominiosConfigurables`, `TestPreferencias`, `TestReauth` (`tests/banco/test_banco_integraciones.py`) |
| CAP-045 | alta | 016 | FR-054 | D | `ha_list_config_subentries`, `ha_start_subentry_flow`, `ha_continue_subentry_flow`, `ha_abort_subentry_flow`, `ha_update_subentry`, `ha_delete_subentry`, `ha_start_reconfigure_flow`, `ha_continue_reconfigure_flow`; tabla `config_entries/subentries/*` → `dedicated`: `tests/test_tools_config_subentries.py`; banco: `TestSubentries`, `TestReconfigure` (`tests/banco/test_banco_integraciones.py`) |
| CAP-046 | alta | 017 | FR-058 | D | `ha_list_blueprints`, `ha_preview_blueprint_substitution`, `ha_save_blueprint`, `ha_delete_blueprint`, `ha_import_blueprint` (familia `blueprints`; 5 entradas `blueprint/*` `dedicated`): `tests/test_tools_blueprints.py`, `test_dedicadas_de_la_017*` (`tests/test_command_table.py`), `TestTemaBlueprints` (`tests/test_tools_guide.py`); banco: `tests/banco/test_banco_blueprints.py`, inventario `tests/banco/cobertura_017.py` |
| CAP-047 | alta | 012 | FR-039 | D | `ha_list_persistent_notifications`, `ha_dismiss_persistent_notification`: `tests/test_tools_persistent_notifications.py`; banco: `TestNotificaciones` (`tests/banco/test_banco_core_diagnostico.py`) |
| CAP-048 | media-alta | 016 | FR-055 | D | `ha_get_repair`, `ha_start_repair_fix`, `ha_continue_repair_fix`, `ha_abort_repair_fix`; tabla `repairs/get_issue_data` → `dedicated`: `tests/test_tools_repair_flows.py`; banco: `TestArreglarUnAviso`, `TestAbortarUnArreglo` (`tests/banco/test_banco_repairs.py`) |
| CAP-049 | media-alta | 029 | FR-041 | D | `ha_get_recorder_info`, `ha_validate_statistics`, `ha_get_statistics_metadata` (familia `recorder`; entradas `dedicated` de `recorder/info`, `recorder/entity_options/get`, `recorder/validate_statistics`, `recorder/get_statistics_metadata`): `tests/test_tools_recorder_status.py`, `TestDedicadasDeLa029Recorder` (`tests/test_tools_generic_commands.py`), `test_dedicadas_de_la_029` (`tests/test_command_table.py`); banco: `tests/banco/test_banco_recorder.py` |
| CAP-050 | media-alta | 020 | FR-069 | D | `ha_clear_statistics`, `ha_change_statistics_unit`, `ha_update_statistics_metadata`, `ha_adjust_statistics_sum`, `ha_import_statistics` (familia `recorder`, módulo `statistics_maintenance`; entradas `dedicated` de `recorder/clear_statistics`, `recorder/change_statistics_unit`, `recorder/update_statistics_metadata`, `recorder/adjust_sum_statistics`, `recorder/import_statistics`; `recorder/update_statistics_issues` `confirm` por la tabla): `tests/test_tools_statistics_maintenance.py`, `TestDedicadasDeLa020` y `TestAvisosDeEstadisticasPorLaTabla` (`tests/test_tools_generic_commands.py`), `TestCapitulosDeLa020` (`tests/test_command_table.py`), tema `recorder` (`tests/test_tools_guide.py`); banco: `tests/banco/test_banco_estadisticas.py` |
| CAP-051 | media-alta | 017 | FR-059 | D | `ha_list_device_triggers`, `ha_list_device_conditions`, `ha_list_device_actions` (familia `automation_assist`; 6 entradas `device_automation/*` `dedicated`): `tests/test_tools_device_automation.py`, `TestDedicadasDeLa017TramoC` (`tests/test_tools_generic_commands.py`), `test_dedicadas_de_la_017_tramo_c` (`tests/test_command_table.py`); banco: `TestDispositivo` (`tests/banco/test_banco_automatizacion_asistida.py`) |
| CAP-052 | media-alta | 017 | FR-060 | D | `ha_resolve_target`, `ha_explain_target`, `ha_list_triggers_for_target`, `ha_list_conditions_for_target`, `ha_list_actions_for_target` (familia `automation_assist`; 5 entradas `dedicated`): `tests/test_tools_targets.py`, `TestDedicadasDeLa017TramoC` (`tests/test_tools_generic_commands.py`), `test_dedicadas_de_la_017_tramo_c` (`tests/test_command_table.py`); banco: `TestTargets` (`tests/banco/test_banco_automatizacion_asistida.py`) |
| CAP-053 | media | 021 | FR-071 | D+T | `ha_get_core_config`, `ha_update_core_config` (familia `core_config`; `config/core/update` `dedicated`, `config/core/detect` `read` de mundo abierto por la tabla): `tests/test_tools_core_config.py`, `test_dedicadas_de_la_021` (`tests/test_command_table.py`), `TestDedicadasDeLa021TramoA` (`tests/test_tools_generic_commands.py`), `TestTemasDeLa021TramoA` (`tests/test_tools_guide.py`); banco: `tests/banco/test_banco_configuracion_sistema.py` |
| CAP-054 | media | 020 | FR-070 | D+T | `ha_get_energy_prefs`, `ha_update_energy_prefs` (familia `energy`; entradas `dedicated` de `energy/get_prefs` y `energy/save_prefs`); `read` por la tabla: `energy/validate`, `energy/info`, `energy/solar_forecast` y `energy/fossil_energy_consumption` (con ejemplo): `tests/test_tools_energy.py`, `TestEnergiaPorLaTabla` (`tests/test_tools_generic_commands.py`), `TestCapitulosDeLa020` (`tests/test_command_table.py`), `TestTemaEnergy` (`tests/test_tools_guide.py`); banco: `tests/banco/test_banco_energia.py` |
| CAP-055 | media | 021 | FR-072 | D | `ha_list_exposed_entities`, `ha_set_entity_exposure`, `ha_set_expose_new_entities` (familia `assistant_exposure`; los cuatro `homeassistant/expose_*` `dedicated`): `tests/test_tools_assistant_exposure.py`, `test_dedicadas_de_la_021` (`tests/test_command_table.py`), `TestDedicadasDeLa021TramoA` (`tests/test_tools_generic_commands.py`); banco: `tests/banco/test_banco_configuracion_sistema.py` |
| CAP-056 | media | 021 | FR-073 | D | `ha_list_users`, `ha_create_user`, `ha_update_user`, `ha_delete_user` (familia `users`; los cuatro `config/auth/*` `dedicated`): `tests/test_tools_users.py` (protecciones con control negativo), `test_dedicadas_de_la_021` y `test_credenciales_y_sesiones_siguen_deny` (`tests/test_command_table.py`), `TestDedicadasDeLa021TramoB` (`tests/test_tools_generic_commands.py`), `TestTemaDeUsuarios` (`tests/test_tools_guide.py`); banco: `tests/banco/test_banco_usuarios.py`. Desviación (research R-5 de la 021, duda D-1): las sesiones de otros usuarios no se pueden listar (`auth/refresh_tokens` solo da las de la conexión); queda `deny` revisado en `_DENY_TRAS_REVISION` |
| CAP-057 | media | 031 | FR-067 | D+T | `ha_list_backup_agents`, `ha_update_backup_config`, `ha_create_backup`, `ha_create_automatic_backup`, `ha_delete_backup`, `ha_restore_backup` (familia `backup_integration`; entradas `dedicated` de `backup/agents/info`, `backup/config/update`, `backup/generate`, `backup/generate_with_automatic_settings`, `backup/delete` y `backup/restore`) y `last_action_event` en `ha_list_backups`: `tests/test_tools_ha_backup_settings.py`, `tests/test_tools_ha_backup_actions.py`, `tests/test_tools_ha_backup_restore.py`, `tests/test_backup_retention_estimate.py`, `test_dedicadas_de_la_031` (`tests/test_command_table.py`); banco: `tests/banco/test_banco_backups_ajustes.py`, `tests/banco/test_banco_backups_acciones.py`, `tests/banco/test_banco_backups_restaurar.py`; **desviación de FR-067** (DV-1 de la 031): los ajustes del backup previo a una actualización (`hassio/update/config/*`) no tienen tool y quedan en `deny`, porque el proxy WebSocket del Supervisor 2026.11.0 rechaza todo `hassio/*` y `supervisor/*` de las apps; se cambian en la interfaz de HA. `ha_restore_backup` con éxito, en la VM de la 014 |
| CAP-058 | media | 029 | FR-042 | T | entrada `read` de `logbook/get_action_calls` con `redact_extra=("code",)` y ejemplo: `test_action_calls_tapa_el_code`, `test_action_calls_sin_code_en_el_log`, `test_action_calls_tiene_ejemplo` (`tests/test_tools_generic_commands.py`), tema `recorder` (`tests/test_tools_guide.py`); banco: `test_auditoria_de_llamadas` (`tests/banco/test_banco_recorder.py`) |
| CAP-059 | media | 024 | FR-085 | D+T | `ha_get_camera_snapshot` y `ha_get_image_entity` (familia `cameras`): `tests/test_tools_cameras.py`, `tests/test_ha_rest_get_image.py`, `TestCamerasRegistration` (`tests/test_tools_registration.py`), `TestTemasDeLa024` (`tests/test_tools_guide.py`); `camera/get_prefs` `read` y `camera/update_prefs` `confirm`: `TestClasificacionDeLa024` (`tests/test_command_table.py`), `TestMenoresDeCoreDeLa024` (`tests/test_tools_generic_commands.py`); banco: `tests/banco/test_banco_camaras.py`, `TestPreferenciasDeCamara` (`tests/banco/test_banco_menores_datos.py`), inventario `tests/banco/cobertura_024.py` |
| CAP-060 | media-alta | 023 | FR-083 | D | `ha_list_conversation_agents`, `ha_list_conversation_sentences`, `ha_debug_conversation`, `ha_process_conversation` (familia `conversation`; entradas `dedicated` de `conversation/agent/list`, `conversation/agent/homeassistant/language_scores`, `conversation/sentences/list`, `conversation/agent/homeassistant/debug`, `conversation/process`): `tests/test_tools_conversation.py`, `TestConversacion023` (`tests/test_tools_registration.py`), `TestDedicadasDeLa023` (`tests/test_tools_generic_commands.py`), `test_dedicadas_de_la_023` (`tests/test_command_table.py`), `TestTemaConversacion` (`tests/test_tools_guide.py`); banco con un disparador de frase: `tests/banco/test_banco_conversacion.py` |
| CAP-061 | baja | 023 | FR-084 | T | entradas `read`/`confirm` de `assist_pipeline/*` (`pipeline_debug/get` con `redact_extra=("url",)`, `pipeline/create` con ejemplo; cualquier `/api/tts_proxy/<token>` tapado en las genéricas): `TestAssistPorLaTabla` (`tests/test_tools_generic_commands.py`), `TestConversacionDeLa023.test_revisadas` (`tests/test_command_table.py`); banco: `test_lecturas`, `test_ciclo_de_un_pipeline` (`tests/banco/test_banco_assist.py`) |
| CAP-062 | baja | 023 | FR-084 | T | entradas de `tts/*`, `stt/engine/list`, `wake_word/info`, `llm/api/list` y `ai_task/preferences/*` (motivo de `set` con la evaluación automática): `TestAssistPorLaTabla` (`tests/test_tools_generic_commands.py`); banco: `test_lecturas`, `test_preferencias_de_ai_task` (`tests/banco/test_banco_assist.py`) |
| CAP-063 | baja | 023 | FR-084 | T | entradas de `assist_satellite/get_configuration` (`read`) y `set_wake_words` (`confirm`): `test_satelite` (`tests/test_tools_generic_commands.py`), unitario: el banco no tiene satélites |
| CAP-064 | media-alta | 015 | FR-050 | D | `ha_list_updates`, `ha_get_update_release_notes`, `ha_install_update` (encaminamiento de las entidades `hassio` a las `sv_*`, rechazo de Hermes por el slug exacto de `/addons/self/info`) con Core simulado: `tests/test_tools_update_entities.py`; `hint` de `ha_call_service`: `TestHintUpdateInstall` (`tests/test_call_service_security.py`); banco con una entidad `update` de plantilla: `tests/banco/test_banco_actualizaciones.py`; tabla: `update/release_notes` en `TestActualizacionesDeLa015` (`tests/test_command_table.py`) y `tests/test_tools_actualizaciones_tabla.py` |
| CAP-065 | baja | 024 | FR-087 | T | `calendar/event/update|delete` y `todo/item/move` `confirm` de mundo abierto: `TestClasificacionDeLa024` (`tests/test_command_table.py`), `TestMenoresDeCoreDeLa024` (`tests/test_tools_generic_commands.py`); banco: `TestCalendarioYTareas` (`tests/banco/test_banco_menores_datos.py`) |
| CAP-066 | baja | 024 | FR-087 | T | `tag/list` `read` y `tag/create|update|delete` `confirm`: `TestClasificacionDeLa024` (`tests/test_command_table.py`); banco: `tests/banco/test_banco_genericas.py` (011) |
| CAP-067 | baja | 024 | FR-087 | T | `media_source/browse_media|search_media` `read` con la `thumbnail` tapada, `local_source/remove` `confirm`, `resolve_media` `deny`: `TestClasificacionDeLa024` (`tests/test_command_table.py`), `TestMenoresDeCoreDeLa024` (`tests/test_tools_generic_commands.py`); banco: `TestMedios` (`tests/banco/test_banco_menores_datos.py`) |
| CAP-068 | media | 029 | FR-043 | T | entradas `read` de `network`, `network/url` y `http/config`: `test_red_y_http_sin_urls_ni_ips_en_el_log` (`tests/test_tools_generic_commands.py`), tema `system_status` (`tests/test_tools_guide.py`); banco: `test_red_y_http_por_la_generica` (`tests/banco/test_banco_recorder.py`) |
| CAP-069 | baja | 021 | FR-074 | D | `ha_update_network_config`, `ha_update_http_config`, `ha_promote_http_config` (familia `core_network`; `network/configure`, `http/config/configure` y `http/config/promote` `dedicated`): `tests/test_tools_core_network.py`, `test_dedicadas_de_la_021` (`tests/test_command_table.py`), `TestDedicadasDeLa021TramoC` (`tests/test_tools_generic_commands.py`), `TestTemaDeRedYHttp` (`tests/test_tools_guide.py`); banco: `tests/banco/test_banco_red_http.py` (la red con efecto; el HTTP, vista previa y rechazos reales); confirmación del HTTP en la VM de la 014 |
| CAP-070 | baja | 024 | FR-087 | T | `config/area_registry/reorder`, `config/floor_registry/reorder` y `config/entity_registry/settings/update` `confirm`; `get_automatic_entity_ids`, `settings/get`, `list_linked_devices` y `list_composite_splits` `read`: `TestClasificacionDeLa024` (`tests/test_command_table.py`), `TestMenoresDeCoreDeLa024Tramo2` (`tests/test_tools_generic_commands.py`); banco: `TestRegistrosYCredenciales` (`tests/banco/test_banco_menores_ui.py`) |
| CAP-071 | baja | 024 | FR-086 | D+T | `ha_reset_lovelace_dashboard_config` (familia `dashboard_reset`; `lovelace/config/delete` `dedicated`): `tests/test_tools_lovelace_reset.py`, `TestRestablecerDashboardRegistration` (`tests/test_tools_registration.py`), `TestTemasDeLa024Tramo2` (`tests/test_tools_guide.py`); `trace/contexts`, `frontend/get_themes`, `webhook/list` (`webhook_id` tapado), `vacuum/get_segments` y `radio_frequency/list` `read`: `TestClasificacionDeLa024` (`tests/test_command_table.py`), `TestMenoresDeCoreDeLa024Tramo2` (`tests/test_tools_generic_commands.py`); banco: `TestRestablecerDashboard` y `TestLecturasDeLaUI` (`tests/banco/test_banco_menores_ui.py`), inventario `tests/banco/cobertura_024.py` |
| CAP-072 | baja | 024 | FR-087 | T | `image/list` `read`, `image/update|delete` `confirm`, `image/create` `deny`: `TestClasificacionDeLa024` (`tests/test_command_table.py`), `TestMenoresDeCoreDeLa024` (`tests/test_tools_generic_commands.py`); banco: `TestImagenesSubidas` (`tests/banco/test_banco_menores_datos.py`) |
| CAP-073 | baja | 024 | FR-088 | T | `application_credentials/list|config|config_entry` `read` (`client_secret` y el id tapados; crear, cambiar y borrar, `deny`): `TestClasificacionDeLa024` (`tests/test_command_table.py`), `test_credenciales_de_aplicacion_sin_secretos` (`tests/test_tools_generic_commands.py`); banco: `test_credenciales_de_aplicacion` (`tests/banco/test_banco_menores_ui.py`) |
| CAP-074 | baja | 021 | FR-075 | T | `analytics`, `labs/list` (`read`), `analytics/preferences` (`confirm`, de mundo abierto) y `labs/update` (`confirm`) por las genéricas: `test_cap_074_por_la_tabla` (`tests/test_command_table.py`), `TestDedicadasDeLa021TramoC` (`tests/test_tools_generic_commands.py`), `TestTemaDeRedYHttp.test_analytics_y_labs_en_core_config` (`tests/test_tools_guide.py`); banco: `tests/banco/test_banco_analytics_labs.py` |
| CAP-075 | baja | 026 | FR-091 | D | Marketplace escritura (unitario; en vivo pendiente) |
| CAP-080 | alta | 015 | FR-049 | D | `sv_list_available_updates`, `sv_check_for_updates`, `sv_update_core`, `sv_update_os`, `sv_update_supervisor` con Supervisor simulado: `tests/test_tools_system_updates.py`; tabla: `TestActualizacionesDeLa015` (`tests/test_command_table.py`) y `tests/test_tools_actualizaciones_tabla.py`; en vivo, pendiente (VM de la 014). Hallazgos sobre el inventario (research R-13 de la 015): `POST /os/update` no reinicia (instala en la ranura inactiva y pide reiniciar el host); `POST /refresh_updates` no es un alias exacto de `/reload_updates` (recarga además la tienda) |
| CAP-081 | alta | 013 | FR-044 | D | `sv_get_core_logs`, `sv_get_supervisor_logs`, `sv_get_plugin_logs`, `sv_get_host_logs`, `sv_list_host_log_identifiers`, `sv_list_boots` y `boot`/`latest` en `sv_get_addon_logs`, con Supervisor simulado: `tests/test_tools_system_logs.py`, `TestLogsDeAddonPorArranque` (`tests/test_tools_supervisor.py`); tabla: `TestLogsDeLa013` (`tests/test_command_table.py`); registro: `TestLogsDelSistema013` (`tests/test_tools_registration.py`); guía: `TestTemaSystemDiagnostics` (`tests/test_tools_guide.py`); en vivo, pendiente (VM de la 014, después instalación real) |
| CAP-082 | alta | 030 | FR-051 | D | `sv_list_store_repositories`, `sv_add_store_repository`, `sv_remove_store_repository`, `sv_repair_store_repository`, `sv_reload_store`, `sv_get_addon_changelog`, `sv_get_addon_documentation`, `sv_get_addon_availability` y las vistas previas de `sv_install_addon` y `sv_update_addon`, con Supervisor simulado: `tests/test_tools_store_repositories.py`, `tests/test_store_comun.py`, `tests/test_tools_store_apps.py`, `tests/test_tools_addons_tienda.py`, `tests/test_tools_addons_convergencia_030.py` (versión atada al token, app desligada, tienda ilegible); tabla: `TestTiendaDeLa030` (`tests/test_command_table.py`, `tests/test_tools_generic_commands.py`); registro: `TestTiendaDeApps030` (`tests/test_tools_registration.py`); guía: `TestTemaAppStore` (`tests/test_tools_guide.py`); **desviación de FR-051**: no se instala ni actualiza una versión concreta, porque el Supervisor 2026.11.0 ignora `{version}` (research R-2 de la 030); las rutas con `{version}` apuntan a la tool sin versión; en vivo, pendiente (VM de la 014, después instalación real) |
| CAP-083 | alta | 019 | FR-066 | D | `sv_list_mounts`, `sv_create_mount`, `sv_update_mount`, `sv_delete_mount`, `sv_reload_mount`, `sv_set_default_backup_mount`, `sv_get_backup_settings`, `sv_set_backup_settings`, `sv_reload_backups` y `location` en `sv_create_backup_full`/`sv_create_backup_partial`, con Supervisor simulado y centinelas CIFS: `tests/test_tools_mounts.py`, `tests/test_tools_backup_settings.py`, `TestUbicacionDelBackup` (`tests/test_tools_supervisor.py`); tabla: `TestMontajesDeLa019` (`tests/test_command_table.py`); registro: `TestMontajes019` (`tests/test_tools_registration.py`); guía: `TestTemaMounts` y `TestGuiaCompleta019` (`tests/test_tools_guide.py`); en vivo, pendiente (VM de la 014) |
| CAP-084 | media | 022 | FR-076 | D+T | `sv_start_core`, `sv_rebuild_core`, `sv_set_core_options`, `sv_reload_supervisor`, `sv_restart_supervisor`, `sv_repair_supervisor`, `sv_set_supervisor_options` con Supervisor simulado: `tests/test_tools_system_control.py`; tabla: `GET /core/stats` y `GET /supervisor/stats` (`read`) y `POST /host/reload` (`confirm`), `TestEntradasDeLa022` (`tests/test_command_table.py`) y `tests/test_tools_control_tabla.py`; registro: `TestControl022` (`tests/test_tools_registration.py`); guía: `TestTemaSystemControl` (`tests/test_tools_guide.py`); en vivo, pendiente (VM de la 014) |
| CAP-085 | media-alta | 013 | FR-045 | D | `sv_list_host_services`, `sv_get_disk_usage`, `sv_get_os_info`, `sv_get_swap`, `sv_list_datadisk_candidates`, con Supervisor simulado: `tests/test_tools_host_system.py`; `GET /host/disks` por la tabla (`read`, justificada en `_POR_LA_TABLA`): `tests/test_tools_diagnostico_tabla.py`; tabla: `TestDiscoHostYOsDeLa013` (`tests/test_command_table.py`); registro: `TestHostSystem013` (`tests/test_tools_registration.py`); guía: `TestTemaSystemDiagnostics` (`tests/test_tools_guide.py`); en vivo, pendiente (VM de la 014, después instalación real) |
| CAP-086 | media | 032 | FR-081 | D | `sv_shutdown_host`, `sv_set_hostname`, `sv_set_swap` y `sv_set_boot_slot` (familia `host_control`) con Supervisor simulado: `tests/test_tools_host_control.py`; tabla: `TestHostControlDeLa032` (`tests/test_command_table.py`); registro: `TestHostControl032` (`tests/test_tools_registration.py`); guía: `TestTemaHostControl` (`tests/test_tools_guide.py`); en vivo, pendiente (VM de la 014) |
| CAP-087 | media | 013, 022 | FR-046, FR-077 | D+T | lectura (013): `GET /jobs/info` y `GET /resolution/issue/{issue}/suggestions` por la tabla (`read`, justificadas en `_POR_LA_TABLA`), con Supervisor simulado: `tests/test_tools_diagnostico_tabla.py`, `TestDiscoHostYOsDeLa013` (`tests/test_command_table.py`); escritura (022): `sv_apply_resolution_suggestion` con Supervisor simulado, `tests/test_tools_resolution_fixes.py` y la guarda `TestSoloResolutionFixesAplica` (`tests/test_tools_resolution.py`); `POST /resolution/check/{check}/run`, `/options` y `POST /resolution/healthcheck` por la tabla (`confirm`), `TestEntradasDeLa022Tramo2` (`tests/test_command_table.py`) y `TestSugerenciasYChequeos` (`tests/test_tools_control_tabla.py`); en vivo, pendiente (VM de la 014, después instalación real) |
| CAP-088 | media | 013 | FR-047 | T | `GET /hardware/info`, `/hardware/audio`, `/security/info`, `/docker/info`, `/time/info` (`read`) por `sv_read_api`, con Supervisor simulado: `tests/test_tools_diagnostico_tabla.py`; **desviación de FR-047**: `POST /security/integrity` sigue `deny` y no `confirm`, porque el Supervisor 2026.11.0 eliminó la comprobación y responde 410 (research R-6 de la 013); test: `test_integridad_no_llega_al_supervisor` y `TestDiscoHostYOsDeLa013.test_integridad_sigue_deny`; en vivo, pendiente (VM de la 014, después instalación real) |
| CAP-089 | media | 013 | FR-048 | T | `GET /network/info`, `/network/interface/{interface}/info`, `/network/interface/{interface}/accesspoints` (`read`) por `sv_read_api`, con Supervisor simulado y el log sin IPs, MAC ni SSID: `tests/test_tools_diagnostico_tabla.py`; en vivo, pendiente (VM de la 014, después instalación real) |
| CAP-090 | baja | 032 | FR-082 | D | `sv_reload_network` (sin token, D-032-1), `sv_update_network_interface` y `sv_create_vlan` (familia `host_network`) con Supervisor simulado, guarda de la interfaz principal, la única conectada y la principal desconocida, y PSK centinela: `tests/test_tools_host_network.py`; tabla: `TestHostNetworkDeLa032` (`tests/test_command_table.py`); registro: `TestHostNetwork032` (`tests/test_tools_registration.py`); guía: `TestTemaHostNetwork` (`tests/test_tools_guide.py`); en vivo, pendiente (VM de la 014) |
| CAP-091 | baja | 022 | FR-078 | T | rutas de plugins de la tabla (sin cambios) recorridas por `sv_read_api`/`sv_call_api` con Supervisor simulado: `TestPluginsDockerPlacas` (`tests/test_tools_control_tabla.py`); en vivo, pendiente (VM de la 014) |
| CAP-092 | baja | 022 | FR-079 | T | registros y opciones de Docker por la tabla (sin cambios), con centinela en la contraseña (vista previa, log y error del Supervisor): `TestRegistroDocker` y `TestPluginsDockerPlacas` (`tests/test_tools_control_tabla.py`); en vivo, pendiente (VM de la 014) |
| CAP-093 | media | 030 | FR-052 | D+X | `sv_rebuild_addon` y la validación de opciones en la vista previa de `sv_set_addon_options`, con Supervisor simulado: `TestReconstruir` (`tests/test_tools_store_apps.py`), `TestValidarOpciones` (`tests/test_tools_addons_tienda.py`), `TestFugaPorElMensaje` y `TestErrorAlGuardar` (`tests/test_tools_addons_convergencia_030.py`); tabla: `TestTiendaDeLa030` (`tests/test_command_table.py`); en vivo, pendiente (VM de la 014, después instalación real) |
| CAP-094 | baja | 022 | FR-080 | T | placas (`/os/boards/*`) y `POST /time/options` por la tabla (sin cambios), con Supervisor simulado: `TestPluginsDockerPlacas` (`tests/test_tools_control_tabla.py`); en vivo, pendiente (VM de la 014) |
| CAP-100 | media | 025 | FR-089, FR-090 | T | Z-Wave JS por la tabla: 55 entradas `zwave_js/*` (18 `read`, 13 `confirm`, 24 `deny`), tema `zwave`; unitario, sin hardware en el banco (`tests/test_command_table_clase_c.py`: `test_clasificacion`, `test_recuento_*`, `test_redact_extra_de_las_claves`; `tests/test_tools_generic_commands_clase_c.py`: `TestZwave`; `tests/test_tools_guide.py`: `TestTemasDeIntegraciones`; `tests/test_generar_tabla.py`: `test_desde_cero_clase_c_igual_que_la_tabla`) |
| CAP-101 | media | 025 | FR-089, FR-090 | T | ZHA por la tabla: 28 entradas `zha/*` (13/10/5), claves de red tapadas, tema `zigbee`; unitario, sin hardware en el banco (`tests/test_command_table_clase_c.py`: `test_clasificacion`, `test_recuento_*`, `test_redact_extra_de_las_claves`; `tests/test_tools_generic_commands_clase_c.py`: `TestZha`; `tests/test_tools_guide.py`: `TestTemasDeIntegraciones`; `tests/test_generar_tabla.py`: `test_desde_cero_clase_c_igual_que_la_tabla`) |
| CAP-102 | baja | 025 | FR-089, FR-090 | T | Matter por la tabla: 11 entradas `matter/*` (3/1/7), tema `matter_thread`; unitario, sin hardware en el banco (`tests/test_command_table_clase_c.py`: `test_clasificacion`, `test_recuento_*`, `test_redact_extra_de_las_claves`; `tests/test_tools_generic_commands_clase_c.py`: `TestMatterThread`; `tests/test_tools_guide.py`: `TestTemasDeIntegraciones`; `tests/test_generar_tabla.py`: `test_desde_cero_clase_c_igual_que_la_tabla`) |
| CAP-103 | baja | 025 | FR-089, FR-090 | T | Thread y OTBR por la tabla: 11 entradas (2/2/7), `thread/get_dataset_tlv` `deny` y dataset de `otbr/info` tapado; unitario, sin hardware en el banco (`tests/test_command_table_clase_c.py`: `test_clasificacion`, `test_recuento_*`, `test_redact_extra_de_las_claves`; `tests/test_tools_generic_commands_clase_c.py`: `TestMatterThread`; `tests/test_tools_guide.py`: `TestTemasDeIntegraciones`; `tests/test_generar_tabla.py`: `test_desde_cero_clase_c_igual_que_la_tabla`) |
| CAP-104 | media | 025 | FR-089, FR-090 | T | MQTT por la tabla: `mqtt/device/debug_info` `read` con `code` y `transmitted` tapados, `mqtt/subscribe` `deny`, tema `other_integrations`; unitario, sin broker en el banco (`tests/test_command_table_clase_c.py`: `test_clasificacion`, `test_recuento_*`, `test_redact_extra_de_las_claves`; `tests/test_tools_generic_commands_clase_c.py`: `TestResto`; `tests/test_tools_guide.py`: `TestTemasDeIntegraciones`; `tests/test_generar_tabla.py`: `test_desde_cero_clase_c_igual_que_la_tabla`) |
| CAP-105 | baja | 025 | FR-089, FR-090 | T | USB y Bluetooth por la tabla: 7 entradas (4/0/3); banco: `tests/banco/test_banco_integraciones_c.py` (`usb/list_serial_ports` y `usb/list_serial_integrations` contra HA real, rechazos y `unknown_command`); Bluetooth, unitario (`tests/test_command_table_clase_c.py`: `test_clasificacion`, `test_recuento_*`, `test_redact_extra_de_las_claves`; `tests/test_tools_generic_commands_clase_c.py`: `TestResto`; `tests/test_tools_guide.py`: `TestTemasDeIntegraciones`; `tests/test_generar_tabla.py`: `test_desde_cero_clase_c_igual_que_la_tabla`) |
| CAP-106 | baja | 025 | FR-089, FR-090 | T | el resto por la tabla: 78 entradas (32/31/15), secretos `deny` o tapados (contraseña del hub Insteon); unitario, sin hardware en el banco (`tests/test_command_table_clase_c.py`: `test_clasificacion`, `test_recuento_*`, `test_redact_extra_de_las_claves`; `tests/test_tools_generic_commands_clase_c.py`: `TestResto`; `tests/test_tools_guide.py`: `TestTemasDeIntegraciones`; `tests/test_generar_tabla.py`: `test_desde_cero_clase_c_igual_que_la_tabla`) |

96 CAP, todas con sub-feature y FR. Ninguna CAP queda excluida: lo excluido es
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
