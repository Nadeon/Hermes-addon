# Changelog

## [1.0.5] — 2026-09-06

### Fixed — El identificador del recurso protegido no era el del servidor MCP

`/.well-known/oauth-protected-resource` anunciaba como `resource` la raíz del
host —`https://tu-host`— cuando el recurso protegido es el servidor MCP, que
vive en `https://tu-host/mcp`. Es la misma URL que el usuario pega en su
cliente.

La RFC 9728 pide al cliente comprobar que el `resource` de esos metadatos
corresponde con el recurso que está usando. Con los dos valores distintos no
puede casarlos, y un cliente estricto tiene motivo para no seguir adelante.

Por lo mismo, el puntero `resource_metadata` de la cabecera `WWW-Authenticate`
pasa a llevar el path insertado —`/.well-known/oauth-protected-resource/mcp`—,
que es la forma que define la RFC 9728 §3.1 para un recurso con path. Esa ruta
ya se servía.

El `issuer` y `authorization_servers` **no** cambian: el servidor de
autorización sí es el host, sin path.

Un test daba por buena la URL antigua, así que afirmaba el fallo en vez de
comprobar la regla.

## [1.0.4] — 2026-09-06

### Changed — Al rechazar `public_hostname`, Hermes propone el valor correcto

`public_hostname` es solo el hostname, pero la cadena que uno acaba de copiar
para pegarla en el cliente MCP es la URL entera: con `https://` delante y `/mcp`
detrás. Pegar esa es el error más fácil de cometer, y Hermes se negaba a
arrancar diciendo «sin esquema ni path ni barras» — correcto, pero dejándole a
quien lo lee el trabajo de deducir cuál era el valor bueno.

Ahora el mensaje termina proponiendo el valor limpio, cuando limpiarlo da algo
válido. Si no da nada válido, no se inventa una sugerencia.

Sigue negándose a arrancar: aceptar un hostname con path produciría URLs de
descubrimiento OAuth malformadas, y el fallo aparecería mucho más tarde y sin
relación aparente con la causa.

## [1.0.3] — 2026-09-06

### Added — El flujo OAuth deja rastro donde antes no dejaba ninguno

Un cliente MCP puede recibir su código de autorización y no volver nunca a
canjearlo. Cuando eso pasa, el log no decía **nada**: ni un error, ni un aviso.
Era indistinguible de que el usuario jamás hubiera llegado a autorizarse, y sin
forma de saber si el problema estaba en el servidor o en el cliente.

Tres señales nuevas:

- **`oauth_auth_failed` dice ahora el motivo**: `bad_password`, `unknown_client`
  o `redirect_uri_mismatch`. Los tres caminos devolvían el mismo
  «Authentication failed», así que la pantalla decía «contraseña incorrecta»
  aunque la contraseña fuera buena. El mensaje **en pantalla no cambia** —el
  motivo va solo al log—, siguiendo el mismo criterio que el endpoint del
  token. Distinguirlos ahí es seguro porque los tres se comprueban *después* de
  validar la contraseña.
- **`oauth_code_issued` registra a dónde va la redirección** (solo el host) y si
  venía `state`. Nunca la URL entera: lleva el código dentro.
- **`oauth_code_expired_unused`** avisa de los códigos que se emitieron y nadie
  presentó. Un código se borra en cuanto se toca el endpoint del token, con
  éxito o sin él, así que todo el que sobrevive hasta caducar es exactamente
  ese caso.

## [1.0.2] — 2026-09-06

### Fixed — Hermes anunciaba la versión equivocada

La pantalla de autorización, el endpoint `/health` y las tres líneas de arranque
del log decían **0.38.0** en una instalación de 1.0.1.

La versión está escrita a mano en dos sitios: `version:` en `config.yaml`, que
es lo que ve el Supervisor, y `__version__` en el paquete Python, que es lo que
Hermes enseña. El segundo seguía anunciando 0.38.0 mientras el primero subía
tres veces.

No afectaba al funcionamiento, pero sí a poder diagnosticar nada: tanto
`SECURITY.md` como `CONTRIBUTING.md` piden que digas qué versión ejecutas al
reportar un fallo, y el número que Hermes daba para eso era falso.

Los dos números no pueden derivarse uno del otro, porque `config.yaml` no viaja
dentro de la imagen —el `Dockerfile` copia solo `src/` y `run.sh`—. Así que la
sincronía la sostiene ahora un test, que falla si vuelven a separarse.

## [1.0.1] — 2026-09-06

### Fixed — El add-on se dejaba arrancar sin `auth_password` ni `public_hostname`

Las dos opciones estaban declaradas como obligatorias en el schema, pero
`options:` les daba `""` por defecto. Una cadena vacía es un valor **válido**
para los tipos `password` y `str`, así que el Supervisor las daba por
configuradas: el formulario no pedía nada y el botón de arrancar quedaba
disponible.

No era un agujero de seguridad —`run.sh` y `config.validate()` paran el arranque
si falta cualquiera de las dos, y siempre lo hicieron—, pero el error salía en
el log en vez de en el formulario, que es donde el usuario está mirando.

Ahora el schema exige longitud (`password(12,)` y `str(1,253)`) y `options:` las
deja en `null`, que es como se marca una opción obligatoria. El Supervisor
rechaza la configuración vacía antes de arrancar nada. El mínimo de 12 es el
mismo que aplica el código, y hay un test que comprueba que no se separen.

Se añaden siete tests del manifiesto, que hasta ahora no tenía ninguno: el
manifiesto lo valida el Supervisor, no Python, así que un error ahí no lo
detectaba nada y aparecía al instalar, en la máquina de otro. Uno de ellos
comprueba cada tipo del schema contra el regex real del Supervisor, porque un
tipo mal escrito hace que rechace el add-on entero.

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
