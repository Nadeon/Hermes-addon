---

description: "Tareas del banco de pruebas del Supervisor (spec 014)"
---

# Tareas: banco de pruebas del Supervisor (procedimiento, matriz y `hassio_role`)

**Entrada**: `specs/014-banco-de-pruebas-supervisor/` (spec.md, plan.md,
research.md, data-model.md, contracts/matriz.md, contracts/procedimiento.md,
quickstart.md).

**Tests**: obligatorios y antes que el documento o el cambio que comprueban
(principios VI y VII). Estilo de la suite: `unittest.TestCase`, sin HA, Docker
ni red; corren en Windows y en Linux. Datos genéricos (principio VIII).

**Cómo se ejecuta la suite en local** (Git Bash, desde la raíz del worktree):
`export MSYS_NO_PATHCONV=1` y
`HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" <venv>/Scripts/python.exe -m pytest -q -p no:cacheprovider`.
Referencia: fallan exactamente los 6 tests conocidos de Windows. Línea base
al especificar (`cc478d4`): 2080 pasados, 38 saltados, 6 fallos.

**Prohibido en esta sub-feature** (decisión del supervisor): montar la VM,
ejecutar nada contra una HA real o una VM, versionar scripts para montarla,
cambiar `hassio_role`, tocar código de `hermes/src/`.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 procedimiento, US2 matriz, US3 casillas manuales,
US4 comentario de `hassio_role`.

## Tramos de implementación

Un solo tramo (la 008 la dimensiona S). Lo hace un agente nuevo. Al terminar:
suite local con exactamente los 6 fallos conocidos; un commit propio (o
varios, pero que se pueda revertir de una vez) con los recuentos de los
controles negativos; si el encargo permite empujar, CI en verde.

| Tramo | Tareas | Resultado |
|---|---|---|
| **Único** | T001–T016 | Comentario de `hassio_role` corregido con sus dos tests; matriz de 124+ filas atada al registro y a los inventarios; procedimiento del banco del Supervisor; casillas manuales con su entorno; documentación |

Tamaño estimado: dos ficheros de test (~350 líneas en total), un documento de
~250 líneas, ~140 líneas de matriz (generadas) y ediciones pequeñas. Cabe en
el contexto de un agente; si no cupiera, el corte natural es tras T005 (US4
cerrada y commiteable).

---

# TRAMO ÚNICO (T001–T016)

## Fase 1: Preparación

- [x] T001 Línea base y estado de la rama: ejecutar la suite completa (esperado: los 6 fallos conocidos) y anotar los recuentos; listar `tests/banco/cobertura*.py` (la 010 siempre; `cobertura_escrituras.py` si la 028 ya está integrada; otros si los hay) y comprobar si existe `hermes/src/hermes/command_table.py` (011); contar las tools sin `readOnlyHint` del registro de producción (`_build_mcp(HermesConfig(call_service_auto_classify_dangerous=False), MagicMock())`) y separarlas en `ha_*`, `sv_*` y `fs_*`. Anotar en el commit: con `cc478d4` eran 124 (100 `ha_*`, 19 `sv_*`, 5 `fs_*`); si la 011 está integrada habrá además sus genéricas que modifican

## Fase 2: US4 — el comentario de `hassio_role` dice la verdad (P1)

- [x] T002 [US4] Tests en `tests/test_addon_manifest.py`, clase nueva `TestComentarioDelRol` (deben fallar al principio): lee `hermes/config.yaml` como texto y aísla el bloque de comentario de `hassio_role` (desde su línea hasta la siguiente clave de primer nivel); (a) el YAML cargado tiene `hassio_role == "admin"`; (b) el bloque no contiene `403` ni afirma que Hermes use `bashio::config` (no contiene `necesario para bashio::config`); (c) contiene `api_bypass`, `2026.11.0`, `/addons/self/options/config`, `manager` y una remisión a `docs/HOJA-DE-RUTA.md` o `docs/BANCO-SUPERVISOR.md`; (d) `hermes/run.sh` no ejecuta `bashio::config` (fuera de comentarios), que es el hecho en que se apoya (b). Docstring con el porqué (FR-007, SC-005)
- [x] T003 [US4] Reescribir el comentario de `hassio_role` en `hermes/config.yaml` según plan §4, sin cambiar el valor ni ninguna otra línea del fichero. Pasan los tests de T002 (FR-007, FR-011)
- [x] T004 [P] [US4] Crear `tests/test_rutas_supervisor_rol.py` (research R-4, data-model): constantes `API_BYPASS`, `ROL_MANAGER` y `NO_SECURITY_CHECK` copiadas literalmente de `supervisor/api/middleware/security.py` (`_V1_PATTERNS`) del Supervisor 2026.11.0, con `RE_SLUG` de `supervisor/apps/const.py`, y un comentario que cita ambos ficheros y la versión; extractor con `ast` de las llamadas `*.sv_request(método, ruta)`/`*.sv_request_text(ruta)` (también con `path=`) en `hermes/src/hermes/**/*.py`, con los huecos de los f-strings sustituidos por `x`; `RUTAS_DEL_PROXY_DE_CORE = ("/core/api/states", "/core/api/websocket")`; `LLAMADAS_DECLARADAS` (módulo, función → rutas posibles o «tabla de la 011»; hoy `("hermes.tools.addons", "sv_list_addons") → ("/addons", "/store/addons")`, data-model) y `EXCEPCIONES_ADMIN: dict[str, str]` (ruta → motivo), vacía. Tests: `test_patrones_copiados_rechazan_lo_de_admin` (`/auth/list`, `/auth/reset`, `/addons/x/security`, `/os/datadisk/wipe`, `/ingress/panels` no casan con ninguno); `test_patrones_copiados_aceptan_options_config` (`/addons/self/options/config` casa con `API_BYPASS`); `test_extractor_encuentra_las_rutas_conocidas` (contiene al menos `/info`, `/addons/x/info`, `/store/addons/x/install`, `/backups/x/restore/full`, `/host/reboot`, `/core/restart`, `/jobs/x`, `/addons/x/logs`); `test_toda_llamada_reconocida` (el número de apariciones de `sv_request` como llamada en el código es el número de llamadas extraídas más las de `LLAMADAS_DECLARADAS`; una llamada con ruta no literal fuera de esa lista cae nombrando fichero y línea); `test_rutas_de_hermes_caben_en_manager` (cada ruta casa con `NO_SECURITY_CHECK`, `API_BYPASS` o `ROL_MANAGER`, o está en `EXCEPCIONES_ADMIN`; cae nombrando las que no); `test_rutas_de_la_tabla_de_la_011` (si `importlib.util.find_spec("hermes.command_table")` existe: las claves de `SUPERVISOR` con categoría `read` o `confirm`, con `{…}` → `x`, cumplen la misma regla; si no existe, el test lo dice en un comentario y no comprueba nada más); `test_excepciones_con_motivo` (ningún motivo vacío y cada excepción se usa). Si alguna ruta real queda fuera de `manager`, se añade a `EXCEPCIONES_ADMIN` con su motivo y se nombra en el comentario de T003 y en la casilla de T011 (FR-008, SC-006)
- [x] T005 [US4] Control negativo de T002–T004: (1) devolver el comentario viejo → cae T002 (b) y (c); (2) `hassio_role: manager` → cae T002 (a); (3) añadir temporalmente en una tool `await ha_client.sv_request("GET", "/auth/list")` → cae `test_rutas_de_hermes_caben_en_manager` nombrándola; (4) quitar `(?!security)` del patrón copiado de `manager` → cae `test_patrones_copiados_rechazan_lo_de_admin`; (5) añadir una llamada `sv_request("GET", ruta)` con variable → cae `test_toda_llamada_reconocida`. Restaurar y anotar los recuentos (FR-010)

## Fase 3: US2 — la matriz tool → entorno → resultado (P1)

- [x] T006 [US2] Crear `tests/test_matriz_pruebas.py` con todos los tests de [contracts/matriz.md](contracts/matriz.md) (deben fallar al principio: no hay matriz, ni procedimiento, ni casillas nuevas). Registro de producción como en `tests/test_banco_cobertura.py`; descubrimiento de inventarios con `pkgutil.iter_modules` sobre `tests/banco` y los módulos que empiezan por `cobertura`, leyendo las constantes por la convención de data-model (ignorar `DOMINIOS_*`, `MODULOS_*`, `XFAIL_*`, `PENDIENTES_*`; tipo equivocado → fallo nombrando módulo y constante); lectura de la matriz entre `<!-- matriz-pruebas:inicio -->` y `<!-- matriz-pruebas:fin -->`; mensajes que nombran la tool y la regla. Docstring con el invariante, la regla para las sub-features siguientes y la nota de que los simuladores no son un entorno de la matriz (FR-002, FR-003, FR-004, FR-005)
- [x] T007 [US2] Generar las filas de la matriz con un fragmento de Python en la carpeta temporal propia (no se versiona): una por tool sin `readOnlyHint`, en orden alfabético; entorno y resultado según las reglas de data-model y los inventarios presentes (T001); `ha_reload_counters` con su nota de hallazgo (spec 033); notas cortas útiles en las `sv_*`/`fs_*` («instantánea antes» en las de la tanda 3, «add-on de prueba» en las de la tanda 2). Añadir a `docs/HOJA-DE-RUTA.md` la subsección `#### Matriz de pruebas: tool → entorno → resultado (014)` tras «Banco de Core: helpers (010)» (o tras la sección de la 028 si está), con el párrafo de contracts/matriz.md y las filas entre los marcadores. Pasan los tests de la matriz salvo los del procedimiento y las casillas (FR-002, FR-003, SC-001, SC-002, SC-003)
- [x] T008 [US2] Control negativo de T006/T007: (1) borrar la fila de `sv_reboot_host` → cae `test_una_fila_por_tool_que_modifica` nombrándola; (2) `ok` sin nota en `sv_restart_core` → cae `test_notas_obligatorias`; (3) `banco de Core` en `fs_write_file` → cae `test_sv_y_fs_en_la_vm`; (4) `pendiente` en `ha_set_input_boolean` → cae `test_coherente_con_los_inventarios`; (5) crear un inventario temporal `tests/banco/cobertura_control.py` con `PROBADAS_CONTROL = ["ha_set_input_boolean"]` (lista, no conjunto) → cae `test_inventarios_descubiertos` nombrando módulo y constante; borrar el fichero; (6) el mismo fichero con `PROBADAS_CONTROL = frozenset({"sv_reboot_host"})` → cae `test_coherente_con_los_inventarios` (una probada del banco cuya fila no dice `banco de Core`/`ok`); borrar el fichero. Restaurar y anotar los recuentos (FR-010)

## Fase 4: US1 — el procedimiento (P1)

- [x] T009 [US1] Escribir `docs/BANCO-SUPERVISOR.md` según [contracts/procedimiento.md](contracts/procedimiento.md): las once secciones `##` con su nombre exacto; comandos en bloques con marcadores genéricos; la sección «Tandas de pruebas» nombra entre comillas invertidas cada tool con entorno «VM» de la matriz y dice qué comprobar en cada una (vista previa que no cambia nada y describe el efecto exacto, ejecución con el token, efecto comprobado fuera de Hermes, log sin secretos); «Probar hassio_role: manager» según FR-006, con las excepciones de `EXCEPCIONES_ADMIN` si las hay. Hechos del Supervisor y de Hermes solo los de research R-3 (si hace falta otro, leerlo antes en `fuentes/supervisor` o en el código y citarlo). Pasan `test_procedimiento_con_sus_secciones` y `test_cada_tool_de_la_vm_en_el_procedimiento` (FR-001, FR-006, SC-002)

## Fase 5: US3 — casillas manuales con su entorno (P2)

- [ ] T010 [US3] En `docs/HOJA-DE-RUTA.md`, renombrar «Pruebas manuales pendientes en una instalación real» a «Pruebas manuales pendientes» (y actualizar los enlaces internos que apunten a ese título, si hay) y poner a cada casilla su entorno al principio según research R-5: «(VM)», «(instalación real)», «(VM o instalación real)», «(cliente contra la instalación real)»…
- [ ] T011 [US3] En la misma sección: casilla nueva «(VM) Matriz del Supervisor» que enlaza `docs/BANCO-SUPERVISOR.md` y remite a la matriz; casilla nueva «(instalación real, tras publicar) Pruebas en vivo de las tools nuevas de la 1.2.0»; reescribir la de `hassio_role: manager` («(VM, después instalación real)», sin `bashio::config`: arranque, opciones de otros add-ons y cada `sv_*`; con las excepciones de `EXCEPCIONES_ADMIN` si las hay); la de «las 13 tools de escritura de la 1.1.x» remite a la matriz. Pasan `test_casillas_manuales` y `test_hoja_de_ruta_enlaza_el_procedimiento`; la suite de la 014 entera en verde (FR-005, SC-004)

## Fase 6: Documentación y cierre

- [ ] T012 [P] `hermes/CHANGELOG.md`, sección «Banco de pruebas» de `## [1.2.0]`: viñeta de la 014 (procedimiento del banco del Supervisor, matriz con una fila por tool que modifica y su test, casillas manuales con entorno, comentario de `hassio_role` corregido sin cambiar el rol y test de las rutas contra `manager`). Sin promesas de pruebas no hechas (FR-009)
- [ ] T013 [P] `docs/HOJA-DE-RUTA.md`: fila 014 → «hecha» en la tabla del programa; «Verificado contra»: las 24 `sv_*`/`fs_*` se prueban con simuladores y su prueba real está en la matriz (VM, pendiente); párrafo «Probar `hassio_role: manager` (014)» de «lo que antes estaba como pendiente»: el comentario ya está corregido y queda la prueba en vivo (D-02) (FR-009)
- [ ] T014 [P] `specs/008-cobertura-total/plan.md`, matriz de trazabilidad: filas CAP-006 (`docs/BANCO-SUPERVISOR.md`, `test_procedimiento_con_sus_secciones`), CAP-022 (`TestComentarioDelRol`, `tests/test_rutas_supervisor_rol.py`; prueba manual pendiente), CAP-034 (añadir `tests/test_matriz_pruebas.py` a la parte del Supervisor) y CAP-035 (`test_casillas_manuales`) (FR-009)
- [ ] T015 Revisión de privacidad del diff (sin hostnames, IPs, slugs reales, contraseñas, rutas `C:\…` ni identificadores de modelos; las notas de la matriz sin datos de una instalación) y de SC-007: `git diff --stat feat/cobertura-total -- hermes/` solo con `config.yaml` (el comentario) y `CHANGELOG.md` (FR-011)
- [ ] T016 Suite completa (exactamente los 6 fallos conocidos de Windows) y commit del tramo con los recuentos de T005 y T008 y la lista de inventarios encontrados en T001 (SC-008)

---

## Dependencias

- T001 primero.
- US4: T002 → T003; T004 en paralelo con T002/T003 (fichero distinto); T005
  tras T003 y T004.
- US2: T006 → T007 → T008. T007 necesita T001 (inventarios presentes).
- US1: T009 tras T007 (nombra las tools con entorno «VM» de la matriz) y tras
  T004 (excepciones, si las hay).
- US3: T010 → T011; T011 tras T004.
- T012, T013 y T014 en paralelo tras T011; T015 y T016 al final.

## Paralelismo

- T002 ∥ T004; T012 ∥ T013 ∥ T014.

## Estrategia

US4 primero: es lo único que toca un fichero del add-on y se cierra solo
(T002–T005). Después la matriz (US2), que es la que fija qué tools tiene que
nombrar el procedimiento (US1); las casillas (US3) y la documentación al
final.

## Tabla de clasificación y tools

- **Tools nuevas**: ninguna.
- **Entradas de la tabla que pasan a `dedicated`**: ninguna (la 014 no añade
  tools; `command_table.py` no se toca).
- **Familias**: ninguna nueva.
