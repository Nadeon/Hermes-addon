---

description: "Tareas del programa de cobertura total, Hermes 1.2.0 (spec 008, paraguas)"
---

# Tareas: Hermes 1.2.0 — cobertura total (paraguas)

**Entrada**: `specs/008-cobertura-total/` (spec.md, plan.md, research.md,
inventario/).

**Cómo se lee**: es un programa. Cada tarea T002…T025 (y T030) es **una sub-feature
entera**: escribir su spec, plan y tareas con spec-kit en `specs/NNN-nombre/`
(trazando a los FR de esta spec y a sus CAP), implementarla en los tramos que
dice el plan y cerrarla con la suite y el CI en verde. Todas comparten las
reglas transversales: tabla actualizada a `dedicated` para sus tools nuevas
(FR-012), banco para lo de Core (FR-015), convenciones y control negativo
(FR-018, principio VII), secretos (FR-019), compatibilidad (FR-020),
privacidad (FR-021), CHANGELOG 1.2.0 y documentación (FR-022, FR-023), fila de
la matriz de trazabilidad de plan.md rellenada y fila de la hoja de ruta a
«hecha». Cada sub-feature termina en su propio commit (o PR contra la rama) con
los recuentos de los controles negativos.

**Tests**: obligatorios en cada sub-feature (principios VI y VII).

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 alcanzable, US2 vista previa, US3 no se rompe, US4
diagnóstico, US5 qué está probado, US6 deriva, US7 familias.

## Fase 1: Preparación

- [X] T001 Línea base del programa: la suite completa pasa sobre la punta de `feat/cobertura-total`; anotar el recuento en `specs/008-cobertura-total/tasks.md` (referencia: CI de Linux) y decidir con el mantenedor las enmiendas E-1…E-4 de `specs/008-cobertura-total/plan.md` antes de T004

## Fase 2: Fundacional — ola 0 (bloquea el resto)

- [X] T002 [P] [US3] Sub-feature 009 `correcciones-pendientes` en `specs/009-correcciones-pendientes/`: CAP-010…CAP-018, CAP-021, CAP-024 (FR-025…FR-035) y versión 1.2.0 en `hermes/config.yaml`, `hermes/src/hermes/__init__.py` y `HA_CORE_LAST_TESTED_IN_HERMES` de `hermes/src/hermes/config.py`, con la entrada `## [1.2.0] — <fecha de publicación>` y sus secciones por bloque en `hermes/CHANGELOG.md` (FR-022). M, 2 tramos: (a) redacción y log (`security.py`, `logging_setup.py`); (b) tools y apagado
- [X] T003 [P] [US5] Sub-feature 010 `banco-de-pruebas-core` en `specs/010-banco-de-pruebas-core/`: job del CI en `.github/workflows/tests.yml` (o uno nuevo) con HA Core 2026.11.1 por digest, onboarding con credenciales del job, Supervisor simulado en `tests/`, y las escrituras de helpers ejecutadas y comprobadas en el banco (CAP-005, CAP-034 parte; FR-013, FR-014). M, 2 tramos: (a) infraestructura y humo; (b) helpers

## Fase 3: Ola 1 — política de comandos y resto del banco

- [X] T004 [US1] [US2] [US6] [US7] Sub-feature 011 `politica-de-comandos` en `specs/011-politica-de-comandos/`: tabla generada desde `specs/008-cobertura-total/inventario/`, extractor versionado fuera de `hermes/src`, guardas fail-closed, test de verbos, test de deriva, `ha_read_ws_command`, `ha_call_ws_command`, `sv_read_api`, `sv_call_api`, familias en `hermes/config.yaml` y en el registro de `hermes/src/hermes/tools/__init__.py`, guía y consulta de la tabla (CAP-001…CAP-004, CAP-007, CAP-008; FR-001…FR-012). Si el mantenedor acepta E-1…E-4, se aplican aquí antes del código. L, 3 tramos: (a) tabla, deriva y verbos; (b) genéricas de Core y del Supervisor; (c) familias y guía. Depende de T002 y T003
- [X] T005 [P] [US5] Sub-feature 028 `pruebas-escrituras-core` en `specs/028-pruebas-escrituras-core/`: resto de tools `ha_*` que modifican (automatizaciones, scripts, escenas, registros, Lovelace, flujos de config entries, servicios, eventos, temporizadores) ejecutadas y comprobadas en el banco, y lista de las no ejecutables con motivo (CAP-034; FR-014). M, 2 tramos. Depende de T003

## Fase 4: Ola 2 — diagnóstico, integraciones, mejoras y procedimientos

- [X] T006 [P] [US4] Sub-feature 012 `diagnostico-core` en `specs/012-diagnostico-core/`: CAP-040, CAP-041, CAP-042, CAP-047 (FR-036…FR-039). M, 2 tramos. Depende de T002 y T004
- [X] T007 [P] [US4] Sub-feature 029 `estado-y-estadisticas-core` en `specs/029-estado-y-estadisticas-core/`: CAP-043, CAP-049 dedicadas; CAP-058, CAP-068 por la tabla (FR-040…FR-043). M, 2 tramos. Depende de T004
- [X] T008 [P] [US4] Sub-feature 013 `diagnostico-supervisor` en `specs/013-diagnostico-supervisor/`: CAP-081, CAP-085 dedicadas; CAP-087 (lectura), CAP-088, CAP-089 por la tabla (FR-044…FR-048). M, 2 tramos. Depende de T002 y T004
- [X] T009 [P] [US5] Sub-feature 014 `banco-de-pruebas-supervisor` en `specs/014-banco-de-pruebas-supervisor/`: procedimiento de la VM con HAOS, matriz tool → entorno → resultado y pruebas manuales en `docs/HOJA-DE-RUTA.md`, comentario de `hassio_role` en `hermes/config.yaml` (CAP-006, CAP-022, CAP-034, CAP-035; FR-016, FR-017). S, 1 tramo. Depende de T003
- [X] T010 [P] [US1] Sub-feature 016 `integraciones-flujos-y-repairs` en `specs/016-integraciones-flujos-y-repairs/`: CAP-044, CAP-045, CAP-048, CAP-036, CAP-037 (FR-053…FR-057). L, 3 tramos: (a) descubiertas, preferencias y guía de helpers; (b) subentries y reconfigure; (c) reparación y traducciones. Depende de T004
- [X] T011 [P] [US2] [US3] Sub-feature 018 `mejoras-de-tools-existentes` en `specs/018-mejoras-de-tools-existentes/`: CAP-019, CAP-020, CAP-023 (FR-063…FR-065). M, 2 tramos: (a) guardado por vistas; (b) denylist con token y sobre común. Depende de T004
- [X] T030 [P] [US2] [US3] Sub-feature 033 `arreglos-del-banco` en `specs/033-arreglos-del-banco/`: tools de la 1.1.2 rotas o deshonestas que destapa el banco (CAP-039; FR-099): token de `ha_trigger_automation`/`ha_run_script` atado a `variables` e inventario de argumentos atados; `not_supported` y deprecación de `ha_reload_counters` y `ha_get_config_entry_options`; `ctx` de `ha_wait_for_event`; `ha_create_scene_from_current`; descripciones de escenas; `amount` de contadores. M, 2 tramos: (1) token atado; (2) el resto. Depende de T004 y T005
- [X] T012 [P] [US3] Sub-feature 027 `plataforma-y-deprecaciones` en `specs/027-plataforma-y-deprecaciones/`: CAP-025, CAP-026, CAP-028…CAP-033 (FR-092…FR-097), sin retirar nada. S, 1 tramo

## Fase 5: Ola 3 — tools dedicadas y cola larga por la tabla

- [X] T013 [P] [US2] Sub-feature 015 `actualizaciones-del-sistema` en `specs/015-actualizaciones-del-sistema/`: CAP-080, CAP-064 (FR-049, FR-050). M, 2 tramos. Depende de T008
- [X] T014 [P] [US1] Sub-feature 030 `tienda-de-apps` en `specs/030-tienda-de-apps/`: CAP-082, CAP-093 (FR-051, FR-052). M, 2 tramos. Depende de T004
- [X] T015 [P] [US1] Sub-feature 017 `automatizacion-asistida` en `specs/017-automatizacion-asistida/`: CAP-046, CAP-051, CAP-052, CAP-038 y la validación al guardar de CAP-040 (FR-058…FR-062). L, 3 tramos: (a) blueprints; (b) automatizaciones de dispositivo y targets; (c) espera de trigger y validación al guardar. Depende de T006
- [X] T016 [P] [US2] Sub-feature 019 `montajes-y-ajustes-de-backup` en `specs/019-montajes-y-ajustes-de-backup/`: CAP-083 (FR-066). M, 2 tramos. Depende de T004
- [X] T017 [P] [US2] Sub-feature 031 `backups-integracion-y-cifrado` en `specs/031-backups-integracion-y-cifrado/`: CAP-057, CAP-027 (FR-067, FR-068). M, 2 tramos. Depende de T004
- [X] T018 [P] [US2] Sub-feature 020 `estadisticas-y-energia` en `specs/020-estadisticas-y-energia/`: CAP-050, CAP-054 (FR-069, FR-070). M, 2 tramos. Depende de T007
- [X] T019 [P] [US2] [US7] Sub-feature 021 `configuracion-del-sistema` en `specs/021-configuracion-del-sistema/`: CAP-053, CAP-055, CAP-056, CAP-069 dedicadas; CAP-074 por la tabla (FR-071…FR-075). L, 3 tramos: (a) núcleo y exposición; (b) usuarios; (c) red y HTTP, analytics y labs. Depende de T004
- [X] T020 [P] [US2] Sub-feature 022 `control-de-core-y-supervisor` en `specs/022-control-de-core-y-supervisor/`: CAP-084, CAP-087 (escritura) dedicadas; CAP-091, CAP-092, CAP-094 por la tabla (FR-076…FR-080). M, 2 tramos. Depende de T008
- [X] T021 [P] [US2] Sub-feature 032 `host-y-red-del-host` en `specs/032-host-y-red-del-host/`: CAP-086, CAP-090 (FR-081, FR-082). M, 2 tramos. Depende de T008
- [X] T022 [P] [US1] Sub-feature 023 `assist-y-conversacion` en `specs/023-assist-y-conversacion/`: CAP-060 dedicada; CAP-061, CAP-062, CAP-063 por la tabla (FR-083, FR-084). S, 1 tramo. Depende de T011
- [X] T023 [P] [US1] Sub-feature 024 `menores-core` en `specs/024-menores-core/`: CAP-059, CAP-071 dedicadas; CAP-065, CAP-066, CAP-067, CAP-070, CAP-072, CAP-073 por la tabla (FR-085…FR-088). M, 2 tramos. Depende de T004
- [X] T024 [P] [US1] Sub-feature 025 `integraciones-especificas` en `specs/025-integraciones-especificas/`: los 192 comandos de clase C clasificados uno a uno en la tabla y temas de la guía (CAP-100…CAP-106; FR-089, FR-090). L, 3 tramos (research R-9 de la 025): (1) Z-Wave JS; (2) ZHA, Matter, Thread y OTBR; (3) el resto. Depende de T004

## Fase 6: Ola 4

- [X] T025 [US2] Sub-feature 026 `marketplace-escritura` en `specs/026-marketplace-escritura/`: CAP-075 (FR-091). M, 2 tramos. Depende de T014

## Fase 7: Cierre del programa

- [X] T026 Converge del programa sobre `specs/008-cobertura-total/plan.md`: matriz de trazabilidad completa (cada CAP con tool o entrada de la tabla y test), ninguna entrada «pendiente de tool dedicada» en la tabla, test de deriva y de verbos en verde, comprobación de SC-001…SC-006 y SC-012 (FR-098)
- [ ] T027 [P] Documentación final: `README.md` y `README.es.md` sincronizados, `hermes/DOCS.md` (familias), `SECURITY.md` (tabla y genéricas), `hermes/CHANGELOG.md` con todos los bloques, y en `docs/HOJA-DE-RUTA.md` la tabla del programa a «hecha», la matriz de pruebas, los pendientes manuales y las dudas D-01…D-10 (FR-023, SC-009, SC-011)
- [ ] T028 Versión: comprobar 1.2.0 en `hermes/config.yaml`, `hermes/src/hermes/__init__.py` y `hermes/src/hermes/config.py`, y poner la fecha de publicación en `hermes/CHANGELOG.md` cuando el mantenedor la decida (FR-022, SC-009)
- [ ] T029 Suite completa y CI en verde (tests, banco de Core, Semgrep, CodeQL) en la punta de la rama; revisión del diff entero buscando datos personales e identificadores de modelos; PR de `feat/cobertura-total` a `main` con los recuentos de controles negativos de todas las sub-features y la lista de dudas para el final. Fusionar y publicar los decide el mantenedor (SC-007, SC-010)

## Dependencias

- T001 → T002, T003 (ola 0, en paralelo) → T004 (necesita las dos) y T005
  (necesita T003).
- Ola 2 (T006…T012 y T030): todas tras T004 salvo T009 (tras T003), T012
  (sin dependencias; puede ir en cualquier momento) y T030 (tras T004 y
  T005).
- Ola 3: T013, T020 y T021 tras T008; T015 tras T006; T018 tras T007; T022 tras
  T011; el resto tras T004.
- T025 tras T014.
- Cierre (T026…T029) tras todas; T027 y T028 en paralelo, T029 el último.
- Cada sub-feature que toca `hermes/src/hermes/tools/_annotations.py`, la
  tabla, `hermes/src/hermes/tools/guide.py` o `hermes/CHANGELOG.md` lo hace en
  su rama de trabajo y resuelve conflictos al integrar en
  `feat/cobertura-total`; el orden de integración es el de las olas.

## Paralelismo

- Ola 0: T002 y T003.
- Ola 1: T004 y T005.
- Ola 2: T006…T012 y T030, hasta ocho a la vez.
- Ola 3: T013…T024, limitado por quién toca los mismos ficheros comunes.

## Estrategia

MVP del programa = olas 0 y 1: la 1.2.0 ya tendría las correcciones, el banco
de Core con todas las escrituras existentes ejecutadas y la cola larga
alcanzable por las genéricas (US1, US3, US5, US6, US7). Las olas siguientes
añaden las tools dedicadas por valor (US2, US4). Todo se publica junto como
1.2.0 (decisión del mantenedor).

## Fase 8: Convergencia

Converge del programa (T026, FR-098), sobre `feat/cobertura-total` con las
sub-features 009–033 integradas: 359 tools en producción (216 de la 1.1.2 y
143 nuevas). Comprobado y en verde:

- **Tabla**: 623 comandos de Core y 254 rutas del Supervisor, ninguno sin
  entrada ni sobrante (`TestDeriva`); ninguna entrada «pendiente de tool
  dedicada», «pendiente de revisión», «sin revisar» ni «provisional», y toda
  `dedicated` apunta a una tool registrada de su familia
  (`TestDedicadas.test_tool_existe_y_familia_coincide`). Nuevo:
  `tests/test_trazabilidad_008.py` (`TestTablaCerrada`) lo prohíbe en toda la
  tabla, no solo por spec.
- **Matriz de `plan.md`**: las 96 CAP del catálogo con su fila, sub-feature,
  FR, vía y test; cada tool, fichero y test citados existen (nuevo:
  `TestMatrizDeTrazabilidad`, con control negativo anotado en su docstring).
- **SC-001** (`TestDeriva`), **SC-002** (matriz y `TestMatrizDeTrazabilidad`),
  **SC-003** (`TestVerbos`, 3 excepciones justificadas), **SC-004**
  (`TestDecidir` y las genéricas con sus controles negativos), **SC-005**
  (`test_sc005_sin_las_de_la_1_2_0_queda_la_1_1_2`, con la desviación DA-12
  de spec.md), **SC-006** (`TestInventarioDeEscrituras`: 203 tools que
  modifican, todas clasificadas; de las 92 `ha_*` nuevas, todas en el banco salvo las
  4 del Marketplace no ejecutables sin catálogo) y **SC-012**
  (`TestRedaccionLineal`).
- Desviaciones aceptadas DA-01…DA-12 y cambios de comportamiento de las tools
  de la 1.1.2, en spec.md («Desviaciones aceptadas en la implementación»).

Lo que falta:

- [ ] T031 [MEDIO] Invariante de banco para las tools de LECTURA nuevas de Core: toda `ha_*` de una familia de la 1.2.0 con `readOnlyHint` ejecutada en el banco y exigida por ejecución en el job (`tests/banco/obligatorio.py`), o en una lista de no ejecutables con su motivo, como ya se hace con las escrituras en `tests/test_banco_cobertura_escrituras.py`. Hoy solo la 024 y la 029 tienen inventario de lecturas; el resto se ejecuta en `tests/banco/` sin que nada impida que deje de hacerlo per SC-006 (partial)
- [ ] T032 [MEDIO] Lista única de dudas para el final en `docs/HOJA-DE-RUTA.md`: D-01…D-10 de la 008 y las que siguen abiertas en las sub-features (por ejemplo la D-29 de la 026, bloquear `update.install` del Marketplace en automatizaciones y scripts), cada una con su spec de origen, para el PR final per FR-098 (partial)
- [ ] T033 [BAJO] `tests/test_tools_registration.py`: devolver a `_HINTS_SNAPSHOT` el código de la 1.1.2 de `ha_create_scene_from_current` (`----`; la 033 lo cambió en la propia instantánea a `-D--`) y llevar el `-D--` a `_HINTS_CAMBIADOS_A_PROPOSITO`, para que la instantánea siga siendo literalmente la 1.1.2 y el test compruebe que el cambio existe per SC-005, FR-099 (partial)
- [ ] T034 [BAJO] Generador de la tabla desde cero (`scripts/inventario/generar_tabla.py` sin tabla previa): hoy da 23 entradas «pendiente de tool dedicada» y unas 100 «provisional» que la tabla revisada ya no tiene (la regeneración en su sitio sí las conserva). Alinear `_DEDICADAS_INICIALES`/`_POR_LA_TABLA` con la tabla o escribir en la cabecera del generador que la generación desde cero no es la de cierre per FR-005, FR-098 (partial)
