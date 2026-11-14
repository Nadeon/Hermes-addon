# Checklist de calidad de la especificación: plataforma y deprecaciones (027)

**Propósito**: validar que la especificación está completa y tiene calidad antes de planificar
**Creado**: 2026-11-14
**Especificación**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación más allá de los que fija la 008 (nombres de tools existentes, campos de respuesta, eventos del log y ficheros que el Supervisor lee)
- [x] Centrada en el valor para el usuario (saber si un job fue bien, que nada se rompa, enterarse de los cambios de plataforma) y para quien mantiene Hermes
- [x] Escrita para quien mantiene Hermes
- [x] Todas las secciones obligatorias completas

## Completitud de los requisitos

- [x] No quedan marcadores [NEEDS CLARIFICATION]
- [x] Los requisitos se pueden probar y no son ambiguos
- [x] Los criterios de éxito son medibles
- [x] Los criterios de éxito no dependen de la tecnología (salvo nombres de tools y campos, que son el contrato)
- [x] Todos los escenarios de aceptación están definidos
- [x] Los casos límite están identificados
- [x] El alcance está delimitado (031, 014, 018 y 013 fuera; nada se retira ni se activa)
- [x] Dependencias y supuestos identificados (S-01…S-04; la implementación espera a integrar 009, 010 y 011)

## Preparación de la funcionalidad

- [x] Todos los requisitos funcionales tienen criterios de aceptación claros
- [x] Los escenarios de usuario cubren los flujos principales
- [x] La funcionalidad cumple los resultados medibles de los criterios de éxito
- [x] Trazabilidad: cada FR cita el FR de la 008 y la CAP que cubre

## Notas

- Decisiones tomadas sin el mantenedor (en «Clarificaciones» de la spec y en
  research.md): `child_errors` (R-1), que cuenta en `success` y en el sondeo del safety backup por decisión del supervisor (D-1); detectar
  socket y `/v2` sin usarlos (R-2, R-3); `unknown_command` → error claro sin
  reintentar (R-4); crear las traducciones que no existían (R-5); textos
  editados en su idioma actual (D-6); guarda de deprecaciones del SDK que
  cubre `MCPDeprecationWarning`, que no hereda de `DeprecationWarning` (R-6);
  solo `claude.ai` como host CIMD conocido (R-7); dos tramos en vez de uno
  (R-10).
- Correcciones a la 008 (research R-0): `docker/app.py` en vez de
  `docker/addon.py`; FR-092 vale solo para los errores del job consultado;
  `translations/` no existía.

## Dudas para el final (para el mantenedor)

- **D-1** (**cerrada**, decisión vinculante del supervisor del programa): los
  errores de los sub-jobs no suben al job padre (research R-1), y Hermes los
  cuenta: `sv_get_job_status` da `success: false` con `child_errors`
  (arreglo, coherente con la 009) y el sondeo de los safety backups de
  `fs_write.py` los trata como fallo (principio III). La retención
  (`safety_retention.py`) no cambia: el backup existe y debe podarse.
- **D-2**: Versión exacta de la retirada de `ha_remove_device_from_config_entry`
  (D-08 de la 008). Propuesta: la 1.3.0, con los alias `ha_hacs_*`, siempre
  que salga antes de HA 2027.9; si no, una 1.2.x anterior a esa versión de HA.
  Solo se puede fijar cuando se conozcan las fechas.
- **D-3**: `ping` y `hermes_guide` declaran `outputSchema` porque el SDK lo
  infiere de `-> str`; si alguna vez se recortaran, saldrían sin contenido
  estructurado (`_limitar` lo quita). Hoy no pasa (respuestas pequeñas).
  ¿Mantener, quitar con `structured_output=False` (cambia `tools/list`) o
  declarar esquemas en las tools nuevas con sobre común?
- **D-4**: Cuando el Supervisor publique la `/v2` como estable o inyecte el
  socket en las apps: inventario de la V2 (modo del extractor y su deriva),
  migración de rutas según la tabla de research R-3 y conexión por el socket
  según research R-2. Depende de versiones del Supervisor que aún no existen.
- **D-5**: La vía nativa de MCP (`InputRequiredResult`/elicitación) como
  segunda forma de confirmar, con el mismo token por debajo (D-10 de la 008).
- **D-6**: Las descripciones de muchas tools y la guía están en español, y el
  principio X pide inglés para lo que ve el cliente. La 027 sigue el idioma de
  cada texto que edita; traducirlas todas sería un cambio propio.

## Hallazgos fuera de alcance (para el informe)

- `tools/config_entries.py`, `_count_config_entry_dependents`: compara
  `entry_id` por subcadena con `config_entry_id` de las entidades (research
  R-9). Para quien toque esas vistas previas (018 o el cierre).

## Resultado de `/speckit-analyze` (2026-11-14)

Cobertura: 16 FR, 16 con tareas (100 %); 27 tareas, todas trazadas a FR o a
la preparación y el cierre; 8 SC, todos con tareas. Sin marcadores ni
duplicados. Ningún CRITICAL abierto.

| ID | Categoría | Gravedad | Dónde | Hallazgo | Estado |
|---|---|---|---|---|---|
| C1 | Constitución (V) | HIGH | tasks T007 | FR-009 cambia lo que devuelve `ha_remove_device_from_config_entry` y la tarea no cambiaba su descripción | Corregido: T007 y T006 exigen la descripción en el mismo commit; contrato actualizado |
| C2 | Constitución (X) | HIGH | spec FR-001, FR-007; plan | Las descripciones al cliente deben ir en inglés y las que se editan están en español | Corregido: decisión explícita (idioma del texto editado, principio IX), plan y duda D-6 |
| A1 | Ambigüedad | MEDIUM | spec FR-005 | «Avisos deprecados del SDK» no decía cuáles: el SDK usa `MCPDeprecationWarning`, que hereda de `UserWarning` | Corregido en spec, research R-6 y T014 |
| U1 | Infraespecificación | MEDIUM | spec FR-010 (primera versión) | Citaba un «filtro por integración» que `ha_list_devices` no tiene | Corregido: nombra las vistas previas y el plan de borrado que usan `device_config_entries` |
| E1 | Cobertura | LOW | T023 | Los cambios de `DOCS.md` y README (FR-007) no tienen test automático | Anotado: se revisan en el diff del cierre; los README tienen su propia comprobación de sincronía si existe |
| E2 | Cobertura | LOW | FR-012, FR-013 | Requisitos documentales sin test | Anotado: son entradas de la hoja de ruta (vía M de la matriz) |
| U2 | Infraespecificación | LOW | SC-003 | «Menos de 10 s de más» se prueba con el tope bajado en el test, no esperando 10 s | Anotado: el tope es una constante (`TIMEOUT_S`) y el test comprueba que se usa |
| F1 | Inconsistencia | LOW | plan, 008 | La 008 estima un tramo; aquí son dos | Justificado en plan («Desviaciones») y research R-10 |
