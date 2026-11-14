# Investigación: cobertura total de Home Assistant 2026.11 (spec 008, paraguas)

Objetivo del programa: que Hermes cubra todo lo que Home Assistant Core
**2026.11.1** y el Supervisor **2026.11.0** ofrecen a un administrador y Hermes
todavía no tiene, y validar la hoja de ruta. Este documento solo investiga y
consolida; la arquitectura la decide el mantenedor (R-5) y la spec, el plan y
las tareas se escriben después.

Cada apartado: hallazgo, decisión propuesta o recomendación, y alternativas.
Las referencias a código son de la rama `feat/cobertura-total` sobre la 1.1.2.

## R-0 — Fuentes, método y correcciones a los informes de partida

- **Fuentes**: código de Core 2026.11.1 (`homeassistant/*.py`, `helpers/`,
  `components/**`, `services.yaml`) y del Supervisor 2026.11.0
  (`supervisor/api/*.py`, `api/middleware/security.py`, `docker/*.py`), leídos
  sin ejecutar nada; código de Hermes (`hermes/src/hermes/`); `docs/HOJA-DE-RUTA.md`,
  `docs/PRINCIPIOS.md` y la constitución; el SDK `mcp` 2.3.0 instalado en el
  entorno de desarrollo (para la especificación MCP 2026-07-28).
- **Extracción de comandos WebSocket de Core**: por AST (claves `type` de
  `websocket_command`, esquemas `BASE_COMMAND_MESSAGE_SCHEMA.extend` y
  `async_register_command`), con las constantes resueltas y las colecciones de
  almacenamiento (`StorageCollectionWebsocket`) expandidas por prefijo. Total:
  **623 comandos**. El grep literal da 356 cadenas, 9 de ellas falsos positivos
  (tipos de fuentes de energía y de selectores).
- **Rutas del Supervisor**: registro de `supervisor/api/__init__.py` (API V1,
  la activa): **254 rutas**, en 217 filas porque los alias y las variantes de
  log se agrupan.
- **Inventarios duraderos**: `inventario/core-ws.tsv` (comando, integración,
  fichero relativo a la raíz de Core, cobertura, clase, nota y CAP) e
  `inventario/supervisor-rutas.tsv` (método, ruta, área, cobertura, clase, rol,
  nota y CAP). Toda fila de clase A o C tiene su CAP; un test de la sub-spec de
  política (R-6, 011) puede comprobarlo.

| Clase | Core (comandos WS) | Supervisor (rutas) |
|---|---|---|
| Cubierto (directo, REST equivalente o acción genérica) | 130 (115 + 15 vía `ha_call_service[_response]`) | 37 |
| **A** — hueco real de administración | **147** (26 grupos) | **130** (13 grupos; 115 filas) |
| B — interno del frontend, suscripción, streaming o alias | 103 | 67 (47 filas) |
| C — gestión específica de una integración | 192 (22 integraciones) | — |
| D — peligroso o no automatizable por diseño | 51 | 20 (18 filas) |

**Correcciones a los informes de partida** (comprobadas en el código):

1. **`hassio.core_update`, `hassio.os_update`, `hassio.supervisor_update` y
   `hassio.addon_update|install|uninstall` ya no existen en Core 2026.11.1**
   (`components/hassio/services.yaml` solo tiene `addon_*`/`app_*` de
   arranque, parada, reinicio y stdin, `host_*`, `backup_*`, `restore_*` y
   `mount_reload`). Actualizar Core, OS y Supervisor desde Hermes hoy solo es
   posible con `update.install` sobre las entidades `update` del Supervisor,
   que está en la denylist: **pide token, no está vetado**. El informe del
   Supervisor dice «no hay ninguna vía» y el de Core cita `hassio.core_update`;
   las dos frases se corrigen aquí. Las entradas `hassio.*_update` de la
   denylist son inofensivas pero muertas (no se proponen quitar: fail-closed).
2. **La denylist no prohíbe: exige confirmación** (`service_policy.py`,
   `CALL_SERVICE_DENYLIST`). La excepción es `ha_call_service_response`, que no
   acepta `confirmation_token` y rechaza todo lo de la denylist con
   `service_in_denylist` (`tools/ha.py`): una acción peligrosa con respuesta
   (`conversation.process`) no puede devolver su respuesta (CAP-020).
3. **Socket Unix**: en 2026.11.0 ya existe, pero solo para Core
   (`docker/homeassistant.py` inyecta `SUPERVISOR_SOCKET`; `docker/addon.py`
   no). El aviso `deprecated_tcp_api_request` solo se emite cuando el token de
   Core llega por TCP (`api/middleware/security.py`). Hermes no está afectado.
4. **`hassio_role`**: en 2026.11.0, `/addons/self/options/config` está en
   `api_bypass` (pasa con cualquier rol). El comentario de `hermes/config.yaml`
   («'manager' y 'default' devuelven 403») es de una versión anterior del
   Supervisor (CAP-022).

## R-1 — Validación de la hoja de ruta

### Lo que está bien

- El estado de compatibilidad, la versión mínima 2024.10 y la tabla de
  problemas de la 1.0.11 (salvo lo que se dice abajo de los números 21 y 23).
- Las deprecaciones con fecha: `config_entries`/`primary_config_entry` del
  dispositivo, `config/device_registry/remove_config_entry` (HA 2027.9),
  `lovelace/resources`, DCR en MCP y la API `/v2` del Supervisor (sigue detrás
  de la *feature flag* `supervisor_v2_api`, desactivada).
- Todos los pendientes que listó el mantenedor están, salvo los marcados en
  «Lo que falta»: `redact_secrets` cuadrático, `external_url`/`internal_url`,
  los `entity_id` de `auto_classify_restricted` (`tools/ha.py`, evento
  `auto_classify_on_save`), `redacted` de `sv_get_addon_logs`,
  `_response_limit` en `ha_get_history` (no existe en `tools/history.py`),
  escritura en el Marketplace detrás de una opción, socket Unix y `/v2`,
  guardar un dashboard por vistas, `ha_marketplace_list_removed` y
  `removal_type`, los eventos `*_ok` que faltan y el coste del barrido de
  tokens. Los seis primeros se han comprobado en el código y siguen siendo
  reales.

### Lo que está desfasado

- **«Verificado contra»**: «Las tools de escritura no se ejecutaron». Desde la
  1.1.2 sí se ejecutaron las de dashboards (`ha_save_lovelace_dashboard` con y
  sin documento). Las otras ~120 tools que modifican siguen sin ejecutarse
  contra una HA real.
- **«Hermes frente a `mcp_server`»**: lista CIMD entre lo que «solo tiene la
  oficial». Hermes tiene CIMD desde la 1.1.0 (spec 003).
- **1.2.x, «estadísticas agregadas»**: ya existen. `ha_statistics_during_period`
  agrega por `5minute|hour|day|week|month|year` y `recorder.get_statistics` va
  por `ha_call_service_response`. Lo que falta es el **mantenimiento** de
  estadísticas (CAP-049, CAP-050).
- **1.2.x, «helpers por config entry»**: ya se pueden crear y editar con lo que
  hay: `ha_list_config_entries(type_filter="helper")`,
  `ha_start_config_entry_flow(handler="template")` (o `group`,
  `utility_meter`…) y los flujos de opciones. Falta solo explicarlo en la guía
  (CAP-037).
- **Deprecaciones, socket Unix**: «preparado en la rama principal del
  Supervisor, no publicado en 2026.11.0». Publicado para Core, no para las apps
  (R-0, punto 3).
- **`hermes/config.yaml`, comentario de `hassio_role`** (no es la hoja de ruta,
  pero la hoja de ruta lo remite a «Revisión de privilegios»): el 403 con
  `manager` ya no se reproduce leyendo el código de 2026.11.0.

### Lo que falta

- `ha_call_service_response` y la denylist (R-0, punto 2; CAP-020).
- `sv_update_addon` sobre el propio Hermes: el Supervisor responde 403 «can't
  update itself» (`api/store.py`); Hermes solo añade un aviso
  (`_self_warning`, `tools/addons.py`) y deja que falle (CAP-021).
- Actualizar Core, OS y Supervisor: posible con `update.install` confirmando,
  pero la vista previa no dice versión actual → destino, notas de la versión,
  si habrá backup ni el estado de `/resolution/info` (CAP-080, CAP-064).
- Las ~120 tools que modifican sin ejecutar contra una HA real, y el banco de
  pruebas que lo permitiría (CAP-005, CAP-006, CAP-034).
- `hassio_role: manager`, concretado: qué añade `admin` y qué hay que probar
  (CAP-022).
- Los problemas 21 (formas de lista) y 23 (traceback al apagar) de la 1.0.11
  siguen «Pendiente» en la tabla y no aparecen en el plan (CAP-023, CAP-024).
- Las retiradas con versión: `ha_remove_device_from_config_entry` (antes de
  HA 2027.9; hoy no tiene versión de Hermes asignada) y los alias `ha_hacs_*`
  (1.3.0; solo lo dice «Estado de compatibilidad», no hay entrada de plan)
  (CAP-030, CAP-031).
- La cobertura medida (R-0) y el programa 008 como marco de «1.2.x y
  posteriores».
- El coste de contexto medido de la lista de tools: `tools/list` de las 216
  tools ocupa **~215 KB** de JSON (~1 KB por tool; la mayor,
  `ha_statistics_during_period`, ~3,9 KB). Medido registrando las tools con un
  cliente simulado y serializando `list_tools()`.

### Correcciones propuestas (texto actual → texto propuesto)

| # | Sección | Texto actual | Propuesta |
|---|---|---|---|
| 1 | Cabecera, «Verificado contra» | «Las tools de escritura no se ejecutaron: sus fallos están confirmados leyendo el código de Hermes y el de Home Assistant.» | «De las 124 tools que modifican, solo las de dashboards se han ejecutado contra una HA real (1.1.2); el resto se verificó leyendo el código de Hermes y el de Home Assistant. El banco de pruebas de la spec 008 cierra ese hueco.» |
| 2 | Estado de compatibilidad | — | Viñeta nueva: «**Cobertura medida**: Core 2026.11.1 expone 623 comandos WebSocket; Hermes cubre 130 y quedan 147 huecos de administración, 192 de integraciones concretas, 103 internos del frontend y 51 excluidos por diseño. El Supervisor expone 254 rutas; Hermes cubre 37 y quedan 130 huecos. Detalle en `specs/008-cobertura-total/`.» |
| 3 | Problemas de 1.0.11, filas 21 y 23 | «Pendiente» | «Pendiente (1.2.x, spec 008)» y entradas en el plan. |
| 4 | Deprecaciones, fila `remove_config_entry` | «…se retirará antes» | «…se retira en la versión de Hermes que fije la spec 008 (como tarde, la última publicada antes de HA 2027.9)». |
| 5 | Deprecaciones | — | Fila nueva: «Alias `ha_hacs_*` | Hermes **1.3.0** | Se retiran; desde la 1.1.0 devuelven `_deprecated`». |
| 6 | Deprecaciones, fila del socket Unix | «Sin fecha; preparado en la rama principal del Supervisor, no publicado en 2026.11.0» | «Sin fecha. En 2026.11.0 el socket existe solo para Core (`SUPERVISOR_SOCKET` no se inyecta en las apps) y el aviso `deprecated_tcp_api_request` solo salta con el token de Core.» |
| 7 | Deprecaciones | — | Fila nueva: «Acciones `hassio.*_update` | Ya no existen en Core 2026.11 | Ninguno: las de la denylist están muertas; actualizar va por `update.install`». |
| 8 | 1.2.x, «Auditoría de llamadas…, estadísticas agregadas, energía» | incluye «estadísticas agregadas» | Quitar «estadísticas agregadas» (ya están) y añadir «mantenimiento de estadísticas (validar, corregir unidades, ajustar sumas)». |
| 9 | 1.2.x, «Subentries y reconfigure; helpers por config entry; …» | «helpers por config entry» | «helpers por config entry: ya se pueden crear con los flujos; falta explicarlo en la guía». |
| 10 | 1.2.x, «Revisión de privilegios (`hassio_role`)…» | una línea | «**Probar `hassio_role: manager`**. En el Supervisor 2026.11.0, `/addons/self/options/config` está en `api_bypass` y el patrón de `manager` cubre todas las rutas que usa Hermes y todos los huecos propuestos (salvo `/reload_updates`; `/refresh_updates` sí entra). `admin` solo añade `/addons/{app}/security`, `/auth/reset`, `/auth/list`, `/os/datadisk/wipe` e `/ingress/panels`, que Hermes no usa. El comentario de `config.yaml` que habla de un 403 es de una versión anterior. Es un cambio de permisos: el Supervisor lo enseña al actualizar.» |
| 11 | 1.2.x | — | Viñeta nueva: «`ha_call_service_response` rechaza todo lo de la denylist y no acepta `confirmation_token`: una acción peligrosa con respuesta (`conversation.process`) no puede devolverla ni confirmando.» |
| 12 | 1.2.x | — | Viñeta nueva: «`sv_update_addon` sobre Hermes: el Supervisor responde 403; rechazarlo antes con un mensaje que diga que se actualiza desde la UI.» |
| 13 | 1.2.x | — | Viñeta nueva: «Actualizar Core, OS y Supervisor con vista previa útil (versión actual → destino, notas, backup, salud del sistema). Hoy solo con `update.install` confirmando.» |
| 14 | 1.2.x | — | Viñeta nueva: «Banco de pruebas: HA Core en contenedor en el CI para ejecutar de verdad las escrituras de Core, y una VM con HAOS para las del Supervisor.» |
| 15 | Pruebas manuales pendientes | — | Casillas nuevas: «`hassio_role: manager` en una instalación real (arranque, `bashio::config`, todas las `sv_*`)»; «las 13 tools de escritura de la 1.1.x»; «`sv_update_addon` sobre Hermes, tras CAP-021». |
| 16 | Hermes frente a `mcp_server`, «Lo que solo tiene la oficial» | «…intents de Assist limitados a lo expuesto; CIMD; prompts…» | Quitar «CIMD». |
| 17 | Hecho en 1.1.0, «Son 216 tools. Riesgos…» | «…y más tools ocupan más contexto en el cliente.» | «…ocupan más contexto en el cliente: la lista de las 216 son unos 215 KB de JSON.» |
| 18 | Plan por versiones | «1.2.x y posteriores» como lista única | Subsecciones por versión según R-5 c) y el desglose de R-6, con enlace a `specs/008-cobertura-total/`. Los pendientes pequeños (CAP-010 a CAP-018, CAP-021) en una **1.1.3**. |

## R-2 — Catálogo consolidado de capacidades

Convenciones: **2P** = confirmación en dos pasos con `confirmation_token` y
vista previa. Esfuerzo S (≤1 día, patrón ya existente), M (2–4 días o patrón
nuevo), L (más de una semana o muchas tools). Prioridad: alta, media-alta,
media, baja. Origen: `Core-An` / `SV-An` = grupo A del informe de Core o del
Supervisor; `HR` = pendiente de la hoja de ruta; `Hallazgo` = de las pruebas en
vivo o de esta investigación; `Arq.` = necesario para la arquitectura. Los IDs
son estables: no se renumeran; lo que se descarte queda marcado.

Los nombres de tools siguen el estilo de Hermes (`ha_` Core, `sv_`
Supervisor, `list|get|create_or_update|update|delete|set` según el caso). Si
la arquitectura elegida en R-5 manda una CAP a la tool genérica, sus «tools
propuestas» pasan a ser entradas de la tabla de clasificación.

### Comprobación de falsos huecos

- Los 147 comandos A de Core se buscaron como literal en `hermes/src/hermes/`:
  ninguno se usa (el único acierto, `"network"`, es un texto de `cimd.py`). Las
  f-strings `f"{domain}/list|create|update|delete"` de `ha.py` solo se usan con
  los 11 dominios de helpers (`input_*`, `counter`, `timer`, `schedule`,
  `zone`, `person`): `tag`, `image` y `assist_pipeline` no.
- Las rutas A del Supervisor no aparecen en ninguna llamada de `sv_request*` de
  Hermes (31 rutas propias usadas, todas de clase cubierta).
- Huecos parcialmente cubiertos, que se mantienen como A porque la vía actual
  no tiene vista previa útil o no devuelve el dato: crear notificaciones
  (`persistent_notification.create`), nivel de log (`logger.set_level`),
  ubicación (`homeassistant.set_location`), instalar actualizaciones
  (`update.install`), crear backups de la integración (`backup.create`). Todas
  piden token.
- Cubiertos que la hoja de ruta daba por pendientes: estadísticas agregadas y
  helpers por config entry (R-1).

### Bloque 1 — Plataforma y arquitectura (CAP-001 a CAP-009)

- **CAP-001 — Tabla de clasificación de comandos y rutas (fail-closed).**
  Módulo neutral (al estilo de `service_policy.py`) con una entrada por comando
  WS de Core y por plantilla de ruta del Supervisor: clase (`read`, `confirm`,
  `deny`, `dedicated`), familia, riesgo, si es suscripción de un solo mensaje y
  si hay que redactar la respuesta. Generada a partir de los inventarios y
  revisada a mano. Comando desconocido → rechazado. HA: todos. Cobertura: no
  existe. 2P: n/a. Riesgo: medio (una mala clasificación abre una puerta).
  Esfuerzo M. Prioridad **alta**. Origen: Arq.
- **CAP-002 — Tools genéricas de WebSocket de Core.** `ha_read_ws_command(type,
  payload)` (solo clase `read`, `readOnlyHint`) y `ha_call_ws_command(type,
  payload, confirmation_token)` (clase `confirm`, siempre 2P, `destructiveHint`).
  `dedicated` → rechazo con el nombre de la tool que hay que usar (así no se
  saltan protecciones como la del dashboard principal). Respuesta por el
  limitador central y `redact_secrets`; el log solo lleva `type` y nombres de
  claves. Riesgo: alto si CAP-001 falla. Esfuerzo M. Prioridad **alta**. Origen:
  Arq.
- **CAP-003 — Tools genéricas de la API del Supervisor.** `sv_read_api(path)` y
  `sv_call_api(method, path, body, confirmation_token)` con la misma tabla;
  validación de ruta con la guarda de `ha.py` contra `..` y `%2e`; `/core/api*`
  rechazado (es el proxy de Core: para eso están las `ha_*`). Esfuerzo M.
  Prioridad **media-alta**. Origen: Arq.
- **CAP-004 — Familias de tools configurables.** Opción `tool_families` (o
  `tools_disabled`) en `config.yaml`; `register_all_tools` omite los módulos
  desactivados. Familias por defecto activas: lo de hoy más diagnóstico; por
  defecto inactivas: escritura del Marketplace, estadísticas (escritura),
  usuarios, red del host, Assist, integraciones concretas. 2P: no. Riesgo bajo.
  Esfuerzo M (opción, registro, test de invariante, guía). Prioridad **alta**.
  Origen: Arq.
- **CAP-005 — Banco de pruebas de Core en el CI** (R-5 b). Prioridad **alta**,
  esfuerzo M. Origen: Hallazgo.
- **CAP-006 — Banco de pruebas del Supervisor (VM con HAOS)** (R-5 b).
  Prioridad **alta**, esfuerzo L. Origen: Hallazgo.
- **CAP-007 — Inventario versionado y test de deriva.** Llevar al repositorio
  (fuera de `hermes/src`, por ejemplo `tools/inventario/`) el extractor de
  comandos y un test que compare el inventario con la tabla de CAP-001; en cada
  versión nueva de HA, los comandos nuevos salen como «sin clasificar» y quedan
  rechazados hasta revisarlos. Esfuerzo S. Prioridad **media-alta**. Origen:
  Arq.
- **CAP-008 — Guía y descubrimiento.** Temas nuevos de `hermes_guide` por
  familia y una consulta de la tabla («qué comandos hay para X, con qué
  payload»), para que el cliente no adivine. Esfuerzo S. Prioridad **media**.
  Origen: Arq.

### Bloque 2 — Pendientes de la hoja de ruta y hallazgos (CAP-010 a CAP-038)

| ID | Capacidad | Dónde | Propuesta | 2P | Riesgo | Esf. | Prio. | Origen |
|---|---|---|---|---|---|---|---|---|
| CAP-010 | `redact_secrets` cuadrático (~0,5 s con 30 KB sin espacios) | `security.py` | Acotar las expresiones o trocear la entrada; test de tiempo. Requisito de CAP-041 y CAP-081 (logs grandes) | no | medio (DoS por un cliente autenticado) | S | alta | HR |
| CAP-011 | Redactar `external_url` e `internal_url` en el log | `logging_setup.py`, arranque | Leer `get_config` al arrancar antes de las primeras líneas | no | bajo | S-M | media | HR |
| CAP-012 | `auto_classify_restricted` escribe `entity_id` en el log | `tools/ha.py` (`auto_classify_on_save`) | Solo contadores o un hash | no | bajo | S | media | HR |
| CAP-013 | IPs con forma `ip-a-b-c-d` en el log | redacción de red | Patrón adicional | no | bajo | S | baja | HR |
| CAP-014 | `redacted` de `sv_get_addon_logs` dice `false` con la red ya redactada | `tools/addons.py` | Separar `secrets_redacted` y `network_redacted`, o documentarlo | no | bajo | S | baja | HR |
| CAP-015 | `ha_get_history` marca `truncated` sin `_response_limit` | `tools/history.py` | Añadir el bloque como las demás | no | bajo | S | baja | HR |
| CAP-016 | `ha_marketplace_list_removed` devuelve el catálogo entero (~500 entradas, ~97 KB); `removal_type` sin normalizar | `tools/marketplace.py` | `installed_only=True` por defecto, `limit`, resumen por tipo; `removal_type` en `_third_party_text` | no | bajo | S | media | HR / Hallazgo |
| CAP-017 | Marketplace y `sv_get_resolution` no escriben `*_ok` | `tools/marketplace.py`, `tools/resolution.py` | Evento `*_ok` con contadores | no | bajo | S | baja | HR / Hallazgo |
| CAP-018 | Barrido de tokens con el tope de 16 MiB lleno: decenas de ms por vista previa | `security.py` | Total en memoria o barrido como mucho cada segundo | no | bajo | S | baja | HR / Hallazgo |
| CAP-019 | Guardar un dashboard por vistas | `tools/lovelace.py` | `view_index` (o `view_path`) en `ha_save_lovelace_dashboard`; el servidor conserva las demás vistas y las claves de nivel superior; documento omitible como en la 1.1.2 | sí | medio | M | alta | HR / Hallazgo |
| CAP-020 | Acción peligrosa con respuesta | `tools/ha.py` | `confirmation_token` en `ha_call_service_response` para lo de la denylist, con la misma vista previa que `ha_call_service` | sí | medio (`conversation.process` ejecuta intents) | S-M | media-alta | Hallazgo |
| CAP-021 | `sv_update_addon` sobre Hermes da 403 | `tools/addons.py` | Rechazo previo `self_update_not_supported` con la indicación de usar la UI; sin token | no | bajo | S | media | Hallazgo |
| CAP-022 | `hassio_role: admin` sobra | `config.yaml` | Probar `manager` en la VM (CAP-006) y en una instalación real; si pasa, bajar el rol y corregir el comentario | n/a | medio (cambio de permisos visible al actualizar) | S | alta | HR / Hallazgo |
| CAP-023 | Formas de lista distintas (problema 21 de la 1.0.11) | varias | Sobre común `{count, items, truncated}` en las tools nuevas; las viejas, con alias o en una versión que lo anuncie | no | medio (rompe clientes que parsean) | M | media | HR |
| CAP-024 | Traceback inofensivo al apagar (problema 23) | `__main__.py` | Capturar la cancelación | no | bajo | S | baja | HR |
| CAP-025 | Errores fatales frente a avisos en `sv_get_job_status` | `supervisor_jobs.py` | Esperar señal fiable del Supervisor; mientras, documentar | no | bajo | S | baja | HR |
| CAP-026 | `oauth_cimd_allowed_hosts` por defecto restrictivo | `config.yaml`, `cimd.py` | Cuando estén documentados los hosts de los clientes | no | medio | S | baja | HR |
| CAP-027 | Cifrado de los safety backups | `safety_retention.py`, backups | Contraseña generada y guardada en `/data`, nunca devuelta | no | medio (perder la clave = backup inservible) | M | media | HR |
| CAP-028 | `outputSchema` y alternativas nativas a la confirmación | `mcp_server.py` | Investigar `InputRequiredResult`/`inputRequests` de MCP 2026-07-28 (R-5 a) como segunda vía; los dos pasos actuales se mantienen | n/a | medio | M | baja | HR |
| CAP-029 | Terminología «apps» y traducciones de las opciones | descripciones, `translations/` | Alinear con el Supervisor (`addons` → `apps`) sin renombrar tools | no | bajo | S-M | baja | HR |
| CAP-030 | Retirar `ha_remove_device_from_config_entry` | `tools/registry_device.py` | Retirarla en una versión con fecha anterior a HA 2027.9 | n/a | bajo | S | media | HR (deprecaciones) |
| CAP-031 | Retirar los alias `ha_hacs_*` | `tools/hacs.py` | En la 1.3.0, como está anunciado | n/a | bajo | S | media | HR |
| CAP-032 | Socket Unix del Supervisor para apps | `network.py`, `ha.py` | Cuando el Supervisor lo inyecte en las apps; detectar `SUPERVISOR_SOCKET` y caer a TCP | n/a | medio | M | baja (bloqueado) | HR |
| CAP-033 | API `/v2` del Supervisor | todo `sv_*` | Cuando se active: `apps`, `store/apps`, `network/interfaces/{name}`, formatos `*_v1` de `info`/`stats`/`backups`/`resolution`; `sv_get_addon` de apps no instaladas tendrá que ir a `/store/apps/{app}` | n/a | alto si llega sin aviso | M | baja (bloqueado) | HR |
| CAP-034 | Pruebas en vivo de las 124 tools que modifican | banco de pruebas | Matriz tool → entorno (CI de Core, VM, instalación real) → resultado; las del Supervisor y las destructivas solo en la VM | n/a | — | L | alta | Hallazgo |
| CAP-035 | Pruebas manuales abiertas | `HOJA-DE-RUTA.md` | `fs_write_file` sin documento y limpieza del directorio de confirmaciones (en la VM hay acceso a `/data`), CIMD con Claude Code, primer byte tras el proxy, clave `homeassistant` en HA antigua, Funnel en el 8443, `sv_get_resolution` con issues reales, trazas de script | n/a | — | S | media | HR / Hallazgo |
| CAP-036 | Textos traducidos de los avisos de Repairs | `tools/repairs.py` | Usar internamente `frontend/get_translations` (categoría `issues`, hoy clase B) para devolver título y descripción | no | bajo | S | media | HR |
| CAP-037 | Helpers por config entry | `tools/guide.py` | Solo guía: tipo `helper`, `handler`, opciones | no | bajo | S | baja | HR (desfasado) |
| CAP-038 | Esperar a un trigger | `tools/wait_for_event.py` | `subscribe_trigger` de un solo disparo, con el mismo tope que `ha_wait_for_event` (reclasificación de B) | no | bajo | S | baja | Hallazgo |

### Bloque 3 — Huecos A de Core (CAP-040 a CAP-075)

Los comandos de cada CAP están en `inventario/core-ws.tsv` (columna `cap`).

**Prioridad alta**

- **CAP-040 — Validación de automatizaciones y scripts** (Core-A1).
  `validate_config`, `test_condition`. Hoy: no (solo `sv_check_core_config`,
  configuración entera). Tools: `ha_validate_config`, `ha_test_condition`;
  además, `ha_create_or_update_automation`/`_script` validan antes de escribir.
  2P: no. Riesgo bajo. S.
- **CAP-041 — Log del sistema y niveles de log** (Core-A2). `system_log/list`,
  `logger/log_info`, `logger/log_level`; REST `/api/error_log`; acciones
  `logger.set_level`, `system_log.clear`. Hoy: solo `logger.set_level` con
  token. Tools: `ha_list_system_log` (agrupado, con contador y primera/última
  vez), `ha_get_error_log(lines)`, `ha_get_log_levels`, `ha_set_log_level`
  (vista previa con el nivel anterior), `ha_clear_system_log`. 2P: fijar nivel
  y limpiar. Riesgo bajo (redacción y tamaño; depende de CAP-010). S.
- **CAP-042 — Diagnósticos de integración y dispositivo** (Core-A3).
  `diagnostics/list|get`; REST `/api/diagnostics/config_entry/{id}[/device/{id}]`.
  Tools: `ha_list_diagnostics_handlers`, `ha_get_config_entry_diagnostics`,
  `ha_get_device_diagnostics`. 2P: no. Riesgo medio (HA redacta, pero se pasa
  `redact_secrets` y el tope de respuesta). M.
- **CAP-043 — Salud y estado del sistema** (Core-A4, HR). `system_health/info`
  (suscripción: primer mensaje más los `pending` con tope de tiempo),
  `subscribe_system_state`, `integration/setup_info`, `manifest/list|get`. Tools:
  `ha_get_system_health`, `ha_get_system_state`,
  `ha_list_integration_setup_times`, `ha_get_integration_manifest`. 2P: no.
  Riesgo bajo. M (patrón `ws_one_shot_subscription` ya existe).
- **CAP-044 — Integraciones descubiertas y preferencias de la entry**
  (Core-A5). `config_entries/flow/progress`, `config_entries/ignore_flow`,
  `config_entries/update`; REST `/api/config/config_entries/flow_handlers`.
  Tools: `ha_list_discovered_integrations`, `ha_ignore_discovery`,
  `ha_update_config_entry` (título, `pref_disable_polling`,
  `pref_disable_new_entities`), `ha_list_flow_handlers`. 2P: al desactivar
  polling o entidades nuevas. Riesgo bajo. S.
- **CAP-045 — Subentries y reconfigure** (Core-A6, HR).
  `config_entries/subentries/list|update|delete`; REST
  `/api/config/config_entries/subentries/flow[/{id}]`; `POST
  /api/config/config_entries/flow` con `entry_id` (fuente `reconfigure`).
  Hoy: `num_subentries` y `supports_reconfigure` se leen. Tools:
  `ha_list_config_subentries`, `ha_start_subentry_flow`,
  `ha_continue_subentry_flow`, `ha_update_subentry`, `ha_delete_subentry`,
  `ha_start_reconfigure_flow`. 2P: borrar subentry. Riesgo medio. M.
- **CAP-046 — Blueprints** (Core-A7). `blueprint/list|import|save|delete|substitute`.
  Hoy: solo `fs_write_file` en `/config/blueprints`, sin validación. Tools:
  `ha_list_blueprints`, `ha_import_blueprint`, `ha_save_blueprint`,
  `ha_delete_blueprint`, `ha_preview_blueprint_substitution`. 2P: importar
  (contenido de terceros, `_third_party_text`), sobrescribir y borrar. Riesgo
  medio. M.
- **CAP-047 — Notificaciones persistentes** (Core-A8, HR).
  `persistent_notification/get`; acciones `create`, `dismiss`, `dismiss_all`.
  Hoy: crear vía acción; descartar con token; listar no. Tools:
  `ha_list_persistent_notifications`, `ha_dismiss_persistent_notification`
  (vista previa con el texto). 2P: descartar. Riesgo bajo. S.

**Prioridad media-alta**

- **CAP-048 — Flujos de reparación de Repairs** (Core-A9, HR).
  `repairs/get_issue_data`; REST `/api/repairs/issues/fix[/{flow_id}]`. Tools:
  `ha_get_repair`, `ha_start_repair_fix`, `ha_continue_repair_fix`,
  `ha_abort_repair_fix`. 2P: el paso que aplica el arreglo. Riesgo medio. M
  (reutiliza el motor de flujos).
- **CAP-049 — Estadísticas: lectura y validación** (Core-A10, parte).
  `recorder/validate_statistics`, `recorder/get_statistics_metadata`,
  `recorder/info`, `recorder/entity_options/get`. Tools:
  `ha_validate_statistics`, `ha_get_statistics_metadata`,
  `ha_get_recorder_info`. 2P: no. Riesgo bajo. S.
- **CAP-050 — Estadísticas: mantenimiento** (Core-A10, parte).
  `recorder/clear_statistics`, `change_statistics_unit`,
  `update_statistics_metadata`, `adjust_sum_statistics`, `import_statistics`,
  `update_statistics_issues`. Tools: `ha_clear_statistics`,
  `ha_change_statistics_unit`, `ha_update_statistics_metadata`,
  `ha_adjust_statistics_sum`, `ha_import_statistics`. 2P: todas (reescriben
  histórico; solo se deshace con un backup). Riesgo **alto**. M.
- **CAP-051 — Triggers, condiciones y acciones de dispositivo** (Core-A11).
  `device_automation/{trigger,condition,action}/{list,capabilities}`. Tools:
  `ha_list_device_triggers`, `ha_list_device_conditions`,
  `ha_list_device_actions` (con `capabilities`). 2P: no. Riesgo bajo. M.
- **CAP-052 — Targets y propósitos** (Core-A11, HR). `get_triggers_for_target`,
  `get_conditions_for_target`, `get_services_for_target`,
  `extract_from_target`, `explain_target`. Tools: `ha_resolve_target`,
  `ha_explain_target`, `ha_list_triggers_for_target`,
  `ha_list_conditions_for_target`, `ha_list_actions_for_target`. 2P: no. Riesgo
  bajo. S-M.
- **CAP-060 — Conversación** (Core-A19, parte). `conversation/process`,
  `conversation/agent/list`, `conversation/agent/homeassistant/debug`,
  `.../language_scores`, `conversation/sentences/list`. Tools:
  `ha_debug_conversation` (analiza la frase sin ejecutarla), `ha_process_conversation`
  (ejecuta: 2P), `ha_list_conversation_agents`, `ha_list_conversation_sentences`.
  Riesgo medio (`process` acciona intents: cerraduras). S. Relacionada con
  CAP-020.
- **CAP-064 — Notas de versión e instalación de entidades `update`**
  (Core-A20 y hallazgo). `update/release_notes`; acción `update.install`. Tools:
  `ha_get_update_release_notes`, `ha_install_update` (vista previa con versión
  instalada → destino, notas recortadas, `backup` si la entidad lo admite). 2P:
  instalar. Riesgo medio-alto. S. Para Core/OS/Supervisor se coordina con
  CAP-080 (una sola tool o una que delegue).

**Prioridad media**

- **CAP-053 — Configuración del núcleo** (Core-A12). `config/core/update`,
  `config/core/detect` (lectura con `get_config`). Tools: `ha_get_core_config`,
  `ha_update_core_config`, `ha_detect_core_config`. 2P: actualizar (unidades y
  zona horaria afectan a estadísticas y automatizaciones). Riesgo medio. S.
- **CAP-054 — Energía** (Core-A13, HR). `energy/get_prefs|save_prefs|validate|info|fossil_energy_consumption|solar_forecast`.
  Tools: `ha_get_energy_prefs`, `ha_update_energy_prefs` (documento completo con
  diff, como Lovelace), `ha_validate_energy`, `ha_get_energy_info`,
  `ha_get_fossil_energy_consumption`, `ha_get_solar_forecast`. 2P: guardar.
  Riesgo medio. M.
- **CAP-055 — Exposición de entidades a asistentes** (Core-A14).
  `homeassistant/expose_entity[/list]`, `homeassistant/expose_new_entities/get|set`.
  Tools: `ha_list_exposed_entities`, `ha_set_entity_exposure` (en lote, por
  asistente), `ha_get_expose_new_entities`, `ha_set_expose_new_entities`. 2P:
  lotes y «exponer nuevas». Riesgo medio (decide qué controla la voz y la
  integración `mcp_server`). S.
- **CAP-056 — Usuarios** (Core-A15). `config/auth/list|create|update|delete`,
  `auth/refresh_tokens` (metadatos). Tools: `ha_list_users`, `ha_create_user`
  (sin credenciales: la contraseña la pone una persona en la UI),
  `ha_update_user` (nombre, activo, admin, `local_only`), `ha_delete_user`,
  `ha_list_user_sessions`. 2P: todo lo que escribe; prohibido tocar al
  propietario y al usuario del propio Hermes. Riesgo **alto** (escalada o
  bloqueo). M. Familia desactivada por defecto.
- **CAP-057 — Backups de la integración `backup`** (Core-A16).
  `backup/agents/info`, `backup/config/update`, `hassio/update/config/info|update`;
  `backup.create` por acción. Tools: `ha_list_backup_agents`,
  `ha_update_backup_config` (programación, retención, agentes; la contraseña de
  cifrado nunca se devuelve), `ha_get_update_backup_settings`,
  `ha_set_update_backup_settings`, `ha_create_backup` (elegir agentes). 2P:
  sí. Riesgo medio (una retención mal puesta borra backups). M.
- **CAP-058 — Auditoría de llamadas a acciones** (Core-A17, HR).
  `logbook/get_action_calls`. Tool: `ha_get_action_calls`. 2P: no. Riesgo bajo.
  S.
- **CAP-059 — Cámaras e imágenes** (Core-A18). REST `/api/camera_proxy/{id}`,
  `/api/image_proxy/{id}`; `camera/get_prefs|update_prefs`. Tools:
  `ha_get_camera_snapshot` (`ImageContent` reducida), `ha_get_image_entity`,
  `ha_get_camera_prefs`, `ha_update_camera_prefs`. 2P: no en lectura, sí en
  prefs. Riesgo medio (privacidad): familia desactivada por defecto. M.
- **CAP-068 — Red y HTTP: lectura** (Core-A24, parte). `network`,
  `network/url`, `http/config`. Tools: `ha_get_network_config`, `ha_get_urls`,
  `ha_get_http_config`. 2P: no. Riesgo bajo (redactar URLs en el log, CAP-011).
  S.

**Prioridad baja**

- **CAP-061 — Pipelines de Assist** (Core-A19). `assist_pipeline/pipeline/list|get|create|update|delete|set_preferred`,
  `assist_pipeline/language/list`, `assist_pipeline/device/list`,
  `assist_pipeline/pipeline_debug/list|get`. Tools: `ha_list_assist_pipelines`,
  `ha_get_assist_pipeline`, `ha_create_or_update_assist_pipeline`,
  `ha_delete_assist_pipeline`, `ha_set_preferred_assist_pipeline`,
  `ha_list_assist_pipeline_runs`, `ha_get_assist_pipeline_run`. 2P: borrar.
  Riesgo bajo. M.
- **CAP-062 — Motores de voz, LLM y AI Task** (Core-A19).
  `tts/engine/list|get|voices`, `stt/engine/list`, `wake_word/info`,
  `llm/api/list`, `ai_task/preferences/get|set`. Tools: `ha_list_tts_engines`,
  `ha_list_tts_voices`, `ha_list_stt_engines`, `ha_list_wake_word_engines`,
  `ha_list_llm_apis`, `ha_get_ai_task_preferences`,
  `ha_update_ai_task_preferences`. 2P: no (preferencias reversibles). S.
- **CAP-063 — Satélites de Assist** (Core-A19). `assist_satellite/get_configuration|set_wake_words`.
  Tools: `ha_get_satellite_configuration`, `ha_set_satellite_wake_words`. S.
- **CAP-065 — Calendario y tareas** (Core-A21). `calendar/event/update|delete`,
  `todo/item/move`. Tools: `ha_update_calendar_event`,
  `ha_delete_calendar_event`, `ha_move_todo_item`. 2P: borrar y editar
  recurrentes. S.
- **CAP-066 — Tags** (Core-A22). `tag/list|create|update|delete`. Tools:
  `ha_list_tags`, `ha_create_or_update_tag`, `ha_delete_tag`. 2P: borrar. S
  (patrón `ws_collection_*`).
- **CAP-067 — Navegación de medios** (Core-A23).
  `media_source/browse_media|search_media|resolve_media|local_source/remove`.
  Tools: `ha_browse_media_source`, `ha_search_media_source`, `ha_resolve_media`,
  `ha_delete_local_media`. 2P: borrar. M.
- **CAP-069 — Red y HTTP: escritura** (Core-A24, parte). `network/configure`,
  `http/config/configure`, `http/config/promote`. Tools:
  `ha_update_network_config`, `ha_update_http_config`. 2P: sí, con aviso de
  pérdida de acceso de la UI (Hermes entra por el Supervisor y no se cae).
  Riesgo **alto**. M. Familia desactivada por defecto.
- **CAP-070 — Registros: orden e ids** (Core-A25). `config/area_registry/reorder`,
  `config/floor_registry/reorder`, `config/entity_registry/get_automatic_entity_ids`,
  `config/entity_registry/settings/get|update`,
  `config/device_registry/list_linked_devices|list_composite_splits`. Tools:
  `ha_reorder_areas`, `ha_reorder_floors`, `ha_get_automatic_entity_ids`
  (media: renombrar entidades en lote), `ha_get_entity_registry_settings`,
  `ha_update_entity_registry_settings`, `ha_list_linked_devices`. 2P: no. S.
- **CAP-071 — Lecturas y ajustes menores de la UI** (Core-A25).
  `lovelace/config/delete`, `trace/contexts`, `frontend/get_themes`,
  `webhook/list` (auditoría: media), `vacuum/get_segments`,
  `radio_frequency/list`. Tools: `ha_reset_lovelace_dashboard_config` (2P),
  `ha_get_trace_contexts`, `ha_list_themes`, `ha_list_webhooks`,
  `ha_list_vacuum_segments`, `ha_list_radio_frequency`. S.
- **CAP-072 — Imágenes subidas** (Core-A25). `image/list|create|update|delete`
  (la subida va por REST multipart). Tools: `ha_list_uploaded_images`,
  `ha_delete_uploaded_image` (2P). S.
- **CAP-073 — Credenciales de aplicación (lectura)** (Core-A25).
  `application_credentials/list|config|config_entry`. Tool:
  `ha_list_application_credentials` (sin `client_secret`). S.
- **CAP-074 — Analytics y labs** (Core-A25). `analytics`,
  `analytics/preferences`, `labs/list`, `labs/update`. Tools:
  `ha_get_analytics`, `ha_update_analytics` (2P), `ha_list_labs_features`,
  `ha_set_labs_feature` (2P). S.
- **CAP-075 — Escritura en el Marketplace** (Core-A26, HR).
  `marketplace/repositories/add|remove|detect`,
  `marketplace/repository/install|uninstall|version|beta|ignore|refresh`,
  `marketplace/critical/acknowledge`. Tools: `ha_marketplace_install`,
  `ha_marketplace_uninstall`, `ha_marketplace_set_version`,
  `ha_marketplace_add_repository`, `ha_marketplace_remove_repository`,
  `ha_marketplace_refresh`, `ha_marketplace_ignore`,
  `ha_marketplace_acknowledge_critical`. 2P: sí, con backup previo; opción
  `marketplace_write_enabled: false` por defecto. Riesgo **alto** (código de
  terceros). L. Nunca `marketplace/github/connect` ni `warning/accept` (D).
  Ojo: con la familia, el prefijo `ha_marketplace_` no debe dar `readOnlyHint`
  (ya está por nombre exacto en `_annotations.py`).

### Bloque 4 — Huecos A del Supervisor (CAP-080 a CAP-094)

Las rutas de cada CAP están en `inventario/supervisor-rutas.tsv`. Ninguna exige
subir de rol; con `manager` entran todas salvo `POST /reload_updates` (usar
`/refresh_updates`).

| ID | Capacidad | Rutas | Tools propuestas | 2P | Riesgo | Esf. | Prio. | Origen |
|---|---|---|---|---|---|---|---|---|
| CAP-080 | Actualizaciones del sistema con vista previa útil | `GET /available_updates`, `POST /reload_updates` (o `/refresh_updates`), `POST /core/update`, `/os/update`, `/supervisor/update`; `GET /os/info` | `sv_list_available_updates`, `sv_check_for_updates`, `sv_update_core(version?, backup=true)`, `sv_update_os(version?)`, `sv_update_supervisor` | sí en las tres `update`: versión actual → destino, notas, backup, `/resolution/info` y `/core/check` antes; seguimiento por job | alto | M | alta | SV-A1 / Hallazgo |
| CAP-081 | Logs del sistema | `/core/logs[/latest|/boots/{b}]`, `/supervisor/logs[...]`, `/host/logs[/identifiers…|/boots…]`, `/{dns,audio,multicast}/logs[...]`, `/addons/{app}/logs/{latest,boots/{b}}` | `sv_get_core_logs`, `sv_get_supervisor_logs`, `sv_get_host_logs`, `sv_list_host_log_identifiers`, `sv_list_boots`, `sv_get_plugin_logs`; `boot`/`latest` en `sv_get_addon_logs` | no | bajo (redacción de red y secretos; depende de CAP-010) | S | alta | SV-A2 |
| CAP-082 | Tienda: repositorios, recarga, changelog, documentación, versión | `/store`, `/store/reload`, `/store/repositories[/{r}[/repair]]`, `/store/addons/{app}/{changelog,documentation,availability,{version}}`, `/store/addons/{app}/{install,update}/{version}` | `sv_list_store_repositories`, `sv_add_store_repository`, `sv_remove_store_repository`, `sv_repair_store_repository`, `sv_reload_store`, `sv_get_addon_changelog`, `sv_get_addon_documentation`, `sv_check_addon_availability`; `version` en `sv_install_addon`/`sv_update_addon` | sí en añadir/quitar repositorio | medio (cadena de suministro; `_third_party_text`) | S-M | alta | SV-A3 |
| CAP-083 | Montajes de red y ajustes de backup | `/mounts[/{m}[/reload]]`, `/mounts/options`, `/backups/info`, `/backups/options`, `/backups/reload` | `sv_list_mounts`, `sv_create_mount`, `sv_update_mount`, `sv_delete_mount`, `sv_reload_mount`, `sv_set_default_backup_mount`, `sv_get_backup_settings`, `sv_set_backup_settings`, `sv_reload_backups`; `location` en `sv_create_backup_*` (nunca `.cloud_backup`) | sí en crear/editar/borrar y montaje por defecto | medio (la contraseña CIFS entra pero nunca se devuelve ni se registra) | M | alta | SV-A4 |
| CAP-084 | Control de Core y del Supervisor | `GET /core/stats`, `POST /core/{start,rebuild,options}`, `GET /supervisor/stats`, `POST /supervisor/{reload,restart,repair,options}`, `POST /host/reload` | `sv_get_core_stats`, `sv_start_core`, `sv_rebuild_core`, `sv_set_core_options`, `sv_get_supervisor_stats`, `sv_reload_supervisor`, `sv_restart_supervisor`, `sv_repair_supervisor`, `sv_set_supervisor_options` (solo `timezone`, `country`, `logging`, `auto_update`, `diagnostics`) | sí salvo stats y `reload` | medio (`sv_start_core` sirve con Core caído si el vigilante de Hermes lo aguanta: revisar `health_reconnect_tolerance_seconds`) | S-M | media | SV-A5 |
| CAP-085 | Disco, host y OS: lectura | `GET /host/services`, `/host/disks`, `/host/disks/{disk}/usage`, `/os/info`, `/os/config/swap`, `/os/datadisk/list` | `sv_list_host_services`, `sv_get_disk_usage(max_depth)`, `sv_get_os_info`, `sv_get_swap`, `sv_list_datadisk_candidates` | no | bajo | S | media-alta (disco lleno: causa frecuente de fallos) | SV-A6 |
| CAP-086 | Host y OS: escritura | `POST /host/shutdown`, `/host/options`, `/os/config/swap`, `/os/boot-slot` | `sv_shutdown_host`, `sv_set_hostname`, `sv_set_swap`, `sv_set_boot_slot` | sí, con aviso explícito (nadie enciende el host a distancia; `boot-slot` reinicia en el OS anterior) | alto | M | media | SV-A6 |
| CAP-087 | Jobs y centro de resolución completo | `GET /jobs/info`, `POST /resolution/suggestion/{s}`, `/resolution/check/{c}/{run,options}`, `/resolution/healthcheck`, `GET /resolution/issue/{i}/suggestions` | `sv_list_jobs`, `sv_apply_resolution_suggestion` (HR), `sv_run_resolution_check`, `sv_set_resolution_check_enabled`, `sv_run_healthcheck` | sí en aplicar (la vista previa traduce `execute_reboot`, `execute_remove`, `execute_reset`…) y en desactivar chequeos | medio | S-M | media | SV-A7 / HR |
| CAP-088 | Hardware, seguridad, Docker y hora (lectura) | `GET /hardware/info`, `/hardware/audio`, `/security/info`, `POST /security/integrity`, `GET /docker/info`, `/time/info` | `sv_get_hardware(subsystem?)`, `sv_get_security_info`, `sv_run_integrity_check`, `sv_get_docker_info`, `sv_get_time_info` | no | bajo (redactar números de serie si se decide) | S | media | SV-A8 |
| CAP-089 | Red del host: lectura | `GET /network/info`, `/network/interface/{i}/info`, `/network/interface/{i}/accesspoints` | `sv_get_network_info`, `sv_get_network_interface`, `sv_scan_wifi` | no | bajo (direcciones redactadas en el log) | S | media | SV-A9 |
| CAP-090 | Red del host: escritura | `POST /network/reload`, `/network/interface/{i}/update`, `/network/interface/{i}/vlan/{v}` | `sv_reload_network`, `sv_update_network_interface`, `sv_create_vlan` | sí, con aviso fuerte; nunca la interfaz por la que entra Hermes; el Supervisor no revierte solo | **muy alto** | M-L | baja | SV-A9 |
| CAP-091 | Plugins (DNS, audio, multicast, observer, CLI) | `/{dns,audio,multicast,observer,cli}/{info,stats,update}`, `/{dns,audio,multicast}/restart`, `/dns/{options,reset}`, `/multicast/options`, `/audio/{reload,profile,volume,mute,default}` | `sv_get_plugin_info(plugin)`, `sv_update_plugin`, `sv_restart_plugin`, `sv_set_dns_servers`, `sv_reset_dns` (audio, solo si se pide) | sí en update/restart/options | bajo-medio | S-M | baja | SV-A10 |
| CAP-092 | Docker: registros privados y opciones | `GET/POST /docker/registries`, `DELETE /docker/registries/{h}`, `POST /docker/options` | `sv_list_docker_registries`, `sv_add_docker_registry`, `sv_remove_docker_registry`, `sv_set_docker_options` | sí | medio (credenciales del registro por el cliente) | S | baja | SV-A11 |
| CAP-093 | Apps: rebuild y validar opciones | `POST /addons/{app}/rebuild`, `/addons/{app}/options/validate` | `sv_rebuild_addon`; `options/validate` dentro de la vista previa de `sv_set_addon_options` | sí en rebuild | bajo | S | media (validar mejora una tool existente) | SV-A12 |
| CAP-094 | Placas y hora | `/os/boards/{green,yellow,raspberrypi/firmware[/update],{board}}`, `POST /time/options` | `sv_get_board_settings`, `sv_set_board_leds`, `sv_update_rpi_firmware`, `sv_set_ntp_servers` | sí en escritura | bajo | S | baja | SV-A13 |

### Resumen por prioridad

| Prioridad | CAP |
|---|---|
| alta (21) | 001, 002, 004, 005, 006, 010, 019, 022, 034, 040, 041, 042, 043, 044, 045, 046, 047, 080, 081, 082, 083 |
| media-alta (11) | 003, 007, 020, 048, 049, 050, 051, 052, 060, 064, 085 |
| media (28) | 008, 011, 012, 016, 021, 023, 027, 030, 031, 035, 036, 053, 054, 055, 056, 057, 058, 059, 068, 084, 086, 087, 088, 089, 093, 100, 101, 104 |
| baja (35) | 013, 014, 015, 017, 018, 024, 025, 026, 028, 029, 032, 033, 037, 038, 061, 062, 063, 065, 066, 067, 069, 070, 071, 072, 073, 074, 075, 090, 091, 092, 094, 102, 103, 105, 106 |

Total: **95 CAP**. Si todo fuera tool dedicada, las CAP de Core y del
Supervisor suman unas **210 tools nuevas** (135 de Core y 76 del Supervisor,
contando las del informe), más de 400 en total sin la clase C.

## R-3 — Clase C: gestión específica de integraciones

192 comandos en 22 integraciones. El reparto lectura / escritura /
suscripción es una heurística por el verbo del comando (a revisar comando a
comando en la sub-spec); las suscripciones son B en la práctica.

| CAP | Integración | Cmd. | L / E / S | Qué habilitaría | Cómo cubrirla |
|---|---|---|---|---|---|
| CAP-100 | `zwave_js` | 55 | 20 / 26 / 9 | Estado de red y nodos, parámetros de configuración, diagnóstico de nodos, reconstruir rutas, refrescar valores, buscar actualizaciones de configuración. Inclusión/exclusión (S2, SmartStart, PIN), firmware OTA y NVM son interactivos o muy destructivos | Lectura por la tool genérica (`read`); `set_config_parameter`, `refresh_node_*`, `rebuild_node_routes` con 2P; `hard_reset_controller`, `restore_nvm`, `remove_failed_node`, `replace_failed_node`, `add_node`/`remove_node` y lo que pide PIN o pulsar un botón, `deny`. Si se quiere tool dedicada: `ha_zwave_get_network_status`, `ha_zwave_get_node`, `ha_zwave_get_config_parameters`, `ha_zwave_set_config_parameter` (2P). Prioridad media |
| CAP-101 | `zha` | 28 | 13 / 15 / 0 | Dispositivos, grupos, bindings, atributos de clústeres, ajustes de red, backups de red, permitir unir | Lectura genérica; `permit` (con duración acotada), bindings, grupos y `reconfigure` con 2P; `network/backups/restore`, `change_channel` y escrituras de atributos arbitrarios, `deny`. Prioridad media |
| CAP-102 | `matter` | 11 | 3 / 7 / 1 | Diagnóstico de nodos, topología, `ping_node`, ventana de commissioning para compartir con otro ecosistema | Lectura genérica; `open_commissioning_window` e `interview_node` con 2P; `commission*`, `remove_matter_fabric`, `set_wifi_credentials`, `set_thread`, `deny` (credenciales o destructivo). Baja |
| CAP-103 | `thread` (7) y `otbr` (4) | 11 | 4 / 7 / 0 | Datasets, router de borde preferido, crear red, canal | Lectura (`list_datasets`, `otbr/info`, `discover_routers`) genérica; `get_dataset_tlv` devuelve la clave de red: `deny` o redactado; crear red, borrar dataset, cambiar canal, `deny`. Baja |
| CAP-104 | `mqtt` | 2 | 1 / 0 / 1 | `mqtt/device/debug_info`: qué topics y payloads tiene un dispositivo | Lectura genérica o `ha_get_mqtt_debug_info`; `mqtt/subscribe` es B. Media |
| CAP-105 | `usb` (3) y `bluetooth` (4) | 7 | 3 / 0 / 4 | Puertos serie y dongles (con CAP-088, para configurar Zigbee/Z-Wave); escáneres Bluetooth | `usb/list_serial_ports` y `usb/scan` por la genérica; las de `bluetooth` son suscripciones (B). Baja |
| CAP-106 | Resto: `insteon` (30), `knx` (23), `lcn` (7), `esphome` (4 + `sendspin` 1), `lorawan` (2), `dynalite` (2), `mobile_app` (2), `wyoming`, `modbus`, `html5`, `generic`, `zeroconf`, `ssdp`, `dhcp` (1 cada una) | 78 | — | Gestión propia de cada integración (ALDB de Insteon, proyecto ETS y telegramas de KNX, entidades LCN…) | Solo la tool genérica, con la tabla: lectura `read`; escrituras `confirm` tras revisarlas; `esphome/get_encryption_key`, `sendspin/get_pairing_token` y `notify/html5/appkey` (secretos), `deny`; suscripciones y `generic_camera/start_preview`, B. Baja |

Recomendación: la clase C no justifica tools dedicadas salvo, quizá, el
paquete de lectura de Z-Wave/ZHA/Matter y `mqtt/device/debug_info`, que es lo
que más se pide. Con la tool genérica y la tabla, toda la clase C queda
alcanzable el día que la tabla la clasifique, sin crecer la lista de tools.

## R-4 — Exclusiones

### Clase B (Core 103, Supervisor 67): no aplica a un MCP

| Grupo | N.º | Por qué |
|---|---|---|
| Suscripciones y streaming (`subscribe_*`, `*/subscribe`, `history/stream`, `logbook/event_stream`, `*/logs/follow`) | 41 Core + rutas `follow` | MCP es petición-respuesta; `ha_wait_for_event` cubre las esperas puntuales |
| Datos internos del frontend (iconos, traducciones, datos de usuario de la UI, paneles, versión) | 8 | Para el navegador. Excepción: `frontend/get_translations` se usará por dentro en CAP-036 |
| Vistas previas en vivo de formularios de helpers (`template`, `group`, `threshold`… `start_preview`) | 7 | Suscripciones de la UI. Posible reclasificación futura como lectura de un solo mensaje (no propuesta) |
| Depurador paso a paso (`trace/debug/*`) | 6 | Interactivo |
| Vídeo y audio en el navegador (HLS, WebRTC, captura de audio) | 7 | Binario o tiempo real |
| Ayudas de formulario, orden, sugerencias de la UI, `slugify`, `ping`, negociación del protocolo | ~15 | Sin valor para un agente |
| Ingress y señales internas del Supervisor (`supervisor/*` en Core; `/ingress/*`, `/discovery*`, `/services*`, `/auth` en el Supervisor) | 5 Core + ~15 rutas | Las usa el frontend u otra app; algunas exigen ser Core |
| Alias legados del Supervisor (`/homeassistant/*`, `/addons/{app}/{install,update,…}`, `/addons/reload`, `/supervisor/available_updates`) | ~30 rutas | Se usa la ruta canónica. Ojo: `/refresh_updates` figura como alias, pero con `manager` es la que entra (CAP-080) |
| Imágenes de la tienda (`icon`, `logo`) | 4 rutas | Binario para la UI |
| Otros: `auth/current_user`, `entity/source` (obsoleto), `config/entity_registry/get_entries` (lote de la UI), `marketplace/repository/info` (sale a GitHub), `subscribe_trigger` | — | Hermes no es una persona o ya hay equivalente. `subscribe_trigger` se propone reclasificar (CAP-038) |

### Clase D (Core 51, Supervisor 20): peligroso o no automatizable

| Grupo | N.º | Por qué |
|---|---|---|
| `cloud/*` (Nabu Casa) | 21 | Cuenta, login, suscripción de pago, Remote UI, sincronización con Alexa/Google |
| `debug_console/*` | 10 | Python arbitrario dentro de HA |
| `auth/*` | 7 | Tokens de larga duración, MFA, firmar rutas, revocar sesiones (incluida la de Hermes) |
| `config/auth_provider/homeassistant/*` | 5 | Contraseñas y nombres de usuario |
| `application_credentials/create|update|delete` | 3 | `client_secret` de OAuth de terceros pasando por el cliente MCP |
| `marketplace/github/connect`, `marketplace/warning/accept` | 2 | Login OAuth de GitHub y aceptación humana del riesgo de código de terceros |
| `execute_script` | 1 | Secuencia arbitraria sin persistir ni trazar; ya existe el camino seguro (script con 2P) |
| `webhook/handle` | 1 | Invocar webhooks como si viniera de fuera |
| `assist_pipeline/run` | 1 | Audio en tiempo real por streaming |
| Supervisor: `/addons/{app}/sys_options`, `/os/ssh/authorized_keys` (3) | 4 | `core_only`: imposibles con el token de una app |
| Supervisor: `/addons/{app}/security`, `/auth/reset`, `/os/datadisk/wipe` | 3 | Escalada de privilegios o borrado total (fuera de `manager`) |
| Supervisor: `/addons/{app}/stdin`, `/core/stop`, `/backups/freeze|thaw`, `/backups/new/upload`, `/backups/{slug}/download` | 6 | Entrada arbitraria; deja HA sin UI; congela Core; binarios de cientos de MB |
| Supervisor: `/os/config/sync`, `/os/datadisk/move`, `/docker/migrate-storage-driver`, `/docker/reset-storage`, `/security/options`, `/jobs/options`, `/jobs/reset` | 7 | Exigen hardware o reinicio, borran todas las imágenes o rebajan la seguridad del sistema |

### D viables con salvaguardas fuertes (candidatas a «duda para el final»)

| Candidata | Salvaguardas que harían falta | Valor |
|---|---|---|
| `cloud/status`, `cloud/subscription` (solo lectura) | Redactar correo e identificadores; nada que escriba | Medio: diagnosticar Remote UI y la cuenta |
| `cloud/alexa/entities[/get]`, `cloud/google_assistant/entities[/get|/update]`, `cloud/alexa/sync` | 2P como CAP-055; familia desactivada | Medio: completa la exposición a asistentes |
| `cloud/remote/connect|disconnect` | 2P con aviso de que corta el acceso remoto de la UI (Hermes no depende de él) | Bajo-medio |
| `auth/delete_refresh_token`, `auth/refresh_token_set_expiry` | 2P; nunca el token de Hermes ni el de la sesión del propietario en uso; lista previa con CAP-056 | Medio: respuesta a un incidente (revocar una sesión sospechosa) |
| `execute_script` | 2P con la secuencia en la vista previa y la clasificación de `auto_classify_restricted` aplicada a cada paso | Bajo: el camino seguro ya existe |
| `assist_pipeline/run` solo texto (`start_stage: intent`) | 2P como `conversation.process` (CAP-020/060); un solo mensaje | Bajo-medio: probar una pipeline concreta |
| `application_credentials/delete` | 2P; no introduce secretos | Bajo |
| `config/auth_provider/homeassistant/admin_change_username` | 2P; nunca el propietario | Bajo (riesgo de bloqueo) |
| `POST /addons/{app}/stdin` | 2P; solo apps que declaran `stdin: true`; lista blanca por opción | Bajo |
| `POST /core/stop` | 2P; solo si existe `sv_start_core` (CAP-084) y el vigilante de Hermes tolera Core parado | Bajo |
| `POST /supervisor/options` con `channel` | 2P; vuelta a `stable` documentada | Bajo |

No viables en ningún caso: `debug_console/*`, `auth/long_lived_access_token`,
MFA, `sign_path`, contraseñas, `client_secret`, aceptar avisos del
Marketplace, `/auth/reset`, `/addons/{app}/security`, `/os/datadisk/wipe`,
`/docker/reset-storage`, `/security/options`, `core_only`.

## R-5 — Arquitectura: opciones, pros, contras y recomendación

### a) Cuántas tools

**Hechos**:

- Hoy: 216 tools registradas desde 44 módulos (`tools/__init__.py`,
  `register_all_tools` llama a `register(mcp)` de cada módulo); anotaciones
  centralizadas por prefijo y nombre exacto en `tools/_annotations.py` (92 de
  solo lectura, 80 destructivas). 69 tools (un 32 %) son CRUD y acciones de los
  11 dominios de helpers.
- `tools/list` de las 216: ~215 KB de JSON, ~1 KB por tool; del orden de
  50–60 mil tokens de contexto si el cliente carga todas.
- **MCP 2026-07-28** (leído en los tipos del SDK `mcp` 2.3.0, que la
  implementa; no se ha leído el texto de la especificación): `Tool` tiene
  `name`, `title`, `description`, `inputSchema`, `outputSchema`, `annotations`
  (hints), `icons` y `_meta`; **no hay grupos ni espacios de nombres de
  tools**. `tools/list` es paginable (`nextCursor`) y cacheable (`cacheScope`,
  SEP-2549); el aviso `tools/list_changed` llega por `subscriptions/listen`.
  Hermes funciona sin estado (`stateless_http`), así que activar o desactivar
  familias en caliente por sesión no es práctico: la lista se fija al arrancar.
  También existe `InputRequiredResult` (`inputRequests`, `requestState`), una
  vía nativa para pedir información al cliente a mitad de una llamada:
  candidata para CAP-028, no para sustituir ya los dos pasos.
- Algunos clientes cargan las tools bajo demanda (búsqueda de tools); otros
  cargan todas o limitan su número. No se puede contar con lo primero.

**Opciones**:

| Opción | Pros | Contras |
|---|---|---|
| A. Una tool dedicada por capacidad (lo de hoy, extendido) | Esquema, validación, vista previa semántica y anotaciones exactas por tool; nombres predecibles | ~430 tools sin la clase C (600+ con ella); ~430 KB de lista (~110 mil tokens); clientes que limitan el número de tools; mucho código y tests por tool de bajo uso |
| B. Solo tools genéricas (`ha_read_ws_command`, `ha_call_ws_command`, `sv_read_api`, `sv_call_api`) con tabla de clasificación | 4 tools cubren todo, incluida la clase C y los comandos que traiga cada versión de HA; la lista no crece | El cliente tiene que conocer los payloads de HA (sin documentación estable); vista previa genérica (sin diff ni recuentos); peor validación; una tool genérica de escritura es destructiva para el cliente y pide permiso hasta para leer si no se separa |
| C. Híbrida: dedicadas para lo de valor alto + genéricas con tabla para la cola larga y la clase C + familias configurables | Lo frecuente conserva vista previa semántica; lo raro es alcanzable sin crecer la lista; las familias recortan el contexto de quien no las usa; la tabla es una sola fuente de verdad, fail-closed, con test de deriva | Dos caminos que mantener coherentes (la tabla marca `dedicated` lo que tiene tool propia para que la genérica no salte sus protecciones); la tabla hay que revisarla en cada versión de HA |
| D. Consolidar las existentes (por ejemplo, `ha_list_helpers(domain)` en vez de 11 `ha_list_*`) | Ahorra ~50 tools y ~50 KB | Rompe a los clientes y la guía; exige alias y una versión que lo anuncie |

**Recomendación**: **C**, con cuatro genéricas separadas por lectura y
escritura (para que los hints sean verdad y el cliente no pida permiso al
leer), tabla `dedicated|read|confirm|deny` con todo lo desconocido rechazado,
y familias por opción con un conjunto por defecto que no pase mucho de las
~250–270 tools. Dedicadas: las CAP de prioridad alta y media-alta y las de
riesgo alto (donde la vista previa semántica es la salvaguarda). D queda como
decisión aparte para una versión mayor.

### b) Banco de pruebas

**Core en el CI (recomendado, CAP-005)**:

- Imagen oficial de Core 2026.11.1 como servicio del job (fijada por digest,
  como las actions). GitHub Actions es gratis sin límite de minutos en
  repositorios públicos con los runners estándar; la imagen pesa del orden de
  1–2 GB y Core arranca en menos de un minuto.
- Alta automática: onboarding por REST (`/api/onboarding/users` → código →
  `/auth/token`), resto de pasos del onboarding y token de larga duración por
  WebSocket. Credenciales generadas en el propio job, nunca guardadas.
- **Cómo conecta Hermes**: Hermes construye `…/core/api` y
  `…/core/api/websocket` a partir de `supervisor_base_url` (`ha.py`) y al
  arrancar llama a `/supervisor/ping` y `/core/info` (`network.py`). Opciones:
  (1) un **Supervisor de pruebas** mínimo en `tests/` (aiohttp) que responde a
  esas dos rutas y reenvía `/core/api/*` (REST y WebSocket) a Core, con
  `HAClient` creado en el proceso del test con el token de larga duración como
  `supervisor_token`: **sin cambiar código de producto**; (2) una variable de
  entorno que cambie la URL base: cambio de producto y una puerta más que
  proteger, descartada; (3) el contenedor del add-on entero con un alias de red
  `supervisor`: más fiel, pero sigue necesitando el reenviador y es más lento;
  para una fase posterior.
- Qué cubre: todas las `ha_*` que escriben (helpers, automatizaciones, scripts,
  escenas, registros, Lovelace, flujos de config entries con integraciones sin
  hardware como `template`, `group` o `utility_meter`) y las capacidades nuevas
  de Core. Qué no: todo `sv_*`, la integración `hassio`, el Marketplace (sale a
  GitHub), `cloud`.
- Extra con mucho valor: la misma suite contra la versión mínima declarada
  (2024.10) en una matriz, lo que comprueba de verdad la compatibilidad que se
  anuncia.

**Supervisor (CAP-006)**:

- Opciones: (1) **VM con HAOS** (HAOS publica imágenes qcow2, vmdk, vhdx y
  ova) en un equipo del mantenedor, con instantánea antes de cada tanda y
  Hermes instalado como add-on local (construido desde el Dockerfile, sin la
  línea `image:`); las pruebas se lanzan contra su endpoint MCP con una
  contraseña de prueba. Aquí, y solo aquí, se ejecutan reinicios, apagados,
  restauraciones, desinstalaciones y el cambio a `hassio_role: manager`.
  (2) La misma VM en un runner de GitHub con KVM (QEMU; los runners Linux
  estándar exponen `/dev/kvm` en repos públicos, a confirmar): arranque,
  inicialización del Supervisor y descarga de Core se van a 10–20 minutos;
  sirve como job nocturno o manual, no por PR. (3) El devcontainer del
  Supervisor (Docker dentro de Docker): pensado para desarrollar el
  Supervisor, frágil y sin soporte para esto; descartado.
- Recomendación: CI con Core por PR (010); VM local para el Supervisor (014),
  y la VM en el CI con KVM como mejora si la local funciona.

### c) Versionado

| Opción | Pros | Contras |
|---|---|---|
| Una 1.2.0 con todo | Un solo anuncio | Meses sin publicar; revisión imposible (principio IX); un fallo bloquea todo; los arreglos pequeños esperan |
| Varias minor por bloques (1.2.0, 1.3.0…) | Cada versión se prueba en vivo y se puede revertir; el CHANGELOG cuenta algo coherente | Más publicaciones; la 1.3.0 llega antes, y con ella la retirada anunciada de los alias `ha_hacs_*` |
| Patch para los pendientes pequeños + minor por bloques | Los arreglos (CAP-010 a CAP-018, CAP-021) salen ya | Igual que la anterior |

**Recomendación**: **1.1.3** con los pendientes pequeños; **1.2.0** con la
infraestructura (banco de Core, tabla, genéricas, familias) y el diagnóstico de
lectura; después una minor por bloque. La 1.3.0 retira los alias `ha_hacs_*`
como está anunciado (avisarlo en el CHANGELOG de la 1.2.0) y es buena candidata
para retirar también `ha_remove_device_from_config_entry`.

## R-6 — Desglose propuesto del programa

Cada sub-feature cabe en 1–3 agentes (≲ 15 tools nuevas o un cambio
transversal acotado). Orden recomendado; las que no dependen entre sí pueden
ir en paralelo.

| Spec | Nombre | CAP | Depende de | Versión sugerida |
|---|---|---|---|---|
| 009 | `correcciones-pendientes` | 010–018, 021, 024 | — | 1.1.3 |
| 010 | `banco-de-pruebas-core` | 005, 034 (parte de Core) | — | 1.2.0 |
| 011 | `politica-de-comandos` (tabla, genéricas, familias, deriva, guía) | 001, 002, 003, 004, 007, 008 | 010 (para probar de verdad) | 1.2.0 |
| 012 | `diagnostico-core` (lectura) | 040, 041, 042, 043, 047, 049, 058, 068 | 009 (CAP-010) | 1.2.0 |
| 013 | `diagnostico-supervisor` (lectura) | 081, 085, 088, 089, 087 (lectura) | 009 (CAP-010) | 1.2.0 |
| 014 | `banco-de-pruebas-supervisor` (VM, rol `manager`, pruebas manuales) | 006, 022, 034 (parte del Supervisor), 035 | 010 | 1.3.0 |
| 015 | `actualizaciones-y-tienda` | 080, 064, 082, 093 | 013, 014 | 1.3.0 |
| 016 | `integraciones-flujos-y-repairs` | 044, 045, 048, 036, 037 | 010 | 1.3.0 |
| 017 | `automatizacion-asistida` | 046, 051, 052, 038 (y CAP-040 dentro del guardado) | 012 | 1.4.0 |
| 018 | `mejoras-de-tools-existentes` | 019, 020, 023 | 010 | 1.3.0 (CAP-019 puede adelantarse) |
| 019 | `backups-y-montajes` | 083, 057, 027 | 014 | 1.4.0 |
| 020 | `estadisticas-y-energia` | 050, 054 | 012 | 1.4.0 |
| 021 | `configuracion-del-sistema` | 053, 055, 056, 069, 074 | 011 (familias) | 1.5.0 |
| 022 | `administracion-supervisor` | 084, 086, 087 (escritura), 090, 091, 092, 094 | 014, 011 | 1.5.0 |
| 023 | `assist-y-conversacion` | 060, 061, 062, 063 | 018 (CAP-020), 011 | 1.5.0 |
| 024 | `menores-core` | 059, 065, 066, 067, 070, 071, 072, 073 | 011 | 1.6.0 |
| 025 | `integraciones-especificas` (clase C por la tabla) | 100–106 | 011 | 1.6.0 |
| 026 | `marketplace-escritura` (opcional, desactivada) | 075 | 011, 014 | cuando se decida |
| 027 | `plataforma-y-deprecaciones` | 025, 026, 028, 029, 030, 031, 032, 033 | — (030 y 031 con fecha) | 1.3.0 para 030/031; el resto, cuando toque |

Notas:

- 012 y 013 pueden ir en paralelo; 016 y 018 también.
- Si el mantenedor elige la opción A de R-5 a), 011 se reduce a familias y
  deriva, y 021–025 crecen (más tools dedicadas por spec).
- Las D candidatas de R-4 no tienen spec: se decidirán al final del programa.

## R-7 — Preguntas para el mantenedor (decisiones de diseño abiertas)

1. Arquitectura de tools (R-5 a): A, B, C o C + D. La recomendación es C.
2. Familias activas por defecto (CAP-004) y si el conjunto por defecto debe
   quedarse cerca de las tools de hoy.
3. Banco de pruebas del Supervisor: VM local, VM en el CI con KVM, o las dos.
4. Versionado (R-5 c): 1.1.3 + minor por bloque, o otra pauta.
5. Bajar a `hassio_role: manager` en cuanto pase la prueba en la VM, aunque el
   Supervisor lo enseñe como cambio de permisos al actualizar.
6. Las D candidatas de R-4.
