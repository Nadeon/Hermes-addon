# Checklist de calidad de la especificación: política de comandos, genéricas y familias (011)

**Propósito**: validar que la especificación está completa y tiene calidad antes de planificar
**Creado**: 2026-11-14
**Especificación**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación más allá de los que fija la 008 (nombres de tools, opción, módulos que ya existen)
- [x] Centrada en el valor para el usuario y en las necesidades del mantenedor
- [x] Escrita para quien mantiene Hermes (no para alguien ajeno al proyecto)
- [x] Todas las secciones obligatorias completas

## Completitud de los requisitos

- [x] No quedan marcadores [NEEDS CLARIFICATION]
- [x] Los requisitos se pueden probar y no son ambiguos
- [x] Los criterios de éxito son medibles
- [x] Los criterios de éxito no dependen de la tecnología (salvo nombres de tools y opciones, que son el contrato)
- [x] Todos los escenarios de aceptación están definidos
- [x] Los casos límite están identificados
- [x] El alcance está delimitado
- [x] Dependencias y supuestos identificados

## Preparación de la funcionalidad

- [x] Todos los requisitos funcionales tienen criterios de aceptación claros
- [x] Los escenarios de usuario cubren los flujos principales
- [x] La funcionalidad cumple los resultados medibles de los criterios de éxito
- [x] Trazabilidad: cada FR cita los FR de la 008 y las CAP que cubre

## Notas

- La spec nombra módulos y ficheros (`command_table.py`, `scripts/inventario/`,
  `tool_families_disabled`) porque es una sub-feature de un programa cuya spec
  paraguas ya fija la arquitectura; es el estilo de las specs 003–007.
- Decisiones tomadas sin el mantenedor, en «Clarificaciones» y en research.md:
  ubicación de la tabla, generador que conserva lo revisado, normalización del
  inventario del Supervisor, clase C `deny` «pendiente de revisión (spec 025)»,
  familia por defecto `generic_commands` para lo que no es `dedicated`, carga
  no omitible al confirmar, argumento `search` de `hermes_guide`, nombre de la
  opción.

## Resultado de `/speckit-analyze` (2026-11-14)

Cobertura: 26 FR, 26 con tareas (100 %); 43 tareas, todas trazadas a FR o a
cierre de tramo; 8 SC, todos con tarea. Sin hallazgos CRITICAL.

Corregidos (HIGH y algunos MEDIUM):

- **H1 (HIGH, ambigüedad de seguridad)**: la regla de los 64 caracteres del
  resumen de la carga no decía si contaban las comillas del JSON. Ahora: texto
  tal cual en cadenas, JSON en el resto (spec FR-010, data-model, T018 con el
  caso límite 64/65).
- **H2 (HIGH, principio II)**: un error de HA o del Supervisor puede repetir el
  valor que rechaza (una contraseña). Ahora el mensaje pasa por
  `redact_secrets` y se tapan los valores de texto de la carga de 4 o más
  caracteres; el log no lleva el mensaje (spec FR-017, contrato, T019, T021).
- **H3 (HIGH, cobertura)**: FR-021 («los mismos argumentos») no tenía test.
  Ahora hay instantánea de esquemas de la 1.1.2 (T022) y su comprobación con
  familias, con `search` como única diferencia permitida (T032).
- M1: la guarda `self_target` necesita la plantilla casada; el orden de las
  guardas lo dice ya (data-model, research R-6).
- M2: la regla de `/core/api*` prevalece sobre «cubierto» (spec FR-002,
  research R-4).
- M3: test de que un `type` inválido no se copia al log (T019).
- M4: recuentos por clase del Supervisor en T003.
- M5: control negativo del catálogo de familias (T016 g).
- L1: id de tarea del banco en S-01.

Anotados, no corregidos (MEDIUM/LOW):

- **M6**: el tramo 1 es el más pesado (tabla de 877 entradas con revisión
  manual de 53 comandos y unas 40 rutas, más lo cubierto). Si el agente se
  queda corto, T013 y T014 se pueden hacer en un commit aparte del mismo tramo;
  la suite queda en verde porque T011 ya pasa con la tabla generada.
- **L2**: SC-007 toma como referencia el CI de Linux, pero los tramos no hacen
  push; el CI se ve al abrir el PR contra `feat/cobertura-total`.
- **L3**: el tope de 10 s de las suscripciones de un solo mensaje y el máximo de
  50 filas de la consulta de la guía están en research/contrato/tareas, no en
  la spec.
- **L4**: `sv_read_api` no admite parámetros de consulta; si alguna ruta de vía
  T los necesitara para ser útil, T014 la deja `confirm`/`read` sin ellos y lo
  anota.
- **L5**: solo los comandos de tags llevan `example` al cerrar la 011; las
  sub-features añaden los suyos.
- **L6**: terminología «carga» (Core) y «cuerpo» (Supervisor) para lo mismo;
  se mantiene porque son los nombres de los argumentos (`payload`, `body`).

## Dudas para el final (para el mantenedor)

- La clase C queda `deny` «pendiente de revisión (spec 025)» en vez de
  clasificarse por verbo aquí (FR-002 de la 008 lo admitía; se eligió
  fail-closed porque la 025 la revisa uno a uno).
- Los inventarios siguen en `specs/008-cobertura-total/inventario/` (decisión
  del supervisor). Para las versiones siguientes de HA tendría más sentido
  moverlos junto al extractor, a `scripts/inventario/`.
- Las familias de la 1.1.2 también se pueden desactivar (la 008 solo exigía
  poder desactivar las nuevas); `base` no.
