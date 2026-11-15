# Lista de calidad de la especificación: integraciones específicas por la tabla (025)

**Propósito**: validar que la spec está completa antes de planificar
**Creada**: 2026-11-15
**Spec**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación que no sean el contrato con el cliente
  MCP (la tabla, las genéricas y la guía son el producto)
- [x] Centrada en el valor para el usuario (qué puede y qué no puede hacer
  el cliente con cada integración)
- [x] Secciones obligatorias completas

## Requisitos

- [x] Sin marcadores [NEEDS CLARIFICATION] (decididas con la 008 y el código
  de HA; ver «Clarificaciones»)
- [x] Requisitos verificables y sin ambigüedad (la clasificación exacta está
  en research.md R-1)
- [x] Criterios de éxito medibles (recuentos, centinelas, filas comparadas)
- [x] Escenarios de aceptación por historia
- [x] Casos límite identificados
- [x] Alcance acotado (solo clase C, sin tools)
- [x] Dependencias y supuestos identificados

## Preparación

- [x] Cada FR traza a su FR y CAP de la 008 (plan.md, «Trazabilidad»)
- [x] Tareas en TDD con controles negativos y partidas en tramos

## Notas

- La 008 estimaba 2 tramos; salen 3 (research.md R-9).
- Desviaciones de las notas de CAP de la 008, justificadas en research.md R-3.

## Resultado de analyze (2026-11-15)

17 FR, 7 SC, 46 tareas; cobertura de FR con tareas: 100 %. Sin CRITICAL.

| ID | Categoría | Severidad | Dónde | Hallazgo | Estado |
|---|---|---|---|---|---|
| U1 | Constitución (II) | HIGH | research R-1, `mqtt/device/debug_info` | El handler devuelve el `payload` de descubrimiento (objeto con `code` en alarmas y cerraduras) y los mensajes enviados (texto con el código dentro, que `redact_secrets` no reconoce) | Corregido: `redact_extra=("code", "transmitted")`, centinela en T032 y control negativo en T035; FR-005, SC-002 (siete entradas), R-6 |
| U2 | Constitución (II) | HIGH | research R-5 | `redact_extra` no tapaba objetos (clave de red de ZHA dentro de `network_key`) | Corregido en el diseño: FR-008, T002–T003 |
| C1 | Cobertura | MEDIUM | T040 | Añadir `usb:` al banco puede cambiar el arranque o los avisos de los demás tests del banco | Corregido: T040 comprueba el resto del banco |
| C2 | Cobertura | MEDIUM | T043 | La tabla de sub-features de la 008 dice 2 tramos para la 025 | Corregido: T043 la actualiza (y el total de tramos) |
| I1 | Inconsistencia | MEDIUM | quickstart | Decía que la prueba con hardware iba a la matriz de la 014, que solo tiene filas por tool que modifica | Corregido: va a «Pruebas manuales pendientes» (FR-017, T043) |
| I2 | Inconsistencia | LOW | plan, diseño 3 | Faltaba `test_esperado_completo`, que sí está en T006 | Corregido |
| A1 | Ambigüedad | LOW | `zwave_js/network_neighbors` | Puede pasar del plazo de 30 s de `ws_send` | Anotado en R-1; la guía lo avisa (T014) |
| R1 | Riesgo | LOW | T020 | Sin el código de zigpy, la forma de `stack_specific` se supone | Se tapa la clave de arriba entera; no depende del interior (plan, «Riesgos») |
| D1 | Duda | LOW | spec, D-1…D-3 | Marca «cerrar tras el resultado», corrección global de `redact_structure`, tools dedicadas de Z-Wave | Dudas para el final |

Menores sin cambio: FR-007 resume las reglas que FR-001…FR-006 aplican (se
deja: uno da las reglas, los otros los recuentos y la tabla exacta).
