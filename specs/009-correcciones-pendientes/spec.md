# Especificación: Hermes 1.2.0 — correcciones pendientes y subida de versión (009)

**Directorio de la spec**: `specs/009-correcciones-pendientes`

**Creada**: 2026-11-14

**Estado**: Borrador

**Entrada**: sub-feature 009 del programa «cobertura total»
([spec 008](../008-cobertura-total/spec.md), tarea T002 de
[tasks.md](../008-cobertura-total/tasks.md) y fila 009 de
[plan.md](../008-cobertura-total/plan.md)). Cubre los menores pendientes de
las pruebas en vivo de la 1.1.1 y la 1.1.2 (CAP-010…CAP-018, CAP-021 y
CAP-024 de [research.md](../008-cobertura-total/research.md); FR-025…FR-035 de
la 008) y la subida de versión a 1.2.0 con el esqueleto de su entrada del
CHANGELOG (FR-022 de la 008). No añade tools: arregla redacción, log, formas de
respuesta y dos comportamientos de borde. Es la primera sub-feature del
programa y la base de otras: la redacción lineal (CAP-010) la necesitan las
tools de logs de 012 y 013 y las genéricas de 011.

## Clarificaciones

### Sesión 2026-11-14

Decisiones del mantenedor recogidas en la spec 008, que no se discuten aquí:

- P: ¿Versión? → R: **una sola 1.2.0** para todo el programa; se sube aquí, en
  la 009, en los tres sitios, y se abre una única entrada
  `## [1.2.0] — <fecha de publicación>` con secciones por bloque, que cada
  sub-feature completa (FR-022 de la 008). La fecha se pone al publicar.
- P: ¿`ha_marketplace_list_removed` filtra los instalados por defecto? → R:
  **no**: `installed_only` y `limit` son opcionales y sus valores por defecto
  dan la misma lista que la 1.1.2 (clarificación de la 008 y su FR-020). La
  propuesta de research CAP-016 («`installed_only=True` por defecto») queda
  sustituida por esta decisión.

Decisiones tomadas al especificar (el mantenedor no estaba; se anotan aquí en
lugar de preguntar):

- P: ¿Qué expresiones de `redact_secrets` se arreglan? → R: las tres que hoy
  son cuadráticas, medidas sobre el código actual: la de JWT (`eyJ` repetido),
  la de URLs con usuario y contraseña (letras, `a.` o `a://b:c` repetidos sin
  `@`) y la de claves JSON (`"` seguido de `password` repetido). 30 KB de esas
  formas tardan entre 0,4 y 0,6 s; las otras dos expresiones ya son lineales
  (research R-1). Lo que se redacta no cambia: un test diferencial lo compara
  con las expresiones de la 1.1.2 (ver S-01).
- P: ¿De dónde salen `external_url` e `internal_url`? → R: del REST
  `/api/config` de HA, que `HAClient` lee al conectar —antes de registrar
  `ha_ws_connected` y de que ninguna tool que necesite HA pueda responder— y
  vuelve a leer en cada reconexión. Si no se puede leer, se avisa sin valores
  y la conexión sigue (research R-2).
- P: ¿Qué nombres se tapan? → R: el host de cada URL, salvo los que no
  identifican a nadie (`localhost`, `homeassistant`, `homeassistant.local`) y
  los literales IP, que ya seudonimiza la redacción de IPs. Igual que el resto
  de la redacción de red, solo con `log_redact_network` activa.
- P: ¿Qué significa `network_redacted` en `sv_get_addon_logs`? → R: que la
  redacción de red **se aplicó** a ese log (el del propio Hermes con
  `log_redact_network` activa), aunque las líneas ya vinieran redactadas de
  origen: es justo el caso de la prueba en vivo de la 1.1.1, donde `redacted`
  decía `false` con la red ya tapada. `secrets_redacted` dice si esta llamada
  tapó algún secreto. `redacted` conserva su significado: el texto devuelto
  difiere del leído (research R-4).
- P: ¿`auto_classify_on_save` también? → R: **sí**. La CAP-012 apunta a
  `auto_classify_on_save` y el FR-027 de la 008 a `auto_classify_restricted`;
  los dos eventos escriben hoy `entity_id` y los dos pasan a solo contadores.
- P: ¿Forma del resumen por tipo de `ha_marketplace_list_removed`? → R: una
  lista `by_removal_type` de `{removal_type, count}` ordenada por `count`
  descendente, con un máximo de 20 tipos y `by_removal_type_other` con la suma
  del resto. `removal_type` es texto de terceros: se recorta como `reason` y
  figura en `_third_party_text`. Lista y no objeto porque un tipo nulo no
  puede ser clave y un tipo inventado por un tercero no puede chocar con una
  clave fija (research R-5).
- P: ¿Cómo se abarata el barrido de tokens? → R: barrido completo **como mucho
  una vez por segundo**; entre barridos, el total en uso sale de la memoria
  (lo del último barrido más lo emitido después). Lo que se libera entre
  barridos no se descuenta hasta el siguiente: el total puede sobrestimarse,
  nunca subestimarse, así que el tope de 16 MiB se sigue cumpliendo
  (research R-6).
- P: ¿`sv_update_addon` sobre Hermes, también con token? → R: se rechaza
  **siempre**, con o sin `confirmation_token`, antes de cualquier llamada al
  Supervisor, sin emitir token y sin gastar uno que se traiga. Se reconoce a
  Hermes con la misma función que ya usan los avisos de auto-daño
  (`_es_hermes`).
- P: ¿Qué traceback sale al apagar? → R: no hay una traza guardada del
  problema 23. Con uvicorn 0.54, si al llegar el plazo de cierre ordenado
  queda una petición en vuelo, uvicorn la cancela y registra
  `Exception in ASGI application` con la traza de `CancelledError`; y un
  `CancelledError` que escape de `asyncio.run` no lo captura el
  `except Exception` de `main()`. El primer test reproduce el primero con un
  uvicorn real en loopback antes de arreglar nada; si no se reproduce, se
  anota y se arregla lo que el test sí demuestre (research R-7).

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es un administrador de Home Assistant que trabaja a través de un
cliente MCP y que, a veces, pega el log de Hermes en un issue o en un foro.

### Historia 1 — Redactar un log enorme no bloquea a Hermes (Prioridad: P1)

Quien pide al agente que lea un log de un add-on (o, desde 012 y 013, el log
de HA o del Supervisor) quiere que la redacción de secretos termine pronto
aunque el log traiga una línea larguísima sin espacios. Hoy 30 KB con ciertas
formas tardan medio segundo en el bucle de eventos y el coste crece con el
cuadrado del tamaño: un cliente autenticado puede bloquear a Hermes.

**Prueba independiente**: `redact_secrets` sobre 1 MiB sin espacios de cada
forma adversaria termina en menos de 1 s, y sobre un corpus de textos cortos da
exactamente lo mismo que las expresiones de la 1.1.2.

**Escenarios de aceptación**:

1. **Dado** 1 MiB de `eyJ` repetido, de letras sin `://`, de `a.` repetido, de
   `a://b:c` repetido sin `@` o de `"` seguido de `password` repetido,
   **cuando** se redacta, **entonces** termina en menos de 1 s en el CI.
2. **Dado** un texto con un JWT, una URL `https://usuario:clave@host`, un
   `"password": "x"` o un `token=x`, **cuando** se redacta, **entonces** queda
   igual que con la 1.1.2.
3. **Dado** el corpus diferencial (textos cortos generados con semilla fija
   que mezclan los fragmentos de los patrones), **entonces** la salida de la
   1.2.0 coincide con la de la 1.1.2 en el 100 % de los casos.

### Historia 2 — El log de Hermes no identifica la instalación (Prioridad: P1)

Quien pega el log de Hermes en un issue público quiere que no lleve sus
dominios, los nombres de sus automatizaciones ni IPs con forma de nombre de
host.

**Prueba independiente**: con la redacción de red activa y un HA simulado cuya
`/api/config` trae `external_url` e `internal_url` con hosts centinela, ninguna
línea del log capturado tras la conexión contiene esos hosts, ningún
`entity_id` centinela de una automatización restringida y ninguna IP con forma
`ip-a-b-c-d`.

**Escenarios de aceptación**:

1. **Dado** HA con `external_url: https://casa.example.org` e
   `internal_url: http://ha.lan.example:8123`, **cuando** Hermes conecta,
   **entonces** las líneas posteriores que los contengan salen con
   `<ha_external_host>` y `<ha_internal_host>`.
2. **Dado** que los hosts cambian y HA se reinicia, **cuando** Hermes
   reconecta, **entonces** se tapan los nuevos.
3. **Dado** que `/api/config` falla al conectar, **entonces** se registra un
   aviso sin valores y la conexión sigue.
4. **Dado** `internal_url: http://homeassistant.local:8123` o una URL con IP,
   **entonces** no se añade un nombre que tapar (la IP la seudonimiza la
   redacción de IPs).
5. **Dado** `log_redact_network: false`, **entonces** no se tapa nada de red,
   como hoy.
6. **Dado** una automatización con `shell_command.*`, **cuando** se clasifica
   al arrancar o al guardarla, **entonces** el log dice cuántas entidades se
   restringieron y no cuáles.
7. **Dado** una línea con `ip-10-0-0-5.ec2.internal`, **entonces** sale como
   `<ip:private:HHHHHHHH>.ec2.internal`, con el mismo seudónimo que
   `10.0.0.5`; `ip-127-0-0-1` se queda como está (loopback) e `ip-999-1-1-1`
   también (no es una IP).

### Historia 3 — Las respuestas dicen lo que han hecho (Prioridad: P2)

Quien usa el agente quiere que las respuestas recortadas o redactadas lo
digan igual que las demás, y que las listas grandes se puedan acotar.

**Prueba independiente**: `sv_get_addon_logs`, `ha_get_history` y
`ha_marketplace_list_removed` devuelven los campos nuevos con un HA y un
Supervisor simulados, y las llamadas sin argumentos nuevos devuelven lo mismo
que la 1.1.2 más esos campos.

**Escenarios de aceptación**:

1. **Dado** el log del propio Hermes con la red ya redactada en origen y sin
   secretos, **cuando** se lee, **entonces** `network_redacted: true`,
   `secrets_redacted: false` y `redacted: false`.
2. **Dado** el log de otro add-on con una contraseña, **entonces**
   `secrets_redacted: true`, `network_redacted: false` y `redacted: true`.
3. **Dado** `ha_get_history` recortado por bytes o por el tope de estados por
   entidad, **entonces** trae `truncated: true`, `truncated_at` y
   `_response_limit` con `list`, `returned`, `total`, `max_bytes` y `hint`, y
   la respuesta entera cabe en `response_max_bytes`. Sin recorte, no hay
   `_response_limit`.
4. **Dado** `ha_marketplace_list_removed()` sin argumentos, **entonces** la
   lista `repositories` tiene las mismas entradas y en el mismo orden que en
   la 1.1.2 y se añaden `by_removal_type` y `removal_type` en
   `_third_party_text`.
5. **Dado** `installed_only=True`, **entonces** solo salen los retirados que
   están instalados; con `limit=5`, como mucho cinco y `truncated: true` si
   había más; `total` y `by_removal_type` cuentan todos los que cumplen el
   filtro.
6. **Dado** un `removal_type` de 5 000 caracteres, **entonces** sale
   recortado como `reason`.
7. **Dado** cualquier tool del Marketplace o `sv_get_resolution` que termina
   bien, **entonces** el log tiene su evento `*_ok` con contadores y sin
   nombres de repositorios ni textos de terceros.

### Historia 4 — Lo que no se puede hacer se dice antes (Prioridad: P2)

Quien pide al agente que actualice Hermes quiere un mensaje claro, no una
vista previa que acaba en un 403 del Supervisor.

**Prueba independiente**: `sv_update_addon` con el slug de Hermes, con y sin
token, devuelve `self_update_not_supported`, no llama al Supervisor y no emite
token.

**Escenarios de aceptación**:

1. **Dado** `sv_update_addon("<slug>_hermes")` o `sv_update_addon("self")`
   sin token, **entonces** `{"error": "self_update_not_supported", "detail":
   …}` con la indicación de actualizar desde la interfaz de HA, sin
   `confirmation_token`, y el Supervisor simulado no recibe ninguna petición.
2. **Dado** lo mismo con un `confirmation_token`, **entonces** el mismo error,
   sin llamar al Supervisor y sin tocar el token.
3. **Dado** `sv_update_addon` con el slug de otro add-on, **entonces** se
   comporta como en la 1.1.2.

### Historia 5 — Vistas previas baratas y apagado limpio (Prioridad: P3)

Quien guarda varios documentos grandes seguidos no quiere que cada vista previa
relea todos los tokens pendientes; quien reinicia el add-on no quiere una traza
que parezca un fallo.

**Prueba independiente**: diez vistas previas con documento en el mismo
segundo hacen un solo barrido y respetan el tope; un uvicorn real con una
petición colgada se apaga sin traza en el log.

**Escenarios de aceptación**:

1. **Dado** diez vistas previas con documento en menos de 1 s, **entonces**
   se hace un único barrido del directorio de confirmaciones.
2. **Dado** el tope casi lleno, **cuando** llegan vistas previas seguidas sin
   barrido entre ellas, **entonces** ninguna guarda un documento que haga
   pasar de 16 MiB la suma de lo guardado.
3. **Dado** un token caducado, **cuando** pasa más de 1 s, **entonces** la
   siguiente vista previa con documento lo barre como hoy.
4. **Dado** Hermes con una petición en vuelo más larga que el plazo de cierre,
   **cuando** recibe SIGTERM, **entonces** el log no contiene `Traceback` ni
   `CancelledError` y termina con `hermes_stopped`.
5. **Dado** una excepción que no es una cancelación en una petición,
   **entonces** su traza sigue saliendo en el log, como hoy.

### Historia 6 — La versión es 1.2.0 desde el principio del programa (Prioridad: P1)

Quien revisa la rama del programa quiere ver una sola versión y una sola
entrada del CHANGELOG donde cada sub-feature va dejando lo suyo.

**Prueba independiente**: los tres sitios dicen 1.2.0, la primera entrada del
CHANGELOG es `## [1.2.0] — <fecha de publicación>` con sus ocho secciones y la
de «Correcciones» describe lo de esta sub-feature.

**Escenarios de aceptación**:

1. **Dado** `hermes/config.yaml`, `hermes/src/hermes/__init__.py` y
   `HA_CORE_LAST_TESTED_IN_HERMES`, **entonces** los tres valen `1.2.0`.
2. **Dado** `hermes/CHANGELOG.md`, **entonces** su primera entrada es la de la
   versión de `__version__` y tiene las secciones Diagnóstico, Integraciones,
   Automatización, Supervisor, Sistema, Política y genéricas, Banco de pruebas
   y Correcciones.

### Casos límite

- **Varias URLs con el mismo host**: si `external_url` coincide con
  `public_hostname` (Funnel), ya sale como `<public_hostname>`, que se aplica
  antes.
- **URL sin host o mal formada**: se ignora sin error.
- **`ip-a-b-c-d` con ceros a la izquierda** (`ip-010-000-000-005`): se trata
  como la forma con puntos, que ya los admite.
- **`ip-a-b-c-d` pegado a letras o dígitos** (`xip-10-0-0-5`,
  `ip-10-0-0-55555`): no se toca, igual que la IPv4 con puntos.
- **Slug que termina en `_hermes` y no es Hermes**: `_es_hermes` lo trata como
  Hermes, como ya hacen los avisos de auto-daño; se rechaza la actualización.
  Es el criterio existente; cambiarlo queda fuera.
- **`limit` fuera de 1–500 o no entero** en `ha_marketplace_list_removed`:
  `invalid_argument`, como en `ha_marketplace_list_repositories`.
- **`installed_only=True` y la lista de repositorios no se puede leer**: se
  devuelve el error, no la lista sin filtrar.
- **HACS (HA ≤ 2026.10)**: `installed_only` usa la lista de HACS por el mismo
  fallback que el resto de las tools.
- **Barrido con el reloj hacia atrás**: si el reloj retrocede, se barre (nunca
  se usa la memoria más de 1 s seguido).
- **Token de una versión anterior en disco al arrancar**: el paso 7 del
  arranque barre y fija el total, como hoy.

## Requisitos *(obligatorio)*

### Requisitos funcionales

Cada requisito cita el FR de la 008 y la CAP que cumple.

- **FR-001** (008 FR-025, CAP-010): `redact_secrets` crece de forma lineal con
  el tamaño de la entrada: 1 MiB sin espacios de cada forma adversaria de la
  Historia 1 se redacta en menos de 1 s en el CI, con test de tiempo. Lo que se
  redacta no cambia: un test diferencial compara la salida con la de las
  expresiones de la 1.1.2 sobre un corpus generado con semilla fija, y los
  tests de redacción existentes pasan sin tocarlos.
- **FR-002** (008 FR-026, CAP-011): con `log_redact_network` activa, el host de
  `external_url` y el de `internal_url` de HA se tapan en el log de Hermes
  (`<ha_external_host>`, `<ha_internal_host>`) desde que `HAClient` los lee al
  conectar, antes de registrar `ha_ws_connected`, y se renuevan en cada
  reconexión. Se excluyen los literales IP y `localhost`, `homeassistant` y
  `homeassistant.local`. Si no se pueden leer, se registra
  `ha_url_redaction_unavailable` sin valores y la conexión sigue. La redacción
  de red se aplica también al log del propio Hermes que devuelve
  `sv_get_addon_logs`, así que estos nombres salen tapados ahí.
- **FR-003** (008 FR-027, CAP-012): `auto_classify_restricted` y
  `auto_classify_on_save` dejan de escribir `entity_id` en el log: solo
  contadores (`count` y `new_count` en el de arranque; `restricted` y
  `count` en el de guardado).
- **FR-004** (008 FR-028, CAP-013): la redacción de red del log cubre los
  nombres de host con forma `ip-a-b-c-d`: si `a.b.c.d` es una IPv4 válida y no
  de loopback, la parte `ip-a-b-c-d` se sustituye por el mismo seudónimo
  `<ip:CLASE:HHHHHHHH>` que tendría `a.b.c.d`; lo demás del nombre se
  conserva. La redacción sigue siendo idempotente.
- **FR-005** (008 FR-029, CAP-014): `sv_get_addon_logs` añade
  `secrets_redacted` (esta llamada tapó al menos un secreto) y
  `network_redacted` (la redacción de red se aplicó a este log), sin cambiar el
  significado de `redacted`. El evento de log `sv_get_addon_logs` lleva los
  tres. La descripción de la tool lo dice.
- **FR-006** (008 FR-030, CAP-015): cuando `ha_get_history` marca
  `truncated: true` (por bytes o por el tope de estados por entidad), añade
  `_response_limit` con `list: "history"`, `returned`, `total`, `max_bytes` y
  `hint`, como las demás tools recortadas; conserva `truncated_at`, y la
  respuesta entera, con el bloque, cabe en `response_max_bytes`. Sin recorte,
  la respuesta es la de la 1.1.2.
- **FR-007** (008 FR-031, CAP-016): `ha_marketplace_list_removed` acepta
  `installed_only: bool = False` y `limit: int | None = None` (1–500), y
  añade `by_removal_type` (hasta 20 `{removal_type, count}`, por `count`
  descendente) y `by_removal_type_other`. `total` y el resumen cuentan los que
  cumplen el filtro antes de `limit`; `truncated` es verdad si `limit` o el
  tope de bytes cortaron. `removal_type` se recorta como `reason` y figura en
  `_third_party_text.fields`. Sin argumentos, `repositories` tiene las mismas
  entradas, en el mismo orden y con los mismos campos que en la 1.1.2; la
  única diferencia posible es un `removal_type` de más de 300 caracteres, que
  sale recortado.
- **FR-008** (008 FR-032, CAP-017): las siete tools `ha_marketplace_*` y
  `sv_get_resolution` escriben al terminar bien su evento `<tool>_ok` con
  contadores (`api`, `count`, `total`, `truncated` según la tool; los cinco
  recuentos en `sv_get_resolution`), sin nombres de repositorios, ids ni
  textos de terceros. Los alias `ha_hacs_*` no cambian.
- **FR-009** (008 FR-033, CAP-018): emitir una vista previa con documento no
  relee todos los ficheros de token cada vez: el barrido completo se hace como
  mucho una vez por segundo y, entre barridos, el total en uso sale de la
  memoria (lo del último barrido más lo guardado después). El total nunca se
  subestima: la suma de lo guardado en los tokens vigentes sigue sin pasar de
  16 MiB (FR-011 de la 007).
- **FR-010** (008 FR-034, CAP-021): `sv_update_addon` sobre el propio Hermes
  se rechaza con o sin `confirmation_token`, antes de llamar al Supervisor,
  con `{"error": "self_update_not_supported", "detail": …}` que indica
  actualizar desde la interfaz de Home Assistant; no emite token ni gasta el
  que traiga. La descripción de la tool lo dice.
- **FR-011** (008 FR-035, CAP-024): apagar Hermes (SIGTERM) con peticiones en
  vuelo no deja `Traceback` ni `CancelledError` en el log: la cancelación de
  una petición al cierre se registra como una línea informativa sin traza, y
  un `CancelledError` que llegue a `main()` se trata como una interrupción.
  Las demás excepciones conservan su traza.
- **FR-012** (008 FR-022): la versión pasa a **1.2.0** en `hermes/config.yaml`,
  `hermes/src/hermes/__init__.py` y `HA_CORE_LAST_TESTED_IN_HERMES`.
  `hermes/CHANGELOG.md` abre una única entrada
  `## [1.2.0] — <fecha de publicación>` con una introducción y las secciones
  Diagnóstico, Integraciones, Automatización, Supervisor, Sistema, Política y
  genéricas, Banco de pruebas y Correcciones; esta sub-feature rellena
  «Correcciones» y deja las demás con una línea «pendiente» que cada
  sub-feature sustituye. La fecha la pone el cierre al publicar.
- **FR-013** (008 FR-023, FR-024): en el mismo cambio, `docs/HOJA-DE-RUTA.md`
  pasa la fila 009 del programa a «hecha», el problema conocido 23 a resuelto
  en 1.2.0 y quita de «lo que antes estaba pendiente» los menores ya
  resueltos; las descripciones de las tools tocadas y el tema del Marketplace
  de `hermes_guide` dicen lo nuevo; las filas CAP-010…CAP-018, CAP-021 y
  CAP-024 de la matriz de `specs/008-cobertura-total/plan.md` nombran sus
  tests; la fila de `log_redact_network` de `README.md`, `README.es.md` y
  `hermes/DOCS.md`, y la viñeta de redacción de red de `SECURITY.md`, añaden
  los hosts de las URLs de HA y los nombres `ip-a-b-c-d` (research R-8).
- **FR-014** (008 FR-018, FR-020, FR-021): nada de lo actual se rompe: las
  216 tools siguen con el mismo nombre, anotaciones y argumentos; los
  argumentos nuevos son opcionales y su valor por defecto reproduce la 1.1.2.
  Cada requisito anterior tiene test de regresión y cada arreglo, su control
  negativo anotado (principio VII). Los tests usan solo marcadores genéricos.

### Entidades clave

- **Hosts de HA para la redacción**: los nombres sacados de `external_url` e
  `internal_url`, guardados en el estado de la redacción de red junto al
  hostname público; se sustituyen enteros, de una vez, como el resto de ese
  estado.
- **Total de documentos guardados**: bytes de los documentos de los tokens
  vigentes según el último barrido, más lo guardado desde entonces, y la hora
  de ese barrido.

## Supuestos

- **S-01**: Las expresiones nuevas de `redact_secrets` se pueden escribir
  equivalentes a las de la 1.1.2 en todos los textos; si en algún caso de
  borde no lo son, la diferencia solo puede ser **redactar más**, nunca menos,
  y se anota en el test diferencial como excepción con su porqué.
- **S-02**: `/api/config` de HA (REST a través del Supervisor, el mismo canal
  que `/api/states`) devuelve `external_url` e `internal_url`; los dos pueden
  ser `null`.
- **S-03**: Los nombres `ip-a-b-c-d` que interesan son los de AWS y similares;
  otras formas (`ec2-a-b-c-d`, `a-b-c-d.nip.io`) no se piden y quedan fuera.
- **S-04**: El problema 23 no tiene una traza guardada; las dos fuentes de
  research R-7 son las que el código actual puede producir. La prueba manual
  tras publicar lo confirma.
- **S-05**: El CI de Linux es la referencia del test de tiempo; en Windows hay
  6 fallos conocidos ajenos a esta spec.

## Fuera de alcance

- Otras expresiones o funciones de redacción que ya son lineales
  (`redact_network`, `_SECRET_KEY_RE`, `_BARE_SECRET_RE`).
- Tapar en el log otros datos de la configuración de HA (nombre de la
  ubicación, coordenadas) o redactar el contenido de las respuestas.
- Otras formas de nombre de host con IP (S-03).
- Cambiar el criterio de `_es_hermes`.
- Unificar la forma de las listas existentes (CAP-023, duda D-07 de la 008).
- Cualquier tool nueva, la tabla de clasificación y las familias (011).

## Criterios de éxito *(obligatorio)*

- **SC-001**: 1 MiB sin espacios de cada forma adversaria se redacta en menos
  de 1 s en el CI; la salida coincide con la de la 1.1.2 en el 100 % del
  corpus diferencial.
- **SC-002**: En los tests con log capturado, ningún host centinela de
  `external_url`/`internal_url`, ningún `entity_id` centinela de una entidad
  restringida y ninguna `ip-a-b-c-d` centinela aparecen en el log.
- **SC-003**: Las respuestas nuevas de `sv_get_addon_logs`, `ha_get_history` y
  `ha_marketplace_list_removed` cumplen [contracts/tools.md](contracts/tools.md)
  y, sin argumentos nuevos, contienen la respuesta de la 1.1.2.
- **SC-004**: `sv_update_addon` sobre Hermes no produce ninguna petición al
  Supervisor en el 100 % de los casos probados.
- **SC-005**: Diez vistas previas con documento en el mismo segundo hacen un
  barrido; el tope de 16 MiB se respeta en todos los casos probados.
- **SC-006**: Un apagado con una petición en vuelo no deja `Traceback` en el
  log capturado.
- **SC-007**: La suite completa pasa (en Windows fallan solo los 6 conocidos),
  el CI de Linux queda en verde y cada FR tiene su control negativo escrito.
