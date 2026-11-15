# Checklist de calidad de la especificación: control de Core y del Supervisor (022)

**Propósito**: validar que la especificación está completa y tiene calidad antes de planificar
**Creado**: 2026-11-15
**Especificación**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación más allá de los que fijan la 008 y la 011 (nombres de tools, rutas del Supervisor, módulos y tabla que ya existen)
- [x] Centrada en el valor para el usuario (recuperar Core y controlar el Supervisor sin la interfaz ni SSH; aplicar sugerencias sabiendo qué harán)
- [x] Escrita para quien mantiene Hermes
- [x] Todas las secciones obligatorias completas

## Completitud de los requisitos

- [x] No quedan marcadores [NEEDS CLARIFICATION] (las decisiones están en «Clarificaciones» y en research.md)
- [x] Los requisitos se pueden probar y no son ambiguos
- [x] Los criterios de éxito son medibles
- [x] Los criterios de éxito no dependen de la tecnología (salvo nombres de tools, rutas y familias, que son el contrato)
- [x] Todos los escenarios de aceptación están definidos
- [x] Los casos límite están identificados
- [x] El alcance está delimitado (nada de actualizaciones, tienda, montajes, host ni red; `/core/stop` y `channel` siguen cerrados)
- [x] Dependencias y supuestos identificados (011, 013, 014, 018 y 033 en la punta; prueba en vivo pendiente)

## Preparación de la funcionalidad

- [x] Todos los requisitos funcionales tienen criterios de aceptación claros
- [x] Los escenarios de usuario cubren los flujos principales
- [x] La funcionalidad cumple los resultados medibles de los criterios de éxito
- [x] Trazabilidad: cada FR cita el FR de la 008 y la CAP que cubre

## Resultado de `analyze` (2026-11-15)

22 FR, 7 SC, 29 tareas en 2 tramos; cobertura de FR con tareas: 100 %
(tabla de trazabilidad de plan.md). Sin marcadores ni datos personales.
Constitución: sin incumplimientos.

Corregido (CRITICAL/HIGH):

- **A1 (HIGH, principio V)** — `POST /resolution/suggestion/{s}` no solo
  ejecuta el fixup: después el Supervisor lanza `healthcheck()`, que ejecuta
  `run_autofix()` y puede aplicar otras sugerencias con `auto: true`. La vista
  previa habría mentido por omisión. Ahora lista `also_auto_applied`, lo ata
  como estado y aplica `targets_hermes` también a esas (research R-6,
  data-model, T018, T019). El motivo de la entrada `confirm` de
  `POST /resolution/healthcheck` lo dice.
- **A2 (HIGH)** — Orden del tramo 1: las entradas `dedicated` necesitan las
  tools registradas para `TestDedicadas`; T012 (registro) va antes de T010 y
  T011 en las dependencias.
- **A3 (HIGH, principio VIII)** — Las órdenes de la suite llevaban la ruta
  local del `.venv`; sustituida por `<python del .venv>` en tasks.md y
  quickstart.md.
- **A4 (HIGH, coherencia)** — La forma de error decía `message`; Hermes usa
  `detail` (genéricas de la 011, `dashboard_changed` de la 018). Unificado y
  `suggestion_changed` definido como traducción de `ESTADO_CAMBIADO`.

Anotado (MEDIUM/LOW):

- **M1 (duda para el final)** — Candidata D-01 «parar Core»: la 008 la
  condicionaba a que existiera `sv_start_core` y a que Hermes tolerase Core
  parado. Tras la 022 se cumplen las dos; `/core/stop` sigue `deny` hasta que
  decida el mantenedor.
- **M2 (duda menor)** — `sv_restart_core` (1.1.2) se anuncia idempotente y
  `sv_rebuild_core`/`sv_restart_supervisor` no. No se toca la 1.1.2 (FR-020
  de la 008); se propone revisarlo al cierre.
- **M3** — `jobs_in_progress` bloquea si el Supervisor deja un job sin
  terminar indefinidamente; la respuesta nombra el job y el usuario puede
  reiniciar desde la interfaz. Se valida en la VM.
- **M4** — Tramo 1 con siete tools: en el límite de un agente. Punto de corte
  definido en tasks.md (tras T009 + T012).
- **M5** — Estadísticas `read` sin tool, aunque el research de la 008
  proponía `sv_get_core_stats`/`sv_get_supervisor_stats`: manda FR-076.
- **M6** — `POST /host/reload` va `confirm` por la tabla (está en CAP-084 sin
  FR propio); un token para algo inocuo es fricción aceptada a cambio de no
  crear una tool sin requisito (principio IX).
- **M7** — `adopt_data_disk` y `rename_data_disk` se rechazan aunque FR-077
  hable de «aplicar una sugerencia»: equivalen a mover el disco de datos,
  clase D en la 008 (`/os/datadisk/move`).
- **M8** — Las duraciones de la vista previa («1–5 minutes», «30–90 seconds»)
  son orientativas y salen del código, no de una medida; se contrastan en la
  VM.
- **M9** — Conflictos de integración previsibles con la 015, la 019 y la 030
  en `tool_families.py`, `command_table.py`, `tools/__init__.py`, `guide.py`,
  el CHANGELOG y los recuentos del README (líneas, no diseño).
- **M10** — Prueba en vivo pendiente (VM de la 014), con sus filas en la
  matriz y sus líneas en las tandas.
- **M11** — Ninguna tool nueva es de Core: el banco de Core no aplica (las 8
  van a `FUERA_DEL_BANCO`).
