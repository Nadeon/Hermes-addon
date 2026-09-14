# Changelog

## [1.0.7] — 2026-09-14

Siete fallos graves encontrados en un repaso completo del código, con un test
de regresión por cada uno y control negativo: los 19 tests nuevos de guarda
fallan contra el código de la 1.0.6. Actualiza cuanto antes.

### Fixed — El `confirmation_token` se usaba como ruta de fichero sin validar

Cualquier tool destructiva construía `CONFIRMATIONS_DIR / f"{token}.json"` con
el token tal cual, y al no encontrar en él un token vigente **borraba** ese
fichero. Con `confirmation_token="../options"` se borraba `/data/options.json`,
la configuración del propio add-on con `auth_password` dentro; con
`../write_rate_limit` se reseteaba el limitador de escrituras; con más `..` se
llegaba a `/config`. Ahora el token debe tener la forma exacta de un UUID4
antes de tocar el disco, y si no la tiene se rechaza sin construir ninguna ruta.

### Fixed — `fs_delete_file` no comprobaba la lista negra

`fs_delete_file("secrets.yaml")` devolvía `{"result": "ok"}` y lo borraba. Lo
mismo con la base de datos del recorder, certificados y claves privadas, e
`ip_bans.yaml`. El backup previo caía en `backups/sensitive/`, que Hermes no
lista ni restaura: la pérdida era irrecuperable desde aquí. `fs_write_file` y
`fs_move_file` sí lo comprobaban; delete se quedó fuera. Ahora rechaza con
`blacklisted`, con y sin token, igual que ellos.

### Fixed — `fs_set_secret` inyectaba YAML

El valor se concatenaba tal cual en `secrets.yaml`. Un salto de línea añadía
claves nuevas que sobreescribían secretos existentes, y la vista previa no lo
enseñaba porque solo muestra la clave. Un `: ` dejaba el fichero inválido y
Home Assistant sin arrancar, sin poder repararlo por Hermes porque el fichero
está en la lista negra. Un `#` truncaba el valor; `no` y `007` se convertían
en booleano y número.

Ahora el valor se escribe como escalar YAML entre comillas dobles, así que se
lee de vuelta exactamente igual sea cual sea su contenido; los caracteres de
control se rechazan antes de emitir la vista previa; la clave se valida con
`fullmatch`, porque `$` aceptaba un salto de línea final; y actualizar un
secreto guardado como escalar de bloque (`clave: |`) se rechaza en vez de
dejar las líneas de continuación pegadas al valor nuevo.

### Fixed — Los scripts clasificados como peligrosos se ejecutaban sin token

Home Assistant registra un servicio `script.<object_id>` por cada script, que
lo ejecuta sin ningún `entity_id` en los datos. La comprobación de entidades
restringidas solo miraba `entity_id`, así que `ha_call_service("script",
"peligroso")` pasaba sin confirmación aunque el script invocara
`shell_command.*`. Por la misma vía, `homeassistant.turn_on` con `entity_id:
all` o por área alcanza todos los dominios y tampoco se detectaba. Y
`ha_call_service_response` no consultaba las entidades restringidas en
absoluto.

`targets_restricted_entity` compara ahora también la pareja `dominio.servicio`
contra el set, trata los servicios genéricos de `homeassistant` como capaces
de alcanzar cualquier dominio, y `ha_call_service_response` la aplica y
rechaza con `entity_restricted`.

### Fixed — Una automatización recién guardada quedaba sin restringir

Al guardar con `ha_create_or_update_automation` se clasificaba bajo
`automation.<id_numérico>`, mientras Home Assistant deriva la entidad del
alias (`automation.<slug>`), que es lo que registra el escáner de arranque y
por lo que la invoca cualquiera. Una automatización nueva con
`shell_command.*` se podía disparar sin token hasta el siguiente reinicio del
add-on. Ahora se registra bajo el mismo entity_id que en el arranque.

### Fixed — `ha_create_or_update_scene` sobreescribía sin token si HA fallaba al leer

Un error transitorio al leer la configuración actual se trataba como "la
escena no existe", y ese camino crea sin vista previa ni token: la escena real
se reemplazaba entera. Ahora ese error devuelve `ha_unavailable` y no escribe
nada.

### Changed — El freno anti-fuerza-bruta del login es por IP, con techo global de respaldo

El freno era un único bloqueo global y escalonado. Bien contra la fuerza bruta,
pero convertía el login en un objetivo de denegación de servicio: una sola IP
reintentando justo al expirar cada bloqueo, 92 intentos por hora, muy por
debajo del límite pre-auth, mantenía `/oauth/authorize` en 429 el 100 % del
tiempo. Nadie podía volver a autorizar un conector mientras durase.

Ahora cada IP acumula sus propios fallos y su propio bloqueo exponencial, y el
nivel global solo cuenta los fallos de IPs que no están ya bloqueadas: hace
falta que veinte direcciones distintas fallen en cinco minutos para que salte,
que es lo que hace quien rota la IP para esquivar el primer nivel. Con
`network_mode: reverse_proxy` y `mcp_bind` en la red puente todas las
peticiones llegan con la IP del proxy, así que ahí los dos niveles coinciden,
como ya pasaba con el resto de límites por IP (ver el README).

## [1.0.6] — 2026-09-06

### Fixed — `sv_get_addon_options` no funcionaba con ningún add-on

Leía `/addons/{slug}/options/config`, un endpoint que el Supervisor reserva al
add-on que se consulta a sí mismo. A cualquier otra petición responde
`403 This can be only read by the app itself!`, así que la tool devolvía un
error siempre, para todos los add-ons, incluido el propio Hermes. Su
descripción prometía «devuelve las opciones actuales», que es exactamente lo
que no podía hacer.

Ahora las lee de `/addons/{slug}/info`, que las incluye. Sigue siendo la
versión enfocada de `sv_get_addon`: aquella devuelve el manifiesto entero
—schema, traducciones, red, permisos—, del orden de varios kilobytes para leer
cuatro valores. Devuelve `{"slug": ..., "options": {...}}`, con los secretos
redactados.

Se detectó llamando a las herramientas contra un Home Assistant en marcha. La suite
no podía verlo: **el test mockeaba el endpoint roto**, así que daba por buena
una tool que en producción no funcionaba nunca.

### Changed — La comprobación de redacción miraba solo la primera coincidencia

`test_addon_options_is_redacted` buscaba la primera aparición del endpoint en
el fichero y comprobaba que hubiera redacción cerca. Al cambiar de sitio esa
primera aparición, el test pasó a vigilar otra tool distinta sin que nada lo
delatara. Ahora comprueba, por tool, las tres que devuelven datos de un add-on.

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
