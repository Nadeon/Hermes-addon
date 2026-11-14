# Lista de calidad de la especificación: Hermes 1.1.0 — Marketplace de solo lectura

**Propósito**: validar que la especificación está completa y es de calidad antes de planificar.

**Creada**: 2026-11-14

**Funcionalidad**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación (lenguajes, frameworks, APIs)
- [x] Centrada en el valor para el usuario
- [x] Comprensible para quien no programa
- [x] Todas las secciones obligatorias completas

## Completitud de los requisitos

- [x] No quedan marcadores [NEEDS CLARIFICATION]
- [x] Los requisitos se pueden probar y no son ambiguos
- [x] Los criterios de éxito son medibles
- [x] Los criterios de éxito no dependen de la tecnología
- [x] Todos los escenarios de aceptación están definidos
- [x] Los casos límite están identificados
- [x] El alcance está acotado
- [x] Dependencias y supuestos identificados

## Preparada para planificar

- [x] Todos los requisitos funcionales tienen criterio de aceptación
- [x] Las historias cubren los flujos principales
- [x] La funcionalidad cumple los resultados medibles de los criterios de éxito
- [x] No se filtran detalles de implementación en la especificación

## Notas

- Como en la spec 001, los nombres de comandos WebSocket (`marketplace/*`,
  `hacs/*`), de códigos de error y de tools aparecen en la spec a propósito: son
  el contrato que ve el cliente MCP y la frontera de seguridad (qué se envía y
  qué no). No describen cómo se implementa. Los ficheros y las líneas de código
  están solo en plan.md y tasks.md.
- Sin preguntas al mantenedor: las dudas se resolvieron con las decisiones 1 y 5
  y con los supuestos S-01…S-10.
- Dependencia: la 1.0.12 (`specs/001-correcciones-1-0-12/`) debe estar
  implementada antes: `HAConnectionError.code`, `ha_version.py` y los cambios de
  `tools/hacs.py` (001 FR-030, FR-038, FR-039).

## Resultado de `/speckit-analyze` (2026-11-14)

- 31 requisitos (FR-001…FR-031), 9 criterios de éxito, 49 tareas. Todos los FR
  tienen tarea; los de comportamiento, test y control negativo. FR-025…FR-027 y
  FR-029 son documentación: se revisan a mano (T045), sin control negativo.
- Sin violaciones de la constitución ni marcadores pendientes.
- Corregido tras el análisis:
  - MEDIUM (principios III y V): las anotaciones se derivaban del prefijo
    `ha_marketplace_`; una futura tool de escritura con ese prefijo se habría
    anunciado de solo lectura. Ahora van por nombre exacto (FR-018, plan lote B,
    T026, T029, T030).
  - LOW (ambigüedad): FR-017 no enumeraba qué campos son texto de terceros;
    ahora sí (`name`, `description`, `reason` y `name` de las versiones).
