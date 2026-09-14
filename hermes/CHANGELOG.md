# Changelog

## [1.0.9] — 2026-09-14

Cierra los issues #2, #3, #6, #7, #8 y #9: lo que el repaso completo dejó
fuera de la 1.0.8 por bajo impacto o por exigir una decisión. Ninguno afecta
al uso diario con Tailscale Funnel; el #6 solo aplica a `reverse_proxy` en la
red puente. Un test de regresión por cambio, con control negativo.

### Changed — `fs_search_in_config` ejecuta la expresión regular en un proceso aparte (#2)

La heurística sintáctica de la 1.0.8 rechaza cuantificadores anidados y
retrorreferencias, pero no la explosión por alternativas solapadas: `(a|aa)+$b`
contra 38 «a» tarda 20 segundos y se multiplica por 2,6 cada dos caracteres
más. Como el motor `re` de CPython no se puede interrumpir, un patrón así
dejaba colgado para siempre un hilo del pool de `asyncio.to_thread`.

Ahora el escaneo corre en un proceso hijo (contexto `spawn`, no `fork`: el
add-on tiene un bucle de eventos con sockets y locks que un fork heredaría en
mal estado) con un plazo de 10 segundos; al vencer, se le envía SIGTERM y, si
hace falta, SIGKILL, y la herramienta devuelve `search_timeout`. La lista de
ficheros legibles la sigue calculando el padre: el hijo recibe rutas ya
filtradas por la lista negra y no decide nada. La heurística se queda como
primera capa barata. Coste aceptado: unas décimas de segundo por búsqueda
para arrancar el intérprete.

### Fixed — Los backups de `a/b.yaml` y `a__b.yaml` ya no comparten nombre (#3)

El aplanado de la ruta sustituía `/` por `__` y no era reversible. Los backups
nuevos codifican `%` como `%25` y `/` como `%2F`, que sí lo es. Los ficheros
antiguos siguen contando para la rotación y siguen siendo restaurables: los
lectores aceptan ambos formatos, y un nombre antiguo ambiguo se marca con
`legacy_name` y sus posibles rutas. La ambigüedad desaparece sola conforme
rotan los backups antiguos. El destino de una restauración es siempre la ruta
que pasa quien llama; el nombre del backup solo elige el origen.

### Added — `trusted_proxy_ips` (#6)

uvicorn solo cree `X-Forwarded-For` desde `127.0.0.1`, así que con
`reverse_proxy` y `mcp_bind` en la red puente todas las peticiones llegaban
con la IP del proxy y los tres límites por IP —pre-auth, fallos de
autenticación y freno del login— se convertían en uno global. La opción
nueva admite IPs sueltas o rangos CIDR (`172.30.32.0/23` es la red puente de
HAOS), se valida al arrancar y se registra en `hermes_started`. Vacía por
defecto: el modo `tailscale` no la necesita. Quien esté dentro de un rango de
confianza puede falsificar la IP del cliente, que solo alimenta límites y
logs, nunca la autorización.

### Changed — OAuth: cuatro flecos de la especificación (#7)

- `resource` (RFC 8707) se acepta en `/authorize` y `/token`, se compara con el
  único recurso, el servidor MCP, y cualquier otro valor devuelve
  `invalid_target`. Se guarda en el código de autorización como audiencia.
- PKCE se comprueba antes de enseñar el formulario y antes de mirar la
  contraseña: un cliente sin PKCE recibe un 400 que explica que el error es
  suyo, y ya no le cuesta al dueño ni la contraseña ni un intento del freno.
- `/.well-known/oauth-authorization-server/mcp` se sirve igual que la raíz
  (RFC 8414 §3.1). Cada 404 era un viaje más por Funnel.
- `redirect_uri` omitido en el token endpoint se registra en el log como
  `oauth_token_redirect_uri_omitted`. No se rechaza: PKCE ya ata el código a
  quien lo pidió, y no hay evidencia de que el cliente de Claude lo envíe;
  rechazarlo podría romper un flujo que hoy funciona. Si el log demuestra que
  nadie lo omite, se endurece.

### Fixed — Arranque y apagado: cinco observaciones (#8)

- El servidor de health comprueba el bind antes de arrancar y, si falla,
  registra `health_bind_failed` con host, puerto, errno y una pista, en vez de
  morir sin una línea. `HERMES_HEALTH_BIND` es una escotilla por variable de
  entorno solo para desarrollo fuera de HAOS; no es opción del add-on.
- Apagado ordenado: `S6_KILL_GRACETIME` sube a 10 s en la imagen, uvicorn
  recibe `timeout_graceful_shutdown=3`, y la espera de Hermes queda entre
  ambos. Un test lee el Dockerfile y el código para que los tres números no
  se separen.
- `health_startup_grace_seconds` se documenta como presupuesto **por paso**
  del arranque, que es lo que siempre fue, y se registra en el paso 4.
- La espera de Tailscale solo mira interfaces `tailscale*`. Antes cualquier
  dirección CGNAT valía, y un uplink LTE o satélite la satisfacía sin
  Tailscale. El modo userspace no crea ninguna interfaz, como ya exigía el
  README.
- Un `version` numérico en `/core/info` ya no aborta el arranque.

### Docs — Los 502 en ráfagas paralelas (#9)

El README, en ambos idiomas, explica el fallo intermitente que motivó el
repaso: en ráfagas de 6 o más llamadas en paralelo, entre el 15 % y el 30 %
vuelven con un 502 de Cloudflare para `api.anthropic.com` y nunca llegan a
Hermes. Cómo reconocerlo en el log y cómo aislar el lado de Funnel.

## [1.0.8] — 2026-09-14

Los 22 fallos restantes del repaso completo que empezó en la 1.0.7, con un
test de regresión por cada uno y control negativo (cada test nuevo falla
contra el código anterior). Ninguno es un agujero de seguridad como los de
la 1.0.7, pero varios rompen funciones enteras o fuerzan reautorizaciones.

### Fixed — OAuth: la ventana de gracia del refresh token no devolvía el sucesor

Si Claude perdía la respuesta de una rotación y reintentaba con el token
anterior, Hermes contestaba dentro de la ventana de gracia con un access
token **sin** `refresh_token`: solo tenía el hash del sucesor y no podía
devolverlo. El cliente se quedaba con el viejo, y una hora después ese viejo
ya estaba fuera de gracia: se revocaba la cadena entera y tocaba volver a
autorizar. Era una reautorización forzada con origen en el código.

Ahora, al rotar, el sucesor se guarda sellado con AES-GCM bajo una clave
derivada del valor del token que se presenta, que nunca está en disco. Solo
quien presente ese token puede abrirlo, que es exactamente el cliente que
reintenta. La gracia exige además que el sucesor siga siendo la cabeza viva
de la cadena: un token dos rotaciones por detrás ya no se atiende, es
reutilización y revoca todo. Antes esa réplica obtenía un access token
válido sin disparar la alarma.

### Fixed — OAuth y middleware, ocho más

- `redirect_uri` con query recibía `?tenant=42?code=…`; ahora se añade con `&`.
- Revocar un refresh token ya rotado no tocaba la sesión viva; ahora sigue la
  cadena entera, como pide la RFC 7009.
- Un `code_verifier` fuera del alfabeto de la RFC 7636 producía un 500 con
  traza desde un endpoint sin autenticar; ahora es `invalid_grant`.
- Las respuestas del token endpoint llevan `Cache-Control: no-store`.
- El código de autorización ya no se guarda en claro dentro de su fichero.
- `/.well-known/oauth-protected-resource/<otro path>` responde 404 en vez de
  anunciar `/mcp` como recurso de rutas que no existen.
- Las rutas OAuth públicas con barra final (`/oauth/token/`) devolvían 401, que
  el cliente leía como fallo de registro.
- El cubo de fallos de autenticación se vaciaba entero al superar 10.000 IPs,
  reseteando el contador de todas; ahora purga primero las entradas con menos
  fallos. Y el log de errores del MCP perdía las cabeceras repetidas al
  reconstruir la respuesta.

### Fixed — Arranque y ciclo de vida

- `startup: services` arrancaba Hermes **antes** de Home Assistant Core, al
  revés de lo que decía su comentario; en hardware lento el paso 8 agotaba su
  plazo y salía con error. Ahora es `application`.
- Una caída larga de Core dejaba Hermes parado para siempre: `/health` daba
  503 a los 300 s, el vigilante reiniciaba, el arranque exigía Core y fallaba,
  y tras varios intentos el Supervisor se rendía. El paso 8 ya no es fatal, y
  `/health` devuelve 200 con `degraded_long` en vez de 503: reiniciar nunca
  arregla una caída de Core, y el bucle de reconexión se recupera solo.
- `call_service_auto_classify_dangerous: false` era imposible: `jq` con
  `// empty` trata `false` como vacío y caía al valor por defecto.
- La comprobación de versión de Core abortaba el arranque ante una respuesta
  transitoria no reintentable (`version: "landingpage"`, cuerpo no JSON).
- La protección anti crash-loop corría después de validar la configuración,
  así que un bucle por configuración inválida, el caso real del 6 de
  septiembre, nunca contaba; ahora corre antes. Un fichero de arranques
  corrupto la desactivaba para siempre, y el umbral exigía un arranque más de
  los que el Supervisor llega a hacer.
- Los ficheros de confirmación caducados solo se limpiaban al arrancar; ahora
  también cada hora.

### Fixed — Cliente de Home Assistant

- `ws_send` retenía el lock durante toda la espera de respuesta: una llamada
  colgada serializaba todo el tráfico WebSocket hasta 30 s.
- Al caer la WebSocket solo se fallaban los comandos pendientes; las
  suscripciones de `ha_render_template` y las colas de `ha_wait_for_event`
  esperaban su propio timeout con HA caída.
- `ha_cancel_wait` tardaba hasta 15 s en hacer efecto.
- `ha_render_template` aceptaba un timeout sin tope; se acota a 1-60 s.
- El hash que ata un token de confirmación a sus argumentos podía colisionar:
  `{"x": 1.5}` y `{"x": {"__float__": "1.5"}}` daban el mismo. Las claves de
  usuario que empiezan por `__` se escapan.
- `ha_get_state` de una entidad inexistente lanzaba error en vez de devolver
  `not_found`, y a la inversa, con HA caída `ha_run_script` decía `not_found`
  de un script que sigue ahí.

### Fixed — Herramientas de Supervisor y registros

- Todas las herramientas de dashboards adicionales estaban muertas: enviaban
  `lovelace/dashboards`, que HA no registra; el comando es
  `lovelace/dashboards/list`. El test simulaba el comando inexistente.
- Actualizar un helper fallaba o borraba campos: HA reemplaza el objeto entero
  y exige `name`; ahora se envía el objeto actual fusionado con el cambio. El
  fixture de tests hacía un merge, por eso pasaban.
- `size_mb` de los backups era siempre 0.0: el Supervisor ya devuelve
  megabytes.
- Al terminar un flujo de integración se perdía el `entry_id`: el estado
  pisaba el campo `result` donde HA lo pone. Ahora va en `status`.
- `ha_hacs_list_repositories` con filtro siempre fallaba: HACS espera
  `categories`, no `category`.
- `sv_set_addon_options` seguía leyendo el endpoint prohibido en su vista
  previa; `installed_only=False` no hacía nada; `period="year"` se rechazaba.
- La redacción de opciones de add-ons dejaba pasar `psk`, `pre_shared_key`,
  `network_key` y las variantes con guion.
- La vista previa de `ha_delete_area` no contaba las entidades que heredan el
  área de su dispositivo. Y un `pending_jobs.json` que no fuera un objeto
  perdía el job tras haber lanzado la operación.

### Fixed — Sandbox de ficheros

- `fs_search_in_config` ejecutaba cualquier expresión regular: `(a+)+$b` colgaba
  un hilo del pool para siempre. Se rechazan cuantificadores anidados y
  retrorreferencias, y se acotan patrón y línea.
- Un `!include` circular en `configuration.yaml` rompía todas las vistas previas
  de escritura, incluida la que hacía falta para arreglarlo; y un `!include`
  fuera de `/config` se abría igualmente. Ahora hay detección de ciclos y
  contención, y el conjunto de ficheros ejecutables se guarda resuelto.
- El backup recién creado podía borrarse en la misma llamada por cuota, porque
  la evicción ordenaba por una fecha que se copiaba del original; y la rotación
  por ruta confundía `x.yaml` con `pkg/x.yaml`.
- Rutas con byte nulo o demasiado largas hacían reventar la tool en vez de
  devolver error; escribir o mover sobre un directorio fallaba después de
  emitir token y consumir cupo.
- La escritura atómica seguía un symlink plantado en el nombre temporal, dejaba
  el fichero legible por todos un instante y no hacía `fsync`.

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
