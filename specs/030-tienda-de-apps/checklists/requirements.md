# Checklist de calidad de la especificación: tienda de apps (030)

**Propósito**: validar que la especificación está completa y tiene calidad antes de planificar
**Creado**: 2026-11-14
**Especificación**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación más allá de los que fija la 008 y la 011 (nombres de tools, rutas del Supervisor, módulos y tabla que ya existen)
- [x] Centrada en el valor para el usuario (gestionar la tienda y las apps sin la interfaz, sin meter código ajeno a ciegas)
- [x] Escrita para quien mantiene Hermes
- [x] Todas las secciones obligatorias completas

## Completitud de los requisitos

- [x] No quedan marcadores [NEEDS CLARIFICATION] (las decisiones están en «Clarificaciones» y en research.md)
- [x] Los requisitos se pueden probar y no son ambiguos
- [x] Los criterios de éxito son medibles
- [x] Los criterios de éxito no dependen de la tecnología (salvo nombres de tools, rutas y familia, que son el contrato)
- [x] Todos los escenarios de aceptación están definidos
- [x] Los casos límite están identificados
- [x] El alcance está delimitado (sin versión concreta, sin iconos, sin `/v2`, sin la 015 ni la 026)
- [x] Dependencias y supuestos identificados (011 y 014 en la rama; 015 y 027 en paralelo; prueba en vivo pendiente)

## Preparación de la funcionalidad

- [x] Todos los requisitos funcionales tienen criterios de aceptación claros
- [x] Los escenarios de usuario cubren los flujos principales
- [x] La funcionalidad cumple los resultados medibles de los criterios de éxito
- [x] Trazabilidad: cada FR cita el FR de la 008 y la CAP que cubre

## Resultado de `analyze` (2026-11-14)

23 FR, 7 SC, 28 tareas en 2 tramos (T001–T014 y T015–T028); cobertura de
FR con tareas: 100 %. Sin marcadores ni datos personales. Constitución:
sin conflictos tras las correcciones.

Corregido (CRITICAL/HIGH):

- **A1 (HIGH)** — FR-014 decía «12 a las tools nuevas»; son 11 (las otras
  cuatro van a tools de la 1.1.2). Corregido.
- **A2 (HIGH)** — FR-012 y T018 suponían que `GET /addons/{slug}/info` da
  error para una app no instalada. En el Supervisor 2026.11.0 esa ruta
  reenvía a la ficha de la tienda (`installed: false`, `state: "unknown"`)
  y solo da 404 si la app no existe. Corregidos la detección
  (`addon_not_found` / `addon_not_installed`) y el test.
- **A3 (HIGH, principio IV)** — La vista previa de añadir un repositorio
  tapaba la contraseña de la URL mientras la ejecución la envía: callaba un
  efecto. Ahora lleva `credentials_hidden` (spec FR-002, data-model, T004).
- **A4 (MEDIUM, corregido por coste cero)** — El `MockHAClient` actual no
  registra `json_body` ni `timeout_seconds` ni responde errores con
  `status`; las tareas dicen que la fixture lo amplía.

Anotado (MEDIUM/LOW):

- **M1** — Desviación de FR-051 de la 008: no hay versión concreta porque el
  Supervisor 2026.11.0 ignora `{version}` en las tres rutas (research R-2).
  Va al CHANGELOG y a la fila CAP-082 de la matriz de la 008 (T027).
- **M2** — `sv_check_addon_availability` (research de la 008) se llama
  `sv_get_addon_availability` para heredar `readOnlyHint` por prefijo
  (research R-1).
- **M3** — Riesgo de fusión con la 027 (descripciones de `tools/addons.py` y
  tema `supervisor`) y la 015 (`tools/__init__.py`, `tool_families.py`,
  `command_table.py`, guía, anotaciones, quizá el formato de
  `_third_party_text`). Mitigación en plan («Riesgos») y T015.
- **M4** — La lista de `slug` integrados es la de 2026.11.0; uno nuevo en una
  versión futura daría token y un error del Supervisor al confirmar (nada se
  rompe). Plan, «Riesgos».
- **M5** — La detección de «No changelog/documentation found for app …»
  depende del texto exacto de 2026.11.0; se lee antes la ficha para que una
  app inexistente nunca salga como texto.
- **L1** — El encargo menciona «iconos»: la 008 los deja en clase B (binario
  para la interfaz) y siguen `deny`. Fuera de alcance.
- **L2** — `sv_update_addon` sigue emitiendo token aunque no haya
  actualización (el Supervisor lo rechaza al confirmar). No lo pide la 008;
  posible mejora (research R-3).
- **L3** — El alias `store` de la guía puede confundirse con el Marketplace
  de Core; el tema `app_store` lo aclara en su primera línea.
- **L4** — Añadir, recargar y reconstruir pueden pasar de 300 s; el error lo
  dice y la operación sigue en el Supervisor (plan, «Riesgos»).
