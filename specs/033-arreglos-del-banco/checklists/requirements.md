# Lista de calidad de la especificación: 033 — arreglos de tools existentes destapados por el banco

**Propósito**: validar que la spec está completa antes de implementar
**Creada**: 2026-11-14
**Spec**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Centrada en lo que nota el usuario (lo que se confirma es lo que se vio, tools que dicen la verdad, nada que funcione se rompe)
- [x] Los detalles de implementación están en el plan, research y contratos; la spec nombra tools, argumentos y códigos de error porque son la interfaz pública de Hermes (como las specs 003–009)
- [x] Todas las secciones obligatorias completas

## Completitud de los requisitos

- [x] Sin marcadores [NEEDS CLARIFICATION]: las decisiones del supervisor y las tomadas al especificar están en «Clarificaciones», con su base en el código de HA (research)
- [x] Requisitos comprobables (códigos de error, argumentos atados, esquemas exactos, efecto en el banco)
- [x] Criterios de éxito medibles (SC-001…SC-006)
- [x] Escenarios de aceptación por historia y casos límite
- [x] Alcance acotado («Fuera de alcance») y supuestos (S-01…S-04)

## Trazabilidad con la 008

- [x] La 033 entra en la 008 en el mismo cambio: FR-099 y excepciones a FR-020/SC-005 en `spec.md`; CAP-039 en `research.md`; fila 033 del desglose, nota de cambios y fila CAP-039 de la matriz en `plan.md`; tarea T030 en `tasks.md`; fila 033 en `docs/HOJA-DE-RUTA.md`
- [x] Cada FR de la 033 cita FR-099 y CAP-039, y los transversales que aplican (FR-014, FR-018, FR-020, FR-022, FR-023, FR-096)
- [x] Ni más ni menos: los siete fallos del encargo; la auditoría de tokens no encontró más (research R-1)

## Preparación

- [x] Plan con la comprobación contra la constitución, principio por principio, y la desviación de FR-020 justificada
- [x] Tareas en TDD con controles negativos, en dos tramos commiteables por separado (1: T001–T011, seguridad; 2: T012–T036, el resto)
- [x] Ninguna tool nueva: la tabla de clasificación y las familias no cambian (no hay entradas que pasar a `dedicated`)

## Resultado de `speckit-analyze` (2026-11-14)

Requisitos: 13 FR y 6 SC. Tareas: 36. Cobertura: 13/13 FR y 6/6 SC con al
menos una tarea (tabla de trazabilidad de tasks.md). Sin hallazgos CRITICAL.
Los HIGH y MEDIUM se corrigieron en los documentos:

| ID | Severidad | Hallazgo | Estado |
|---|---|---|---|
| A1 | HIGH | El plan movía `ctx` al final de la firma con valor por defecto; los tests actuales llaman a la función con `None` como primer argumento y se habrían roto (FR-020) | Corregido: `ctx: Context` en la misma posición (plan, research R-3, T019) |
| A2 | HIGH | Cambiar la anotación de `ha_create_scene_from_current` en T022 y actualizar `_HINTS_SNAPSHOT` en T032 dejaba la suite en rojo entre medias | Corregido: la línea de la instantánea va en T022 |
| A3 | MEDIUM | La respuesta de éxito de `ha_create_scene_from_current` dejaba de incluir la de HA de la 1.1.2 | Corregido: se conserva entera en `ha_response` (contracts) |
| A4 | MEDIUM | El inventario de argumentos atados (FR-003) chocará con sub-features que añadan tokens en paralelo (018, FR-064 de la 008) | Previsto en Riesgos del plan: es el comportamiento buscado; quien se integre después añade su entrada |
| A5 | MEDIUM | El control negativo del test del banco del tramo 1 no se puede hacer en local | Corregido: T009 lo hace con un commit temporal en el CI o lo deja anotado; el arreglo queda cubierto por T005 |

Menores, anotados y no bloqueantes:

| ID | Severidad | Hallazgo | Estado |
|---|---|---|---|
| L1 | LOW | Research R-1 contaba «11» tools de helpers con `collection_update_flow` sin que cuadrase | Corregido: sin número |
| L2 | LOW | Una escena de `configuration.yaml` sin `id` no se distingue de una temporal por su estado | Supuesto S-03; la comprobación posterior (`scene_not_created`) lo dice |
| L3 | LOW | `ha_set_counter_value` con un valor no múltiplo del `step` sigue dando el 500 de HA | Fuera de alcance; duda para el final |
| L4 | LOW | Si la 011 no está integrada al implementar, la excepción de esquemas no tiene test donde escribirse | S-01 y T032: se escribe al integrar la 011 |
| L5 | LOW | `ha_get_config_entry_options` se deprecia por analogía con `ha_reload_counters`; el encargo solo pedía que fuera honesta | Decisión anotada en research R-6; duda para el final |

## Notas

- Dudas para el final: L3, L5, y si `name` en `ha_create_scene_from_current`
  debe dar error (decisión tomada) o ignorarse con un aviso.
