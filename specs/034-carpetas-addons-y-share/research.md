# Investigación: carpetas /addons y /share (034)

Todo comprobado en el código de Hermes en `main` (`37a25d4`) y en el del
Supervisor 2026.11.0 (copia local de solo lectura). Las rutas del Supervisor
son relativas a su paquete `supervisor/`.

## R-1 — Montaje: `addons` y no `local_apps`

**Decisión**: `map: - type: addons, read_only: false` (D-3).

**Comprobado**:

- `apps/const.py`, `MappingType`: `LOCAL_APPS = "local_apps"` es el tipo
  nuevo; `ADDONS = "addons"` sigue en la enumeración como «Legacy, deprecated
  as of 2026.07».
- `apps/validate.py`, `_warn_app_config`: un tipo heredado solo produce un
  aviso en el log («uses legacy map type 'addons'; use 'local_apps'
  instead»); no invalida el manifiesto. Con los dos a la vez, el heredado se
  ignora.
- `docker/app.py` (montajes): `LOCAL_APPS` o, si no está, `ADDONS`, montan
  la MISMA fuente (`path_extern_apps_local`, `apps/local` en el disco del
  Supervisor); el destino por defecto es `/local_apps` para el nuevo y
  `/addons` para el heredado (`docker/const.py`: `PATH_LOCAL_APPS`,
  `PATH_LOCAL_ADDONS`).
- Hermes declara `homeassistant: "2024.10.0"`: un Supervisor anterior a
  2026.07 no conoce `local_apps`, y su validación (`vol.In` sobre la
  enumeración) rechazaría el manifiesto entero; la app dejaría de poder
  actualizarse.

**Consecuencia**: el Supervisor 2026.11 escribirá ese aviso de tipo heredado
en su log para Hermes (solo para repositorios locales, en canal dev o para
apps instaladas de repositorios de terceros, según `store/data.py`). Se
documenta en DOCS y en la hoja de ruta. Pasar a `local_apps` (y a la raíz
`/local_apps`) queda como duda para cuando el mínimo admitido lo permita;
`HERMES_ADDONS_BASE` hace que ese cambio sea de una línea.

**Alternativas descartadas**: `local_apps` (rompe instalaciones anteriores a
2026.07); declarar los dos (el Supervisor nuevo ignora el heredado y monta
`/local_apps`, el viejo rechaza el manifiesto).

## R-2 — Validación de rutas compartida con `/config`

**Decisión**: extraer de `fs.normalize_path` una función
`normalize_in_root(user_path, root, alias)` con los mismos pasos (vacía,
`unquote`, NFC, `strip`, absoluta con el alias o el prefijo real de la
raíz, `NAME_MAX`/`PATH_MAX`, `resolve()` con `ValueError`/`OSError` →
`PathTraversalError`, `relative_to(root)`). `normalize_path(user_path)` pasa
a ser `normalize_in_root(user_path, CONFIG_BASE, "/config")` y conserva firma,
mensajes y excepciones. Los tests de `/config`
(`tests/test_fs_security.py`, `tests/test_tools_filesystem.py`,
`tests/test_fs_write_security.py`) son el control de que no cambia nada.

Para las carpetas nuevas, un envoltorio en `hermes/folders.py` añade:

- el rechazo explícito del byte nulo ANTES de `resolve()` (en Windows
  `resolve()` no lo rechaza: así los tests nuevos no dependen del sistema
  operativo; en `/config` no se añade para no cambiar su comportamiento ni la
  lista de los 6 fallos conocidos de Windows);
- `resolver_sin_seguir_el_final(path)`: para borrar y mover, valida el padre
  con `normalize_in_root` y conserva el último nombre sin resolver, de modo
  que un symlink se trata como enlace (FR-006). El nombre final no puede ser
  `.`, `..` ni vacío.

**Por qué no ampliar `normalize_path` con un parámetro**: tiene más de diez
llamadores en `/config`; un parámetro con valor por defecto es lo mismo, pero
un nombre distinto deja claro en cada llamada qué raíz se usa.

## R-3 — Nombres, familia y módulos

**Decisión**: familia `addons_share` (`desde="1.2.1"`), módulos
`tools/folders.py` (lectura) y `tools/folders_write.py` (escritura), módulo
común sin tools `hermes/folders.py` (raíces, rutas, huellas, recuentos,
índice de apps locales, puntos de montaje). Tools:

| Tool | Modifica | Token | Anotación |
|---|---|---|---|
| `fs_list_dir_in_folder` | no | no | prefijo `fs_list_` |
| `fs_stat_in_folder` | no | no | prefijo `fs_stat` |
| `fs_read_file_in_folder` | no | no | prefijo `fs_read_` |
| `fs_write_file_in_folder` | sí | sí | `_DESTRUCTIVE_EXACT` |
| `fs_create_dir_in_folder` | sí | sí | `_DESTRUCTIVE_EXACT` |
| `fs_move_in_folder` | sí | sí | `_DESTRUCTIVE_EXACT` |
| `fs_delete_in_folder` | sí | sí | prefijo `fs_delete_` |

El sufijo `_in_folder` deja los nombres al lado de sus parientes de
`/config` (`fs_list_dir`, `fs_stat`, `fs_read_file`, `fs_write_file`,
`fs_move_file`, `fs_delete_file`) y los prefijos de anotación existentes las
clasifican bien sin tocar `_READ_ONLY_PREFIXES`. Títulos: «List dir in folder
(files)», etc., únicos (lo comprueba `test_every_tool_has_a_unique_title…`).

**Conjunto mínimo**: el del encargo. Una sola tool de lectura (por líneas,
con `offset`/`limit`) en vez de las dos de `/config` (`fs_read_file` y
`fs_read_file_lines`): la paginación ya cubre el fichero entero. No se añade
búsqueda (`grep`), copia ni lectura binaria: no los pide el encargo.
`fs_create_dir_in_folder` pide token aunque solo añade (D-5: «todo lo que
modifica va en dos pasos»); por el invariante «pide token ⇔ destructiva» se
anuncia destructiva, como `sv_start_core` (precedente de la 022).

**Familia aparte de `filesystem`**: D-4 y FR-010 de la 008 (las tools nuevas
van en familias nuevas): apagando `addons_share` vuelve la lista de la 1.2.0.

## R-4 — Apps locales: cómo se reconoce su carpeta y si están instaladas

**Comprobado** en `store/data.py`:

- `StoreData.update` lee `path_apps_local` (la fuente de `/addons`) como
  repositorio `local`.
- `_find_app_configs`: `path.glob("**/config.*")`, descartando las rutas con
  alguna parte que empieza por `.` o es `rootfs`, y con sufijo en
  `FILE_SUFFIX_CONFIGURATION` (`.json`, `.yaml`, `.yml`). La carpeta de la app
  puede estar a cualquier profundidad.
- `_process_apps_config`: un fichero ilegible o que no valida se salta (no
  hay app); el slug es `f"{repository}_{app[ATTR_SLUG]}"` → `local_<slug>`.
- `api/apps.py`, `_list_apps_data`: `GET /addons` lista las apps
  INSTALADAS con su `slug` (la clave de la respuesta v1 es `addons`, la que
  ya usa `sv_list_addons`). Ninguna ruta da la carpeta (`location` es
  interno).

**Decisión**: índice = {`local_<slug>` → carpeta} construido igual, sobre la
raíz de `addons`; instaladas = slugs `local_*` de `GET /addons`. Reglas en
FR-019. Detalles:

- Una app «instalada huérfana» (instalada y sin `config.*` legible en el
  índice: su manifiesto se corrompió o se borró) no se puede ligar a ninguna
  carpeta. Si la ruta a borrar contiene un `config.*` ilegible o sin `slug`,
  podría ser el suyo: `installed_check_inconclusive`. Si no hay huérfanas,
  los `config.*` ilegibles no son apps (el Supervisor los ignora).
- La comprobación se repite al confirmar (FR-017).
- Ruta DENTRO de una app instalada (un fichero suyo): borrar, mover y
  escribir se admiten con el aviso `inside_installed_app`, salvo su propio
  `config.*` (borrarlo o moverlo quita la app de la tienda; reescribirlo con
  otro `slug` la desliga).
- `config.*` se lee con `yaml.safe_load` (JSON es YAML válido) y un tope de
  1 MiB por fichero; uno mayor cuenta como ilegible.

## R-5 — Redacción y lista negra

**Comprobado**: `fs_read_file`, `fs_read_file_lines` y `fs_search_in_config`
devuelven el contenido tal cual; la protección es `check_blacklisted` (por
ruta exacta, por nombre, por patrón, por directorio y la lista de
`.storage`). No hay `redact_secrets` sobre el contenido de `/config`.

**Decisión**: «la misma redacción» = la protección por nombre de fichero
(`BLACKLIST_BASENAMES`, `BLACKLIST_PATTERNS`), extraída a
`fs.blacklisted_name(name) -> tuple[bool, str]` y usada por
`check_blacklisted` sin cambiar su resultado. Las reglas de directorio y de
`.storage` describen `/config` y no tienen sentido fuera de él.

Solo protege la LECTURA (el secreto llegaría al contexto del modelo). Borrar
o mover un fichero de la lista negra se admite con token: si no, el borrado
recursivo de una copia de desarrollo fallaría por cualquier fichero de
pruebas con `token` en el nombre o un certificado de ejemplo; el riesgo de
borrar no es de confidencialidad y ya va en dos pasos. Ninguna vista previa
enseña contenido.

## R-6 — Backup previo: no

**Comprobado**: `api/backups.py` acepta en v1 las carpetas `addons/local` (el
nombre heredado de `Folder.APPS`) y `share`; Hermes ya tiene
`sv_create_backup_partial(folders=…)` (JSON).

**Decisión**: ningún backup automático, en ninguna de las dos carpetas.

- `/share` puede ocupar muchos GB (grabaciones, bases de datos de otras
  apps, NAS montados debajo): un backup parcial por cada escritura llenaría
  el disco de backups, tardaría minutos y bloquearía la confirmación.
- El backup por fichero de `/config` (copia en `/data`) no escala a un
  borrado recursivo y llenaría `/data` de Hermes.
- Un backup de `addons/local` solo para `addons` sería más barato, pero
  dejaría dos comportamientos distintos detrás de la misma tool, y la
  decisión de copiar sigue estando en manos del usuario con una tool que ya
  existe.

**Lo que dice la vista previa** (FR-020): `backup: null`, `reversible:
false` (salvo crear carpeta) y `backup_hint` con la llamada exacta. Es lo
que de verdad pasa (principio IV).

## R-7 — Privilegios en la vista previa

**Campos que da el Supervisor 2026.11.0** (comprobado):

- `GET /store/addons/{slug}` (`api/store.py`,
  `_generate_app_information(app, extended=True)`): `apparmor`, `auth_api`,
  `detached`, `docker_api`, `full_access`, `hassio_api`, `hassio_role`,
  `homeassistant_api`, `host_network`, `host_pid`, `ingress`,
  `long_description`, `rating`, `signed` (más los no privilegios: nombre,
  versión, repositorio…).
- `GET /addons/{slug}/info` (`api/apps.py`, `info_data`; solo instaladas, si
  no `APIAppNotInstalled`): además `host_ipc`, `host_uts`, `host_dbus`,
  `privileged` (lista de capacidades), `gpio`, `usb`, `uart`,
  `kernel_modules`, `devicetree`, `udev`, `video`, `audio`, `devices`
  (lista de rutas).
- **Ninguna da `map`** ni `ports` del host como privilegio.

**Quién aplica qué** (comprobado): instalar usa la ficha de la tienda; al
reconstruir (`apps/app.py`, `rebuild`), tras construir la imagen, el
Supervisor copia la ficha de la tienda a los datos de la app instalada
(`self.sys_apps.data.update(self.app_store)`): lo que se aplica después de
reconstruir es lo de la tienda, no lo de `/addons/{slug}/info`. La ficha de la
tienda de una app local refleja su `config.*` tal como estaba en la última
recarga de la tienda.

**Decisión**:

- `privileges.store`: los campos de privilegio de la ficha de la tienda
  (lista cerrada de arriba, sin `long_description`).
- `privileges.installed` (solo reconstruir): los de `/addons/{slug}/info`.
- `privileges.declared_in_folder` (solo `local_*` con `config.*` en el
  índice): lo que declara el fichero, incluido `map` y `ports`, con la nota de
  que el Supervisor usa su copia hasta recargar la tienda
  (`sv_reload_store`).
- `privileges.elevated`: nombres de los elevados según una regla fija sobre
  la unión de las fuentes: `full_access`, `docker_api`, `host_network`,
  `host_pid`, `host_ipc`, `host_uts`, `host_dbus`, `kernel_modules`, `udev`
  con `true`; `privileged` o `devices` no vacíos; `hassio_role` `manager` o
  `admin`; `apparmor` `false`; en `map`, cualquier entrada con escritura.
- Valores de texto del autor (`hassio_role`, rutas de `devices`, `map`)
  pasan por `redact_secrets`.
- Estado del token: el bloque entero (sin las notas). En `sv_install_addon`
  se suma a `version_latest` en el `estado` que ya ata `_token_con_version`;
  en `sv_rebuild_addon`, `validate_confirmation_token` pasa a
  `resolve_confirmation_token` con `estado` (`ESTADO_CAMBIADO` →
  `preview_outdated`, como en instalar). Para leer el estado al confirmar se
  vuelven a pedir las mismas rutas (GET, sin efecto).

**Esquema**: no cambia ningún argumento de las dos tools (lo vigila
`test_esquemas_de_la_1_1_2` y su equivalente de la 1.2.0); solo crece la
vista previa. Las huellas de los temas `supervisor` y `app_store` cambian
porque la guía lo cuenta.

## R-8 — Huellas, límites y puntos de montaje

- Huella de fichero (FR-012): SHA-256 si mide ≤ 64 MiB (leer 64 MiB en un
  hilo es razonable en el hardware de HAOS); por encima, (tamaño, `st_mtime_ns`,
  `st_ino`): cambiar el contenido sin cambiar ni tamaño ni fecha exige
  manipular la fecha a propósito, y el token dura 60 s.
- Huella de carpeta: lista ordenada de (ruta relativa POSIX, tipo, tamaño,
  `st_mtime_ns`) con `os.scandir` sin seguir symlinks; SHA-256 de su forma
  canónica. Tope 50 000 entradas y 10 s (en un hilo) →
  `too_large_to_preview`.
- Puntos de montaje: `mounts/mount.py` monta los recursos de uso `share` en
  `path_extern_share / name`, es decir `/share/<nombre>` para Hermes. Un
  `rmtree` sobre `/share` o sobre `/share/<nombre>` borraría el NAS. Se
  detectan con un predicado inyectable (`es_punto_de_montaje(path)`:
  `os.path.ismount` o `st_dev` distinto del de la raíz); el recorrido no
  entra en ellos y borrar o mover uno, o algo que lo contenga, se rechaza. En
  los tests se sustituye el predicado (independiente del sistema operativo).
- Borrado: `shutil.rmtree` (en Linux usa la variante segura frente a
  symlinks con descriptores); un symlink se borra con `unlink`. Si `rmtree`
  falla a medias, se cuenta lo que queda y se responde `partial: true`.

## R-9 — Pruebas

- Raíces: `folders.ADDONS_BASE` y `folders.SHARE_BASE` (mutables, como
  `fs.CONFIG_BASE`) con `HERMES_ADDONS_BASE`/`HERMES_SHARE_BASE` de entorno;
  los tests las parchean con `tmp_path`.
- Supervisor simulado: el `MockHAClient` de `tests/test_tools_supervisor.py`
  (o la fixture de la 030, `tests/fixtures/supervisor_tienda.py`) con
  respuestas de la forma de 2026.11.0: `GET /addons` → `{"addons": [{"slug":
  "local_ejemplo", …}]}`, `GET /store/addons/{slug}` con los campos de R-7.
- Symlinks: un ayudante crea el symlink y, si el sistema operativo no lo
  permite (Windows sin privilegio), hace `skip` con el motivo; en el CI de
  Linux corren siempre. No se añade ningún fallo a los 6 conocidos.
- Byte nulo: el rechazo explícito (R-2) hace que el test pase igual en
  Windows y en Linux.
- Fechas: los tests de huella cambian `st_mtime_ns` con `os.utime(ns=…)` en
  vez de esperar.

## R-10 — Tests existentes que hay que adaptar

- `tests/test_tools_registration.py`: las tools nuevas van en un diccionario
  `_HINTS_NUEVAS_1_2_1` (código de hints y título), hermano de
  `_HINTS_NUEVAS_1_2_0`; `test_hints_did_not_change` resta los dos y
  `test_hints_y_titulos_de_las_nuevas` recorre los dos.
- `tests/test_tool_families.py::test_nombres_unicos_y_con_forma`: admite
  `desde` en {`1.1.2`, `1.2.0`, `1.2.1`}.
- `tests/test_tools_registration.py::test_sc005_sin_las_de_la_1_2_0_queda_la_1_1_2`:
  apaga todas las familias con `desde != "1.1.2"`; y un test nuevo «sin
  `addons_share` quedan las 359 de la 1.2.0».
- `tests/test_banco_cobertura_escrituras.py::test_recuento_028`:
  `FUERA_DEL_BANCO` pasa de 51 a 55.
- `tests/test_confirmation_args_inventory.py`: 145 → 149 en los dos recuentos.
- `tests/test_addon_manifest.py`: la entrada que se comprueba es la de
  `__version__` (1.2.1) con sus secciones (lista nueva `SECCIONES_1_2_1`, que
  sustituye a `SECCIONES_1_2_0` en `test_la_entrada_tiene_las_secciones…`);
  un test nuevo comprueba el montaje `addons` con escritura.
- `tests/test_sobre_de_lista.py`: `_PREFIJOS_DE_LISTA` incluye `fs_list_`
  (las `fs_list_*` de la 1.1.2 quedan fuera por la instantánea de esquemas).
- `tests/test_tools_guide.py`: huellas de `filesystem`, `supervisor` y
  `app_store`, y las instrucciones con y sin la familia.
