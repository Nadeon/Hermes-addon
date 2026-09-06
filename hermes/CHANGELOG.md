# Changelog

## [0.39.0] — 2026-09-06

### Añadido — `auth_password` se comprueba de verdad, no solo su longitud

Antes bastaba con tener 12 caracteres, así que `123456789012` arrancaba el
add-on sin una queja. El login ya frena la fuerza bruta con un bloqueo global y
escalonado que deja el techo de un atacante en unos 2.000 intentos al día —y que
no se sube rotando de IP, porque el contador es global—. Con ese techo, una
password generada al azar es inalcanzable; el único caso que quedaba abierto era
la password **predecible**.

Ahora Hermes no arranca con una adivinable, y el mensaje dice cuál de las seis
reglas falla: pocos caracteres distintos, un trozo corto repetido, una tirada
seguida del abecedario, de los dígitos o de una fila del teclado, caracteres
estrenados en orden, una de las listas de más usadas, o una palabra del propio
contexto o de tu hostname público.

Las reglas siguen NIST SP 800-63B §5.1.1.2, que prohíbe las reglas de
composición del tipo «una mayúscula, un número y un símbolo». Los umbrales están
calibrados sobre 200.000 passwords generadas al azar para no rechazar ninguna
legítima: lo que salga de tu gestor de contraseñas pasa.

El motivo del rechazo nunca cita la password, porque ese mensaje acaba en el log
del add-on.

954 tests.

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
