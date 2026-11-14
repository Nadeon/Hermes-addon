# Lista de calidad de la especificación: banco de pruebas de Core (spec 010)

**Propósito**: validar que la spec está completa antes de planificar e implementar
**Creada**: 2026-11-14
**Spec**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación innecesarios. Nota: como en el resto de
  specs del programa, los FR nombran ficheros, rutas y la imagen porque la 008
  los fija (FR-013) y el banco es infraestructura de pruebas, no una función
  para usuarios finales.
- [x] Centrada en el valor para el mantenedor (saber qué está probado de
  verdad, historia 5 de la 008)
- [x] Secciones obligatorias completas

## Completitud de los requisitos

- [x] Sin marcadores [NEEDS CLARIFICATION]: las decisiones se tomaron con la
  008 y la decisión del supervisor, y están en «Clarificaciones»
- [x] Requisitos verificables y sin ambigüedad: cada FR tiene su tarea con test
  o comprobación
- [x] Criterios de éxito medibles (recuentos, 0 saltos, 0 líneas en código de
  producto, minutos)
- [x] Escenarios de aceptación definidos para las cuatro historias
- [x] Casos límite identificados
- [x] Alcance acotado (fuera de alcance: 028, 014, 011, ruleset)
- [x] Dependencias y supuestos identificados (S-01…S-05; 009, 011, 014, 028)
- [x] Cada FR traza a un FR o CAP de la 008

## Preparación

- [x] Cada FR tiene criterio de aceptación (tabla de cobertura abajo)
- [x] Las historias cubren los flujos principales (CI, helpers, local,
  privacidad)
- [x] Comprobación de la constitución en plan.md, con dos desviaciones
  transitorias justificadas (puerta 4 → E-3 y XI → E-4, ambas en la 011)

## Resultado de `analyze` (2026-11-14)

Cobertura: 14 FR, 7 SC, 35 tareas; 100 % de los FR con al menos una tarea.

| FR | Tareas |
|---|---|
| FR-001 | T014, T015, T016 |
| FR-002 | T003, T015 |
| FR-003 | T005, T006, T007 |
| FR-004 | T008, T009, T010, T017 |
| FR-005 | T012, T017 |
| FR-006 | T034 |
| FR-007 | T011, T012, T013, T019 |
| FR-008 | T025, T026, T027, T029, T030 |
| FR-009 | T023, T024, T028 |
| FR-010 | T014, T015, T033 |
| FR-011 | T006, T012, T014, T015 |
| FR-012 | T005, T018, T034 |
| FR-013 | T022, T031, T032 |
| FR-014 | T007, T010, T013, T016, T021, T028, T030 |

Hallazgos corregidos en los artefactos:

| ID | Severidad | Hallazgo | Corrección |
|---|---|---|---|
| D1 | CRITICAL | La cabecera `## [1.2.0] — <fecha de publicación>` contradice el formato `AAAA-MM-DD` del principio XI y el plan lo daba por «OK» | Fila XI de la comprobación de la constitución: desviación transitoria justificada por FR-022 de la 008 y la enmienda E-4 (011) |
| C1 | HIGH | El humo usa un helper «creado por el lector», pero el lector no tenía operación de crear | `crear(dominio, datos)` en data-model, plan §6 y T012 |
| F1 | HIGH | FR-006 prohibía tocar `hermes/` y FR-013 exige `hermes/CHANGELOG.md` | FR-006, SC-003 y plan: «salvo `hermes/CHANGELOG.md`» |
| E1 | MEDIUM | FR-011 (tiempos y reintentos) sin comprobación automática | T014 comprueba `--timeout=120`, reintentos de `docker pull`, logs si falla y limpieza siempre |
| E2 | MEDIUM | Historia 3, escenario 3 (HA inalcanzable → fallo) sin test | T011 añade la URL a un puerto cerrado |
| F2 | MEDIUM | plan.md citaba un solo `test_banco_helpers.py` y tasks.md lo parte en tres | plan §7 y «Ficheros» con los tres ficheros |

Hallazgos menores que quedan anotados (no bloquean):

- **L1 (LOW)**: SC-006 dice «ejecución normal» sin definirla; se entiende sin
  reintentos de descarga. Se mide en T020 y T029.
- **L2 (LOW)**: el test de T014 sobre los reintentos de `docker pull` depende
  de cómo se escriba el bucle en el YAML; el agente del tramo A fija una forma
  reconocible (por ejemplo `for intento in 1 2 3`) y la comprueba.
- **L3 (LOW)**: sin caché de la imagen (research R-6). Si la descarga pasa de 3
  minutos de forma sostenida, añadir caché o repartir el banco en varios jobs
  (riesgo de la 008).
- **L4 (LOW)**: en la reproducción local con Docker (quickstart §2) no se corta
  la salida a internet; los tests no dependen de ello.
- **L5 (LOW)**: la sección del CHANGELOG puede chocar con la que crea la 009 al
  integrar las dos ramas; se resuelve dejando una sola cabecera `## [1.2.0]`.
- **L6 (MEDIUM, fuera de los tramos)**: añadir el check `banco de Core` al
  ruleset es del mantenedor (T033); el ruleset «Hermes Protegido» está hoy con
  `enforcement: disabled`, así que tampoco bloquea los checks actuales.
- **L7 (LOW)**: `resolve_supervisor_base_url` no se ejecuta en el banco
  (research R-4); sigue cubierta por sus tests unitarios.

## Dudas para el final

- **Q1**: completar el paso `core_config` del onboarding lanza integraciones
  que salen a internet; se decidió completarlo (FR-013 de la 008) y cortar la
  salida del contenedor. Si el mantenedor prefiere un onboarding sin ese paso
  (más simple, sin regla de `iptables`), basta con quitarlo de
  `onboarding.py` y los pasos 6 y 9 del job.
- **Q2**: el job corre en cada push a cualquier rama. Si el coste en tiempo
  molesta, se puede limitar a pull requests y a la rama del programa.
