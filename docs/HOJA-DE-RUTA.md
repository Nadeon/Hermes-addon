<!-- Hoja de ruta de Hermes tras la revisión de compatibilidad de noviembre de
     2026. El plan por versiones es una propuesta pendiente de decisión del
     mantenedor, no un compromiso de fechas. -->

# Hoja de ruta de Hermes

**Revisión:** 2026-11-14, sobre Hermes **1.0.11**.

**Verificado contra:** Home Assistant Core **2026.11.1**, Supervisor **2026.11.0**
y la especificación MCP **2026-07-28**. El código de Core y del Supervisor se
leyó en esos tags; las tools de lectura se probaron en una instalación de prueba
con HA 2026.11.1. Las tools de escritura no se ejecutaron: sus fallos están
confirmados leyendo el código de Hermes y el de Home Assistant.

## Estado de compatibilidad

- **Funciona en lo esencial.** Ningún comando WebSocket o REST que usa Hermes ha
  cambiado de nombre en HA 2026.11.1, y todos los endpoints del Supervisor que
  usa existen, salvo uno (el del sondeo del backup de seguridad).
- **Las tools de HACS no funcionan en HA ≥ 2026.11**: HACS se ha integrado en el
  core como el **Marketplace**, con otra API. Mientras se adaptan, las
  actualizaciones pendientes se ven con `ha_get_states(domain="update")`.
- **La versión mínima real es HA 2024.10**, no la 2024.1 declarada: por debajo
  no se pueden crear ni editar automatizaciones.
- **MCP:** transporte Streamable HTTP sin estado y SDK oficial 2.x, al día. En
  OAuth faltan **CIMD** (Client ID Metadata Documents, el registro preferido
  desde la revisión 2026-07-28) y el parámetro **`iss`** (RFC 9207). El registro
  dinámico (DCR) que usa Hermes sigue funcionando, pero está deprecado.

## Problemas conocidos de 1.0.11

Severidad, de mayor a menor: **pérdida de datos** > **rota** > **degradada** >
**cosmética**. Todas las acciones afectadas de pérdida de datos exigen
`confirmation_token`; el problema es que la vista previa no describe bien lo que
va a pasar.

| # | Problema | Severidad | Origen |
|---|---|---|---|
| 1 | Al reenviar los alias de una entidad, el marcador de «nombre calculado» (`null`) se guarda como el texto `"None"`: la entidad deja de responder a su nombre en Assist | Pérdida de datos | Cambio de HA 2026.4 |
| 2 | `ha_remove_device_from_config_entry` borra el dispositivo entero del registro, no solo la asociación que anuncia | Pérdida de datos | Cambio de HA 2026.9 |
| 3 | El dashboard principal (`url_path: "lovelace"`) se puede borrar con `ha_delete_lovelace_dashboard`, aunque la documentación de la tool dice que no | Pérdida de datos | Cambio de HA 2026.2 |
| 4 | Solo con la opción `safety_backup_enabled` activada (viene desactivada por defecto): el backup de seguridad previo nunca se da por terminado y las escrituras `fs_*` no llegan a ejecutarse | Rota | Hermes |
| 5 | `sv_get_job_status` informa como terminado (`done`) un job que ha fallado, sin sus errores | Rota | Hermes |
| 6 | Las tools `ha_hacs_*` responden «Unknown command» en HA ≥ 2026.11 | Rota | Cambio de HA 2026.11 |
| 7 | Con HA 2024.1–2024.9 no se pueden guardar automatizaciones (versión mínima declarada incorrecta) | Rota | Hermes |
| 8 | No se puede guardar un script que tenga la clave `trace` | Rota | Hermes |
| 9 | `aliases: null`, documentado como «limpiar alias», lo rechaza HA | Rota | Cambio de HA 2026.4 |
| 10 | Borrar un helper que no existe da un error genérico en lugar de `not_found` | Degradada | Hermes |
| 11 | `ha_render_template` devuelve error y pierde el resultado cuando la plantilla solo genera un aviso | Degradada | Hermes |
| 12 | Los dispositivos hijo (HA 2026.9) quedan fuera de los filtros por área y fabricante | Degradada | Cambio de HA 2026.9 |
| 13 | `sv_get_supervisor_info` y `sv_get_host_info` devuelven siempre `null` en algunos campos (máquina, versión de Docker, kernel) | Degradada | Hermes |
| 14 | `ha_list_services` no admite filtro y su respuesta puede superar el límite del cliente | Degradada | Hermes |
| 15 | Desde HA 2026.11, `name` en el registro de entidades es solo la parte de la entidad; la documentación no lo avisa y se duplica el nombre del dispositivo | Cosmética | Cambio de HA 2026.11 |
| 16 | `ha_list_lovelace_dashboards` puede mostrar dos veces el dashboard principal | Cosmética | Cambio de HA 2026.2 |
| 17 | Descripciones de tools que no coinciden con la respuesta real (estadísticas, stats de add-ons, ubicación de backups) | Cosmética | Hermes |
| 18 | La guía enseña sintaxis heredada de automatizaciones (`platform:`, `service:`) | Cosmética | Hermes |
| 19 | Defectos menores de las tools de HACS (categorías, cálculo de actualizaciones, mensaje de error poco claro) | Cosmética | Hermes |
| 20 | Un `not_found` del registro de entidades llega como texto crudo de HA | Cosmética | Hermes |
| 21 | Las tools de lista devuelven formas distintas (lista suelta, bloques sueltos, `{count, items}`) | Cosmética | Hermes |
| 22 | `period: "year"` en estadísticas se acepta sin comprobar que HA sea ≥ 2026.3 | Cosmética | Hermes |
| 23 | El log muestra un traceback inofensivo al apagar y no redacta direcciones de red | Cosmética | Hermes |

Recomendación mientras sale 1.0.12: no reenviar `aliases` leídos del registro,
no usar `ha_remove_device_from_config_entry` salvo que se quiera borrar el
dispositivo, no borrar el dashboard `lovelace` y mantener
`safety_backup_enabled` desactivada, que es su valor por defecto, hasta el
arreglo. Con la opción desactivada, el problema 4 no aparece.

## Deprecaciones con fecha

| Qué | Cuándo | Efecto en Hermes |
|---|---|---|
| Acción `home-assistant/builder@master` y `build.yaml` | Deprecados (aviso del 2026-04-02); retirada anunciada sin fecha | El flujo de publicación de imágenes dejará de funcionar |
| Campos `config_entries` y `config_entries_subentries` del dispositivo | HA **2027.8** (`primary_config_entry`: **2027.10**) | Recuentos de dispositivos por integración |
| Comando `config/device_registry/remove_config_entry` | HA **2027.9** | `ha_remove_device_from_config_entry` dará «Unknown command» |
| Comando `lovelace/resources` (alias) | Anunciado para 2025.1; sigue presente, puede desaparecer sin aviso | `ha_list_lovelace_resources` |
| Campo `has_mean` de estadísticas | Plazo vencido; sigue presente | Solo documentación |
| Acceso TCP de las apps al Supervisor (`SUPERVISOR_TOKEN`) en favor de un socket Unix | Sin fecha; preparado en la rama principal del Supervisor, no publicado en 2026.11.0 | Hermes usa solo TCP |
| API `/v2` del Supervisor (`addons` → `apps`) | Sin fecha; hoy detrás de una opción de desarrollo y sin retirar la V1 | Ninguno hoy |
| DCR (RFC 7591) en MCP | Deprecado en la revisión 2026-07-28; la spec garantiza al menos 12 meses | OAuth de Hermes |
| Constante de versiones de protocolo admitidas del SDK `mcp` (sustituida por las de handshake y modernas) | Deprecada en 2.x | Puede romper con un futuro SDK 3.x |

Pendiente de confirmar en la documentación oficial de Claude: los límites de
~150 000 caracteres por resultado y 240 s por llamada en claude.ai, frente al
`response_max_bytes` de 1 MiB y los 300 s máximos de `ha_wait_for_event` de
Hermes.

Para quien publique Hermes con el add-on de Tailscale: desde la versión 0.14.0
gestiona `share_homeassistant` como servicio propio y, una sola vez, borra la
configuración Serve/Funnel existente. Comprueba el Funnel de Hermes tras
actualizarlo y, si también publicas HA con `share_homeassistant: funnel`, pon
su `share_on_port` en 8443 o 10000 para que no choque con Hermes en el 443.

## Plan por versiones

> **Propuesta pendiente de decisión.** El orden y el contenido pueden cambiar.

### 1.0.12 — solo arreglos (esfuerzo M)

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

Riesgos: los cambios tocan tools destructivas y necesitan tests de regresión;
subir la versión mínima deja fuera HA 2024.1–2024.9.

### PR aparte — publicación de imágenes (esfuerzo S–M)

Antes de que se retire el builder: actions `build-image` y
`publish-multi-arch-manifest`, `FROM` con valor por defecto en el Dockerfile,
etiquetas `io.hass.*` explícitas y fuera `build.yaml`. Riesgo: la primera
publicación con el flujo nuevo debe probarse con un tag de prueba, y las
imágenes ya publicadas deben seguir disponibles.

### 1.1.0 — Marketplace, OAuth moderno y diagnóstico (esfuerzo L)

- Tools del Marketplace de **solo lectura**, con alias de las `ha_hacs_*`.
- CIMD (manteniendo DCR) e `iss`.
- Límites por defecto alineados con los de Claude, una vez confirmados.
- `title` en las tools, versión del servidor, errores marcados como tales.
- Repairs de HA y resolución del Supervisor; trazas de automatizaciones y
  `search/related`; estado de los backups de HA y retención de los backups de
  seguridad; plantas, etiquetas y categorías.

Riesgos: CIMD añade descargas salientes que hay que acotar; límites más bajos
pueden truncar respuestas que hoy pasan; más tools ocupan más contexto.

### 1.2.x y posteriores

- Escritura en el Marketplace, solo si se decide, desactivada por defecto y con
  confirmación, backup previo y vista previa completa.
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
