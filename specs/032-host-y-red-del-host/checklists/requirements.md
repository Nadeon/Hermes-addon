# Lista de comprobación de la especificación: host y red del host (032)

**Propósito**: validar que la spec está completa antes de implementar.
**Creada**: 2026-11-15
**Spec**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación innecesarios en las historias (las rutas
  del Supervisor son el contrato externo, no implementación).
- [x] Centrada en lo que necesita el administrador y en su seguridad.
- [x] Todas las secciones obligatorias completas.

## Completitud de los requisitos

- [x] Sin marcadores `[NEEDS CLARIFICATION]`: las decisiones están en
  Clarificaciones y research.
- [x] Requisitos comprobables y sin ambigüedad (cada uno con su test en la
  trazabilidad del plan).
- [x] Criterios de éxito medibles (SC-001…SC-006).
- [x] Escenarios de aceptación y casos límite definidos.
- [x] Alcance acotado: CAP-086 y CAP-090, FR-081 y FR-082 de la 008; fuera de
  alcance en research R-8.
- [x] Dependencias y supuestos identificados (019 para el tramo 2).

## Preparación

- [x] Cada FR traza a su FR y CAP de la 008.
- [x] Comprobación de la constitución principio por principio (plan).
- [x] Tareas en TDD con controles negativos, en dos tramos.
- [x] Rutas comprobadas en `fuentes/supervisor` (2026.11.0) y en
  `inventario/supervisor-rutas.tsv` (las 7, clase A).

## Resultado de `analyze` (2026-11-15)

Sin CRITICAL. Corregidos en los artefactos:

- **H1 (HIGH, inconsistencia de seguridad)**: la huella de `sv_set_swap`
  incluía `disk_free`, que cambia solo (logs, base de datos): casi ningún
  token habría valido. Sale de la huella; `insufficient_disk` se repite al
  confirmar (spec FR-011, research R-6, data-model, T005).
- **H2 (HIGH, mismo motivo)**: la huella de la interfaz incluía
  `wifi.signal` y `ready`, que fluctúan. Salen de la huella; T019 prueba que
  un cambio solo de esos campos no invalida el token.
- **M1 (MEDIUM)**: la longitud de la PSK WPA solo estaba en data-model y en
  T018; pasa a FR-008 (8–63 caracteres o 64 hexadecimales).
- **M2 (MEDIUM)**: `before` y la respuesta de `sv_create_vlan` no decían si
  llevaban la MAC; las tres usan la forma pública sin `mac`.
- **M3 (MEDIUM)**: el inventario de la 033 decía «sin argumentos» para
  `sv_shutdown_host`; tiene `confirmation_token`, exento como en
  `sv_reboot_host` (T009, contracts).

### Hallazgos menores (anotados, sin corregir)

- **L1**: T008 dice «`tests/test_generar_tabla.py` si compara el mapa»: lo
  compara (013); el agente lo verá al ejecutar la suite.
- **L2**: `wifi.mode` obligatorio aunque casi siempre sea `infrastructure`:
  es el precio de no dejar que el Supervisor rellene valores por defecto
  (R-4).
- **L3**: la PSK WEP no tiene regla de longitud (WEP es residual).
- **L4**: los recuentos de DOCS y README (número de tools por familia)
  dependen del orden de integración con otras sub-features.
- **L5**: FR-017 y las tareas de la guía reparten los alias entre los dos
  tramos (T011 los de host, T025 los de red); el tema se llama
  `host_control` aunque cubra las dos familias, porque `host` y `network` ya
  son alias de otros temas.

## Dudas para el final

- **D-032-1**: `sv_reload_network` sin token (research R-3). FR-082 de la 008
  dice «con confirmación» para las tres; aquí solo se confirma lo que cambia
  la red. Si el supervisor prefiere el texto literal, hay que darle token y
  anunciarla destructiva (invariante), con una vista previa que diga que no
  cambia nada.
- **D-032-2**: rechazo total de la interfaz principal, también para cambios
  inocuos (`mdns`/`llmnr`). Más simple y seguro; resta algo de utilidad.
- **D-032-3**: gateway en una interfaz secundaria o en una VLAN solo avisa
  (multi-WAN legítimo). La alternativa sería rechazarlo.
