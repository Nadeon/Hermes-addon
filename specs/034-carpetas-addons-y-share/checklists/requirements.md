# Checklist de calidad de la especificación: carpetas /addons y /share (034)

**Propósito**: validar que la especificación está completa y tiene calidad antes de planificar
**Creado**: 2026-11-15
**Especificación**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación más allá de los que fija el encargo y lo que ya existe (nombres de tools, familia, rutas del Supervisor, módulos de `/config` que se reutilizan)
- [x] Centrada en el valor para el usuario (trabajar en `/addons` y `/share` sin la interfaz y sin poder romper una app instalada)
- [x] Escrita para quien mantiene Hermes
- [x] Todas las secciones obligatorias completas

## Completitud de los requisitos

- [x] No quedan marcadores [NEEDS CLARIFICATION] (las decisiones están en «Clarificaciones» y en research.md)
- [x] Los requisitos se pueden probar y no son ambiguos
- [x] Los criterios de éxito son medibles
- [x] Los criterios de éxito no dependen de la tecnología (salvo nombres de tools, carpetas y familia, que son el contrato)
- [x] Todos los escenarios de aceptación están definidos
- [x] Los casos límite están identificados (symlinks, montajes bajo `/share`, árboles enormes, ficheros enormes, carpeta sin montar, `config.*` ilegible, mover entre carpetas, Hermes borrándose a sí mismo)
- [x] El alcance está delimitado (solo `/addons` y `/share`; sin búsqueda, copia, binarios ni backup automático)
- [x] Dependencias y supuestos identificados (Supervisor 2026.11.0; prueba en vivo pendiente)

## Preparación de la funcionalidad

- [x] Todos los requisitos funcionales tienen criterios de aceptación claros
- [x] Los escenarios de usuario cubren los flujos principales
- [x] La funcionalidad cumple los resultados medibles de los criterios de éxito
- [x] Trazabilidad: cada FR cita la decisión del encargo (D-1…D-8) o el principio que lo motiva

## Resultado de `analyze` (2026-11-15)

34 FR, 6 SC, 44 tareas en 4 tramos (T001–T016, T017–T028, T029–T035,
T036–T044); cobertura de FR con tareas: 100 % (matriz de plan.md). Sin
marcadores ni datos personales. Constitución: sin conflictos; una desviación
justificada en el principio II (el contenido sale sin redactar, igual que
`fs_read_file`).

Corregido (CRITICAL/HIGH):

- **A1 (HIGH, cobertura)** — `tests/test_tools_registration.py` exige que
  toda tool fuera de la 1.1.2 esté en `_HINTS_NUEVAS_1_2_0`
  (`test_hints_did_not_change`): las siete nuevas lo habrían hecho caer. Se
  añade `_HINTS_NUEVAS_1_2_1` a R-10, T011 y T025.
- **A2 (HIGH, inconsistencia)** — contracts/tools.md y T032/T034 prometían
  `changed: "privileges"` en el rechazo de `sv_install_addon`, pero el token
  solo guarda UNA huella del estado (`security.py`, `state_hash`): no se puede
  saber qué cambió. Se quita la clave y la pista nombra las dos causas
  (principio V: no prometer lo que no se sabe).
- **A3 (HIGH, fail-closed)** — FR-019 no decía qué pasa al ESCRIBIR en
  `addons` con el Supervisor caído: se podía reescribir el `config.*` de una
  app instalada cambiándole el `slug`. Ahora: `config.*` →
  `installed_check_failed`; el resto lleva `installed_check: "failed"` en la
  vista previa. Test en T023.
- **A4 (HIGH, privacidad)** — tasks.md y quickstart.md llevaban la ruta del
  intérprete del checkout del mantenedor (principio VIII). Sustituida por un
  marcador.

Menor, anotado (B1 y B2 incorporados a T008 y T037; el resto, sin cambios):

- **B1 (MEDIUM)** — FR-012 no fija el tamaño de una carpeta en la lista
  canónica; depende del sistema de ficheros. Recomendación para el tramo 1:
  `None` para carpetas (solo cuenta su existencia y su fecha).
- **B2 (MEDIUM)** — El borrado recursivo de una carpeta que otra app está
  escribiendo (p. ej. un log en `/share`) nunca casará la huella: es
  fail-closed a propósito; la guía (T037) debería decir que se pare antes la
  app.
- **B3 (LOW)** — Plan y tareas nombran clases de test que aún no existen
  (`TestMontajes`, `TestFamiliaAddonsShare`…): son el contrato del tramo que
  las crea.
- **B4 (LOW)** — El aviso del tipo de montaje heredado aparecerá en el log
  del Supervisor; está documentado (R-1, T039, T042) pero no se puede probar
  en la suite.
