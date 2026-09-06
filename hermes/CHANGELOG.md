# Changelog

## [0.38.0] — 2026-09-06

Primera versión pública.

Hermes se desarrolló en privado desde abril de 2026. Las versiones anteriores no
se documentan aquí: nadie las ejecutó fuera de la instalación del autor, así que
un changelog de esos cambios no le sirve a nadie.

Lo que sí conviene saber de cómo llega esta versión:

- **Auditoría de seguridad completa** sobre las 185 herramientas y los 54
  módulos, con verificación adversarial de cada hallazgo y un test de regresión
  por cada corrección. Endurecimiento en autenticación, límites de recursos,
  validación de rutas, redacción de secretos en logs y anotaciones MCP.
- **Rotación de refresh tokens** con detección de reutilización, tope de sesiones
  activas y caducidad que no se estira al rotar.
- **Confirmación en dos pasos** para las acciones destructivas: la primera llamada
  devuelve una vista previa y un token; sin ese token no se ejecuta nada. El
  token está atado a la acción y a sus argumentos, caduca, y vale una sola vez.
- **Denylist de servicios** aplicada en el cliente de Home Assistant, no en cada
  herramienta, para que no haya forma de rodearla. Clasificación automática de
  scripts y automatizaciones que invocan servicios peligrosos.
- **Sandbox de `/config`**: resolución de la ruta y contención comprobadas antes
  de aplicar cualquier regla, listas negras por nombre, patrón y directorio, y
  allowlist restrictiva para `.storage/`.

940 tests, con control negativo por cada guarda: se reintroduce el fallo y se
comprueba que el test lo detecta.
