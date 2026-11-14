# Investigación: Hermes 1.0.12

Fase 0 del plan. Recoge las decisiones técnicas, por qué se toman y qué se
descartó. La evidencia de fondo es la revisión de compatibilidad de noviembre de
2026 (código de HA Core 2026.11.1 y Supervisor 2026.11.0 leído en sus tags),
resumida en `docs/HOJA-DE-RUTA.md`. No quedan marcas «NEEDS CLARIFICATION».

## Transversal

### R-0.1 Código de error de Home Assistant en las excepciones

- **Decisión**: `HAConnectionError` gana un atributo `code` (opcional) que `_handle_ws_message` rellena con `error.code` de la respuesta WS. El texto del mensaje no cambia.
- **Razón**: Home Assistant da códigos estables (`not_found`, `unknown_command`, `invalid_format`, `not_allowed`, `home_assistant_error`), mientras que el texto cambia de un comando a otro («Entity not found», «Unable to find counter_id …», «Config entry not found»). Hoy `ha.py:526-531` descarta el código y `ha.py:873` busca «not found» en un texto que no lo contiene: la rama `not_found` es código muerto (D1).
- **Alternativas**: ampliar la búsqueda de texto («Unable to find»): frágil y vuelve a romperse con el siguiente texto. Una excepción por código (`HANotFoundError`…): más cambio del necesario y obliga a tocar todos los `except`.

### R-0.2 Versión de HA en tiempo de ejecución

- **Decisión**: módulo nuevo `hermes/src/hermes/ha_version.py` con `ha_core_version()` (WS `get_config` → `version`) y `ha_at_least(minimo)`, que devuelve `True`, `False` o `None` (desconocida). Sin caché. Las versiones `.devN` se comparan por `base_version`.
- **Razón**: la vista previa de `ha_remove_device` tiene que decir qué comando usará antes de ejecutarlo (principio IV), y Home Assistant se puede actualizar mientras Hermes sigue en marcha, así que la versión del arranque (`__main__.py:173-183`) puede estar desfasada. `get_config` ya lo usa `tools/supervisor.py:114` y existe en todas las versiones soportadas.
- **Alternativas**: probar el comando nuevo y caer al viejo con `unknown_command` (no permite una preview veraz); leer `/core/info` del Supervisor (otra petición HTTP y otro punto de fallo); caché con TTL (complica los tests y gana poco: solo se consulta en ramas concretas).

### R-0.3 Organización en lotes

- **Decisión**: fase 0 secuencial (R-0.1 y R-0.2) y luego cuatro lotes paralelos que no comparten ningún fichero, más un lote de integración al final.
- **Razón**: `ha.py` lo necesitan la fase 0 y el lote D; si D1 entero fuera al lote D, los lotes B, C y D dependerían de él. Con la fase 0 fusionada antes, cada lote trabaja contra una base estable.
- **Alternativas**: un solo lote secuencial (no aprovecha el paralelismo pedido); dejar el código de error a cada lote (conflictos en `ha.py`).

## Lote A — Supervisor, jobs y safety backup

### R-A1 Ruta y parseo del job

- **Decisión**: `GET /jobs/{uuid}`; éxito = `done is True` y `errors` vacío; fallo = `done` con `errors` no vacío.
- **Razón**: el Supervisor solo registra `GET /jobs/info` y `GET /jobs/{uuid}`; `/jobs/{id}/info` da 404. El job tiene `done` y `errors` (lista de `{type, message, stage}`), no `state` ni `error`. `done` pasa a `True` también cuando el job falla.
- **Alternativas**: `GET /jobs/info` y buscar el job en el árbol (más datos, sin ventaja).

### R-A2 Anotación pendiente del safety backup

- **Decisión**: claves aparte `pending_job_id`, `pending_started_at` y `pending_backup_name` en `last_safety_backup.json`; `_MARCA` (`last_safety_backup_at`) sigue siendo el último backup correcto. La siguiente escritura resuelve la anotación pendiente antes de mirar la ventana. El límite duro de 60 s cuenta desde el último intento, no solo desde el último éxito.
- **Razón**: si el timeout no deja rastro, cada intento lanza otro backup completo (varios GB). Si se moviera `_MARCA` al lanzar, una escritura posterior dentro de la ventana seguiría adelante con un backup fallido, lo que contradice el principio III.
- **Compatibilidad**: `sv_create_safety_backup` (`tools/backups.py:361-367`) sigue escribiendo `_MARCA` al lanzar, como hasta ahora. Ese comportamiento manual queda fuera de alcance (principio IX) y se anota para otra spec.
- **Alternativas**: esperar más de 5 minutos (bloquea al cliente MCP, que tiene su propio plazo); escribir sin backup tras el timeout (incumple fail-closed).

### R-A3 Saneado de errores de jobs

- **Decisión**: helper `_job_errors()` en `tools/backups.py`: solo el campo `message` de cada error, recortado y pasado por `redact_secrets` (`security.py:377`).
- **Razón**: principio I (nada en crudo) y II (un mensaje de error del Supervisor podría citar rutas u opciones).

### R-A4 Campos de `sv_get_supervisor_info` y `sv_get_host_info`

- **Decisión**: `machine` y `docker_version` desde `GET /info` (`machine`, `docker`); `kernel_version` desde `kernel` de `GET /host/info`. Se conservan los nombres de salida.
- **Razón**: son las claves reales del Supervisor 2026.11.0. `GET /info` está permitido a cualquier app.
- **Alternativas**: `GET /docker/info` (`version`) para Docker: una petición más sin ventaja.

## Lote B — Registros

### R-B1 Alias

- **Decisión**: conservar `None` dentro de la lista; rechazar `aliases: null`.
- **Razón**: desde HA 2026.4, `null` dentro de `aliases` es el marcador de nombre calculado y toda entidad nace con `[null]`; el esquema exige lista (`[Any(str, None)]`).

### R-B2 `ha_remove_device`

- **Decisión**: HA ≥ 2026.9 → `config/device_registry/remove {device_id}`. HA < 2026.9 → `config/device_registry/remove_config_entry` con la única integración del dispositivo (Home Assistant borra el dispositivo cuando se queda sin integraciones). Con varias integraciones en HA < 2026.9, la tool se niega. Versión desconocida → se niega. Los argumentos atados al token son solo `device_id`; el método se recalcula al ejecutar y, si cambió desde la preview (HA actualizado entre las dos llamadas), se aborta.
- **Razón**: `remove` aparece en 2026.9 y en esa versión `remove_config_entry` pasa a ser su alias deprecado (retirada en 2027.9). La preview debe describir exactamente lo que se ejecuta.
- **Alternativas**: llamar a `remove_config_entry` por cada integración en HA antiguo (varias llamadas, fallo parcial difícil de describir en la preview); exigir `config_entry_id` en la tool nueva (obliga al cliente a conocer un detalle que en HA moderno no hace falta).

### R-B3 Área efectiva y recuentos

- **Decisión**: helper `effective_area_id()` en `tools/registry_device.py`: área propia, o la del padre (`parent_device_id`) si es nula, con un máximo de 8 saltos y corte en ciclo. Para entidades: área propia o, si es nula, la efectiva de su dispositivo. Recuentos por integración: `config_entry_id` y, de respaldo, `config_entries`.
- **Razón**: HA 2026.9 añade `ChildDeviceEntry`, sin `config_entries` ni fabricante, que hereda el área del padre (`async_get_effective_area_id`); `config_entries` del dispositivo es retirable en 2027.8.

## Lote C — Lovelace

### R-C1 Panel por defecto

- **Decisión**: leer `frontend/get_system_data` con `key: "core"` y tomar `default_panel`. Al implementar, la forma exacta de la respuesta se comprueba en el código de HA (`components/frontend/__init__.py`, comandos `*_system_data`, presentes desde 2025.12) y se fija en el test. Cualquier forma inesperada o error que no sea `unknown_command` falla cerrado.
- **Razón**: la migración de HA 2026.2 fija `default_panel = "lovelace"` en esos datos de sistema, y el usuario puede cambiarlo. Con `unknown_command` (HA anterior a 2025.12) no hay panel por defecto configurable por esa vía y basta con proteger `null` y `lovelace`.
- **Alternativas**: proteger solo `lovelace` (deja sin proteger un panel por defecto cambiado); leer `.storage/frontend.system_data` del disco (salta la API y el formato no es público).

### R-C2 Lista sin duplicado y recursos

- **Decisión**: si existe `lovelace`, no se añade el «Default» sintético y `lovelace` lleva `is_default: true`. Recursos con `lovelace/resources/list`.
- **Razón**: HA redirige `url_path=None` al dashboard `lovelace` cuando existe, así que son el mismo. El alias `lovelace/resources` estaba anunciado para retirarse en 2025.1 y puede desaparecer sin aviso; `lovelace/resources/list` existe en modo storage y YAML en todas las versiones soportadas.

## Lote D — Automatizaciones, plantillas, servicios, estadísticas y HACS

### R-D1 Avisos de plantilla

- **Decisión**: parámetro `collect_warnings` en `ws_one_shot_subscription`: acumula eventos `{"error", "level": "WARNING"}` hasta el primer evento con `result` o con un error que no sea WARNING, dentro del mismo plazo.
- **Razón**: con `report_errors: true`, HA emite cada aviso como evento antes del resultado. Hoy Hermes toma el primero y pierde el resultado.
- **Alternativas**: quitar `report_errors` (se perderían los errores reales en modo estricto); una función nueva solo para plantillas (duplica la gestión de la suscripción).

### R-D2 Timeout de plantilla

- **Decisión**: reconocer también «Exceeded maximum execution time» en el mensaje. Si la fase 0 deja el código, la respuesta lleva `code: "template_error"`, que no distingue el timeout, así que aquí se mantiene el texto, aislado en una constante.

### R-D3 `trace`

- **Decisión**: `trace: dict[str, Any] | None`. HA siempre lo definió como diccionario (`stored_traces`).

### R-D4 `ha_list_services(domain)`

- **Decisión**: filtro opcional en la tool, sobre la lista que ya devuelve `get_services()`; sin filtro, la respuesta no cambia.
- **Razón**: la respuesta completa ronda los 100 KB en una instalación normal, por encima del límite práctico de algunos clientes.

### R-D5 `period: "year"`

- **Decisión**: error claro si `ha_at_least("2026.3.0") is False`; con versión desconocida decide HA (es una lectura, no hay daño).

### R-D6 HACS

- **Decisión**: con `code == "unknown_command"`, mensaje según la versión: ≥ 2026.11 → Marketplace y entidades `update`; anterior o desconocida → HACS no instalado. Categorías reales y `pending_upgrade`. La migración completa a `marketplace/*` es de 1.1.0.

### R-D7 `perform_action`

- **Decisión**: se corrige el comentario de `tools/ha.py:161-167` y el test de `tests/test_security_regressions.py:211-212` pasa a documentarse como defensa en profundidad. La clave se mantiene en la detección: solo puede dar falsos positivos.

## Integración

### R-I1 Versión mínima

- **Decisión**: `HA_CORE_MIN_SUPPORTED = "2024.10.0"`.
- **Razón**: Hermes normaliza siempre a `triggers`/`conditions`/`actions`, que HA solo acepta desde 2024.10.0; por debajo no se puede guardar ninguna automatización.

### R-I2 Funnel en 8443/10000

- **Decisión**: los README recomiendan `tailscale funnel --bg --https=8443 8765` y `public_hostname: homeassistant.tailXXXX.ts.net:8443`. 443 sigue documentado como válido si no se publica Home Assistant con `share_homeassistant: funnel`.
- **Razón**: el add-on de Tailscale publica Home Assistant en `share_on_port` (443 por defecto) con `--set-path=/` y choca con un Funnel de Hermes en `443:/`. `public_hostname` ya admite `:puerto` (`config.py:131-134`) y las URL OAuth se construyen con él (`oauth.py:421`), así que no hace falta cambiar código.
- **Riesgo**: no se ha verificado que todos los clientes MCP acepten puertos distintos de 443 (spec S-10).
