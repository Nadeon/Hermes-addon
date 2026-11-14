<!-- Hoja de ruta de Hermes tras la revisión de compatibilidad de noviembre de
     2026. El plan por versiones es una propuesta pendiente de decisión del
     mantenedor, no un compromiso de fechas. -->

# Hoja de ruta de Hermes

**Revisión:** 2026-11-14, sobre Hermes **1.1.1** (la revisión de
compatibilidad se hizo sobre la 1.0.11; la 1.0.12 corrige lo que se encontró,
la 1.1.0 añade lo planificado para ella y la 1.1.1 corrige lo que encontraron
las pruebas en vivo de la 1.1.0). La 1.0.12 no se publicó por separado: llega
a los usuarios dentro de la 1.1.0.

**Verificado contra:** Home Assistant Core **2026.11.1**, Supervisor **2026.11.0**
y la especificación MCP **2026-07-28**. El código de Core y del Supervisor se
leyó en esos tags; las tools de lectura se probaron en una instalación de prueba
con HA 2026.11.1. Las tools de escritura no se ejecutaron: sus fallos están
confirmados leyendo el código de Hermes y el de Home Assistant.

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
| 21 | Las tools de lista devuelven formas distintas (lista suelta, bloques sueltos, `{count, items}`) | Cosmética | Hermes | Pendiente |
| 22 | `period: "year"` en estadísticas se acepta sin comprobar que HA sea ≥ 2026.3 | Cosmética | Hermes | Corregido |
| 23 | El log muestra un traceback inofensivo al apagar y no redacta direcciones de red | Cosmética | Hermes | Pendiente; la redacción de red, resuelta en 1.1.0 (`log_redact_network`) |

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
| Comando `config/device_registry/remove_config_entry` | HA **2027.9** | `ha_remove_device_from_config_entry`, deprecada en la 1.0.12, se retirará antes; `ha_remove_device` usa `config/device_registry/remove` desde HA 2026.9 |
| Comando `lovelace/resources` (alias de `lovelace/resources/list`) | Anunciado para 2025.1; sigue presente, puede desaparecer sin aviso | Ninguno desde la 1.0.12: `ha_list_lovelace_resources` usa `lovelace/resources/list` |
| Campo `has_mean` de estadísticas | Plazo vencido; sigue presente | Solo documentación |
| Acceso TCP de las apps al Supervisor (`SUPERVISOR_TOKEN`) en favor de un socket Unix | Sin fecha; preparado en la rama principal del Supervisor, no publicado en 2026.11.0 | Hermes usa solo TCP |
| API `/v2` del Supervisor (`addons` → `apps`) | Sin fecha; hoy detrás de una opción de desarrollo y sin retirar la V1 | Ninguno hoy |
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
del SIGKILL de Docker. Pendiente: probar la primera publicación con una
etiqueta y comprobar que las imágenes ya publicadas siguen disponibles.

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
que antes pasaban, y más tools ocupan más contexto en el cliente.

### Hecho en 1.1.1 — correcciones de la 1.1.0 (spec 006)

Las pruebas en vivo de la 1.1.0 con HA 2026.11.1 encontraron tres fallos:

- `ha_marketplace_list_updates` (y `ha_hacs_list_updates`) fallaba siempre:
  pedía el catálogo entero del Marketplace en un mensaje que pasa del tope WS
  y tumbaba la conexión. Ahora se pide por categorías.
- `response_max_bytes` no se aplicaba a las tools que no recortaban por su
  cuenta (`ha_get_states`, entre otras). Ahora lo aplica el servidor a todas.
- El log guardaba el `pattern` de `fs_search_in_config` y la plantilla de
  `ha_render_template`; ahora solo su longitud.

Lo que las pruebas en vivo de la 1.1.0 dieron por bueno: arranque y redacción
de red, `sv_get_supervisor_info`, `sv_get_host_info`, dashboards y recursos de
Lovelace, `ha_list_services(domain=…)`, avisos de `ha_render_template`, los
alias `ha_hacs_info` y `ha_hacs_list_repositories`, la protección del
dashboard principal y los tokens DCR emitidos antes de actualizar.

### Pruebas manuales pendientes en una instalación real

La suite no puede cubrir esto; hay que hacerlo justo después de publicar la
1.1.1, y anotar el resultado aquí:

- [ ] **Tools nuevas de la 1.1.0 desde un cliente sin la lista cacheada**: el
  cliente de las pruebas en vivo guardaba la lista de antes de actualizar y no
  veía ninguna de las tools nuevas. Con una sesión nueva o tras quitar y volver
  a añadir el conector, probar en lectura las `ha_marketplace_*` (sobre todo
  `ha_marketplace_list_updates`), `ha_list_floors`, `ha_list_labels`,
  `ha_list_categories`, `ha_list_repairs`, `ha_list_traces`, `ha_get_trace`,
  `ha_search_related`, `sv_get_resolution`, `ha_list_backups` y
  `ha_get_backup_config` (que solo exponga `password_set`).
- [ ] **`ha_get_states(domain="sensor")` en una casa grande**: que llegue
  recortada con `truncated: true` y por debajo de `response_max_bytes`.

- [ ] **CIMD con Claude Code y con claude.ai**: autorizar con los dos clientes,
  comprobar la pantalla de autorización (host, nombre y destino del código) y
  que los clientes DCR de antes siguen funcionando
  (`specs/003-oauth-y-protocolo/quickstart.md`).
- [ ] **Primer byte tras el proxy**: Claude Code con una espera de 90 s detrás
  del proxy. Si corta a los 60 s, completar DOCS.md con lo que haga falta en
  ese proxy.
- [ ] **Actualización con la clave `homeassistant`** del manifiesto: que el
  Supervisor actualice sin problemas en una HA soportada y rechace la
  actualización en una HA anterior a 2024.10.
- [ ] **Funnel en el 8443**: publicar Hermes en el 8443 con
  `public_hostname: homeassistant.tailXXXX.ts.net:8443`, con
  `share_homeassistant: funnel` en el 443, y pasar una instalación existente
  del 443 al 8443 siguiendo los README.
- [ ] **Publicación de la imagen con el CI nuevo** (spec 002): la primera
  etiqueta con `build-image`, las dos arquitecturas, la firma, y que las
  imágenes ya publicadas siguen disponibles.
- [ ] **Dashboards grandes**: leer por vistas un dashboard de más de 128 KiB
  (`too_large`, `view_index`, `top_level`) y guardarlo entero sin perder
  claves de nivel superior.

### 1.2.x y posteriores

- **Pruebas manuales en una instalación real**: las de la sección anterior
  (CIMD con Claude Code y claude.ai, primer byte tras el proxy, actualización
  con la clave `homeassistant`, Funnel en el 8443, publicación de la imagen
  con el CI nuevo y lectura y guardado de dashboards grandes), si no se
  hicieron con la 1.1.0.
- **Redactar en el log los dominios propios de HA** (`external_url` e
  `internal_url`): hoy solo se tapa `public_hostname`. Exige leer la
  configuración de HA al arrancar, antes de que salgan las primeras líneas.
- **IPs con forma `ip-a-b-c-d`** (nombres de host de algunos proveedores) en
  el log: no se redactan. Valor bajo.
- **Distinguir errores fatales de avisos en los jobs del Supervisor**
  (`sv_get_job_status`): hoy cualquier entrada en `errors` da
  `success: false`, y el Supervisor no da una señal fiable para separarlos.
- **`oauth_cimd_allowed_hosts`**: decidir un valor por defecto restrictivo
  cuando estén documentados los hosts CIMD de todos los clientes de Claude.

- **`redact_secrets` (security.py) es cuadrático con cadenas largas sin
  espacios**: 30 KB sin espacios tardan del orden de medio segundo (0,4–0,7 s
  según la máquina). Afecta a textos grandes que se redactan enteros, como
  logs con líneas muy largas o blobs codificados. Hay que acotar las
  expresiones regulares o trocear la entrada, con un test de tiempo.
- Cifrado de los safety backups (hoy se crean sin contraseña).
- Aplicar sugerencias del Supervisor, solo con confirmación y vista previa
  completa (hoy solo se leen y se descartan).
- Escritura en el Marketplace, solo si se decide, desactivada por defecto y con
  confirmación, backup previo y vista previa completa.
- Flujos de reparación de Repairs (hoy solo se listan e ignoran) y textos de
  los avisos traducidos.
- Subentries y reconfigure; helpers por config entry; triggers y condiciones
  por propósito; resolución de targets.
- Auditoría de llamadas a acciones (`logbook/get_action_calls`), estado del
  sistema, notificaciones persistentes, estadísticas agregadas, energía.
- `outputSchema` y alternativas nativas de MCP a la confirmación en dos pasos.
- Socket Unix del Supervisor y API `/v2` cuando se publiquen.
- Revisión de privilegios (`hassio_role`), terminología «apps» y traducciones de
  las opciones.

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
  limitados a lo expuesto; CIMD; prompts, búsqueda y acceso a calendario, listas
  y multimedia.

Hermes se centra en la **administración y la configuración con salvaguardas**,
donde la integración oficial no llega.
