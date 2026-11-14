# Lista de calidad de la especificación: mejoras de tools existentes (018)

**Propósito**: validar que la spec está completa y es de calidad antes de planificar
**Creada**: 2026-11-14
**Spec**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación innecesarios (los nombres de tools y
      argumentos son el contrato que ve el usuario de Hermes, no implementación)
- [x] Centrada en el valor para el usuario (no perder tarjetas, obtener la
      respuesta de una acción confirmada, listas predecibles)
- [x] Comprensible para quien administra Home Assistant
- [x] Secciones obligatorias completas

## Completitud de los requisitos

- [x] No quedan marcadores [NEEDS CLARIFICATION] (decisiones en Clarificaciones
      y research R-1…R-4; lo que no se puede decidir sin el mantenedor está en
      «Dudas para el final»)
- [x] Requisitos verificables y sin ambigüedad
- [x] Criterios de éxito medibles
- [x] Criterios de éxito sin tecnología
- [x] Escenarios de aceptación definidos para las tres historias
- [x] Casos límite identificados
- [x] Alcance acotado (Fuera de alcance)
- [x] Dependencias y supuestos identificados (011, banco de la 010, 023)

## Preparación

- [x] Todo FR tiene criterio de aceptación (escenarios y tareas de test)
- [x] Las historias cubren los flujos principales
- [x] Cumple los resultados medibles de los criterios de éxito
- [x] Sin detalles de implementación que se filtren a la spec más allá del
      contrato de las tools

## Notas

- Validación: una iteración, sin fallos.
- Hallazgos menores de `analyze` (ver al final de este fichero, sección
  «Analyze»).

## Analyze

`/speckit-analyze` sobre spec, plan y tasks (2026-11-14). 19 FR, 7 SC, 26
tareas; cobertura de FR 100 % (cada FR con al menos una tarea, ver la tabla de
trazabilidad del plan); constitución sin conflictos.

Corregidos (CRITICAL y HIGH):

- **A1 (CRITICAL, constitución III y FR-020 de la 008)**: el plan ponía `view`
  en la misma tupla de omitibles que `config`. `resolve_confirmation_token`
  rechaza una confirmación a la que le falta un omitible no guardado, así que
  toda confirmación completa de la 1.1.2 (sin `view`) habría fallado con «has
  no stored value for: view». Corregido: tupla propia `_OMITIBLES_VISTA` solo
  en el modo por vista (plan, data-model, research, T008) y control negativo
  (e) en T011 con los tests existentes de `TestConfirmarSoloConTokenLovelace`.
- **A2 (HIGH, inconsistencia)**: la spec mandaba un `view_index` no entero a
  `view_index_out_of_range` y el contrato a `invalid_argument`. Unificado en
  `invalid_argument` (spec, T004).
- **A3 (HIGH, ambigüedad)**: FR-005 decía «antes de leer» e incluía
  `preview_unavailable`, que solo puede ocurrir tras intentar leer.
  Reformulado.

Menores (anotados, sin cambiar):

- **A4 (MEDIUM, alcance)**: FR-008 extiende la confirmación a
  `entity_restricted`, que FR-064 de la 008 no nombra; se justifica con «la
  misma vista previa que `ha_call_service`» (research R-3). Si el supervisor lo
  quiere estricto, basta con quitar ese caso de T014 y T017.
- **A5 (MEDIUM, dependencia externa)**: el test del banco (T010, T022) no se
  puede ejecutar hasta integrar la 010 en la rama, y puede necesitar un método
  público nuevo en el lector; el mismo patrón que la T027 de la 011.
- **A6 (LOW, terminología)**: «huella», `state_hash` y `estado` nombran lo
  mismo en distintos niveles (texto, fichero del token, argumento); se deja así
  porque cada uno es el nombre en su capa.
- **A7 (LOW, riesgo de integración)**: el test transversal del sobre (T019)
  señalará las tools de lista de sub-features implementadas antes de integrar
  la 018 (research R-4).
- **A8 (LOW)**: research R-0 citaba la clase `TestDestructiveToolsTakeToken`;
  el nombre real es `TestDestructiveToolsAskBeforeActing`. Corregido.
