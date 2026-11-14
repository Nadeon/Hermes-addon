# Lista de calidad de la especificación: banco de pruebas del Supervisor (spec 014)

**Propósito**: validar que la spec está completa antes de planificar e implementar
**Creada**: 2026-11-14
**Spec**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación innecesarios. Nota: como en el resto de
  specs del programa, los FR nombran ficheros y rutas porque la 008 los fija
  (FR-016, FR-017) y la sub-feature es documentación y tests de
  infraestructura, no una función para usuarios finales.
- [x] Centrada en el valor para el mantenedor (saber qué está probado de
  verdad y dónde, y que el comentario del rol no mienta)
- [x] Secciones obligatorias completas

## Completitud de los requisitos

- [x] Sin marcadores [NEEDS CLARIFICATION]: las decisiones se tomaron con la
  008 y la decisión del supervisor, y están en «Clarificaciones»
- [x] Requisitos verificables: cada FR tiene su test o su comprobación de
  lectura (FR-001 y FR-006, por la estructura del documento)
- [x] Criterios de éxito medibles (recuentos de filas, 24 de 24, 0
  contradicciones, 0 líneas de código de producto, 6 fallos conocidos)
- [x] Escenarios de aceptación definidos para las cuatro historias
- [x] Casos límite identificados
- [x] Alcance acotado (fuera: montar la VM, D-02, D-06, tools, tabla,
  familias, el docstring de `config.py`)
- [x] Dependencias y supuestos identificados (S-01…S-05; 010, 011, 028 y las
  sub-features con `sv_*` nuevas)
- [x] Cada FR traza a un FR o CAP de la 008

## Preparación

- [x] Cada FR tiene criterio de aceptación (tabla de cobertura abajo)
- [x] Las historias cubren los flujos principales (procedimiento, matriz,
  casillas, comentario del rol)
- [x] Comprobación de la constitución en plan.md, con la desviación
  transitoria de XI (cabecera provisional del CHANGELOG, E-4 en la 011) igual
  que la 010

## Resultado de `analyze` (2026-11-14)

Cobertura: 11 FR, 8 SC, 16 tareas, 1 tramo; 100 % de los FR y de los SC con
al menos una tarea.

| FR | Tareas |
|---|---|
| FR-001 | T009 |
| FR-002 | T006, T007 |
| FR-003 | T006, T007 |
| FR-004 | T006 |
| FR-005 | T006, T010, T011 |
| FR-006 | T009 |
| FR-007 | T002, T003 |
| FR-008 | T004 |
| FR-009 | T012, T013, T014 |
| FR-010 | T005, T008 |
| FR-011 | T003, T015 |

Sin hallazgos CRITICAL ni HIGH. Corregidos en los artefactos durante el
análisis:

- (MEDIO) El extractor de rutas no preveía llamadas con ruta en una variable,
  y hoy hay una (`sv_list_addons`, `/addons` o `/store/addons`): añadida a
  `LLAMADAS_DECLARADAS` con sus rutas, que se comprueban igual
  (data-model, T004).
- (MEDIO) SC-004 pedía las 7 casillas de CAP-035, pero el test solo miraba
  las de SC-011: el test pasa a llamarse `test_casillas_manuales` y comprueba
  las claves de las dos listas y el entorno de cada casilla
  (contracts/matriz.md, FR-005).
- (BAJO) Un recuento del patrón de `manager` que no cuadraba con el código
  del Supervisor: quitado; el patrón se copia tal cual.
- (BAJO) El procedimiento decía que la autoprotección «rechaza»
  `sv_stop_addon` sobre Hermes: solo avisa en la vista previa; el rechazo
  previo es el de `sv_update_addon` (009). Corregido en
  contracts/procedimiento.md.

Anotados, sin cambio:

- (BAJO) FR-016 de la 008 lista «simuladores» como entorno de la matriz. Aquí
  no es un valor de la columna porque corren siempre para todas las tools; el
  párrafo de la matriz lo dice. Es una lectura, no una omisión.
- (BAJO) T009 de la 008 sitúa «procedimiento, matriz y pruebas manuales» en
  `docs/HOJA-DE-RUTA.md`; el procedimiento va a `docs/BANCO-SUPERVISOR.md`,
  enlazado desde la hoja de ruta, por longitud (spec, clarificaciones).
- (BAJO) Los tests de `tests/test_rutas_supervisor_rol.py` pasan desde el
  primer momento (comprueban código que no cambia); su valor lo demuestran
  los controles negativos de T005, no un rojo inicial.
- (BAJO) Conflictos previsibles en `docs/HOJA-DE-RUTA.md` («Verificado
  contra», tabla del programa) con la 011 y la 028 al integrar; la matriz va
  entre marcadores y en orden alfabético para que sean de una línea.
- (BAJO) Si la 028 se integra después de la 014, el test de la matriz caerá
  en la integración hasta poner sus 53 filas en «ok»: es intencionado
  (research R-2) y lo resuelve quien integra.

## Hallazgos fuera de alcance (para otra sub-feature)

- `hermes/src/hermes/config.py`, docstring del módulo: «run.sh lee
  options.json con bashio». Es falso (run.sh usa `jq`); mismo error que el
  comentario de `hassio_role`, pero en código de producto.

## Dudas para el final (del mantenedor)

- D-02 de la 008: bajar a `hassio_role: manager` tras la prueba en la VM y en
  la instalación real.
- D-06 de la 008: la VM con HAOS en un runner del CI con KVM, como job
  nocturno o manual. No se implementa.
