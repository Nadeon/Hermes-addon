# Lista de calidad de la especificación: estado del sistema y estadísticas de Core (029)

**Propósito**: validar que la spec está completa antes de planificar
**Creada**: 2026-11-14
**Spec**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación en la spec más allá de los nombres de
  tools y comandos, que son el contrato del programa (como en la 008 y la 012)
- [x] Centrada en el valor para el administrador
- [x] Secciones obligatorias completas

## Requisitos

- [x] Ningún marcador [NEEDS CLARIFICATION]: las decisiones se tomaron con la
  008 y el código de HA y están en Clarificaciones y research
- [x] Requisitos comprobables y sin ambigüedad (cada FR con su test en el plan)
- [x] Criterios de éxito medibles
- [x] Escenarios de aceptación por historia
- [x] Casos límite identificados
- [x] Alcance delimitado: 012, 020, 021, 013 y `dismiss_system_state` fuera,
  dicho
- [x] Dependencias y supuestos: 009, 010, 011 completas; relación con la 012

## Preparación

- [x] Cada FR traza a un FR y una CAP de la 008 (tabla de trazabilidad del
  plan)
- [x] Las historias cubren los flujos principales (salud, arranque y
  manifiestos, estadísticas, auditoría y red, compatibilidad)
- [x] Tramos con tareas TDD y controles negativos

## Resultado de analyze (2026-11-14)

Corregido en los artefactos (CRITICAL/HIGH):

- **A1 (HIGH, cobertura)**: FR-016 no tenía la tarea de los rechazos de la
  genérica para los comandos de CAP-049; T023 añadida a la trazabilidad.
- **A2 (HIGH, coherencia)**: la frase de la guía sobre cambiar red y HTTP
  difería entre spec y tareas; unificada («Hermes aún no tiene tool para
  cambiarlos; la 021 actualizará el texto»).
- **A9 (HIGH, principio V)**: FR-020 traducía todo `unknown_command` que no
  fuera del recorder a `unsupported_by_ha_version`, pero `system_health/info`
  tampoco existe si la integración no está cargada: la respuesta mentiría.
  Añadido `system_health_not_loaded` (spec FR-020, research R-5, data-model,
  T006 y T008).

Anotado, menor (no bloquea):

- **A3 (MEDIUM)**: `ha_validate_statistics` hereda el plazo de 30 s de
  `ws_send`; en una base muy grande podría no bastar. Se deja así (igual que
  el resto de lecturas); si el banco o una prueba en vivo lo muestran, se
  ajusta.
- **A4 (MEDIUM)**: research R-2 de la 008 nombraba una sola tool para
  `manifest/list|get`; aquí son dos (research R-3). Cuando se actualice la
  matriz de la 008 (T033), la fila de CAP-043 lleva los nombres definitivos.
- **A5 (LOW)**: la estimación de la 008 era «~7» tools; son ocho. Dentro del
  tamaño M y de dos tramos.
- **A6 (LOW)**: el banco quizá no grabe `call_service` o no cargue `network:`
  sin red; previsto en T030 y en los supuestos.
- **A7 (LOW)**: la línea base de la suite cambiará al integrar 009, 010 y la
  011 completa; T001 la vuelve a tomar.
- **A8 (LOW)**: el motivo de `logbook/get_action_calls` de la 011 decía que
  la respuesta se redactaba sin tapar `code`: hallazgo de la 029, corregido en
  su tramo 2 (FR-012), no un fallo de esta spec.
