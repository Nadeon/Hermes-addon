# Checklist de calidad de la especificación: Hermes 1.1.0 — diagnóstico y organización

**Propósito**: validar que la especificación está completa y tiene calidad antes de planificar
**Creado**: 2026-11-14
**Especificación**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación (lenguajes, frameworks, APIs)
- [x] Centrada en el valor para el usuario y en las necesidades del negocio
- [x] Escrita para personas no técnicas
- [x] Todas las secciones obligatorias completas

## Completitud de los requisitos

- [x] No quedan marcadores [NEEDS CLARIFICATION]
- [x] Los requisitos se pueden probar y no son ambiguos
- [x] Los criterios de éxito son medibles
- [x] Los criterios de éxito no dependen de la tecnología
- [x] Todos los escenarios de aceptación están definidos
- [x] Los casos límite están identificados
- [x] El alcance está delimitado
- [x] Dependencias y supuestos identificados

## Preparación de la funcionalidad

- [x] Todos los requisitos funcionales tienen criterios de aceptación claros
- [x] Los escenarios de usuario cubren los flujos principales
- [x] La funcionalidad cumple los resultados medibles de los criterios de éxito
- [x] No se filtran detalles de implementación en la especificación

## Seguridad y constitución (específico de esta spec)

- [x] Toda tool que borra, edita un registro, ignora un aviso o descarta algo del Supervisor exige `confirmation_token` (principio IV)
- [x] Las vistas previas de borrado tienen un camino fail-closed explícito (`preview_unavailable`) (principios III y IV)
- [x] La contraseña de cifrado de los backups de HA nunca sale, y se garantiza por lista blanca, no por lista negra (principios I y II)
- [x] La retención define la identificación inequívoca y cada motivo de exclusión (decisión 9, principio III)
- [x] La única desviación del principio IV (poda sin token) está justificada en plan.md
- [x] Aplicar sugerencias del Supervisor queda fuera y lo vigila un test (FR-024)
- [x] Cada tool nueva tiene test previo y control negativo (FR-043)
- [x] Ningún ejemplo contiene datos de una instalación real (principio VIII)

## Notas

- Iteración 1 de validación, 2026-11-14: todos los puntos pasan.
- «Sin detalles de implementación» se da por cumplido con la misma salvedad
  que la spec 001: Hermes es un servidor de tools para un cliente MCP, así que
  los nombres de las tools, de sus parámetros y de los campos de respuesta
  (`preview_unavailable`, `password_set`, `ha_version_unsupported`) **son** la
  interfaz que ve el usuario. Los comandos concretos de Home Assistant y del
  Supervisor, los ficheros y el algoritmo de la retención están en plan.md,
  research.md y data-model.md.
- Algunos criterios (SC-002…SC-008) se miden con la suite de tests, porque el
  «usuario» es un cliente automático; se expresan en efectos observables (qué
  anuncia la vista previa, qué se borra, qué no sale en la respuesta).
- Las ambigüedades se resolvieron con las decisiones del mantenedor y con los
  supuestos S-01 a S-16; no se ejecutó `/speckit-clarify` con preguntas porque
  el mantenedor estaba ausente.
