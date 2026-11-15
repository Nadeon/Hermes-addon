# Checklist de calidad de la especificación: diagnóstico de Core (012)

**Propósito**: validar que la especificación está completa y tiene calidad antes de planificar
**Creado**: 2026-11-14
**Especificación**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación más allá de los que fija la 008 (nombres de tools, familia, comandos de HA que ya existen)
- [x] Centrada en el valor para el usuario (diagnosticar, validar, depurar, ordenar)
- [x] Escrita para quien mantiene Hermes
- [x] Todas las secciones obligatorias completas

## Completitud de los requisitos

- [x] No quedan marcadores [NEEDS CLARIFICATION]
- [x] Los requisitos se pueden probar y no son ambiguos
- [x] Los criterios de éxito son medibles
- [x] Los criterios de éxito no dependen de la tecnología (salvo nombres de tools y familia, que son el contrato)
- [x] Todos los escenarios de aceptación están definidos
- [x] Los casos límite están identificados
- [x] El alcance está delimitado (029, 013 y 017 fuera, dicho)
- [x] Dependencias y supuestos identificados (S-01…S-04)

## Preparación de la funcionalidad

- [x] Todos los requisitos funcionales tienen criterios de aceptación claros
- [x] Los escenarios de usuario cubren los flujos principales
- [x] La funcionalidad cumple los resultados medibles de los criterios de éxito
- [x] Trazabilidad: cada FR cita el FR de la 008 y la CAP que cubre

## Notas

- Decisiones tomadas sin el mantenedor (en «Clarificaciones» de la spec y en
  research.md): `ha_get_error_log` sin caída al journal; `logger/log_level` es
  escritura y lo usa `ha_set_log_level`; nivel anterior `null` para módulos;
  persistencia `none` por defecto; descarte de una sola notificación por la
  acción de HA; diagnósticos sin información del sistema por defecto y con
  `keys`; dueña del dispositivo por `config_entry_id`; `config` entera en
  `ha_validate_config`; una sola familia `core_diagnostics`; textos de
  terceros marcados.

## Dudas para el final (para el mantenedor)

- **D-1**: En HA OS, `/api/error_log` da 404 salvo con `duplicate_log_file`
  (research R-2), así que `ha_get_error_log` casi siempre devolverá
  `error_log_unavailable`. ¿Debe caer a la tool de logs de Core de la 013
  cuando exista, o basta con remitir a ella? Hoy: remite.
- **D-2**: El inventario de la 008 agrupa `logger/log_level` con las lecturas
  de CAP-041 y su research decía «leer niveles»; en Core es escritura. No
  cambia la clasificación (pasa a `dedicated`), pero conviene corregir la nota
  del inventario si se regenera.
- **D-3**: `logger.set_default_level` (nivel por defecto de todo HA) no está en
  la denylist ni en ninguna CAP: por `ha_call_service` se ejecuta sin token,
  aunque oculta rastro igual que `logger.set_level`. Fuera del alcance de la
  012; anotado para quien revise la denylist (018 o cierre).

## Resultado de `/speckit-analyze` (2026-11-14)

Cobertura: 22 FR, 22 con tareas (100 %); 34 tareas, todas trazadas a FR, SC
o cierre de tramo; 7 SC, todos con tarea. Constitución: sin conflictos (tabla
principio a principio en plan.md). Sin hallazgos CRITICAL ni HIGH.

Corregidos al analizar (MEDIUM):

- FR-022 (privacidad) no aparecía en ninguna tarea → citado en T019 y T034.
- SC-001, SC-004, SC-006 y SC-007 sin tarea explícita → citados en T012/T026,
  T009/T024 y T019/T034.
- `ha_clear_system_log` sin caso para `system_log` no cargado en la vista
  previa → `system_log_unavailable` sin token en T010.
- La prueba de nivel por módulo en el banco no decía qué comprobar → logger
  `homeassistant.components.input_boolean` y `logger/log_info` en T015.

Anotados, sin cambio (MEDIUM/LOW):

- **M-1**: el token de `ha_clear_system_log` no se ata al contenido del log
  (no tiene argumentos); lo que entre entre la vista previa y la confirmación
  también se borra. La vista previa lo dice (principio IV: no omite efectos).
- **M-2**: `ha_get_error_log` dará casi siempre `error_log_unavailable` en HA
  OS (D-1); dicho en la descripción, el error y la guía.
- **M-3**: el camino feliz de `ha_get_device_diagnostics` no se puede probar en
  el banco (S-03); queda en unitarios y en la matriz de la 014.
- **L-1**: `_request_json` carga el diagnóstico entero antes de recortarlo;
  acotado por el tope de HA y el tiempo de 30 s (riesgo en plan.md).
- **L-2**: nota del inventario de `logger/log_level` (D-2) y
  `logger.set_default_level` fuera de la denylist (D-3).
