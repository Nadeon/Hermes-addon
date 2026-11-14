---

description: "Tareas de las pruebas de las escrituras de Core en el banco (spec 028)"
---

# Tareas: pruebas de las escrituras de Core en el banco

**Entrada**: `specs/028-pruebas-escrituras-core/` (spec.md, plan.md,
research.md, data-model.md, contracts/inventario-de-escrituras.md,
quickstart.md). Base: el banco de la 010 (`specs/010-banco-de-pruebas-core/`,
`tests/banco/`).

**Tests**: obligatorios y antes del código (principios VI y VII). Estilo: el de
`tests/banco/base_helpers.py` (un `async with` por test con el lector y Hermes
conectado; limpieza al cerrar). Datos genéricos (principio VIII). Los tests de
la suite normal corren en Windows y en Linux; los de `tests/banco/`, solo en el
job `banco de Core`.

**Cómo se ejecuta la suite en local** (Git Bash, desde la raíz del worktree):
`export MSYS_NO_PATHCONV=1` y
`HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" <venv>/Scripts/python.exe -m pytest -q -p no:cacheprovider`.
Referencia: fallan exactamente los 6 tests conocidos de Windows.

**Fallo de una tool contra HA real** (FR-007, plan §5): `@pytest.mark.xfail(strict=True, raises=<excepción>, reason="<qué responde HA>")`,
comentario `HALLAZGO`, la tool sigue en `PROBADAS_028`, nota en «Notas del
tramo» de este fichero y en el informe al supervisor. Solo un arreglo trivial
(definición en spec.md, «Clarificaciones») entra en `hermes/src/`, con test
unitario que falla sin él, control negativo y línea en «Correcciones» del
CHANGELOG.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 automatización, ejecución, eventos y Lovelace; US2
registros, integraciones y reparaciones; US3 ninguna escritura sin probar o sin
motivo; US4 un fallo contra HA real se ve.

## Tramos de implementación

Cada tramo lo hace un agente nuevo. Al terminar su tramo: suite local con
exactamente los 6 fallos conocidos; push de la rama y CI en verde
(`gh run watch`: `pytest (3.12)`, `pytest (3.13)` y `banco de Core`); un commit
propio (o varios, pero el tramo se puede revertir de una vez) con los
recuentos de los controles negativos.

| Tramo | Tareas | Tools | Resultado |
|---|---|---|---|
| **A — automatización, ejecución, eventos y Lovelace** | T001–T016 | 26 | Lector ampliado, inventario e invariante en verde (con las 27 del B pendientes), 26 tools ejecutadas en el banco |
| **B — registros, integraciones y reparaciones** | T017–T029 | 27 | `kitchen_sink` cargado, 27 tools ejecutadas, inventario sin pendientes (53 + 47 + 24 = 124), documentación final |

---

# TRAMO A — automatización, ejecución, eventos y Lovelace (T001–T016)

## Fase 1: Preparación

- [x] T001 Línea base: suite completa en local sobre la punta de `feat/028-pruebas-escrituras-core` (esperado: los 6 fallos conocidos de Windows y los del banco saltados con su motivo) y, si la rama está empujada, `gh run list --branch feat/028-pruebas-escrituras-core` con el último CI; anotar los recuentos para el commit
- [x] T002 [P] Ampliar `tests/banco/ha_config/configuration.yaml` con `automation: !include automations.yaml`, `script: !include scripts.yaml`, `scene: !include scenes.yaml` y `frontend:`, con un comentario por bloque que dice qué tools lo necesitan y que nada sale a internet; crear `tests/banco/ha_config/automations.yaml` (`[]`), `tests/banco/ha_config/scripts.yaml` (`{}`) y `tests/banco/ha_config/scenes.yaml` (`[]`), cada uno con un comentario de cabecera (FR-005, research R-3)

## Fase 2: Fundacional — lector e inventario (bloquea US1 y US2)

- [x] T003 Tests del lector en `tests/test_banco_entorno.py` (junto a los de la 010; deben fallar al principio): `Lector.comando({"type": <tipo>})` hace ida y vuelta por el eco WebSocket de `tests/banco/core_doble.py` y devuelve su `result`; un `success: false` lanza `ErrorCore` con el código; `Lector.rest("GET"|"POST"|"DELETE", "/api/eco/x", cuerpo)` llega al eco con el método, la ruta, el cuerpo JSON y el token de Core, y devuelve `(estado, cuerpo)`; `repr(lector)` sigue sin el token (FR-001 apoyo, FR-011; research R-10). Si el doble no tiene lo necesario (por ejemplo, un comando que responda error), añadir lo mínimo a `tests/banco/core_doble.py`
- [x] T004 Implementar en `tests/banco/lector.py` `comando(mensaje)` (público, sobre el `_comando` existente) y `rest(metodo, ruta, cuerpo=None)` con la sesión del lector; comentarios con el porqué; sin tocar las operaciones existentes. Pasan los tests de T003
- [x] T005 Control negativo de T003/T004: (1) `rest` sin la cabecera `Authorization` de la sesión → cae el test del token; (2) `comando` que devuelve el mensaje entero en vez de `result` → cae el de ida y vuelta. Restaurar y anotar
- [x] T006 [US3] Tests del invariante en `tests/test_banco_cobertura_escrituras.py` (suite normal; deben fallar al principio, el módulo aún no existe), los seis de [contracts/inventario-de-escrituras.md](contracts/inventario-de-escrituras.md): todas clasificadas (unión con `tests/banco/cobertura.py` de la 010, sin modificarlo), disjuntas, `FUERA_DEL_BANCO` solo `fs_*`/`sv_*`, motivos no vacíos, recuento 53 de la 028 y cada probada citada en algún `tests/banco/test_banco_escrituras_*.py`. «Modifica» = `classify(nombre).read_only_hint` falso sobre el registro de `_build_mcp(HermesConfig(call_service_auto_classify_dangerous=False), MagicMock())` (FR-003, FR-004; research R-0)
- [x] T007 [US3] Crear `tests/banco/cobertura_escrituras.py` según [data-model.md](data-model.md): `PROBADAS_028` con las 26 del tramo A, `NO_EJECUTABLES_028 = {}`, `FUERA_DEL_BANCO` con las 24 (`fs_*` y `sv_*`) y su motivo cada una, y `PENDIENTES_TRAMO_B` con las 27 del tramo B y el motivo «se ejecuta en el banco en el tramo B de la 028»; docstring con el invariante y la regla para las sub-features siguientes. Pasan los tests de T006 (el de «citada en un test» pasa cuando existan T009–T011; hasta entonces, se comprueba que cae nombrando las 26)
- [x] T008 [US3] Control negativo de T006/T007: (1) quitar `ha_fire_event` de `PROBADAS_028` → cae `test_todas_las_escrituras_clasificadas` nombrándola; (2) moverla a `FUERA_DEL_BANCO` → cae `test_fuera_del_banco_solo_fs_y_sv`; (3) vaciar el motivo de `sv_reboot_host` → cae `test_motivos_no_vacios`; (4) poner `ha_get_state` en `PROBADAS_028` → cae el primero («declarada que no modifica»). Restaurar y anotar los recuentos (FR-009)

**Punto de control**: suite normal en verde con el invariante; los tests del banco nuevos aún no existen.

## Fase 3: Historia 1 — automatización, ejecución, eventos y Lovelace (P1) 🎯 MVP

**Objetivo**: las 26 tools del tramo A ejecutadas en el banco con su efecto comprobado (tabla «Tramo A» de [data-model.md](data-model.md)).
**Prueba independiente**: el job del banco ejecuta los tres ficheros; el lector ve cada efecto.

- [x] T009 [P] [US1] `tests/banco/test_banco_escrituras_automatizacion.py` (`pytestmark = pytest.mark.banco`), 15 tools, una clase por dominio sobre un `input_boolean` creado por el lector: **automation** (`ha_create_or_update_automation` en dos pasos: tras la vista previa `GET /api/config/automation/config/<id>` da 404; tras confirmar, la configuración pedida; editar → configuración reemplazada; `ha_disable_automation` → `off`; `ha_enable_automation` → `on`; `ha_trigger_automation` en dos pasos → el `input_boolean` a `on`; `ha_reload_automations` en dos pasos → `automation.reload` exactamente una vez y la automatización sigue; `ha_delete_automation` en dos pasos → 404 y sin entidad); **script** (`ha_create_or_update_script`, `ha_run_script`, `ha_reload_scripts`, `ha_delete_script`, igual); **scene** (`ha_create_or_update_scene` con el `input_boolean` a `on`, `ha_activate_scene` con el `input_boolean` en `off` antes → `on`, `ha_create_scene_from_current` → `scene.<id>` con el `input_boolean` en `entity_id`, `ha_reload_scenes`, `ha_delete_scene`). Acciones solo inocuas (`input_boolean.turn_on`); ids `banco_<x>_<hex>`; limpieza con el lector (REST `DELETE /api/config/<dominio>/config/<id>`) al cerrar (FR-001, FR-008)
- [x] T010 [P] [US1] `tests/banco/test_banco_escrituras_servicios.py`, 4 tools: `ha_call_service` directo (`input_boolean.turn_on` → `on`) y en dos pasos con `input_boolean.reload` (vista previa: el lector no ve la llamada en el bus; confirmación: la ve exactamente una vez); `ha_call_service_response` con `schedule.get_schedule` sobre un horario creado por el lector (la respuesta trae su `entity_id` y sus franjas); `ha_fire_event` con `banco_evento_<hex>` y datos genéricos (el lector, suscrito con `eventos`, lo recibe con esos datos); `ha_cancel_wait` según research R-7 (espera de 60 s en una tarea, sondeo de `ha_list_active_waits`, cancelación, la tarea termina en menos de 10 s con `reason: cancelled`, la espera ya no figura y un evento posterior del lector no la cambia). Nunca `homeassistant.restart` ni `homeassistant.stop` (FR-001, FR-008)
- [x] T011 [P] [US1] `tests/banco/test_banco_escrituras_lovelace.py`, 7 tools: dashboard `banco-<hex>` (`ha_create_lovelace_dashboard` → en `lovelace/dashboards/list`; `ha_update_lovelace_dashboard_metadata` con `show_in_sidebar` en dos pasos → cambio en la lista; `ha_save_lovelace_dashboard` en dos pasos → `lovelace/config` con su `url_path` igual a lo guardado; `ha_delete_lovelace_dashboard` en dos pasos → fuera de la lista) y recurso `/local/banco-<hex>.js` (`ha_create_lovelace_resource`, `ha_update_lovelace_resource`, `ha_delete_lovelace_resource`, en dos pasos, comprobados en `lovelace/resources`). Nunca URLs externas; limpieza con el lector (FR-001, FR-008)
- [x] T012 [US1] Comprobar en local que la suite normal sigue con los 6 fallos conocidos, que `test_cada_probada_aparece_en_un_test_del_banco` ya pasa y que los tests nuevos del banco se saltan con su motivo (`pytest -rs`); push de la rama y `gh run watch`: los tres jobs en verde, en el log del banco los 26 casos ejecutados y ninguno saltado; anotar la duración del job (SC-001, SC-005). Si algo falla: `gh run view --log-failed`, decidir según el plan (§5 y «Tratamiento de los fallos») y repetir
- [x] T013 [US4] Por cada tool del tramo A que falle contra HA real y no tenga arreglo trivial: `xfail` estricto en su test, comentario `HALLAZGO` (qué responde HA y por qué), nota en «Notas del tramo A» abajo; si el arreglo es trivial: test unitario en `tests/` que falla sin él, arreglo en `hermes/src/hermes/tools/`, control negativo, línea en «Correcciones» de `## [1.2.0]` en `hermes/CHANGELOG.md` (crear la subsección si no existe). Si no hay ninguno, anotarlo (FR-007)
- [x] T014 [US1] Control negativo del banco en CI (research R-12): en una rama desechable (`prueba/028-control-a`) que nunca se fusiona, `ha_activate_scene` (en `hermes/src/hermes/tools/scenes.py`) manda un `entity_id` inexistente; push y `gh run watch` hasta ver en rojo el test de escenas del job `banco de Core`; borrar la rama remota y la local. Solo si el encargo no permite empujar otras ramas: commit de control en la rama de la sub-feature y `git revert` en el siguiente (desviación acotada de la comprobación de la constitución del plan). Anotar el run y el resultado
- [x] T015 Documentación parcial: `docs/HOJA-DE-RUTA.md`, fila 028 → «en curso (tramo A: automatización, ejecución, eventos y Lovelace)»; `hermes/CHANGELOG.md`, en la sección «Banco de pruebas» de `## [1.2.0]`, las 26 tools del tramo A ejecutadas contra HA Core real y los hallazgos (FR-010)
- [x] T016 Verificación y commit del tramo A: `git diff --stat <base>..HEAD -- hermes/src` vacío (o solo arreglos triviales documentados) (SC-003); suite local con los 6 fallos conocidos (SC-004); revisión del diff completo buscando datos personales, rutas locales e identificadores de modelos (FR-011); `git add` por ruta; commit con los recuentos de T005, T008 y T014 y los hallazgos

### Notas del tramo A (al implementar)

- **Línea base (T001)**: tras integrar la punta de la 010 (tramo B cerrado),
  suite local con 6 fallos (los de Windows), 1979 verdes y 37 saltados; la
  rama no estaba empujada. Al cerrar el tramo A: 6 fallos, 1989 verdes y 48
  saltados (los 11 tests nuevos del banco, con su motivo).
- **CI (T012)**: run 43637719698, los tres jobs en verde; el banco ejecuta
  31 tests y 1 `xfail` (el de la 010), 11 de ellos de la 028, ninguno
  saltado. Job `banco de Core` en 1 min 15 s (el paso de pytest, 10 s).
- **Hallazgos (T013)**: ninguno. Las 26 tools hacen contra HA Core 2026.11.1
  lo que dicen. El único rojo del primer run fue del propio test: el segundo
  `ha_cancel_wait` (ya sin espera) devuelve `{error: not_found}` como
  resultado de error de MCP, y `llamar()` lo convertía en fallo.
- **Control negativo de CI (T014)**: rama desechable `prueba/028-control-a`
  con `ha_activate_scene` mandando `scene.no_existe_control_028`; run
  43637892770 en rojo solo en `banco de Core`
  (`TestEscena.test_ciclo_completo`: el `input_boolean` no se enciende); rama
  borrada en remoto y en local.
- **Desviaciones de la tabla de data-model**:
  - `ha_trigger_automation` y `ha_run_script` piden token solo si la entidad
    está restringida (su contenido llama a la denylist). Con acciones inocuas
    (casos límite de la spec) van por el camino directo, y así se prueban.
    Corregido en la convergencia (T033): el test de `ha_call_service` en dos
    pasos usa un SERVICIO de la denylist, no una entidad restringida, así que
    no cubría este camino. Ahora lo ejecutan
    `TestAutomatizacion.test_disparar_restringida_con_token` y
    `TestScript.test_ejecutar_restringido_con_token`, con una acción
    `input_boolean.reload` (denylist, inocua) que restringe la entidad.
  - `ha_create_or_update_scene` crea una escena **nueva** sin token (lo dice
    su descripción); el test la crea directa y la edita en dos pasos.
  - `ha_create_scene_from_current` se llama sin `name`: el esquema de
    `scene.create` de Core 2026.11.1 no admite esa clave. No era una
    desviación sino un HALLAZGO (T032): con `name` la tool falla siempre. Va
    en `xfail` estricto
    (`TestEscena.test_hallazgo_escena_desde_el_estado_con_nombre`).
- **Base propia**: `tests/banco/base_escrituras.py` monta Hermes con la
  configuración que pide el test (`ha_fire_event` necesita su tipo en
  `fire_event_allowlist`, que el `hermes_conectado` de la 010 deja vacía) y
  limpiezas arbitrarias; no modifica la base de la 010.
- **Fuera de alcance, para el supervisor**: `ha_wait_for_event` (lectura, no
  es de la 028) publica `ctx` como argumento **obligatorio** en su esquema
  MCP: está anotado `Any` y no `Context`, así que FastMCP no lo inyecta. Un
  cliente tiene que mandar un `ctx` cualquiera; el test de `ha_cancel_wait`
  manda `ctx={}`.

---

# TRAMO B — registros, integraciones y reparaciones (T017–T029)

## Fase 4: Preparación del tramo B

- [x] T017 Añadir `kitchen_sink:` a `tests/banco/ha_config/configuration.yaml` con un comentario (por qué: dispositivos que se pueden borrar a mano, avisos de reparación y flujo de opciones sin hardware ni internet; research R-1). Crear `tests/banco/test_banco_escrituras_integraciones.py` con una primera clase de comprobación del entorno: el lector ve en `config_entries/get` una entrada de `kitchen_sink` en estado `loaded`, en `repairs/list_issues` avisos de dominio `kitchen_sink` y en `config/device_registry/list` dispositivos suyos además de `statistics_issues`. Push y `gh run watch` **antes** de escribir el resto: si `kitchen_sink` no carga, parar y aplicar la fila «Falla una integración de apoyo» del plan, avisando al supervisor (S-02)

## Fase 5: Historia 2 — registros, integraciones y reparaciones (P1)

**Objetivo**: las 27 tools del tramo B ejecutadas en el banco con su efecto comprobado (tabla «Tramo B» de [data-model.md](data-model.md)).
**Prueba independiente**: el job del banco ejecuta los tres ficheros; el lector ve cada efecto.

- [x] T018 [P] [US2] `tests/banco/test_banco_escrituras_registros.py`, 12 tools, una clase por registro (área, planta, etiqueta, categoría con scope `automation`): `ha_create_*` → en `config/<x>_registry/list` con los datos pedidos; `ha_update_*` en dos pasos (tras la vista previa, el nombre no ha cambiado; tras confirmar, sí); `ha_delete_*` en dos pasos → fuera de la lista. Nombres `banco_<x>_<hex>`; limpieza con el lector (`config/<x>_registry/delete`) al cerrar (FR-001, FR-008)
- [x] T019 [P] [US2] `tests/banco/test_banco_escrituras_dispositivos.py`, 6 tools: `ha_update_device` en dos pasos (`name_by_user` genérico en un dispositivo de `kitchen_sink`; se restaura al terminar); `ha_remove_device` y `ha_remove_device_from_config_entry` en dos pasos, cada uno sobre un dispositivo distinto de `kitchen_sink` (nunca `statistics_issues`), comprobando justo después de confirmar que ya no está; `ha_update_entity_registry` con `new_entity_id` en dos pasos sobre un `input_boolean` del lector (existe el nuevo y no el viejo); `ha_remove_entity_registry` en dos pasos (`config/entity_registry/get` da `not_found`); `ha_ignore_repair` en dos pasos sobre un aviso de `kitchen_sink` (`ignored: true`) y restaurado con `ignore=False` al terminar (FR-001, FR-008)
- [x] T020 [P] [US2] En `tests/banco/test_banco_escrituras_integraciones.py`, 9 tools según research R-2: ciclo de `uptime` en un solo test (`ha_start_config_entry_flow` → flujo en `config_entries/flow/progress`; `ha_abort_config_entry_flow` → ya no; nuevo flujo y `ha_continue_config_entry_flow` con `{}` → entrada `loaded`; `ha_reload_config_entry` → el estado del sensor de `uptime` cambia; `ha_disable_config_entry` en dos pasos → `disabled_by: user`; `ha_enable_config_entry` → `loaded`; `ha_delete_config_entry` en dos pasos → no existe; limpieza que borra la entrada pase lo que pase) y flujo de opciones de `kitchen_sink` (`ha_start_options_flow` → paso `options_1`; `ha_continue_options_flow` con valores genéricos → el lector abre su propio flujo de opciones por REST, ve esos valores como actuales y lo aborta). Ninguna prueba borra ni deshabilita la entrada de `kitchen_sink` (FR-001, FR-008)
- [x] T021 [US3] Cerrar el inventario: pasar las 27 del tramo B a `PROBADAS_028` en `tests/banco/cobertura_escrituras.py`, borrar `PENDIENTES_TRAMO_B` del módulo y de `tests/test_banco_cobertura_escrituras.py`; el recuento de la 028 sigue en 53 y el total en 124 (SC-002)
- [x] T022 [US3] Control negativo local de T021: quitar `ha_ignore_repair` de `PROBADAS_028` → cae nombrándola; borrar su llamada del test del banco dejándola en la lista → cae `test_cada_probada_aparece_en_un_test_del_banco`. Restaurar y anotar (FR-009)
- [x] T023 [US2] Suite local (6 fallos conocidos, banco saltado con motivo); push y `gh run watch`: los tres jobs en verde, en el log del banco los 53 casos de la 028 (y los de la 010) ejecutados y ninguno saltado; anotar la duración del job (SC-001, SC-005; si pasa de 10 minutos, anotarlo según FR-012). Si algo falla, `gh run view --log-failed` y decidir según el plan
- [x] T024 [US4] Hallazgos del tramo B como en T013 (con nota en «Notas del tramo B»); si no hay, anotarlo (FR-007)
- [x] T025 [US2] Control negativo del banco en CI (research R-12): como T014, en `prueba/028-control-b`: `ha_create_area` (en `hermes/src/hermes/tools/registry_area.py`) crea el área con el nombre cambiado; push y `gh run watch` hasta ver en rojo el test de áreas; borrar la rama (o, si el encargo no lo permite, commit de control y `git revert`). Anotar el run y el resultado

## Fase 6: Documentación y cierre

- [x] T026 [P] `docs/HOJA-DE-RUTA.md`: fila 028 → «hecha»; la frase de la cabecera sobre las 124 tools dice que las 100 `ha_*` que modifican se ejecutan en el CI contra HA Core 2026.11.1 real (47 en la 010 y 53 en la 028); lista de las 53 tools ejecutadas en el banco, lista de las 24 de fuera del banco con su motivo y los hallazgos con su estado (FR-010)
- [x] T027 [P] `hermes/CHANGELOG.md`: completar en «Banco de pruebas» de `## [1.2.0]` las 27 del tramo B y los hallazgos; `specs/008-cobertura-total/plan.md`: fila CAP-034 de la matriz, columna de test con `tests/banco/test_banco_escrituras_*.py` y `tests/test_banco_cobertura_escrituras.py` (FR-010)
- [x] T028 Verificación final: `git diff --stat <base de la 028>..HEAD -- hermes/src` vacío o solo arreglos triviales documentados (SC-003); suite local con los 6 fallos conocidos y los del banco saltados con motivo (SC-004); revisión del diff completo de la sub-feature buscando datos personales, rutas locales e identificadores de modelos (FR-011)
- [x] T029 Commit del tramo B (`git add` por ruta) con los recuentos de T022 y T025, la duración del job y los hallazgos; informe al supervisor con los hallazgos de los dos tramos

### Notas del tramo B (al implementar)

- **`kitchen_sink` (T017)**: carga sin internet. Run 43638545572, los tres
  jobs en verde; el banco pasa de 31 a 32 tests (la comprobación del
  entorno: entrada `loaded`, avisos propios y al menos dos dispositivos que
  se pueden borrar).
- **CI (T023)**: primer run del tramo completo (43638923560) en rojo solo en
  `TestConfigEntryUptime`, por el propio test: `config_entries/flow/progress`
  solo lista los flujos que **no** abrió un usuario (descubrimientos), y los
  de las tools son de origen `user`. Se comprueba por REST
  (`GET /api/config/config_entries/flow/<id>`: 200 abierto, 404 cerrado).
  Run 43639108146: los tres jobs en verde; el banco ejecuta 42 tests y 1
  `xfail` (el de la 010), ninguno saltado; job `banco de Core` en 1 min 20 s
  (el paso de pytest, 15 s). Suite local: 6 fallos (los de Windows), 1989
  verdes y 59 saltados.
- **Hallazgos (T024)**: ninguno. Las 27 tools hacen contra HA Core 2026.11.1
  lo que dicen.
- **Control negativo local (T022)**: sin `ha_ignore_repair` en
  `PROBADAS_028` caen `test_todas_las_escrituras_clasificadas` (la nombra) y
  `test_recuento_028`; sin su nombre literal en el test del banco cae
  `test_cada_probada_aparece_en_un_test_del_banco`.
- **Control negativo de CI (T025)**: rama desechable `prueba/028-control-b`
  con `ha_create_area` creando el área con `_control` al final del nombre;
  run 43639286070 en rojo en `banco de Core` (`TestArea.test_ciclo_completo`)
  y también en `pytest (3.12)` y `pytest (3.13)`
  (`test_tools_registry_area.py::TestCreateArea::test_create_basic`); rama
  borrada en remoto y en local.
- **Desviaciones de la tabla de data-model**:
  - `ha_continue_options_flow`: el lector no puede «ver los valores nuevos
    como actuales». Core no publica las opciones de una entrada
    (`as_json_fragment` no las incluye) y el formulario de `kitchen_sink` lee
    sus valores por defecto fuera de la sección `section_1` en la que los
    guarda. Se comprueba que el flujo de Hermes ya no existe (404), que
    `modified_at` de la entrada avanza (HA solo lo toca si las opciones
    cambian; el entero es aleatorio) y que el lector abre y aborta su propio
    flujo de opciones.
  - Flujo de `uptime` en curso: por REST, no por `flow/progress` (arriba).
  - `ha_ignore_repair` se prueba en los dos sentidos por Hermes (ocultar y
    volver a mostrar, ambos en dos pasos); el lector lo restaura igualmente
    al cerrar.
  - `ha_remove_device` y `ha_remove_device_from_config_entry` van en el
    mismo test para garantizar dos dispositivos distintos; se eligen sin
    hijos (`via_device_id`) para no arrastrar a otros.
- **Fuera de alcance, para el supervisor**: `ha_get_config_entry_options`
  (lectura, no es de la 028) lee `options` de `config_entries/get_single`,
  pero Core 2026.11.1 no las incluye en esa respuesta (`as_json_fragment`):
  por el código, devolvería siempre `{}`. No se ha ejecutado en el banco.

---

## Dependencias

- Tramo A: T001 → T002; T003 → T004 → T005; T006 → T007 → T008 (T006 usa la
  lista de la 010, no necesita el lector). T009, T010 y T011 tras T002, T004 y
  T007, en paralelo (ficheros distintos). T012 tras T009–T011; T013 tras T012
  (y repite T012 si cambia algo); T014 tras T012; T015 y T016 al final.
- Tramo B depende del tramo A entero (lector, inventario, configuración).
- Tramo B: T017 primero y en verde en el CI; T018, T019 y T020 en paralelo
  tras T017 (T020 añade al fichero que crea T017); T021 tras T018–T020; T022
  tras T021; T023 tras T021; T024 tras T023; T025 tras T023; T026 y T027 en
  paralelo tras T024; T028 y T029 al final.

## Paralelismo

- Tramo A: T002 ∥ T003 ∥ T006; T009 ∥ T010 ∥ T011.
- Tramo B: T018 ∥ T019 ∥ T020; T026 ∥ T027.

## Estrategia

MVP = tramo A: con él, el invariante de las 124 ya vigila que ninguna tool que
modifica quede sin probar o sin motivo, y las tools de automatización,
ejecución, eventos y Lovelace están probadas contra HA real. El tramo B cierra
FR-014 de la 008 para Core (100 de 100 `ha_*` en el banco) y deja la lista para
la matriz de la 014.

---

## Fase 7: Convergencia

Añadida por la revisión independiente y `speckit-converge` sobre la punta de la
rama (8e833d7). Severidad entre corchetes.

- [x] T030 [ALTO] Integrar la punta de la 010 (convergencia T036-T045) y adaptar la 028 a su contrato: (1) hoy el invariante cae al integrar (comprobado con `git merge-tree` y la suite sobre el árbol resultante: `test_todas_las_escrituras_clasificadas` → «sin clasificar: ['ha_reload_counters']», porque la 010 la mueve a `cobertura.FALLAN_EN_BANCO`): sumar `FALLAN_EN_BANCO` a `_listas()` de `tests/test_banco_cobertura_escrituras.py`; (2) `tests/banco/conftest.py` solo exige por ejecución `PROBADAS_EN_BANCO`: añadir `PROBADAS_028` a `tools_exigidas` (y que el mensaje de `obligatorio.py` no diga solo `PROBADAS_EN_BANCO`) y retirar o degradar a ayuda `test_cada_probada_aparece_en_un_test_del_banco`, que es la comprobación textual que la 010 sustituyó (T037 de la 010); (3) resolver los conflictos de `tests/test_banco_entorno.py`, `docs/HOJA-DE-RUTA.md` y `hermes/CHANGELOG.md`; control negativo en CI: una tool de `PROBADAS_028` sin llamar con éxito pone el job en rojo nombrándola per FR-003, SC-001, SC-002 (partial)
- [x] T031 [MEDIO] Las vistas previas sin token de las recargas (`recarga_vista_una_vez` en `tests/banco/base_escrituras.py`) y de `ha_call_service` con `input_boolean.reload` (`test_en_dos_pasos_con_la_denylist`) no prueban que la vista previa no llame: si la vista previa llamara al servicio y la confirmación no, se vería una sola llamada y el test pasaría. Arreglo mínimo: tras la vista previa, una barrera del lector en el mismo bus (por ejemplo, una llamada propia a un servicio inocuo sobre un `input_boolean` del lector, esperada en `vistos`) y comprobar entonces que `(<dominio>, "reload")` aún no está; control negativo (vista previa que llama y confirmación que no) per FR-001, US1/AC3 (partial)
- [x] T032 [MEDIO] HALLAZGO no anotado: `ha_create_scene_from_current` con `name` falla siempre contra Core 2026.11.1 (el esquema de `scene.create` no tiene `name` y rechaza claves extra), y su descripción dice que «HA decide»; además dice que una colisión de `scene_id` da error, cuando Core reemplaza en silencio una escena de `scene.create` y, con una escena de configuración, solo deja un aviso en el log y responde bien (`homeassistant/components/homeassistant/scene.py`, `create_service`). El test la llama sin `name` y lo anota como desviación: añadir un test con `name` en `xfail` estricto con su `HALLAZGO`, registrado como pide el contrato de la 010 tras T030 (`XFAIL_PERMITIDOS`), nota en «Notas» y aviso al supervisor (el arreglo cambia la firma y la descripción: no es trivial) per FR-007, US4/AC1 (missing)
- [x] T033 [MEDIO] El camino con token de `ha_trigger_automation` y `ha_run_script` (entidad restringida por `classify_saved_config`) no se ejecuta contra HA real, y la nota del tramo A dice que lo cubre `ha_call_service` «con entidad restringida», cuando ese test usa un servicio de la denylist, no una entidad restringida. Se puede probar sin riesgo: un script y una automatización creados por Hermes cuya acción es `input_boolean.reload` más `input_boolean.turn_on` del `input_boolean` del lector; vista previa con token y el `input_boolean` sigue `off`; confirmación y pasa a `on`. Corregir la nota per US1/AC2, FR-001 (partial)
- [ ] T034 [BAJO] `asyncio.sleep(1.5)` fijo en `TestConfigEntryUptime` (`tests/banco/test_banco_escrituras_integraciones.py`) contra FR-008 («sin pausas fijas») y sin anotar como desviación: quitarlo y apoyarse solo en el sondeo de `esperar_estado` (el sensor guarda `utcnow()` al crearse), o anotar la desviación con su motivo per FR-008 (contradicts)
- [ ] T035 [BAJO] `TestEntornoKitchenSink` (T017) corre DESPUÉS de los tests de dispositivos y reparaciones (orden alfabético de ficheros), así que no cumple «antes de probar ninguna tool»: si `kitchen_sink` no carga, `TestDispositivo` cae con `IndexError` y `TestReparacion` con un `StopIteration` convertido, sin el motivo. Arreglo mínimo: que los tests que dependen de `kitchen_sink` empiecen esperando la entrada `loaded` con el mismo mensaje (una ayuda común), o mover la comprobación a un fichero que se recoja antes per T017, FR-008 (partial)
- [ ] T036 [BAJO] Documentación alineada con lo comprobado: tras T030, el CHANGELOG y la HOJA-DE-RUTA dicen «las 100 `ha_*`» y «ninguna ha fallado»; con el contrato de la 010 son 99 probadas y 1 que falla (`ha_reload_counters`), más el hallazgo de T032. FR-007, US4 y el docstring de `tests/banco/cobertura_escrituras.py` siguen el contrato viejo (la tool en `xfail` sigue en las probadas). US2/AC5 y la tabla de `data-model.md` siguen pidiendo que el lector vea los valores nuevos del flujo de opciones (desviación aceptada en las notas del tramo B, sin reflejar en esos documentos) per FR-010, FR-007 (partial)
- [ ] T037 [BAJO] En `TestCancelarEspera`, el evento del lector tras cancelar no comprueba nada: `resultado` ya se había leído y la última aserción repite la anterior. Comprobar algo observable tras el evento (por ejemplo, que `ha_list_active_waits` sigue sin la espera) o quitar esa parte y su frase del docstring per FR-001 (research R-7) (partial)
