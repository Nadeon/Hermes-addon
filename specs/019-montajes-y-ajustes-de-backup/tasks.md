---

description: "Tareas de la sub-feature 019 — montajes de red y ajustes de backup del Supervisor (Hermes 1.2.0)"
---

# Tareas: montajes de red y ajustes de backup del Supervisor (019)

**Entrada**: `specs/019-montajes-y-ajustes-de-backup/` (spec.md, plan.md,
research.md, data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `DummyMCP`, un
`MockHAClient` (el de `tests/test_tools_supervisor.py`, ampliado para guardar
método, ruta y `json_body` de cada llamada y devolver respuestas por método y
ruta) como **Supervisor simulado** con respuestas de la forma del Supervisor
2026.11.0, `structlog.testing.capture_logs` y el `CONFIRMATIONS_DIR` temporal
de `tests/conftest.py`. Datos ficticios (`nas.local`, `192.0.2.10`, `backups`,
`/export/media`, slugs inventados) y **centinelas** de usuario y contraseña
(`USUARIO-CENTINELA-019`, `CLAVE-CENTINELA-019`). Nada de la instalación real.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" <python del .venv del checkout principal> -m pytest -q -p no:cacheprovider`.
Línea base al especificar (2026-11-14, `feat/cobertura-total` en `cc92b4a`):
2357 passed, 65 skipped, 6 failed (los 6 conocidos de Windows);
`grep -c "spec 019" hermes/src/hermes/command_table.py` = 9. Cada tramo anota
su propia línea base al empezar y termina con exactamente esos 6 fallos en
local; la referencia es el CI de Linux.

**Requisito previo (S-01)**: la 011 y la 014 integradas (lo están en la base).
La 033 puede no estarlo: T013 dice qué hacer en cada caso. Si falta algo de la
011 o de la 014 al empezar un tramo, el agente se detiene y lo anota.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 llevar los backups a un NAS, US2 cambiar o quitar un
montaje sin romper nada a ciegas, US3 ver y ajustar montajes y backups, US4
nada de lo actual cambia.

## Tramos de implementación

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado.

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **1** — montajes (`/mounts`) | **T001–T018** | Familia `mounts` con el módulo `mounts`; `sv_list_mounts`, `sv_create_mount`, `sv_update_mount`, `sv_delete_mount`, `sv_reload_mount`, `sv_set_default_backup_mount`; credenciales que entran y no salen; token atado a argumentos y estado; 6 entradas a `dedicated`; inventario de la 033; 5 filas de la matriz; tema de guía (montajes); CHANGELOG, DOCS y README (parte) |
| **2** — ajustes de backup y `location` | **T019–T032** | `sv_get_backup_settings`, `sv_set_backup_settings`, `sv_reload_backups` (módulo `backup_settings`); `location` en `sv_create_backup_*`; 3 entradas a `dedicated` y ninguna «spec 019»; 2 filas de la matriz; guía completa; documentación completa y fila CAP-083 de la 008 |

El tramo 2 necesita el tramo 1 integrado.

---

## Tramo 1 — montajes (CAP-083, `/mounts`)

### Preparación

- [x] T001 Línea base: comprobar el requisito previo (S-01), si existe `tests/test_confirmation_args_inventory.py` (033), ejecutar la suite y anotar passed/skipped/failed y la punta; comprobar que `grep -c "spec 019" hermes/src/hermes/command_table.py` da 9
- [x] T002 [P] [US4] Tests en `tests/test_tool_families.py`: `mounts` existe, `desde="1.2.0"`, desactivable, módulos `("mounts",)`, `familia_de_modulo("mounts") == "mounts"`; en `tests/test_config_validation.py`, `tool_families_disabled: [mounts]` es válido. Después, la familia en `hermes/src/hermes/tool_families.py` con un comentario del porqué (research R-1) (FR-016)
- [x] T003 [P] Fixtures en `tests/fixtures/supervisor_montajes.py`: respuesta de `GET /mounts` del Supervisor 2026.11.0 (un CIFS de uso `backup` con `version: null`, un NFS de uso `media`, un `disk` de uso `share`, `default_backup_mount`, `state`, `user_path`); variante «Supervisor que filtrara» con `username`/`password` centinela; `GET /backups` con `location` y `locations` (backups solo en el montaje, en el montaje y en local, solo en local; 25 en el montaje para el recorte a 20); errores de montaje con los centinelas en el texto; respuestas de forma inesperada. Solo datos ficticios (FR-019; principio VIII)

### Tests de las tools de montajes (escritos antes, en rojo)

- [x] T004 [P] [US3] `TestListar` en `tests/test_tools_mounts.py` (`sv_list_mounts`): sobre `{default_backup_mount, count, items, truncated}`; cada elemento con solo las claves de la lista permitida de data-model (el `disk` con `uuid` y `filesystem`); con la variante que filtra, ni `username` ni `password` ni los centinelas en la respuesta; respuesta sin `mounts` o que no es un objeto → `error` de forma inesperada, no lista vacía; una sola llamada, `GET /mounts` (FR-001, FR-010)
- [x] T005 [P] [US1] `TestCrear` y `TestValidacion` en `tests/test_tools_mounts.py` (`sv_create_mount`): (a) cada regla de FR-007 con un valor que la incumple (nombre, `type` `bind` → `unsupported_mount_type`, `disk` sin `device` ni `uuid`, con campos de red o con credenciales, `device` fuera de `/dev/` o con `..`, `uuid` con forma inválida, `device`/`uuid` en CIFS o NFS, `usage`, `server` con `/`, espacio o salto de línea, `share` con `/`, `path` relativo, `port` 0, 70000 y `True`, `version` `3.0`, `read_only=True` con `backup`, `username` sin `password` y al revés, credenciales en NFS, `share`/`version` en NFS, `path` en CIFS, credenciales con salto de línea o iguales a `***REDACTED***`) → `invalid_argument` con la regla, **sin ninguna llamada de escritura** y sin el valor en el mensaje; (b) vista previa CIFS con credenciales: carga sin credenciales, `credentials: "set"`, `becomes_default_backup_mount` verdadero sin por defecto y falso con uno, `reloads_backups` con `backup`, la nota de que el Supervisor prueba la conexión; sin credenciales, `"none"`; NFS sin `credentials`; nombre que ya existe → error que sugiere `sv_update_mount`, sin token; la vista previa no hace ninguna llamada de escritura; vista previa y confirmación de un `disk` (decisión del supervisor: carga con `device`/`uuid`, sin `credentials`, nota de la comprobación del dispositivo); (c) confirmación: `POST /mounts` con la carga exacta (credenciales incluidas, `read_only` y `version` como el Supervisor los espera) y respuesta con el montaje leído de vuelta, sin credenciales; (d) error del Supervisor al montar → `error` redactado con `hint` de `sv_get_resolution` y el token completado como fallido; `GET /mounts` de forma inesperada en la vista previa → `error` sin token; `version="auto"` → `null` en la carga (FR-002, FR-007, FR-010)
- [x] T006 [P] [US2] `TestEditar` en `tests/test_tools_mounts.py` (`sv_update_mount`): fusión (solo `server` → `PUT /mounts/{name}` con el resto igual al actual); `changes` con de → a solo de lo que cambia; sin credenciales en CIFS → `credentials: "removed_if_present"` y `credentials_warning`, y la carga sin `username`/`password`; con las dos → `"replaced"` sin enseñarlas; cambio de `type` sin los campos del nuevo → `invalid_argument`, y con ellos, sin los del viejo en la carga; `version="auto"` → `null` en la carga; `read_only=True` sobre uno de `backup` sin cambiar el uso → `invalid_argument` (validación del resultado fundido); `remount: true`; deja de ser `backup` siendo el por defecto → `stops_being_default_backup_mount: true`; cambia el destino o el uso de uno de `backup` → `affected_backups` con `count`, `only_here`, 20 `items` y `truncated`; nombre inexistente → `mount_not_found` sin token; montaje `disk` → editable (conserva su `uuid`, no envía `filesystem`) (FR-003, FR-007)
- [x] T007 [P] [US2] `TestBorrar` en `tests/test_tools_mounts.py` (`sv_delete_mount`): vista previa de uno de `backup` que es el por defecto: `is_default_backup_mount`, `default_after: null`, `affected_backups` (cuántos, `only_here`, recorte a 20 por fecha descendente) y el `warning` con el disco local y los safety backups; de uno de `media`/`share`: el aviso de `user_path`; de uno `disk`: se puede borrar; confirmación → `DELETE /mounts/{name}` y respuesta con el por defecto leído de vuelta; nombre inexistente → `mount_not_found` sin token (FR-004)
- [x] T008 [P] [US2] [US3] `TestRecargar` y `TestPorDefecto` en `tests/test_tools_mounts.py`: `sv_reload_mount` → `POST /mounts/{name}/reload` sin token y respuesta con el montaje leído de vuelta; error → redactado con `hint`; nombre inválido sin llamada. `sv_set_default_backup_mount`: vista previa `from`/`to` y la nota; `name=None` → `{"default_backup_mount": null}`; montaje de `media` → `not_a_backup_mount` sin token; inexistente → `mount_not_found`; confirmación → `POST /mounts/options` con la carga exacta (FR-005, FR-006)
- [x] T009 [US1] [US2] `TestTokenAtado` y `TestSecretos` en `tests/test_tools_mounts.py`: (a) confirmar `sv_create_mount` con otra contraseña, otro usuario u otro servidor → no se ejecuta (ninguna llamada de escritura); (b) entre la vista previa y la confirmación cambia el montaje (otro servidor), el por defecto o aparece un backup afectado → `sv_update_mount`, `sv_create_mount`, `sv_delete_mount` y `sv_set_default_backup_mount` no ejecutan y devuelven la pista de pedir otra vista previa; (c) centinelas: en vista previa, confirmación, respuesta, error del Supervisor que los repite, todos los eventos de `capture_logs` y **todo el contenido** de los ficheros de `CONFIRMATIONS_DIR` tras la vista previa y tras la confirmación → ninguno aparece; (d) los eventos de log no llevan `server`, `share` ni `path` de los fixtures y sí `mount`, `type`, `usage`, `changed`, `credentials` (FR-008, FR-009, FR-019, FR-020)

### Implementación

- [x] T010 [US1] [US2] [US3] `hermes/src/hermes/tools/mounts.py` con las seis tools según contracts/tools.md: validadores, lista permitida + `redact_structure`, lectura del estado y de los backups afectados, huella del estado como `estado=` del token (018), `create_confirmation_token` **sin** `omitibles`, limpieza de errores (valores literales + `redact_secrets`), eventos de log de R-10, descripciones en inglés que dicen lo que hacen (también que editar sin credenciales las quita y que crear prueba la conexión). Comentarios en español con el porqué (R-4, R-5, R-6). T004–T009 en verde (FR-001…FR-010, FR-020)
- [x] T011 [US4] Registro y anotaciones: tests primero en `tests/test_tools_registration.py` (las 6 registradas con la configuración por defecto; ninguna con `mounts` desactivada; `sv_list_mounts` `readOnlyHint`; `sv_create_mount`, `sv_update_mount`, `sv_delete_mount` y `sv_set_default_backup_mount` `destructiveHint`; `sv_reload_mount` ni de solo lectura ni destructiva e idempotente; ninguna de mundo abierto; títulos «Create mount (Supervisor)»…; el invariante destructiva ⇔ token sigue en verde); después, `hermes/src/hermes/tools/__init__.py` (`_activa("mounts")`) y `_DESTRUCTIVE_EXACT` en `tools/_annotations.py` con el comentario de contracts/tools.md (FR-016, SC-001)
- [x] T012 [US4] Tabla: tests primero en `tests/test_command_table.py` (las 6 rutas `/mounts*` de data-model son `dedicated` con su tool, familia `mounts` y `cap="CAP-083"`; si la regla `test_clase_a_de_via_dedicada_pendiente_de_su_spec` aún exige `deny`, ampliarla para admitir `dedicated` con tool, como hizo la 013; si la 013 ya está integrada, no se toca) y en `tests/test_tools_generic_commands.py` (`sv_read_api("/mounts")` y `sv_call_api("POST", "/mounts", …)` → `use_dedicated_tool` con la tool y sin llamada; con `mounts` desactivada, `family_disabled`). Después, las 6 entradas a mano en `hermes/src/hermes/command_table.py` (una línea cada una, «cubierto por `<tool>`»); ejecutar `scripts/inventario/generar_tabla.py` y comprobar que la tabla no cambia (`git diff --exit-code`). `grep -c "spec 019"` = 3 (FR-015)
- [x] T013 Inventario de la 033: si `tests/test_confirmation_args_inventory.py` existe, añadir `sv_create_mount` y `sv_update_mount` (los 13 argumentos `atado`, con `device` y `uuid`), `sv_delete_mount` y `sv_set_default_backup_mount` (`name` `atado`), con un comentario que diga que la huella `_estado` también entra en el hash, y subir `test_recuento` en 4; si no existe, anotarlo en las notas del tramo para la integración con la 033 (FR-009)
- [x] T014 [P] Matriz de la 014: en `docs/HOJA-DE-RUTA.md`, filas `VM` / `pendiente` (orden alfabético) de `sv_create_mount`, `sv_delete_mount` («instantánea antes»), `sv_reload_mount`, `sv_set_default_backup_mount` y `sv_update_mount` («instantánea antes»); en `docs/BANCO-SUPERVISOR.md`, «Tools nuevas del programa», su línea con qué comprobar (vista previa sin credenciales, `ha mounts info`, log sin credenciales, backups afectados al borrar) y su tanda. `tests/test_matriz_pruebas.py` en verde (FR-021)
- [x] T015 [P] Guía: tests primero en `tests/test_tools_guide.py` (tema `mounts` con los alias `cifs`, `nfs`, `nas`, `network_storage` y `backup_settings`; nombra las 6 tools, el flujo de llevar los backups a un NAS, que las credenciales no se devuelven y que editar sin ellas las quita; las tools que nombra existen); después el tema en `hermes/src/hermes/tools/guide.py` (FR-018, parte)
- [x] T016 Control negativo del tramo 1, anotando recuentos: (a) quitar la lista permitida (devolver el montaje tal cual) → cae el de la variante que filtra; (b) pasar `omitibles=("password", "username")` → cae el del directorio de tokens; (c) quitar `password` del dict del hash → cae el de confirmar con otra contraseña; (d) quitar `estado=` → caen los de estado cambiado; (e) no limpiar los valores literales del error → cae el del error con centinelas; (f) aceptar caracteres de control en la contraseña → cae; (g) quitar `credentials_warning` → cae; (h) añadir `server` al evento de log → cae; (i) dejar `/mounts` como `deny` → caen los de la tabla y de la genérica. Restaurar y comprobar verde
- [x] T017 Documentación del tramo 1: en `## [1.2.0] — <fecha de publicación>` de `hermes/CHANGELOG.md`, bajo `### Supervisor`, el bloque «Montajes de red y ajustes de backup (019)» con las seis tools y la regla de las credenciales (quitar el «_Pendiente_» si es el primero); `hermes/DOCS.md`, la familia `mounts` en «Familias de tools»; `README.md` y `README.es.md`, `mounts` en la lista de `tool_families_disabled`; `docs/HOJA-DE-RUTA.md`, estado de la 019 «tramo 1 hecho» (FR-022, parte)
- [x] T018 Cierre del tramo 1: suite completa (los 6 fallos conocidos y ninguno más), `grep -c "spec 019"` = 3, regeneración sin cambios, revisión del diff (principio VIII: ni hostnames ni IPs reales, ni rutas `C:\`, ni identificadores de modelo), commit con los recuentos de T016, el resultado de T012 y lo de T013

---

## Tramo 2 — ajustes de backup y `location`

### Preparación

- [x] T019 Línea base del tramo 2: tramo 1 integrado, suite, `grep -c "spec 019"` = 3
- [x] T020 [P] [US4] Tests en `tests/test_tool_families.py`: `mounts` tiene los módulos `("mounts", "backup_settings")`; después, en `hermes/src/hermes/tool_families.py` (FR-016)

### Tests (escritos antes, en rojo)

- [x] T021 [P] [US3] `TestAjustes` en `tests/test_tools_backup_settings.py` (`sv_get_backup_settings`): `GET /backups/info` y `GET /mounts`; respuesta `{days_until_stale, default_backup_mount, backup_mounts: [{name, state}]}` sin la lista de backups; solo los de uso `backup`; forma inesperada en cualquiera de las dos → `error` (FR-011)
- [x] T022 [P] [US3] `TestDiasHastaViejo` en `tests/test_tools_backup_settings.py` (`sv_set_backup_settings`): `7` → `POST /backups/options` con `{"days_until_stale": 7}` y `{result, days_until_stale, previous}`; `0`, `-1`, `True`, `7.5` y `"7"` → `invalid_argument` sin llamada de escritura; error del Supervisor redactado; evento con los dos valores (FR-012, FR-020)
- [x] T023 [P] [US3] `TestReleerBackups` en `tests/test_tools_backup_settings.py` (`sv_reload_backups`): `POST /backups/reload` y después `GET /backups`; `{result: "ok", backups_count}`; error redactado (FR-013)
- [x] T024 [P] [US1] [US4] `TestUbicacionDelBackup` en `tests/test_tools_supervisor.py`: sin `location`, la carga de `sv_create_backup_full` y de `sv_create_backup_partial` es **idéntica** a la de hoy (comparar con la capturada antes del cambio) y la respuesta también; `location="nas_backups"`, `".local"` y `["nas_backups", ".local"]` → la clave en la carga tal cual; `".cloud_backup"` (sola o en la lista), `[]`, `["a", "a"]`, `"../x"` y `"con espacio"` → `invalid_argument` sin llamada; respuesta y evento con `location`; error del Supervisor (montaje que no es de backup) → redactado (FR-014, FR-017)

### Implementación

- [x] T025 [US3] `hermes/src/hermes/tools/backup_settings.py` con las tres tools según contracts/tools.md y su registro en `tools/__init__.py` (dentro de `_activa("mounts")`); tests de registro en `tests/test_tools_registration.py` (registradas por defecto, no con `mounts` desactivada; `sv_get_backup_settings` `readOnlyHint`; `sv_set_backup_settings` y `sv_reload_backups` ni de solo lectura ni destructivas e idempotentes). T021–T023 en verde (FR-011…FR-013, FR-016)
- [x] T026 [US1] [US4] `location` en `hermes/src/hermes/tools/backups.py` (validador común, clave solo si se pasa, docstring que dice que sin ella se usa el montaje por defecto y que `.cloud_backup` no se admite); en `tests/test_tools_registration.py`, la excepción anotada en `test_esquemas_de_la_1_1_2` (`location` opcional en las dos, nunca en `required`). T024 en verde (FR-014, FR-017)
- [x] T027 [US4] Tabla: tests primero en `tests/test_command_table.py` (las 3 rutas de `/backups` de data-model son `dedicated`, familia `mounts`, `cap="CAP-083"`; ninguna entrada con «spec 019») y en `tests/test_tools_generic_commands.py` (`sv_read_api("/backups/info")` → `use_dedicated_tool` con `sv_get_backup_settings`); después, las 3 entradas en `command_table.py`; regenerar sin cambios; `grep -c "spec 019"` = 0 (FR-015, SC-002)
- [x] T028 [P] Matriz de la 014: filas `VM` / `pendiente` de `sv_reload_backups` y `sv_set_backup_settings`; en `docs/BANCO-SUPERVISOR.md`, sus líneas y, en la de `sv_create_backup_full`/`sv_create_backup_partial` (tanda 1), «también con `location`». `tests/test_matriz_pruebas.py` en verde (FR-021, SC-008)
- [x] T029 [P] Guía completa: tests primero en `tests/test_tools_guide.py` (el tema `mounts` nombra las 3 tools de ajustes y `days_until_stale`; el tema `backups` menciona `location`, `.local` y que sin ella va al montaje por defecto); después `hermes/src/hermes/tools/guide.py` (FR-018)
- [x] T030 Control negativo del tramo 2, anotando recuentos: (a) añadir siempre `location` (también `None`) a la carga → cae el de identidad con la 1.1.2; (b) aceptar `.cloud_backup` → cae; (c) aceptar `True` como `days_until_stale` → cae; (d) devolver la lista de backups en `sv_get_backup_settings` → cae; (e) dejar `/backups/options` como `deny` → caen los de la tabla; (f) quitar la excepción de `location` del test de esquemas → cae. Restaurar y comprobar verde
- [x] T031 Documentación completa: bloque de la 019 en el CHANGELOG con las 9 tools y `location`; `hermes/DOCS.md` (la familia con sus 9 tools); `README.md` y `README.es.md` sincronizados; `docs/HOJA-DE-RUTA.md`, estado de la 019 «hecha; prueba en la VM pendiente»; fila CAP-083 de la matriz de `specs/008-cobertura-total/plan.md` con las tools y los ficheros de test (FR-022)
- [x] T032 Cierre del tramo 2: suite completa (los 6 fallos conocidos y ninguno más), `grep -c "spec 019"` = 0, regeneración sin cambios, revisión del diff (principio VIII), commit con los recuentos de T030

---

## Notas del tramo 1 (implementación)

- **Línea base** (T001): punta `4c7943e` (merge de `feat/cobertura-total`
  con la 009, 010, 011, 028, 014, 013 y 018): 2531 passed, 67 skipped, 6
  failed (los 6 conocidos de Windows); `grep -c "spec 019"` = 9. La 033 NO
  está integrada: no existe `tests/test_confirmation_args_inventory.py`.
- **T013 para la integración con la 033**: añadir al inventario
  `sv_create_mount` y `sv_update_mount` con sus 13 argumentos `atado`
  (`name`, `type`, `usage`, `server`, `share`, `path`, `port`, `version`,
  `read_only`, `username`, `password`, `device`, `uuid`), y
  `sv_delete_mount` y `sv_set_default_backup_mount` con `name` `atado`; el
  comentario dice que la huella del estado también ata el token (`estado=`);
  `test_recuento` sube en 4.
- **Decisiones del supervisor** (vinculantes, recogidas en spec, research,
  data-model y contrato): `disk` se crea y se edita (`device`, `uuid`);
  `compute_action_hash` pasa a HMAC-SHA256 con clave en memoria (commit
  propio, con sus tests y su control negativo en `tests/test_security.py`).
- **Desviaciones**: la huella del estado va por el `estado=` de la 018 (error
  `mount_changed`, el token no se gasta) en vez de una clave `_estado` en los
  argumentos; `server` es opcional en la firma de `sv_create_mount` (un
  `disk` no lo lleva; CIFS y NFS lo exigen igual). `tools/mounts.py` llama a
  `validate_path_segment` sobre el nombre (lo exige
  `test_every_module_that_builds_a_path_has_a_validator`). Las 5 que
  modifican van a `FUERA_DEL_BANCO` del inventario de escrituras de la 028
  (`sv_*`, Supervisor simulado).
- **T012**: las 6 rutas de `/mounts` a mano; regenerar con
  `scripts/inventario/generar_tabla.py` no cambia nada (0 nuevas, 0
  quitadas, diff solo de las 6 líneas); `grep -c "spec 019"` = 3.
- **T016, controles negativos** (`tests/test_tools_mounts.py` salvo (i)):
  (a) sin lista permitida → 8 failed; (b) `omitibles=("password",
  "username")` → 1 failed (`test_crear_y_editar_sin_centinelas_en_ningun_sitio`);
  (c) sin `password` en el hash → 3 subtests failed
  (`test_otra_contrasena_otro_usuario_otro_servidor`); (d) sin `estado=` →
  4 failed (los cuatro de estado cambiado); (e) sin limpiar los literales →
  2 failed; (f) caracteres de control admitidos → 2 subtests failed; (g)
  sin `credentials_warning` → 1 failed; (h) `server` en el log → 1 failed;
  (i) `POST /mounts` como `deny` → 4 failed (tabla, genérica y registro).
  Todo restaurado y en verde.

## Notas del tramo 2 (implementación)

- **Línea base** (T019): punta `71270b2` (tramo 1): 2595 passed, 67
  skipped, 6 failed (los 6 conocidos de Windows); `grep -c "spec 019"` = 3.
- **Duda del tramo 1 resuelta (petición del supervisor)**: el usuario CIFS
  que repite un error del Supervisor no se tapaba en las tools que no reciben
  las credenciales (`sv_reload_mount`, `sv_delete_mount`,
  `sv_set_default_backup_mount`, las lecturas, editar sin credenciales).
  `_limpiar_error` (`tools/mounts.py`) tapa ahora el usuario por su forma
  (`"username": "x"`, `username=x`, `user: x`, `domain=x`, `user x`,
  `user 'x'`) antes de `redact_secrets`; lo usan también las tres de ajustes
  de backup. Tests: `TestUsuarioEnErroresSinCredenciales`
  (`tests/test_tools_mounts.py`) y los de error de
  `tests/test_tools_backup_settings.py`; control negativo (sin las tres
  sustituciones) → 9 failed. Tapa de más a propósito (un «user» seguido de
  cualquier palabra).
- **T024/T026**: los errores de `sv_create_backup_full`/`_partial` pasan por
  `redact_secrets` (con o sin `location`); la carga y la respuesta sin
  `location` son las de la 1.1.2 (`TestUbicacionDelBackup`).
- **Desviaciones**: `sv_reload_backups`, si tras releer no puede contar los
  backups, responde `result: "ok"`, `backups_count: null` y un `warning` (la
  relectura ya se hizo) en vez de un error. Las 2 que modifican van a
  `FUERA_DEL_BANCO` (31) y el inventario de escrituras sube a 133. La huella
  del tema `backups` de la guía (`TestTemaSystemDiagnostics`) se actualiza.
  README, README.es y DOCS pasan de 237 a 240 tools.
- **T027**: 3 entradas a mano; regenerar con
  `scripts/inventario/generar_tabla.py` deja la tabla idéntica (0 nuevas, 0
  quitadas); `grep -c "spec 019"` = 0.
- **Inventario de la 033 al integrar**: ninguna de las tools de este tramo
  pide token (`sv_get_backup_settings`, `sv_set_backup_settings`,
  `sv_reload_backups`; `location` en `sv_create_backup_*`, que tampoco lo
  piden). Las filas son las del tramo 1 (`sv_create_mount` y
  `sv_update_mount` con 13 argumentos `atado`; `sv_delete_mount` y
  `sv_set_default_backup_mount` con `name` `atado`; `test_recuento` +4).
- **T030, controles negativos**: (a) `location` siempre en la carga → 2
  subtests failed (identidad con la 1.1.2); (b) aceptar `.cloud_backup` → 3
  failed; (c) aceptar `True` → 1 subtest failed; (d) devolver la lista de
  backups → 1 failed; (e) `POST /backups/options` como `deny` → 4 failed
  (tabla ×2, genérica y registro); (f) sin la excepción de `location` en el
  test de esquemas → 1 failed. Guía: sin `sv_reload_backups` en `mounts` → 1
  subtest; sin `.cloud_backup` en `backups` → 2. Todo restaurado y en verde.

## Dependencias

- Tramo 1: T001 → T002 y T003 (en paralelo) → T004…T009 (en paralelo; T009 tras T005–T008 si comparten clase) → T010 → T011 (registro: sin él, `TestDedicadas` no encuentra las tools) → T012 → T013; T014 y T015 tras T011; T016, T017 y T018 al final.
- Tramo 2 (tras el tramo 1): T019 → T020 → T021…T024 en paralelo → T025 (tras T021–T023) y T026 (tras T024) → T027 tras T025; T028 y T029 tras T025 y T026; T030, T031 y T032 al final.

## Paralelismo

- Tramo 1: T002 y T003; T004…T008 (clases distintas del mismo fichero nuevo: escribirlas una tras otra si el agente es uno solo); T014 y T015.
- Tramo 2: T021…T024; T028 y T029.

## Estrategia

MVP = tramo 1: llevar los backups a un NAS y gestionar los montajes con las
credenciales a salvo, que es donde está el riesgo y la prioridad alta de
CAP-083. El tramo 2 añade los ajustes de backup y `location`, pequeños y sin
token, y cierra la documentación. Todo sale en la 1.2.0 con el resto del
programa; la prueba en la VM queda pendiente en la matriz.

## Fase 3: Convergencia

Revisión independiente y converge (2026-11-15) sobre la punta `e96660b`.
Severidad entre corchetes. Cada hallazgo se verificó con un script fuera del
repositorio contra el código de Hermes y el del Supervisor 2026.11.0.

- [ ] T033 [MEDIO] **Se hace al integrar** (decisión del supervisor: el inventario de la 033 no está en esta rama; lo añade el agente que integre la 019). Al integrar con la 033: añadir al inventario de argumentos atados (`tests/test_confirmation_args_inventory.py`) `sv_create_mount` y `sv_update_mount` con sus 13 argumentos `atado` y `sv_delete_mount` y `sv_set_default_backup_mount` con `name` `atado`, con el comentario de la huella del estado (`estado=`) y `test_recuento` +4, como dicen las notas de T013, per FR-009 (partial)
- [x] T034 [BAJO] `security.py`, `resolve_confirmation_token`: `hmac.compare_digest(str(expected_hash), actual_hash)` lanza `TypeError` si el `action_hash` del fichero del token tiene caracteres no ASCII (fichero dañado o manipulado en /data), en vez de responder «corrupted»/«does not match»; comparar bytes (`str(expected_hash).encode("utf-8")` contra `actual_hash.encode("ascii")`), con un test, per principio III (fail-closed limpio) (contradicts)
- [x] T035 [BAJO] Honestidad del cambio a HMAC: la entrada «Tokens de confirmación con HMAC» de `hermes/CHANGELOG.md` («Nada visible cambia: un token de antes de un reinicio ya se daba por perdido») y el comentario de `_CLAVE_HASH` en `security.py` no son ciertos: en la 1.1.2 el hash era determinista y el arranque solo barre los caducados, así que un token vigente sobrevivía a un reinicio de Hermes; ahora no (falla cerrado con «lost across restart»). Decirlo así, per principio V (contradicts)
- [x] T036 [BAJO] `tools/mounts.py`, `_limpiar_error`: la sustitución literal no cubre las credenciales escapadas (una contraseña con `\` o `"` llega como `\`/`\"` en el JSON de error del Supervisor o en el `repr` de `humanize_error`), ni un usuario entre comillas con espacios (`username='ana lopez'`), `DOMINIO\usuario` o `//usuario@servidor`; sustituir también `json.dumps(s)[1:-1]` y `repr(s)[1:-1]` de cada secreto y ampliar `_USUARIO_CLAVE` a valores entre comillas con espacios, con tests de centinela, per FR-008 y FR-019 (partial)
- [x] T037 [BAJO] `sv_set_backup_settings` sin tope superior: con `days_until_stale` ≥ ~740 000 el `is_current` del Supervisor (`utcnow() - timedelta(days=N)`) lanza `OverflowError` en cada comprobación del centro de resolución (la captura, la registra como error y la manda a Sentry) y el aviso de backups viejos deja de existir sin decirlo; acotar a un máximo razonable (p. ej. 3650) y decirlo en el docstring, la guía y el error, con test, per FR-012 y principio V (partial)

Notas de la convergencia:

- T034: se comparan bytes; test `test_hash_danado_no_ascii_da_error_limpio`
  (`tests/test_security.py`): seis hashes dañados dan «does not match» y el
  token sigue `pending`. Control negativo: con dos `str`, `TypeError`.
- T035: el CHANGELOG y el comentario de `_CLAVE_HASH` dicen ahora que es un
  cambio de comportamiento intencionado y fail-closed (en la 1.1.2 un token
  vigente sobrevivía a un reinicio de Hermes; ahora no).
- T036: `_limpiar_error` tapa las formas escapadas de la contraseña conocida
  (JSON y `repr`), los valores entre comillas con espacios tras una clave de
  usuario o de contraseña, `DOMINIO\usuario`, `usuario@servidor` y
  `//usuario:clave@servidor`. Test `TestRedaccionDeFormasEscapadas`
  (`tests/test_tools_mounts.py`). Control negativo: con el anterior caen 10
  de 11 subtests y el del JSON válido.
- T037: tope de 3650 días (diez años) en `sv_set_backup_settings`, con error
  claro sin llamar al Supervisor; dicho en la descripción, la guía y el
  CHANGELOG. Test `test_tope_superior_sin_llamada`. Control negativo: sin el
  tope caen los 3 subtests.
