# Lista de calidad de la especificación: estadísticas y energía (020)

**Propósito**: validar que la spec está completa antes de planificar
**Creada**: 2026-11-15
**Spec**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación en la spec más allá de los nombres de
  tools, argumentos y comandos, que son el contrato del programa (como en la
  008, la 012 y la 029)
- [x] Centrada en el valor para el administrador
- [x] Secciones obligatorias completas

## Requisitos

- [x] Ningún marcador [NEEDS CLARIFICATION]: las decisiones se tomaron con la
  008, las del supervisor y el código de HA, y están en Clarificaciones y
  research
- [x] Requisitos comprobables (cada FR con su tarea y su test en el plan)
- [x] Criterios de éxito medibles
- [x] Escenarios de aceptación por historia
- [x] Casos límite identificados
- [x] Alcance delimitado: lecturas de la 1.1.2 y la 029, purga del recorder,
  panel de energía, fuera, dicho
- [x] Dependencias y supuestos: base con la 029 y los inventarios de la 028,
  la 014 y la 033 integrados

## Preparación

- [x] Cada FR traza a un FR y una CAP de la 008 (tabla de trazabilidad del
  plan)
- [x] Las historias cubren los flujos principales (borrar, unidades, sumas,
  importar, energía, compatibilidad)
- [x] Tramos con tareas TDD y controles negativos

## Resultado de analyze (2026-11-15)

Corregido en los artefactos (CRITICAL/HIGH):

- **A1 (HIGH, principio IV)**: con preferencias de energía sin guardar, o al
  importar una estadística nueva, el `estado` podía quedar en `None`, y con
  `None` `create_confirmation_token` no ata nada: alguien podía guardar
  preferencias entre la vista previa y la confirmación sin que el token lo
  notara. FR-007 y FR-012 dicen ahora que el estado nunca es `None`
  (`{"configured": false}`; lista vacía de metadatos); test en T038.
- **A2 (HIGH, principio V)**: `change_statistics_unit` con la misma unidad
  vieja y nueva responde éxito en HA y no hace nada (solo un aviso en su log).
  FR-002, contracts y T004: `invalid_argument`.
- **A3 (HIGH, cobertura)**: añadir `statistics_maintenance` a la familia
  `recorder` rompe tres tests de la 029 que fijan la familia
  (`test_recorder_es_de_la_1_2_0`, `TestRecorderRegistration`,
  `TestCoberturaDeLa029.test_modulos_de_las_familias_de_la_029`) y uno de la
  guía («SOLO LECTURA»). Las tareas no lo decían; T007, T013 y T016 lo dicen
  ahora, con `MODULOS_020`.
- **A4 (HIGH, trazabilidad)**: FR-022 apuntaba a T035 (cierre) en vez de a
  T034 (documentación); corregido en el plan.

Anotado, menor (no bloquea):

- **A5 (MEDIUM)**: FR-017 dice que las listas de las vistas previas se
  recortan con `truncated`, pero ninguna tarea lo prueba con una vista previa
  grande (100 estadísticas, energía con muchos dispositivos). Las vistas
  previas de la 020 son pequeñas por construcción (100 ids como mucho); si el
  implementador ve que alguna puede pasar del tope, añade el test en su tramo.
- **A6 (MEDIUM)**: tres tramos en vez de los dos de la 008 (D-2). Justificado
  en el plan; no cambia el alcance.
- **A7 (LOW)**: `recorded_entity_warning` de la importación está en research,
  data-model y T022, pero no en el texto de FR-006 (que enumera lo mínimo de
  cada vista previa). Es un aviso adicional, no un requisito distinto.
- **A8 (LOW)**: la versión de HA en la que aparecieron el rango de
  `clear_statistics` y `unit_class` en `update_statistics_metadata` no se puede
  fijar con el código leído; una HA más antigua responde `invalid_format`, que
  la tool devuelve redactado con `ha_code` y `table_ha_core` (caso límite).
- **A9 (LOW)**: la 008 estimaba «~7» tools; son siete.
