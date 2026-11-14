# Investigación: diagnóstico del Supervisor (013)

Decisiones de diseño con su porqué y las alternativas descartadas. Todo
comprobado contra el código de Hermes de la rama (base: la 011) y contra el
código del Supervisor 2026.11.0 (solo leído).

## Lo que hay hoy (comprobado en el código)

- **`sv_get_addon_logs(slug, lines=100)`** (`tools/addons.py`): pide
  `GET /addons/{slug}/logs?lines=N` con `sv_request_text`, acota `lines` a
  [1, 1000], aplica `redact_secrets` y, si el add-on es Hermes (`_es_hermes`,
  que reconoce también `self`), `redact_network`. Si el log no cabe en
  `response_max_bytes`, `_ultimas_lineas_que_caben` devuelve las últimas
  líneas con `truncated`, `lines_returned` y una pista. Deja un evento con
  `slug`, `lines`, `bytes` y `redacted`.
- **`sv_request_text`** (`ha.py`): `GET` con `params`, `_assert_safe_request_path`
  (sin `..`, `%`, `#`, `?`), error HTTP → `HAConnectionError` con `status`.
- **Tabla de la 011** (`command_table.py`): 31 entradas del Supervisor con el
  motivo «pendiente de tool dedicada (spec 013)» (las 28 de data-model, más
  `/host/disks`, `/jobs/info` y `/resolution/issue/{issue}/suggestions`).
  Las rutas de CAP-088 y CAP-089 ya son `read` (revisión manual de la 011),
  y `POST /security/integrity` es `deny` («eliminada en el Supervisor
  2026.11»). `test_clase_a_de_via_dedicada_pendiente_de_su_spec` exige que
  toda clase A de vía D/D+T/D+X sea `deny` «pendiente de tool dedicada»: hay
  que adaptarlo.
- **Familias** (`tool_families.py`): catálogo con `generic_commands` como
  única familia 1.2.0. `tests/test_command_table.py::TestDedicadas` comprueba
  que la tool de cada entrada `dedicated` está registrada y que la familia de
  la entrada es la del módulo que la registra.
- **Anotaciones**: `sv_get_` y `sv_list_` son prefijos de solo lectura.
  `_TITLE_WORDS` no tiene `os`: `sv_get_os_info` saldría «Get os info».
- **Guía**: temas en español; alias `host`, `core` y `system` ya apuntan a
  `supervisor`.
- **Línea base de la suite en esta rama** (Windows): 2021 passed, 16 skipped,
  6 failed (los 6 conocidos).

### Supervisor 2026.11.0

- `_register_advanced_logs(path, identifier)` registra para `/core`
  (`homeassistant`), `/dns` (`hassio_dns`), `/audio` (`hassio_audio`) y
  `/multicast` (`hassio_multicast`): `logs`, `logs/follow`, `logs/latest`,
  `logs/boots/{bootid}`, `logs/boots/{bootid}/follow`. El Supervisor tiene las
  mismas rutas con un manejador propio que, si el journal falla, cae al log de
  su contenedor descartando `follow`, `latest` y `no_colors` (el `bootid` de la
  ruta tampoco se usa). `cli` y `observer` **no** tienen log.
- Host: `/host/logs`, `/host/logs/boots`, `/host/logs/boots/{bootid}`,
  `/host/logs/identifiers`, `/host/logs/identifiers/{identifier}`,
  `/host/logs/boots/{bootid}/identifiers/{identifier}` (más `follow`). No hay
  `latest` en el host.
- Add-ons: `/addons/{app}/logs[/latest|/boots/{bootid}]` con los
  identificadores `addon_<slug>` y `app_<slug>`.
- `advanced_logs_handler`: `lines` en la query → `Range: entries=:-(N-1):N`
  (mínimo 2); `latest` exige un identificador y añade `CONTAINER_LOG_EPOCH`;
  `bootid` pasa por `_get_boot_id`: un entero es un **desplazamiento** (0 =
  actual, negativo hacia atrás, positivo desde el más antiguo; fuera de rango
  → `APIError` «Logs only contain N boots»), y cualquier otro texto se usa
  como identificador de arranque tal cual. La respuesta es `text/plain`; los
  errores, texto (`api_process_raw(..., error_type=CONTENT_TYPE_TEXT)`).
- `list_boots` → `{"boots": {"0": id, "-1": id, …}}`; `list_identifiers` →
  `{"identifiers": [...]}`.
- `/host/services` → `{"services": [{name, description, state}]}`.
- `/host/disks/{disk}/usage`: `disk` = `default` (disco del sistema, reservado)
  o nombre de montaje (`^[A-Za-z0-9_]+$`); `max_depth` en la query (por
  defecto 1 en el sistema y 0 en un montaje; un valor no entero cae al
  defecto). El sondeo de un montaje espera hasta 60 s (`MOUNT_USAGE_TIMEOUT`).
  En v1 los ids `apps_data`/`apps_config` salen como `addons_data`/
  `addons_config`. Cada nodo: `id`, `label`, `used_bytes`, `children`.
- `/os/info`, `/os/config/swap` (HAOS ≥ 15; si no, `APINotFound`),
  `/os/datadisk/list` (`devices` y `disks` con `name`, `vendor`, `model`,
  `serial`, `size`, `id`, `dev_path`). Sin HAOS, `/os/*` responde 404.
- `/host/disks` → discos locales con particiones montables (para crear
  montajes).
- `/jobs/info` → `{ignore_conditions, jobs: [...]}` con todos los jobs.
- `/resolution/issue/{issue}/suggestions` → `{"suggestions": [...]}`.
- `POST /security/integrity` → `APIGone` («Integrity check feature has been
  removed»).

## R-1 — Una familia, dos módulos

**Decisión**: familia `system_diagnostics` («Supervisor, Core, host and plugin
logs; host services, disk usage, OS and swap (read only).», desde 1.2.0,
desactivable) con los módulos `system_logs` (6 tools de CAP-081) y
`host_system` (5 de CAP-085). Tema de guía `system_diagnostics`.

**Por qué**: FR-010 de la 008 pide familias nuevas para las tools nuevas, y
FR-011 un tema por familia. Las 11 tools son un mismo caso de uso
(diagnosticar el sistema) y caben en un tema; dos familias de 6 y 5 tools
obligarían a dos temas casi vacíos. Dos módulos mantienen cada tramo en su
fichero.

**Alternativas**: meterlas en `supervisor` (rompe FR-010: desactivar las
nuevas no dejaría la lista de la 1.1.2); dos familias (más superficie sin
ganancia).

## R-2 — Argumentos comunes de las tools de logs

**Decisión**:

- `lines: int = 100`, acotado a [1, 1000] como `sv_get_addon_logs` (el
  Supervisor devuelve al menos 2).
- `boot: int | str | None = None`. Entero de -999 a 999 → desplazamiento
  (se envía tal cual, `0` incluido); texto que es un entero con esa forma
  (`"-1"`) → igual; texto de 32 caracteres hexadecimales → identificador en
  minúsculas. Cualquier otra cosa → `invalid_argument`.
- `latest: bool = False` en Core, Supervisor, plugins y add-ons. `latest` y
  `boot` a la vez → `invalid_argument` (no hay ruta que combine los dos).
- `identifier: str | None = None` solo en el host, con
  `^[A-Za-z0-9_@-][A-Za-z0-9._@-]{0,63}$`: los identificadores de syslog
  habituales (`kernel`, `systemd-journald`, `NetworkManager`,
  `hassio_supervisor`, `addon_<slug>`) caben; no puede empezar por punto
  (`.`/`..`) ni llevar `/`, `%`, `?`, `#` o espacios. Es la primera capa;
  `_assert_safe_request_path` sigue siendo la segunda.
- `plugin` de `sv_get_plugin_logs`: `dns`, `audio` o `multicast`.

**Por qué**: el Supervisor acepta cualquier texto como identificador de
arranque y lo pasa al journal; validar la forma antes evita mandar basura y
cierra cualquier rareza de ruta (principio III). El desplazamiento es lo que
un agente necesita de verdad («el arranque anterior»), y `sv_list_boots` da
los identificadores si hacen falta. El rango ±999 sobra para cualquier
journal real y evita enteros enormes.

**Alternativas**: un parámetro `previous_boot: bool` (no deja pedir el
antepenúltimo); aceptar cualquier texto (sin primera capa).

## R-3 — `sv_get_addon_logs` gana `boot` y `latest`

**Decisión**: dos argumentos opcionales en la tool existente, con la misma
validación que R-2. Sin ellos, la petición (`/addons/{slug}/logs?lines=N`) y
la respuesta son las de la 1.1.2. La respuesta gana `route` solo cuando se usa
`boot` o `latest`, para no cambiar la forma de la 1.1.2.

**Por qué**: lo pide FR-044 de la 008 y FR-020 exige que los argumentos nuevos
sean opcionales con el comportamiento de la 1.1.2 por defecto. Una tool aparte
(`sv_get_addon_boot_logs`) duplicaría la redacción de Hermes y su autodetección.

**Consecuencia**: la instantánea de esquemas de la 011
(`tests/fixtures/esquemas_1_1_2.json`) gana una diferencia permitida y
comentada: `boot` y `latest` opcionales en `sv_get_addon_logs`.

## R-4 — Uso de disco acotado

**Decisión**: `max_depth` de 0 a 3 (por defecto 1, el del Supervisor para el
disco del sistema); fuera de rango → `invalid_argument`. Poda en Hermes: en
cada nodo, los 20 hijos con más `used_bytes` (empate por `id`), y si se quitan
otros, `children_omitted` y `omitted_bytes`. Tiempo de espera de la petición:
75 s (el Supervisor espera hasta 60 s por un montaje lento y luego da error).

**Por qué**: la 008 pide «profundidad acotada». Con profundidad 3, una carpeta
con miles de subcarpetas da un árbol que no cabe en el tope; el tope central
solo recorta listas del primer nivel y aquí daría `response_too_large`. Lo útil
para «qué llena el disco» son las carpetas grandes; lo omitido se resume para
que la suma cuadre y no se mienta.

**Alternativas**: dejar el árbol entero (falla con `response_too_large`);
aplanar a una lista (pierde la jerarquía).

## R-5 — Lo que va por la tabla

**Decisión**:

- `GET /jobs/info` → `read` (CAP-087): «todos los jobs del Supervisor
  (nombre, progreso, estado, errores, hijos) y si se ignoran condiciones; solo
  lee». FR-046 de la 008 lo pide en la tabla; la 011 lo había dejado
  pendiente de la 013 porque el research de la 008 nombraba una
  `sv_list_jobs`. Manda FR-046: es una lectura de prioridad media y la forma
  del Supervisor ya es un objeto con una lista, que el tope recorta bien.
- `GET /resolution/issue/{issue}/suggestions` → `read` (CAP-087): «sugerencias
  que arreglan un issue; solo lee». `sv_get_resolution` ya trae las
  sugerencias; esta ruta solo filtra.
- `GET /host/disks` → `read` (CAP-085): «discos locales con particiones
  montables (para crear montajes); solo lee». No tiene tool en el research de
  la 008, sirve a los montajes de la 019 y es una lectura menor: la regla de
  reparto de la 008 lo permite si la sub-spec lo justifica.
- El test `test_clase_a_de_via_dedicada_pendiente_de_su_spec` pasa a admitir,
  para la clase A de vía D/D+T/D+X: `deny` «pendiente de tool dedicada (spec
  NNN)» con NNN de la matriz, `dedicated`, o `read`/`confirm` si la clave está
  en un diccionario `_POR_LA_TABLA` del test con la spec y el porqué (aquí las
  tres de arriba).

**Por qué**: es la regla de la 008 («dentro de una CAP dedicada, sus lecturas
menores pueden ir por la tabla si la sub-spec lo justifica»), y dejar la
justificación en el test la hace visible y obliga a la siguiente sub-feature a
dar la suya.

## R-6 — Comprobación de integridad

**Decisión**: `POST /security/integrity` sigue `deny`. Desviación de FR-047 de
la 008 («`confirm`»): el Supervisor 2026.11.0 eliminó la función y la ruta
responde 410 Gone. Un `confirm` daría una vista previa con token para algo que
siempre falla. Se anota en la matriz de la 008 y en el CHANGELOG.

## R-7 — Números de serie y direcciones

**Decisión**: las respuestas de `sv_list_datadisk_candidates` y de
`/host/disks` llevan `serial` tal cual; ningún evento de log lleva datos de la
respuesta (solo recuentos y bytes). En la red del host, la genérica de la 011
ya registra solo la plantilla de la ruta, la categoría y los bytes; la 013
añade el test que lo comprueba con una respuesta con IPs, MAC y SSID ficticios
(`192.0.2.x`, `02:00:00:00:00:01`, `red-ficticia`).

**Por qué**: el número de serie no es un secreto (principio II) y el `id` del
disco ya lo contiene; taparlo solo en `serial` sería redactar a medias y daría
una falsa sensación de privacidad. El usuario necesita distinguir discos
iguales. Lo que no debe pasar es que acabe en el log, que se pega en issues
públicos (principio VIII).

## R-8 — Errores

**Decisión**: `HAConnectionError` → `{"error": <mensaje redactado con
redact_secrets>}` y, si `status` es 404 en una ruta `/os/*`, `hint`: «Requires
Home Assistant OS (swap needs OS 15 or newer).». Un argumento inválido →
`{"error": "invalid_argument", "field": <argumento>, "detail": <regla>}` sin
llamar al Supervisor, con la forma que ya usan las tools de la 1.1.2
(`tools/lovelace.py`, `tools/ha_backups.py`); un `slug` inválido sigue dando
`invalid_identifier` como hoy (`_bad_slug`).

**Por qué**: el mensaje del Supervisor puede repetir parte de la petición; se
redacta igual que el log. La pista evita que el agente reintente algo que no
puede funcionar en una instalación Supervised.

## R-9 — Pruebas

- **Unitarias con un Supervisor simulado**: un `MockHAClient` (el patrón de
  `tests/test_tools_supervisor.py`) que registra método, ruta, `params` y
  tiempo de espera, con respuestas que reproducen la forma del Supervisor
  2026.11.0 en `tests/fixtures/supervisor_diagnostico.py` (datos ficticios).
  Lo que se comprueba es la ruta y los parámetros que Hermes manda, la
  validación y lo que Hermes hace con la respuesta (redacción, recorte, poda,
  orden).
- **Genéricas**: las rutas `read` de FR-018…FR-020 se ejecutan por
  `sv_read_api` con el mismo simulado; `POST /security/integrity` por las dos
  genéricas, sin llamada.
- **Banco de la 010**: no aplica (su Supervisor simulado solo reenvía a Core) y
  ninguna tool de esta sub-feature modifica nada, así que no entran en el
  inventario «ninguna tool que modifica sin probar en el banco».
- **En vivo**: pendiente para la 014 o el cierre del programa, con su casilla
  en la matriz de la hoja de ruta (SC-011 de la 008).
- **Control negativo** por tramo, con recuentos (principio VII).
