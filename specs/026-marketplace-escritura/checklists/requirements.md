# Lista de calidad de la especificación: escritura en el Marketplace (026)

**Propósito**: validar que la spec está completa antes de implementar
**Creada**: 2026-11-15
**Feature**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Centrada en el valor para el administrador (historias US1–US3)
- [x] Secciones obligatorias completas
- [x] Los detalles de implementación (comandos WS, rutas) están donde la 008
  y las sub-features anteriores los ponen: en FR verificables y en
  data-model/contracts; la spec no fija estructuras de código
- [x] Sin datos de ninguna instalación (principio VIII): `ejemplo/…`,
  `"123456"`, `centinela-026`, `https://example.com/aviso`

## Completitud de requisitos

- [x] Ningún marcador [NEEDS CLARIFICATION]: las decisiones están en
  «Clarificaciones» con su justificación en research
- [x] Requisitos verificables (cada FR tiene tests en tasks.md)
- [x] Criterios de éxito medibles (SC-001…SC-007)
- [x] Escenarios de aceptación por historia y casos límite
- [x] Alcance acotado («Fuera de alcance») y supuestos escritos
- [x] Cada FR traza a FR-091 / CAP-075 o a un FR transversal de la 008
  (FR-010, FR-011, FR-012, FR-015, FR-016, FR-018…FR-020, FR-023)

## Preparación

- [x] Todos los FR tienen tareas (mapa abajo)
- [x] Tramos de tamaño de un agente, cada uno con suite verde y commit propio
- [x] Constitución comprobada principio por principio (plan.md)

## Mapa FR → tareas

| FR | Tareas |
|---|---|
| FR-001 | T003, T007, T008, T021, T023 |
| FR-002 | T003, T007, T008 |
| FR-003 | T006, T019, T020 |
| FR-004 | T004, T005, T006, T019 |
| FR-005 | T003, T004, T019 |
| FR-006 | T003, T006 |
| FR-007 | T007, T021 |
| FR-008…FR-012 | T004, T005, T006, T008 |
| FR-013…FR-017 | T018, T019, T020, T023 |
| FR-018 | T022, T024, T026 |
| FR-019 | T011, T025 |
| FR-020 | T002, T009, T017, T025 |
| FR-021 | T009, T023, T025 |
| FR-022 | T012, T026 |
| FR-023 | T014, T027 |
| FR-024 | T010, T025 |
| FR-025 | T015, T029 |

## Resultado de `analyze` (2026-11-15)

Corregidos al especificar (CRITICAL/HIGH y los MEDIUM baratos):

- **A1 [HIGH] Cobertura de la 008**: la primera versión tenía un solo tema de
  guía (`marketplace_write`) para dos familias nuevas; FR-011 de la 008 pide
  un tema por familia nueva. Corregido: temas `marketplace_manage` (tramo 1)
  y `marketplace_install` (tramo 2) en FR-022, plan y T012/T026.
- **A2 [MEDIUM] Inconsistencia**: FR-001 y research R-1 nombraban
  `config/entity_registry/list`, que ninguna vista previa usa. Quitado.
- **A3 [MEDIUM] Vista previa que mentiría**: la de `set_version` prometía «la
  versión seleccionada actual», que `repositories/list` no da (solo
  `repository/info`, clase B). Corregido: enseña `installed_version` y
  `available_version` y lo dice.
- **A4 [MEDIUM] Inconsistencia**: el `estado` de añadir decía «categorías
  detectadas», pero al confirmar no se repite la detección (saldría otra vez
  a GitHub). Corregido en data-model y R-9: `full_name` y «no está ya en la
  lista».
- **A5 [MEDIUM] Matriz**: «banco de Core / no ejecutable» para ocho tools que
  sí se pueden probar en una instalación real con internet ocultaba la prueba
  pendiente. Corregido: «instalación real / pendiente» con el motivo del banco
  en la nota (el test de la matriz lo admite para un `NO_EJECUTABLES*`).
- **A6 [MEDIUM] Riesgo del banco**: el plan llamaba HALLAZGO (`xfail`) a un
  fallo de la semilla, que es del banco y no de HA. Corregido: la semilla que
  no se lee lleva a `NO_EJECUTABLES_026`; solo un fallo de HA al reconocer es
  HALLAZGO con `xfail` estricto.

Menores, anotados (no bloquean):

- **A7 [LOW] Limitación de HA (R-2)**: cuatro tools rechazarán siempre con
  HA 2026.11.1 desde Hermes (aviso por usuario; el de Hermes es el del
  Supervisor). Es honesto (rechazo sin token y descripción), pero ocupa
  contexto: duda D-1 para el mantenedor.
- **A8 [LOW] Lectura de FR-091**: «backup previo» solo en instalar y
  desinstalar (las que cambian ficheros); las otras siete no hacen backup y lo
  dicen (research R-6).
- **A9 [LOW] Nombres**: `refresh` e `ignore` llevan `_repository` y se añade
  `ha_marketplace_set_beta`, respecto a research CAP-075 de la 008 (R-3, R-4).
- **A10 [LOW] `replaces_built_in`**: `manifest/get` resuelve la personalizada
  si sus ficheros ya están; si Hermes se equivoca, HA vuelve a comprobarlo y
  su rechazo se traduce (R-8).
- **A11 [LOW] Espera del backup**: con `background: false`, si pasa la espera
  larga no hay `job_id`; la respuesta lo dice y no instala (fail-closed).

## Dudas para el final

- **D-1**: publicar o no las cuatro tools que exigen el aviso de riesgos
  aceptado por el usuario del Supervisor (`ha_marketplace_install`,
  `ha_marketplace_set_version`, `ha_marketplace_set_beta`,
  `ha_marketplace_add_repository`), que con HA 2026.11.1 no pueden funcionar
  desde Hermes (research R-2).
- **D-2**: hereda la D-03 de la 008: las dos familias, de riesgo alto,
  activas por defecto.
