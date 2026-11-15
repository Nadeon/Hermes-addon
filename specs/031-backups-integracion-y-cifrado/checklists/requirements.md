# Lista de calidad de la especificación: backups de la integración y safety backups cifrados (031)

**Propósito**: validar que la spec está completa y es de calidad antes de planificar
**Creada**: 2026-11-15
**Spec**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación que no sean el contrato visible (nombres de tools, opciones y comandos de HA, que son el «qué» en este proyecto)
- [x] Centrada en el valor para el usuario (configurar, crear, restaurar y borrar backups; safety backups que no se pueden leer si se filtran)
- [x] Comprensible para quien administra Home Assistant
- [x] Secciones obligatorias completas

## Completitud de los requisitos

- [x] Ningún marcador [NEEDS CLARIFICATION] (las decisiones están en Clarificaciones y research.md; lo que el mantenedor puede querer cambiar, en «Dudas para el final»)
- [x] Requisitos verificables y sin ambigüedad (cada FR con su test en la trazabilidad de plan.md)
- [x] Criterios de éxito medibles (SC-001…SC-006)
- [x] Criterios de éxito sin detalles de implementación salvo los nombres del contrato
- [x] Escenarios de aceptación definidos para las seis historias
- [x] Casos límite identificados
- [x] Alcance acotado (fuera: montajes y `location` de la 019, cambiar la clave de cifrado, subidas y descargas)
- [x] Dependencias y supuestos identificados (019 para el tramo 3; 027 para las traducciones)

## Preparación

- [x] Cada FR traza a su FR y CAP de la 008
- [x] Las historias cubren los flujos principales
- [x] La comprobación de la constitución está en plan.md, principio por principio

## Resultado de `analyze` (2026-11-15)

Corregido en el mismo cambio (CRITICAL: ninguno):

| ID | Severidad | Hallazgo | Arreglo |
|---|---|---|---|
| A1 | HIGH | La vista previa de `ha_create_backup` decía un `encrypted` global, pero HA guarda sin cifrar la copia de un agente con `protected: false`: la vista previa mentiría (principio IV) | `encrypted` por agente en data-model sección 7, FR-005, FR-006 y T019 |
| A2 | HIGH | `backup/config/update` sustituye `schedule` y `retention` enteros: pasar solo `time` dejaba `recurrence: never` y apagaba los backups automáticos | Hermes completa esos documentos con los valores actuales (FR-002, R-10, data-model sección 3, T004) |
| A3 | HIGH | `PROBADAS_031` incluía `ha_list_backup_agents`, de lectura: el invariante de la 028 no admite lecturas en la unión de escrituras y el test caería | `LECTURAS_EN_BANCO_031` aparte, solo en `TOOLS_EXIGIDAS_DEL_JOB` (R-12, FR-022, T014) |
| A4 | MEDIUM | La regla «`restore_database` igual a lo que trae el backup» es de HA OS; en Core sin Supervisor HA permite restaurar sin la base de datos | Solo con `hassio.local` presente (FR-007, R-6, data-model sección 8, T034) |
| A5 | MEDIUM | Crear con apps o carpetas en Core sin Supervisor lo rechaza HA tarde | `invalid_argument` en la vista previa (FR-005, data-model sección 7, T019) |
| A6 | MEDIUM | T044 pedía comprobar «sin `.HA_RESTORE`», que el lector no puede leer | La prueba es que HA no se reinicia (misma conexión del lector viva) |
| A7 | LOW | SC-003 hablaba de «once datos» sin lista | Remite a data-model sección 8 |
| A8 | LOW | Tareas del tramo 4 numeradas fuera de orden | Renumeradas y trazabilidad de plan.md al día |

Menores anotados (no bloquean):

- M1 (MEDIUM): el mecanismo de la clave se desvía del texto de FR-068 de la 008 (research R-3); cumple su intención. Duda D-031-1.
- M2 (LOW): cuatro tramos en vez de los dos de la 008 (R-15). La fila de la 031 en la tabla de sub-features del plan de la 008 (tamaño, ~3 tools, 2 tramos) no se toca desde aquí: la actualiza el supervisor o el converge del programa (T026 de la 008). Duda D-031-2.
- M3 (LOW): la estimación de retención reproduce HA 2026.11.1; si una versión futura cambia las reglas, la estimación puede errar. Se presenta como estimación y el banco la contrasta.
- M4 (LOW): `restore_started` depende de `HAConnectionError.sent` (aditivo en `ha.py`); otra sub-feature que toque `ws_send` debe conservarlo.
- M5 (LOW): las traducciones de la opción dependen de que la 027 esté en la base (T052 lo anota si no).
- M6 (LOW): FR-020 de la 008 («nada cambia por defecto») frente a FR-068 (safety backups cifrados): manda FR-068; FR-023 de esta spec lo dice.
- M7 (LOW): `ha_delete_backup` necesita una lectura pública de la anotación de la retención (`safety_retention.py`); solo lee.
- M8 (LOW): `ha_get_update_backup_settings`, `ha_set_update_backup_settings` y la restauración con éxito solo se prueban en vivo (VM de la 014; quickstart.md).

## Dudas para el final

- **D-031-1**: ¿Clave de cifrado de los backups de HA (la del kit de emergencia) para los safety backups, en vez de una contraseña generada y guardada en `/data` como dice FR-068 de la 008? Recomendación: sí (research R-3: con la generada, un safety backup no se puede restaurar si Hermes está roto, y la clave va dentro del propio backup).
- **D-031-2**: cuatro tramos en vez de dos (R-15).
- **D-031-3**: `ha_create_backup` pide confirmación (FR-067 de la 008) y, por el invariante de la 1.1.2, se anuncia `destructiveHint`, aunque las `sv_create_backup_*` no confirman. Si el mantenedor prefiere que crear no confirme, `ha_create_backup` pasaría a no destructiva y FR-005 cambiaría; `ha_create_automatic_backup` debe seguir confirmando porque borra por retención.
