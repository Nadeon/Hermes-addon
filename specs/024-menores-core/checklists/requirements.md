# Checklist de calidad de la especificación: menores de Core (024)

**Propósito**: validar que la especificación está completa y tiene calidad antes de planificar
**Creado**: 2026-11-15
**Especificación**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación más allá de los que fijan la 008 y la 011 (nombres de tools, comandos, rutas REST, módulos y tabla)
- [x] Centrada en el valor para el usuario (ver una cámara, restablecer un dashboard, lo menor de Core sin la interfaz)
- [x] Escrita para quien mantiene Hermes
- [x] Todas las secciones obligatorias completas

## Completitud de los requisitos

- [x] No quedan marcadores [NEEDS CLARIFICATION] (decisiones en «Clarificaciones» y research.md)
- [x] Los requisitos se pueden probar y no son ambiguos
- [x] Los criterios de éxito son medibles
- [x] Todos los escenarios de aceptación están definidos
- [x] Los casos límite están identificados
- [x] El alcance está delimitado (sin vídeo, sin subir imágenes, sin escribir credenciales, sin tools para lo que va por la tabla)
- [x] Dependencias y supuestos identificados (base en `1752984`; banco sin red)

## Preparación de la funcionalidad

- [x] Todos los requisitos funcionales tienen criterios de aceptación claros
- [x] Los escenarios de usuario cubren los flujos principales
- [x] Trazabilidad: cada FR cita el FR de la 008 y la CAP que cubre

## Resultado de `analyze` (2026-11-15)

20 FR, 6 SC, 31 tareas en 2 tramos (T001–T015 y T016–T031); cobertura de FR
con tareas: 100 %. Sin marcadores ni datos personales. Constitución: sin
conflictos. Comandos comprobados en `fuentes/core` y en `core-ws.tsv`:
ninguno con `hassio/` ni `supervisor/`; los que salen a internet llevan
`open_world`; la clase D sigue `deny`.

Corregido (CRITICAL/HIGH):

- **A1 (HIGH)** — Las anotaciones de `ha_reset_lovelace_dashboard_config`
  eran ambiguas («no idempotente en el sentido de…» en la spec y «como
  decida» en el contrato): se fija `-DI-`, como
  `ha_delete_lovelace_dashboard` (`tests/test_tools_registration.py`), en
  spec, research y contrato.

Corregido (MEDIUM):

- **A2** — El plan decía 15 entradas fijadas en el tramo 1; son 17 (CAP-059
  2, CAP-065 3, CAP-066 4, CAP-067 4, CAP-072 4).
- **A3** — La trazabilidad del plan no citaba T012, T017, T021, T027 ni
  T028: añadidas.

Anotado (LOW):

- **A4** — SC-003 cuenta 33 entradas en `1752984`; si otra sub-feature
  añade entradas con estas CAP antes de implementar, el tramo 2 ajusta el
  número y lo anota.
- **A5** — `height=⌈max_width·9/16⌉` supone 16:9; con otra proporción Core
  devuelve algo mayor (nunca menor). Está dicho en la descripción («puede ser
  mayor»).
- **A6** — La viabilidad en el banco de `local_file`, `image_upload`,
  `application_credentials` y el `vacuum` de plantilla sin red es un
  supuesto; si alguno no arranca, unitarios y nota (T011, T026).

Hallazgos sobre lo ya integrado (se arreglan en esta sub-feature):

- **H1** — `media_source/browse_media` y `search_media` (`read` desde la
  011) pueden devolver miniaturas firmadas (`authSig`, 5 min) de la fuente de
  motionEye: se tapan con `redact_extra=("thumbnail",)` (research R-6, T009).
- **H2** — El motivo de `application_credentials/config_entry` promete el id
  de la credencial, que la redacción general tapa (la clave contiene
  `credential`): el motivo pasa a decirlo (research R-7, T024).

## Dudas para el final

- **D-03 de la 008**: la familia `cameras` queda activa por defecto, como
  manda FR-010; desactivarla por defecto lo decide el mantenedor.
- Las miniaturas se tapan todas en `browse_media`/`search_media`, no solo
  las firmadas; si se quiere conservar las no firmadas, haría falta una
  redacción por valor (`authSig=`) en las genéricas, fuera del alcance de la
  024.
