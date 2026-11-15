# Checklist de calidad de la especificación: diagnóstico del Supervisor (013)

**Propósito**: validar que la especificación está completa y tiene calidad antes de planificar
**Creado**: 2026-11-14
**Especificación**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación más allá de los que fija la 008 y la 011 (nombres de tools, rutas del Supervisor, módulos y tabla que ya existen)
- [x] Centrada en el valor para el usuario (diagnosticar el sistema sin SSH)
- [x] Escrita para quien mantiene Hermes
- [x] Todas las secciones obligatorias completas

## Completitud de los requisitos

- [x] No quedan marcadores [NEEDS CLARIFICATION] (las decisiones están en «Clarificaciones» y en research.md)
- [x] Los requisitos se pueden probar y no son ambiguos
- [x] Los criterios de éxito son medibles
- [x] Los criterios de éxito no dependen de la tecnología (salvo nombres de tools, rutas y familia, que son el contrato)
- [x] Todos los escenarios de aceptación están definidos
- [x] Los casos límite están identificados
- [x] El alcance está delimitado (solo lectura; la escritura es de la 022 y la 032)
- [x] Dependencias y supuestos identificados (009, 011 completa; prueba en vivo pendiente)

## Preparación de la funcionalidad

- [x] Todos los requisitos funcionales tienen criterios de aceptación claros
- [x] Los escenarios de usuario cubren los flujos principales
- [x] La funcionalidad cumple los resultados medibles de los criterios de éxito
- [x] Trazabilidad: cada FR cita el FR de la 008 y la CAP que cubre

## Resultado de `analyze` (2026-11-14)

25 FR, 7 SC, 28 tareas en 2 tramos; cobertura de FR con tareas: 100 %.
Sin marcadores ni datos personales.

Corregido (CRITICAL/HIGH):

- **A1 (HIGH)** — Orden del tramo 1: T010 (tabla a `dedicated`) necesitaba el
  registro de T011 para que `TestDedicadas` encontrase las tools. Se reordenan
  las dependencias (T011 antes de T009/T010).
- **A2 (HIGH)** — FR-022 decía «la única diferencia de esquema» y la 011 ya
  permite otra (`search` en `hermes_guide`). Reescrito como «la única que añade
  esta sub-feature».
- **A3 (HIGH)** — Las entradas que pasan a `dedicated` son clase A del
  inventario: `test_a_y_c_con_su_cap` exige que conserven su CAP. data-model y
  T010/T022 lo dicen.
- **A4 (HIGH, principio I)** — Las respuestas JSON de `/os/*`, servicios,
  arranques, identificadores y disco se devolvían «tal cual». Ahora pasan por
  `redact_structure` (FR-016, T016, T019), con un centinela en el test.

Anotado (MEDIUM/LOW):

- **M1** — Desviación de FR-047 de la 008: `POST /security/integrity` queda
  `deny` porque el Supervisor 2026.11.0 la eliminó (410 Gone). Se anota en la
  matriz y en el CHANGELOG (T026).
- **M2** — `/jobs/info` va por la tabla (FR-046 de la 008) aunque el research
  de la 008 nombraba `sv_list_jobs` y la 011 lo dejó «pendiente (spec 013)».
- **M3** — `GET /host/disks` va por la tabla como lectura menor de CAP-085; la
  regla de la 008 lo permite si la sub-spec lo justifica (research R-5).
- **M4** — Prueba en vivo pendiente (014 o cierre), con casilla en la hoja de
  ruta (T026).
- **M5** — Sin journal, el Supervisor devuelve el log de su contenedor sin
  `boot`/`latest`; Hermes no lo detecta y lo dice la descripción.
- **M6** — El alfabeto de `identifier` puede dejar fuera algún identificador
  raro (con `:` o espacios); limitación aceptada por seguridad de ruta.
- **M7** — Conflictos de fusión previsibles con la 012 y la 029 (misma ola) en
  `tools/__init__.py`, `guide.py`, `tool_families.py`, `command_table.py`,
  `tests/test_command_table.py` y el CHANGELOG. El recuento de tools del README
  depende del orden de integración (T026 usa el del registro).
- **M8** — No se usa el alias `logs` en la guía para no chocar con el log de
  Core de la 012.
- **M9** — La rama tiene solo el tramo 1 de la 011; la implementación espera a
  la 011 completa (S-01).
