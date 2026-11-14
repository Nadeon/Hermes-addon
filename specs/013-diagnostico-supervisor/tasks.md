---

description: "Tareas de la sub-feature 013 — diagnóstico del Supervisor (Hermes 1.2.0)"
---

# Tareas: diagnóstico del Supervisor (013)

**Entrada**: `specs/013-diagnostico-supervisor/` (spec.md, plan.md,
research.md, data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `DummyMCP`, un
`MockHAClient` (el de `tests/test_tools_supervisor.py`, ampliado para
registrar `params` y `timeout_seconds`) como **Supervisor simulado** con
respuestas de la forma del Supervisor 2026.11.0, `structlog.testing.capture_logs`.
Datos ficticios (`192.0.2.x`, `02:00:00:00:00:01`, `red-ficticia`, `<slug>`,
ids de arranque inventados, centinelas de texto). Nada de la instalación real.
**Nada de escritura**: si una tarea parece pedir un `POST`, es un error.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`.
Línea base al especificar (2026-11-14, rama de la 011 con su tramo 1, punta
`ab8c888`): 2021 passed, 16 skipped, 6 failed (los 6 conocidos de Windows).
Cada tramo anota su propia línea base al empezar y termina con exactamente
esos 6 fallos en local; la referencia es el CI de Linux.

**Requisito previo (S-01)**: la 009 y la 011 completa integradas en la rama
(`sv_read_api`, registro por familias, `tool_families_disabled`, tema
`generic_commands`, `tests/fixtures/esquemas_1_1_2.json`). Si falta algo al
empezar un tramo, el agente se detiene y lo anota.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 logs del sistema, US2 disco, host y OS, US3 el resto
por la tabla, US4 nada de lo actual cambia.

## Tramos de implementación

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado.

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **1** — logs del sistema (CAP-081) | **T001–T015** | Familia `system_diagnostics` con `system_logs`; `sv_get_core_logs`, `sv_get_supervisor_logs`, `sv_get_plugin_logs`, `sv_get_host_logs`, `sv_list_host_log_identifiers`, `sv_list_boots`; `boot`/`latest` en `sv_get_addon_logs`; 23 entradas a `dedicated`; tema de guía (logs); CHANGELOG y DOCS (parte) |
| **2** — disco, host y OS (CAP-085) y la tabla (CAP-087 lectura, 088, 089) | **T016–T028** | `sv_list_host_services`, `sv_get_disk_usage`, `sv_get_os_info`, `sv_get_swap`, `sv_list_datadisk_candidates`; 5 `dedicated` + 3 `read`; tests de las genéricas; guía completa; documentación y matriz de la 008; ninguna entrada «pendiente (spec 013)» |

El tramo 2 necesita el tramo 1 integrado.

---

## Tramo 1 — logs del sistema (CAP-081)

### Preparación

- [x] T001 Línea base: comprobar el requisito previo (S-01), ejecutar la suite y anotar passed/skipped/failed y la punta; comprobar que `grep -c "spec 013" hermes/src/hermes/command_table.py` da 31
- [x] T002 [P] [US4] Tests en `tests/test_tool_families.py`: `system_diagnostics` existe, es `desde="1.2.0"`, desactivable, con los módulos `("system_logs",)`, y `familia_de_modulo("system_logs") == "system_diagnostics"`; en `tests/test_config_validation.py`, `tool_families_disabled: [system_diagnostics]` es válido. Después, la familia en `hermes/src/hermes/tool_families.py` con un comentario del porqué (research R-1) (FR-021)

### Tests de las tools de logs (escritos antes, en rojo)

- [x] T003 [P] [US1] Fixture `tests/fixtures/supervisor_diagnostico.py` (respuestas de la forma del Supervisor 2026.11.0, datos ficticios: logs de texto con líneas numeradas, `{"boots": {"0": …, "-1": …}}`, `{"identifiers": [...]}`) y tests en `tests/test_tools_system_logs.py` para `sv_get_core_logs`, `sv_get_supervisor_logs` y `sv_get_plugin_logs`: ruta según data-model para cada combinación (sin nada, `latest`, `boot=-1`, `boot="-1"`, `boot=0`, `boot=<32 hex en mayúsculas>` → minúsculas); `params={"lines": "N"}` siempre y `lines` acotado (0 → 1, 5000 → 1000); `boot` inválido (`"abc"`, `1.5`, `1000`, `-1000`, 31 y 33 hex, `"../x"`) → `invalid_argument` con `field: "boot"` y **ninguna** llamada; `boot`+`latest` → `invalid_argument` sin llamada; `plugin` `cli`, `observer`, `DNS` y `""` → `invalid_argument` con la lista sin llamada; centinelas (`password: centinela-1`, un JWT, `token=centinela-2`) en el log → no aparecen y `redacted: true`; error del Supervisor con un centinela → `error` redactado; `HAConnectionError` → `error` (FR-001…FR-003, FR-008, FR-009, FR-016, FR-024)
- [x] T004 [P] [US1] Tests en `tests/test_tools_system_logs.py` para el host: `sv_get_host_logs` con las cuatro rutas (`identifier` y `boot` combinados); `identifier` inválido (`".."`, `".hidden"`, `"a/b"`, `"a b"`, `"a%2e"`, 65 caracteres, `""`) → `invalid_argument` sin llamada; `identifier` válidos (`kernel`, `systemd-journald`, `NetworkManager`, `addon_<slug>`, `hassio_supervisor`) → llamada; `identifier="addon_<slug de Hermes>"` y `"app_<slug de Hermes>"` → también `redact_network` (con la opción activa una IP ficticia sale seudonimizada) y con otro identificador no; `sv_list_host_log_identifiers` ordena, `search` filtra sin distinguir mayúsculas, sobre `{count, items, truncated}`; `sv_list_boots` → `items` `{offset, boot_id}` de 0 hacia atrás; un log mayor que `response_max_bytes` → últimas líneas con `truncated`, `lines_returned` y la pista (FR-004…FR-006, FR-008, FR-009)
- [x] T005 [P] [US1] [US4] Tests en `tests/test_tools_supervisor.py` para `sv_get_addon_logs`: sin `boot` ni `latest`, la petición (`/addons/{slug}/logs`, `params`) y la respuesta son **idénticas** a las de hoy (comparar con una respuesta capturada antes del cambio); `latest=True` → `/addons/{slug}/logs/latest`; `boot=-1` → `/addons/{slug}/logs/boots/-1`; respuesta con `route` y `boot`/`latest` solo entonces; `boot`+`latest` y `boot` inválido → `invalid_argument` sin llamada; Hermes con `boot` → `redact_network` sigue aplicándose (FR-007, FR-009, FR-022)
- [x] T006 [P] [US1] Tests del log de Hermes en `tests/test_tools_system_logs.py` con `capture_logs`: un evento `system_diagnostics_read` por llamada con `tool`, `route` (plantilla), `lines`, `bytes`, `redacted` y `outcome`; nunca el contenido, el centinela, el id de arranque, el `identifier` ni el `search`; con un `boot`/`identifier` inválido, `outcome="invalid_argument"` y sin el valor (FR-010)

### Implementación

- [x] T007 [US1] `hermes/src/hermes/tools/system_logs.py`: `register(mcp, ha_client, *, response_max_bytes)`, validadores (`boot`, `identifier`, `latest`+`boot`, `plugin`), ruta por data-model, `sv_request_text` con `params`, `redact_secrets` y `redact_network` para Hermes (`_es_hermes` de `tools/addons.py`), `_ultimas_lineas_que_caben` de `tools/addons.py`, sobre común y `redact_structure` en las listas, errores (research R-8), evento de log; seis tools con docstrings en inglés según contracts/tools.md (también el aviso del Supervisor sin journal). T003, T004 y T006 en verde (FR-001…FR-006, FR-008…FR-010, FR-016, FR-024)
- [x] T008 [US1] [US4] `hermes/src/hermes/tools/addons.py`: `boot` y `latest` opcionales en `sv_get_addon_logs` con los validadores de T007 (si importar de `system_logs` crea un ciclo, moverlos a `tools/_logs.py`), camino por defecto sin tocar, docstring ampliado. T005 en verde (FR-007, FR-009)
- [x] T009 [US1] Tests en `tests/test_command_table.py`: las 23 rutas de logs de data-model son `dedicated` con su tool y familia (`sv_get_addon_logs` → `supervisor`; el resto → `system_diagnostics`) y su CAP-081; `test_clase_a_de_via_dedicada_pendiente_de_su_spec` admite `dedicated` (además de `deny` «pendiente de tool dedicada (spec NNN)»); las variantes `follow` y `/homeassistant/logs*` siguen `deny` (FR-017)
- [x] T010 [US1] `hermes/src/hermes/command_table.py`: las 23 entradas a `dedicated` a mano, una línea cada una, con «cubierto por `<tool>`», familia y `cap="CAP-081"`; ejecutar `scripts/inventario/generar_tabla.py` y comprobar que la tabla no cambia (`git diff --exit-code`); anotarlo en el commit. T009 en verde y `TestDedicadas` en verde (necesita el registro de T011, que va antes) (FR-017)
- [x] T011 [US1] [US4] Registro en `hermes/src/hermes/tools/__init__.py` dentro de la comprobación de la familia `system_diagnostics` (patrón de la 011), con `response_max_bytes`. Tests en `tests/test_tools_registration.py`: las seis tools registradas por defecto con `readOnlyHint`, idempotentes, sin mundo abierto y sin `confirmation_token`; ninguna con la familia desactivada (y `sv_get_addon_logs` sigue con `boot`/`latest`); SC-005 de la 011 sigue en verde (con las familias 1.2.0 desactivadas, la lista es la de la 1.1.2); actualizar los recuentos y la comprobación «las únicas tools de más» de la 011 para que admita las de familias 1.2.0; en la instantánea `esquemas_1_1_2.json`, diferencia permitida y comentada para `sv_get_addon_logs` (`boot`, `latest` opcionales, fuera de `required`) (FR-021, FR-022)
- [x] T012 [US1] Guía: tests en `tests/test_tools_guide.py` (tema `system_diagnostics` con las seis tools, `boot`/`latest` y cómo usar `sv_list_boots`; alias `system_logs`, `supervisor_logs`, `host_logs`, `boots`; el índice lo nombra; el tema `supervisor` menciona `boot` y `latest`; los temas de la 1.1.2 que no se tocan devuelven lo mismo); después, `hermes/src/hermes/tools/guide.py` (tema en español, como los demás, y lista de temas del docstring de `hermes_guide`) (FR-023)
- [x] T013 Control negativo del tramo 1, anotando recuentos: (a) aceptar cualquier texto en `boot` → caen los de `boot` inválido; (b) no rechazar `boot`+`latest` → cae; (c) no aplicar `redact_network` al identificador de Hermes en el host → cae; (d) recortar por el principio en vez de por el final → cae el de recorte; (e) registrar `boot` o el contenido en el evento → caen los del log; (f) dejar una ruta de logs como `deny` → cae el de dedicadas; (g) cambiar el camino por defecto de `sv_get_addon_logs` (p. ej. añadir `route` siempre) → cae el de identidad con la 1.1.2. Restaurar y comprobar verde
- [x] T014 Documentación del tramo 1: sección «Diagnóstico del Supervisor» en `## [1.2.0] — <fecha de publicación>` de `hermes/CHANGELOG.md` (las seis tools, `boot`/`latest`, familia nueva); `hermes/DOCS.md`, familia `system_diagnostics` en la lista de `tool_families_disabled`
- [x] T015 Cierre del tramo 1: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII: nada de hostnames, IPs reales, slugs, rutas `C:\`), commit con los recuentos de T013 y el resultado de la regeneración de T010


### Notas del tramo 1 (2026-11-14)

- **Línea base** (T001), tras traer `feat/cobertura-total` (009, 010, 011
  completa y 028) con `git merge --no-ff`: 2320 passed, 65 skipped, 6 failed
  (los 6 de Windows); `grep -c "spec 013"` en la tabla = 31. Al cerrar el
  tramo quedan 8 (las 5 de CAP-085 y las 3 que van a `read`, tramo 2).
- **Desviación — la familia**: en este tramo `system_diagnostics` solo tiene
  el módulo `system_logs` y la descripción habla solo de logs; el tramo 2
  añade `host_system` y completa la descripción de data-model
  (`test_cada_familia_nombra_modulos_que_existen` no admite un módulo que aún
  no existe).
- **Desviación — validación en `tools/_logs.py`**: los validadores y la
  construcción de las rutas van en un módulo aparte para evitar el ciclo
  `addons` ↔ `system_logs` (lo preveía T008). Además de las reglas de
  data-model, cada segmento de ruta pasa por `validate_path_segment` (segunda
  capa común de Hermes): lo exige
  `test_every_module_that_builds_a_path_has_a_validator` y para, por ejemplo,
  un `identifier` `a..b`, que cumple la forma pero lleva `..`.
- **Desviación — campos de la respuesta**: las respuestas de log llevan
  también `secrets_redacted` y `network_redacted`, como `sv_get_addon_logs`
  desde la 009 (FR-005 de la 009); data-model no los nombraba.
- **Desviación — el evento con error y con argumento inválido**: con error
  lleva `status` (el HTTP) en vez de `bytes`; con argumento inválido, `field`
  y ninguna ruta.
- **README, README.es y DOCS** (adelantado del tramo 2 a la fuerza): el
  recuento de tools (220 → 226), la fila de la familia en DOCS.md y su nombre
  en los README los exigen `TestToolCountInDocs` y
  `TestFamiliasEnLaDocumentacion` en cuanto se registran las tools. La matriz
  de la 008 tiene ya la fila de CAP-081; el resto de filas, en el tramo 2.
- **CHANGELOG**: sección en el bloque «Diagnóstico» de `## [1.2.0]`; se
  actualizan los recuentos de la tabla del bloque de la 011 (Supervisor:
  `dedicated` 29 → 52, `deny` 174 → 151).
- **Guía**: el tema `system_diagnostics` entra también en la lista de temas
  de las instrucciones del servidor, solo con la familia activa (como
  `generic_commands`). La comprobación «los temas que no se tocan no cambian»
  usa huellas sha256 de los temas tal como estaban antes de la 013.
- **Matriz de la 014**: no existe todavía en la hoja de ruta; las seis tools
  son de solo lectura y no entran en la lista de «modifican».
- **Regeneración de la tabla** (T010): `generar_tabla.py` → 0 nuevas, 0
  quitadas, contenido idéntico salvo finales de línea (el generador escribe
  LF; el checkout de Windows es CRLF).
- **Controles negativos** (T013), sobre `test_tools_system_logs.py`,
  `test_tools_supervisor.py` y `test_command_table.py`: (a) 28 caídos,
  entre ellos `test_boot_invalido` y `test_invalidos_sin_llamada`; (b) 5
  (`test_boot_y_latest_a_la_vez`, `test_invalidos_sin_llamada`); (c) 2
  (`test_identifier_de_hermes_tapa_la_red`); (d) 1
  (`test_log_grande_devuelve_las_ultimas_lineas`); (e) 1
  (`test_lectura_correcta`); (f) 2 (`test_rutas_de_logs_dedicadas`,
  `test_ninguna_ruta_de_logs_pendiente_de_la_013`); (g) 1
  (`test_sin_boot_ni_latest_identica_a_la_1_1_2`). Restaurado: verde.

---

## Tramo 2 — disco, host y OS (CAP-085) y la tabla (CAP-087 lectura, CAP-088, CAP-089)

### Tests (escritos antes, en rojo)

- [x] T016 [P] [US2] Fixture (ampliar `tests/fixtures/supervisor_diagnostico.py`: `/host/services`, uso de disco con 30 hijos en un nivel y tres niveles, `/os/info`, `/os/config/swap`, `/os/datadisk/list`) y tests en `tests/test_tools_host_system.py`: `sv_list_host_services` (sobre común; `state="failed"` filtra exacto); `sv_get_disk_usage` → `/host/disks/default/usage` con `params={"max_depth": "1"}` y `timeout_seconds` ≥ 75; `disk="nas_backups"` → su ruta; `disk` inválido (`"a-b"`, `"a/b"`, `""`, 65 caracteres) y `max_depth` -1 o 4 → `invalid_argument` sin llamada; poda: 20 hijos por nivel ordenados por `used_bytes` (empate por `id`), `children_omitted` y `omitted_bytes` que cuadran con lo quitado, recursiva hasta `max_depth`; ids `addons_data`/`addons_config` de v1 pasan tal cual; `sv_get_os_info` y `sv_get_swap` devuelven el objeto; `sv_list_datadisk_candidates` con el sobre común y `devices`; un centinela bajo una clave `password` inyectado en la respuesta de `/os/info` sale tapado (`redact_structure`) (FR-011…FR-016)
- [x] T017 [P] [US2] Tests de errores en `tests/test_tools_host_system.py`: 404 en `/os/info`, `/os/config/swap` y `/os/datadisk/list` → `error` con la pista de Home Assistant OS; 400 de un montaje desconocido → `error` redactado sin pista; `HAConnectionError` sin `status` → `error`; nunca una respuesta vacía como buena; evento de log `system_diagnostics_read` con `count`/`bytes` y sin datos de la respuesta (ni `serial` ni nombres de disco) (FR-016, FR-010)
- [x] T018 [P] [US3] Tests en `tests/test_tools_diagnostico_tabla.py` con `sv_read_api` (de la 011) y el Supervisor simulado: `GET /jobs/info`, `/resolution/issue/<uuid ficticio>/suggestions`, `/host/disks`, `/hardware/info`, `/hardware/audio`, `/security/info`, `/docker/info`, `/time/info`, `/network/info`, `/network/interface/eth0/info` y `/network/interface/wlan0/accesspoints` → una llamada `GET` y la respuesta redactada (un centinela bajo `password` en `/docker/info` sale tapado); `sv_call_api("POST", "/security/integrity")` y `sv_read_api` con esa ruta → rechazo sin llamada y el motivo de la tabla; `sv_read_api("/core/logs")`, `("/os/info")` y `("/addons/<slug>/logs/latest")` → `use_dedicated_tool` con la tool correcta y sin llamada; con `system_diagnostics` desactivada → `family_disabled: true`; `/network/info` con IPs, MAC y SSID ficticios → el log capturado no contiene ninguno (FR-018…FR-020)

### Implementación

- [x] T019 [US2] `hermes/src/hermes/tools/host_system.py`: cinco tools según contracts/tools.md (poda en una función pura con su porqué, `redact_structure` en las respuestas JSON, errores con pista, evento de log); `host_system` en la familia `system_diagnostics` (`tool_families.py` y su test de T002); registro en `tools/__init__.py`. T016 y T017 en verde (FR-011…FR-016, FR-021)
- [x] T020 [US2] Tests en `tests/test_tools_registration.py` para las cinco: registradas por defecto, `readOnlyHint`, idempotentes, sin mundo abierto, sin `confirmation_token`; ninguna con la familia desactivada; SC-005 de la 011 en verde (FR-021)
- [x] T021 [US2] `hermes/src/hermes/tools/_annotations.py`: `"os": "OS"` en `_TITLE_WORDS` con un comentario; test en `tests/test_tools_registration.py`: `sv_get_os_info` → `Get OS info (Supervisor)` y ningún título de las tools de `_HINTS_SNAPSHOT` (1.1.2) cambia (FR-021)
- [x] T022 [US2] [US3] Tests en `tests/test_command_table.py` y después `hermes/src/hermes/command_table.py`: las 5 rutas de CAP-085 a `dedicated` (`cap="CAP-085"`); `/jobs/info` y `/resolution/issue/{issue}/suggestions` a `read` (`cap="CAP-087"`) y `/host/disks` a `read` (`cap="CAP-085"`) con los motivos de data-model y un comentario encima de cada una; en el test, diccionario `_POR_LA_TABLA` (clave → «spec 013: <porqué>», research R-5) que `test_clase_a_de_via_dedicada_pendiente_de_su_spec` admite como `read`/`confirm`; ninguna entrada con «spec 013»; el test de verbos sigue en verde; regenerar la tabla sin cambios (FR-017, FR-018)
- [x] T023 [US3] Hacer verde T018 (sin código de producto: si algo falla, es la tabla o la genérica de la 011; un fallo de la 011 se anota y no se arregla aquí, principio IX) (FR-018…FR-020)
- [x] T024 [US4] Comprobar en `tests/test_tools_registration.py` que, con `system_diagnostics` desactivada, la tabla sigue con sus 28 `dedicated` y `TestDedicadas` pasa con todas las familias activas (FR-021; FR-012 de la 008)
- [x] T025 [US2] [US3] Guía: tests en `tests/test_tools_guide.py` (el tema `system_diagnostics` nombra las once tools, `max_depth` y la poda, la necesidad de Home Assistant OS, y las rutas que se leen con `sv_read_api`: jobs, sugerencias, hardware, seguridad, Docker, hora, red y discos montables; alias `disk`, `storage`, `os`, `jobs`; `hermes_guide(topic="generic_commands", search="jobs")` lista `/jobs/info` como `read`); después, `hermes/src/hermes/tools/guide.py` (FR-023)
- [x] T026 Documentación: completar la sección de la 013 en el CHANGELOG (cinco tools, tres rutas `read`, integridad `deny` por el Supervisor 2026.11, prueba en vivo pendiente); `docs/HOJA-DE-RUTA.md`: estado de la 013 en la tabla del programa y la prueba en vivo de las 11 tools y de las rutas `read` como pendiente manual (014 o cierre) en la matriz tool → entorno; `README.md` y `README.es.md` sincronizados (recuento de tools según el registro de ese momento, fila de la familia nueva y logs de arranques anteriores en la fila de add-ons); filas CAP-081, CAP-085, CAP-087, CAP-088 y CAP-089 de la matriz de `specs/008-cobertura-total/plan.md` con las tools, las rutas de la tabla y los ficheros de test, sin cambiar sus columnas de sub-feature ni de vía (las lee `_matriz_008`); la desviación de FR-047 anotada en la fila de CAP-088 (FR-025)
- [x] T027 Control negativo del tramo 2, anotando recuentos: (a) quitar la poda → cae el de 20 hijos; (b) no validar `max_depth` → caen los de rango; (c) no poner la pista en el 404 de `/os/*` → cae; (d) dejar `/jobs/info` como `deny` → caen el de la tabla y el de `sv_read_api`; (e) pasar `/security/integrity` a `confirm` → cae; (f) añadir al evento de la genérica un dato de la respuesta de red → cae el de log sin direcciones; (g) quitar `"os": "OS"` → cae el del título. Restaurar y comprobar verde
- [x] T028 Cierre del tramo 2: suite completa (los 6 fallos conocidos y ninguno más), `grep -c "spec 013" hermes/src/hermes/command_table.py` = 0, regeneración sin cambios, revisión del diff (principio VIII), commit con los recuentos de T027

### Notas del tramo 2 (2026-11-14)

- **Línea base** (punta `68cbd6f`, sin volver a traer `feat/cobertura-total`):
  2363 passed, 65 skipped, 6 failed (los 6 de Windows).
- **Desviación — `children_omitted`**: solo aparece en un nodo al que se le
  han quitado hijos (lo que dice FR-012); el ejemplo de contracts/tools.md lo
  ponía a 0 en la raíz. Los hijos se ordenan siempre por `used_bytes`
  (empate por `id`), también si son 20 o menos.
- **Desviación — respuesta de forma inesperada**: un `data` vacío o sin la
  forma esperada (sin `services`, `disks` o `used_bytes`) da
  `{"error": "Unexpected Supervisor response for GET <plantilla>."}` (FR-016:
  nunca una respuesta vacía como buena). `devices` de
  `sv_list_datadisk_candidates` pasa también por `redact_structure`.
- **Desviación — validación de `disk`**: además de la regla de data-model,
  el segmento pasa por `validate_path_segment` (segunda capa, como en el
  tramo 1); `max_depth` rechaza `True` y el texto `"1"`.
- **`_POR_LA_TABLA`** (T022): la regla del test exige además que la spec del
  porqué («spec 013: …») sea una de las sub-features de la CAP en la matriz.
- **T024**: en `TestHostSystem013.test_con_la_familia_apagada_la_tabla_sigue_igual`
  (26 entradas `dedicated` de `system_diagnostics` y 2 de `supervisor`, 28).
- **README**: la fila «System logs» / «Logs del sistema» pasa a «System
  diagnostics» / «Diagnóstico del sistema» con 11 tools; recuento 226 → 231.
- **CHANGELOG**: recuentos de la tabla del Supervisor del bloque de la 011:
  `dedicated` 52 → 57, `read` 26 → 29, `deny` 151 → 143.
- **Matriz de la 014**: no está en esta rama (la 014 se integra en
  `feat/cobertura-total` después de que se abriera la 013 y no se ha vuelto a
  traer). La prueba en vivo de las once tools y de las rutas `read` queda en
  «Pruebas manuales pendientes» de la hoja de ruta; al integrar, las once
  van a la matriz de la 014 como «VM / pendiente» (todas solo leen).
- **Desviación de FR-047 de la 008**: `POST /security/integrity` sigue
  `deny` (410 en el Supervisor 2026.11.0, research R-6); anotada en la fila
  CAP-088 de la matriz de la 008 y en el CHANGELOG.
- **Regeneración de la tabla** (T022): `generar_tabla.py` → 0 nuevas, 0
  quitadas, contenido idéntico salvo finales de línea.
- **Controles negativos** (T027), sobre `test_tools_host_system.py`,
  `test_tools_diagnostico_tabla.py`, `test_command_table.py`,
  `test_tools_registration.py` y `test_tools_guide.py`: (a) 3 caídos
  (`test_poda_a_20_hijos`, `test_poda_recursiva`, `test_empate_por_id`);
  (b) 1 con 4 subtests (`test_argumentos_invalidos_sin_llamada`); (c) 1 con 3
  subtests (`test_404_de_os_con_pista`); (d) 4
  (`test_rutas_read_se_ejecutan`, `test_tres_rutas_a_read`,
  `test_clase_a_de_via_dedicada_pendiente_de_su_spec`,
  `test_jobs_en_la_tabla`); (e) 2 (`test_integridad_no_llega_al_supervisor`,
  `test_integridad_sigue_deny`); (f) 1 (`test_log_de_red_sin_direcciones`);
  (g) 2 (`test_os_no_cambia_ningun_titulo_existente`,
  `test_hints_y_titulos_de_las_nuevas`). Restaurado: verde.

---

## Dependencias

- Tramo 1: T001 → T002 → T003…T006 (en paralelo) → T007 → T008 → T011 (registro: sin él, `TestDedicadas` no encuentra las tools) → T009 → T010 → T012; T013, T014 y T015 al final.
- Tramo 2 (tras el tramo 1): T016…T018 en paralelo; T019 tras T016 y T017; T020 y T021 tras T019; T022 tras T019; T023 tras T018 y T022; T024 tras T022; T025 tras T019 y T022; T026, T027 y T028 al final.

## Paralelismo

- Tramo 1: T003, T004, T005 y T006 (ficheros o clases de test distintos).
- Tramo 2: T016, T017 y T018.

## Estrategia

MVP = tramo 1: los logs de todo el sistema, también de arranques anteriores,
que es la CAP de prioridad alta. El tramo 2 añade disco y OS (media-alta) y
deja documentado y probado lo que va por la tabla. Todo es de lectura y sale
en la 1.2.0 con el resto del programa; la prueba en vivo queda para la 014 o
el cierre.

---

## Fase 3: Convergencia

Revisión independiente y converge (2026-11-14) sobre la punta `f26f5dd`.
Severidad entre corchetes. Cada hallazgo se verificó con un script fuera del
repositorio contra el Supervisor simulado y el código del Supervisor 2026.11.0.

- [ ] T029 [MEDIO] `sv_get_disk_usage` debe caber en `response_max_bytes` por su cuenta: con `max_depth` 2–3 un árbol podado a 20 hijos por nivel pasa del tope (8 ramas × 20 × 20 nodos de nombre corto ≈ 213 KB con el tope de 128 KiB) y el guardián central quita ramas enteras del primer nivel (quedan 4 de 8) sin poner `children_omitted`/`omitted_bytes` en la raíz, así que la suma no cuadra y la pista habla de dominios y fechas. Podar con el tope (bajar `max_hijos` 20 → 10 → 5… hasta que quepa, o recortar en la tool actualizando `children_omitted` y `omitted_bytes`), decirlo en la respuesta, corregir el comentario de `tools/__init__.py` («podan el árbol… a su tope») y añadir un test con un árbol de tres niveles mayor que el tope, con su control negativo, per FR-012, research R-4 y principio V (partial)
- [ ] T030 [BAJO] `sv_get_addon_logs`: el error del Supervisor vuelve sin redactar (`{"error": str(exc)}`), también con `boot`/`latest`; pasarlo por `redact_secrets` (y `redact_network` si es Hermes), como las tools nuevas, sin cambiar la forma `{"error": …}` de la 1.1.2, con un test con centinela en el error, per FR-024, FR-009 y el caso límite «`boot` fuera de lo que el journal tiene» (partial)
- [ ] T031 [BAJO] `sv_list_boots` y `sv_list_host_log_identifiers`: una respuesta sin `boots`/`identifiers` se devuelve como lista vacía buena, y `boots` que no sea un objeto lanza `AttributeError`; devolver `error` de forma inesperada como en `host_system.py`, y pasar los `items` de `sv_list_boots` por `redact_structure`, con tests, per FR-016 y FR-006 (partial)
- [ ] T032 [BAJO] Descripción y guía de `sv_get_disk_usage`: en un montaje el Supervisor convierte `max_depth` < 2 en 0 y solo desglosa con `max_depth` > 1, así que el valor por defecto (1) da solo totales y N da N-1 niveles; decirlo en el docstring y en el tema `system_diagnostics`, per FR-012 y principio V (partial)
