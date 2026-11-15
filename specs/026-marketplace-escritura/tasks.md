---

description: "Tareas de la sub-feature 026 — escritura en el Marketplace (Hermes 1.2.0)"
---

# Tareas: escritura en el Marketplace (026)

**Entrada**: `specs/026-marketplace-escritura/` (spec.md, plan.md,
research.md, data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `DummyMCP` y el HA
simulado de `tests/test_tools_marketplace.py` (registra `type` y carga de cada
`ws_send` y responde errores con `code`), ampliado en la fixture con
`sv_request` (método, ruta, `json_body`, `timeout_seconds`) para los backups, y
`structlog.testing.capture_logs`. Datos ficticios: `ejemplo/tarjeta`,
`ejemplo/integracion`, `ejemplo/tarjeta-critica`, ids `"123456"`, `"234567"`,
`https://usuario:centinela-026@github.com/ejemplo/tarjeta`. Nada de la
instalación real; ninguna llamada a las tools MCP de Hermes conectadas.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`.
Línea base al especificar (2026-11-15, `feat/026-marketplace-escritura` en
`f108af0`): 3955 passed, 133 skipped, 6 failed (los 6 conocidos de Windows).
Cada tramo anota su propia línea base al empezar y termina con exactamente
esos 6 fallos en local; la referencia es el CI de Linux.

**Requisito previo (S-01)**: la 011, la 028 y la 030 integradas (lo están en
`f108af0`). Si otra sub-feature se ha integrado en `feat/cobertura-total`
antes de empezar un tramo y toca los ficheros comunes (`tool_families.py`,
`command_table.py`, `tools/__init__.py`, `_annotations.py`, `guide.py`,
`cobertura_escrituras.py`, matriz, CHANGELOG), traerla primero
(`git merge --no-ff`) y anotarlo.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 catálogo y avisos, US2 código instalado, US3 nada de
lo actual cambia.

## Tramos de implementación

> **DESVIACIÓN DV-1 (spec.md, «Requisitos»; decisión del supervisor)**: las
> cuatro tools que exigen el aviso de riesgos del Marketplace aceptado por el
> usuario de Hermes (`ha_marketplace_add_repository` del tramo 1;
> `ha_marketplace_install`, `ha_marketplace_set_version` y
> `ha_marketplace_set_beta` del tramo 2) **no se implementan**, y sus cinco
> comandos (`repositories/add`, `repositories/detect`, `repository/install`,
> `repository/version`, `repository/beta`) quedan en `deny` con el motivo de
> la duda D-29. Las tareas de abajo están reescritas con ese alcance.

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado.

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **1** — catálogo y avisos | **T001–T015** | Familia `marketplace_manage`; `tools/_marketplace_write.py` (común); `ha_marketplace_acknowledge_critical`, `ha_marketplace_ignore_repository`, `ha_marketplace_remove_repository`, `ha_marketplace_refresh_repository`; 4 entradas a `dedicated` y 5 a `deny` con el motivo del aviso (DV-1); tema `marketplace_manage`; banco (reconocer ejecutado, tres no ejecutables, contrato de las cuatro cargas) y matriz; inventario de la 033; CHANGELOG, DOCS, README y SECURITY |
| **2** — desinstalar | **T016–T030** | `ha_marketplace_uninstall` con backup previo; 1 entrada a `dedicated` (ninguna «spec 026»); tema de su familia; banco y matriz; documentación final y matriz de la 008 |

El tramo 2 necesita el tramo 1 integrado.

---

## Tramo 1 — catálogo y avisos (familia `marketplace_manage`)

### Preparación

- [x] T001 Línea base: comprobar el requisito previo (S-01), ejecutar la suite y anotar passed/skipped/failed y la punta; comprobar que `grep -c "spec 026" hermes/src/hermes/command_table.py` da 10 y que la tabla regenerada no cambia antes de tocar nada
- [x] T002 [P] [US3] Tests en `tests/test_tool_families.py`: `marketplace_manage` existe, `desde="1.2.0"`, desactivable, módulos `("marketplace_manage",)`, `familia_de_modulo("marketplace_manage") == "marketplace_manage"`, distinta de `marketplace`; en `tests/test_config_validation.py`, `tool_families_disabled: [marketplace_manage]` es válido. Después, la familia en `hermes/src/hermes/tool_families.py` con un comentario del porqué (research R-3) (FR-020)

### Tests

- [x] T003 [P] [US1] Fixture `tests/fixtures/marketplace_escritura.py` (HA simulado con la forma de 2026.11.1: `repositories/list` por categoría con el `repository_summary` de HA, `repositories/removed` con una retirada normal y una crítica, `critical/list` con una sin reconocer —guardada con mayúsculas— y otra reconocida, escrituras que cambian el estado como HA, errores por `code`) y tests puros en `tests/test_marketplace_write_comun.py`: las listas cerradas y sus guardas (un sufijo fuera → `RuntimeError` sin enviar), nunca `hacs/*`, lista por categorías, cargas exactas de los cuatro comandos, validadores de `repository_id` y de `owner/repo`, traducción de códigos de HA, detalle redactado (FR-001, FR-002, FR-005, FR-006). (La URL de GitHub y `marketplace/info` ya no aplican: DV-1.)
- [x] T004 [P] [US1] Tests en `tests/test_tools_marketplace_manage.py` (`TestReconocer`, `TestIgnorar`): vista previa y confirmación con la carga exacta (reconocer envía el nombre que guarda HA, que lo compara con `==`), `not_critical`, `already_acknowledged`, `repository_not_found`, `repository_not_removed`, `critical_repository` sin token ni escritura; cambio de lo leído entre vista previa y confirmación → `ESTADO_CAMBIADO` sin enviar nada (FR-004, FR-005, FR-008, FR-009)
- [x] T005 [P] [US1] Tests (`TestQuitar`, `TestRefrescar`): quitar el personalizado no instalado; `repository_installed`, `not_custom_repository`, `repository_not_found` sin token; instalado o renombrado entre vista previa y confirmación → no se envía nada; error de HA al confirmar → token fallido; refrescar con `contacts_github` y `backup.will_create: false`, la relectura y `github_rate_limited` explicado con el token fallido; token de otro repositorio rechazado (FR-004, FR-010, FR-011)
- [x] T006 ~~Tests de `ha_marketplace_add_repository`~~ — no aplica (DV-1)
- [x] T007 [P] [US1] Tests comunes (`TestComun`): `unknown_command` → `marketplace_write_unsupported` sin `hacs/*`; `not_loaded` → `marketplace_not_loaded`; solo los comandos permitidos (nunca `hassio/`, `supervisor/`, `warning/accept`, `github/connect`); evento `marketplace_write` con `tool`, `outcome` y `category` y sin ids, nombres, URLs ni textos; URL con credenciales en un texto de terceros tapada; HA caído al leer (FR-001, FR-002, FR-006, FR-007)

### Implementación

- [x] T008 [US1] `hermes/src/hermes/tools/_marketplace_write.py` (común, sin tools) y `hermes/src/hermes/tools/marketplace_manage.py` (cuatro tools en dos pasos con `estado`, salida por `tapar_en_estructura`, `requires_ready`). Reutiliza de `tools/marketplace.py` `_trim`, `_REPOSITORY_ID_RE` y `MARKETPLACE_CATEGORIES` sin moverlos ni ampliar `_ALLOWED_SUFFIXES`. DESVIACIÓN: no usa `_list_catalog` (cae a HACS); lee por categorías solo de `marketplace/*` con su propia lista cerrada de lecturas (FR-001…FR-011)
- [x] T009 [US1] [US3] Registro en `tools/__init__.py` dentro de la comprobación de la familia; `_annotations.py`: las cuatro en `_DESTRUCTIVE_EXACT` y refrescar en `_OPEN_WORLD`. Tests en `tests/test_tools_registration.py` (`TestMarketplaceManage026`, `_HINTS_NUEVAS_1_2_0`, `_TOOLS_DE_FAMILIA_1_2_0`): anotaciones y títulos, argumentos, `ha_marketplace_xyz` sin `readOnlyHint`, las cuatro del aviso no existen, familia apagada (FR-020, FR-021)
- [x] T010 [US1] Inventario de la 033 con las cuatro (recuento 122); `test_allow_dangerous_inventario.py` en verde sin cambios (FR-024)
- [x] T011 [US1] Tabla: `tests/test_command_table.py` (`TestEntradasDeLa026` y la excepción del aviso en la regla de las filas A), `tests/test_generar_tabla.py` (`test_desde_cero_las_de_la_026`) y `tests/test_tools_generic_commands.py` (`TestMarketplaceDeLa026`); después, las cuatro a `dedicated` y las cinco del aviso a `deny` con `MOTIVO_AVISO_MARKETPLACE`, en `command_table.py` y en `_DEDICADAS_INICIALES` (`_Deny` en filas A, mismo mecanismo que la 031). Regenerada en su sitio: idéntica (`cmp`); desde cero: las nueve entradas del Marketplace iguales. `grep -c "spec 026"` da 1 (`repository/uninstall`) (FR-019)
- [x] T012 [US1] Guía: tema `marketplace_manage` (las cuatro tools, ignorar frente a reconocer, quitar solo personalizados no instalados, lo que Hermes no puede hacer y por qué), alias, línea del índice y marcador `@TEMA_MARKETPLACE@` de las instrucciones; tests en `tests/test_tools_guide.py` (`TestTemaMarketplaceManage`, huellas de `marketplace`, `security` y `workflows` intactas; el test de `app_store` que miraba «marketplace, security» pasa a «marketplace, marketplace_manage, security») (FR-022)
- [x] T013 Control negativo del tramo 1 (recuentos abajo, en las notas)
- [x] T014 [US1] Banco y matriz: `tests/banco/cobertura_026.py` (`PROBADAS_026` con reconocer, `NO_EJECUTABLES_026` con ignorar, quitar y refrescar), sumado al invariante, a `TOOLS_EXIGIDAS_DEL_JOB` y a `tests/test_banco_cobertura.py` (`TestCoberturaDeLa026`); semilla `tests/banco/ha_config/.storage/marketplace.critical` con su comentario en `configuration.yaml`; `tests/banco/test_banco_marketplace.py` (estado sin catálogo, reconocer con lector y Repairs, contrato de las cuatro cargas); filas de la matriz (reconocer `banco de Core | ok`, las tres `instalación real | pendiente` con el motivo) (FR-023)
- [x] T015 Documentación y cierre del tramo 1: CHANGELOG («Escritura en el Marketplace» y recuentos de la tabla del bloque de la 011), DOCS (familia y párrafo del Marketplace), README y README.es (326 tools, fila y familia), SECURITY, HOJA-DE-RUTA (026 «en curso» y casilla de prueba en vivo), spec.md (DV-1), plan.md (DV-1 y desviaciones) (FR-025)

### Notas del tramo 1 (al cerrar)

- Línea base (tras `git merge --no-ff feat/cobertura-total`, sin
  conflictos, punta `a8c53b1`): 4072 passed, 133 skipped, 6 failed (los 6
  conocidos de Windows). `grep -c "spec 026"` daba 10.
- Comprobado en `fuentes/core` (HA 2026.11.1): `critical/acknowledge` no usa
  `marketplace_command` (nunca `not_loaded`, no exige el aviso);
  `repository/ignore`, `repository/refresh` y `repositories/remove` usan
  `marketplace_command()` sin `requires_accepted_warning`. Ninguna de las
  cuatro exige el aviso. `repositories/detect` sí (con GitHub): pasa a
  `deny` con las demás del aviso.
- HA no comprueba que un repositorio ignorado esté retirado (solo añade su
  `full_name` a `ignored_repositories`): el rechazo `repository_not_removed`
  es de Hermes (research R-10).
- Control negativo (T013), cada uno revertido y restaurado: (a) sin la
  guarda de `_WRITE_SUFFIXES` → 6 failed (`test_guarda_de_escritura` y sus
  subtests); (e) sin `estado` al quitar → 1 failed
  (`test_cambio_entre_vista_y_confirmacion`); (f) aceptar ignorar un no
  retirado → 1 failed (`test_no_retirado`); (g) `ha_marketplace_` en
  `_READ_ONLY_PREFIXES` → 5 failed; (h) `marketplace/repository/ignore` en
  `deny` → 7 failed (tabla, generador desde cero, genérica y registro);
  (i) sin `already_acknowledged` → 2 failed; (j) enviar el nombre del cliente
  y no el guardado → 1 failed; (k) sin la rama `_Deny` de las filas A en el
  generador → 6 failed (`test_desde_cero_las_de_la_026`); (l) sin el marcador
  `@TEMA_MARKETPLACE@` → 1 failed. Los de (b), (c) y (d) eran de añadir
  repositorios: no aplican (DV-1).
- Estado del Marketplace en el banco: lo comprueba
  `TestEstadoDelMarketplace.test_sin_catalogo` (lista vacía o `not_loaded`);
  el resultado real queda en el run del CI.

---

## Tramo 2 — desinstalar

Tras la DV-1 solo queda `ha_marketplace_uninstall` (no exige el aviso).
**DECISIÓN D-2 (supervisor)**: va en la familia `marketplace_manage` (módulo
`tools/marketplace_manage.py`), no en una familia de una sola tool; la
familia `marketplace_install` no existe. Las tareas de abajo se leen así.

### Preparación

- [x] T016 Línea base del tramo 2 con el tramo 1 integrado; `grep -c "spec 026"` da 1; leer las notas del tramo 1
- [x] T017 [P] [US3] Tests de la familia (como T002) y la familia en `tool_families.py` (FR-020). Con la D-2: sin familia nueva; la descripción de `marketplace_manage` nombra desinstalar y un test comprueba que `marketplace_install` no existe

### Tests (escritos antes, en rojo)

- [x] T018 [P] [US2] Fixture: ampliar `tests/fixtures/marketplace_escritura.py` con `config_entries/get` (con y sin entradas del `domain`), `repository/uninstall` (como el manejador de HA) y un Supervisor simulado de `POST /backups/new/partial` (`{"slug"}`, error, o más lento que la espera); tests puros en `tests/test_marketplace_write_comun.py`: carga de desinstalar, `reinicio_probable` por categoría y por `config_flow`/cargada, nombre del backup `hermes_marketplace_uninstall_<AAAAMMDDTHHMMSSZ>` sin el repositorio, `uninstall` en `_WRITE_SUFFIXES` (FR-014, FR-017)
- [x] T019 [P] [US2] Tests en `tests/test_tools_marketplace_uninstall.py` (nombre por la D-2) (`TestDesinstalar`): `repository_not_found`, `repository_not_installed` y `repository_in_use` (con la pista de `ha_delete_config_entry`) sin token; vista previa con `removes` (con el recurso de Lovelace en `plugin`), `restart`, `backup` y lo de terceros; funciona sin el aviso aceptado; confirmación → primero el backup parcial (`homeassistant: true`, `homeassistant_exclude_database: true`, `background: false`, `_LONG_OP_TIMEOUT`), después `marketplace/repository/uninstall`; backup fallido o sin terminar → `backup_failed` sin comando y token fallido; `backup=false` → sin backup y la vista previa lo avisa; versión instalada cambiada entre vista previa y confirmación → token rechazado sin backup ni comando (FR-004, FR-014, FR-017; SC-005)
- [x] T020 ~~Tests de fijar versión y betas~~ — no aplica (DV-1)
- [x] T021 [P] [US2] Tests comunes de desinstalar (`TestComun`): `unknown_command` → `marketplace_write_unsupported` sin `hacs/*`; ningún `type` con `hassio/`/`supervisor/`, `warning/accept` ni `github/connect`; evento sin id, `full_name`, versión ni textos (FR-001, FR-007)
- [x] T022 ~~Textos de lectura (FR-018)~~ — no aplica (DV-1): «Hermes does not install anything» sigue siendo verdad. Lo opcional no se hace: el tema `marketplace` no cambia (su huella sigue)

### Implementación

- [x] T023 [US2] `_marketplace_write.py` (backup previo, reinicio probable, carga de desinstalar) y el módulo de la tool; registro con la familia; `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD` (FR-001…FR-007, FR-014, FR-017, FR-021)
- [x] T024 ~~Textos de lectura~~ — no aplica (DV-1)
- [x] T025 [US2] [US3] Registro, inventario 033 y tabla: `repository/uninstall` a `dedicated` en `command_table.py` y en `_DEDICADAS_INICIALES`; ninguna entrada con «spec 026»; regenerar sin cambios, en su sitio y desde cero (FR-019, FR-020, FR-021, FR-024)
- [x] T026 [US2] [US3] Guía: tema de la familia de desinstalar (con la D-2, el tema `marketplace_manage`) (el backup parcial sin base de datos y qué pasa si falla, el reinicio y que Hermes no reinicia, `repository_in_use`); índice y marcador en las instrucciones; huellas (FR-022)
- [x] T027 [US2] Banco y matriz: desinstalar a `NO_EJECUTABLES_026` (sin catálogo en el banco), contrato del banco con su carga, su fila `instalación real | pendiente` (FR-023)
- [x] T028 Control negativo del tramo 2: (a) enviar el comando aunque el backup falle → cae `backup_failed`; (e) no rechazar `repository_in_use`; (g) dejar `marketplace/repository/uninstall` como `deny`; (h) incluir el `full_name` en el nombre del backup. Restaurar y comprobar verde
- [x] T029 Documentación final: CHANGELOG, HOJA-DE-RUTA («hecha», con la viñeta de pruebas en vivo y la DV-1), DOCS y READMEs, y la fila CAP-075 de la matriz de `specs/008-cobertura-total/plan.md` con las cinco tools, la DV-1 y sus ficheros de test, sin cambiar sus columnas de sub-feature ni de vía (FR-025)
- [x] T030 Cierre del tramo 2: suite completa (los 6 fallos conocidos y ninguno más), CI del banco en verde, revisión del diff (principio VIII), commit con los recuentos de T028

### Notas del tramo 2 (al cerrar)

- Línea base (punta `5189687`, sin traer `feat/cobertura-total`): 4138
  passed, 136 skipped, 6 failed (los 6 conocidos de Windows).
  `grep -c "spec 026"` daba 1; ahora 0, también en una tabla generada desde
  cero. Regenerada en su sitio: solo cambia la línea de
  `repository/uninstall`.
- Comprobado en `fuentes/core` (HA 2026.11.1):
  `marketplace_repository_uninstall` usa `marketplace_command()` sin el
  aviso; rechaza `repository_not_installed`, `repository_busy` y
  `repository_in_use` (entradas del `domain` de una integración, también
  ignoradas: `async_entries`); con GitHub conectado refresca el repositorio
  antes de borrar (por eso `openWorldHint`). `async_post_uninstall`: la
  integración pide reiniciar si Core ya la cargó o si no tiene
  `config_flow`; la tarjeta quita su recurso de Lovelace; tema y plantilla
  recargan solos. Ninguna dice qué entidades o tarjetas usan el repositorio:
  la vista previa lo avisa (`may_break.listed_by_home_assistant: false`).
  En `fuentes/supervisor`, `_do_backup_partial` con `background: false`
  devuelve `{job_id, slug}` o un `APIError` con «check job '…'».
- DESVIACIONES: (1) D-2: misma familia, test en
  `tests/test_tools_marketplace_uninstall.py`; (2) el backup no se cifra: la
  integración de la 031 no está en esta rama, así que no se promete cifrado
  (`backup.encrypted: false`); (3) `restart.likely` es `null` cuando depende
  de si Core cargó la integración (no se adivina); (4) se mantiene
  `backup=true` por defecto con la opción `backup=false` de FR-014, atada al
  token.
- Control negativo (T028), cada uno revertido y restaurado: (a) enviar el
  comando aunque el backup falle → 3 failed; (e) no rechazar
  `repository_in_use` → 3 failed; (g) `repository/uninstall` en `deny`
  «pendiente» → 7 failed (tabla, generador desde cero, genérica y registro,
  contando subtests); (h) el `full_name` en el nombre del backup → 2 failed.

---

## Inventario de argumentos atados (referencia para T010 y T025)

- `ha_marketplace_acknowledge_critical` → `repository`
- `ha_marketplace_ignore_repository` → `repository_id`
- `ha_marketplace_remove_repository` → `repository_id`
- `ha_marketplace_refresh_repository` → `repository_id`
- `ha_marketplace_uninstall` → `repository_id`, `backup`

Todos `atado`; ninguno exento. Las que exigen el aviso de riesgos no existen
(DV-1).

---

## Dependencias y paralelismo

- T002–T007 en paralelo (ficheros distintos); T008 tras T003–T007; T009,
  T010 y T011 tras T008; T012 y T014 en paralelo tras T009.
- T017–T021 en paralelo; T023 tras T017–T021; T025 tras T023; T026 y T027
  en paralelo tras T025.
- Fuera de esta sub-feature: cualquier otra que se integre a la vez toca los
  ficheros comunes de «Requisito previo».

## Fase 3: Convergencia

Añadida por la revisión independiente y `speckit-converge` sobre la punta de la
rama (`65d1682`). Severidad entre corchetes.

- [ ] T031 [ALTO] El aviso de riesgos del Marketplace se puede saltar por una automatización creada por Hermes: `RepositoryUpdateEntity.async_install` (`components/marketplace/update.py` de HA 2026.11.1) comprueba `warning_accepted(user_id)` del contexto, pero si `user_id` es `None` se conforma con que CUALQUIER usuario lo haya aceptado (`bool(warning_acceptances)`), y toda automatización corre con `Context(parent_id=…)` sin usuario (`automation/entity.py`, `async_trigger`), también la disparada por `automation.trigger`. Con el aviso aceptado por una persona (lo normal si usa el Marketplace), `ha_create_or_update_automation` con una acción `update.install` (con `version` a cualquier ref) sobre la entidad `update` de un repositorio del Marketplace, y `ha_trigger_automation` o un disparador automático, instala código de terceros sin que el usuario de Hermes haya aceptado nada; las dos piden token, pero ninguna vista previa dice que eso salta la protección de HA (`tools/automations.py` no mira las acciones; `update.install` en la denylist solo marca la automatización como restringida). Además la guía (`tools/guide.py`, tema `marketplace_manage`, «actualizar con `update.install` choca con lo mismo») lo niega. Vía previa a la 026 (genérica de automatizaciones y scripts), DECISIÓN DEL SUPERVISOR (ampliar D-29). Arreglo mínimo propuesto: fail-closed en `ha_create_or_update_automation` y `ha_create_or_update_script`, rechazar sin token una acción `update.install` cuyo objetivo no sea una lista explícita de `entity_id` o incluya una entidad de la plataforma `marketplace` (registro), con `marketplace_warning_bypass`; corregir la frase de la guía; test con la forma real de una automatización y control negativo per FR-091 de la 008, research R-2 (contradicts)
- [ ] T032 [MEDIO] La guía (`tools/guide.py`, tema `marketplace_manage`, «LO QUE HERMES NO PUEDE HACER: … mostrar betas … HA 2026.11 exige … el aviso de riesgos») no es verdad: el interruptor «pre-release» de cada repositorio instalado (`components/marketplace/switch.py`, `RepositoryPreReleaseSwitchEntity._handle_change`) cambia `show_beta` sin mirar el aviso, y `switch.turn_on` no está en la denylist (comprobado con `service_policy.is_in_denylist`), así que `ha_call_service("switch","turn_on",…)` hace lo mismo que `marketplace/repository/beta` (deny por DV-1), sin token. No instala nada por sí solo. Arreglo mínimo: la guía dice que el comando WS exige el aviso pero el interruptor de la entidad no (y que solo cambia la versión ofrecida), o, si el supervisor lo decide, ese interruptor pasa a pedir token; test del texto per FR-022, principio V (contradicts)
- [ ] T033 [MEDIO] El tema `marketplace` de la guía y `_HOW_TO_UPDATE` (`tools/marketplace.py`, que sale en `ha_marketplace_list_updates`) siguen diciendo que, si HA responde que el aviso no está aceptado, «a person must accept it in the Marketplace UI»: por la R-2 eso nunca hace funcionar `update.install` desde Hermes (el aviso es del usuario del Supervisor, que nadie puede aceptar), y contradice el tema nuevo. Además el tema `marketplace` no remite a `marketplace_manage`, que FR-022 pide. Arreglo mínimo: los dos textos dicen que desde Hermes `update.install` de una entidad del Marketplace falla siempre con `warning_not_accepted` y que se actualiza desde la interfaz; el tema `marketplace` remite a `marketplace_manage`; huella del tema actualizada per FR-018, FR-022, principio V (partial)
- [ ] T034 [BAJO] La vista previa de `ha_marketplace_ignore_repository` dice «Home Assistant stops warning that this repository was removed», pero `marketplace_repository_ignore` (`websocket/repository.py`) no borra el aviso `removed_<id>` de Repairs ya creado: sigue hasta el próximo reinicio (no es persistente) y entonces no se vuelve a crear. Arreglo mínimo: el `effect` lo dice; test del texto per FR-009, principio V (partial)
- [ ] T035 [BAJO] La vista previa de `ha_marketplace_remove_repository` dice «It can be added again later from the Marketplace UI», pero `marketplace/repositories/add` exige además GitHub conectado (`requires_github=True`, `websocket/repositories.py`). Arreglo mínimo: añadir «(needs GitHub connected in the Marketplace)»; test del texto per FR-010, principio V (partial)
- [ ] T036 [BAJO] `ha_marketplace_uninstall`: el `estado` atado no incluye `domain` ni `local_path` (solo `full_name`, `category`, `installed_version`), así que un cambio de carpeta entre vista previa y confirmación no invalida el token y `removes.path` puede no ser lo que se borra; y con GitHub conectado HA refresca el repositorio antes de borrar (`marketplace_repository_uninstall`), lo que puede recalcular la carpeta. Arreglo mínimo: atar `domain` y `local_path`, y que `removes` diga que con GitHub conectado HA puede recalcular la ruta antes de borrar; test de token con la ruta cambiada per FR-004, FR-014 (partial)
- [ ] T037 [BAJO] Si `marketplace/repository/uninstall` agota los 120 s, la respuesta es `ha_error` con el backup, sin decir que HA puede haber desinstalado igualmente (el manejador sigue en HA). Arreglo mínimo: con `TimeoutError`, `outcome_unknown: true` y la pista de releer con `ha_marketplace_get_repository`; test per FR-006, principio V (partial)
