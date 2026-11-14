# Lista de calidad de la especificación: 009 — correcciones pendientes y versión 1.2.0

**Propósito**: validar que la spec está completa antes de planificar e implementar
**Creada**: 2026-11-14
**Spec**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Centrada en lo que nota el usuario (log que se puede pegar, respuestas que dicen lo que hacen, mensajes claros)
- [x] Los detalles de implementación están en el plan, research y contratos; la spec nombra tools, campos y eventos porque son la interfaz pública de Hermes (como las specs 003–007)
- [x] Todas las secciones obligatorias completas

## Completitud de los requisitos

- [x] Sin marcadores [NEEDS CLARIFICATION]: las decisiones abiertas se tomaron con la 008 y quedan en «Clarificaciones»
- [x] Requisitos comprobables y sin ambigüedad (umbral de tiempo, campos y eventos con nombre, contrato)
- [x] Criterios de éxito medibles (SC-001…SC-007)
- [x] Escenarios de aceptación por historia
- [x] Casos límite identificados
- [x] Alcance acotado («Fuera de alcance»)
- [x] Supuestos identificados (S-01…S-05)

## Trazabilidad con la 008

- [x] Cada FR de la 009 cita su FR y su CAP de la 008: FR-001…FR-011 → FR-025…FR-035 (CAP-010…CAP-018, CAP-021, CAP-024); FR-012 → FR-022; FR-013 → FR-023, FR-024; FR-014 → FR-018, FR-020, FR-021
- [x] Ni más ni menos: no hay FR sin origen en la 008; las CAP de la fila 009 del plan de la 008 están todas
- [x] Decisión de la 008 sobre `installed_only` (por defecto `false`) aplicada frente a la propuesta de research CAP-016

## Preparación

- [x] Plan con comprobación contra la constitución (desviación de XI justificada; matiz de III justificado)
- [x] Tareas en TDD (test en rojo → arreglo → control negativo) y partidas en dos tramos commiteables por separado (A: T001–T020; B: T021–T042)

## Resultado de `speckit-analyze` (2026-11-14)

Requisitos: 14 FR y 7 SC. Tareas: 42. Cobertura: 14/14 FR con al menos una
tarea; SC-001…SC-007 cubiertos por tareas de test o de cierre. Sin hallazgos
CRITICAL. Los HIGH y MEDIUM se corrigieron en los documentos:

| ID | Severidad | Hallazgo | Estado |
|---|---|---|---|
| I1 | HIGH | FR-007 decía a la vez «`removal_type` se recorta» y «`repositories` es la misma lista que en la 1.1.2» (contradicción con entradas de más de 300 caracteres) | Corregido: misma lista y orden; solo un `removal_type` largo sale recortado (spec FR-007 e Historia 3.4) |
| C1 | MEDIUM | SC-007 y la puerta 4 de la constitución piden el CI en verde y ninguna tarea lo cubría | Corregido: T042 lo comprueba al subir la rama o lo deja anotado como pendiente |
| U1 | MEDIUM | T032 (b) hablaba de «un token válido emitido para otro add-on», que no prueba el caso real (un token de Hermes de una vista previa de la 1.1.2) | Corregido: token creado con `create_confirmation_token` para el slug de Hermes |
| C2 | MEDIUM | FR-002 afirma que los hosts de HA salen tapados también en `sv_get_addon_logs` del propio Hermes y no había test | Corregido: T022 (g) |

Menores, anotados y no bloqueantes:

| ID | Severidad | Hallazgo | Estado |
|---|---|---|---|
| T1 | LOW | Deriva de nombre `ha_hosts_re` (plan) frente a `ha_hosts` (data-model) | Corregido en el plan |
| T2 | LOW | Texto de la línea «pendiente» del esqueleto distinto en research y tasks | Corregido: «Pendiente: la añade la sub-feature que lo implemente.» |
| T3 | LOW | FR-003 no decía qué contadores lleva `auto_classify_on_save` | Corregido: `restricted` y `count` |
| L1 | LOW | El umbral de 1 s del test de tiempo puede ser frágil en un runner muy lento | Previsto en el plan (Riesgos) y en las notas de tasks: pasar a la razón 256 KiB / 1 MiB, nunca subir el umbral |
| L2 | LOW | R-7 (traceback al apagar) es una hipótesis sin traza guardada del problema 23 | Previsto: T035 lo reproduce antes de arreglar y anota si no; prueba manual tras publicar (quickstart) |
| L3 | LOW | La cabecera `<fecha de publicación>` se aparta del formato de XI | Desviación justificada en el plan; depende de la enmienda E-4 que decide la 011 |
| L4 | LOW | `_es_hermes` trata cualquier `*_hermes` como Hermes, así que se negaría a actualizar otro add-on con ese sufijo | Criterio existente, fuera de alcance (spec, casos límite); a revisar si alguien lo reporta |
| L5 | LOW | FR-002 no recoge un cambio de URLs de HA sin reconexión (`core_config_updated`) | Decisión de research R-2; se recoge en la siguiente reconexión |

## Notas

- Todo lo marcado está validado; la spec está lista para implementar por tramos.
