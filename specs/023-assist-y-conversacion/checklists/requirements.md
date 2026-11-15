# Lista de calidad de la especificación: Assist y conversación (023)

**Propósito**: validar que la spec está completa y es de calidad antes de
implementar.
**Creada**: 2026-11-15
**Feature**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación que no pida la constitución (los nombres
  de tools, comandos WS y entradas de la tabla son el contrato del programa)
- [x] Centrada en el valor para el usuario (administrador de HA desde un
  cliente MCP)
- [x] Todas las secciones obligatorias completas

## Completitud de requisitos

- [x] No quedan marcadores [NEEDS CLARIFICATION]
- [x] Requisitos comprobables y sin ambigüedad
- [x] Criterios de éxito medibles
- [x] Escenarios de aceptación definidos
- [x] Casos límite identificados
- [x] Alcance delimitado (fuera de alcance explícito)
- [x] Dependencias y supuestos identificados

## Trazabilidad con la 008

- [x] FR-001…FR-005 → FR-083 / CAP-060
- [x] FR-009 → FR-084 / CAP-061, CAP-062, CAP-063
- [x] FR-006…FR-008, FR-010…FR-015 → transversales de la 008 (FR-010,
  FR-011, FR-012, FR-014, FR-016, FR-018…FR-020, FR-022, FR-023)
- [x] Clasificaciones de la 008 respetadas: `assist_pipeline/run` en D
  (D-01), suscripciones y asistentes de satélite en B, exposición en la 021

## Resultado de `analyze` (2026-11-15)

Sin hallazgos CRITICAL. Corregidos durante el análisis:

| Id | Severidad | Hallazgo | Arreglo |
|---|---|---|---|
| A1 | HIGH | El plazo vencido: `ws_send` no lanza `asyncio.TimeoutError`, sino `HAConnectionError` sin código; la regla de `outcome_unknown` no se podía implementar tal como estaba escrita | research R-4, data-model, plan y T005: `HAConnectionError` sin código de HA al confirmar → `outcome_unknown`; con código → `ha_error` |
| A2 | HIGH | Un `xfail` nuevo en el banco no lo admite el job si no está en `XFAIL_DEL_JOB`; T014 decía «xfail estricto» sin registrarlo | T014/T015: `XFAIL_PERMITIDOS_023` sumado a `XFAIL_DEL_JOB`; si una integración entera no carga, se quita de la configuración y la prueba pasa a unitarios con la causa |
| A3 | MEDIUM | FR-012 (`conversation_not_loaded`) solo se probaba en las tools de lista | T003: en las cuatro, también en la vista previa de procesar |
| A4 | MEDIUM | El `example` de `assist_pipeline/pipeline/create` estaba en data-model y research, no en FR-009 | FR-009 lo nombra |

Menores, anotados (no bloquean):

- **M1** (LOW): `local: "unknown"` para todo agente que no es el integrado,
  aunque sea, por ejemplo, Ollama en la red local. Hermes no tiene forma
  fiable de saberlo (el `iot_class` del manifiesto es de la integración, no
  de dónde corre el modelo); se prefiere no afirmar.
- **M2** (LOW): la forma de `device_id` (32 hex) es la de
  `uuid_util.random_uuid_hex()` del registro de dispositivos de Core
  2026.11.1; si una versión futura cambia, la validación rechazaría ids
  válidos (fail-closed, error claro).
- **M3** (LOW): la referencia cruzada a las tools de exposición de la 021 en
  el tema `conversation` depende del orden de integración (S-04); la que se
  integre segunda la completa.
- **M4** (LOW): S-02, `assist_pipeline:` y `ai_task:` sin internet en el
  banco, no se puede comprobar sin el CI (los manifiestos no están en la
  copia de `fuentes`); T014 dice qué hacer si no arrancan.
- **M5** (LOW): los alias del tema `conversation` pueden chocar con alias
  existentes (`statistics` ya chocó en la 029); T012 dice que se quitan los
  que choquen.

## Notas

- Dudas para el final: ninguna nueva. La variante «solo texto» de
  `assist_pipeline/run` sigue en D-01 de la 008.
