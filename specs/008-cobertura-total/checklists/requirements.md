# Checklist de calidad de la especificación: Hermes 1.2.0 — cobertura total (paraguas)

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

## Notas

- Iteración 1 de validación, 2026-11-14: todos los puntos pasan.
- Es una spec paraguas: los requisitos por sub-feature fijan el «qué» y cada
  sub-spec (009–032) fija escenarios de aceptación detallados por tool.
- «Sin detalles de implementación» se da por cumplido con la misma salvedad que
  en las specs 001, 006 y 007: Hermes es un servidor de tools para un cliente
  MCP, así que los nombres de tools, categorías de la tabla y códigos de error
  son la interfaz que ve el usuario. El job del CI y el Supervisor simulado se
  nombran porque son decisiones vinculantes del mantenedor.
- No se ejecutó `/speckit-clarify`: las decisiones de fondo son del mantenedor
  y el resto se anotó en «Clarificaciones» y en «Dudas para el final».

## Análisis cruzado (`/speckit-analyze`, 2026-11-14)

Sobre spec.md, plan.md y tasks.md: 98 FR, 12 SC, 29 tareas; cobertura de FR
por tareas del 100 % (los transversales, por el preámbulo de tasks.md y las
tareas de cierre). Sin hallazgos CRITICAL. Corregidos los HIGH:

- H1 (ambigüedad de seguridad, FR-006): «valores cortos no secretos» en la
  vista previa genérica → regla medible (escalares de 64 caracteres o menos con
  clave no sensible; el resto, tapado).
- H2 (criterio no comprobable, SC-005 frente a FR-010): para que «desactivar
  lo nuevo deja la lista de la 1.1.2» sea verificable, las tools nuevas van en
  familias distintas de las de la 1.1.2; SC-005 compara nombres, no esquemas
  (las tools viejas ganan argumentos opcionales).
- H3 (ambigüedad, FR-004): la lista de verbos de escritura terminaba en «entre
  otros» → la lista es explícita en el test y solo crece.

Anotados, de severidad menor:

- M1: principios IV, V y XI y la puerta 4 del flujo tienen matices que el plan
  justifica por escrito y para los que propone las enmiendas E-1…E-4; no se
  aplican aquí.
- M2: nombres de sub-features distintos de research R-6 (015, 019, 022 y las
  partidas 028–032); el plan explica cada cambio.
- M3: FR-014 y SC-006 dependen de la lista de tools no ejecutables en el banco,
  que fija 010/028; hasta entonces el 100 % no tiene denominador cerrado.
- M4: la prueba de CAP-048 en el banco depende de poder provocar un issue
  reparable en una HA limpia.
- M5: conflictos previsibles en ficheros comunes (`_annotations.py`, guía,
  tabla, CHANGELOG) entre sub-features paralelas; tasks.md fija el orden de
  integración por olas.
- L1: la estimación de tools nuevas (~135 en el plan) es antes de agrupar por
  parámetro; la suma por sub-feature da unas 139.
- L2: cada tarea de tasks.md es una sub-feature entera; el detalle por tool es
  de cada sub-spec, como corresponde a un paraguas.
