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

**Verificado contra:** Home Assistant Core **2026.11.1**, Supervisor **2026.11.0**
y la especificación MCP **2026-07-28**. El código de Core y del Supervisor se
leyó en esos tags; las tools de lectura se probaron en una instalación de prueba
con HA 2026.11.1. De las 124 tools que modifican, las 100 `ha_*` se ejecutan
en cada push en el CI contra HA Core 2026.11.1 real (banco de pruebas): las 47
de helpers en la spec 010 y las 53 restantes en la 028 (ver «Banco de Core:
helpers» y «Banco de Core: escrituras» más abajo). Funcionan 99 (dos de
ellas con un hallazgo abierto con un argumento concreto);
`ha_reload_counters` falla (ver más abajo). Las 24 `fs_*` y `sv_*` no
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
| Campos `config_entries` y `config_entries_subentries` del dispositivo | HA **2027.8** (`primary_config_entry`: **2027.10**) | Ninguno desde la 1.0.12: los recuentos de dispositivos por integración usan `config_entry_id` y solo recurren a `config_entries` como respaldo |
| Comando `config/device_registry/remove_config_entry` | HA **2027.9** | `ha_remove_device_from_config_entry`, deprecada en la 1.0.12, se retira en la versión de Hermes que fije la spec 008 (como tarde, la última publicada antes de HA 2027.9); `ha_remove_device` usa `config/device_registry/remove` desde HA 2026.9 |
| Comando `lovelace/resources` (alias de `lovelace/resources/list`) | Anunciado para 2025.1; sigue presente, puede desaparecer sin aviso | Ninguno desde la 1.0.12: `ha_list_lovelace_resources` usa `lovelace/resources/list` |
| Campo `has_mean` de estadísticas | Plazo vencido; sigue presente | Solo documentación |
| Acceso TCP de las apps al Supervisor (`SUPERVISOR_TOKEN`) en favor de un socket Unix | Sin fecha. En 2026.11.0 el socket existe solo para Core (`SUPERVISOR_SOCKET` no se inyecta en las apps) y el aviso `deprecated_tcp_api_request` solo salta con el token de Core | Hermes usa solo TCP |
| API `/v2` del Supervisor (`addons` → `apps`) | Sin fecha; hoy detrás de una opción de desarrollo y sin retirar la V1 | Ninguno hoy |
| Alias `ha_hacs_*` | Hermes **1.3.0** | Se retiran; desde la 1.1.0 devuelven `_deprecated` |
| Acciones `hassio.*_update` | Ya no existen en Core 2026.11 | Ninguno: las de la denylist están muertas; actualizar va por `update.install` |
| DCR (RFC 7591) en MCP | Deprecado en la revisión 2026-07-28; la spec garantiza al menos 12 meses | OAuth de Hermes |
| Constante de versiones de protocolo admitidas del SDK `mcp` (sustituida por las de handshake y modernas) | Deprecada en 2.x | Puede romper con un futuro SDK 3.x |

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

### Programa de cobertura total (spec 008) — 1.2.0

Objetivo: que Hermes cubra todo lo que HA Core 2026.11.1 y el Supervisor
2026.11.0 ofrecen a un administrador. Modelo híbrido: tools dedicadas para lo
de prioridad alta y media-alta y para lo que tiene consecuencias; cuatro tools
genéricas (WebSocket de Core y API del Supervisor, separadas en lectura y
escritura) gobernadas por una tabla de clasificación fail-closed para la cola
larga y la gestión de integraciones concretas; familias de tools que se pueden
desactivar (todas activas por defecto); banco de pruebas con HA Core real en el
CI. Todo sale como **una sola versión 1.2.0**; fusionar y publicar los decide
el mantenedor. Spec, plan, tareas, investigación e inventarios en
`specs/008-cobertura-total/`.

| N.º | Sub-feature | CAP | Estado |
|---|---|---|---|
| 009 | Correcciones pendientes y versión 1.2.0 | 010–018, 021, 024 | hecha |
| 010 | Banco de pruebas de Core (infraestructura y helpers) | 005, 034 | hecha |
| 011 | Política de comandos: tabla, genéricas, familias, deriva, guía | 001–004, 007, 008 | hecha: tabla, cuatro genéricas, familias y `tool_families_disabled`, tema `generic_commands` con `search`, extractor y generador; convergencia tras la revisión independiente cerrada (T044–T049); prueba de las genéricas en el banco de Core (T027) activada al integrarla con la 010 |
| 012 | Diagnóstico de Core | 040, 041, 042, 047 | pendiente |
| 013 | Diagnóstico del Supervisor | 081, 085, 087 (lectura), 088, 089 | hecha: once tools de solo lectura en la familia `system_diagnostics` (logs de Core, Supervisor, plugins y host, también de arranques anteriores; servicios del host, uso de disco, OS y swap); `boot`/`latest` en `sv_get_addon_logs`; 28 rutas a `dedicated` y 3 a `read` (jobs, sugerencias de un issue, discos montables); `POST /security/integrity` sigue `deny` (410 en el Supervisor 2026.11); prueba en vivo pendiente (VM de la 014, después instalación real) |
| 014 | Banco del Supervisor: procedimiento, matriz y `hassio_role` | 006, 022, 034, 035 | hecha |
| 015 | Actualizaciones del sistema | 064, 080 | pendiente |
| 016 | Integraciones: flujos y Repairs | 036, 037, 044, 045, 048 | pendiente |
| 017 | Automatización asistida | 038, 040, 046, 051, 052 | pendiente |
| 018 | Mejoras de tools existentes | 019, 020, 023 | hecha: guardado por vista, `ha_call_service_response` con token para la denylist (y la denylist también en la capa de cliente) y sobre común de las listas nuevas con su test transversal; las pruebas de banco (guardado por vista y `conversation.process`) corren en el job del banco de Core |
| 019 | Montajes y ajustes de backup | 083 | pendiente |
| 020 | Estadísticas y energía | 050, 054 | pendiente |
| 021 | Configuración del sistema | 053, 055, 056, 069, 074 | pendiente |
| 022 | Control de Core y del Supervisor | 084, 087 (escritura), 091, 092, 094 | pendiente |
| 023 | Assist y conversación | 060–063 | pendiente |
| 024 | Menores de Core | 059, 065–067, 070–073 | pendiente |
| 025 | Integraciones específicas por la tabla | 100–106 | pendiente |
| 026 | Escritura en el Marketplace | 075 | pendiente |
| 027 | Plataforma y deprecaciones | 025, 026, 028–033 | pendiente |
| 028 | Pruebas de las escrituras de Core en el banco | 034 | hecha |
| 029 | Estado del sistema y estadísticas de Core | 043, 049, 058, 068 | hecha: familias `system_status` (cinco tools, CAP-043) y `recorder` (tres, CAP-049), `ws_collect_subscription`, auditoría de acciones y red y HTTP por la genérica (CAP-058, CAP-068), tabla, guía y banco de las ocho. Solo leen, así que no tienen fila en la matriz de la 014; en vivo (salud con `cloud` y `hassio`, un reinicio pendiente y la validación de estadísticas de una instalación real), en las pruebas manuales pendientes |
| 030 | Tienda de apps | 082, 093 | pendiente |
| 031 | Backups de la integración y safety backups cifrados | 027, 057 | pendiente |
| 032 | Host y red del host | 086, 090 | pendiente |

#### Banco de Core: helpers (010)

El job `banco de Core` del workflow `Tests` arranca HA Core 2026.11.1 (imagen
fijada por digest), conecta Hermes por un Supervisor simulado como en un
add-on y ejecuta las tools que modifican de los 11 dominios de helpers; el
efecto lo comprueba un lector que habla directamente con Core. El inventario
está en `tests/banco/cobertura.py` y un test de la suite normal impide que una
tool nueva de estos dominios entre sin probarse en el banco.

Ejecutadas en el banco con su efecto comprobado (46; el job exige que cada
una se haya llamado con éxito en un test que ha pasado):

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

No ejecutables en el banco: ninguna.

Se ejecuta en el banco pero falla (`FALLAN_EN_BANCO`; no cuenta como probada).
Hallazgo pendiente de arreglo en la spec 033:

- **`ha_reload_counters` no funciona.** HA Core 2026.11.1 no tiene el servicio
  `counter.reload` (la integración `counter` solo registra `increment`,
  `decrement`, `reset` y `set_value`): Core responde 400 y la tool termina en
  «Error executing tool». En el banco está como fallo esperado estricto
  (`xfail`) que solo admite ese error y que se pondrá en rojo cuando deje de
  fallar.

#### Banco de Core: escrituras (028)

En el mismo job, el resto de tools `ha_*` que modifican. El inventario está en
`tests/banco/cobertura_escrituras.py` y un test de la suite normal
(`tests/test_banco_cobertura_escrituras.py`) obliga a que las 126 tools que
modifican (las 124 de la 1.1.2 y las 2 genéricas de la 011) estén probadas
en el banco (010, 011 o 028), anotadas como hallazgo que
falla (`ha_reload_counters`) o fuera de él con su motivo.

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

Hallazgos de la 028, pendientes de arreglo en la spec 033 (en el banco, fallo
esperado estricto que solo admite ese error; las dos tools siguen contando
como probadas porque su camino normal funciona):

- `ha_create_scene_from_current` con `name` falla siempre: `scene.create` de
  Core 2026.11.1 no admite ese campo y responde 400. Su descripción dice que
  «HA decide» y que una colisión de `scene_id` da error; Core reemplaza la
  escena (o, si es de configuración, solo avisa en el log).
- **Seguridad, prioridad máxima:** el token de `ha_run_script` y
  `ha_trigger_automation` con una entidad restringida no cubre `variables`:
  se acepta una confirmación con variables distintas de las de la vista
  previa.

#### Matriz de pruebas: tool → entorno → resultado (014)

Una fila por cada tool que modifica (sin `readOnlyHint` en el registro de
producción, con todas las familias activas): dónde se prueba contra el
software real y con qué resultado. Entornos: **banco de Core** (el job del CI
con HA Core 2026.11.1 real; el resultado sale de los inventarios
`tests/banco/cobertura*.py`), **VM** (Home Assistant OS con el Supervisor
2026.11.0, según el procedimiento de [BANCO-SUPERVISOR.md](BANCO-SUPERVISOR.md);
todas las `sv_*` y `fs_*` que modifican) e **instalación real**. Resultados:
**ok**, **falla** (con la causa en la nota) y **pendiente**. Una tool del
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
| `fs_delete_file` | VM | pendiente | |
| `fs_move_file` | VM | pendiente | |
| `fs_restore_file_backup` | VM | pendiente | |
| `fs_set_secret` | VM | pendiente | |
| `fs_write_file` | VM | pendiente | |
| `ha_abort_config_entry_flow` | banco de Core | ok | |
| `ha_activate_scene` | banco de Core | ok | |
| `ha_call_service` | banco de Core | ok | |
| `ha_call_service_response` | banco de Core | ok | |
| `ha_call_ws_command` | banco de Core | ok | |
| `ha_cancel_timer` | banco de Core | ok | |
| `ha_cancel_wait` | banco de Core | ok | |
| `ha_change_timer` | banco de Core | ok | |
| `ha_continue_config_entry_flow` | banco de Core | ok | |
| `ha_continue_options_flow` | banco de Core | ok | |
| `ha_create_area` | banco de Core | ok | |
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
| `ha_create_scene_from_current` | banco de Core | falla | con `name` falla siempre: `scene.create` de Core 2026.11.1 no admite ese campo y responde 400; sin `name` funciona (spec 033) |
| `ha_cycle_input_select` | banco de Core | ok | |
| `ha_decrement_counter` | banco de Core | ok | |
| `ha_decrement_input_number` | banco de Core | ok | |
| `ha_delete_area` | banco de Core | ok | |
| `ha_delete_automation` | banco de Core | ok | |
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
| `ha_delete_timer` | banco de Core | ok | |
| `ha_delete_zone` | banco de Core | ok | |
| `ha_disable_automation` | banco de Core | ok | |
| `ha_disable_config_entry` | banco de Core | ok | |
| `ha_enable_automation` | banco de Core | ok | |
| `ha_enable_config_entry` | banco de Core | ok | |
| `ha_finish_timer` | banco de Core | ok | |
| `ha_fire_event` | banco de Core | ok | |
| `ha_ignore_repair` | banco de Core | ok | |
| `ha_increment_counter` | banco de Core | ok | |
| `ha_increment_input_number` | banco de Core | ok | |
| `ha_pause_timer` | banco de Core | ok | |
| `ha_press_input_button` | banco de Core | ok | |
| `ha_reload_automations` | banco de Core | ok | |
| `ha_reload_config_entry` | banco de Core | ok | |
| `ha_reload_counters` | banco de Core | falla | `counter.reload` no existe en Core 2026.11.1 (spec 033) |
| `ha_reload_scenes` | banco de Core | ok | |
| `ha_reload_schedules` | banco de Core | ok | |
| `ha_reload_scripts` | banco de Core | ok | |
| `ha_reload_timers` | banco de Core | ok | |
| `ha_reload_zones` | banco de Core | ok | |
| `ha_remove_device` | banco de Core | ok | |
| `ha_remove_device_from_config_entry` | banco de Core | ok | |
| `ha_remove_entity_registry` | banco de Core | ok | |
| `ha_reset_counter` | banco de Core | ok | |
| `ha_run_script` | banco de Core | falla | seguridad: con una entidad restringida, el token no cubre `variables`; el camino normal funciona (spec 033) |
| `ha_save_lovelace_dashboard` | banco de Core | ok | |
| `ha_set_counter_value` | banco de Core | ok | |
| `ha_set_input_boolean` | banco de Core | ok | |
| `ha_set_input_datetime` | banco de Core | ok | |
| `ha_set_input_number` | banco de Core | ok | |
| `ha_set_input_select` | banco de Core | ok | |
| `ha_set_input_select_options` | banco de Core | ok | |
| `ha_set_input_text` | banco de Core | ok | |
| `ha_start_config_entry_flow` | banco de Core | ok | |
| `ha_start_options_flow` | banco de Core | ok | |
| `ha_start_timer` | banco de Core | ok | |
| `ha_toggle_input_boolean` | banco de Core | ok | |
| `ha_trigger_automation` | banco de Core | ok | comparte el hallazgo de seguridad de `ha_run_script` (spec 033) |
| `ha_update_area` | banco de Core | ok | |
| `ha_update_category` | banco de Core | ok | |
| `ha_update_device` | banco de Core | ok | |
| `ha_update_entity_registry` | banco de Core | ok | |
| `ha_update_floor` | banco de Core | ok | |
| `ha_update_label` | banco de Core | ok | |
| `ha_update_lovelace_dashboard_metadata` | banco de Core | ok | |
| `ha_update_lovelace_resource` | banco de Core | ok | |
| `ha_update_person` | banco de Core | ok | |
| `sv_call_api` | VM | pendiente | |
| `sv_check_core_config` | VM | pendiente | |
| `sv_create_backup_full` | VM | pendiente | |
| `sv_create_backup_partial` | VM | pendiente | |
| `sv_create_safety_backup` | VM | pendiente | |
| `sv_delete_backup` | VM | pendiente | instantánea antes |
| `sv_dismiss_resolution_issue` | VM | pendiente | |
| `sv_dismiss_resolution_suggestion` | VM | pendiente | |
| `sv_get_job_status` | VM | pendiente | |
| `sv_install_addon` | VM | pendiente | add-on de prueba |
| `sv_reboot_host` | VM | pendiente | instantánea antes |
| `sv_restart_addon` | VM | pendiente | add-on de prueba |
| `sv_restart_core` | VM | pendiente | instantánea antes |
| `sv_restore_backup_full` | VM | pendiente | instantánea antes |
| `sv_restore_backup_partial` | VM | pendiente | instantánea antes |
| `sv_set_addon_options` | VM | pendiente | add-on de prueba |
| `sv_start_addon` | VM | pendiente | add-on de prueba |
| `sv_stop_addon` | VM | pendiente | add-on de prueba |
| `sv_uninstall_addon` | VM | pendiente | add-on de prueba |
| `sv_update_addon` | VM | pendiente | add-on de prueba |
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
- **Actualizar Core, OS y Supervisor con vista previa útil** (015): versión
  actual → destino, notas, backup y salud del sistema. Hoy solo con
  `update.install` confirmando.
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
- **Distinguir errores fatales de avisos en `sv_get_job_status`** (027): hasta
  que el Supervisor dé una señal fiable, se documenta.
- **Cifrado de los safety backups** (031).
- **Aplicar sugerencias del Supervisor** con confirmación y vista previa
  completa (022).
- **Escritura en el Marketplace** (026), con confirmación, backup previo y
  vista previa completa.
- **Flujos de reparación de Repairs y textos traducidos** (016).
- **Subentries y reconfigure** (016). **Helpers por config entry**: ya se
  pueden crear con los flujos; falta explicarlo en la guía (016).
  **Triggers y condiciones por propósito; resolución de targets** (017).
- **Auditoría de llamadas a acciones, estado del sistema y notificaciones
  persistentes** (012 y 029); **mantenimiento de estadísticas** (validar,
  corregir unidades, ajustar sumas) **y energía** (020). Las estadísticas
  agregadas ya existen (`ha_statistics_during_period`).
- **`outputSchema` y alternativas nativas de MCP a la confirmación** (027,
  solo investigación).
- **Terminología «apps» y traducciones de las opciones** (027).
- **`oauth_cimd_allowed_hosts`** (027): se documentan los hosts CIMD conocidos;
  el valor por defecto no cambia en la 1.2.0.

Queda fuera del programa la clase B (suscripciones, streaming e internos del
frontend, que no aplican a un servidor MCP) y la clase D (peligroso o no
automatizable), que la tabla deniega. La justificación por grupo está en la
spec 008.

### 1.3.0 y posteriores

- Retirar los alias `ha_hacs_*` (anunciado para la 1.3.0) y, como tarde antes
  de HA 2027.9, `ha_remove_device_from_config_entry`.
- Socket Unix del Supervisor y API `/v2`, cuando se publiquen para las apps
  (bloqueados; la spec 027 deja escrito lo que hará falta).
- Lo que el programa deja al mantenedor (spec 008, «Dudas para el final»):
  candidatas de clase D con salvaguardas fuertes, bajar a
  `hassio_role: manager`, familias de riesgo alto desactivadas por defecto,
  tamaño de la lista de tools, el banco también contra HA 2024.10, la VM en el
  CI con KVM, unificar la forma de las listas de las tools existentes, el valor
  por defecto de `oauth_cimd_allowed_hosts` y la vía nativa de MCP para
  confirmar.

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
