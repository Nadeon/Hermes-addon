# Plan de implementación: carpetas /addons y /share (034)

**Rama**: `feat/034-carpetas-addons-y-share` (sale de `main`, punta
`37a25d4`, con la 1.2.0 publicada) · **Spec**: [spec.md](spec.md) ·
**Encargo**: decisiones D-1…D-8 (spec, «Clarificaciones»). Sin spec
paraguas.

## Resumen

Hermes 1.2.1 monta `/addons` (tipo `addons`, con escritura) y estrena la
familia `addons_share` con siete tools sobre `/addons` y `/share`: tres de
lectura (listar, metadatos, leer texto por líneas) y cuatro que modifican en
dos pasos (escribir, crear carpeta, mover o renombrar y borrar, también
recursivo). El token ata la carpeta, las rutas, el contenido y la huella de lo
que vio la vista previa. En `/addons` no se borra ni se mueve la carpeta de
una app local instalada, y las vistas previas avisan de que ahí está el código
que el Supervisor construye y ejecuta. No hay backup automático: la vista
previa lo dice y da la llamada para hacerlo. Además, `sv_install_addon` y
`sv_rebuild_addon` enseñan en su vista previa los privilegios de la app (de la
tienda, de la app instalada y, para las locales, de su `config.*`) y atan su
token a ellos. Las `fs_*` de `/config` no cambian.

## Contexto técnico

**Lenguaje**: Python 3.13. **Dependencias**: las de Hermes (SDK MCP,
aiohttp, structlog, PyYAML); ninguna nueva. **Pruebas**: pytest +
`unittest` asíncrono, ficheros reales en `tmp_path`, Supervisor simulado
(`MockHAClient`). **Plataforma**: add-on de HAOS; tests en Windows y CI de
Linux. **Restricciones**: `response_max_bytes` (131072 por defecto), API v1
del Supervisor, rol `manager` (no se usa ninguna ruta nueva: `GET /addons`,
`GET /store/addons/{slug}` y `GET /addons/{slug}/info` ya son `dedicated` en
la tabla).

**Escala**: 7 tools en 2 módulos nuevos (`tools/folders.py`,
`tools/folders_write.py`) y un módulo común sin tools (`hermes/folders.py`);
cambios en `fs.py` (dos extracciones sin cambio de comportamiento),
`tools/addons.py` y `tools/store_apps.py` (vista previa y estado),
`tools/_store.py` (privilegios), `tool_families.py`, `tools/__init__.py`,
`tools/_annotations.py`, `tools/guide.py`, `hermes/config.yaml`,
`__init__.py`, `config.py`; tests nuevos y ajustes de invariantes;
documentación.

**Tabla de comandos**: sin cambios (ninguna ruta nueva; R-4 y R-7).

**Otros invariantes**: el inventario de `allow_dangerous` (018) no cambia
(ninguna tool nueva llama a servicios); el HMAC de los tokens (019) no cambia
la forma de usar `create_confirmation_token`; el banco de Core no gana ni
pierde `xfail` (las tools nuevas no hablan con Core).

## Comprobación de la constitución

Contra la constitución 1.2.0.

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Las carpetas nuevas pasan por la misma validación de rutas que `/config` (FR-005, FR-006); todo lo que modifica, en dos pasos con huella (FR-011, FR-012); en `/addons`, aviso y bloqueo de apps instaladas (FR-018, FR-019); puntos de montaje de `/share` protegidos (FR-016); privilegios visibles y atados al instalar o reconstruir (FR-021–FR-023). Cada respuesta es una decisión explícita: campos elegidos, nunca la respuesta del Supervisor en crudo. | OK |
| II. Secretos | La lista negra por nombre de `/config` impide leer `secrets.yaml`, claves, certificados y bases de datos (FR-007); ninguna vista previa enseña contenido; el log no lleva contenido ni huellas (FR-026); los textos del autor en `privileges` pasan por `redact_secrets` (FR-023). Desviación declarada: el contenido de los demás ficheros sale sin redactar, IGUAL que `fs_read_file` (R-5); redactar solo aquí daría dos comportamientos distintos para la misma clase de fichero. | OK (desviación justificada) |
| III. Fail-closed | Supervisor caído con `config.*` en la ruta → rechazo; huérfanas con `config.*` ilegible → rechazo (FR-019); árbol demasiado grande o lento → rechazo (FR-012); carpeta sin montar → `folder_unavailable` (FR-002); todo se vuelve a comprobar al confirmar (FR-017); privilegios ilegibles al confirmar con los de la vista previa leídos → no casa (FR-023). | OK |
| IV. Dos pasos y token atado | Las cuatro piden token siempre; el token ata tool, carpeta, rutas normalizadas, contenido y `recursive`, y el estado (FR-011); la vista previa dice exactamente qué se borra o escribe, incluido que no hay backup (FR-020); el inventario de la 033 recoge lo que ata cada una (FR-029). | OK |
| V. Nombres y descripciones | Nombres al lado de sus parientes de `/config` y prefijos que las clasifican bien; las que modifican, `destructiveHint` (crear carpeta incluida, por el invariante «token ⇔ destructiva»); ninguna de mundo abierto (FR-024); las instrucciones dejan de decir que `fs_` es solo `/config` (FR-032). | OK |
| VI. Probar | Tests con ficheros reales y Supervisor simulado con la forma de 2026.11.0; las tools que modifican, en la matriz como «VM / pendiente» y fuera del banco con motivo (FR-028), porque no hablan con Core. | OK |
| VII. Control negativo | Cada protección nueva tiene su control negativo en tasks.md (raíz, montaje, app instalada, huella, symlink, lista negra, privilegios, familia). | OK |
| VIII. Privacidad | Datos ficticios (`local_ejemplo`, `ejemplo/`, `192.0.2.x`); nada de la instalación real; ningún identificador de modelo. | OK |
| IX. Cambios mínimos | Siete tools (el conjunto mínimo del encargo, R-3); `/config` solo con dos extracciones sin cambio de comportamiento; `sv_install_addon` y `sv_rebuild_addon`, solo vista previa y estado. Fuera: búsqueda, copia, binarios, backup automático, `local_apps`. | OK |
| X. Comentarios en español | Comentarios del porqué en español; descripciones, errores y eventos de log en inglés. | OK |
| XI. Versionado | 1.2.1 en `config.yaml`, `__init__.py` y `HA_CORE_LAST_TESTED_IN_HERMES`; entrada `## [1.2.1] — <fecha de publicación>`; READMEs sincronizados; DOCS con el montaje y la familia (FR-033, FR-034). La publicación (fecha, etiqueta, imagen) es del mantenedor. | OK |

Sin violaciones; la desviación del principio II está justificada arriba.

## Estructura

```text
hermes/config.yaml                    # map: addons (rw), versión 1.2.1
hermes/src/hermes/__init__.py         # __version__ = "1.2.1"
hermes/src/hermes/config.py           # HA_CORE_LAST_TESTED_IN_HERMES
hermes/src/hermes/fs.py               # normalize_in_root, blacklisted_name (extracciones)
hermes/src/hermes/folders.py          # NUEVO: raíces, rutas, huellas, recuentos, índice, montajes
hermes/src/hermes/tool_families.py    # familia addons_share (desde 1.2.1)
hermes/src/hermes/tools/__init__.py   # registro bajo _activa("addons_share")
hermes/src/hermes/tools/folders.py        # NUEVO: 3 tools de lectura
hermes/src/hermes/tools/folders_write.py  # NUEVO: 4 tools que modifican
hermes/src/hermes/tools/_annotations.py   # 3 en _DESTRUCTIVE_EXACT
hermes/src/hermes/tools/_store.py     # bloque privileges (puro + lectura)
hermes/src/hermes/tools/addons.py     # sv_install_addon: privileges + estado
hermes/src/hermes/tools/store_apps.py # sv_rebuild_addon: privileges + estado
hermes/src/hermes/tools/guide.py      # tema folders, cabecera, menciones
tests/test_folders.py                 # NUEVO (módulo común)
tests/test_tools_folders.py           # NUEVO (lectura)
tests/test_tools_folders_write.py     # NUEVO (escritura)
tests/test_tools_privilegios.py       # NUEVO (vistas previas de instalar y reconstruir)
tests/banco/cobertura_escrituras.py   # FUERA_DEL_BANCO +4
tests/…                               # ajustes de invariantes (R-10)
docs/HOJA-DE-RUTA.md, docs/BANCO-SUPERVISOR.md, hermes/DOCS.md, SECURITY.md,
README.md, README.es.md, hermes/CHANGELOG.md
```

## Diseño

### `hermes/folders.py` (sin tools)

- `ADDONS_BASE`, `SHARE_BASE`: `Path(os.environ.get(..., "/addons"|"/share"))`
  resueltas al importar, mutables para los tests; `raiz(folder)` valida el
  nombre (`invalid_argument`) y que la raíz exista (`folder_unavailable`).
- `normalizar(folder, path)`: byte nulo → `PathTraversalError`; después
  `fs.normalize_in_root(path, raiz, f"/{folder}")`.
- `normalizar_sin_seguir(folder, path)`: padre por `normalizar`, último nombre
  literal (para borrar y mover; R-2).
- `es_raiz(folder, p)`, `es_punto_de_montaje` (predicado de módulo,
  sustituible en tests), `contiene_punto_de_montaje(p)`.
- `huella(p)` y `recuento(p)` (un solo recorrido con `os.scandir`, sin
  seguir symlinks ni entrar en montajes, con topes de 50 000 entradas y 10 s;
  `ArbolDemasiadoGrande`).
- `indice_de_apps_locales()` (puro sobre la raíz de `addons`) y
  `async comprobar_apps_instaladas(ha_client, ruta, accion)` → `None` o el
  rechazo (`installed_app`, `installed_check_failed`,
  `installed_check_inconclusive`) o los avisos (`inside_installed_app`).
- Textos comunes de la vista previa: aviso de `/addons`, `backup_hint` por
  carpeta.

### `fs.py` (sin cambio de comportamiento en `/config`)

- `normalize_in_root(user_path, root, alias)`: el cuerpo actual de
  `normalize_path` con `CONFIG_BASE` y `"/config"` como parámetros (los
  mensajes que dicen `/config` pasan a usar el alias, que para `/config` es el
  mismo texto).
- `normalize_path(user_path)` → `normalize_in_root(user_path, CONFIG_BASE,
  "/config")`. OJO: `CONFIG_BASE` se lee en cada llamada (los tests lo
  parchean), no se captura al definir.
- `blacklisted_name(name)`: pasos 1b y 2 de `check_blacklisted`, que los
  llama.

### Tools

Patrón de `tools/filesystem_write.py` y `tools/store_apps.py`:
`create_confirmation_token(tool, args, preview=…, omitibles=…, estado=…)` en
la vista previa y `resolve_confirmation_token(…, estado=huella_actual)` al
confirmar; `ESTADO_CAMBIADO` → `preview_outdated`. El trabajo de disco va en
`asyncio.to_thread`. Las respuestas se arman con `tam_json` y
`sobre_de_lista`. Eventos de log `folder_action` (tool, folder, path,
result).

### Privilegios (`tools/_store.py`)

- `privilegios_de(ficha_tienda, info_instalada, declarado)` (pura): elige los
  campos de R-7, calcula `elevated` y redacta los textos.
- `declarado_en_carpeta(slug)` (lee el índice y el `config.*` de la app
  local; `None` si no es `local_*` o no está).
- `sv_install_addon`: `_vista_previa_de_instalar` ya tiene la ficha; añade
  `privileges` y `_token_con_version` pasa a atar
  `{"version_latest", "privileges"}` (al confirmar vuelve a leer la ficha,
  como ya hace para la versión, y el `config.*`).
- `sv_rebuild_addon`: la vista previa añade la ficha de la tienda y el
  `config.*`; la confirmación pasa de `validate_confirmation_token` a
  `resolve_confirmation_token` con `estado`.

## Matriz de trazabilidad

| FR | Encargo | Tramo | Tareas | Test |
|---|---|---|---|---|
| FR-001 | D-3 | 1 | T003 | `tests/test_addon_manifest.py::TestMontajes` |
| FR-002 | D-6 | 1 | T004, T005 | `tests/test_folders.py::TestRaices` |
| FR-003 | D-4 | 1 | T002, T010, T011 | `tests/test_tool_families.py`, `tests/test_tools_registration.py::TestFamiliaAddonsShare` |
| FR-004 | D-4 | 1 | T004, T005 | `tests/test_folders.py::TestCarpeta` |
| FR-005 | D-5 | 1 | T006, T007 | `tests/test_fs_security.py::TestNormalizeInRoot`, `tests/test_folders.py::TestRutas` |
| FR-006 | D-5 | 1 | T007, T013 | `tests/test_folders.py::TestSymlinks`, `tests/test_tools_folders.py::TestSymlinks` |
| FR-007 | D-5 | 1 | T006, T013 | `tests/test_fs_security.py::TestBlacklistedName`, `tests/test_tools_folders.py::TestListaNegra` |
| FR-008 | D-4 | 1 | T012, T013 | `tests/test_tools_folders.py::TestListar` |
| FR-009 | D-4 | 1 | T012, T013 | `tests/test_tools_folders.py::TestStat` |
| FR-010 | D-4 | 1 | T012, T013 | `tests/test_tools_folders.py::TestLeer` |
| FR-011 | D-5 | 2 | T018–T024 | `tests/test_tools_folders_write.py::TestTokenYEstado` |
| FR-012 | D-5 | 1, 2 | T008, T018 | `tests/test_folders.py::TestHuellas`, `::TestTopes` |
| FR-013 | D-4 | 2 | T019 | `tests/test_tools_folders_write.py::TestEscribir` |
| FR-014 | D-4 | 2 | T020 | `tests/test_tools_folders_write.py::TestCrearCarpeta` |
| FR-015 | D-4 | 2 | T021 | `tests/test_tools_folders_write.py::TestMover` |
| FR-016 | D-5 | 2 | T022 | `tests/test_tools_folders_write.py::TestBorrar`, `::TestPuntosDeMontaje` |
| FR-017 | D-5 | 2 | T018, T023 | `tests/test_tools_folders_write.py::TestRecompruebaAlConfirmar` |
| FR-018 | D-5 | 2 | T018 | `tests/test_tools_folders_write.py::TestAvisoAddons` |
| FR-019 | D-5 | 1, 2 | T009, T023 | `tests/test_folders.py::TestIndiceDeApps`, `tests/test_tools_folders_write.py::TestAppsInstaladas` |
| FR-020 | D-5 | 2 | T018 | `tests/test_tools_folders_write.py::TestSinBackup` |
| FR-021 | D-5 | 3 | T030–T032 | `tests/test_tools_privilegios.py::TestInstalar` |
| FR-022 | D-5 | 3 | T030, T033 | `tests/test_tools_privilegios.py::TestReconstruir` |
| FR-023 | D-5 | 3 | T032, T033, T034 | `tests/test_tools_privilegios.py::TestEstadoDelToken`, `tests/test_tools_registration.py::test_esquemas_de_la_1_1_2` |
| FR-024 | D-4, V | 1, 2 | T011, T025 | `tests/test_tools_registration.py::TestFamiliaAddonsShare` |
| FR-025 | I | 1, 2 | T013, T022 | `tests/test_tools_folders.py::TestTopeDeRespuesta`, `tests/test_tools_folders_write.py::TestBorrar` |
| FR-026 | II | 1, 2 | T013, T024 | `tests/test_tools_folders_write.py::TestLog` |
| FR-027 | D-4 | 1–3 | T006, T010, T034 | suite existente de `/config`, `tests/test_tools_registration.py::test_sin_addons_share_quedan_las_359_de_la_1_2_0` y `::test_esquemas_de_la_1_1_2` |
| FR-028 | D-6 | 2 | T026 | `tests/test_matriz_pruebas.py`, `tests/test_banco_cobertura_escrituras.py` |
| FR-029 | D-6 | 2 | T025 | `tests/test_confirmation_args_inventory.py` |
| FR-030 | D-6 | 1 | T012, T014 | `tests/test_sobre_de_lista.py` |
| FR-031 | D-6 | 1 | T010, T011 | `tests/test_tools_registration.py::TestRegistroPorFamilias` |
| FR-032 | D-7 | 4 | T037, T038 | `tests/test_tools_guide.py::TestTemaFolders` |
| FR-033 | D-7 | 2, 4 | T026, T039–T042 | `tests/test_matriz_pruebas.py` (hoja y procedimiento), revisión |
| FR-034 | D-2 | 4 | T036 | `tests/test_addon_manifest.py::TestEntradaDelChangelog` |

## Riesgos

- **El refactor de `normalize_path`** podría cambiar `/config`: se hace en el
  tramo 1 ANTES de nada más y con la suite de `/config` como control; el
  parche de `CONFIG_BASE` en los tests tiene que seguir funcionando (se lee en
  cada llamada).
- **Tests de symlinks en Windows**: se saltan si el sistema operativo no
  deja crearlos (R-9); corren en el CI de Linux. No se añaden fallos a los 6.
- **Tests de `sv_rebuild_addon` existentes** (030) mockean una sola lectura
  al confirmar: con el estado, la confirmación vuelve a leer la ficha y el
  `/addons/{slug}/info`. El tramo 3 ajusta esos simulados, sin cambiar las
  aserciones de comportamiento.
- **Huellas de la guía**: cambiar `filesystem`, `supervisor` y `app_store`
  obliga a recalcular sus huellas en `tests/test_tools_guide.py`; se dice en
  el commit.
- **El aviso del Supervisor por el tipo heredado `addons`**: esperado; se
  documenta (R-1).

## Tramos

| Tramo | Tareas | Resultado |
|---|---|---|
| **1** — base y lectura | T001–T016 | `fs.py` con las extracciones; `hermes/folders.py`; montaje `addons`; familia `addons_share`; las tres de lectura; invariantes de familias y registro |
| **2** — escritura | T017–T028 | las cuatro que modifican, con token, huella, apps instaladas, montajes, aviso y backup; matriz, banco, inventario de la 033, procedimiento de la VM |
| **3** — privilegios | T029–T035 | `privileges` en `sv_install_addon` y `sv_rebuild_addon`, con su estado |
| **4** — guía, documentación y versión | T036–T044 | tema `folders` y menciones; DOCS, SECURITY, READMEs, hoja de ruta, CHANGELOG; versión 1.2.1 |

Cada tramo necesita el anterior integrado (el 3 solo necesita el índice de
apps del tramo 1, pero va después del 2 para no cruzar ficheros de tests).
