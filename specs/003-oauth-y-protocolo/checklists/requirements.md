# Lista de calidad de la especificación: Hermes 1.1.0 — OAuth y protocolo

**Propósito**: validar que la especificación está completa y es de calidad antes de planificar.
**Creada**: 2026-11-14
**Funcionalidad**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación (lenguajes, frameworks, APIs)
- [x] Centrada en el valor para el usuario y en sus necesidades
- [x] Escrita para personas no técnicas
- [x] Todas las secciones obligatorias completas

## Completitud de los requisitos

- [x] No queda ningún marcador [NEEDS CLARIFICATION]
- [x] Los requisitos se pueden probar y no son ambiguos
- [x] Los criterios de éxito se pueden medir
- [x] Los criterios de éxito no dependen de la tecnología
- [x] Todos los escenarios de aceptación están definidos
- [x] Los casos límite están identificados
- [x] El alcance está acotado
- [x] Dependencias y supuestos identificados

## Preparación de la funcionalidad

- [x] Todos los requisitos funcionales tienen criterios de aceptación claros
- [x] Los escenarios de usuario cubren los flujos principales
- [x] La funcionalidad cumple los resultados medibles de los criterios de éxito
- [x] No se filtran detalles de implementación a la especificación

## Notas

- **Detalles técnicos inevitables**: igual que en la spec 001, el «usuario» administra Home Assistant a través de un cliente MCP, y los nombres de protocolo (`client_id`, `iss`, `WWW-Authenticate`, `isError`, opciones del add-on) son la interfaz que ve. Se nombran porque son el contrato observable, no por cómo se implementan. Las decisiones de implementación (módulos, bibliotecas, resolvedor DNS, subclase del servidor MCP) están en plan.md y research.md.
- **Sin preguntas al mantenedor**: estaba ausente. Las dudas se resolvieron con sus decisiones (CIMD con DCR de respaldo, bajar `response_max_bytes`, redactar el log por defecto, nada rompe a los clientes ya autorizados) y el resto quedó como supuesto (S-01…S-16).
- **Trazabilidad**: cada FR cita su origen (R-CIMD-n, R-ISS-n, R-SCOPE-n, R-AUD-1, R-LIM-n, R-SRV-n, decisión 10, doc. 11 §8 o principio). Tabla completa en research.md.
- **Validación**: una iteración. Se corrigió un ejemplo de IP del escenario 3.1 para usar rangos privados y CGNAT reales.
