# Checklist de calidad de la especificación: actualizaciones del sistema (015)

**Propósito**: validar que la especificación está completa y tiene calidad antes de planificar
**Creado**: 2026-11-14
**Especificación**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación más allá de los que fijan la 008 y la 011 (nombres de tools, rutas del Supervisor, comandos de Core, módulos y tabla que ya existen)
- [x] Centrada en el valor para el usuario (actualizar sabiendo lo que va a pasar)
- [x] Escrita para quien mantiene Hermes
- [x] Todas las secciones obligatorias completas

## Completitud de los requisitos

- [x] No quedan marcadores [NEEDS CLARIFICATION] (las decisiones están en «Clarificaciones» y en research.md; lo que no se pudo decidir, en «Dudas para el final»)
- [x] Los requisitos se pueden probar y no son ambiguos
- [x] Los criterios de éxito son medibles
- [x] Los criterios de éxito no dependen de la tecnología (salvo nombres de tools, rutas y familia, que son el contrato)
- [x] Todos los escenarios de aceptación están definidos
- [x] Los casos límite están identificados
- [x] El alcance está delimitado (tienda 030, plugins 022, backup de la integración 031)
- [x] Dependencias y supuestos identificados (009, 010, 011, 013; prueba real pendiente en la VM de la 014)

## Preparación de la funcionalidad

- [x] Todos los requisitos funcionales tienen criterios de aceptación claros
- [x] Los escenarios de usuario cubren los flujos principales
- [x] La funcionalidad cumple los resultados medibles de los criterios de éxito
- [x] Trazabilidad: cada FR cita el FR de la 008 y la CAP que cubre

## Resultado de `analyze` (2026-11-14)

22 FR, 9 SC, 46 tareas en 3 tramos; cobertura de FR con tareas: 100 %; de SC
con tareas: 100 %. Sin marcadores ni datos personales. Constitución: sin
violaciones (VI con pendiente declarado, como manda FR-016 de la 008).

Corregido (CRITICAL/HIGH):

- **A1 (HIGH, principio IV)** — El primer diseño del token atado a la versión
  (research R-3) dependía de un registro en memoria que se perdía al
  reiniciar y no estaba en ningún FR. Ahora el hash incluye
  `_from_version`/`_to_version`, la tool relee antes de validar y responde
  `preview_outdated: true` con la pista; FR-008 y T006/T019/T034 lo dicen.
- **A2 (HIGH)** — La trazabilidad del plan citaba tareas que no existían
  (T040 en FR-017, T047, controles negativos T016/T029/T046). Alineada con
  tasks.md (T015, T028, T045; tramo 3 = T030–T046).
- **A3 (HIGH)** — S-01 decía que el tramo 1 añadía el título `OS`, pero
  `sv_update_os` es del tramo 2. Corregido: la regla del test de la tabla en
  el tramo 1 y el título en el tramo 2.
- **A4 (HIGH)** — Orden del tramo 2: la tabla (T023) necesita las tools
  registradas (T020) para `TestDedicadas`; decía T024. Corregido.
- **A5 (HIGH, principio IV)** — En data-model no estaba claro si las «notas»
  del OS (solo un aviso de reinicio) contaban como notas disponibles. Ahora
  `available: false` en los tres componentes y el aviso va en `text`.

Anotado (MEDIUM/LOW):

- **M1** — Desviación de la letra de FR-049 de la 008: HA no tiene notas de
  versión de Core ni del Supervisor en local (la del OS es solo un aviso). La
  vista previa lo dice y da la `release_url`; no se descarga nada (R-4).
- **M2** — Tres tramos en vez de los dos que estimaba la 008 (plan,
  «Tramos»).
- **M3** — Una tool más de las estimadas: `ha_list_updates` (R-9).
- **M4** — `POST /refresh_updates` (clase B en el inventario) pasa a
  `dedicated`: no es un alias exacto y es la que funciona con `manager` en v1
  (R-2). El inventario también dice que `/os/update` «reinicia», y no lo hace
  (R-13). Se anotan en la matriz; el TSV no se toca.
- **M5** — Plugins: el encargo pedía actualizarlos; la 008 los asigna a la 022
  por la tabla (FR-078). Aquí solo se listan (la actualización de Core
  depende de ellos) y el elemento remite a `sv_call_api`.
- **M6** — `hassio/update/core` estaba `dedicated` hacia `ha_call_service`
  (familia `services`), una imprecisión de la 011: ahora apunta a
  `sv_update_core`.
- **M7** — `config/entity_registry/get_entries` se usa dentro de las `ha_*`
  aunque es `deny` para las genéricas (clase B): la tabla solo gobierna las
  genéricas (R-9).
- **M8** — Prueba real de `sv_check_for_updates` y las tres `sv_update_*`
  pendiente manual en la VM de la 014 (quickstart.md, paso 3; T044).
- **M9** — La vista previa de Core ejecuta `POST /core/check` (hasta 120 s);
  no cambia nada en HA ni escribe `check_config_state.json` (R-6).
- **M10** — Conflictos de fusión previsibles con la 013, 019, 022, 028 y 030
  en `tools/__init__.py`, `_annotations.py`, `guide.py`, `tool_families.py`,
  `command_table.py`, `tests/test_command_table.py`, la configuración del
  banco (`template:`) y el CHANGELOG.
- **M11** — Dudas para el final: D-1 (Hermes actualizándose por Core), D-2
  (backup antes del OS), D-3 (saltar el bloqueo por configuración inválida).
