# Investigación: banco de pruebas del Supervisor (spec 014)

**Fecha**: 2026-11-14 · **Fuentes**: spec 008 (FR-016, FR-017, CAP-006,
CAP-022, CAP-034, CAP-035, D-02, D-06), research de la 008 (R-0 punto 4, R-1,
R-5 b), specs 010 y 028 (inventarios del banco), código del Supervisor
2026.11.0 en `fuentes/supervisor` (solo leído), código de Hermes en la punta de
`feat/cobertura-total` (`cc478d4`).

Línea base de la suite en Windows sobre `cc478d4`: 2080 pasados, 38 saltados,
6 fallos (los 6 conocidos).

## R-1 — Qué tools entran en la matriz

- **Decisión**: todas las que modifican: las del registro de producción
  (`_build_mcp(HermesConfig(call_service_auto_classify_dangerous=False),
  MagicMock())`, todas las familias activas) sin `readOnlyHint` en la tabla
  central de anotaciones. Hoy son 124: 47 de helpers (010), 53 `ha_*` de la
  028 y 24 `sv_*`/`fs_*`.
- **Por qué**: CAP-034 pide «matriz tool → entorno → resultado» para las tools
  que modifican, y FR-016 de la 008 la quiere con «CI de Core, simuladores, VM,
  instalación real». Si solo tuviera las 24 del Supervisor, una `sv_*` nueva
  (015, 019, 022, 030, 031, 032) podría entrar sin fila y nadie lo vería. Con
  todas, la regla es la misma que la del banco: ninguna tool que modifica sin
  decir dónde se prueba de verdad.
- **«Modifica»**: la misma definición que la 010 (T045) y la 028: sin
  `readOnlyHint`, no el prefijo. Comprobado con el registro: de las 24 de
  fuera del banco, 19 son `sv_*` (incluidas `sv_check_core_config` y
  `sv_get_job_status`, que la tabla de anotaciones marca como de escritura) y
  5 `fs_*` (`fs_write_file`, `fs_delete_file`, `fs_move_file`,
  `fs_restore_file_backup`, `fs_set_secret`).
- **Alternativas**: solo las 24 (descartada por lo dicho); una matriz por
  grupos de tools (descartada: no se puede comprobar fila a fila y esconde la
  tool que falta).

## R-2 — Cómo se mantiene la matriz al día

- **Decisión**: la matriz vive en `docs/HOJA-DE-RUTA.md` como tabla Markdown
  entre dos comentarios HTML (`<!-- matriz-pruebas:inicio -->` y
  `<!-- matriz-pruebas:fin -->`), y un test de la suite normal la lee y la
  compara con el registro y con los inventarios del banco. Los inventarios se
  descubren importando cada `tests/banco/cobertura*.py` y leyendo sus nombres
  en mayúsculas por convención: `PROBADAS*` (conjunto), `FALLAN*` y
  `NO_EJECUTABLES*` (diccionarios tool → motivo) y `FUERA_DEL_BANCO`. Las
  constantes auxiliares (`DOMINIOS_HELPERS`, `MODULOS_HELPERS`,
  `XFAIL_PERMITIDOS`, `PENDIENTES_TRAMO_B`) no son inventario de resultado y se
  ignoran por nombre.
- **Por qué**: FR-016 pide la matriz en la hoja de ruta (documento para
  personas), y el principio VI pide que el invariante se compruebe solo. El
  descubrimiento por convención hace que, cuando la 028 (hoy en su rama, con
  `tests/banco/cobertura_escrituras.py`) se integre en una rama que ya tiene
  la 014, el test caiga hasta que las 53 filas de la 028 pasen de «pendiente»
  a «ok»: la matriz no puede quedarse diciendo menos de lo que hay. La 028 ya
  fija la convención para las sub-features siguientes
  (`tests/banco/cobertura_<NNN>.py`).
- **Orden de integración**: si la 014 se implementa con la 028 ya integrada,
  las 53 entran directamente como «ok» y las 24 de `FUERA_DEL_BANCO` como
  «VM»; si no, entran como «banco de Core / pendiente» y la integración de la
  028 las pone al día. Las dos cosas las fuerza el mismo test.
- **Alternativas**: un módulo Python con la matriz y la hoja de ruta generada
  de él (dos fuentes que sincronizar, y FR-016 la quiere en la hoja de ruta);
  importar explícitamente `cobertura_escrituras` (rompe la 014 en una rama sin
  la 028, o al revés).

## R-3 — Procedimiento de la VM, sin automatizar

- **Decisión**: `docs/BANCO-SUPERVISOR.md`, con los comandos dentro del texto
  y sin scripts versionados. Contenido mínimo en
  [contracts/procedimiento.md](contracts/procedimiento.md).
- **Por qué**: la decisión del supervisor prohíbe montar la VM o automatizar
  nada que cambie el sistema del mantenedor; un script que no se ejecuta en
  ningún sitio es código sin probar (principio VI) que alguien puede lanzar
  sin leer. Los comandos en el texto se leen y se ejecutan uno a uno.
- **Hechos del código del Supervisor 2026.11.0 que usa el procedimiento**:
  - El Supervisor no se puede fijar (corregido en la convergencia, T017).
    `POST /supervisor/update` solo respeta `version` en el modo de desarrollo
    (`SUPERVISOR_DEV=1`); fuera de él actualiza a la última
    (`supervisor/api/supervisor.py`, `update`). Desactivar `auto_update`
    tampoco sirve: con un Supervisor más nuevo publicado, `need_update` hace
    que la condición `SUPERVISOR_UPDATED` (`supervisor/jobs/decorator.py`)
    bloquee `app_manager_install` y `app_manager_update`
    (`APP_UPDATE_CONDITIONS`, `supervisor/apps/const.py`),
    `store_manager_reload` (`supervisor/store/__init__.py`) y
    `home_assistant_core_update` (`supervisor/homeassistant/core.py`). Se
    puede ignorar con `POST /jobs/options` `ignore_conditions`, que marca el
    sistema como no soportado (`job_conditions`) y se deshace con
    `ignore_conditions: []` o `POST /jobs/reset`. `POST /core/update` sí
    acepta `version`.
  - Las apps locales viven en `apps/local` del directorio de datos del
    Supervisor (`supervisor/config.py`, `APPS_LOCAL`), que el add-on de
    terminal y SSH ve como `/addons` (mapeo heredado) o `/local_apps`
    (`supervisor/docker/const.py`). El slug de una app local lleva el prefijo
    `local_` (`REPOSITORY_LOCAL`): Hermes ya protege `local_hermes`.
  - Sin `image:` en el manifiesto, el Supervisor construye la imagen desde el
    `Dockerfile` (comentario de `hermes/config.yaml`).
- **Hechos de Hermes que usa el procedimiento**: el emisor OAuth es
  `https://<public_hostname>` (`__main__.py`), así que el cliente necesita TLS
  delante como en producción (por defecto `tailscale serve` con el add-on de
  Tailscale en la VM, un nombre de máquina propio y un tailnet de pruebas;
  Funnel solo con aviso, porque publica un Hermes `admin` en internet; o un
  proxy local con certificado de confianza; corregido en la convergencia,
  T018);
  `network_mode` y `mcp_bind` como en `hermes/DOCS.md`; el `/data` del add-on
  es accesible desde la VM (lo pide la prueba de la limpieza de
  confirmaciones de CAP-035).
- **Hipervisores**: Hyper-V (el mantenedor trabaja en Windows; imagen `vhdx`,
  generación 2, arranque seguro desactivado, `Checkpoint-VM` /
  `Restore-VMCheckpoint`) y QEMU/libvirt (`qcow2`, UEFI; la instantánea es una
  copia del `qcow2` y del `nvram` con la VM apagada, porque libvirt no admite
  instantáneas internas con firmware `pflash`; corregido en la convergencia,
  T022). Otros (VMware, VirtualBox), con
  una línea de referencia a la documentación oficial de HAOS.
- **Alternativas**: devcontainer del Supervisor (descartado en la 008 R-5 b:
  Docker dentro de Docker, frágil y sin soporte para esto); VM en el CI con KVM
  (D-06, duda para el final).

## R-4 — El comentario de `hassio_role` y qué se puede comprobar sin la VM

- **Lo que dice hoy** (`hermes/config.yaml`): «'admin' es el único rol que da
  acceso garantizado a /addons/self/options/config (necesario para
  bashio::config). Probado: 'manager' y 'default' devuelven 403 Forbidden.»
- **Lo que dice el Supervisor 2026.11.0** (`supervisor/api/middleware/security.py`,
  `_V1_PATTERNS`): `api_bypass` incluye `^/addons/self/options/config$`, y
  `SecurityMiddleware` lo comprueba **antes** que el rol y antes incluso de
  `access_hassio_api`: pasa con cualquier rol. El patrón de `manager` cubre
  `/.+/info`, `/addons(/<slug>/(?!security).+|/reload)?`, `/backups.*`,
  `/core/.+`, `/host/.+`, `/jobs/.+`, `/resolution/.+`, `/store.*`,
  `/supervisor/.+` y más; `admin` es `.*`. Lo que solo da `admin`:
  `/addons/{app}/security`, `/auth/list`, `/auth/reset`, `/os/datadisk/wipe`,
  `/ingress/panels` (y lo que no está en ninguna lista).
- **Lo que hace Hermes**: `hermes/run.sh` dice expresamente que no usa
  `bashio::config` y lee `/data/options.json` con `jq`. El docstring de
  `hermes/src/hermes/config.py` todavía dice «con bashio» (hallazgo fuera de
  alcance, ver spec).
- **Rutas del Supervisor que usa Hermes hoy** (llamadas a `sv_request` y
  `sv_request_text`): `/info`, `/core/info`, `/core/check`, `/core/restart`,
  `/host/info`, `/host/reboot`, `/supervisor/info`, `/resolution/info`,
  `/resolution/{clase}/{uuid}`, `/jobs/{id}`, `/addons`, `/addons/{slug}/info`,
  `/addons/{slug}/stats`, `/addons/{slug}/logs`, `/addons/{slug}/options`,
  `/addons/{slug}/start|stop|restart|uninstall`, `/store/addons`,
  `/store/addons/{slug}/install|update`, `/backups`, `/backups/new/full|partial`,
  `/backups/{slug}`, `/backups/{slug}/info`, `/backups/{slug}/restore/full|partial`;
  y el proxy de Core: `/core/api/...` y `/core/api/websocket` (en
  `no_security_check`, y además dentro de `/core/.+`). Todas casan con
  `api_bypass` o con `manager`: la lista de excepciones se espera vacía.
- **Decisión**: el comentario nuevo dice esos hechos y que el rol se mantiene
  `admin` hasta probar `manager` en vivo (D-02); un test en
  `tests/test_addon_manifest.py` lo ata (rol, ausencia de «403» y de la
  dependencia de `bashio::config`, presencia de `api_bypass` y de la remisión
  a la prueba pendiente), y otro, `tests/test_rutas_supervisor_rol.py`,
  comprueba las rutas contra los patrones copiados. El segundo no sustituye a
  la prueba en vivo: comprueba lo que dice el código de 2026.11.0, no lo que
  hace un Supervisor real; por eso la casilla manual sigue.
- **Extracción de rutas**: con `ast` sobre `hermes/src/hermes/**/*.py`, cada
  llamada cuyo atributo sea `sv_request` (ruta en el segundo argumento o en
  `path=`) o `sv_request_text` (primero o `path=`); un `Constant` se toma tal
  cual y un `JoinedStr` sustituye cada hueco por un slug de ejemplo (`x`). Una
  ruta que no es literal ni f-string (una variable) hace caer el test salvo
  que su función esté en una lista de llamadas declaradas con el origen de sus
  rutas: es el caso de `sv_read_api`/`sv_call_api` de la 011, cuyas rutas
  salen de `SUPERVISOR` en `hermes/src/hermes/command_table.py`; el test
  comprueba las entradas `read` y `confirm` de esa tabla cuando el módulo
  existe en la rama. Si alguna de la tabla queda fuera de `manager`, va a la
  lista de excepciones con su motivo y el comentario la nombra.
- **Alternativas**: grabar las rutas que llegan al simulador del Supervisor en
  la suite (cubre solo lo que los tests ejercitan; más intrusivo); no
  comprobar nada y dejarlo todo a la prueba manual (el comentario volvería a
  afirmar algo sin prueba, que es justo el error que se corrige).

## R-5 — Pruebas manuales abiertas (CAP-035) y su entorno

Comprobado en la hoja de ruta de `cc478d4`: ya existen casillas para las 7 de
CAP-035; ninguna dice su entorno. Decisión, una etiqueta por casilla:

| Prueba | Entorno |
|---|---|
| `sv_get_resolution` con issues o sugerencias reales; trazas de un script | VM (se pueden provocar) o instalación real |
| CIMD con Claude Code | cliente contra la VM o la instalación real |
| Primer byte tras el proxy (90 s) | cliente contra la instalación real (depende del proxy de producción) |
| Clave `homeassistant` en una HA antigua | VM con Core anterior a 2024.10 (`ha core update --version`) |
| Funnel en el 8443 | instalación real (depende del tailnet y de Funnel) |
| `fs_write_file` sin documento y limpieza del directorio de confirmaciones | VM (acceso a `/data` del add-on) |
| `hassio_role: manager` | VM, después instalación real |

Casillas nuevas para SC-011 de la 008: «la matriz del Supervisor en la VM» y
«pruebas en vivo de las tools nuevas del programa, tras publicar». La de «las
13 tools de escritura de la 1.1.x» y la de «`sv_update_addon` sobre Hermes» se
quedan; la primera queda cubierta por la matriz y remite a ella.

## R-6 — Qué no se toca

- `hassio_role` (D-02), la VM en el CI (D-06), el docstring de `config.py`
  (código de producto, fuera de FR-017).
- La tabla de clasificación (011) y las familias: la 014 no añade tools.
- Los inventarios del banco: la matriz los lee, no los cambia.
