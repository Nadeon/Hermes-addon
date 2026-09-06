# Changelog

## [1.0.0] — 2026-09-06

Primera versión publicada.

Hermes se desarrolló en privado desde abril de 2026. Las versiones anteriores no
llegaron a instalarse fuera de la máquina del autor —no hubo tags ni imágenes—,
así que no se documentan una a una: un changelog de esos cambios no le sirve a
nadie. Lo que sí conviene saber de cómo llega esta versión:

- **Auditoría de seguridad completa** sobre las 185 herramientas y los 54
  módulos, con verificación adversarial de cada hallazgo y un test de regresión
  por cada corrección. Endurecimiento en autenticación, límites de recursos,
  validación de rutas, redacción de secretos en logs y anotaciones MCP.
- **OAuth 2.1 con PKCE obligatorio**, registro dinámico de clientes, tokens
  opacos guardados solo como hash, y rotación de refresh tokens con detección de
  reutilización, tope de sesiones activas y caducidad que no se estira al rotar.
- **`auth_password` se comprueba, no solo se mide.** El login frena la fuerza
  bruta con un bloqueo global y escalonado que deja el techo de un atacante en
  unos 2.000 intentos al día, y que no se sube rotando de IP. Con ese techo una
  password generada al azar es inalcanzable, así que lo que se comprueba es que
  no sea *adivinable*: repeticiones, tiradas del teclado, listas de las más
  usadas y palabras del propio contexto. Las reglas siguen NIST SP 800-63B
  §5.1.1.2, y los umbrales están calibrados sobre 200.000 passwords generadas al
  azar para no rechazar ninguna legítima.
- **Confirmación en dos pasos** para las acciones destructivas: la primera
  llamada devuelve una vista previa y un token; sin ese token no se ejecuta
  nada. El token está atado a la acción y a sus argumentos, caduca, y vale una
  sola vez.
- **Denylist de servicios** aplicada en el cliente de Home Assistant, no en cada
  herramienta, para que no haya forma de rodearla. Clasificación automática de
  scripts y automatizaciones que invocan servicios peligrosos.
- **Sandbox de `/config`**: resolución de la ruta y contención comprobadas antes
  de aplicar cualquier regla, listas negras por nombre, patrón y directorio, y
  allowlist restrictiva para `.storage/`.

954 tests, con control negativo por cada guarda: se reintroduce el fallo y se
comprueba que el test lo detecta.
