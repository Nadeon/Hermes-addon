# Lista de calidad de la especificación: configuración del sistema (021)

**Propósito**: validar que la spec está completa antes de planificar
**Creada**: 2026-11-15
**Spec**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación en la spec más allá de los nombres de
  tools y comandos, que son el contrato del programa (como en la 008, la 012
  y la 029)
- [x] Centrada en el valor para el administrador
- [x] Secciones obligatorias completas

## Requisitos

- [x] Ningún marcador [NEEDS CLARIFICATION]: las decisiones se tomaron con la
  008 y el código de HA y están en Clarificaciones y research; lo que no se
  pudo decidir va en «Dudas para el final»
- [x] Requisitos comprobables y sin ambigüedad (cada FR con su test en el plan)
- [x] Criterios de éxito medibles
- [x] Escenarios de aceptación por historia
- [x] Casos límite identificados
- [x] Alcance delimitado: CAP-068 (029), red del host (032), opciones de Core
  del Supervisor (022), nube y credenciales (clase D y D-01) fuera, dicho
- [x] Dependencias y supuestos: base `c4a57bf` con todo lo necesario

## Preparación

- [x] Cada FR traza a un FR y una CAP de la 008 (tabla de trazabilidad del
  plan)
- [x] Las historias cubren los flujos principales (núcleo, exposición,
  usuarios, red y HTTP, analytics y labs, compatibilidad)
- [x] Tres tramos, como dice la 008, con tareas TDD y controles negativos

## Resultado de analyze (2026-11-15)

Corregido en los artefactos (CRITICAL/HIGH):

- **A1 (HIGH, cobertura de FR-020)**: ninguna tarea probaba
  `unknown_command` → `unsupported_by_ha_version`, y `http/config` no existe
  en la versión mínima declarada de HA (2024.10). Añadido a T005, T039 (j) y
  T040, y como caso límite en la spec.
- **A2 (HIGH, coherencia)**: el motivo de `protected_user` era uno solo, pero
  en el banco el propietario es también el usuario de Hermes (dos motivos a
  la vez): el test del banco no sabría cuál esperar. Ahora `reasons` con
  todos los que aplican (data-model, T022).
- **A3 (HIGH, principio V)**: la spec decía en un supuesto que `analytics`,
  `labs` y `network` no se cargan sin `default_config:`; `bootstrap.py` los
  tiene en `DEFAULT_INTEGRATIONS` (se cargan siempre). Corregido.

Anotado, menor (no bloquea):

- **A4 (MEDIUM)**: FR-073 de la 008 pedía las sesiones de los usuarios; no se
  puede (research R-5). Desviación justificada y duda D-1; la fila CAP-056 de
  la matriz de la 008 lo dirá (T051).
- **A5 (MEDIUM)**: `ha_list_users` devuelve `username` (nombre de acceso), que
  HA da a los administradores y la interfaz enseña. No es un secreto, pero es
  media credencial: nunca va al log (T033). Si el mantenedor prefiere
  ocultarlo, es un cambio de una línea.
- **A6 (MEDIUM)**: el aviso de `server_host` se da cuando la lista no incluye
  `0.0.0.0` ni `::`; es conservador (en HA OS el Supervisor llega a Core por la
  red interna de Docker). Duda D-3 (avisar o rechazar).
- **A7 (LOW)**: la estimación de la 008 era «~12» tools; son doce. Research
  R-2 de la 008 nombraba `ha_detect_core_config`, `ha_get_expose_new_entities`
  y `ha_list_user_sessions`: la primera va por la tabla (FR-071 de la 008), la
  segunda se pliega en la lista (research R-3) y la tercera no es posible
  (R-5).
- **A8 (LOW)**: `_DENY_TRAS_REVISION` es un mecanismo nuevo del test de la
  clase A (mismo patrón que `_POR_LA_TABLA`); la convergencia del programa
  (T026 de la 008) tiene que contarlo como «no pendiente».
- **A9 (LOW)**: la definición de administrador y el efecto de desactivar vienen
  de `homeassistant/auth/`, que no está en la copia de fuentes; el banco
  (T030) lo comprueba contra HA real.
- **A10 (LOW)**: cambiar el alias `network` de `system_status` a
  `core_network` cambia lo que ve quien ya lo usaba; el CHANGELOG lo dice
  (T050) y el tema nuevo remite a la lectura.
