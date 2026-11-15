---

description: "Tareas de la sub-feature 032 — host y red del host (Hermes 1.2.0)"
---

# Tareas: host y red del host (032)

**Entrada**: `specs/032-host-y-red-del-host/` (spec.md, plan.md, research.md,
data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `DummyMCP`, un
`MockHAClient` como **Supervisor simulado** (guarda método, ruta y
`json_body`; responde por método y ruta; lanza `HAConnectionError` con
`status`) con la forma del Supervisor 2026.11.0, `capture_logs` y el
`CONFIRMATIONS_DIR` temporal de `tests/conftest.py`. Solo datos genéricos:
`192.0.2.x`, `2001:db8::`, `aa:bb:cc:dd:ee:ff`, «mi-red», `homeassistant`,
`casa-ha`, y la PSK centinela `PSK-CENTINELA-032`.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" <python del .venv del checkout principal> -m pytest -q -p no:cacheprovider`.
Línea base al especificar (2026-11-15, `feat/cobertura-total` en `0b7d5e2`):
3172 passed, 106 skipped, 6 failed (los 6 conocidos de Windows);
`grep -c "spec 032" hermes/src/hermes/command_table.py` = 7. Cada tramo anota
su línea base al empezar y termina con exactamente esos 6 fallos en local; la
referencia es el CI de Linux.

**Requisito previo**: 011, 013, 014 y 033 integradas (lo están en la base). El
tramo 2 necesita además el HMAC de la 019 (T014). Si falta, el agente se
detiene y lo anota.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias: US1 apagar, US2 hostname, swap y ranura, US3 segunda interfaz y
VLAN, US4 nada de lo actual cambia.

## Tramos de implementación

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **1** — `host_control` (CAP-086) | **T001–T013** | `sv_shutdown_host`, `sv_set_hostname`, `sv_set_swap`, `sv_set_boot_slot`; token atado a argumentos y estado; 4 `dedicated`; inventario de la 033; 4 filas de la matriz; tema de guía (host); documentación (parte) |
| **2** — `host_network` (CAP-090) | **T014–T027** | `sv_reload_network`, `sv_update_network_interface`, `sv_create_vlan`; guarda de la interfaz de acceso; PSK que no sale; 3 `dedicated` y ninguna «spec 032»; 3 filas; guía y documentación completas; filas de la 008 |

El tramo 2 necesita el tramo 1 integrado.

---

## Tramo 1 — `host_control` (CAP-086)

### Preparación

- [x] T001 Línea base: comprobar el requisito previo, ejecutar la suite y anotar passed/skipped/failed y la punta; `grep -c "spec 032" hermes/src/hermes/command_table.py` = 7
- [x] T002 [P] [US4] Tests en `tests/test_tool_families.py` (`host_control` existe, `desde="1.2.0"`, desactivable, módulos `("host_control",)`, `familia_de_modulo`) y en `tests/test_config_validation.py` (`tool_families_disabled: [host_control]` válido). Después, la familia en `hermes/src/hermes/tool_families.py` con el porqué (research R-1) (FR-015)
- [x] T003 [P] Fixtures en `tests/fixtures/supervisor_host.py`: `GET /host/info` (`hostname: "homeassistant"`, `disk_free` en GiB), `GET /os/config/swap` (`1G`, 1) y su 404, `GET /os/info` con ranuras A (booted, good, 17.0) y B (inactive, bad, 17.1) y variantes (B sin versión, sin B), errores del Supervisor (migración de la base de datos en curso, hostname inválido) y formas inesperadas. Solo datos genéricos (FR-019)

### Tests (escritos antes, en rojo)

- [x] T004 [P] [US1] [US2] `TestApagar`, `TestHostname`, `TestSwap` y `TestRanura` en `tests/test_tools_host_control.py`: (a) vistas previas con los campos y avisos de data-model, sin ninguna llamada que no sea GET; `sv_shutdown_host` dice que nadie puede encenderlo a distancia y que se corta Hermes; (b) confirmación → `POST` con la carga exacta (`/host/shutdown` con `{}` y sin `force`; `/host/options` `{"hostname"}`; `/os/config/swap` solo con lo pasado; `/os/boot-slot` `{"boot_slot": "B"}` aunque se pase `"b"`); (c) `invalid_argument` sin llamar para cada regla de FR-002…FR-004 (hostname con mayúsculas, espacio, punto, `-` al borde, 64 caracteres, vacío, no `str`; swap sin argumentos, `swap_size` `"2T"`, `"-1"`, `swappiness` 201, -1, `True`; ranura `"C"`), sin el valor en el mensaje; (d) `no_change` (hostname igual, swap igual), `insufficient_disk`, aviso de `"0"`, `not_supported` (404 en swap y en `/os/info`), `already_booted`, `slot_unusable`, aviso de ranura `bad`; (e) migración en curso → error redactado y ningún reintento con `force` (FR-001…FR-004)
- [x] T005 [US1] [US2] `TestTokenAtado`, `TestCorteTrasEnviar` y `TestLog` en `tests/test_tools_host_control.py`: (a) confirmar con otro hostname, otra swap u otra ranura → no se ejecuta; (b) entre vista previa y confirmación cambia el hostname, la swap o las ranuras → no se ejecuta y pide otra vista previa; si solo cambia `disk_free` el token sigue valiendo, pero `insufficient_disk` se vuelve a comprobar al confirmar; un cambio de `wifi.signal` o `ready` no invalida el token de red (lo prueba T019); (c) `HAConnectionError` tras enviar `shutdown` o `boot-slot` → `outcome: "unknown"` con `hint` y `verify_with`, token completado como fallido; en la lectura previa → `error` sin token; (d) los eventos no llevan `homeassistant`, `casa-ha`, `1G` ni versiones de OS de los fixtures y sí `tool`, `outcome`, `changed` (FR-011…FR-013)

### Implementación

- [x] T006 [US1] [US2] `hermes/src/hermes/tools/host_control.py` con las cuatro tools según contracts/tools.md: validadores, lecturas, huella como `estado=`, `create_confirmation_token` sin `omitibles`, `_enviar` con `outcome: "unknown"`, eventos `host_control`, descripciones en inglés que dicen lo que hacen (sin `force`; nadie enciende a distancia; la ranura reinicia ya). Comentarios en español con el porqué. T004–T005 en verde
- [x] T007 [US4] Registro y anotaciones: tests primero en `tests/test_tools_registration.py` (las 4 registradas por defecto y ninguna con `host_control` desactivada; las 4 `destructiveHint`; títulos «Shut down host (Supervisor)», «Set hostname (Supervisor)», «Set swap (Supervisor)», «Set boot slot (Supervisor)»; el invariante destructiva ⇔ token en verde); después `tools/__init__.py` (`_activa("host_control")`) y `_DESTRUCTIVE_EXACT` con comentario (FR-016)
- [x] T008 [US4] Tabla: tests primero en `tests/test_command_table.py` (las 4 rutas de data-model `dedicated` con su tool, familia `host_control` y `cap="CAP-086"`), `tests/test_tools_generic_commands.py` (`sv_call_api("POST", "/host/shutdown")` y `("POST", "/os/boot-slot", …)` → `use_dedicated_tool` sin llamada; con la familia desactivada, `family_disabled`) y `tests/test_generar_tabla.py` si compara el mapa. Después, las 4 claves en `_DEDICADAS_INICIALES` de `scripts/inventario/generar_tabla.py` y en `hermes/src/hermes/command_table.py`; regenerar y `git diff --exit-code` sobre la tabla. `grep -c "spec 032"` = 3 (FR-014)
- [x] T009 Inventario de la 033: `sv_shutdown_host` (solo `confirmation_token`, exento como en `sv_reboot_host`), `sv_set_hostname`, `sv_set_swap`, `sv_set_boot_slot` (todo `atado`; `boot_slot` normalizado) con el comentario de la huella; `test_recuento` + 4 (FR-011)
- [x] T010 [P] Matriz de la 014: en `docs/HOJA-DE-RUTA.md`, filas `VM` / `pendiente` (orden alfabético) de las 4 con las notas de contracts/tools.md; en `docs/BANCO-SUPERVISOR.md`, «Tools nuevas del programa», su línea (qué comprobar y en qué tanda: hostname y swap en la 3 con instantánea; ranura y apagar al final, una por instantánea). `tests/test_matriz_pruebas.py` en verde (FR-018)
- [x] T011 [P] Guía: tests primero en `tests/test_tools_guide.py` (tema `host_control` con los alias `hostname`, `swap`, `boot_slot`, `shutdown`; nombra las 4 tools, el aviso de encendido y la vuelta de ranura; las tools que nombra existen; el índice lo lista); después el tema en `hermes/src/hermes/tools/guide.py`. Si cambia un tema existente (`overview`, `supervisor`), actualizar su huella en el test (FR-017, parte)
- [x] T012 Control negativo del tramo 1, anotando recuentos: (a) quitar `estado=` → caen los de estado cambiado; (b) quitar `swap_size` del dict del hash → cae el de otra swap; (c) tratar el corte tras enviar como «ok» → cae `TestCorteTrasEnviar`; (d) añadir `hostname` al evento → cae `TestLog`; (e) aceptar hostname con punto → cae; (f) dejar `/host/shutdown` como `deny` → caen los de la tabla y la genérica. Restaurar y comprobar verde
- [x] T013 Documentación (parte): sección «Host y red del host (032)» en `## [1.2.0]` de `hermes/CHANGELOG.md` (tramo 1); familia `host_control` en la tabla de familias de `hermes/DOCS.md` y en la lista de `tool_families_disabled` de `README.md` y `README.es.md` (sincronizados); estado «en curso (tramo 1)» en la tabla del programa de `docs/HOJA-DE-RUTA.md`; revisar el diff buscando datos personales; commit del tramo (FR-020)


### Notas del tramo 1 (al implementar)

- **T001**: base `feat/032-host-y-red-del-host` tras traer `feat/cobertura-total`
  (019, con el HMAC de los tokens; la 015 no estaba integrada todavía) en el
  commit de merge `947545b`: 3263 passed, 106 skipped, 6 failed (los 6
  conocidos de Windows); `grep -c "spec 032"` = 7.
- **Desviaciones**:
  - `_enviar` trata como «unknown» cualquier fallo que no sea una respuesta
    del Supervisor (sin `status` y sin «Supervisor error:»), también
    `aiohttp.ClientError` y `TimeoutError`, que `sv_request` no envuelve en
    `HAConnectionError`. Se aplica a las cuatro tools (FR-013 nombra apagar y
    la ranura; para el hostname y la swap un corte tras enviar es igual de
    incierto).
  - Título «Shut down host (Supervisor)»: se añade `shutdown → shut down` a
    `_TITLE_WORDS` (ninguna tool de la 1.1.2 tiene esa palabra).
  - `tests/test_generar_tabla.py::test_clase_a_via_dedicada` usaba
    `POST /host/shutdown` como ejemplo de «spec 032»; ahora comprueba que es
    `dedicated` (la regla del mapa va antes).
  - Las instrucciones del `initialize` anuncian el tema `host_control` solo
    con la familia activa (`@TEMA_HOST@`, como `mounts`).
  - No estaba en las tareas y lo piden los invariantes: las cuatro tools van
    a `FUERA_DEL_BANCO` de `tests/banco/cobertura_escrituras.py` (necesitan
    un host real; recuentos 152 y 35), y las rutas de `_leer` y `_enviar` a
    `LLAMADAS_DECLARADAS` de `tests/test_rutas_supervisor_rol.py` (las siete
    caben en `manager`).
- Suite al cerrar: 3316 passed, 106 skipped, 6 failed (los 6 conocidos).
- **T012, controles negativos** (cada uno aplicado, visto en rojo y
  restaurado):
  - (a) sin `estado=` en la creación y la resolución del token → 3 failed
    (`test_estado_cambiado_no_ejecuta`: hostname, swap y ranuras);
  - (b) sin `swap_size` en el dict del hash → 1 failed
    (`test_otro_argumento_no_ejecuta`, otra swap);
  - (c) corte tras enviar tratado como «ok» → 6 failed (los 5 casos de
    `TestCorteTrasEnviar` y `TestLog::test_errores_y_cortes_sin_valores`);
  - (d) `hostname` en el evento de la vista previa → 2 failed (`TestLog`);
  - (e) hostname con punto aceptado → 1 failed
    (`test_invalidos_sin_llamar`, `casa.ha`);
  - (f) `POST /host/shutdown` como `deny` → 6 failed (2 de la tabla, 2 de la
    genérica, la generación desde cero y el registro con la familia
    apagada).
- Al cerrar: `grep -c "spec 032"` = 3 (las tres de la red, tramo 2).

---

## Tramo 2 — `host_network` (CAP-090)

### Preparación

- [x] T014 Línea base y requisito: tramo 1 integrado; `compute_action_hash` de `hermes/src/hermes/security.py` es HMAC con clave en memoria (019). Si no lo es, **detenerse** y anotarlo (research R-9). Suite y `grep -c "spec 032"` = 3
- [x] T015 [P] [US4] Familia `host_network`: tests en `tests/test_tool_families.py` y `tests/test_config_validation.py`, después la familia en `tool_families.py` (FR-015)
- [x] T016 [P] Fixtures de red en `tests/fixtures/supervisor_host.py`: `GET /network/info` con `eth0` (ethernet, principal, conectada), `wlan0` (wireless, no principal, no conectada) y `eth0.10` (vlan); variantes: sin principal, `wlan0` única conectada y no principal, forma inesperada; `GET /network/interface/{i}/info`; 404 de interfaz; error del Supervisor que repite la PSK centinela. Solo datos genéricos

### Tests (escritos antes, en rojo)

- [x] T017 [P] [US3] `TestRecargar`, `TestEditarInterfaz` y `TestCrearVlan` en `tests/test_tools_host_network.py`: `sv_reload_network` → `POST /network/reload` sin token y respuesta con la conectividad; `sv_update_network_interface("wlan0", …)` → vista previa con `role`, `before`, `after` (`"psk": "set"`), `replaces_blocks` y `warning`; `route_warning` con `gateway`; confirmación con la carga exacta (PSK incluida) y la interfaz releída sin PSK; relectura fallida → `"interface": null` y `verify_with`; `sv_create_vlan("eth0", 20, …)` → vista previa y `POST /network/interface/eth0/vlan/20`; `vlan_exists` (`eth0.10`), `not_ethernet` (`wlan0`), `interface_not_found`, `vlan_id` 0, 4095 y `True` → error sin token; crear sobre la madre principal se permite (FR-005, FR-006, FR-009)
- [x] T018 [P] [US3] `TestGuardaDeAcceso` y `TestValidacionDeBloques`: (a) `eth0` principal con cualquier cambio (también solo `mdns`) → `primary_interface`; `default` → `invalid_argument`; `wlan0` única conectada → `only_connected_interface`; sin principal, lectura fallida o forma inesperada → `primary_unknown`; en todos, **ninguna llamada de escritura** y sin token; (b) la guarda se repite al confirmar: si entre medias `wlan0` pasa a principal → no se ejecuta; (c) cada regla de FR-008 con un valor que la incumple (bloque sin `method`, `static` sin dirección, `auto` con `address` o `gateway`, IPv6 en `ipv4`, prefijo ausente, `route_metric` `True`, `addr_gen_mode` desconocido, `wifi` sin `auth`/`ssid`/`mode`, `ssid` de 33 bytes, `wpa-psk` sin `psk` o con 7 caracteres, `psk` con `open`, clave desconocida, `enabled` `"yes"`, `mdns` `"on"`, ningún cambio) → `invalid_argument` con `field` y sin el valor (FR-007, FR-008)
- [x] T019 [US3] `TestPsk`, `TestTokenAtado`, `TestCorteTrasEnviar` y `TestLog`: (a) la PSK centinela no aparece en la vista previa, la confirmación, la respuesta, el error del Supervisor que la repite, ningún evento de `capture_logs` ni **ningún fichero** de `CONFIRMATIONS_DIR` tras la vista previa y tras la confirmación; PSK igual al marcador de redacción o con salto de línea → `invalid_argument`; (b) confirmar con otra PSK, otro SSID u otra IP → no se ejecuta; cambio de la configuración o del papel de la interfaz → no se ejecuta; cambio solo de `wifi.signal` o `ready` → sí se ejecuta; (c) corte tras enviar el cambio → `outcome: "unknown"`; (d) los eventos no llevan IP, gateway, DNS, SSID, MAC ni PSK de los fixtures y sí `tool`, `interface`, `changed`, `outcome` (FR-010…FR-013)

### Implementación

- [x] T020 [US3] `hermes/src/hermes/tools/host_network.py` con las tres tools según contracts/tools.md: lectura de la red y guarda (dos veces), validadores de bloques con `ipaddress`, `_interfaz_publica`, `_limpiar_error`, huella como `estado=`, sin `omitibles`, eventos `host_network`, descripciones en inglés (reemplaza bloques; principal rechazada; sin reversión; PSK no se devuelve; recargar no cambia nada). Comentarios en español con el porqué (research R-2, R-4, R-9). T017–T019 en verde
- [x] T021 [US4] Registro y anotaciones: tests primero en `tests/test_tools_registration.py` (las 3 por defecto y ninguna con `host_network` desactivada; las 2 con token `destructiveHint`; `sv_reload_network` ni de solo lectura ni destructiva e idempotente; `sv_create_vlan` no idempotente; títulos); después registro y `_DESTRUCTIVE_EXACT` (FR-016)
- [x] T022 [US4] Tabla: tests primero (las 3 rutas `dedicated` con `cap="CAP-090"` y familia `host_network`; `sv_call_api("POST", "/network/interface/eth0/update", …)` → `use_dedicated_tool` sin llamada; `sv_read_api("/network/info")` sigue `read`); después `_DEDICADAS_INICIALES` y `command_table.py`; regenerar sin cambios; `grep -c "spec 032"` = 0 (FR-014)
- [x] T023 Inventario de la 033: `sv_update_network_interface` y `sv_create_vlan` con todos sus argumentos `atado` (y `confirmation_token` exento) (la PSK dentro de `wifi`, sin guardarse) y el comentario de la huella; `test_recuento` + 2 (FR-011)
- [x] T024 [P] Matriz: 3 filas `VM` / `pendiente` y sus líneas en el procedimiento (VM con segunda interfaz; comprobar el rechazo de la principal y que la PSK no sale) (FR-018)
- [x] T025 [P] Guía completa: tests primero (alias `host_network`, `network_config`, `vlan`, `wifi`; nombra las 3 tools, la guarda de la principal, que la red se lee con `sv_read_api("/network/info")`, que los bloques se reemplazan enteros y que la PSK no se devuelve); después el tema (FR-017)
- [x] T026 Control negativo del tramo 2, anotando recuentos: (a) quitar la guarda de la principal → caen los de `primary_interface` y SC-002; (b) quitar la de la única conectada → cae; (c) tratar «sin principal» como permitido → cae; (d) pasar `omitibles=("wifi",)` → cae el del directorio de tokens; (e) no limpiar la PSK del error → cae; (f) aceptar `ipv4` sin `method` → cae; (g) añadir `ssid` al evento → cae `TestLog`; (h) dejar `/network/reload` como `deny` → caen tabla y genérica. Restaurar y comprobar verde
- [x] T027 Documentación completa: CHANGELOG (tramo 2), familia `host_network` en DOCS y README (sincronizados), hoja de ruta «hecha», filas CAP-086 y CAP-090 de la matriz de `specs/008-cobertura-total/plan.md` con las tools y los tests reales; revisar el diff buscando datos personales; commit del tramo (FR-020)


### Notas del tramo 2 (al implementar)

- **T014**: base `feat/032-host-y-red-del-host` en `0cc8bec` (tramo 1 hecho;
  `compute_action_hash` es HMAC-SHA256 con clave en memoria, de la 019):
  3316 passed, 106 skipped, 6 failed (los 6 conocidos de Windows);
  `grep -c "spec 032"` = 3.
- **Decisiones del supervisor aplicadas**: D-032-1 (`sv_reload_network` sin
  token; desviación literal de FR-082 de la 008, anotada en la spec), D-032-2
  (la principal, la única conectada y la principal desconocida se rechazan
  siempre, sin token, también con `mdns`; el mensaje remite a la interfaz de
  HA) y D-032-3 (puerta de enlace en una secundaria o en una VLAN: aviso
  fuerte `route_warning`, con token).
- **Desviaciones**:
  - Título de `sv_update_network_interface`: «Update network interface
    (Supervisor)», el que genera `title_for`, y no «Update host network
    interface» del contrato (no hay mecanismo de títulos a mano). Para
    `sv_create_vlan` se añade `vlan → VLAN` a `_TITLE_WORDS`.
  - Varias principales en `/network/info` también es `primary_unknown`
    (fail-closed: no se sabe cuál es la de acceso).
  - La vista previa de `sv_create_vlan` lleva `parent_is_primary` y siempre
    `route_warning` (con `auto` por defecto, el DHCP de la VLAN puede dar
    puerta de enlace). `sv_update_network_interface` solo da `route_warning`
    con una `gateway` explícita; el aviso principal ya nombra el DHCP.
  - La PSK `"set"` también se rechaza (es lo que enseña la vista previa).
  - La vista previa no pasa entera por `redact_structure`: taparía el
    `confirmation_token` y el `"psk": "set"`; solo `before`.
  - El tema de la guía es uno (`host_control`, FR-017) y las instrucciones
    del `initialize` lo nombran salvo con las dos familias desactivadas; se
    adapta el test del tramo 1 (`test_indice_e_instrucciones`).
  - No estaba en las tareas y lo piden los invariantes: las tres tools van a
    `FUERA_DEL_BANCO` (recuentos 155 y 38) y `_enviar` a
    `LLAMADAS_DECLARADAS` de `tests/test_rutas_supervisor_rol.py`.
- **T026, controles negativos** (cada uno aplicado, visto en rojo y
  restaurado; ficheros de la tabla, la genérica, el generador, el registro y
  `test_tools_host_network.py`):
  - (a) sin la guarda de la principal → 5 failed (3 subtests de
    `test_principal_rechazada_siempre`, `test_la_guarda_se_repite_al_confirmar`
    y `TestLog`);
  - (b) sin la de la única conectada → 2 failed (`test_unica_conectada` y
    `test_pasa_a_unica_conectada_al_confirmar`);
  - (c) «sin principal» permitido → 1 failed (`test_principal_desconocida`,
    caso «sin principal»);
  - (d) `omitibles=("wifi",)` → 2 failed (`TestPsk`: la PSK aparece en el
    fichero del token);
  - (e) sin limpiar la PSK del error → 3 failed (`TestPsk`);
  - (f) `ipv4` sin `method` aceptado → 1 failed (`test_cada_regla`, «sin
    method»);
  - (g) `ssid` en el evento → 2 failed (`TestLog`);
  - (h) `POST /network/reload` como `deny` → 5 failed (2 de la tabla, la
    genérica, la generación desde cero y el registro con la familia
    apagada).
- Al cerrar: `grep -c "spec 032"` = 0; tabla regenerada sin cambios.
- Suite al cerrar: 3365 passed, 106 skipped, 6 failed (los 6 conocidos).

## Dependencias y paralelismo

- T002, T003 en paralelo; T004–T005 antes de T006; T007–T011 tras T006 (T010 y T011 en paralelo); T012 y T013 al final del tramo.
- T014 primero en el tramo 2; T015 y T016 en paralelo; T017–T019 antes de T020; T021–T025 tras T020; T026 y T027 al final.

## Fase 3: Convergencia

Revisión independiente del rango del tramo 1 y 2, comprobada contra el código
del Supervisor 2026.11.0. Severidad entre corchetes.

- [x] T028 [ALTO] Guarda de acceso: rechazar también la madre de la interfaz principal cuando la principal es una VLAN (`primary_interface`). Hoy `_guarda` (`host_network.py`) solo compara el nombre y deja editar `eth0` cuando la principal es `eth0.10`. Con `enabled: false`, el Supervisor v1 borra el perfil de `eth0` (`apply_changes` → `_apply_delete`), y la VLAN guarda como madre el UUID de ese perfil (`dbus/network/setting/generate.py`), así que no vuelve a levantarse y se pierde el acceso. Como `vlan.parent` puede llegar como UUID, si no se resuelve a un nombre conocido, fail-closed: rechazar cualquier ethernet (o la `X` de un nombre `X.N`). Test con la principal en `eth0.10` y control negativo, por FR-007 (partial)
- [x] T029 [MEDIO] `sv_set_boot_slot`: el Supervisor reinicia sin comprobar la migración de la base de datos de Core. `os/manager.py::set_boot_slot` llama a `host.control.reboot()` directamente, y `_check_ha_offline_migration` solo está en `api/host.py` (reboot y shutdown). Antes de la vista previa y otra vez al confirmar, leer el estado de Core (`/api/core/state`, `recorder_state`). Si hay una migración que no es en vivo, rechazar sin token (`db_migration_in_progress`); si no se puede leer, avisar en la vista previa. Descripción, guía y CHANGELOG coherentes, por FR-004 y principio V (partial)
- [x] T030 [MEDIO] `sv_update_network_interface` con `enabled: false`: en la v1 BORRA el perfil guardado (`destructive_disable`), PSK y configuración IP incluidas, y descarta los demás bloques. Hoy la vista previa los enseña en `after` como si se aplicaran. Hay que rechazar `enabled: false` junto con otros bloques y, solo, avisar en la vista previa (y decirlo en la descripción y la guía) de que borra la conexión y de que volver a activarla exige la configuración completa, por FR-006 y principio V (contradicts)
- [x] T031 [BAJO] `_limpiar` (`host_network.py`): tapar también las formas escapadas de la PSK (`json.dumps(psk)[1:-1]`, con y sin `ensure_ascii`), no solo el literal. Si el texto del Supervisor la repitiera dentro de un JSON y la PSK lleva `"`, `\` o caracteres no ASCII, hoy sale tal cual. El 2026.11.0 no la repite en ningún camino de la v1: es defensa en profundidad. Test con una PSK que lleve comillas, por FR-010 (partial)
- [x] T032 [BAJO] `sv_set_boot_slot` y `sv_set_swap` sin HAOS: `GET /os/info` NO da 404 (`api/os.py::info` no lo comprueba); devuelve `boot: null` y `boot_slots: {}`, y Hermes contesta «Unexpected Supervisor response» en vez de `not_supported`. El fixture simula un 404 que el Supervisor real no da. Tratar `boot` nulo o sin ranuras como `not_supported` y ajustar el fixture, por FR-004 (partial)
- [x] T033 [BAJO] `insufficient_disk` admite una swap igual o casi igual al disco libre (`>` estricto), aunque el mensaje dice que se evita llenar el disco de datos. Exigir un margen (por ejemplo, dejar al menos 1 GiB o un porcentaje libres) o corregir el texto, por FR-003 (partial)
- [x] T034 [BAJO] Bloques que el Supervisor v1 acepta pero ignora, y la vista previa enseña como aplicados. (a) `wifi` en una interfaz que no es `wireless`: `generate.py` solo lo usa con WIRELESS; hay que rechazarlo con el `type` leído. (b) `nameservers` con `method: disabled`: `_get_ipv4_connection_settings` solo los escribe con auto o static; hay que rechazarlos. (c) `auth: wep`: el Supervisor escribe la clave en `psk` con `key-mgmt: none`, y NetworkManager usa `wep-key0` para WEP, así que la red no conecta. Hay que rechazar `wep` o decirlo en la descripción. Por FR-008 y principio V (partial)

**Hecho en la convergencia (decisiones del supervisor: todo, fail-closed).**
Cada arreglo con su test, que reproduce el escenario de la revisión, y su
control negativo (mutación aplicada, vista en rojo y restaurada):

- **T028**: `_dependencias_de_la_principal` sigue `vlan.parent` (también
  VLAN sobre VLAN) y `_guarda` rechaza la madre (`primary_interface_parent`).
  Desviación sobre el texto de la tarea: si la madre no se resuelve a un
  nombre (UUID de la conexión, ausente o desconocida), se rechaza CUALQUIER
  interfaz (`primary_dependency_unknown`), sin adivinar por la forma `X.N`.
  Puentes y *bonds* no existen en el modelo del Supervisor (`InterfaceType`
  solo tiene ethernet, wireless y vlan; los demás tipos no se listan), así
  que una principal de ese tipo deja sin `primary` y ya da `primary_unknown`.
  Control: con `dependencias = set()` caen 4 tests (15 fallos con subtests).
- **T029**: `_sin_migracion` lee `/api/core/state` (criterio de
  `get_api_state`) antes del token y al confirmar. Desviación: si no se puede
  leer, se RECHAZA (`core_state_unknown`) en vez de avisar. `sv_shutdown_host`
  no lo necesita: con `{}` lo comprueba el Supervisor (test
  `test_apagar_no_lee_core`). Control: sin la llamada caen 4 tests.
- **T030**: `enabled: false` con otros bloques → `invalid_argument` (campo
  `enabled`); solo, la vista previa lleva `deletes_saved_connection` y
  `disable_warning`. Control: 2 tests (uno por cada parte).
- **T031**: `_formas_de_la_psk` (literal, JSON con y sin `ensure_ascii`,
  `repr` y un nivel de JSON dentro de JSON). Control: solo el literal → caen
  los 4 casos escapados.
- **T032**: `boot: null` con `boot_slots: {}` → `not_supported`; el fixture
  devuelve esa forma (`os_info_sin_haos`) en vez del 404. La swap sigue con
  404, que es lo que da el Supervisor real. Control: 1 test.
- **T033**: margen `max(1 GiB, 10 % de disk_total)`, sin descontar la swap
  actual (no se sabe si su fichero existe). Control: 3 tests.
- **T034**: `wifi_not_wireless`; DNS con `disabled`; `addr_gen_mode` e
  `ip6_privacy` sin `auto` (también ignorados, por el mismo motivo); `wep`
  rechazado con su motivo. Control: cada una de las cuatro, en rojo.
