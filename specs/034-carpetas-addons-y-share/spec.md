# Especificación: Hermes 1.2.1 — carpetas /addons y /share (034)

**Directorio de la spec**: `specs/034-carpetas-addons-y-share`

**Creada**: 2026-11-15

**Estado**: Borrador

**Entrada**: encargo del supervisor de la 034 (las decisiones D-1 a D-8 de
«Clarificaciones»). No hay spec paraguas: la 1.2.0 ya está publicada y
fusionada en `main`, y los FR de esta spec se trazan al encargo. Siguen
vigentes los invariantes que dejó el programa 1.2.0 (tabla de comandos,
familias, matriz de la 014, inventario de argumentos atados de la 033,
inventario de `allow_dangerous` de la 018, `sobre_de_lista`, huellas de la
guía e instantánea de esquemas de la 1.1.2).

Contrastado con el código de Hermes en `main` (`37a25d4`): `fs.py`
(`normalize_path`, `check_blacklisted`, `read_bytes`, `is_binary`,
`detect_encoding`), `fs_write.py` (`safe_write_file`), `tools/filesystem.py`,
`tools/filesystem_write.py`, `security.py` (`create_confirmation_token` y
`resolve_confirmation_token` con `estado`), `tools/addons.py`
(`sv_install_addon`, `_vista_previa_de_instalar`, `_token_con_version`),
`tools/store_apps.py` (`sv_rebuild_addon`), `tools/_store.py`
(`ficha_de_tienda`), `tool_families.py` y `hermes/config.yaml`; y con el
código del Supervisor 2026.11.0: `apps/const.py` (`MappingType`),
`apps/validate.py`, `docker/app.py` y `docker/const.py` (montajes),
`store/data.py` (cómo se descubren las apps locales), `api/apps.py` y
`api/store.py` (campos de la ficha), `apps/manager.py` y `apps/app.py`
(reconstruir), `api/backups.py` (nombres de carpetas) y `mounts/mount.py`
(montajes de red bajo `/share`).

## Clarificaciones

### Sesión 2026-11-15

Decisiones del supervisor, que no se discuten aquí:

- **D-1** — Solo `/addons` y `/share`. Ninguna otra carpeta (`/ssl`,
  `/media`, `/backup`, `/addon_configs`).
- **D-2** — Versión **1.2.1** (la 1.3.0 está anunciada para retirar lo
  deprecado y esto no lo hace). Entrada nueva `## [1.2.1] — <fecha de
  publicación>` encima de la 1.2.0.
- **D-3** — Montaje: se añade `addons` con escritura al `map:`; `share` ya
  está.
- **D-4** — Tools nuevas en una familia nueva, desactivable y activa por
  defecto, con un argumento que elige la carpeta (`addons` o `share`) y una
  ruta relativa a ella. Las `fs_*` de `/config` no cambian; se puede
  reutilizar por dentro su validación de rutas, la protección de symlinks y la
  escritura atómica, parametrizando la raíz, sin cambiar el comportamiento en
  `/config`.
- **D-5** — Seguridad fail-closed: dos pasos para todo lo que modifica, con el
  token atado a carpeta, ruta, contenido y estado; borrado recursivo con
  recuento, tamaño y muestra, nunca la raíz; aviso en `/addons`; las apps
  locales instaladas no se borran ni se mueven; privilegios en la vista previa
  de `sv_install_addon` y `sv_rebuild_addon`; mismas protecciones de rutas que
  en `/config`; misma redacción que las lecturas de `/config`; backup previo a
  decidir y la vista previa lo dice sin mentir.
- **D-6** — Pruebas: raíces cambiables en los tests; ficheros reales en
  carpetas temporales y Supervisor simulado; matriz de la 014 como «VM /
  pendiente»; inventario de la 033; tests independientes del sistema
  operativo; controles negativos.
- **D-7** — Documentación en el mismo cambio (guía, `DOCS.md`, `SECURITY.md`,
  READMEs, hoja de ruta y CHANGELOG).
- **D-8** — Trazabilidad al encargo; comprobación contra la constitución en el
  plan.

Decisiones de esta spec, comprobadas en el código (detalle en research.md):

- P: ¿Tipo de montaje `addons` o `local_apps`? → R: **`addons`** (D-3). El
  Supervisor 2026.11.0 lo da por heredado desde 2026.07 y escribe un aviso en
  su log, pero lo sigue montando en `/addons` con la misma fuente que
  `local_apps` (`docker/app.py`). `local_apps` (montado en `/local_apps`) no
  lo conoce un Supervisor anterior a 2026.07, y Hermes admite instalaciones
  desde Core 2024.10: con él, esas instalaciones no podrían leer el manifiesto
  de Hermes. Pasar a `local_apps` queda para cuando el mínimo lo permita
  (research R-1).
- P: ¿Backup antes de escribir o borrar? → R: **no**, en ninguna de las dos
  carpetas. La vista previa lo dice (`backup: null`), avisa de que no se puede
  deshacer desde Hermes y da la llamada exacta para hacer antes un backup
  parcial (`sv_create_backup_partial` con `addons/local` o `share`). Motivos
  en research R-6.
- P: ¿Redacción al leer? → R: **la misma que en `/config`**, que no redacta el
  contenido: protege por nombre (lista negra). Se aplican las reglas por
  nombre de fichero (`secrets.yaml`, `*.key`, `*.pem`, `*token*`, `*.db`…);
  las de directorio (`.storage`, `.cloud`, `deps`) son propias de `/config` y
  no se aplican (research R-5).
- P: ¿Cómo se reconoce la carpeta de una app local? → R: como el Supervisor:
  todo `config.json|yaml|yml` bajo `/addons` (a cualquier profundidad, salvo
  rutas con una parte que empieza por `.` o que se llama `rootfs`) define una
  app con slug `local_<slug del fichero>`; si ese slug está en la lista de
  apps instaladas del Supervisor (`GET /addons`), la app está instalada
  (research R-4).
- P: ¿Qué privilegios da el Supervisor? → R: la ficha de la tienda
  (`/store/addons/{slug}`) da `apparmor`, `auth_api`, `docker_api`,
  `full_access`, `hassio_api`, `hassio_role`, `homeassistant_api`,
  `host_network`, `host_pid`, `ingress`, `rating`, `signed` y `detached`;
  `/addons/{slug}/info` (solo apps instaladas) da además `privileged`,
  `devices`, `host_ipc`, `host_uts`, `host_dbus`, `kernel_modules`, `udev`,
  `usb`, `uart`, `gpio`, `devicetree`, `video` y `audio`. **Ninguna da
  `map`**: para una app local, Hermes lo lee de su `config.*` en `/addons`
  (research R-7).

## Escenarios de usuario y pruebas *(obligatorio)*

Actor: el mantenedor (o cualquier usuario de Hermes) hablando con un cliente
MCP, que es quien llama a las tools.

### Historia 1 — Borrar la copia de desarrollo que quedó en /addons (Prioridad: P1)

El mantenedor tiene en `/addons` la carpeta de una copia de desarrollo de
Hermes que ya no usa. Quiere que el cliente la borre entera, sabiendo antes
cuántos ficheros son y cuánto ocupan, y con la garantía de que no se lleva por
delante una app local que esté instalada.

**Por qué esta prioridad**: es el caso que motivó la 034.

**Prueba independiente**: con una raíz de `/addons` temporal que tiene una
carpeta de app local con `config.yaml` (slug `ejemplo`) y un Supervisor
simulado, `fs_delete_in_folder(folder="addons", path="ejemplo",
recursive=true)` sin token devuelve una vista previa con el recuento, el
tamaño, la muestra, el aviso de `/addons` y `backup: null`; con el token, la
carpeta desaparece. Si el Supervisor dice que `local_ejemplo` está instalada,
la vista previa se rechaza sin token.

**Escenarios de aceptación**:

1. **Dado** una carpeta `ejemplo/` con 12 ficheros (40 KB) en `/addons` y la
   app `local_ejemplo` no instalada, **cuando** se pide borrarla con
   `recursive=true` sin token, **entonces** la respuesta trae
   `confirmation_token` y una vista previa con `files: 12`, los directorios,
   `total_bytes`, una muestra de rutas (hasta 20), el aviso de que `/addons`
   es el código de las apps locales que el Supervisor construye y ejecuta,
   `backup: null` y la llamada para hacer un backup parcial antes.
2. **Dado** esa vista previa, **cuando** se confirma con el token y los mismos
   argumentos, **entonces** la carpeta se borra entera y la respuesta dice
   cuántos ficheros se borraron.
3. **Dado** que entre la vista previa y la confirmación cambia algo dentro de
   la carpeta (un fichero nuevo, uno modificado), **cuando** se confirma,
   **entonces** se rechaza con «el estado cambió» y no se borra nada.
4. **Dado** que el Supervisor lista `local_ejemplo` como instalada, **cuando**
   se pide borrar (o mover) `ejemplo` o una carpeta que la contiene,
   **entonces** se rechaza sin token con `installed_app`, el slug y la
   indicación de desinstalarla antes con `sv_uninstall_addon`.
5. **Dado** que el Supervisor no responde, **cuando** se pide borrar una
   carpeta que contiene algún `config.*` de app, **entonces** se rechaza sin
   token (`installed_check_failed`): no se puede saber si está instalada.
6. **Dado** `path` vacío, `.` o `/addons`, **cuando** se pide borrar,
   **entonces** se rechaza sin token: la raíz de una carpeta nunca se borra.
7. **Dado** una carpeta no vacía, **cuando** se pide borrar sin
   `recursive=true`, **entonces** se rechaza sin token con
   `directory_not_empty` y la pista de `recursive`.

---

### Historia 2 — Ver qué hay en /addons y /share (Prioridad: P1)

El usuario quiere listar, ver metadatos y leer ficheros de texto de las dos
carpetas: la configuración de otra app guardada en `/share`, el `config.yaml`
o el `Dockerfile` de una app local.

**Por qué esta prioridad**: sin poder mirar, no se puede decidir qué borrar o
escribir.

**Prueba independiente**: con raíces temporales, `fs_list_dir_in_folder`,
`fs_stat_in_folder` y `fs_read_file_in_folder` devuelven lo que hay, con los
mismos rechazos de ruta que las `fs_*` de `/config`.

**Escenarios de aceptación**:

1. **Dado** `/share` con ficheros y carpetas, **cuando** se lista con
   `folder="share"`, **entonces** se recibe el sobre común de listas
   (`count`, `items`, `truncated`) con nombre, tipo (`file`, `dir`,
   `symlink`), tamaño, fecha y `is_blacklisted`.
2. **Dado** un fichero de texto grande, **cuando** se lee, **entonces**
   vuelven las líneas pedidas (`offset`, `limit`) dentro del tope de
   respuesta, con `next_offset` si quedan más.
3. **Dado** un fichero binario, **cuando** se lee, **entonces** vuelven solo
   sus metadatos (`binary: true`), sin contenido.
4. **Dado** `secrets.yaml`, un `*.pem` o un fichero con `token` en el nombre,
   **cuando** se lee, **entonces** se rechaza con `blacklisted`, como en
   `/config`; al listarlo aparece con `is_blacklisted: true`.
5. **Dado** una ruta con `..`, un symlink que apunta fuera de la carpeta o un
   byte nulo, **cuando** se usa en cualquiera de las tools, **entonces** se
   rechaza con `traversal`, como en `/config`.
6. **Dado** la carpeta de una app local en `/addons`, **cuando** se pide
   `fs_stat_in_folder` de esa carpeta, **entonces** la respuesta dice el slug
   `local_<slug>` y si está instalada.

---

### Historia 3 — Escribir, crear carpetas y mover en las dos carpetas (Prioridad: P2)

El usuario quiere editar un fichero de una app local, guardar un fichero de
configuración en `/share` para otra app, crear una carpeta o renombrar una.

**Por qué esta prioridad**: completa el conjunto mínimo; el borrado (P1) ya
cubre el caso que motivó la 034.

**Prueba independiente**: las tres tools devuelven vista previa y token, y
con el token hacen exactamente lo previsualizado; si el estado cambió entre
medias, no hacen nada.

**Escenarios de aceptación**:

1. **Dado** un fichero existente, **cuando** se pide escribirlo, **entonces**
   la vista previa dice que existe, su tamaño y su huella, el tamaño y la
   huella del contenido nuevo, `backup: null` y, en `/addons`, el aviso; con
   el token, se escribe de forma atómica. Para confirmar basta con la ruta y
   el token (el contenido lo guardó el servidor).
2. **Dado** que el fichero cambió (o se creó) entre la vista previa y la
   confirmación, **cuando** se confirma, **entonces** no se escribe.
3. **Dado** una ruta que no existe, **cuando** se pide crear la carpeta,
   **entonces** vista previa y, con el token, la carpeta (con sus padres).
   Si ya existe, `already_exists` sin token.
4. **Dado** un fichero o carpeta, **cuando** se pide moverlo dentro de la
   misma carpeta a un destino que no existe, **entonces** vista previa (con
   el recuento si es una carpeta) y, con el token, se mueve. Si el destino
   existe, `destination_exists` sin token.
5. **Dado** un fichero dentro de la carpeta de una app local instalada,
   **cuando** se pide escribirlo, **entonces** la vista previa avisa de que
   pertenece a `local_<slug>` y de que el cambio se aplica al reconstruirla.

---

### Historia 4 — Ver los privilegios de una app antes de instalarla o reconstruirla (Prioridad: P2)

Con las tools nuevas, un cliente puede escribir una app local en `/addons` y
después instalarla. La salvaguarda es que la vista previa de instalar y de
reconstruir enseñe qué privilegios pide la app.

**Por qué esta prioridad**: es la defensa frente a una app local maliciosa
escrita con las tools nuevas.

**Prueba independiente**: con un Supervisor simulado que da la ficha real de
2026.11.0 y una app local en una raíz temporal, la vista previa de
`sv_install_addon` y de `sv_rebuild_addon` trae el bloque `privileges`.

**Escenarios de aceptación**:

1. **Dado** una app de la tienda, **cuando** se pide instalarla, **entonces**
   la vista previa enseña los privilegios de la ficha de la tienda y cuáles
   son elevados (`elevated`).
2. **Dado** una app local con `config.yaml` en `/addons`, **cuando** se pide
   instalarla, **entonces** la vista previa enseña además lo que declara su
   fichero, incluido `map` (que el Supervisor no da por la API).
3. **Dado** que los privilegios cambian entre la vista previa y la
   confirmación, **cuando** se confirma, **entonces** no se instala (ni se
   reconstruye) y se pide otra vista previa.
4. **Dado** que la ficha no se puede leer, **cuando** se pide la vista previa,
   **entonces** `privileges` es `null` con el motivo; nunca se inventa.

---

### Historia 5 — Nada de lo que funciona hoy cambia (Prioridad: P1)

**Por qué esta prioridad**: es una versión de parche (1.2.1).

**Prueba independiente**: la suite existente pasa sin tocar sus aserciones
de comportamiento; la instantánea de esquemas de la 1.1.2 no cambia;
apagando la familia nueva, la lista de tools es la de la 1.2.0.

**Escenarios de aceptación**:

1. **Dado** las `fs_*` de `/config`, **cuando** se usan, **entonces**
   responden igual que en la 1.2.0 (sus tests no cambian).
2. **Dado** `tool_families_disabled: [addons_share]`, **cuando** arranca
   Hermes, **entonces** se registran exactamente las 359 tools de la 1.2.0.
3. **Dado** `sv_install_addon` y `sv_rebuild_addon`, **cuando** se mira su
   esquema de entrada, **entonces** es el mismo de antes.

---

### Casos límite

- **Symlinks**: al listar no se siguen; leer a través de uno que apunta
  dentro de la carpeta funciona; uno que apunta fuera es `traversal`; borrar
  o mover un symlink actúa sobre el enlace, nunca sobre su destino; el
  borrado recursivo no sigue ninguno.
- **Montajes bajo `/share`**: el Supervisor monta los recursos de red de uso
  `share` en `/share/<nombre>`. Borrar o mover un punto de montaje, o una
  carpeta que contenga uno, se rechaza sin token (`mount_point`): borraría el
  contenido del NAS. El recuento no entra en ellos.
- **Árboles enormes** (`/share` puede tener millones de ficheros): si la
  vista previa recursiva pasa de 50 000 entradas o de 10 s, se rechaza sin
  token (`too_large_to_preview`, con la pista de ir por subcarpetas).
- **Fichero enorme**: la huella es SHA-256 hasta 64 MiB; por encima, tamaño,
  fecha de modificación (ns) e inodo. La lectura es en streaming y
  `total_lines` solo se da hasta 4 MiB.
- **Carpeta no montada** (instalación sin el montaje nuevo, desarrollo
  local): `folder_unavailable` sin token.
- **`config.*` ilegible o sin `slug`** dentro de lo que se borra: el
  Supervisor tampoco lo carga, así que no es una app instalada; pero si hay
  apps `local_*` instaladas cuyo `config.*` no se encuentra en `/addons`, no
  se puede descartar que sea la suya y se rechaza
  (`installed_check_inconclusive`).
- **Mover entre carpetas** (`addons` ↔ `share`): no se admite; son montajes
  distintos y `rename` no los cruza.
- **Mover dentro de sí misma** (`a` → `a/b`): `invalid_destination` sin
  token.
- **Escribir el `config.*` de una app instalada** con otro `slug`: se
  rechaza (`installed_app`); la dejaría desligada de su carpeta.
- **Contenido con una credencial tapada** (`usuario:***@`): lo rechaza el
  guardián central de la 1.2.0 antes de llegar a la tool.
- **Hermes se borra a sí mismo**: si Hermes corre como app local
  (`local_hermes`), su carpeta es la de una app instalada y se rechaza.

## Requisitos *(obligatorio)*

Todos se trazan al encargo de la 034 (D-1…D-8); la columna «Encargo» de la
matriz de plan.md dice cuál.

### Requisitos funcionales

**Montaje, raíces y familia**

- **FR-001** (D-3) — `hermes/config.yaml` monta `addons` con escritura
  (`type: addons`, `read_only: false`). `share` sigue igual. Un comentario
  explica por qué `addons` y no `local_apps`.
- **FR-002** (D-6) — Las raíces de las dos carpetas salen de
  `HERMES_ADDONS_BASE` (por defecto `/addons`) y `HERMES_SHARE_BASE` (por
  defecto `/share`), resueltas al cargar el módulo y cambiables en los tests,
  como `HERMES_CONFIG_BASE`. Si la raíz no existe o no es un directorio,
  toda tool responde `folder_unavailable` sin token.
- **FR-003** (D-4) — Familia nueva `addons_share` (`desde="1.2.1"`,
  desactivable, activa por defecto) con siete tools en dos módulos
  (`folders`, lectura; `folders_write`, escritura). Apagándola, la lista de
  tools es la de la 1.2.0 (359), y apagando además las de la 1.2.0, la de la
  1.1.2 (216).
- **FR-004** (D-4) — Todas las tools reciben `folder` (`"addons"` o
  `"share"`; otro valor → `invalid_argument` sin tocar el disco) y una ruta
  relativa a esa carpeta. Se admite también la ruta absoluta con el prefijo
  de la propia carpeta (`/addons/…`, `/share/…`); cualquier otra absoluta es
  `traversal`.

**Rutas, symlinks y lista negra**

- **FR-005** (D-5 rutas) — La ruta pasa la misma validación que en `/config`,
  con la raíz de la carpeta: vacía, URL-decode, NFC, límites `NAME_MAX` y
  `PATH_MAX`, byte nulo, `..` y symlinks que salen de la raíz → `traversal`.
  Es la MISMA función, parametrizada por raíz; `normalize_path` de `/config`
  conserva su firma y su comportamiento.
- **FR-006** (D-5 rutas) — Symlinks: el listado no los sigue y los marca como
  `symlink`; borrar o mover uno actúa sobre el enlace (se valida su carpeta
  padre, no su destino); ningún recorrido recursivo los sigue.
- **FR-007** (D-5 redacción) — Lista negra por nombre de fichero, la misma de
  `/config` (`BLACKLIST_BASENAMES` y `BLACKLIST_PATTERNS`): su contenido no se
  devuelve nunca (`blacklisted` al leer) y el listado y `stat` los marcan con
  `is_blacklisted`. Las reglas de directorio de `/config` no se aplican. El
  contenido de los demás ficheros se devuelve sin redactar, igual que
  `fs_read_file`. Escribir, mover o borrar un fichero de la lista negra se
  admite con token; ninguna vista previa enseña contenido.

**Lectura**

- **FR-008** (D-4) — `fs_list_dir_in_folder(folder, path=".", recursive=false,
  max_depth=3)` lista con `sobre_de_lista`: nombre (ruta relativa si es
  recursivo), tipo, tamaño, fecha e `is_blacklisted`; profundidad máxima 3,
  500 entradas como mucho (`truncated` y una pista).
- **FR-009** (D-4) — `fs_stat_in_folder(folder, path)` da tipo, tamaño,
  fecha, `is_blacklisted`, `is_mount_point` y, en `addons`, si la ruta es la
  carpeta de una app local (`app: {"slug": "local_<slug>", "installed":
  true|false|null}`; `null` si el Supervisor no responde).
- **FR-010** (D-4) — `fs_read_file_in_folder(folder, path, offset=0,
  limit=500)` lee texto por líneas (`limit` hasta 5000) en streaming, sin
  cargar el fichero entero, y recorta al tope de respuesta (`next_offset`
  cuando quedan líneas). Un binario (byte nulo en los primeros 8 KiB) o un
  texto que no se puede decodificar devuelve solo metadatos
  (`binary: true`, sin contenido). Un directorio → `is_directory`.

**Escritura (todas en dos pasos)**

- **FR-011** (D-5) — Las cuatro tools que modifican
  (`fs_write_file_in_folder`, `fs_create_dir_in_folder`,
  `fs_move_in_folder`, `fs_delete_in_folder`) piden `confirmation_token`
  SIEMPRE. El token ata la tool, `folder`, las rutas ya normalizadas, el
  contenido (escribir) y `recursive` (borrar), y, con `estado`, la huella de
  lo que la vista previa vio (FR-012). En la confirmación se vuelve a calcular;
  si no coincide, `ESTADO_CAMBIADO` y no se toca nada.
- **FR-012** (D-5) — Huellas: un fichero, SHA-256 de su contenido si mide
  hasta 64 MiB y, si no, tamaño, fecha de modificación en ns e inodo; un
  symlink, su destino literal; una ruta inexistente, «ausente»; una carpeta,
  la lista ordenada de (ruta relativa, tipo, tamaño, fecha en ns) de todo su
  contenido, sin seguir symlinks ni entrar en puntos de montaje. Si el
  recorrido pasa de 50 000 entradas o de 10 s, `too_large_to_preview` sin
  token.
- **FR-013** (D-4) — `fs_write_file_in_folder(folder, path, content,
  confirmation_token)` crea o sobrescribe un fichero de texto UTF-8 (crea las
  carpetas padre que falten) con la escritura atómica de `/config`
  (`safe_write_file`: mismas reglas de modo, finales de línea, BOM y salto
  final). Un directorio → `is_directory` sin token. `content` es omitible al
  confirmar, como en `fs_write_file`. La vista previa: si existe, tamaño y
  huella corta (12 hex) actuales; tamaño y huella corta del contenido nuevo;
  `is_blacklisted`; avisos (FR-018, FR-019) y backup (FR-020).
- **FR-014** (D-4) — `fs_create_dir_in_folder(folder, path,
  confirmation_token)` crea la carpeta y sus padres. Si ya existe algo en esa
  ruta → `already_exists` sin token.
- **FR-015** (D-4) — `fs_move_in_folder(folder, src, dst,
  confirmation_token)` mueve o renombra un fichero, symlink o carpeta DENTRO
  de la misma carpeta. Sin token se rechazan: origen inexistente
  (`not_found`), destino existente (`destination_exists`), padre del destino
  inexistente (`destination_parent_missing`), destino dentro del origen
  (`invalid_destination`), raíz como origen o destino (`root_protected`),
  punto de montaje (`mount_point`). La vista previa enseña tipo y, si es una
  carpeta, recuento, tamaño y muestra (FR-016).
- **FR-016** (D-5) — `fs_delete_in_folder(folder, path, recursive=false,
  confirmation_token)` borra un fichero, un symlink o una carpeta vacía; una
  carpeta no vacía exige `recursive=true` (si no, `directory_not_empty` sin
  token). La vista previa de una carpeta da `files`, `dirs`, `symlinks`,
  `total_bytes` y una muestra de hasta 20 rutas relativas (las primeras en
  orden), con `sample_truncated`. La raíz de una carpeta nunca se borra
  (`root_protected` sin token). Un punto de montaje o una carpeta que lo
  contiene → `mount_point` sin token. Si el borrado se queda a medias, la
  respuesta lo dice (`partial: true` y lo que quedó), no `ok`.
- **FR-017** (D-5) — Ningún rechazo de los anteriores emite token. Al
  confirmar se repiten todas las comprobaciones de FR-015, FR-016 y FR-019
  (fail-closed): si algo ya no se cumple, no se hace nada y el token no se
  gasta en vano (se completa con error).

**Avisos, apps locales y backup**

- **FR-018** (D-5) — Toda vista previa de una tool que modifica con
  `folder="addons"` lleva un aviso (`warning`) que dice que esa carpeta es el
  código de las apps locales, que el Supervisor construye y ejecuta.
- **FR-019** (D-5) — Apps locales instaladas (solo en `addons`):
  - el índice de apps locales se calcula como el Supervisor
    (`store/data.py`): cada `config.json|yaml|yml` bajo `/addons`, salvo rutas
    con una parte que empieza por `.` o que se llama `rootfs`, con su `slug`
    → `local_<slug>`; instaladas = las `local_*` de `GET /addons`;
  - borrar o mover una ruta que es o contiene la carpeta de una app local
    instalada, o su `config.*`, se rechaza sin token con `installed_app`, el
    slug y la pista `sv_uninstall_addon`;
  - si el Supervisor no responde y la ruta contiene algún `config.*` →
    `installed_check_failed`; si hay apps `local_*` instaladas cuyo
    `config.*` no aparece en el índice y la ruta contiene algún `config.*`
    ilegible o sin `slug` → `installed_check_inconclusive`;
  - escribir dentro de la carpeta de una app instalada lleva el aviso
    `inside_installed_app` (el cambio se aplica al reconstruirla con
    `sv_rebuild_addon`); escribir su `config.*` con otro `slug` (o con uno
    ilegible) se rechaza con `installed_app`;
  - con el Supervisor caído, escribir un `config.*` se rechaza
    (`installed_check_failed`) y las demás escrituras en `addons` llevan
    `installed_check: "failed"` en la vista previa (no se sabe si el fichero
    es de una app instalada).
- **FR-020** (D-5 backup) — No se hace backup antes de escribir, mover ni
  borrar. Toda vista previa de una tool que modifica dice `backup: null`, que
  la acción no se puede deshacer desde Hermes (salvo crear carpeta) y la
  llamada exacta para hacer antes un backup parcial:
  `sv_create_backup_partial(folders='["addons/local"]')` o
  `sv_create_backup_partial(folders='["share"]')`.

**Privilegios en la vista previa de instalar y reconstruir**

- **FR-021** (D-5 privilegios) — La vista previa de `sv_install_addon` lleva
  `privileges` (forma en data-model.md). `privileges.store`: los campos de
  privilegios de la ficha de la tienda que ya lee
  (`apparmor`, `auth_api`, `docker_api`, `full_access`, `hassio_api`,
  `hassio_role`, `homeassistant_api`, `host_network`, `host_pid`, `ingress`,
  `rating`, `signed`) y `privileges.elevated`, la lista de los que son elevados según
  una regla fija (research R-7). Si el slug es `local_*` y su `config.*` está
  en el índice de `/addons`, añade `privileges.declared_in_folder`: lo que declara el
  fichero (`privileged`, `full_access`, `docker_api`, `host_network`,
  `host_pid`, `host_ipc`, `host_uts`, `host_dbus`, `hassio_api`,
  `hassio_role`, `homeassistant_api`, `auth_api`, `apparmor`, `devices`,
  `map`, `kernel_modules`, `udev`, `usb`, `uart`, `gpio`, `video`, `audio`,
  `ports`), avisando de que el Supervisor usa su copia hasta recargar la
  tienda. Si la ficha no se puede leer, `privileges: null` y el motivo.
- **FR-022** (D-5 privilegios) — La vista previa de `sv_rebuild_addon` lleva
  `privileges` con lo que se aplicará (la ficha de la tienda, que la
  reconstrucción copia: `apps/app.py`, `rebuild`), lo actual de
  `/addons/{slug}/info` (que añade `privileged`, `devices`, `host_ipc`,
  `host_uts`, `host_dbus`, `kernel_modules`, `udev`, `usb`, `uart`, `gpio`,
  `devicetree`, `video` y `audio`), `elevated` y, para `local_*`,
  `declared_in_folder`.
- **FR-023** (D-5 privilegios) — El token de las dos se ata además, con
  `estado`, al bloque `privileges` de la vista previa (en `sv_install_addon`,
  junto a `version_latest`): si cambia antes de confirmar, se rechaza sin
  hacer nada y se pide otra vista previa. El esquema de entrada de las dos no
  cambia (instantánea de la 1.1.2); los textos del autor que haya en el
  bloque pasan por `redact_secrets`.

**Contrato, límites y registro**

- **FR-024** (D-4, V) — Anotaciones honestas: las tres de lectura,
  `readOnlyHint`; las cuatro que modifican, `destructiveHint` (escribir, mover
  y crear carpeta por nombre exacto, borrar por el prefijo `fs_delete_`);
  ninguna de mundo abierto; todas idempotentes (repetida, cada una deja el
  mismo estado o se rechaza sin efecto). Las
  descripciones dicen la carpeta, los dos pasos, la ausencia de backup y los
  rechazos.
- **FR-025** (I) — Toda respuesta respeta `response_max_bytes`; las vistas
  previas tienen tamaño acotado (muestra de 20, huellas cortas, sin
  contenido).
- **FR-026** (II) — El log (`folder_action`) lleva la tool, la carpeta, la
  ruta relativa y el resultado; nunca contenido ni huellas completas.

**Lo que no cambia**

- **FR-027** (D-4) — Las once `fs_*` de `/config` no cambian de nombre,
  esquema, descripción ni comportamiento; sus tests siguen igual. Las 359
  tools de la 1.2.0 conservan sus anotaciones.

**Invariantes del programa**

- **FR-028** (D-6) — Cada tool que modifica tiene su fila «VM / pendiente»
  en la matriz de la 014, su entrada en `FUERA_DEL_BANCO` (motivo: ficheros
  de las carpetas, no hablan con Core) y su apartado en «Tandas de pruebas»
  de `docs/BANCO-SUPERVISOR.md`.
- **FR-029** (D-6) — El inventario de la 033 tiene la fila de cada una de las
  cuatro con lo que ata su token, y el recuento pasa de 145 a 149.
  `sv_install_addon` y `sv_rebuild_addon` no cambian de fila (sus argumentos
  no cambian; el estado va aparte).
- **FR-030** (D-6) — `fs_list_dir_in_folder` usa `sobre_de_lista`, y el test
  transversal de la 018 cubre también las `fs_list_*` nuevas.
- **FR-031** (D-6) — Los tests de familias y del registro admiten familias
  `desde="1.2.1"`: SC-005 de la 008 («sin las nuevas queda la 1.1.2») apaga
  todas las que no son de la 1.1.2.

**Documentación y versión**

- **FR-032** (D-7) — Guía: tema nuevo `folders` (con alias `addons`, `share`,
  `local_apps`), mención en el tema `filesystem` y en la cabecera de las
  instrucciones (`fs_` ya no es solo `/config`), y privilegios en los temas
  `supervisor` y `app_store`; con las huellas de los temas cambiados al día.
  Con la familia apagada, ni el tema ni la mención aparecen.
- **FR-033** (D-7) — `hermes/DOCS.md` (familia, opción y montaje nuevo),
  `SECURITY.md` (superficie nueva), `README.md` y `README.es.md`
  sincronizados (366 tools, fila de la familia, lista de familias de
  `tool_families_disabled`), `docs/HOJA-DE-RUTA.md` (sección de la 1.2.1,
  filas de la matriz y pruebas en vivo pendientes) y el CHANGELOG.
- **FR-034** (D-2) — Versión 1.2.1 en `hermes/config.yaml`,
  `hermes/src/hermes/__init__.py` y `HA_CORE_LAST_TESTED_IN_HERMES`; entrada
  `## [1.2.1] — <fecha de publicación>` encima de la 1.2.0, con sus
  secciones; `tests/test_addon_manifest.py` comprueba la entrada nueva.

### Entidades clave

- **Carpeta**: `addons` o `share`, con su raíz (`/addons`, `/share`) y su
  nombre de backup parcial (`addons/local`, `share`).
- **Huella**: resumen del estado de una ruta (FR-012), atada al token.
- **App local**: carpeta con `config.*`; slug `local_<slug>`; instalada o no.
- **Privilegios**: bloque de la vista previa de instalar y reconstruir, con
  su origen (`store`, `installed`, `declared_in_folder`) y `elevated`.

## Fuera de alcance

- Otras carpetas (`/ssl`, `/media`, `/backup`, `/addon_configs`) (D-1).
- Copiar, buscar con patrón (`grep`) o leer binarios; escribir binarios.
- Mover entre `addons` y `share`.
- Backup automático (R-6); rate limit y bloqueo de reinicio de `/config`
  (D-4).
- Pasar el montaje a `local_apps` (R-1, duda para después).
- Cambiar `sv_install_addon` o `sv_rebuild_addon` más allá de su vista
  previa y del estado del token.

## Supuestos

- El Supervisor 2026.11.0 sigue montando `addons` en `/addons` con la misma
  fuente que `local_apps` (`docker/app.py`).
- El cliente es el mismo actor de siempre: potencialmente manipulable por lo
  que lee (constitución, «Alcance»), por eso todo lo que modifica va en dos
  pasos y la instalación enseña privilegios.
- La prueba en vivo (VM de la 014 y después instalación real) queda
  pendiente en la hoja de ruta.

## Criterios de éxito *(obligatorio)*

- **SC-001** — El borrado recursivo de una carpeta de `/addons` que no es una
  app instalada funciona en dos pasos, y el de una que sí lo es se rechaza
  sin token, en el 100 % de los casos de prueba (incluidos los de Supervisor
  caído y `config.*` ilegible).
- **SC-002** — Ninguna de las siete tools sale de su carpeta: cero
  escrituras, lecturas o borrados fuera de la raíz en los tests de
  traversal, symlink y byte nulo (los mismos casos que en `/config`).
- **SC-003** — Cualquier cambio entre vista previa y confirmación (fichero
  creado, modificado o borrado dentro del objetivo; privilegios de la app)
  hace que la confirmación no toque nada.
- **SC-004** — Con `addons_share` apagada, la lista de tools es idéntica a la
  de la 1.2.0 y con las mismas anotaciones; la instantánea de esquemas de la
  1.1.2 no cambia.
- **SC-005** — La suite completa pasa (en Windows, con solo los 6 fallos
  conocidos; en el CI de Linux, en verde), con un control negativo anotado
  por cada protección nueva.
- **SC-006** — La documentación cuenta 366 tools en los tres sitios y nombra
  la familia nueva; la hoja de ruta tiene las cuatro filas «VM / pendiente».
