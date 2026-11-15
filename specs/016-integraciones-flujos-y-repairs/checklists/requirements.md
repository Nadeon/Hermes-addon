# Checklist de calidad de la especificación: integraciones, flujos y Repairs (016)

**Propósito**: validar que la especificación está completa y tiene calidad antes de planificar
**Creado**: 2026-11-14
**Especificación**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación más allá de los que fija la 008 (nombres de tools, familias, comandos y rutas de HA que ya existen)
- [x] Centrada en el valor para el usuario (atender descubiertos, ajustar integraciones, subentries, arreglar avisos)
- [x] Escrita para quien mantiene Hermes
- [x] Todas las secciones obligatorias completas

## Completitud de los requisitos

- [x] No quedan marcadores [NEEDS CLARIFICATION]
- [x] Los requisitos se pueden probar y no son ambiguos
- [x] Los criterios de éxito son medibles
- [x] Los criterios de éxito no dependen de la tecnología (salvo nombres de tools y familias, que son el contrato)
- [x] Todos los escenarios de aceptación están definidos
- [x] Los casos límite están identificados
- [x] El alcance está delimitado (012, 017, 024 y 025 fuera, dicho)
- [x] Dependencias y supuestos identificados (S-01…S-05; la implementación espera a la 011 integrada)

## Preparación de la funcionalidad

- [x] Todos los requisitos funcionales tienen criterios de aceptación claros
- [x] Los escenarios de usuario cubren los flujos principales
- [x] La funcionalidad cumple los resultados medibles de los criterios de éxito
- [x] Trazabilidad: cada FR cita el FR de la 008 y la CAP que cubre

## Notas

- Decisiones tomadas sin el mantenedor (en «Clarificaciones» de la spec y en
  research.md): `ha_list_config_flow_domains` en vez de
  `ha_list_flow_handlers`; token de `ha_update_config_entry` solo al pasar una
  preferencia a `true`; ignorar sin token; cada envío de un paso de reparación
  con token; `domain` e `issue_id` en `ha_continue_repair_fix`; reconfigure y
  flujos de subentry sin token; idioma de HA sin argumento nuevo y traducciones
  fail-soft; dos familias (`integration_flows`, `repair_flows`);
  `ha_abort_subentry_flow` añadida; integración de prueba propia en el banco.

## Dudas para el final (para el mantenedor)

- **D-1**: La 008 propone `ha_list_flow_handlers`, pero ese nombre lo retiró la
  1.1.x por mentir y un test impide que vuelva. Se usa
  `ha_list_config_flow_domains`. ¿Conforme?
- **D-2**: Reconfigurar una entrada (`ha_start_reconfigure_flow` +
  `ha_continue_config_entry_flow`) y crear o reconfigurar una subentry por su
  flujo van sin token, como los flujos de configuración y de opciones de la
  1.1.2 y como dice la 008. Un reconfigure puede cambiar credenciales o la
  dirección de un equipo y recarga la integración: el principio IV podría
  pedir token en el paso final. No se cambia en la 1.2.0 (afectaría también a
  las tools de la 1.1.2).
- **D-3**: `ha_start_repair_fix` no pide token, aunque algunas integraciones
  terminan el flujo al abrirlo (en Core 2026.11.1, los avisos del Supervisor
  sin sugerencias: HA retira el aviso, que es obsoleto). Se dice en la
  descripción y en `finished_on_start`. Alternativa: token también al abrir
  (dos tokens por arreglo).
- **D-4**: `ha_start_config_entry_flow`, `ha_continue_config_entry_flow`,
  `ha_start_options_flow` y `ha_continue_options_flow` se anuncian idempotentes
  (por defecto del clasificador) y no lo son; las nuevas de la 016 sí se marcan
  no idempotentes. Corregir las de la 1.1.2 cambia sus hints (FR-020 de la 008
  lo prohíbe en la 1.2.0).
- **D-5**: La API de HA no dice a qué aviso pertenece un flujo de reparación;
  `ha_continue_repair_fix` comprueba el dominio, pero no puede distinguir dos
  flujos del mismo dominio abiertos a la vez. La vista previa lo dice.
- **D-6**: Los textos de Repairs salen en el idioma configurado en HA, sin
  argumento para pedir otro (los esquemas de la 1.1.2 son la referencia).
- **D-7**: El banco carga una integración de prueba propia
  (`tests/banco/ha_config/custom_components/banco_flujos/`). Es configuración
  del banco, no código de producto, pero es código Python que corre dentro del
  HA de prueba. ¿Conforme, o se prefiere `kitchen_sink` (con sus efectos sobre
  el resto del banco y sin descubrimiento ignorable ni reconfigure de entrada)?

## Resultado de `/speckit-analyze` (2026-11-14)

Cobertura: 26 FR, 26 con tareas (100 %); 45 tareas, todas trazadas a FR, SC o
cierre de tramo; 7 SC, todos con tarea. Constitución: tabla principio a
principio en plan.md; sin conflictos con un MUST (la única desviación, el
fail-soft de las traducciones, no es una decisión de seguridad y está
justificada en la fila III).

Corregidos al analizar (HIGH y MEDIUM):

- **H-1**: el nombre `ha_list_flow_handlers` de la 008 chocaba con
  `test_flow_handlers_tool_renamed_to_what_it_does` → `ha_list_config_flow_domains`
  y corrección de la docstring de `ha_list_configured_domains` (FR-003, T006,
  T009; D-1).
- **H-2**: la vista previa de `ha_continue_repair_fix` no podía saber a qué
  aviso pertenece el flujo → `domain` e `issue_id` obligatorios,
  `flow_mismatch` y nota en la vista previa (FR-013, T036; D-5).
- **M-1**: reactivar el sondeo también recarga la integración (sin token) y la
  respuesta no lo decía → campo `reloaded` (FR-004, data-model, T007).
- **M-2**: los textos traducidos los escribe cada integración y no estaban
  marcados → `_third_party_text` (FR-015, data-model, T032).
- **M-3**: el banco no podía recrear el aviso para probar el abort → la
  integración de prueba crea dos avisos (T012, T042).
- **M-4**: un flujo de subentry abierto no se podía cerrar → `ha_abort_subentry_flow`
  (FR-007, research R-4).

Anotados, sin cambio (MEDIUM/LOW):

- **M-5**: principio IV frente a los flujos sin token (reconfigure, subentries,
  abrir un arreglo): decisión de la 008 y coherencia con la 1.1.2 (D-2, D-3).
- **M-6**: el `GET` de un flujo de reparación repite el paso actual sin datos;
  es lo que hace la interfaz (research R-5; riesgo en plan.md).
- **M-7**: el generador y el test de la vía D los cambian igual la 012 y la
  016; lo hace la primera que se implemente (S-03).
- **L-1**: la forma de los dispositivos por subentry en el registro se fija en
  el banco (dos formas aceptadas).
- **L-2**: `ha_list_repairs` hace dos lecturas más por llamada (idioma y
  textos); acotadas a los dominios devueltos.
