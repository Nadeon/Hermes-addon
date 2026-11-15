<!-- Hoja de ruta de Hermes tras la revisión de compatibilidad de noviembre de
     2026. El plan por versiones es una propuesta pendiente de decisión del
     mantenedor, no un compromiso de fechas. -->

# Hoja de ruta de Hermes

**Revisión:** 2026-11-14, sobre Hermes **1.1.2** (la revisión de
compatibilidad se hizo sobre la 1.0.11; la 1.0.12 corrige lo que se encontró,
la 1.1.0 añade lo planificado para ella, la 1.1.1 corrige lo que encontraron
las pruebas en vivo de la 1.1.0 y la 1.1.2, lo que encontraron las de la
1.1.1). La 1.0.12 no se publicó por separado: llega a los usuarios dentro de la
1.1.0.

**1.2.0, publicada el 2026-11-15:** el programa de cobertura total (más abajo)
lleva Hermes de 216 a 359 tools. Los recuentos de este apartado son los de la
1.1.2; los de la 1.2.0 están en «Programa de cobertura total».

**1.2.1, pendiente de publicar:** las carpetas `/addons` y `/share` (spec 034)
suben a 366 tools. Ver «Hecho en 1.2.1» en el plan por versiones.

**Verificado contra:** Home Assistant Core **2026.11.1**, Supervisor **2026.11.0**
y la especificación MCP **2026-07-28**. El código de Core y del Supervisor se
leyó en esos tags; las tools de lectura se probaron en una instalación de prueba
con HA 2026.11.1. De las 124 tools que modifican, las 100 `ha_*` se ejecutan
en cada push en el CI contra HA Core 2026.11.1 real (banco de pruebas): las 47
de helpers en la spec 010 y las 53 restantes en la 028 (ver «Banco de Core:
helpers» y «Banco de Core: escrituras» más abajo). Se prueban 99 con su
efecto; `ha_reload_counters` no modifica nada (HA no tiene `counter.reload`:
responde `not_supported`, ver más abajo). Las 24 `fs_*` y `sv_*` no
pasan por el banco, cada una con su motivo: las `fs_*` se ejecutan contra
ficheros reales en la suite normal y las `sv_*` se verificaron leyendo el
código de Hermes y el del Supervisor, con simuladores del Supervisor en la
suite. A esas 124 se suman las 2 genéricas de escritura de la 011:
`ha_call_ws_command` se ejecuta en el mismo banco y `sv_call_api` va con las
del Supervisor. La prueba de las del Supervisor y de ficheros contra un
Supervisor real está en la matriz de pruebas (VM, pendiente; ver «Matriz de
pruebas» más abajo y `docs/BANCO-SUPERVISOR.md`).

## Estado de compatibilidad

- **Funciona en lo esencial.** Ningún comando WebSocket o REST que usa Hermes ha
  cambiado de nombre en HA 2026.11.1. En la 1.0.11 todos los endpoints del
  Supervisor que usaba existían salvo uno (el del sondeo del backup de
  seguridad); la 1.0.12 usa el correcto.
- **HACS es el Marketplace desde HA 2026.11**: se ha integrado en el core con
  otra API. En la 1.0.12 las tools `ha_hacs_*` solo lo explicaban con un mensaje
  claro; la 1.1.0 añade las `ha_marketplace_*`, de solo lectura, que detectan en
  cada llamada si hay Marketplace o HACS 2.x, y deja las `ha_hacs_*` como alias
  deprecados hasta la 1.3.0.
- **La versión mínima es HA 2024.10**: por debajo no se pueden crear ni editar
  automatizaciones. La 1.0.11 declaraba 2024.1; la 1.0.12 declara la real.
- **MCP:** transporte Streamable HTTP sin estado y SDK oficial 2.x, al día. En
  OAuth faltan **CIMD** (Client ID Metadata Documents, el registro preferido
  desde la revisión 2026-07-28) y el parámetro **`iss`** (RFC 9207). El registro
  dinámico (DCR) que usa Hermes sigue funcionando, pero está deprecado. Los dos
  están en la 1.1.0 (spec 003).
- **Cobertura medida**: Core 2026.11.1 expone 623 comandos WebSocket; Hermes
  cubre 130 y quedan 147 huecos de administración, 192 de integraciones
  concretas, 103 internos del frontend y 51 excluidos por diseño. El
  Supervisor expone 254 rutas; Hermes cubre 37 y quedan 130 huecos. Detalle en
  `specs/008-cobertura-total/`.

## Problemas conocidos de 1.1.1

Resuelto en la 1.1.2 (spec 007, ver «Hecho en 1.1.2»).

- **Resuelto en 1.1.2. Las escrituras con confirmación y un documento grande
  caducan antes de poder confirmarse.** El `confirmation_token` dura 60 s, y la segunda llamada
  tiene que repetir los mismos argumentos. Un modelo escribe unos 0,4 KB por
  segundo. En la prueba en vivo, la confirmación de un dashboard de 41 KB llegó
  a los 104 s de la vista previa y dio `confirmation_token expired`. Por encima
  de unos 20–25 KB no da tiempo. Afecta a `ha_save_lovelace_dashboard` y, por
  el mismo mecanismo, a `fs_write_file` y a `ha_create_or_update_*` cuando el
  documento es largo. No hay pérdida de datos, porque falla cerrado: no se
  guarda nada. Se eligió confirmar solo con el token: la vista previa guarda
  el documento en el servidor y la confirmación puede omitirlo. Dar al token
  más tiempo se descartó porque el documento se seguiría escribiendo dos veces.

## Problemas conocidos de 1.0.11

Severidad, de mayor a menor: **pérdida de datos** > **rota** > **degradada** >
**cosmética**. Todas las acciones afectadas de pérdida de datos exigen
`confirmation_token`; el problema era que la vista previa no describía bien lo
que iba a pasar. La última columna dice qué hace con cada uno la 1.0.12; el
detalle está en el CHANGELOG.

| # | Problema | Severidad | Origen | En 1.0.12 |
|---|---|---|---|---|
| 1 | Al reenviar los alias de una entidad, el marcador de «nombre calculado» (`null`) se guarda como el texto `"None"`: la entidad deja de responder a su nombre en Assist | Pérdida de datos | Cambio de HA 2026.4 | Corregido |
| 2 | `ha_remove_device_from_config_entry` borra el dispositivo entero del registro, no solo la asociación que anuncia | Pérdida de datos | Cambio de HA 2026.9 | Corregido: nueva `ha_remove_device`; la antigua queda deprecada y su vista previa dice la verdad |
| 3 | El dashboard principal (`url_path: "lovelace"`) se puede borrar con `ha_delete_lovelace_dashboard`, aunque la documentación de la tool dice que no | Pérdida de datos | Cambio de HA 2026.2 | Corregido |
| 4 | Solo con la opción `safety_backup_enabled` activada (viene desactivada por defecto): el backup de seguridad previo nunca se da por terminado y las escrituras `fs_*` no llegan a ejecutarse | Rota | Hermes | Corregido |
| 5 | `sv_get_job_status` informa como terminado (`done`) un job que ha fallado, sin sus errores | Rota | Hermes | Corregido |
| 6 | Las tools `ha_hacs_*` responden «Unknown command» en HA ≥ 2026.11 | Rota | Cambio de HA 2026.11 | Mitigado: mensaje claro. Resuelto en 1.1.0: tools `ha_marketplace_*` y alias `ha_hacs_*` |
| 7 | Con HA 2024.1–2024.9 no se pueden guardar automatizaciones (versión mínima declarada incorrecta) | Rota | Hermes | Corregido |
| 8 | No se puede guardar un script que tenga la clave `trace` | Rota | Hermes | Corregido |
| 9 | `aliases: null`, documentado como «limpiar alias», lo rechaza HA | Rota | Cambio de HA 2026.4 | Corregido |
| 10 | Borrar un helper que no existe da un error genérico en lugar de `not_found` | Degradada | Hermes | Corregido |
| 11 | `ha_render_template` devuelve error y pierde el resultado cuando la plantilla solo genera un aviso | Degradada | Hermes | Corregido |
| 12 | Los dispositivos hijo (HA 2026.9) quedan fuera de los filtros por área y fabricante | Degradada | Cambio de HA 2026.9 | Corregido el área; el filtro por fabricante los deja fuera a propósito (no lo tienen) y la descripción lo dice |
| 13 | `sv_get_supervisor_info` y `sv_get_host_info` devuelven siempre `null` en algunos campos (máquina, versión de Docker, kernel) | Degradada | Hermes | Corregido |
| 14 | `ha_list_services` no admite filtro y su respuesta puede superar el límite del cliente | Degradada | Hermes | Corregido |
| 15 | Desde HA 2026.11, `name` en el registro de entidades es solo la parte de la entidad; la documentación no lo avisa y se duplica el nombre del dispositivo | Cosmética | Cambio de HA 2026.11 | Corregido |
| 16 | `ha_list_lovelace_dashboards` puede mostrar dos veces el dashboard principal | Cosmética | Cambio de HA 2026.2 | Corregido |
| 17 | Descripciones de tools que no coinciden con la respuesta real (estadísticas, stats de add-ons, ubicación de backups) | Cosmética | Hermes | Corregido |
| 18 | La guía enseña sintaxis heredada de automatizaciones (`platform:`, `service:`) | Cosmética | Hermes | Corregido |
| 19 | Defectos menores de las tools de HACS (categorías, cálculo de actualizaciones, mensaje de error poco claro) | Cosmética | Hermes | Corregido; en 1.1.0 las `ha_hacs_*` pasan a ser alias de las `ha_marketplace_*` |
| 20 | Un `not_found` del registro de entidades llega como texto crudo de HA | Cosmética | Hermes | Corregido |
| 21 | Las tools de lista devuelven formas distintas (lista suelta, bloques sueltos, `{count, items}`) | Cosmética | Hermes | Parcial (1.2.0: sobre común en las tools nuevas; las existentes, duda D-07) |
| 22 | `period: "year"` en estadísticas se acepta sin comprobar que HA sea ≥ 2026.3 | Cosmética | Hermes | Corregido |
| 23 | El log muestra un traceback inofensivo al apagar y no redacta direcciones de red | Cosmética | Hermes | Resuelto en 1.2.0 (009); la redacción de red, resuelta en 1.1.0 (`log_redact_network`) |

Recomendación: actualizar a la 1.0.12. Quien siga en la 1.0.11 no debe
reenviar `aliases` leídos del registro, ni usar
`ha_remove_device_from_config_entry` salvo para borrar el dispositivo entero, ni
borrar el dashboard `lovelace`, y debe mantener `safety_backup_enabled`
desactivada, que es su valor por defecto. En la 1.0.12,
`ha_remove_device_from_config_entry` sigue disponible pero deprecada: usa
`ha_remove_device`.

## Deprecaciones con fecha

| Qué | Cuándo | Efecto en Hermes |
|---|---|---|
| Acción `home-assistant/builder@master` y `build.yaml` | Deprecados (aviso del 2026-04-02); retirada anunciada sin fecha | Ninguno: el flujo de publicación ya usa las actions nuevas y `build.yaml` se ha quitado (spec 002) |
| Campos `config_entries` y `config_entries_subentries` del dispositivo | HA **2027.8** (`primary_config_entry`: **2027.10**) | Ninguno desde la 1.0.12: los recuentos de dispositivos por integración usan `config_entry_id` y solo recurren a `config_entries` como respaldo. Desde la 1.2.0 un test fija la forma futura, sin esos campos, y que ningún fichero de Hermes lee `primary_config_entry` ni `config_entries_subentries` (`TestDispositivosSinCamposDeprecados` en `tests/test_deprecaciones.py`) |
| Comando `config/device_registry/remove_config_entry` | HA **2027.9** | `ha_remove_device_from_config_entry`, deprecada en la 1.0.12, sigue en la 1.2.0 y se retira como tarde en la última versión de Hermes publicada antes de HA 2027.9 (D-08 de la spec 008). Desde la 1.2.0, si HA ya no tiene el comando, la tool devuelve `command_removed_in_ha` con `replacement: ha_remove_device`, sin probar otro comando (`TestComandoRetiradoEnHA` en `tests/test_tools_registry_device.py`). `ha_remove_device` usa `config/device_registry/remove` desde HA 2026.9 |
| Comando `lovelace/resources` (alias de `lovelace/resources/list`) | Anunciado para 2025.1; sigue presente, puede desaparecer sin aviso | Ninguno desde la 1.0.12: `ha_list_lovelace_resources` usa `lovelace/resources/list` |
| Campo `has_mean` de estadísticas | Plazo vencido; sigue presente | Solo documentación |
| Acceso TCP de las apps al Supervisor (`SUPERVISOR_TOKEN`) en favor de un socket Unix | Sin fecha. En 2026.11.0 el socket existe solo para Core (`SUPERVISOR_SOCKET` no se inyecta en las apps) y el aviso `deprecated_tcp_api_request` solo salta con el token de Core | Hermes usa solo TCP. Desde la 1.2.0 detecta `SUPERVISOR_SOCKET` al arrancar y lo anota en el log (`supervisor_platform` y el aviso `supervisor_unix_socket_offered`); sigue por TCP (`tests/test_supervisor_platform.py`). Qué hará falta para usarlo: «Socket Unix y API `/v2` del Supervisor», en «1.3.0 y posteriores» |
| API `/v2` del Supervisor (`addons` → `apps`) | Sin fecha; hoy detrás de una opción de desarrollo y sin retirar la V1 | Ninguno hoy. Desde la 1.2.0 Hermes lee la opción `supervisor_v2_api` al arrancar y la anota (el aviso `supervisor_api_v2_enabled` si está activa); sigue con la V1, que no se retira al activarla (`tests/test_supervisor_platform.py`). Rutas y cambios de formato: «Socket Unix y API `/v2` del Supervisor», en «1.3.0 y posteriores» |
| Alias `ha_hacs_*` | Hermes **1.3.0** | Se retiran; desde la 1.1.0 devuelven `_deprecated`. En la 1.2.0 siguen registrados con sus argumentos y anotaciones (`TestDeprecadasSiguen` en `tests/test_deprecaciones.py`) |
| `ha_reload_counters` | Hermes **1.3.0** | Se retira; desde la 1.2.0 responde `not_supported` con `_deprecated` (HA no tiene `counter.reload`; spec 033) |
| `ha_get_config_entry_options` | Hermes **1.3.0** | Se retira; desde la 1.2.0 responde `not_supported` con `_deprecated` (HA no publica las opciones; la vía es el flujo de opciones; spec 033) |
| Argumento `name` de `ha_create_scene_from_current` | Hermes **1.3.0** | Se retira; desde la 1.2.0 con valor responde `name_not_supported` (`scene.create` no admite nombre; spec 033) |
| Acciones `hassio.*_update` | Ya no existen en Core 2026.11 | Ninguno: las de la denylist están muertas; actualizar va por `update.install` |
| DCR (RFC 7591) en MCP | Deprecado en la revisión 2026-07-28; la spec garantiza al menos 12 meses | OAuth de Hermes |
| Constante de versiones de protocolo admitidas del SDK `mcp` (sustituida por las de handshake y modernas) | Deprecada en 2.x | Ninguno: el middleware usa las dos tuplas nuevas desde la spec 003. Desde la 1.2.0 la suite falla si Hermes usa algo que el SDK marque como deprecado (`MCPDeprecationWarning` o `DeprecationWarning`) o nombra esa constante, y comprueba que `requirements.txt` mantiene `mcp<3` (`tests/test_sdk_deprecaciones.py`) |
| Alias de carpeta `homeassistant` en los backups parciales de las acciones `hassio.backup_partial` y `hassio.restore_partial` | HA **2026.12** | Ninguno: Hermes usa la API del Supervisor, y esas acciones van por la denylist con token |

Pendiente de confirmar en la documentación oficial de Claude: los límites de
~150 000 caracteres por resultado y 240 s por llamada en claude.ai. La 1.1.0
ya se ajusta a ellos: `response_max_bytes` de 128 KiB por defecto y 512 KiB como
máximo, y 220 s como máximo de `ha_wait_for_event`.

Para quien publique Hermes con el add-on de Tailscale: desde la versión 0.14.0
gestiona `share_homeassistant` como servicio propio y, una sola vez, borra la
configuración Serve/Funnel existente. Comprueba el Funnel de Hermes tras
actualizarlo. Desde la 1.0.12 los README recomiendan publicar Hermes en el 8443
(o el 10000) con `tailscale funnel --bg --https=8443 8765` y
`public_hostname: homeassistant.tailXXXX.ts.net:8443`, y dejar el 443 a
`share_homeassistant: funnel`, que lo usa por defecto: así no chocan. Los
README explican cómo pasar una instalación existente del 443 al 8443.

## Plan por versiones

> **Propuesta pendiente de decisión.** El orden y el contenido pueden cambiar.
> Lo que viene tras la 1.1.2 ya está decidido: es el programa de la spec 008
> (ver «Programa de cobertura total»), que sale entero como 1.2.0.

### Hecho en 1.0.12 — solo arreglos

1. Backup de seguridad y estado de jobs (problemas 4 y 5), con tests.
2. Alias de entidades (1 y 9).
3. Borrado de dispositivos con una tool y una vista previa que digan la verdad (2).
4. Protección del dashboard principal y lista sin duplicados (3 y 16).
5. `trace` en scripts (8).
6. Versión mínima a 2024.10 (7 y 22).
7. Errores por código de HA, no por texto (10 y 20).
8. Avisos de plantillas (11).
9. Dispositivos hijo y campo `config_entry_id` (12; prepara 2027.8).
10. Campos del Supervisor y del host (13).
11. `lovelace/resources/list`.
12. Mensaje claro en las tools de HACS en HA ≥ 2026.11 (6, mínimo).
13. Filtro por dominio en `ha_list_services` (14).
14. Documentación de tools y guía (15, 17, 18).

Todo con test de regresión y control negativo. Subir la versión mínima deja
fuera HA 2024.1–2024.9, que de todos modos no podía guardar automatizaciones.
Se añadió `ha_remove_device` y `ha_remove_device_from_config_entry` quedó
deprecada.

### Hecho — publicación de imágenes (spec 002)

El flujo de publicación usa la action `build-image` de Home Assistant, fijada
por SHA, con cada arquitectura en un runner nativo y firma cosign; el
Dockerfile trae su imagen base por defecto y `build.yaml` desaparece.
`config.yaml` declara `timeout: 20` para que el apagado ordenado termine antes
del SIGKILL de Docker. Las primeras publicaciones con etiqueta (`v1.1.0` y
`v1.1.1`) salieron bien, y las imágenes publicadas con el builder anterior
siguen disponibles en GHCR.

### Hecho en 1.1.0 — OAuth moderno, límites y protocolo (spec 003)


- **CIMD** (manteniendo DCR), con la descarga acotada contra SSRF y la opción
  `oauth_cimd_enabled`; parámetro **`iss`** en todas las redirecciones;
  `scopes_supported` y `scope` en el 401; tokens ligados al recurso.
- **Límites alineados con Claude**: `response_max_bytes` 128 KiB por defecto y
  512 KiB como máximo (el 1 MiB guardado pasa a 128 KiB);
  `wait_for_event_max_seconds` hasta 220 s. Los recortes quedan en el log.
- **Protocolo**: `title` en las tools, versión del servidor en `serverInfo`,
  errores marcados con `isError`.
- **Redacción de red en el log** (`log_redact_network`, activa por defecto).

### Hecho en 1.1.0 — Marketplace, organización y diagnóstico (specs 004 y 005)

- Tools del Marketplace de **solo lectura**, con alias de las `ha_hacs_*`
  (deprecados hasta la 1.3.0).
- Plantas, etiquetas y categorías; Repairs de HA; trazas de automatizaciones y
  scripts; `search/related`.
- Centro de resolución del Supervisor (leer y descartar; las sugerencias nunca
  se aplican).
- Backups de la integración `backup` de HA, de solo lectura y sin la contraseña
  de cifrado.
- Retención de los safety backups (`safety_backup_keep`, 3 por defecto).

Son 216 tools. Riesgos que quedan: límites más bajos pueden truncar respuestas
que antes pasaban, y más tools ocupan más contexto en el cliente: la lista de
las 216 son unos 215 KB de JSON.

### Hecho en 1.1.1 — correcciones de la 1.1.0 (spec 006)

Las pruebas en vivo de la 1.1.0 con HA 2026.11.1 encontraron tres fallos:

- `ha_marketplace_list_updates` (y `ha_hacs_list_updates`) fallaba siempre:
  pedía el catálogo entero del Marketplace en un mensaje que pasa del tope WS
  y tumbaba la conexión. Ahora se pide por categorías.
- `response_max_bytes` no se aplicaba a las tools que no recortaban por su
  cuenta (`ha_get_states`, entre otras). Ahora lo aplica el servidor a todas.
- El log guardaba el `pattern` de `fs_search_in_config` y la plantilla de
  `ha_render_template`; ahora solo su longitud.

Una revisión independiente de la 1.1.1, antes de publicarla, encontró que el
límite central rompía lo que ya recortaba por su cuenta: `ha_get_history` y
`ha_statistics_during_period` devolvían `response_too_large` justo con rangos
amplios, una vista previa grande perdía su `confirmation_token` (borrar un
fichero grande o editar una automatización larga era imposible) y los logs
largos de un add-on daban error. Corregido en la misma 1.1.1, junto con el tope
de mensaje WebSocket (16 MiB por defecto y `ha_ws_message_too_big` en el log) y
el evento `oauth_cimd_document`.

Una verificación independiente de esos arreglos, también antes de publicar,
encontró que la red de seguridad recortaba por dentro objetos que se guardan
de vuelta (un script de muchos pasos o una vista de Lovelace de muchas
tarjetas). Ahora solo `ha_get_history` y `ha_statistics_during_period` pueden
recortar listas anidadas; el resto da `response_too_large`. En la misma pasada,
los topes por cantidad de history, statistics y logbook avisan con
`truncated`, y el recorte de history y statistics es lineal (antes, más de un
minuto de CPU en el peor caso).

Lo que las pruebas en vivo de la 1.1.0 dieron por bueno: arranque y redacción
de red, `sv_get_supervisor_info`, `sv_get_host_info`, dashboards y recursos de
Lovelace, `ha_list_services(domain=…)`, avisos de `ha_render_template`, los
alias `ha_hacs_info` y `ha_hacs_list_repositories`, la protección del
dashboard principal y los tokens DCR emitidos antes de actualizar.

### Hecho en 1.1.2 — confirmar solo con el token (spec 007)

Las pruebas en vivo de la 1.1.1 encontraron que un documento grande no se
podía guardar con confirmación (ver «Problemas conocidos de 1.1.1»). En
`ha_save_lovelace_dashboard`, `fs_write_file` y
`ha_create_or_update_automation`/`_script`/`_scene`, la vista previa guarda el
documento junto al token y la confirmación basta con el destino y el token
(`confirm_with`, `omit_on_confirm` y `confirm_hint` en la respuesta). El token
sigue atado a la tool y a sus argumentos; reenviarlo todo, como en la 1.1.1,
sigue funcionando. El documento guardado se borra al completar el token o, si
caduca, como mucho un minuto después (la limpieza pasa de cada hora a cada
60 s); nunca va al log, y entre todos los tokens no pasa de 16 MiB. El
principio IV se enmienda en el mismo cambio.

### Pruebas manuales hechas en una instalación real (1.1.0)

- [x] **Arranque y log redactado**: OK.
- [x] **Arreglos de la 1.0.12**: OK.
- [x] **Protección del dashboard `lovelace`**: OK.
- [x] **Tokens DCR emitidos antes de actualizar**: siguen valiendo. OK.
- [x] **CIMD con claude.ai**: OK. claude.ai inicia sesión con CIMD con su
  documento en el host `claude.ai`; si solo usas Claude,
  `oauth_cimd_allowed_hosts: ["claude.ai"]` basta.

**Hosts CIMD conocidos** (para `oauth_cimd_allowed_hosts`; spec 027):

| Cliente | Host del documento | Comprobado |
|---|---|---|
| claude.ai | `claude.ai` | Sí, en una instalación real (1.1.0) |
| Claude Code | `claude.ai` | Documentado; la prueba en vivo sigue pendiente |

No se añade ningún host sin comprobarlo. Para averiguar el de otro cliente,
conéctalo con la lista vacía y busca en el log el evento `oauth_cimd_document`,
que lleva solo el host del `client_id`; con la lista ya puesta, el evento
`oauth_cimd_rejected` con motivo `host_not_allowed` dice qué host falta. El
valor por defecto sigue vacío en la 1.2.0 (`TestCimdPorDefecto` en
`tests/test_deprecaciones.py`); restringirlo es D-09 de la spec 008.

### Pruebas manuales hechas en una instalación real (1.1.1)

- [x] **Publicación con el CI nuevo** (spec 002): las etiquetas `v1.1.0` y
  `v1.1.1` publicaron las dos arquitecturas con `build-image` a la primera.
- [x] **Actualización con la clave `homeassistant`** en una HA soportada: el
  Supervisor actualizó a 1.1.0 y a 1.1.1 sin problemas.
- [x] **Valores heredados**: `config_legacy_default_replaced` para
  `response_max_bytes` (1 MiB → 128 KiB) y `ha_ws_max_msg_size_bytes`
  (4 MiB → 16 MiB).
- [x] **Marketplace**: `ha_hacs_list_updates` y `ha_hacs_list_repositories`
  responden sin cortar la WebSocket (ningún `ha_ws_reconnect_failure`).
- [x] **`ha_get_states(domain="sensor")` en una casa con cientos de
  sensores**: llega recortada por debajo de 128 KiB con `truncated`.
- [x] **`ha_get_history`**: datos útiles con `truncated` y `truncated_at`,
  nunca `response_too_large`.
- [x] **Log**: solo `pattern_len` y `template_len`, y la red sigue redactada.
- [x] **Tools nuevas de la 1.1.x, en lectura**, desde un cliente que ya veía
  la lista nueva: las 18 de lectura (las siete `ha_marketplace_*`, plantas,
  etiquetas, categorías, Repairs, trazas, `ha_search_related`,
  `sv_get_resolution`, `ha_list_backups`, `ha_get_backup` y
  `ha_get_backup_config`) y los cuatro alias `ha_hacs_*` responden con la
  forma del contrato, sin errores en el log y sin cortar la WebSocket.
  `ha_marketplace_list_updates` ya funciona. `ha_get_backup_config` solo
  expone `create_backup.password_set`. Los alias devuelven lo mismo que su
  sustituta más `_deprecated`. Los `not_found` de `ha_get_trace` y
  `ha_get_backup` y el `invalid_argument` de `ha_list_categories` son los del
  contrato. Las 13 tools de escritura de la 1.1.x no se ejecutaron.
- [x] **Imágenes antiguas en GHCR**: las 13 versiones publicadas, de la 1.0.0
  a la 1.1.1, se descargan sin credenciales en `hermes-amd64` y
  `hermes-aarch64`: manifiesto, config con su sha256 y todas las capas. La
  1.0.0 y la 1.0.11 se descargaron enteras en las dos arquitecturas, con el
  sha256 de cada capa verificado. Hasta la 1.0.9 son manifiestos Docker v2;
  desde la 1.0.10, índices OCI con la imagen y una atestación de buildx.
  `latest` apunta a la 1.1.1. La 1.0.7 y la 1.0.12 no se etiquetaron y no
  tienen imagen.

### Pruebas manuales hechas en una instalación real (1.1.2)

Sobre un dashboard de prueba, creado para la prueba y borrado al terminar,
con HA 2026.11.1 y desde un cliente que aún tenía cacheado el esquema de la
1.1.1 (con `config` obligatorio): la llamada sin `config` llegó igual y
Hermes la aceptó.

- [x] **Publicación**: `v1.1.2` publicó las dos arquitecturas a la primera;
  las imágenes se descargan enteras de GHCR con el sha256 de cada capa
  verificado, y `latest` apunta a la 1.1.2. El Supervisor actualizó a la
  1.1.2 sin problemas.
- [x] **Confirmar sin el documento**: el dashboard de unos 41 KB que caducaba
  en la 1.1.1 se guarda confirmando solo con `url_path` y
  `confirmation_token`, unos 4 s después de la vista previa (en la 1.1.1, la
  confirmación llegaba a los 104 s y caducaba). La vista previa trae
  `confirm_with`, `omit_on_confirm: ["config"]` y `confirm_hint`. El log no
  contiene el documento.
- [x] **Dashboards grandes**: uno de unos 134 KB (más que los 128 KiB de
  `response_max_bytes`) se guarda confirmando solo con el token. Leído entero
  da `too_large` con `total_size_bytes`, `views_count` y `top_level` con sus
  tres claves y valores; leído por vistas, cada una trae el mismo `top_level`
  y `views_total`. Sin las claves de nivel superior, el guardado da
  `top_level_keys_missing` con las tres y sin token. Reconstruido como
  `{**top_level, "views": [...]}` y guardado de nuevo, conserva las tres
  claves. Al reescribir a mano los 134 KB, el cliente se dejó tarjetas; la
  vista previa lo mostró (cuenta las tarjetas antes y después), así que la
  salvaguarda funciona, pero reconstruir un dashboard grande entero es
  propenso a errores del cliente (ver 1.2.x, guardado por vistas).

### Pruebas manuales pendientes

La suite no puede cubrir esto; anota aquí el resultado. Cada casilla dice
dónde se hace: en la VM del banco del Supervisor
([BANCO-SUPERVISOR.md](BANCO-SUPERVISOR.md)), en la instalación real o desde
un cliente contra la instalación real.

- [ ] (VM) **Matriz del Supervisor**: las tandas de pruebas del procedimiento
  sobre las `sv_*` y `fs_*` que modifican, con el resultado anotado en la
  matriz de pruebas (sección «Matriz de pruebas: tool → entorno → resultado»).
- [ ] (VM o instalación real) **Lo que la instalación de prueba no tenía**: la
  redacción de las referencias de `sv_get_resolution` con issues o
  sugerencias reales, y las trazas de un script (`ha_list_traces` y
  `ha_get_trace` con `domain: "script"`).
- [ ] (cliente contra la VM o la instalación real) **CIMD con Claude Code**
  (con claude.ai ya está hecho): autorizar, comprobar la pantalla de
  autorización (host, nombre y destino del código) y el evento
  `oauth_cimd_document` del log (`specs/003-oauth-y-protocolo/quickstart.md`).
- [ ] (cliente contra la instalación real) **Primer byte tras el proxy**:
  Claude Code con una espera de 90 s detrás del proxy. Si corta a los 60 s,
  completar DOCS.md con lo que haga falta en ese proxy.
- [ ] (VM) **Clave `homeassistant` en una HA antigua**: que el Supervisor
  rechace la actualización en una HA anterior a 2024.10 (en una soportada ya
  está comprobado).
- [ ] (instalación real) **Funnel en el 8443**: publicar Hermes en el 8443 con
  `public_hostname: homeassistant.tailXXXX.ts.net:8443`, con
  `share_homeassistant: funnel` en el 443, y pasar una instalación existente
  del 443 al 8443 siguiendo los README.
- [ ] (VM) **Confirmar sin el documento con `fs_write_file` (1.1.2)**: lo
  mismo que con el dashboard, con un fichero de prueba grande; y comprobar
  que, pasados unos dos minutos, el directorio de confirmaciones no conserva
  el contenido (`specs/007-confirmar-con-token/quickstart.md`). Hace falta
  acceso al `/data` del add-on, que las tools no dan.
- [ ] (VM, después instalación real) **`hassio_role: manager`**: según el
  procedimiento, comprobar el arranque, la lectura de las opciones de otros
  add-ons (`sv_get_addon_options`, `sv_get_addon`) y cada tool `sv_*`, sin
  ningún 403 nuevo. Según el código del Supervisor 2026.11.0 todas las rutas
  que usa Hermes caben en `manager`, sin excepciones
  (`tests/test_rutas_supervisor_rol.py`). El rol del add-on publicado se
  decide con este resultado (D-02).
- [ ] (VM o instalación real, con internet) **`ha_import_blueprint` con los
  importadores que el banco no puede probar** (spec 017): una URL de GitHub
  (`github.com/<repo>/blob/…` y `raw.githubusercontent.com`), un gist y un
  tema del foro. Comprobar la vista previa (`importer`, ruta sugerida, YAML
  entero y huella), la confirmación y el `source_url` guardado. El banco
  solo cubre el importador genérico (sin salida a internet).
- [ ] (instalación real, con internet y el Marketplace configurado)
  **Mantenimiento del Marketplace (spec 026), en vivo**: ignorar un
  repositorio retirado, quitar un personalizado no instalado, refrescar uno
  y desinstalar uno de prueba (comprobar que el backup parcial sin base de
  datos se crea antes y que, si falla, no se desinstala nada; el banco no
  tiene catálogo ni Supervisor real), y reconocer un aviso crítico real.
  Instalar, fijar versión, betas y añadir no tienen tool (DV-1, duda D-29):
  revisar si una versión futura de HA deja aceptar el aviso al usuario de
  una app.
- [ ] (instalación real, tras publicar) **Pruebas en vivo de las tools nuevas
  de la 1.2.0**: las tools nuevas del programa en una instalación en uso,
  solo después de publicar; las destructivas, antes en la VM.
- [ ] (VM o instalación real) **Las 13 tools de escritura de la 1.1.x**, en
  vivo: cubiertas por la matriz de pruebas (banco de Core para las de Core,
  VM para las del Supervisor).
- [ ] (VM) **`sv_update_addon` sobre Hermes**, tras el rechazo previo de la
  spec 009 (CAP-021).
- [ ] (VM, después instalación real) **Diagnóstico del Supervisor (spec 013), en
  vivo**: las once tools de `system_diagnostics` (los logs con
  `boot=-1` y `latest`, `sv_get_disk_usage` con `max_depth` 3 y con un
  montaje, y las tres de OS) y las rutas `read` de la tabla (`/jobs/info`,
  `/resolution/issue/{issue}/suggestions`, `/host/disks`, hardware, Docker,
  hora y red) por `sv_read_api`. Solo leen; en la suite se prueban con un
  Supervisor simulado.
- [ ] (VM, después instalación real con nube) **Estado del sistema y
  estadísticas (spec 029), en vivo**: las ocho tools de `system_status` y
  `recorder`. Solo leen, así que no tienen fila en la matriz de pruebas; el
  banco de Core ya las ejecuta contra HA Core real, y lo que este no tiene
  queda aquí. En la VM: `ha_get_system_health` con el dominio `hassio`
  completo o con pendientes, y `ha_get_system_state` con un reinicio
  pendiente tras instalar una integración. En la instalación real: la salud
  con `cloud` (hace falta la nube de Home Assistant) y
  `ha_validate_statistics` con estadísticas que tienen problemas reales.
- [ ] (VM, después instalación real) **Diagnóstico de Core (spec 012), en
  vivo**: lo que el banco de Core no tiene, porque sus 12 tools ya se
  ejecutan ahí contra HA Core real (y las tres que modifican tienen su fila
  «ok» en la matriz de pruebas). En la VM (HA OS): `ha_get_error_log`
  responde `error_log_unavailable` con `duplicate_log_file` desactivado y da
  líneas con la opción activada, y `ha_set_log_level` con `persistence`
  `once` y `permanent` sobrevive a un reinicio como dice la vista previa. En
  la instalación real: el camino feliz de `ha_get_device_diagnostics` con un
  dispositivo de una integración con diagnóstico de dispositivo (Z-Wave, ZHA,
  Matter, MQTT…); en el banco solo se prueba `diagnostics_not_supported`.
- [ ] (instalación real, tras publicar) **Integraciones: flujos y Repairs
  (spec 016), en vivo**: lo que la integración de prueba `banco_flujos` del
  banco de Core no puede dar, porque las 12 tools que modifican ya se
  ejecutan ahí contra HA Core real (con su fila «ok» en la matriz de
  pruebas). Un descubrimiento real (listarlo e ignorarlo), las subentries de
  una integración real, un flujo de reparación real del Supervisor y otro de
  varios pasos, una reautenticación real con
  `ha_continue_config_entry_flow` y los textos de los avisos con HA en un
  idioma distinto del inglés.
- [ ] (VM, después instalación real) **Backups de Home Assistant y safety
  backups cifrados (spec 031), en vivo**: `ha_restore_backup` desde
  `hassio.local` y desde un agente remoto (instantánea antes); un safety
  backup cifrado con la clave de HA y su restauración con
  `sv_restore_backup_full` sin `password` y desde la interfaz de HA con el kit
  de emergencia; `safety_backup_encryption: required` con HA sin clave (la
  escritura en `/config` no se hace); y la retención podando safety backups
  cifrados reales. En la suite se prueban con un Supervisor y un HA
  simulados, y en el banco de Core todo lo que no reinicia Core.
- [ ] (instalación real con hardware, tras publicar) **Integraciones
  específicas (spec 025), en vivo**: con Z-Wave, Zigbee o Matter/Thread,
  pedir a un cliente MCP el estado de la red Z-Wave, los parámetros de un
  nodo, los dispositivos y los ajustes de la red Zigbee y los routers de
  borde OTBR, y comprobar que las claves salen `***REDACTED***`
  (`specs/025-integraciones-especificas/quickstart.md`). Sin tools nuevas:
  no hay filas en la matriz de pruebas; el banco de Core solo puede cargar
  `usb`.

- [ ] (VM, después instalación real) **Carpetas /addons y /share (spec 034),
  en vivo**: con Hermes instalado como app local, `fs_list_dir_in_folder` y
  `fs_stat_in_folder` en `addons` (las apps locales, su `local_<slug>` y si
  están instaladas); en una carpeta de prueba de `/share`, las cuatro que
  modifican (`fs_create_dir_in_folder`, `fs_write_file_in_folder`,
  `fs_move_in_folder` y `fs_delete_in_folder` con `recursive`), cada una en
  dos pasos; el resultado, en la matriz de la 014. Nunca con las tools
  conectadas a la instalación real del mantenedor hasta que pasen en la VM.
- [ ] (VM) **Borrar una app local instalada (spec 034)**: borrar su carpeta
  con `fs_delete_in_folder` se rechaza con `installed_app`; tras
  `sv_uninstall_addon`, la vista previa da el recuento y al confirmar se
  borra.
- [ ] (VM) **Aviso del montaje heredado (spec 034)**: el log del Supervisor
  avisa de que Hermes usa el tipo de montaje heredado `addons` (esperado) y
  `/addons` queda montada con escritura.
- [ ] (VM) **Privilegios al instalar una app local (spec 034)**:
  `sv_install_addon` de una app local con `map` y `privileged` enseña
  `privileges` con `declared_in_folder` y `elevated`; cambiar su
  `config.yaml` antes de confirmar da `preview_outdated`.
- [ ] (VM) **Actualizar una app local y `store_copy_stale` (convergencia 2
  de la 034)**: subir la `version` de una app local instalada,
  `sv_reload_store` y `sv_update_addon` enseña `privileges`; tocar
  cualquier fichero de `/addons` antes de confirmar da `store_copy_stale`;
  confirmar mientras se reconstruye otra app local da `folder_busy` a los
  15 s sin gastar el token.
- [ ] (VM) **Recarga que revienta (convergencia 3 de la 034)**: con un
  `config.yaml` con `creada: 2001-13-01` en `/addons`, `sv_reload_store` da
  error dos veces seguidas (Hermes cambia la fecha de `/addons` y el
  Supervisor relee las dos), `sv_install_addon` de una app local responde
  `store_copy_stale` con esa ruta, y tras quitarlo y recargar hay token;
  con una recarga en curso en el Supervisor, `store_copy_stale`.

### Programa de cobertura total (spec 008) — 1.2.0

Objetivo: que Hermes cubra todo lo que HA Core 2026.11.1 y el Supervisor
2026.11.0 ofrecen a un administrador. Modelo híbrido: tools dedicadas para lo
de prioridad alta y media-alta y para lo que tiene consecuencias; cuatro tools
genéricas (WebSocket de Core y API del Supervisor, separadas en lectura y
escritura) gobernadas por una tabla de clasificación fail-closed para la cola
larga y la gestión de integraciones concretas; familias de tools que se pueden
desactivar (todas activas por defecto); banco de pruebas con HA Core real en el
CI. Todo sale como **una sola versión 1.2.0**, publicada el 2026-11-15. Spec,
plan, tareas, investigación e inventarios en `specs/008-cobertura-total/`.

| N.º | Sub-feature | CAP | Estado |
|---|---|---|---|
| 009 | Correcciones pendientes y versión 1.2.0 | 010–018, 021, 024 | hecha |
| 010 | Banco de pruebas de Core (infraestructura y helpers) | 005, 034 | hecha |
| 011 | Política de comandos: tabla, genéricas, familias, deriva, guía | 001–004, 007, 008 | hecha: tabla, cuatro genéricas, familias y `tool_families_disabled`, tema `generic_commands` con `search`, extractor y generador; convergencia tras la revisión independiente cerrada (T044–T049); prueba de las genéricas en el banco de Core (T027) activada al integrarla con la 010 |
| 012 | Diagnóstico de Core | 040, 041, 042, 047 | hecha: familia `core_diagnostics` con 12 tools (logs, validación, diagnósticos de integraciones y notificaciones persistentes), 9 entradas de la tabla a `dedicated` y tema de la guía. En el banco, las 12 contra HA Core real (diagnóstico de entrada con `local_calendar`). Pendiente manual: el camino feliz de `ha_get_device_diagnostics`, que ninguna integración sin hardware ni nube ofrece (cubierto por unitarios) |
| 013 | Diagnóstico del Supervisor | 081, 085, 087 (lectura), 088, 089 | hecha: once tools de solo lectura en la familia `system_diagnostics` (logs de Core, Supervisor, plugins y host, también de arranques anteriores; servicios del host, uso de disco, OS y swap); `boot`/`latest` en `sv_get_addon_logs`; 28 rutas a `dedicated` y 3 a `read` (jobs, sugerencias de un issue, discos montables); `POST /security/integrity` sigue `deny` (410 en el Supervisor 2026.11); prueba en vivo pendiente (VM de la 014, después instalación real) |
| 014 | Banco del Supervisor: procedimiento, matriz y `hassio_role` | 006, 022, 034, 035 | hecha |
| 015 | Actualizaciones del sistema | 064, 080 | hecha: familia `system_updates` con 8 tools (`sv_list_available_updates`, `sv_check_for_updates`, `sv_update_core`, `sv_update_os`, `sv_update_supervisor`, `ha_list_updates`, `ha_get_update_release_notes`, `ha_install_update`), vista previa con bloqueos y token atado a las versiones, encaminamiento de las entidades del Supervisor a las `sv_*` y Hermes sin autoactualización; 8 entradas de la tabla a `dedicated`; tema `updates`; `ha_install_update` probada en el banco de Core; prueba real de las cuatro `sv_*` que modifican pendiente manual en la VM de la 014 |
| 016 | Integraciones: flujos y Repairs | 036, 037, 044, 045, 048 | hecha: familias `integration_flows` (descubiertos, dominios configurables, título y preferencias de una entrada, subentries y reconfigure con token en cada paso; la tool general de flujos rechaza los reconfigure y los flujos que no reconoce, y pide token en los `reauth`; ignorar, solo descubrimientos) y `repair_flows` (aviso con sus datos internos y flujo de reparación con token en cada paso); textos traducidos en `ha_list_repairs`; guía de helpers por config entry. Todo lo que modifica, probado en el banco de Core con la integración de prueba `banco_flujos`. Pendiente manual tras publicar: un descubrimiento real, subentries de una integración real, flujos de reparación reales (uno del Supervisor y uno de varios pasos), una reautenticación real y textos en un idioma distinto del inglés |
| 017 | Automatización asistida | 038, 040, 046, 051, 052 | hecha: familia `blueprints` con `ha_list_blueprints`, `ha_preview_blueprint_substitution`, `ha_save_blueprint`, `ha_delete_blueprint` e `ha_import_blueprint`; familia `automation_assist` con las tres listas de dispositivo, `ha_resolve_target`, `ha_explain_target`, las tres listas por target y `ha_wait_for_trigger` (solo lectura, lista cerrada de triggers); la vista previa de `ha_create_or_update_automation` y `_script` valida con HA y no da token si la rechazaría; 17 entradas a `dedicated` (`subscribe_trigger` reclasificado de B a A); todo probado en el banco de Core (guardar, importar desde `/local/` del banco, borrar, las lecturas, la espera de trigger y la validación al guardar). Pendiente manual: importar de GitHub, gist y foro |
| 018 | Mejoras de tools existentes | 019, 020, 023 | hecha: guardado por vista, `ha_call_service_response` con token para la denylist (y la denylist también en la capa de cliente) y sobre común de las listas nuevas con su test transversal; las pruebas de banco (guardado por vista y `conversation.process`) corren en el job del banco de Core |
| 019 | Montajes y ajustes de backup | 083 | hecha; prueba en la VM pendiente: familia `mounts` con nueve tools (seis de montajes CIFS, NFS y disco local, con crear, editar, borrar y el por defecto con token atado también al estado; tres de ajustes de backup sin token), `location` opcional en `sv_create_backup_full` y `sv_create_backup_partial`, credenciales (también el usuario en los errores del Supervisor) que entran y nunca salen, las nueve rutas de CAP-083 a `dedicated` y el `action_hash` de los tokens con HMAC |
| 020 | Estadísticas y energía | 050, 054 | hecha: cinco tools de mantenimiento de estadísticas en `recorder` (borrar, cambiar la unidad, editar los metadatos, ajustar sumas, importar) y la familia nueva `energy` (leer y guardar las preferencias del panel), todas las que escriben en dos pasos; `recorder/update_statistics_issues` `confirm` y cuatro lecturas de energía `read` por la tabla; las siete y las genéricas, contra HA Core real en el banco |
| 021 | Configuración del sistema | 053, 055, 056, 069, 074 | hecha: núcleo (`ha_get_core_config`, `ha_update_core_config`), exposición a asistentes (`ha_list_exposed_entities`, `ha_set_entity_exposure`, `ha_set_expose_new_entities`), usuarios (`ha_list_users`, `ha_create_user`, `ha_update_user`, `ha_delete_user`, con protecciones del propietario, el usuario de Hermes, los de sistema y el último administrador) y red y HTTP de Core (`ha_update_network_config`, `ha_update_http_config`, `ha_promote_http_config`, con la prueba de 5 minutos de HA y el rechazo de un `server_host` sin el Supervisor); `config/core/detect` y CAP-074 por la tabla. Todo probado en el banco de Core salvo la confirmación de las dos de HTTP (reinicia HA), pendiente en la VM |
| 022 | Control de Core y del Supervisor | 084, 087 (escritura), 091, 092, 094 | hecha: familia `system_control` con siete tools (arrancar, reconstruir y configurar Core; recargar, reiniciar, reparar y configurar el Supervisor) y familia `resolution_fixes` con `sv_apply_resolution_suggestion` (vista previa que traduce el arreglo, rechazos y arreglos automáticos atados al token); 8 rutas a `dedicated`, estadísticas `read`, `/host/reload` y los chequeos del centro de resolución `confirm`; plugins, Docker, placas y hora probados por la tabla sin cambiarla; prueba en la VM pendiente |
| 023 | Assist y conversación | 060–063 | hecha: familia `conversation` con cuatro tools (agentes, frases de los disparadores, análisis sin ejecutar y `ha_process_conversation`, siempre en dos pasos, con lo que reconoce el agente integrado o el aviso del agente externo, y `outcome_unknown` si vence el plazo); 5 entradas de la tabla a `dedicated`; pipelines, motores, AI Task y satélites por las genéricas, con el token del audio de `pipeline_debug/get` tapado en su `url`, su `media_id` y cualquier `/api/tts_proxy/…` o `media-source://tts/-stream-/…`; tema `conversation`; en el banco de Core, `ha_process_conversation` con un disparador de frase y pipelines y AI Task por las genéricas. Solo en unitarios: otro agente (un LLM) y los satélites, que el banco no tiene |
| 024 | Menores de Core | 059, 065–067, 070–073 | hecha: familia `cameras` con `ha_get_camera_snapshot` y `ha_get_image_entity` (imagen MCP, tope de 2 MiB, sin Pillow) y familia `dashboard_reset` con `ha_reset_lovelace_dashboard_config` (dos pasos, token atado a la configuración leída, principal y panel por defecto protegidos); `lovelace/config/delete` a `dedicated`; preferencias de cámara y cinco lecturas de la UI (`trace/contexts`, `frontend/get_themes`, `webhook/list` con el `webhook_id` tapado, `vacuum/get_segments`, `radio_frequency/list`) por la tabla; miniaturas de `browse_media`/`search_media` tapadas (hallazgo); motivo de `application_credentials/config_entry` corregido; las 33 entradas fijadas por test; temas `cameras` y `core_minor` y sección «Restablecer» en `lovelace`; todo probado en el banco de Core, sin hallazgos. Pendiente manual: una cámara real JPEG y otra en la nube (reducción y tope) |
| 025 | Integraciones específicas por la tabla | 100–106 | hecha: las 192 entradas de la clase C clasificadas con el handler leído (73 de lectura, 57 en dos pasos, 62 rechazadas; ninguna «pendiente»), sin tools nuevas (no hay filas en la matriz de pruebas): Z-Wave JS 18/13/24; ZHA, Matter, Thread y OTBR 18/13/19; MQTT, USB, Bluetooth y el resto 37/31/19. Redacción de valor entero bajo claves sensibles y claves S0/S2 como secretos; nueve entradas tapan secretos con su centinela; mapa de la clase C del generador (desde cero igual que la tabla; lo nuevo, «sin revisar»); temas `zwave`, `zigbee`, `matter_thread` y `other_integrations`; `usb` en el banco de Core |
| 026 | Escritura en el Marketplace | 075 | hecha: familia `marketplace_manage` con `ha_marketplace_acknowledge_critical`, `ha_marketplace_ignore_repository`, `ha_marketplace_remove_repository`, `ha_marketplace_refresh_repository` y `ha_marketplace_uninstall` (con backup parcial sin base de datos antes; en la misma familia por la D-2), en dos pasos; reconocer probado en el banco de Core, las otras cuatro no ejecutables allí (sin catálogo) con su carga comprobada contra HA real. Instalar, fijar versión, betas y añadir repositorios sin tool: HA exige el aviso de riesgos aceptado por el usuario de Hermes, que no puede aceptarlo (DV-1, desviación parcial de FR-091; duda D-29); sus comandos, `deny`. Converge: aviso en la vista previa de automatizaciones y scripts con `update.install` (HA les deja instalar sin usuario si alguna persona aceptó el aviso; bloquearlo, decisión pendiente de la D-29) y token para el interruptor «pre-release» por `ha_call_service`. Prueba en vivo pendiente |
| 027 | Plataforma y deprecaciones | 025, 026, 028–033 | hecha: `child_errors` en `sv_get_job_status`, y los errores de los sub-jobs cuentan como fallo, también en el sondeo del safety backup (D-1); `child_jobs` redactado; `command_removed_in_ha`; detección del socket Unix y de la `/v2` al arrancar, sin usarlos; guarda de deprecaciones del SDK; nada deprecado se retira; traducciones de las opciones y «app» en las tools de apps y en la guía; hosts CIMD, `outputSchema` y vía nativa documentados |
| 028 | Pruebas de las escrituras de Core en el banco | 034 | hecha |
| 029 | Estado del sistema y estadísticas de Core | 043, 049, 058, 068 | hecha: familias `system_status` (cinco tools, CAP-043) y `recorder` (tres, CAP-049), `ws_collect_subscription`, auditoría de acciones y red y HTTP por la genérica (CAP-058, CAP-068), tabla, guía y banco de las ocho. Solo leen, así que no tienen fila en la matriz de la 014; en vivo (salud con `cloud` y `hassio`, un reinicio pendiente y la validación de estadísticas de una instalación real), en las pruebas manuales pendientes |
| 030 | Tienda de apps | 082, 093 | hecha: nueve tools en la familia `app_store` (repositorios: listar, añadir y quitar en dos pasos, reparar y recargar; apps: changelog y documentación de la versión de la tienda por trozos, disponibilidad y reconstrucción en dos pasos); vistas previas nuevas en `sv_install_addon` (disponibilidad), `sv_update_addon` (changelog; `already_up_to_date` sin token) y `sv_set_addon_options` (validación del Supervisor, con los mensajes de opciones sin ningún valor); tokens de instalar y actualizar atados a la versión de la vista previa; credenciales de las URL tapadas enteras; 15 rutas a `dedicated`; sin versión concreta (el Supervisor 2026.11 ignora `{version}`: desviación de FR-051); prueba en vivo de las cinco que modifican pendiente (VM de la 014, después instalación real) |
| 031 | Backups de la integración y safety backups cifrados | 027, 057 | hecha: familia `backup_integration` con seis tools (agentes, ajustes con la estimación de la retención, crear, crear con los ajustes automáticos, borrar en todas las ubicaciones y restaurar desde cualquiera); `sv_restore_*` con la clave de HA; safety backups cifrados con la clave de HA y opción `safety_backup_encryption` (`auto` por defecto; desviación de FR-068 de la 008: la clave de HA y no una generada en `/data`); la retención poda los cifrados que Hermes anotó; tabla, guía y banco. DV-1: sin tools del backup previo a actualizar (el proxy del Supervisor rechaza `hassio/*` a las apps). En vivo, en las pruebas manuales pendientes |
| 032 | Host y red del host | 086, 090 | hecha; prueba en la VM pendiente: familia `host_control` con `sv_shutdown_host`, `sv_set_hostname`, `sv_set_swap` y `sv_set_boot_slot`, y familia `host_network` con `sv_reload_network` (sin token: solo relee), `sv_update_network_interface` y `sv_create_vlan`; dos pasos con el token atado a los argumentos y al estado, la interfaz principal, la única conectada o una principal desconocida rechazadas siempre, la PSK del Wi-Fi que entra y nunca sale, y sus siete rutas a `dedicated` |
| 033 | Arreglos de tools de la 1.1.2 que destapa el banco | 039 | hecha: tramo 1 (el token de `ha_run_script` y `ha_trigger_automation` ata `variables`; inventario de argumentos atados) y tramo 2 (`ha_reload_counters` y `ha_get_config_entry_options` dicen `not_supported` y quedan deprecadas; `ha_wait_for_event` sin `ctx`; `ha_create_scene_from_current` con escena temporal, token para reemplazar y `name` rechazado; descripciones de escenas con `scenes.yaml`; `amount` y `ha_set_counter_value` validados); banco sin ningún `xfail` |

**Cierre del programa** (T026 de la 008, converge): las 25 sub-features
están hechas e integradas en `feat/cobertura-total`: 359 tools (las 216 de
la 1.1.2 y 143 nuevas), tabla completa (623 comandos de Core y 254 rutas del
Supervisor) sin ninguna entrada «pendiente» ni «sin revisar», y la matriz de
trazabilidad de `specs/008-cobertura-total/plan.md` completa y vigilada por
`tests/test_trazabilidad_008.py`. Las desviaciones aceptadas (DA-01…DA-12)
y los cambios de comportamiento de las tools de la 1.1.2 están en
`specs/008-cobertura-total/spec.md`. La fase de convergencia de
`specs/008-cobertura-total/tasks.md` (T031–T034) y la de cierre
(T027–T029) están hechas: la PR #26 se fusionó en `main` y la 1.2.0 se
publicó el 2026-11-15.

#### Dudas abiertas para el mantenedor (1.2.0)

Decisiones que el programa no toma por su cuenta (FR-098 de la spec 008). Las
D-01…D-10 vienen de la spec 008 («Dudas para el final»); las demás, de las
sub-features y del cierre. La D-13 (Hermes por su slug exacto) y la D-24 ya
están resueltas, y la D-26 (publicar antes una 1.1.3 con algunos arreglos de
seguridad de la 1.2.0) quedó sin objeto al publicarse la 1.2.0.

- **D-01** — Comandos de clase D que se podrían abrir con salvaguardas fuertes:
  - `cloud/status` y `cloud/subscription`, la exposición vía la nube y `cloud/remote`;
  - `auth/delete_refresh_token` y `refresh_token_set_expiry`;
  - `execute_script`, y `assist_pipeline/run` solo con texto;
  - `application_credentials/delete` y `admin_change_username`;
  - el `stdin` de las apps, `/core/stop` y el `channel` del Supervisor.
- **D-02** — Bajar a `hassio_role: manager` (hay que probarlo en vivo antes).
- **D-03** — Si las familias de riesgo alto (usuarios, red de Core, red y control del host, cámaras, Marketplace…) deben venir desactivadas por defecto.
- **D-04** — El coste de contexto de 359 tools en el cliente, y si conviene recortar la lista que se anuncia por defecto.
- **D-05** — Ejecutar el banco de Core también contra HA 2024.10, la versión mínima soportada.
- **D-06** — Llevar la VM de HAOS al CI con KVM, para probar las `sv_*` contra un Supervisor real.
- **D-07** — Unificar la forma de las listas de las tools existentes con el sobre común de las nuevas.
- **D-08** — Fijar la versión en que se retira `ha_remove_device_from_config_entry`.
- **D-09** — Dar a `oauth_cimd_allowed_hosts` un valor por defecto restrictivo.
- **D-10** — Adoptar la vía nativa de MCP para pedir la confirmación a mitad de una llamada.
- **D-11** — Completar el paso `core_config` del onboarding del banco, que hoy choca con la regla de `iptables` que lo deja sin internet.
- **D-12** — Qué hacer con la traza que sale en el log al apagar Hermes.
- **D-14** — Dónde viven los inventarios de comandos y rutas para las versiones futuras de HA.
- **D-15** — Quitar en la 1.3.0 el campo `error` de la respuesta que trae el token de confirmación.
- **D-16** — Atar también al estado del dashboard el token del guardado completo, como el del guardado por vista.
- **D-17** — Permitir añadir o borrar vistas con el guardado por vista.
- **D-18** — Qué hacer con el `outputSchema` que el SDK infiere en `ping` y `hermes_guide`.
- **D-19** — Hacer el inventario de la API `/v2` y del socket Unix del Supervisor cuando se publiquen para las apps.
- **D-20** — Traducir al inglés las descripciones de tools que siguen en español.
- **D-21** — Hacer un backup opcional antes de actualizar el OS (`sv_update_os` no lo hace).
- **D-22** — `ha_validate_config` no detecta un `mode` inválido, porque la validación de HA no lo mira.
- **D-23** — Revisar en cada versión de HA la lista cerrada de triggers de `ha_wait_for_trigger`.
- **D-25** — Si `safety_backup_encryption: auto` es el valor por defecto adecuado.
- **D-27** — Permitir `ha_create_user` con credenciales opcionales.
- **D-28** — Una marca «cerrar tras el resultado» para las escrituras de integraciones que se suscriben al progreso.
- **D-29** (026) — Marketplace: instalar, fijar versión, betas, añadir y detectar repositorios exigen el aviso de riesgos aceptado por el usuario que manda el comando, y el usuario de Hermes no puede aceptarlo. Además, por diseño de HA, las automatizaciones pueden instalar si alguna persona lo aceptó; hoy Hermes solo avisa.
- **D-30** — Devolver el `webhook_id` en `ha_get_automation`, que hace falta para leer, modificar y guardar una automatización con trigger de webhook.
- **Nota** — Un nombre de familia desconocido en `tool_families_disabled` impide arrancar: si se renombra una familia, hay que dejar un alias en `ALIAS` (`tool_families.py`).

#### Pruebas en vivo pendientes tras publicar

Lo que ni la suite ni el banco de Core pueden probar. Se hace tras publicar,
en la VM de HAOS ([BANCO-SUPERVISOR.md](BANCO-SUPERVISOR.md)) o en una
instalación real, y el resultado se anota en la matriz de la 014.

- [ ] La VM de HAOS para las `sv_*` que modifican (la matriz de la 014).
- [ ] `fs_write_file` con un documento grande.
- [ ] `hassio_role: manager`.
- [ ] CIMD con Claude Code.
- [ ] Importar blueprints desde GitHub, gist y el foro.
- [ ] Las tools del Marketplace con un catálogo real.
- [ ] Restaurar backups.
- [ ] Las tools de red y HTTP.
- [ ] Las demás que la matriz de la 014 marque como pendientes.

#### Banco de Core: helpers (010)

El job `banco de Core` del workflow `Tests` arranca HA Core 2026.11.1 (imagen
fijada por digest), conecta Hermes por un Supervisor simulado como en un
add-on y ejecuta las tools que modifican de los 11 dominios de helpers; el
efecto lo comprueba un lector que habla directamente con Core. El inventario
está en `tests/banco/cobertura.py` y un test de la suite normal impide que una
tool nueva de estos dominios entre sin probarse en el banco.

Ejecutadas en el banco con su efecto comprobado (46 probadas y 1 no
ejecutable con motivo; el job exige que cada probada se haya llamado con éxito
en un test que ha pasado):

- `input_boolean`: `ha_create_or_update_input_boolean`, `ha_set_input_boolean`,
  `ha_toggle_input_boolean`, `ha_delete_input_boolean`.
- `input_button`: `ha_create_or_update_input_button`, `ha_press_input_button`,
  `ha_delete_input_button`.
- `input_datetime`: `ha_create_or_update_input_datetime`,
  `ha_set_input_datetime`, `ha_delete_input_datetime`.
- `input_number`: `ha_create_or_update_input_number`, `ha_set_input_number`,
  `ha_increment_input_number`, `ha_decrement_input_number`,
  `ha_delete_input_number`.
- `input_select`: `ha_create_or_update_input_select`, `ha_set_input_select`,
  `ha_cycle_input_select`, `ha_set_input_select_options`,
  `ha_delete_input_select`.
- `input_text`: `ha_create_or_update_input_text`, `ha_set_input_text`,
  `ha_delete_input_text`.
- `counter`: `ha_create_or_update_counter`, `ha_increment_counter`,
  `ha_decrement_counter`, `ha_set_counter_value`, `ha_reset_counter`,
  `ha_delete_counter`.
- `timer`: `ha_create_or_update_timer`, `ha_start_timer`, `ha_pause_timer`,
  `ha_change_timer`, `ha_cancel_timer`, `ha_finish_timer`, `ha_reload_timers`,
  `ha_delete_timer`.
- `schedule`: `ha_create_or_update_schedule`, `ha_reload_schedules`,
  `ha_delete_schedule`.
- `zone`: `ha_create_or_update_zone`, `ha_reload_zones`, `ha_delete_zone`.
- `person`: `ha_create_person`, `ha_update_person`, `ha_delete_person`.

No ejecutable en el banco (`NO_EJECUTABLES`, con su motivo):

- **`ha_reload_counters`.** HA Core 2026.11.1 no tiene el servicio
  `counter.reload` (la integración `counter` solo registra `increment`,
  `decrement`, `reset` y `set_value`). Era el hallazgo de la 010 (Core
  respondía 400); desde la spec 033 la tool responde `not_supported` sin
  llamar a HA y está deprecada. No modifica nada que se pueda comprobar; su
  test del banco es un canario que cae si un HA futuro añade la recarga.

Ninguna falla en el banco (`FALLAN_EN_BANCO` vacía) ni queda ningún `xfail`.

#### Banco de Core: escrituras (028)

En el mismo job, el resto de tools `ha_*` que modifican. El inventario está en
`tests/banco/cobertura_escrituras.py` y un test de la suite normal
(`tests/test_banco_cobertura_escrituras.py`) obliga a que las 126 tools que
modifican (las 124 de la 1.1.2 y las 2 genéricas de la 011) estén probadas
en el banco (010, 011 o 028), no ejecutables con su motivo
(`ha_reload_counters`, desde la 033) o fuera de él con su motivo.

Ejecutadas en el banco (53; tramo A, 26):

- automatizaciones: `ha_create_or_update_automation`, `ha_disable_automation`,
  `ha_enable_automation`, `ha_trigger_automation`, `ha_reload_automations`,
  `ha_delete_automation`.
- scripts: `ha_create_or_update_script`, `ha_run_script`, `ha_reload_scripts`,
  `ha_delete_script`.
- escenas: `ha_create_or_update_scene`, `ha_activate_scene`,
  `ha_create_scene_from_current`, `ha_reload_scenes`, `ha_delete_scene`.
- servicios, eventos y esperas: `ha_call_service` (directo y en dos pasos),
  `ha_call_service_response`, `ha_fire_event`, `ha_cancel_wait`.
- Lovelace: `ha_create_lovelace_dashboard`,
  `ha_update_lovelace_dashboard_metadata`, `ha_save_lovelace_dashboard`,
  `ha_delete_lovelace_dashboard`, `ha_create_lovelace_resource`,
  `ha_update_lovelace_resource`, `ha_delete_lovelace_resource`.

Tramo B (27), con la integración de demostración `kitchen_sink` cargada en la
HA del banco (dispositivos, avisos de reparación y flujo de opciones sin
hardware ni internet) y una entrada de `uptime` que crean y borran las propias
tools:

- áreas: `ha_create_area`, `ha_update_area`, `ha_delete_area`.
- plantas: `ha_create_floor`, `ha_update_floor`, `ha_delete_floor`.
- etiquetas: `ha_create_label`, `ha_update_label`, `ha_delete_label`.
- categorías: `ha_create_category`, `ha_update_category`,
  `ha_delete_category`.
- dispositivos: `ha_update_device`, `ha_remove_device`,
  `ha_remove_device_from_config_entry`.
- entidades: `ha_update_entity_registry` (con `new_entity_id`),
  `ha_remove_entity_registry`.
- reparaciones: `ha_ignore_repair` (ocultar y volver a mostrar).
- config entries: `ha_reload_config_entry`, `ha_disable_config_entry`,
  `ha_enable_config_entry`, `ha_delete_config_entry`.
- flujos: `ha_start_config_entry_flow`, `ha_continue_config_entry_flow`,
  `ha_abort_config_entry_flow`, `ha_start_options_flow`,
  `ha_continue_options_flow`.

Fuera del banco (24), con su motivo en el inventario:

- `fs_write_file`, `fs_delete_file`, `fs_move_file`, `fs_restore_file_backup`
  y `fs_set_secret`: no hablan con HA (escriben en el `/config` de Hermes); la
  suite normal las ejecuta contra ficheros reales.
- `sv_check_core_config`, `sv_get_job_status`, `sv_create_backup_full`,
  `sv_create_backup_partial`, `sv_create_safety_backup`, `sv_delete_backup`,
  `sv_restore_backup_full` y `sv_restore_backup_partial`: backups, trabajos y
  validación del Supervisor, que en el banco es simulado.
- `sv_install_addon`, `sv_uninstall_addon`, `sv_update_addon`,
  `sv_start_addon`, `sv_stop_addon`, `sv_restart_addon` y
  `sv_set_addon_options`: necesitan el Supervisor real y la tienda.
- `sv_restart_core` y `sv_reboot_host`: el banco no sobreviviría.
- `sv_dismiss_resolution_issue` y `sv_dismiss_resolution_suggestion`: los
  avisos solo existen en el Supervisor real.

Todas con simuladores en la suite normal; su banco es la VM de la 014.

`ha_run_script` y `ha_trigger_automation` se ejecutan por sus dos caminos:
directo y con token (script o automatización restringidos por llamar a la
denylist). El job exige por ejecución las 53 (cada una llamada con éxito en
un test que ha pasado), igual que las 46 de la 010.

Hallazgos de la 028, arreglados en la spec 033 (en el banco ya no hay ningún
fallo esperado; las dos tools siempre contaron como probadas porque su camino
normal funciona):

- **Arreglado en el tramo 2 de la 033:** `ha_create_scene_from_current` con
  `name` fallaba siempre (`scene.create` de Core 2026.11.1 no admite ese
  campo y responde 400), y su descripción decía que una colisión de
  `scene_id` daba error cuando Core reemplaza la escena. Ahora `name` da
  `name_not_supported` sin llamar a HA, reemplazar una temporal pide token y
  una escena que no es temporal da `scene_exists`; el banco lo comprueba
  contra HA real.
- **Seguridad, arreglado en el tramo 1 de la 033:** el token de
  `ha_run_script` y `ha_trigger_automation` con una entidad restringida no
  cubría `variables` y se aceptaba una confirmación con variables distintas
  de las de la vista previa. Ahora las ata y la vista previa las enseña; el
  banco lo comprueba contra HA real sin `xfail`.

#### Matriz de pruebas: tool → entorno → resultado (014)

Una fila por cada tool que modifica (sin `readOnlyHint` en el registro de
producción, con todas las familias activas): dónde se prueba contra el
software real y con qué resultado. Entornos: **banco de Core** (el job del CI
con HA Core 2026.11.1 real; el resultado sale de los inventarios
`tests/banco/cobertura*.py`), **VM** (Home Assistant OS con el Supervisor
2026.11.0, según el procedimiento de [BANCO-SUPERVISOR.md](BANCO-SUPERVISOR.md);
todas las `sv_*` y `fs_*` que modifican) e **instalación real**. Resultados:
**ok**, **falla** (con la causa en la nota), **pendiente** y **no
ejecutable** (solo en el banco de Core, para una tool de un
`NO_EJECUTABLES*` y con el motivo en la nota: hoy, `ha_reload_counters`,
que no modifica nada desde la 033). Una tool del
banco con un hallazgo abierto (`HALLAZGOS_*` de los inventarios, con su
`xfail` estricto) va a **falla** aunque su camino normal funcione. Un «ok» en la VM o
en la instalación real lleva en la nota la versión de Hermes y la fecha. Los
simuladores de la suite normal no son un entorno de esta tabla: corren
siempre, para todas.

`tests/test_matriz_pruebas.py` compara la tabla con el registro y con los
inventarios del banco: una tool que modifica sin fila, una fila de más o una
fila que contradice un inventario lo ponen en rojo. Quien añade una tool que
modifica añade su fila en el mismo cambio (y, si es del Supervisor o de
ficheros, su línea en «Tandas de pruebas» del procedimiento); quien la prueba
cambia `pendiente` por `ok` o `falla`. Las filas van en orden alfabético.

<!-- matriz-pruebas:inicio -->
| Tool | Entorno | Resultado | Nota |
|---|---|---|---|
| `fs_create_dir_in_folder` | VM | pendiente | spec 034 |
| `fs_delete_file` | VM | pendiente | |
| `fs_delete_in_folder` | VM | pendiente | spec 034 |
| `fs_move_file` | VM | pendiente | |
| `fs_move_in_folder` | VM | pendiente | spec 034 |
| `fs_restore_file_backup` | VM | pendiente | |
| `fs_set_secret` | VM | pendiente | |
| `fs_write_file` | VM | pendiente | |
| `fs_write_file_in_folder` | VM | pendiente | spec 034 |
| `ha_abort_config_entry_flow` | banco de Core | ok | |
| `ha_abort_repair_fix` | banco de Core | ok | spec 016 |
| `ha_abort_subentry_flow` | banco de Core | ok | spec 016 |
| `ha_activate_scene` | banco de Core | ok | |
| `ha_adjust_statistics_sum` | banco de Core | ok | |
| `ha_call_service` | banco de Core | ok | |
| `ha_call_service_response` | banco de Core | ok | |
| `ha_call_ws_command` | banco de Core | ok | |
| `ha_cancel_timer` | banco de Core | ok | |
| `ha_cancel_wait` | banco de Core | ok | |
| `ha_change_statistics_unit` | banco de Core | ok | |
| `ha_change_timer` | banco de Core | ok | |
| `ha_clear_statistics` | banco de Core | ok | |
| `ha_clear_system_log` | banco de Core | ok | |
| `ha_continue_config_entry_flow` | banco de Core | ok | |
| `ha_continue_options_flow` | banco de Core | ok | |
| `ha_continue_reconfigure_flow` | banco de Core | ok | spec 016 |
| `ha_continue_repair_fix` | banco de Core | ok | spec 016 |
| `ha_continue_subentry_flow` | banco de Core | ok | spec 016 |
| `ha_create_area` | banco de Core | ok | |
| `ha_create_automatic_backup` | banco de Core | ok | |
| `ha_create_backup` | banco de Core | ok | |
| `ha_create_category` | banco de Core | ok | |
| `ha_create_floor` | banco de Core | ok | |
| `ha_create_label` | banco de Core | ok | |
| `ha_create_lovelace_dashboard` | banco de Core | ok | |
| `ha_create_lovelace_resource` | banco de Core | ok | |
| `ha_create_or_update_automation` | banco de Core | ok | |
| `ha_create_or_update_counter` | banco de Core | ok | |
| `ha_create_or_update_input_boolean` | banco de Core | ok | |
| `ha_create_or_update_input_button` | banco de Core | ok | |
| `ha_create_or_update_input_datetime` | banco de Core | ok | |
| `ha_create_or_update_input_number` | banco de Core | ok | |
| `ha_create_or_update_input_select` | banco de Core | ok | |
| `ha_create_or_update_input_text` | banco de Core | ok | |
| `ha_create_or_update_scene` | banco de Core | ok | |
| `ha_create_or_update_schedule` | banco de Core | ok | |
| `ha_create_or_update_script` | banco de Core | ok | |
| `ha_create_or_update_timer` | banco de Core | ok | |
| `ha_create_or_update_zone` | banco de Core | ok | |
| `ha_create_person` | banco de Core | ok | |
| `ha_create_scene_from_current` | banco de Core | ok | |
| `ha_create_user` | banco de Core | ok | |
| `ha_cycle_input_select` | banco de Core | ok | |
| `ha_decrement_counter` | banco de Core | ok | |
| `ha_decrement_input_number` | banco de Core | ok | |
| `ha_delete_area` | banco de Core | ok | |
| `ha_delete_automation` | banco de Core | ok | |
| `ha_delete_backup` | banco de Core | ok | |
| `ha_delete_blueprint` | banco de Core | ok | |
| `ha_delete_category` | banco de Core | ok | |
| `ha_delete_config_entry` | banco de Core | ok | |
| `ha_delete_counter` | banco de Core | ok | |
| `ha_delete_floor` | banco de Core | ok | |
| `ha_delete_input_boolean` | banco de Core | ok | |
| `ha_delete_input_button` | banco de Core | ok | |
| `ha_delete_input_datetime` | banco de Core | ok | |
| `ha_delete_input_number` | banco de Core | ok | |
| `ha_delete_input_select` | banco de Core | ok | |
| `ha_delete_input_text` | banco de Core | ok | |
| `ha_delete_label` | banco de Core | ok | |
| `ha_delete_lovelace_dashboard` | banco de Core | ok | |
| `ha_delete_lovelace_resource` | banco de Core | ok | |
| `ha_delete_person` | banco de Core | ok | |
| `ha_delete_scene` | banco de Core | ok | |
| `ha_delete_schedule` | banco de Core | ok | |
| `ha_delete_script` | banco de Core | ok | |
| `ha_delete_subentry` | banco de Core | ok | spec 016 |
| `ha_delete_timer` | banco de Core | ok | |
| `ha_delete_user` | banco de Core | ok | |
| `ha_delete_zone` | banco de Core | ok | |
| `ha_disable_automation` | banco de Core | ok | |
| `ha_disable_config_entry` | banco de Core | ok | |
| `ha_dismiss_persistent_notification` | banco de Core | ok | |
| `ha_enable_automation` | banco de Core | ok | |
| `ha_enable_config_entry` | banco de Core | ok | |
| `ha_finish_timer` | banco de Core | ok | |
| `ha_fire_event` | banco de Core | ok | |
| `ha_ignore_discovery` | banco de Core | ok | spec 016 |
| `ha_ignore_repair` | banco de Core | ok | |
| `ha_import_blueprint` | banco de Core | ok | importador genérico desde `/local/` del banco; GitHub, gist y foro sin probar |
| `ha_import_statistics` | banco de Core | ok | |
| `ha_increment_counter` | banco de Core | ok | |
| `ha_increment_input_number` | banco de Core | ok | |
| `ha_install_update` | banco de Core | ok | spec 015; entidad `update` de plantilla del banco |
| `ha_marketplace_acknowledge_critical` | banco de Core | ok | spec 026; aviso crítico ficticio sembrado en el storage del banco |
| `ha_marketplace_ignore_repository` | instalación real | pendiente | spec 026; no ejecutable en el banco: sin internet el Marketplace no descarga el catálogo y no hay repositorio sobre el que actuar; carga comprobada contra HA real en el test de contrato |
| `ha_marketplace_refresh_repository` | instalación real | pendiente | spec 026; no ejecutable en el banco: sin internet el Marketplace no descarga el catálogo y no hay repositorio sobre el que actuar; carga comprobada contra HA real en el test de contrato |
| `ha_marketplace_remove_repository` | instalación real | pendiente | spec 026; no ejecutable en el banco: sin internet el Marketplace no descarga el catálogo y no hay repositorio sobre el que actuar; carga comprobada contra HA real en el test de contrato |
| `ha_marketplace_uninstall` | instalación real | pendiente | spec 026; no ejecutable en el banco: sin internet no hay catálogo y no se puede instalar ningún repositorio que desinstalar; carga comprobada contra HA real en el test de contrato; el backup previo, con el Supervisor simulado |
| `ha_pause_timer` | banco de Core | ok | |
| `ha_press_input_button` | banco de Core | ok | |
| `ha_process_conversation` | banco de Core | ok | spec 023; disparador de frase del banco |
| `ha_promote_http_config` | VM | pendiente | aplicarla reinicia HA: en el banco de Core solo la vista previa y el rechazo real (spec 021, research R-8) |
| `ha_reload_automations` | banco de Core | ok | |
| `ha_reload_config_entry` | banco de Core | ok | |
| `ha_reload_counters` | banco de Core | no ejecutable | `counter.reload` no existe en Core 2026.11.1: responde `not_supported` sin llamar a HA y está deprecada hasta la 1.3.0 (spec 033); su test del banco es un canario |
| `ha_reload_scenes` | banco de Core | ok | |
| `ha_reload_schedules` | banco de Core | ok | |
| `ha_reload_scripts` | banco de Core | ok | |
| `ha_reload_timers` | banco de Core | ok | |
| `ha_reload_zones` | banco de Core | ok | |
| `ha_remove_device` | banco de Core | ok | |
| `ha_remove_device_from_config_entry` | banco de Core | ok | |
| `ha_remove_entity_registry` | banco de Core | ok | |
| `ha_reset_counter` | banco de Core | ok | |
| `ha_reset_lovelace_dashboard_config` | banco de Core | ok | |
| `ha_restore_backup` | VM | pendiente | spec 031; instantánea antes; en el banco de Core solo la vista previa, el token y la contraseña incorrecta |
| `ha_run_script` | banco de Core | ok | |
| `ha_save_blueprint` | banco de Core | ok | |
| `ha_save_lovelace_dashboard` | banco de Core | ok | |
| `ha_set_counter_value` | banco de Core | ok | |
| `ha_set_entity_exposure` | banco de Core | ok | |
| `ha_set_expose_new_entities` | banco de Core | ok | |
| `ha_set_input_boolean` | banco de Core | ok | |
| `ha_set_input_datetime` | banco de Core | ok | |
| `ha_set_input_number` | banco de Core | ok | |
| `ha_set_input_select` | banco de Core | ok | |
| `ha_set_input_select_options` | banco de Core | ok | |
| `ha_set_input_text` | banco de Core | ok | |
| `ha_set_log_level` | banco de Core | ok | |
| `ha_start_config_entry_flow` | banco de Core | ok | |
| `ha_start_options_flow` | banco de Core | ok | |
| `ha_start_reconfigure_flow` | banco de Core | ok | spec 016 |
| `ha_start_repair_fix` | banco de Core | ok | spec 016 |
| `ha_start_subentry_flow` | banco de Core | ok | spec 016 |
| `ha_start_timer` | banco de Core | ok | |
| `ha_toggle_input_boolean` | banco de Core | ok | |
| `ha_trigger_automation` | banco de Core | ok | |
| `ha_update_area` | banco de Core | ok | |
| `ha_update_backup_config` | banco de Core | ok | |
| `ha_update_category` | banco de Core | ok | |
| `ha_update_config_entry` | banco de Core | ok | spec 016 |
| `ha_update_core_config` | banco de Core | ok | |
| `ha_update_device` | banco de Core | ok | |
| `ha_update_energy_prefs` | banco de Core | ok | |
| `ha_update_entity_registry` | banco de Core | ok | |
| `ha_update_floor` | banco de Core | ok | |
| `ha_update_http_config` | VM | pendiente | aplicarla reinicia HA: en el banco de Core solo la vista previa y el rechazo real (spec 021, research R-8) |
| `ha_update_label` | banco de Core | ok | |
| `ha_update_lovelace_dashboard_metadata` | banco de Core | ok | |
| `ha_update_lovelace_resource` | banco de Core | ok | |
| `ha_update_network_config` | banco de Core | ok | |
| `ha_update_person` | banco de Core | ok | |
| `ha_update_statistics_metadata` | banco de Core | ok | |
| `ha_update_subentry` | banco de Core | ok | spec 016 |
| `ha_update_user` | banco de Core | ok | |
| `sv_add_store_repository` | VM | pendiente | repositorio de prueba |
| `sv_apply_resolution_suggestion` | VM | pendiente | instantánea antes; sugerencia provocada |
| `sv_call_api` | VM | pendiente | |
| `sv_check_core_config` | VM | pendiente | |
| `sv_check_for_updates` | VM | pendiente | spec 015 |
| `sv_create_backup_full` | VM | pendiente | |
| `sv_create_backup_partial` | VM | pendiente | |
| `sv_create_mount` | VM | pendiente | recurso CIFS y NFS de prueba |
| `sv_create_safety_backup` | VM | pendiente | spec 031: cifrado con la clave de HA (`safety_backup_encryption`); restaurarlo con `sv_restore_backup_full` sin `password` y desde la interfaz con el kit de emergencia |
| `sv_create_vlan` | VM | pendiente | VM con segunda interfaz; instantánea antes |
| `sv_delete_backup` | VM | pendiente | instantánea antes |
| `sv_delete_mount` | VM | pendiente | instantánea antes |
| `sv_dismiss_resolution_issue` | VM | pendiente | |
| `sv_dismiss_resolution_suggestion` | VM | pendiente | |
| `sv_get_job_status` | VM | pendiente | |
| `sv_install_addon` | VM | pendiente | add-on de prueba |
| `sv_reboot_host` | VM | pendiente | instantánea antes |
| `sv_rebuild_addon` | VM | pendiente | app local de prueba |
| `sv_rebuild_core` | VM | pendiente | instantánea antes |
| `sv_reload_backups` | VM | pendiente | |
| `sv_reload_mount` | VM | pendiente | |
| `sv_reload_network` | VM | pendiente | |
| `sv_reload_store` | VM | pendiente | |
| `sv_reload_supervisor` | VM | pendiente | |
| `sv_remove_store_repository` | VM | pendiente | repositorio de prueba |
| `sv_repair_store_repository` | VM | pendiente | repositorio de prueba |
| `sv_repair_supervisor` | VM | pendiente | instantánea antes |
| `sv_restart_addon` | VM | pendiente | add-on de prueba |
| `sv_restart_core` | VM | pendiente | instantánea antes |
| `sv_restart_supervisor` | VM | pendiente | instantánea antes |
| `sv_restore_backup_full` | VM | pendiente | instantánea antes |
| `sv_restore_backup_partial` | VM | pendiente | instantánea antes |
| `sv_set_addon_options` | VM | pendiente | add-on de prueba |
| `sv_set_backup_settings` | VM | pendiente | |
| `sv_set_boot_slot` | VM | pendiente | instantánea antes; VM con HAOS y dos ranuras |
| `sv_set_core_options` | VM | pendiente | |
| `sv_set_default_backup_mount` | VM | pendiente | |
| `sv_set_hostname` | VM | pendiente | instantánea antes |
| `sv_set_supervisor_options` | VM | pendiente | |
| `sv_set_swap` | VM | pendiente | HAOS ≥ 15; instantánea antes |
| `sv_shutdown_host` | VM | pendiente | instantánea antes; encender la VM a mano |
| `sv_start_addon` | VM | pendiente | add-on de prueba |
| `sv_start_core` | VM | pendiente | instantánea antes; Core parado |
| `sv_stop_addon` | VM | pendiente | add-on de prueba |
| `sv_uninstall_addon` | VM | pendiente | add-on de prueba |
| `sv_update_addon` | VM | pendiente | add-on de prueba |
| `sv_update_core` | VM | pendiente | spec 015; instantánea antes |
| `sv_update_mount` | VM | pendiente | instantánea antes |
| `sv_update_network_interface` | VM | pendiente | VM con segunda interfaz; instantánea antes; comprobar el rechazo de la principal |
| `sv_update_os` | VM | pendiente | spec 015; instantánea antes; reinicio del host después |
| `sv_update_supervisor` | VM | pendiente | spec 015; instantánea antes |
<!-- matriz-pruebas:fin -->

El orden no es el del número: primero 009 y 010; después 011 (la tabla y las
genéricas, antes que cualquier tool dedicada) y 028; luego el resto según las
dependencias de `specs/008-cobertura-total/plan.md`.

Lo que antes estaba en esta hoja de ruta como pendiente y ahora es parte del
programa:

- **Guardar un dashboard por vistas** (018). En la prueba en vivo de la 1.1.2
  el cliente se dejó tarjetas al reescribir 134 KB; la vista previa lo mostró.
- **`ha_call_service_response` y la denylist** (018, hecho): en la 1.1.2
  rechazaba todo lo de la denylist sin aceptar `confirmation_token`, así que
  una acción peligrosa con respuesta (`conversation.process`) no podía
  devolverla ni confirmando. Desde la 1.2.0 se confirma en dos pasos.
- **Actualizar Core, OS y Supervisor con vista previa útil** (015).
  Resuelto en 1.2.0: `sv_update_core`, `sv_update_os` y
  `sv_update_supervisor` (versión actual → destino, backup, salud y bloqueos)
  y `ha_install_update` para las entidades `update`; la prueba real de las
  `sv_*`, pendiente en la VM de la 014.
- **Banco de pruebas** (010, 028 y 014): HA Core en contenedor en el CI para
  ejecutar de verdad las escrituras de Core; para el Supervisor, una VM con
  HAOS cuyo procedimiento se documenta y que queda como prueba manual.
- **Probar `hassio_role: manager`** (014). En el Supervisor 2026.11.0,
  `/addons/self/options/config` está en `api_bypass` y el patrón de `manager`
  cubre todas las rutas que usa Hermes y todos los huecos propuestos (salvo
  `/reload_updates`; `/refresh_updates` sí entra). `admin` solo añade
  `/addons/{app}/security`, `/auth/reset`, `/auth/list`, `/os/datadisk/wipe` e
  `/ingress/panels`, que Hermes no usa. El comentario de `config.yaml` ya
  está corregido (014) y `tests/test_rutas_supervisor_rol.py` comprueba las
  rutas contra los patrones de 2026.11.0; queda la prueba en vivo
  (procedimiento en `docs/BANCO-SUPERVISOR.md`). Es un cambio de permisos: el
  Supervisor lo enseña al actualizar; el cambio de rol se decide al final, tras
  la prueba manual (D-02).
- **Distinguir errores fatales de avisos en `sv_get_job_status`** (027,
  hecho): el Supervisor 2026.11.0 no da gravedad, así que cualquier entrada en
  `errors` da `success: false`, y la descripción y la guía lo dicen. Los
  errores de los sub-jobs, que no suben al job, salen en `child_errors` y
  también dan `success: false`; el sondeo del safety backup los cuenta igual.
- **Aplicar sugerencias del Supervisor** con confirmación y vista previa
  completa (022).
- **Escritura en el Marketplace** (026, hecho en parte): reconocer críticos,
  ignorar retirados, quitar personalizados, refrescar y desinstalar (con
  backup previo), con confirmación y vista previa completa. Instalar, fijar
  versión, betas y añadir no tienen tool (DV-1, duda D-29).
- **Auditoría de llamadas a acciones, estado del sistema y notificaciones
  persistentes** (012 y 029); **mantenimiento de estadísticas** (validar,
  corregir unidades, ajustar sumas) **y energía** (020). Las estadísticas
  agregadas ya existen (`ha_statistics_during_period`).
- **`outputSchema` y alternativas nativas de MCP a la confirmación** (027,
  investigado; research R-6 de la spec 027, con el SDK `mcp` 2.3.0):
  - `outputSchema`: hoy solo lo declaran `ping` y `hermes_guide` (el SDK lo
    infiere de `-> str`), y un test lo fija. Daría al cliente una forma de
    validar las respuestas, pero cada tool devolvería el JSON dos veces,
    `tools/list` crecería y las respuestas de Hermes no tienen una forma única
    (errores, vistas previas con token, listas recortadas): el esquema sería
    una unión sin validación real. **Recomendación**: no declararlo en la
    1.2.0; reconsiderarlo para las tools con el sobre común
    `{count, items, truncated}`.
  - Vía nativa para pedir datos a mitad de una llamada (`InputRequiredResult`
    y la elicitación de MCP 2026-07-28): el cliente enseñaría la vista previa y
    pediría el «sí» con su propia interfaz. No sustituye a los dos pasos:
    depende de que el cliente lo implemente, y el token de Hermes ya está
    atado a la tool y a los argumentos. **Recomendación**: segunda vía
    opcional en una versión posterior, detrás de la capacidad del cliente y
    con el mismo token por debajo (D-10 de la spec 008).
- **Terminología «apps» y traducciones de las opciones** (027, hecho):
  `translations/en.yaml` y `es.yaml` con las opciones (32 desde la 031), y «app (add-on)» en
  las descripciones de las tools de apps, en la guía y en las instrucciones;
  los nombres de las tools no cambian.
- **`oauth_cimd_allowed_hosts`** (027, hecho): hosts CIMD conocidos y cómo
  averiguar otro, junto a la prueba de CIMD con claude.ai; el valor por
  defecto no cambia en la 1.2.0.

Queda fuera del programa la clase B (suscripciones, streaming e internos del
frontend, que no aplican a un servidor MCP) y la clase D (peligroso o no
automatizable), que la tabla deniega. La justificación por grupo está en la
spec 008.

### Hecho en 1.2.1 — carpetas /addons y /share (spec 034)

Spec, plan y tareas en `specs/034-carpetas-addons-y-share/`. Hermes pasa de
359 a 366 tools.

- **Siete tools nuevas en la familia `addons_share`** (desactivable, activa
  por defecto): `fs_list_dir_in_folder`, `fs_stat_in_folder` y
  `fs_read_file_in_folder` (lectura) y `fs_write_file_in_folder`,
  `fs_create_dir_in_folder`, `fs_move_in_folder` y `fs_delete_in_folder`
  (siempre en dos pasos, con el token atado a una huella de lo que vio la
  vista previa). Todas reciben `folder` (`addons` o `share`); las rutas pasan
  la misma validación que en `/config`.
- **Montaje `addons` con escritura**, del tipo heredado: el Supervisor
  2026.11 lo avisa en su log; `local_apps` rompería las instalaciones con un
  Supervisor anterior a 2026.07.
- **Sin backup automático** en esas carpetas: la vista previa lo dice y da
  la llamada del backup parcial.
- **Protecciones**: no se borra ni se mueve una app local instalada, la raíz
  de una carpeta ni un punto de montaje; el aviso de `/addons` en cada vista
  previa; la lista negra por nombre de fichero de `/config`.
- **Privilegios en `sv_install_addon`, `sv_update_addon` y
  `sv_rebuild_addon`**: la vista previa enseña `privileges` (tienda,
  instalada, lo que declara el `config.*` de una app local y cuáles son
  elevados) y el token se ata a ese bloque; `sv_rebuild_addon` ata ahora su
  token al estado. Para una app local, `store_copy_stale` si algo en
  `/addons` cambió desde la última recarga de la tienda lanzada por Hermes
  (las recargas de Hermes van en serie) y `folder_busy` si la espera del
  candado de `/addons` pasa de 15 s.
- Guía (tema `folders`), DOCS, SECURITY y los README al día. Las cuatro que
  modifican tienen su fila «VM / pendiente» en la matriz de la 014 y están
  fuera del banco de Core (no hablan con Core); la prueba en vivo, en
  «Pruebas manuales pendientes».

#### Dudas abiertas para el mantenedor (1.2.1)

- **D-31** (034) — Pasar el montaje `addons` a `local_apps` (y la raíz a
  `/local_apps`) cuando el mínimo admitido del Supervisor sea 2026.07 o
  posterior: desaparece el aviso del tipo heredado. Hoy rompería las
  instalaciones con un Supervisor anterior, que rechaza el manifiesto. La
  raíz ya se puede cambiar con `HERMES_ADDONS_BASE`.
- **D-32** (034) — La redacción en `/addons` y `/share` es por nombre de
  fichero, igual que en `/config`: un fichero con nombre normal (un
  `options.json`, un `.env` con otro nombre, el código de una app) se
  devuelve tal cual, sin redactar. Decidir si conviene redactar también el
  contenido (`redact_secrets`) al leer de estas carpetas, o algún nombre más
  en la lista negra.

### 1.3.0 y posteriores

- Retirar los alias `ha_hacs_*` (anunciado para la 1.3.0) y, como tarde en la
  última versión de Hermes publicada antes de HA 2027.9,
  `ha_remove_device_from_config_entry` (D-08 de la spec 008).
- Socket Unix del Supervisor y API `/v2`, cuando se publiquen para las apps
  (bloqueados; lo que hará falta, en el apartado siguiente).
- Lo que el programa deja al mantenedor: la lista completa está en
  «Dudas abiertas para el mantenedor (1.2.0)», en el apartado del programa de
  cobertura total.
- Las dudas de la 1.2.1 (D-31 y D-32): pasar el montaje `addons` a
  `local_apps` cuando suba el mínimo admitido del Supervisor, y la redacción
  por nombre de fichero en `/addons` y `/share`.

#### Socket Unix y API `/v2` del Supervisor: qué hará falta

Desde la 1.2.0 Hermes detecta los dos al arrancar y lo anota en el log, sin
usarlos (`supervisor_platform`, con `transport`, `unix_socket_offered` y
`api_v2_enabled`; los avisos `supervisor_unix_socket_offered` y
`supervisor_api_v2_enabled`). Leído en el código del Supervisor 2026.11.0
(research R-2 y R-3 de la spec 027).

**Socket Unix.** Hoy solo lo tiene Core (`docker/homeassistant.py`); a las
apps no se les inyecta `SUPERVISOR_SOCKET` (`docker/app.py`). En el socket no
se lee ningún token: el socket identifica a quien llama. Cuando se publique
para las apps:

1. Conectar con `aiohttp.UnixConnector(path=SUPERVISOR_SOCKET)` y la URL base
   `http://supervisor`, sin cabecera `Authorization` en esas peticiones. El
   WebSocket de Core que usa Hermes (`/core/api/websocket`, por el proxy del
   Supervisor) seguiría pidiendo el token en el mensaje `auth`.
2. Volver a TCP si el socket no existe o no responde a `/supervisor/ping`, con
   el mismo arranque de hoy.
3. Revisar qué rutas permite el rol de una app por el socket
   (`check_principal_access`, los mismos patrones que por TCP) y la redacción
   de red del log (por el socket no hay IP).
4. Tests con un servidor aiohttp en un socket Unix (solo Linux: omitidos en
   Windows) o con un conector simulado.

**API `/v2`.** La V1 se monta siempre en la raíz; la V2, en `/v2`, solo con la
opción de desarrollo `supervisor_v2_api`, y activarla no quita la V1. En la V2
las claves de error no se traducen a sus nombres antiguos y los roles tienen
sus propios patrones (`_V2_PATTERNS`), con las mismas reglas. Rutas que usa
Hermes:

| Hermes (V1) | V2 | Cambio de formato en la V2 |
|---|---|---|
| `GET /supervisor/info` | `GET /v2/supervisor/info` | sin `addons` ni `wait_boot` |
| `GET /info`, `GET /host/info`, `GET /core/info` | igual con `/v2` | `host/info` cambia de forma |
| `GET /addons` | `GET /v2/apps` | lista de apps |
| `GET /store/addons` | `GET /v2/store/apps` | lista de apps del catálogo |
| `GET /addons/{slug}/info` | `GET /v2/apps/{app}/info` | solo apps instaladas; para el catálogo, `GET /v2/store/apps/{app}` |
| `GET /addons/{slug}/stats` | `GET /v2/apps/{app}/stats` | cambia de forma |
| `GET /addons/{slug}/logs` | `GET /v2/apps/{app}/logs` | mismo texto |
| `POST /addons/{slug}/start`, `stop`, `restart`, `options`, `uninstall` | `POST /v2/apps/{app}/…` | — |
| `POST /store/addons/{slug}/install`, `update` | `POST /v2/store/apps/{app}/…` | — |
| `GET /backups`, `GET /backups/{slug}/info` | igual con `/v2` | la clave `apps` en vez de `addons` |
| `POST /backups/new/full`, `partial`; `POST /backups/{slug}/restore/full`, `partial` | igual con `/v2` | `partial`: cuerpo con `apps` en vez de `addons` |
| `DELETE /backups/{slug}` | igual con `/v2` | — |
| `GET /jobs/{id}` | igual con `/v2` | — |
| `GET /resolution/info`, `DELETE /resolution/{clase}/{uuid}` | igual con `/v2` | cambia de forma |
| `POST /core/check`, `restart`; `POST /host/reboot` | igual con `/v2` | — |

El test de deriva del inventario (`scripts/inventario/`) extrae **solo la V1**:
avisará si una versión del Supervisor quita o cambia rutas de la V1, pero no ve
las rutas nuevas de la V2. Un inventario de la V2 queda como duda D-4 de la
spec 027 mientras la V2 sea una opción de desarrollo.

## Hermes frente a la integración oficial `mcp_server`

Desde HA 2026.11, la integración oficial `mcp_server` incluye una API
«Home Assistant» que permite a un administrador consultar todo y ejecutar
cualquier acción. El control y la consulta ya no distinguen a Hermes.

- **Lo que solo tiene Hermes:** ficheros de `/config` con copia por fichero;
  crear y editar automatizaciones, scripts, escenas y helpers; escritura en
  registros; dashboards y recursos de Lovelace; gestión de add-ons, backups,
  restauración y reinicios a través del Supervisor; confirmación en dos pasos
  atada a los argumentos y backup de seguridad.
- **Lo que solo tiene la oficial:** viene con Home Assistant y no necesita
  Supervisor; modo de solo lectura y control por usuario; intents de Assist
  limitados a lo expuesto; prompts, búsqueda y acceso a calendario, listas
  y multimedia.

Hermes se centra en la **administración y la configuración con salvaguardas**,
donde la integración oficial no llega.
