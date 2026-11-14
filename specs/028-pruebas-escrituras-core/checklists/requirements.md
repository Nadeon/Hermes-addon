# Lista de calidad de la especificación: pruebas de las escrituras de Core en el banco (spec 028)

**Propósito**: validar que la spec está completa antes de planificar e implementar
**Creada**: 2026-11-14
**Spec**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación innecesarios. Nota: como en la 010, los
  FR nombran ficheros, integraciones de Core y tools porque el banco es
  infraestructura de pruebas y la 008 fija el alcance por tools (FR-014).
- [x] Centrada en el valor para el mantenedor (saber qué está probado de
  verdad, historia 5 de la 008)
- [x] Secciones obligatorias completas

## Completitud de los requisitos

- [x] Sin marcadores [NEEDS CLARIFICATION]: las decisiones se tomaron con la
  008 y el encargo del supervisor, y están en «Clarificaciones»
- [x] Requisitos verificables: cada FR tiene tareas con test o comprobación
- [x] Criterios de éxito medibles (53 de 53, 124 de 124, 0 saltos, 0 líneas,
  minutos)
- [x] Escenarios de aceptación definidos para las cuatro historias
- [x] Casos límite identificados (recursos compartidos, recargas, una sola
  instancia, servicios peligrosos, URLs externas, esperas)
- [x] Alcance acotado (fuera: 010, 014, `fs_*`, `sv_*`, arreglos no triviales)
- [x] Dependencias y supuestos identificados (S-01…S-04; 009, 010, 011, 014)
- [x] Cada FR traza a un FR o CAP de la 008 (o al encargo del supervisor)

## Preparación

- [x] Cada FR tiene criterio de aceptación (tabla de cobertura abajo)
- [x] Las historias cubren los flujos principales (tramo A, tramo B,
  invariante, hallazgos)
- [x] Comprobación de la constitución en plan.md, con tres desviaciones
  justificadas (XI → E-4, puerta 4 → E-3, ambas de la 011; y el commit de
  control negativo en rojo, acotado)

## Resultado de `analyze` (2026-11-14)

Cobertura: 12 FR, 6 SC, 29 tareas (16 en el tramo A, 13 en el B); 100 % de
los FR con al menos una tarea.

| FR | Tareas |
|---|---|
| FR-001 | T009, T010, T011, T012, T018, T019, T020, T023 |
| FR-002 | T009–T011 (tramo A), T018–T020 (tramo B) |
| FR-003 | T006, T007, T021 |
| FR-004 | T006, T007 |
| FR-005 | T002, T017 |
| FR-006 | T016, T028 |
| FR-007 | T013, T024 |
| FR-008 | T009, T010, T011, T018, T019, T020 |
| FR-009 | T005, T008, T014, T022, T025 |
| FR-010 | T015, T026, T027 |
| FR-011 | T003, T016, T028 |
| FR-012 | T012, T023 |

| SC | Tareas |
|---|---|
| SC-001 | T012, T023 |
| SC-002 | T007, T021 |
| SC-003 | T016, T028 |
| SC-004 | T016, T028 |
| SC-005 | T012, T023 |
| SC-006 | T016, T029 |

Hallazgos corregidos en los artefactos:

| ID | Severidad | Hallazgo | Corrección |
|---|---|---|---|
| D1 | CRITICAL | El control negativo de CI empuja a propósito un commit que pone el banco en rojo; choca con «la suite completa debe pasar antes de cada commit que se vaya a publicar» (VII y puerta 3) y el plan lo daba por «OK» | Fila nueva en la comprobación de la constitución: desviación acotada (rama desechable que se borra; solo si el encargo lo impide, commit y `git revert`; nunca en la punta ni en un PR). Research R-12, T014 y T025 alineados |
| A1 | HIGH | «Arreglo trivial» era vago («unas pocas líneas») y decide si se toca `hermes/src/` (SC-003) | Spec, «Clarificaciones»: como mucho 10 líneas de `hermes/src/` en una sola tool, sin cambiar firma, anotaciones, descripción, confirmación ni denylist |
| I1 | MEDIUM | S-02 (spec) decía «`xfail` o no ejecutables» si `kitchen_sink` no carga; el plan, solo `xfail` | Spec S-02 y tabla del plan: no carga → no ejecutables con motivo y aviso; carga y la tool falla → hallazgo |
| I2 | MEDIUM | FR-012 admitía pasar de 10 minutos con nota; SC-005 exigía menos de 10 | SC-005: nunca más de 20; menos de 10 o duración anotada con la propuesta |

Hallazgos menores que quedan anotados (no bloquean):

- **M1 (MEDIUM)**: el invariante de las 124 cae en la rama que se integre en
  segundo lugar si la 011 (u otra) añade tools que modifican. Es lo que se
  quiere (ninguna sin probar), pero obliga a sumar su lista al integrar; la
  regla está en el contrato del inventario y en «Dependencias» del plan.
- **L1 (LOW)**: añadir una ruta al Supervisor simulado (FR-006, research R-9)
  no tiene tarea propia; no hace falta hoy y la tabla de fallos del plan dice
  qué hacer si aparece.
- **L2 (LOW)**: `ha_cancel_wait` se comprueba en Hermes y no con el lector
  (research R-7): excepción justificada en FR-001.
- **L3 (LOW)**: no se ha podido leer el `manifest.json` de `kitchen_sink` en
  las fuentes descargadas; T017 comprueba en el CI que carga antes de escribir
  el resto del tramo B.
- **L4 (LOW)**: entre T007 y T009–T011, `test_cada_probada_aparece_en_un_test_del_banco`
  está en rojo a propósito (las 26 aún no tienen test); el tramo no se
  commitea hasta que pasa.
- **L5 (LOW)**: `ha_call_service` directo repite el humo de la 010; se repite
  a propósito para que la tool figure en los ficheros de la 028 que vigila el
  inventario.
- **L6 (LOW)**: la sección «Correcciones» de `## [1.2.0]` puede no existir aún
  (la crea la 009); T013 la crea si hace falta.
