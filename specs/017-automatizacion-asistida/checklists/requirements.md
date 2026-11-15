# Lista de calidad de la especificación: automatización asistida (017)

**Propósito**: comprobar que la spec está completa y es de calidad antes de
implementar.
**Creada**: 2026-11-14
**Spec**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Cada FR traza a su FR y CAP de la 008 (FR-058…FR-062; transversales
      FR-010…FR-012, FR-015, FR-018…FR-021, FR-023)
- [x] Escrita para quien mantiene Hermes: qué y por qué; el cómo, en plan,
      research, data-model y contracts
- [x] Todas las secciones obligatorias completas

## Completitud de los requisitos

- [x] Ningún marcador [NEEDS CLARIFICATION]: las decisiones están en
      «Clarificaciones» con su research
- [x] Requisitos verificables y sin ambigüedad (formas en data-model, errores en
      contracts)
- [x] Criterios de éxito medibles (SC-001…SC-007)
- [x] Escenarios de aceptación por historia y casos límite
- [x] Alcance acotado (fuera de alcance explícito) y supuestos (S-01…S-04)

## Preparación

- [x] Cada FR tiene tareas y tests (tabla de trazabilidad de plan.md)
- [x] Tareas en TDD con controles negativos enumerados en el cierre de cada
      tramo (T016, T025, T037, T054)
- [x] Tramos que dejan la suite en verde y se commitean por separado (4; la
      008 decía 3: research R-12)
- [x] Comprobación de la constitución principio por principio (plan.md)

## Resultado de `analyze` (2026-11-14)

Corregidos al especificar (CRITICAL/HIGH):

| ID | Severidad | Hallazgo | Arreglo |
|---|---|---|---|
| A1 | HIGH | La espera de trigger rechazaba solo `webhook` y `conversation` (lista negra): un trigger desconocido o personalizado pasaba con una anotación de solo lectura que podía ser falsa. Contra el principio III («ante la duda, se deniega») y el V | Lista cerrada en research R-8 (plataformas de Core que escuchan; `<integración>.<nombre>` y `device` solo de integraciones incluidas, comprobado con `manifest/get`, y sin `webhook`, `conversation`, `samsungtv`, `webostv`, `lg_netcast`); error `trigger_not_allowed`; FR-009, contracts, T040 y T054 |
| A2 | HIGH | La fila de la matriz de pruebas (T009) y el alta en `PROBADAS_017` (T012) en commits distintos dejaban `test_matriz_pruebas` en rojo entre ellos | T009 con T012, y T020 con T023, en el mismo commit |
| A3 | HIGH | SC-004 prometía ningún centinela en los ficheros de token, pero el `yaml` omitible de `ha_save_blueprint` se guarda ahí (spec 007) | Excepción explícita en FR-015 y SC-004, igual que el `config` de las automatizaciones |
| A4 | HIGH | La spec solo admitía blueprints de `automation` y `script`; HA 2026.11.1 registra también `template` (`components/template/helpers.py`), y `search/related` no tiene tipo para él | `template` admitido en las cinco tools; en el borrado, `used_by: null` con motivo (research R-3) |

Menores, anotados y no corregidos:

| ID | Severidad | Hallazgo | Estado |
|---|---|---|---|
| M1 | MEDIUM | FR-062 de la 008 dice «una configuración que HA rechazaría se devuelve como error sin token»; `validate_config` solo valida triggers, condiciones y acciones, así que un `mode` inválido sigue dando token (HA lo rechaza al guardar) | Dicho en la vista previa (`not_validated`) y en research R-9; duda D-1 |
| M2 | MEDIUM | `import_failed`, `content_changed` y `trigger_not_allowed` están en contracts y data-model, no todos en el texto de la spec | Aceptado: la spec describe el comportamiento; los códigos son contrato |
| M3 | MEDIUM | El tramo C puede ir en paralelo con el B y ambos tocan `_annotations.py`, `guide.py`, `command_table.py` y `tools/__init__.py` | El segundo en integrarse resuelve (tasks, «Dependencias») |
| M4 | MEDIUM | La espera de trigger usa `manifest/get` por dentro, que es de la 029 (pendiente de tool dedicada) | Solo lectura interna, como `search/related`; no cambia su entrada de la tabla |
| L1 | LOW | `ha_import_blueprint` vuelve a descargar al confirmar: si la URL deja de responder entre los dos pasos, no se puede confirmar | Deliberado (research R-1): sin la descarga no hay huella que comparar |
| L2 | LOW | La lista cerrada de triggers está escrita a mano contra 2026.11.1 | Duda D-3 |

## Dudas para el final

- **D-1**: ¿Basta con `not_validated` en la validación al guardar, o se
  quiere algo más (p. ej. comprobar `mode` y `max` en Hermes con el esquema de
  HA copiado)? HA no expone otra validación por WebSocket.
- **D-2**: Las descripciones de los triggers y condiciones por propósito (sus
  `options`) solo salen por `trigger_platforms/subscribe` y
  `condition_platforms/subscribe` (clase B). Si el primer mensaje de esas
  suscripciones trae el catálogo entero, una tool de un solo mensaje (como las
  de FR-009 de la 008) podría darlas; queda fuera de esta sub-feature.
- **D-3**: La lista cerrada de triggers de `ha_wait_for_trigger` hay que
  revisarla al cambiar la versión de HA de referencia (un trigger nuevo con
  efectos, o una tele nueva con «encender»).
- **D-4**: Los importadores de GitHub, gist, foro y web de HA no se prueban en
  el banco (sin internet): prueba manual pendiente en la hoja de ruta.
- **D-5**: La 008 dimensionó la 017 en 3 tramos; se proponen 4.

## Notas

- Línea base al especificar (Windows, punta `cc92b4a`): 2357 passed, 65
  skipped, 6 failed (los 6 conocidos).
- Implementar exige la 012 integrada (S-01, T001).
