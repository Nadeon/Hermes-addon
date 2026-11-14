# Lista de calidad de la especificación: montajes de red y ajustes de backup (019)

**Propósito**: validar que la spec está completa antes de planificar e
implementar.
**Creada**: 2026-11-14
**Spec**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación que no sean el contrato con el cliente MCP
  (los nombres de tools, rutas del Supervisor y argumentos son el contrato,
  como en las specs 007 y 013)
- [x] Centrada en el valor para el administrador y en la seguridad
- [x] Secciones obligatorias completas

## Completitud de los requisitos

- [x] Sin marcadores [NEEDS CLARIFICATION]: las decisiones están en
  «Clarificaciones» y en research.md (R-1…R-12)
- [x] Requisitos verificables y sin ambigüedad (cada FR tiene su test en la
  trazabilidad del plan)
- [x] Criterios de éxito medibles (recuentos, 100 % de casos inválidos sin
  llamada, centinelas)
- [x] Escenarios de aceptación para las cuatro historias
- [x] Casos límite identificados
- [x] Alcance acotado (fuera de alcance: 031, `disk`, clase D, restaurar con
  `location`)
- [x] Dependencias y supuestos identificados (S-01…S-05)

## Preparación

- [x] Cada FR traza a FR-066 de la 008 (y a los transversales FR-010…FR-024
  que le tocan) y a CAP-083
- [x] Las historias cubren los flujos principales
- [x] Comprobación de la constitución, principio por principio, en plan.md
- [x] Tareas en TDD con controles negativos (T016, T030), partidas en dos
  tramos que dejan la suite en verde

## Análisis (speckit-analyze, 2026-11-14)

Corregido al analizar (CRITICAL/HIGH y algún MEDIUM de coste nulo):

- **[MEDIUM, corregido] Ambigüedad de `version`**: «nada» y «nulo» se
  confundían al editar. Ahora `auto` pide la negociación automática en las dos
  tools y `None` significa «automático» al crear y «no se toca» al editar
  (spec FR-003, FR-007; data-model; contrato; T005).
- **[MEDIUM, corregido] FR-003 y data-model no casaban**: los backups
  afectados al editar solo se calculan si el montaje era de uso `backup`.
- **[MEDIUM, corregido] FR-004 «los 20 primeros»**: ahora «los 20 más
  recientes», como data-model.
- **[MEDIUM, corregido] FR-014**: decía que la respuesta nombra la ubicación
  siempre; sin `location` la respuesta es la de la 1.1.2.
- **[MEDIUM, corregido] FR-010 sin test en la vista previa**: T005 cubre ya
  `GET /mounts` de forma inesperada antes de emitir un token.

Sin CRITICAL ni HIGH abiertos. Menores anotados (no bloquean):

- **[LOW] Nombres de más de 64 caracteres**: el Supervisor no pone tope al
  nombre y Hermes valida 1–64 (como el `disk` de la 013); un montaje creado
  fuera de Hermes con un nombre más largo no se podría editar, borrar ni
  recargar desde Hermes. Improbable; si aparece, se sube el tope.
- **[LOW] `truncated` de `sv_list_mounts`**: solo lo pone el tope central de
  respuesta (una instalación tiene pocos montajes); no hay recorte propio.
- **[LOW] `sv_create_mount` no idempotente**: se anuncia `idempotentHint`
  falso por el prefijo `sv_create_`, aunque repetirla con los mismos
  argumentos solo da «ya existe». Es la opción conservadora y no miente en la
  dirección peligrosa.
- **[LOW] Recuentos compartidos**: `test_recuento` del inventario de la 033 y
  los recuentos por categoría de la tabla los suben también otras
  sub-features; se cuadran al integrar.
- **[LOW] Regla de clase A del test de la tabla**: la 013 la amplía para
  admitir `dedicated`; si la 019 se implementa antes de integrar la 013, hace
  la misma ampliación (T012) y habrá un conflicto de texto trivial.
- **[LOW] Conflicto de texto con la 031** en `tools/backups.py` (la 031 toca
  los safety backups; la 019, `location`).

## Dudas para el final

- **D-019-1 — Montajes de disco (`type: disk`)**: el Supervisor 2026.11.0
  permite crear montajes de un disco local por `POST /mounts`. Al pasar esa
  ruta a `dedicated` y no admitir `disk` en `sv_create_mount`, dejan de ser
  alcanzables desde Hermes (fail-closed). ¿Se cubren en otra sub-feature
  (¿032, host?), o se quedan fuera?
- **D-019-2 — Hash del token con la contraseña dentro**: el `action_hash`
  (SHA-256) incluye la contraseña CIFS, como ya pasa con `fs_set_secret` y
  `sv_restore_backup_*`. Con lectura de `/data` durante los 60 s del token, una
  contraseña débil se podría adivinar contra el hash. Un HMAC con clave en
  memoria lo cerraría para todas las tools; es un cambio de `security.py`
  fuera de esta sub-feature.
- **D-019-3 — La 033 sin integrar**: si al implementar el tramo 1 la 033 no
  está en la rama, las cuatro tools con token entran en su inventario al
  integrarla (T013).

## Notas

- Las tools que modifican quedan en la matriz de la 014 como VM / pendiente:
  la prueba con un NAS real (Samba o NFS de prueba junto a la VM) está por
  hacer.
