---

description: "Tareas de la sub-feature 034 — carpetas /addons y /share (Hermes 1.2.1)"
---

# Tareas: carpetas /addons y /share (034)

**Entrada**: `specs/034-carpetas-addons-y-share/` (spec.md, plan.md,
research.md, data-model.md, contracts/tools.md, quickstart.md). Sin spec
paraguas: cada FR se traza al encargo (D-1…D-8).

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `DummyMCP`, el
`MockHAClient` de `tests/test_tools_supervisor.py` (o la fixture
`tests/fixtures/supervisor_tienda.py` de la 030) como **Supervisor simulado**
con respuestas de la forma de 2026.11.0 (research R-4 y R-7), y
`structlog.testing.capture_logs`. Las raíces se parchean con `tmp_path`
(`folders.ADDONS_BASE`, `folders.SHARE_BASE`), ficheros REALES. Datos
ficticios: `local_ejemplo`, `ejemplo/`, `otra/`, centinelas de texto
(`centinela-clave-1`). Nada de la instalación real; ninguna llamada a las
tools MCP de Hermes conectadas.

**Independencia del sistema operativo**: rutas con `pathlib`; los puntos de
montaje con el predicado sustituible `folders.es_punto_de_montaje`; los
symlinks con un ayudante que hace `skip` si el sistema operativo no deja
crearlos (corren en el CI de Linux); las fechas con `os.utime(ns=…)`; el byte
nulo se rechaza antes de `resolve()` (R-2). Ningún test nuevo puede sumar
fallos a los 6 conocidos de Windows.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" <python del .venv del checkout principal> -m pytest -q -p no:cacheprovider`.
Línea base al especificar (2026-11-15, `feat/034-carpetas-addons-y-share` en
`37a25d4`): 5071 passed, 182 skipped, 6 failed (los 6 conocidos de Windows).
Cada tramo anota su propia línea base al empezar y termina con exactamente
esos 6 fallos en local; la referencia es el CI de Linux.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 borrar la copia de desarrollo, US2 ver qué hay,
US3 escribir, crear y mover, US4 privilegios, US5 nada de lo actual cambia.

## Tramos de implementación

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado. Cada uno necesita el anterior integrado en la rama.

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **1** — base y lectura | **T001–T016** | `fs.normalize_in_root` y `fs.blacklisted_name` (sin cambio en `/config`); `hermes/folders.py` (raíces, rutas, symlinks, huellas, recuentos, topes, montajes, índice de apps locales); montaje `addons`; familia `addons_share` (`desde="1.2.1"`); `fs_list_dir_in_folder`, `fs_stat_in_folder`, `fs_read_file_in_folder`; invariantes de familias, registro y `sobre_de_lista` |
| **2** — escritura | **T017–T028** | `fs_write_file_in_folder`, `fs_create_dir_in_folder`, `fs_move_in_folder`, `fs_delete_in_folder` en dos pasos con huella; apps instaladas; puntos de montaje; aviso de `/addons`; sin backup; matriz de la 014, `FUERA_DEL_BANCO`, inventario de la 033, procedimiento de la VM |
| **3** — privilegios | **T029–T035** | bloque `privileges` en `sv_install_addon` y `sv_rebuild_addon`, atado al token |
| **4** — guía, documentación y versión | **T036–T044** | tema `folders` y menciones en la guía; DOCS, SECURITY, READMEs (366 tools), hoja de ruta, CHANGELOG `## [1.2.1]`; versión 1.2.1 |

---

## Tramo 1 — base y lectura

### Preparación

- [x] T001 Línea base: ejecutar la suite y anotar passed/skipped/failed y la punta de la rama; comprobar que `grep -c "_in_folder" -r hermes/src` da 0

### Tests y código, en orden (rojo → verde)

- [x] T002 [P] [US5] Tests en `tests/test_tool_families.py`: `addons_share` existe, `desde="1.2.1"`, desactivable, módulos `("folders", "folders_write")`, `familia_de_modulo("folders") == "addons_share"`; `test_nombres_unicos_y_con_forma` admite `desde` en {`1.1.2`, `1.2.0`, `1.2.1`} (R-10); en `tests/test_config_validation.py`, `tool_families_disabled: [addons_share]` es válido. Después, la familia en `hermes/src/hermes/tool_families.py` con un comentario del porqué (R-3) y el docstring del módulo al día (366 tools) (FR-003)
- [x] T003 [P] [US5] Test `TestMontajes` en `tests/test_addon_manifest.py`: el `map:` de `hermes/config.yaml` tiene `addons` con `read_only: false`, `share` con `read_only: false` y `homeassistant_config` como antes, y ningún otro (D-1); `local_apps` no está. Después, el montaje en `hermes/config.yaml` con el comentario de R-1 (tipo heredado, por qué no `local_apps`, el aviso en el log del Supervisor) (FR-001)
- [x] T004 [P] [US2] Tests en `tests/test_folders.py` (`TestRaices`, `TestCarpeta`): `ADDONS_BASE`/`SHARE_BASE` salen de `HERMES_ADDONS_BASE`/`HERMES_SHARE_BASE` (recargando el módulo con el entorno parcheado) y por defecto son `/addons` y `/share`; `raiz("addons")` con la raíz parcheada; `raiz("config")`, `raiz("")`, `raiz("ADDONS")` → error `invalid_argument` sin tocar el disco; raíz inexistente o que es un fichero → `folder_unavailable` (FR-002, FR-004)
- [x] T005 [US2] `hermes/src/hermes/folders.py`: raíces, `raiz(folder)` con sus dos errores (excepciones propias con el código y el `detail` en inglés), docstring del módulo con el porqué (D-4: no se amplía `fs_*`). T004 en verde (FR-002, FR-004)
- [x] T006 [P] [US5] Tests en `tests/test_fs_security.py` (`TestNormalizeInRoot`, `TestBlacklistedName`): `normalize_in_root` con una raíz temporal y su alias da lo mismo que `normalize_path` con `CONFIG_BASE` para una batería de casos (vacía, `%2e%2e`, NFD, absoluta con alias, absoluta ajena, componente de 300 bytes, ruta de 5000 bytes, `..`), y los mensajes de `normalize_path` no cambian (compárense con los literales actuales); `blacklisted_name` da lo mismo que los pasos 1b y 2 de `check_blacklisted` para `secrets.yaml`, `secrets.yml`, `x.pem`, `mi_token.txt`, `home-assistant_v2.db`, `ok.yaml`. Después, en `hermes/src/hermes/fs.py`, las dos extracciones sin cambiar nada de `/config` (`CONFIG_BASE` se lee en cada llamada); toda la suite de `/config` en verde sin tocar sus tests (FR-005, FR-007, FR-027)
- [x] T007 [P] [US2] Tests en `tests/test_folders.py` (`TestRutas`, `TestSymlinks`): en las dos carpetas, `normalizar` rechaza con `PathTraversalError` `..`, `/etc/passwd`, `/config/x`, `/share/x` para `addons` (y al revés), byte nulo (también en Windows), componente de 300 bytes; acepta `x/y`, `/addons/x/y` para `addons`; un symlink dentro de la raíz que apunta dentro se resuelve, uno que apunta fuera → traversal; `normalizar_sin_seguir` devuelve el propio enlace (no su destino) y rechaza `.`, `..` y vacío como último nombre; `es_raiz`. Después, en `hermes/folders.py` (FR-005, FR-006)
- [x] T008 [P] [US1] Tests en `tests/test_folders.py` (`TestHuellas`, `TestRecuento`, `TestTopes`, `TestPuntosDeMontaje`): huella de fichero (SHA-256; cambia al cambiar un byte; con el umbral de 64 MiB parcheado a 10 bytes, usa tamaño, `mtime_ns` e inodo y cambia con `os.utime(ns=…)`), de symlink (su destino), de ausente y de carpeta (tamaño `None` para las carpetas de la lista, que depende del sistema de ficheros; cambia al crear, borrar, renombrar o modificar un fichero a cualquier profundidad; no sigue symlinks; es estable entre dos llamadas); `recuento` da `files`, `dirs`, `symlinks`, `total_bytes`, muestra de 20 en orden y `sample_truncated`; con el tope de entradas parcheado a 5 o el de tiempo a 0 → `ArbolDemasiadoGrande`; con `es_punto_de_montaje` sustituido para marcar `sub/nas`, el recorrido no entra y `contiene_punto_de_montaje` lo detecta. Después, en `hermes/folders.py` (R-8) (FR-012, FR-016)
- [x] T009 [P] [US1] Tests en `tests/test_folders.py` (`TestIndiceDeApps`): con una raíz de `addons` temporal que tiene `ejemplo/config.yaml` (`slug: ejemplo`), `anidada/dev/otra/config.json` (`"slug": "otra"`), `.oculta/config.yaml`, `x/rootfs/config.yaml`, `rota/config.yaml` ilegible, `sinslug/config.yml` sin `slug` y un `config.yaml` de 2 MiB: el índice da `local_ejemplo` y `local_otra` con su carpeta y su fichero, ignora los ocultos y `rootfs`, y lista como ilegibles `rota`, `sinslug` y el grande (R-4). Después, `indice_de_apps_locales()` en `hermes/folders.py` (la parte que habla con el Supervisor va en el tramo 2) (FR-019)
- [x] T010 [US5] Tests en `tests/test_tools_registration.py` (R-10): `test_sc005_sin_las_de_la_1_2_0_queda_la_1_1_2` apaga todas las familias con `desde != "1.1.2"`; nuevo `test_sin_addons_share_quedan_las_359_de_la_1_2_0` (nombres y anotaciones iguales a la lista con la familia apagada antes de la 034, guardando la lista de nombres en el propio test); `_TOOLS_DE_FAMILIA_1_2_0` (o un diccionario hermano para 1.2.1) con `addons_share` y sus tools de este tramo (FR-003, FR-031)
- [x] T011 [US2] Registro en `hermes/src/hermes/tools/__init__.py` bajo `_activa("addons_share")` (patrón de las demás, `response_max_bytes`); clase `TestFamiliaAddonsShare` en `tests/test_tools_registration.py`: las tres registradas por defecto con `readOnlyHint`, sin `destructiveHint` ni `openWorldHint`, idempotentes, títulos «List dir in folder (files)», «Stat in folder (files)», «Read file in folder (files)»; argumentos de contracts/tools.md; ninguna con la familia apagada; diccionario `_HINTS_NUEVAS_1_2_1` (código y título de cada tool nueva) hermano de `_HINTS_NUEVAS_1_2_0`, restado en `test_hints_did_not_change` y recorrido en `test_hints_y_titulos_de_las_nuevas` (R-10) (FR-003, FR-024)
- [x] T012 [P] [US2] Tests en `tests/test_tools_folders.py` (`TestListar`, `TestStat`, `TestLeer`, `TestListaNegra`, `TestSymlinks`, `TestTopeDeRespuesta`, `TestCarpetaNoDisponible`) en las dos carpetas: listar devuelve el sobre (`count`, `items`, `truncated`) con `folder` y `path` en la cabecera, tipos `file`/`dir`/`symlink`, recursivo hasta `max_depth` (tope 3), sin seguir symlinks, 500 entradas como mucho con `truncated` y `hint`; `stat` con `is_blacklisted`, `is_mount_point` y, en `addons`, `app` (`local_ejemplo`, `installed` true/false según el Supervisor simulado, `null` si falla; sin `app` en una carpeta que no es de app y nunca en `share`); leer por líneas con `offset`/`limit` (tope 5000), `next_offset` y `truncated` al pasar del tope de respuesta (con `response_max_bytes` pequeño), `total_lines: null` por encima de 4 MiB (umbral parcheado), binario → `binary: true` sin contenido, latin-1 decodificado, directorio → `is_directory`, inexistente → `not_found`; `secrets.yaml`, `x.pem`, `mi_token.txt` → `blacklisted` al leer y `is_blacklisted: true` al listar; traversal, symlink hacia fuera y byte nulo → `traversal` en las tres; raíz inexistente → `folder_unavailable`; `folder="config"` → `invalid_argument` (FR-004…FR-010, FR-025)
- [x] T013 [US2] `hermes/src/hermes/tools/folders.py`: `register(mcp, ha_client, *, response_max_bytes)` y las tres tools con docstrings en inglés según contracts/tools.md (carpeta, ruta relativa, lista negra, binarios), `sobre_de_lista`, `tam_json`, trabajo de disco en `asyncio.to_thread`, lectura en streaming, evento de log `folder_action` (tool, folder, path, result; nunca contenido). `stat` en `addons` consulta `GET /addons` solo si la ruta es la carpeta de una app del índice. T012 en verde (FR-006…FR-010, FR-025, FR-026)
- [x] T014 [P] [US5] `tests/test_sobre_de_lista.py`: `_PREFIJOS_DE_LISTA` incluye `fs_list_` y el test transversal encuentra `fs_list_dir_in_folder` con `sobre_de_lista` (las `fs_list_*` de la 1.1.2 quedan fuera por la instantánea) (FR-030)
- [x] T015 Control negativo del tramo 1, anotando recuentos: (a) en `normalize_in_root`, comparar con `CONFIG_BASE` en vez de con `root` → caen los de rutas de las carpetas; (b) quitar el rechazo explícito del byte nulo → cae en Windows el de byte nulo (en Linux sigue el de `resolve()`: anótalo); (c) seguir symlinks en el listado o en la huella → caen `TestSymlinks`; (d) no excluir `rootfs` del índice → cae `TestIndiceDeApps`; (e) quitar `blacklisted_name` de la lectura → caen `TestListaNegra`; (f) registrar las tools fuera de `_activa("addons_share")` → caen los de la familia apagada; (g) no entrar en el tope de entradas → cae `TestTopes`. Restaurar y comprobar verde
- [x] T016 Cierre del tramo 1: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII), commit con los recuentos de T015

**Notas del tramo 1** (al cerrar):

- T001: línea base en `62b2b6d` (punta de la rama con la spec): 5071 passed,
  182 skipped, 6 failed (los 6 conocidos de Windows); `_in_folder` no
  aparecía en `hermes/src`.
- T002, desviación: el docstring de `tool_families` y los recuentos de los
  README y de DOCS.md dicen 362 (no 366), porque los tests de documentación
  (`TestToolCountInDocs`, `TestFamiliasDocumentadasContraElRegistro`,
  `TestFamiliasEnLaDocumentacion`) los comparan con el registro real, que en
  este tramo tiene 359 + 3. Por la misma razón el tramo 1 ya añade la fila
  mínima de `addons_share` (3 tools, «por ahora solo lectura») en DOCS.md y
  en los dos README y la familia en sus listas; el tramo 2 sube a 7 y el
  tramo 4 escribe la documentación completa.
- T002, desviación: `tools/folders_write.py` existe ya, sin tools, para que la
  familia nombre sus dos módulos (`test_cada_familia_nombra_modulos_que_existen`).
- T004: las raíces del entorno se comprueban importando `hermes.folders` en un
  subproceso, no recargando el módulo (recargarlo cambiaría las clases de
  error que ya tienen importadas otros tests).
- T006: además de `normalize_in_root` y `blacklisted_name`, `fs.py` expone sus
  dos mitades, `prepare_in_root` (pasos 0-4, sin disco) y `resolve_in_root`
  (pasos 5-7), para que `folders.normalizar_sin_seguir` no decodifique dos
  veces. Ningún test de `/config` cambia.
- T008, desviación del data-model: en la lista canónica las carpetas van sin
  tamaño NI fecha (`[ruta, "dir", null, null]`). La fecha de una carpeta se vio
  cambiar entre dos recorridos seguidos en Windows (un token que no casaría
  nunca) y no aporta nada: solo cambia cuando cambian sus entradas, que ya
  están en la lista. Los puntos de montaje salen como `[ruta, "mount", null,
  null]`. En el recorrido, `st_dev` se lee con `os.lstat` y no del
  `DirEntry` (en Windows lo trae a 0).
- T009: `config.json` se lee con `json` y el resto con `yaml.safe_load`, como
  `read_json_or_yaml_file` del Supervisor; un `config.*` que es un symlink no
  se sigue y cuenta como ilegible; `slug` tiene que ser texto.
- T010, desviación: la lista de nombres de la 1.2.0 está en
  `tests/fixtures/tools_1_2_0.json` ({nombre: hints}, generada del registro de
  `main` en `37a25d4`), no en el propio test: son 359 nombres, como la
  instantánea `esquemas_1_1_2.json`.
- T013: las tres devuelven dict. Ninguna f-string empieza por `/` (el
  inventario de `test_security_regressions` las toma por rutas de API).
- T015, controles negativos (recuentos de tests que caen):
  (a) `relative_to(CONFIG_BASE)` en `resolve_in_root` → 8 (6 de `TestRutas`
  y 2 de `TestNormalizeInRoot`); (b) sin el rechazo explícito del byte nulo →
  20 en Windows (los de byte nulo de `test_folders` y `test_tools_folders`; en
  Linux lo sigue rechazando `resolve()`); (c) seguir symlinks en el recorrido
  o en el listado → 0 en Windows (los tests de symlinks se saltan) y comprobado
  en el CI de Linux con una rama desechable, ya borrada: 4 caen en
  pytest 3.12 y 3.13 (`test_carpeta_no_sigue_symlinks`,
  `test_cuenta_symlinks_sin_seguirlos` y `test_listar_no_sigue` en las dos
  carpetas); (d) sin excluir
  `rootfs` → 1 (`test_indice`); (e) sin `blacklisted_name` en la lectura → 2
  (`test_leer_se_rechaza` en las dos carpetas); (f) registro fuera de
  `_activa("addons_share")` → 7 de `test_tools_registration`; (g) sin el tope
  de entradas → 1 (`test_tope_de_entradas`). Además: sin el montaje `addons`
  → 2 de `TestMontajes`; sin `fs_list_` en los prefijos → 1
  (`test_cubre_las_fs_list_nuevas`); `folders` fuera de la familia → 2 de
  `test_tool_families`.

---

## Tramo 2 — escritura

### Preparación

- [x] T017 Línea base del tramo 2 con el tramo 1 integrado; comprobar que las tres de lectura están registradas y que `FUERA_DEL_BANCO` tiene 51 entradas

### Tests (escritos antes, en rojo)

- [x] T018 [P] [US1] [US3] Tests comunes en `tests/test_tools_folders_write.py` (`TestTokenYEstado`, `TestAvisoAddons`, `TestSinBackup`, `TestRecompruebaAlConfirmar`) para las cuatro tools, en las dos carpetas: sin token, vista previa y token, y el disco NO cambia; con token y los mismos argumentos, hace lo previsualizado; otro `folder`, otra ruta, otro `content` u otro `recursive` → «does not match» sin efecto; cambiar el objetivo entre medias (crear, modificar con `os.utime(ns=…)`, borrar un fichero dentro de la carpeta) → `ESTADO_CAMBIADO` con `preview_outdated: true` y sin efecto; en `addons`, `warning` de `/addons` en toda vista previa, nunca en `share`; `backup: null`, `reversible` (true solo al crear carpeta) y `backup_hint` con `addons/local` o `share` exactos; el token de una tool no vale en otra (FR-011, FR-012, FR-017, FR-018, FR-020)
- [x] T019 [P] [US3] Tests en `tests/test_tools_folders_write.py` (`TestEscribir`): fichero nuevo (crea padres) y existente (vista previa con `exists`, tamaños y huellas cortas de 12 hex, `is_blacklisted`); confirmar sin `content` (`omit_on_confirm`) escribe lo previsualizado; `content` distinto al confirmar → no casa; directorio → `is_directory` sin token; escritura atómica (`safe_write_file`: conserva CRLF y BOM de un fichero existente); `content` con `{"a": 1}` llega como texto; un fichero de la lista negra se escribe con token y su contenido no sale en la vista previa (FR-013, FR-007)
- [x] T020 [P] [US3] Tests en `tests/test_tools_folders_write.py` (`TestCrearCarpeta`): crea con padres (`creates_parents`), `already_exists` sin token si hay fichero o carpeta, la ruta raíz → `already_exists` o `root_protected` sin token (FR-014)
- [x] T021 [P] [US3] Tests en `tests/test_tools_folders_write.py` (`TestMover`): fichero, carpeta (con `contents`) y symlink (se mueve el enlace, el destino intacto); `not_found`, `destination_exists`, `destination_parent_missing`, `invalid_destination` (`a` → `a/b`), `root_protected` (origen o destino raíz), `mount_point` (origen que es o contiene un montaje, con el predicado sustituido), todos sin token; cambiar origen o destino entre medias → `ESTADO_CAMBIADO` (FR-015, FR-016)
- [x] T022 [P] [US1] Tests en `tests/test_tools_folders_write.py` (`TestBorrar`, `TestPuntosDeMontaje`): fichero, symlink (se borra el enlace, nunca su destino, también si apunta fuera) y carpeta vacía sin `recursive`; carpeta no vacía sin `recursive` → `directory_not_empty` sin token; con `recursive`, vista previa con `files`, `dirs`, `symlinks`, `total_bytes`, muestra de 20 y `sample_truncated` (con 25 ficheros), y la confirmación lo borra todo y lo cuenta; raíz (`""`, `.`, `/addons`, `/share`) → `root_protected`; punto de montaje o carpeta que lo contiene → `mount_point`; árbol por encima del tope → `too_large_to_preview`; `rmtree` que falla a medias (simulado con `onexc`) → `partial: true` con lo que queda y token completado como fallido; la vista previa cabe en `response_max_bytes` pequeño (FR-016, FR-017, FR-025)
- [x] T023 [P] [US1] Tests en `tests/test_tools_folders_write.py` (`TestAppsInstaladas`) con el Supervisor simulado (`GET /addons` → `{"addons": [{"slug": "local_ejemplo", …}]}`): borrar o mover `ejemplo`, una carpeta que la contiene o su `config.yaml` → `installed_app` con slug y pista, sin token; borrar `ejemplo/Dockerfile` → token con `inside_installed_app`; `local_ejemplo` no instalada → token; Supervisor caído y `config.*` en la ruta → `installed_check_failed`; caído y sin `config.*` → token; huérfana instalada (`local_perdida` sin `config.*`) y `rota/config.yaml` ilegible en la ruta → `installed_check_inconclusive`; sin huérfanas, la ilegible no bloquea; escribir `ejemplo/config.yaml` con otro `slug` (o ilegible) → `installed_app`, con el mismo `slug` → token con aviso; con el Supervisor caído, escribir un `config.yaml` → `installed_check_failed` y escribir `ejemplo/Dockerfile` → token con `installed_check: "failed"`; la app se instala entre la vista previa y la confirmación → la confirmación se rechaza sin efecto; en `share` no se consulta al Supervisor (cero llamadas) (FR-019, FR-017)
- [x] T024 [P] [US1] Tests del log en `tests/test_tools_folders_write.py` (`TestLog`) con `capture_logs`: un evento `folder_action` por llamada con `tool`, `folder`, `path` y `result` (`preview`, `ok`, `rejected:<código>`); nunca el contenido, una huella completa ni un centinela del contenido (FR-026)

### Implementación

- [x] T025 [US1] [US3] `hermes/folders.py` (`async comprobar_apps_instaladas`, textos comunes de la vista previa) y `hermes/src/hermes/tools/folders_write.py`: `register(mcp, ha_client, *, response_max_bytes)` y las cuatro tools con docstrings en inglés según contracts/tools.md (dos pasos, carpeta, sin backup, rechazos); `create_confirmation_token(…, estado=…)` y `resolve_confirmation_token(…, estado=huella_actual)`; `content` omitible y anotado `str`; todas las comprobaciones repetidas al confirmar y `complete_confirmation_token` en cada salida; trabajo de disco en `asyncio.to_thread`. Registro en `tools/__init__.py` (misma familia). `tools/_annotations.py`: `fs_write_file_in_folder`, `fs_create_dir_in_folder` y `fs_move_in_folder` en `_DESTRUCTIVE_EXACT` con su comentario. Tests de registro en `TestFamiliaAddonsShare` (las cuatro con `destructiveHint`, idempotentes, sin `openWorldHint`, con `confirmation_token`) y sus entradas en `_HINTS_NUEVAS_1_2_1` y el invariante «pide token ⇔ destructiva» en verde. Inventario de la 033 (`tests/test_confirmation_args_inventory.py`): sus cuatro filas según data-model (todo atado), los recuentos 145 → 149 y una línea de recuento en el docstring. T018–T024 en verde (FR-011…FR-020, FR-024, FR-029)
- [x] T026 [US5] Matriz y banco: en `tests/banco/cobertura_escrituras.py`, un motivo `_CARPETAS` («ficheros de /addons y /share: no hablan con Core; se prueban con ficheros reales en la suite normal y en la VM de la 014») y las cuatro en `FUERA_DEL_BANCO`; `test_recuento_028` 51 → 55 con su porqué; sus filas `VM` / `pendiente` en la matriz de `docs/HOJA-DE-RUTA.md` (orden alfabético); sus líneas en «Tandas de pruebas» de `docs/BANCO-SUPERVISOR.md` (carpeta de prueba en `/share`, app local de prueba en `/addons`, borrar una instalada y luego desinstalada). `tests/test_matriz_pruebas.py` y `tests/test_banco_cobertura_escrituras.py` en verde (FR-028, FR-033)
- [x] T027 Control negativo del tramo 2, anotando recuentos: (a) quitar `estado` del token de borrar → caen los de cambio entre vista previa y confirmación; (b) no repetir la comprobación de apps al confirmar → cae el de «se instala entre medias»; (c) emitir token con Supervisor caído y `config.*` → cae `installed_check_failed`; (d) usar `normalizar` (que sigue el symlink) al borrar → cae el del symlink que apunta fuera (en Linux); (e) no comprobar puntos de montaje → caen `TestPuntosDeMontaje`; (f) permitir la raíz → caen los de `root_protected`; (g) quitar el aviso de `/addons` → cae `TestAvisoAddons`; (h) quitar una de las cuatro filas de la 033 → cae el inventario nombrándola. Restaurar y comprobar verde
- [x] T028 Cierre del tramo 2: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII), commit con los recuentos de T027

**Notas del tramo 2** (al cerrar):

- T017: línea base en `1a2759d` (punta del tramo 1): 5258 passed, 198
  skipped, 6 failed (los 6 conocidos de Windows); las tres de lectura
  registradas y `FUERA_DEL_BANCO` con 51.
- T018–T024: `tests/test_tools_folders_write.py` (223 tests, 18 saltados en
  Windows por los symlinks y por el de CRLF y BOM). `safe_write_file` abre el
  temporal sin `O_BINARY` y en Windows escribe `\r\n` por `\n` (es el fallo
  conocido `test_preserves_lf_line_endings`): los tests comparan lo escrito
  deshaciendo eso solo en Windows (`_leido`) y el de CRLF y BOM se salta en
  Windows; en el CI de Linux comparan byte a byte.
- T025, orden al confirmar: primero el token con su `estado` (un cambio en
  el objetivo es siempre `preview_outdated`, sin gastar el token) y DESPUÉS
  todas las comprobaciones (raíz, montajes, padre del destino, apps
  instaladas); si alguna ya no se cumple, el token se completa con error.
- T025: `hermes/folders.py` gana `inspeccionar` (huella, recuento y montajes
  en UN recorrido), `slug_de_texto`, `es_config_candidato`,
  `apps_instaladas` (movida desde `tools/folders.py`), `evaluar_apps` (sin
  E/S, las reglas de FR-019), `comprobar_apps_instaladas` y los textos
  comunes (`AVISO_ADDONS`, `textos_de_vista_previa`). En `addons` se
  pregunta al Supervisor en TODA vista previa y confirmación de las cuatro
  (así `installed_check: "failed"` sale siempre que no responde); en
  `share`, nunca.
- T025, desviación menor: crear carpeta sobre la raíz responde
  `already_exists` (T020 admitía las dos). Un symlink que apunta a la raíz
  se puede borrar o mover como enlace: solo es `root_protected` la ruta
  cuyo último nombre es vacío, `.` o `..` y resuelve a la raíz.
- T025: documentación con el recuento real (366) y la fila de
  `addons_share` con 7 en DOCS.md y los dos README, porque
  `TestToolCountInDocs` y `TestFamiliasDocumentadasContraElRegistro` lo
  exigen; el texto completo es del tramo 4.
- T026: además de `test_recuento_028` (51 → 55),
  `test_todas_las_escrituras_clasificadas` pasa de 203 a 207.
- T027, controles negativos (recuentos de tests que caen): (a) sin `estado`
  en el token de borrar → 9 (los 8 de `TestCambioEntreMedias::test_borrar` y
  `test_estado_cambiado_queda_en_el_log`); (b) sin repetir la comprobación
  de apps al confirmar el borrado → 2 (`test_se_instala_entre_medias` de
  borrar y `test_supervisor_cae_entre_medias`); (c) token con el Supervisor
  caído y un `config.*` → 3 (`test_supervisor_caido_con_config` ×2 y
  `test_supervisor_cae_entre_medias`); (d) borrar y mover con `normalizar`
  (sigue el symlink) → 0 en Windows (se saltan) y comprobado en el CI de
  Linux con una rama desechable, ya borrada (ver el commit); (e) sin
  comprobar puntos de montaje → 6 (`TestPuntosDeMontaje::test_borrar` ×4 y
  `TestMover::test_rechazos_sin_token` ×2); (f) admitiendo la raíz → 17 (14
  de `TestBorrar::test_raiz`, 2 de `TestMover::test_rechazos_sin_token` y el
  de `TestLog`); (g) sin el aviso de `/addons` → 4 (`TestAvisoAddons`);
  (h) sin la fila de `fs_move_in_folder` en la 033 → 3, nombrándola.

---

## Tramo 3 — privilegios en instalar y reconstruir

### Preparación

- [ ] T029 Línea base del tramo 3 con el tramo 2 integrado; localizar en `tests/test_tools_addons_tienda.py` y `tests/test_tools_store_apps.py` los simulados de confirmación de `sv_install_addon` y `sv_rebuild_addon` que tendrán que leer otra vez la ficha (R-7)

### Tests (escritos antes, en rojo)

- [ ] T030 [P] [US4] Tests de la función pura en `tests/test_tools_privilegios.py` (`TestBloque`): con fichas de la forma de 2026.11.0 (todos los campos de `api/store.py` extendido, más `long_description` y otros que no son privilegios), `privilegios_de` elige exactamente los campos de R-7 (nunca `long_description`, `options` ni `schema`); con `/addons/{slug}/info` añade los suyos en `installed`; `elevated` según la regla fija (un caso por regla: `full_access`, `docker_api`, `host_network`, `host_pid`, `host_ipc`, `host_uts`, `host_dbus`, `kernel_modules`, `udev`, `privileged` no vacía, `devices` no vacía, `hassio_role` `manager`/`admin`, `apparmor: false`, `map` con escritura) y vacía para una app sin nada; `declared_in_folder` desde un `config.yaml` de app local con `map`, `privileged`, `devices` y `ports`, con la nota de la recarga; un centinela en `hassio_role` o en una ruta de `devices` sale redactado (FR-021, FR-022, FR-023)
- [ ] T031 [P] [US4] Tests en `tests/test_tools_privilegios.py` (`TestInstalar`): la vista previa de `sv_install_addon` trae `privileges.store` de la ficha (sin llamadas nuevas al Supervisor) y, para `local_ejemplo` con `ejemplo/config.yaml` en la raíz temporal, `declared_in_folder`; app de la tienda no local → sin `declared_in_folder`; ficha ilegible → `privileges: null` y `privileges_unavailable`, y el token sale como hoy; los rechazos sin token de la 030 (`addon_not_found`, `already_installed`, `addon_not_available`) no cambian (FR-021)
- [ ] T032 [P] [US4] Tests en `tests/test_tools_privilegios.py` (`TestEstadoDelToken`): `sv_install_addon` con la ficha cambiada entre vista previa y confirmación (`full_access` false → true) → `preview_outdated` (la pista nombra la versión o los privilegios) y sin `POST`; con el `config.yaml` local cambiado (`map` nuevo) → igual; con la versión cambiada → el rechazo de la 030 de siempre; sin cambios → la misma petición que en la 1.1.2 (FR-023)
- [ ] T033 [P] [US4] Tests en `tests/test_tools_privilegios.py` (`TestReconstruir`): la vista previa de `sv_rebuild_addon` trae `store` (lo que se aplicará), `installed` (lo actual) y, para `local_*`, `declared_in_folder`; un cambio en cualquiera de ellos antes de confirmar → `preview_outdated` sin `POST /addons/{slug}/rebuild`; sin cambios, la misma petición de la 030; los rechazos sin token de la 030 no cambian (FR-022, FR-023)

### Implementación

- [ ] T034 [US4] `hermes/src/hermes/tools/_store.py` (`privilegios_de`, `declarado_en_carpeta` con el índice de `hermes/folders.py`); `hermes/src/hermes/tools/addons.py` (`_vista_previa_de_instalar` añade `privileges`; `_token_con_version` ata `{"version_latest", "privileges"}` y relee la ficha y el `config.*` al confirmar; la pista del rechazo nombra las dos causas); `hermes/src/hermes/tools/store_apps.py` (vista previa con las tres fuentes; confirmación con `resolve_confirmation_token(…, estado=…)` y `preview_outdated`). Descripciones de las dos tools al día (enseñan los privilegios y se cancelan si cambian). Ajustar los simulados de confirmación de T029 sin cambiar aserciones de comportamiento. Los esquemas no cambian (`test_esquemas_de_la_1_1_2` en verde sin tocarlo); el inventario de la 033 tampoco (mismos argumentos; anotar en su docstring que el estado de las dos crece). T030–T033 en verde (FR-021…FR-023)
- [ ] T035 Control negativo y cierre del tramo 3: (a) quitar `privileges` del estado de instalar → cae el de `full_access` cambiado; (b) lo mismo en reconstruir → cae su caso; (c) devolver la ficha entera en `store` → cae el de campos exactos; (d) no redactar los textos → cae el del centinela; (e) mirar `local_*` en `share` o no mirar el índice → cae `declared_in_folder`. Restaurar; suite completa (los 6 fallos y ninguno más), revisión del diff (principio VIII), commit con los recuentos

---

## Tramo 4 — guía, documentación y versión

- [ ] T036 [US5] Versión 1.2.1: tests en `tests/test_addon_manifest.py` (la entrada que se comprueba es la de `__version__`; `SECCIONES_1_2_1` sustituye a `SECCIONES_1_2_0` en `test_la_entrada_tiene_las_secciones_del_programa`, con secciones `### Carpetas /addons y /share`, `### Privilegios al instalar y reconstruir` y `### Pruebas`, y el comentario de por qué); después `hermes/config.yaml` (`version: "1.2.1"`), `hermes/src/hermes/__init__.py`, `HA_CORE_LAST_TESTED_IN_HERMES` en `config.py` y la entrada `## [1.2.1] — <fecha de publicación>` encima de la 1.2.0 en `hermes/CHANGELOG.md` (las siete tools y la familia, el montaje nuevo y su aviso en el log del Supervisor, sin backup automático, apps instaladas protegidas, privilegios en instalar y reconstruir, invariantes, prueba en vivo pendiente) (FR-034, FR-033)
- [ ] T037 [P] [US2] Guía, tests en `tests/test_tools_guide.py` (`TestTemaFolders`): tema `folders` que nombra las siete tools, el argumento `folder`, los dos pasos con huella, que no hay backup y cómo hacerlo, el aviso de `/addons`, que no se borra ni mueve una app instalada (desinstalar antes), la lista negra, los puntos de montaje de `/share`, que una carpeta en la que otra app está escribiendo nunca casa la huella (parar antes esa app); alias `addons`, `share`, `local_apps`, `carpetas`; el índice lo nombra; con `addons_share` apagada no aparece ni en el índice ni en las instrucciones; las instrucciones dicen `fs_` (ficheros de /config, /addons y /share) solo con la familia activa (y el texto de antes con ella apagada); el tema `filesystem` remite a `folders`; `supervisor` y `app_store` nombran `privileges`; `test_no_nombra_tools_que_no_existen` en verde; huellas de `filesystem`, `supervisor` y `app_store` recalculadas y las demás iguales (FR-032)
- [ ] T038 [US2] `hermes/src/hermes/tools/guide.py`: tema `folders` en `_TEMAS` (familia `addons_share`), alias, cabecera condicional y menciones. T037 en verde (FR-032)
- [ ] T039 [P] `hermes/DOCS.md`: recuento (366), la familia `addons_share` en la lista de `tool_families_disabled`, el montaje nuevo (`addons`, con escritura: qué permite, que el Supervisor lo da por heredado y lo avisa en su log, y que se puede apagar la familia) y el apartado de uso de las dos carpetas (FR-033)
- [ ] T040 [P] `SECURITY.md`: superficie nueva en el modelo de seguridad (escritura en `/addons`, código que el Supervisor construye y ejecuta; `/share` y los NAS montados; dos pasos con huella; apps instaladas protegidas; sin backup automático; privilegios en instalar y reconstruir como salvaguarda frente a una app local maliciosa; la lista negra por nombre y que el resto del contenido sale sin redactar, como en `/config`) (FR-033)
- [ ] T041 [P] `README.md` y `README.es.md` sincronizados: 366 tools en la entradilla y en el título de la sección, fila «/addons and /share» / «/addons y /share» (7, familia `addons_share`, nueva en 1.2.1), la familia en las dos listas de familias y en la fila de `tool_families_disabled` (FR-033)
- [ ] T042 [P] `docs/HOJA-DE-RUTA.md`: sección «Hecho en 1.2.1 — carpetas /addons y /share (spec 034)» en «Plan por versiones»; casillas en «Pruebas manuales pendientes» (las cuatro que modifican en la VM y después en una instalación real; borrar una app local instalada; el aviso del tipo heredado en el log del Supervisor; los privilegios en `sv_install_addon` de una app local), y la duda de pasar a `local_apps` en «1.3.0 y posteriores»; `tests/test_matriz_pruebas.py` en verde (FR-033)
- [ ] T043 Control negativo del tramo 4: (a) dejar `version` en 1.2.0 en `config.yaml` → cae la coherencia de versiones; (b) quitar una sección de `SECCIONES_1_2_1` del CHANGELOG → cae su test; (c) registrar el tema `folders` sin familia → caen los de la familia apagada; (d) no cambiar la cabecera → cae el de `fs_`. Restaurar y comprobar verde
- [ ] T044 Cierre del tramo 4: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff completo de la rama (principio VIII: nada de hostnames, IPs, slugs de una instalación, rutas `C:\`), `README.md` y `README.es.md` con el mismo recuento que el registro real (`len(_real_registry())` sin `test_progress`), commit con los recuentos de T043

## Dependencias

- Tramo 1 → tramo 2 → tramo 3 → tramo 4, en serie.
- Dentro de cada tramo, las tareas `[P]` de tests se pueden escribir a la vez;
  la implementación va después de sus tests.
- T006 (refactor de `fs.py`) es lo primero que toca código del tramo 1
  después de la familia y el montaje: si algo de `/config` cambia, se ve antes
  de construir encima.
