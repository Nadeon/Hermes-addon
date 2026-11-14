# Especificación: Hermes 1.1.2 — confirmar solo con el token

**Directorio de la spec**: `specs/007-confirmar-con-token`

**Creada**: 2026-11-14

**Estado**: Borrador

**Entrada**: pruebas en vivo de la 1.1.1 contra HA 2026.11.1 (ver
`docs/HOJA-DE-RUTA.md`, «Problemas conocidos de 1.1.1»). Las escrituras con
confirmación en dos pasos exigen que la segunda llamada repita los MISMOS
argumentos más `confirmation_token`, y el token caduca a los 60 s. Un cliente
LLM escribe unos 0,4 KB/s: la confirmación de un dashboard de 41 KB llegó a los
104 s de la vista previa y dio `confirmation_token expired`. Por encima de unos
20–25 KB es imposible guardar. Afecta a las tools que llevan un documento
grande: `ha_save_lovelace_dashboard` (`config`), `fs_write_file` (`content`),
`ha_create_or_update_automation`, `ha_create_or_update_script` y
`ha_create_or_update_scene` (`config`). Falla cerrado: no se pierde nada, pero
no se puede guardar.

## Clarificaciones

### Sesión 2026-11-14

Decisión del mantenedor, que no se discute en esta spec:

- P: ¿Confirmar solo con el token o dar más tiempo al token? → R: **confirmar
  solo con el token**. En la vista previa el servidor guarda el documento
  junto al token; en la confirmación, el documento se puede omitir y se toma
  del guardado. Versión 1.1.2.

Decisiones tomadas al especificar (el mantenedor no estaba; se anotan aquí en
lugar de preguntar):

- P: ¿Se puede omitir cualquier argumento o solo una lista explícita por tool?
  → R: **lista explícita por tool** («omitibles»): `config` en
  `ha_save_lovelace_dashboard`, `ha_create_or_update_automation`,
  `ha_create_or_update_script` y `ha_create_or_update_scene`; `content` en
  `fs_write_file`. Ninguna otra tool cambia. Motivo: el alcance queda acotado a
  las cinco tools del problema, el destino nunca se puede omitir por descuido y
  las demás tools con token siguen exactamente igual (ver S-01).
- P: ¿Qué se guarda en el servidor? → R: **solo los argumentos omitibles**, no
  todos. Los demás ya los ata el `action_hash`, que se sigue comprobando sobre
  los argumentos resultantes; guardarlos todos escribiría en disco, por
  ejemplo, las opciones con contraseñas de `sv_set_addon_options` (ver S-02).
- P: ¿Hace falta un tope de lo guardado? → R: **sí, un tope global de 16 MiB**:
  la suma de los bytes de los documentos guardados en los tokens vigentes. Si guardar el documento lo superase, el
  token se emite igual pero sin documento guardado y la respuesta dice que hay
  que reenviarlo: es el comportamiento de 1.1.1, nunca uno más permisivo (ver
  S-03).
- P: ¿Qué devuelve la vista previa? → R: además de lo de siempre,
  `confirm_with` (los argumentos que bastan para confirmar), `omit_on_confirm`
  (los que se pueden omitir) y `confirm_hint` (una frase que lo explica). Solo
  cuando el documento se ha guardado.
- P: ¿Cuándo se borra lo guardado? → R: al completar el token (con éxito o con
  fallo), al detectar que ha caducado y en una limpieza periódica cada 60 s
  (hoy cada hora), además de un barrido de caducados en cada vista previa nueva.

## Escenarios de usuario y pruebas *(obligatorio)*

### Historia 1 — Guardar un documento grande con confirmación (Prioridad: P1)

Quien pide al agente que reorganice un dashboard grande, reescriba un fichero
de `/config` largo o edite una automatización, un script o una escena extensos
quiere que el cambio se pueda guardar. Hoy, por encima de unos 20–25 KB, la
confirmación siempre llega tarde.

**Prueba independiente**: con un HA simulado, la vista previa de un dashboard
de 41 KB devuelve un token; la confirmación con solo `url_path` y
`confirmation_token` guarda exactamente el documento de la vista previa.

**Escenarios de aceptación**:

1. **Dado** `ha_save_lovelace_dashboard(url_path, config)` sin token,
   **cuando** el agente confirma con `ha_save_lovelace_dashboard(url_path,
   confirmation_token=…)` sin `config`, **entonces** HA recibe
   `lovelace/config/save` con el `config` de la vista previa, byte a byte.
2. **Dado** lo mismo con el dashboard principal (`url_path: null`),
   **entonces** también funciona: `null` es un destino, no una omisión.
3. **Dado** `fs_write_file(path, content)` sin token, **cuando** se confirma
   con `fs_write_file(path, confirmation_token=…)`, **entonces** el fichero
   queda con el `content` de la vista previa.
4. **Dado** `ha_create_or_update_automation`, `_script` o `_scene` (escena
   existente) sin token, **cuando** se confirma sin `config`, **entonces** se
   guarda la configuración normalizada de la vista previa.
5. **Dado** cualquiera de las cinco tools, **cuando** el agente confirma
   reenviando todos los argumentos como en 1.1.1, **entonces** funciona igual
   que antes.
6. **Dado** cualquiera de las cinco tools, **cuando** se llama sin token y sin
   el documento, **entonces** devuelve `invalid_argument` y no emite token.

### Historia 2 — El agente sabe que puede omitir el documento (Prioridad: P1)

Si nada le dice al agente que puede confirmar sin el documento, lo reenviará y
seguirá caducando. Quien lo usa quiere que la primera respuesta y la guía lo
digan sin ambigüedad.

**Prueba independiente**: la respuesta de la vista previa de las cinco tools
trae `confirm_with`, `omit_on_confirm` y `confirm_hint`; la guía y las
descripciones de las tools ya no piden repetir «los MISMOS argumentos».

**Escenarios de aceptación**:

1. **Dado** la vista previa de `ha_save_lovelace_dashboard`, **entonces** trae
   `omit_on_confirm: ["config"]` y `confirm_with: ["confirmation_token",
   "url_path"]` (más `remove_top_level_keys` si se usó), y `confirm_hint`.
2. **Dado** una vista previa que no cabe en `response_max_bytes`, **entonces**
   el recorte del guardián conserva `confirm_with`, `omit_on_confirm` y
   `confirm_hint` igual que conserva el token.
3. **Dado** una tool con token que no está entre las cinco, **entonces** su
   respuesta no cambia (sin esos campos).
4. **Dado** las instrucciones de conexión y el tema `security` de
   `hermes_guide`, **entonces** explican que el documento grande se puede
   omitir al confirmar y que lo que se reenvía tiene que ser idéntico.

### Historia 3 — El token sigue atado a la acción previsualizada (Prioridad: P1)

Quien confía en la vista previa como única revisión antes de un cambio grave
quiere que la confirmación solo pueda ejecutar exactamente lo que vio.

**Prueba independiente**: un token emitido para una acción no ejecuta otra,
ni con otro destino, ni con otro documento, ni con un argumento añadido, ni
desde otra tool.

**Escenarios de aceptación**:

1. **Dado** un token de `ha_save_lovelace_dashboard` para `url_path: "a"`,
   **cuando** se confirma con `url_path: "b"` (con o sin `config`),
   **entonces** «confirmation_token does not match this action» y no se guarda
   nada.
2. **Dado** un token de `fs_write_file` para un `path`, **cuando** se confirma
   con otro `path`, **entonces** se rechaza igual.
3. **Dado** un token, **cuando** la confirmación trae el documento con otro
   contenido, **entonces** se rechaza igual (no se mezcla ni se prefiere
   ninguno).
4. **Dado** un token de `ha_save_lovelace_dashboard` emitido sin
   `remove_top_level_keys`, **cuando** la confirmación lo añade, **entonces**
   se rechaza: un argumento que no estaba en la vista previa no se puede añadir.
5. **Dado** un token de una tool, **cuando** se usa en otra, **entonces** se
   rechaza.
6. **Dado** un token sin documento guardado (emitido con el tope lleno o por
   la 1.1.1), **cuando** se confirma omitiendo el documento, **entonces** se
   rechaza con un error que pide repetir la llamada completa y el token no se
   gasta.

### Historia 4 — El documento guardado no se queda en disco ni en el log (Prioridad: P2)

Quien escribe con `fs_write_file` un fichero con datos sensibles no quiere que
una copia quede en el almacenamiento del add-on ni que aparezca en el log.

**Prueba independiente**: tras completar, fallar o caducar el token, ningún
fichero del directorio de confirmaciones contiene el documento; ningún evento
de log lo contiene.

**Escenarios de aceptación**:

1. **Dado** una confirmación que termina bien o falla, **entonces** el fichero
   del token conserva su estado y su `cached_result`, pero ya no el documento.
2. **Dado** un token que caduca sin confirmarse, **entonces** el documento
   desaparece a lo sumo 60 s después de la caducidad (limpieza periódica), o
   antes si llega otra vista previa o se intenta confirmar.
3. **Dado** documentos guardados que ya suman 16 MiB, **cuando** llega otra
   vista previa, **entonces** su token se emite sin documento guardado, sin
   `omit_on_confirm`, con un `confirm_hint` que pide reenviar todos los
   argumentos, y el log lo anota sin contenido.
4. **Dado** cualquier vista previa o confirmación, **entonces** el log no
   lleva el documento ni partes de él; como mucho, la tool, los nombres de los
   argumentos guardados y su tamaño en bytes.

### Casos límite

- `content: ""` en `fs_write_file` es un fichero vacío, no una omisión; `config:
  {}` es un documento (inválido), no una omisión. Solo la ausencia del
  argumento o `null` cuentan como omisión. Excepción: en `fs_write_file` la
  omisión es no mandar `content`; un `null` explícito lo rechaza el SDK MCP,
  porque `content` se anota exactamente `str` para que el SDK no convierta en
  JSON un contenido como `{"a": 1}` (revisión de la 1.1.2).
- `url_path: null` es el dashboard principal y se compara como cualquier otro
  destino.
- La escena nueva (no existe aún) no pide token: sin `config` es
  `invalid_argument`.
- Dos confirmaciones simultáneas con el mismo token: solo una pasa de
  `pending` a `executing`; la otra recibe «currently being executed» o
  «already used», como hoy.
- Reinicio del add-on: si el fichero del token sigue en `/data` y no ha
  caducado, la confirmación sin documento funciona; si se perdió, «expired or
  lost across restart», como hoy.
- Reintento tras completar: «already used», como hoy; el `cached_result` se
  conserva, el documento no.
- Una vista previa recortada por el guardián (`preview_truncated`) no cambia lo
  guardado: se guarda el documento entero que se envió, no lo que se ve.

## Requisitos *(obligatorio)*

### Requisitos funcionales

- **FR-001**: Al emitir un token, el servidor guarda junto a él los argumentos
  que la tool declara omitibles y que vienen en la llamada, y solo esos. Las
  tools sin omitibles no guardan nada nuevo.
- **FR-002**: Omitibles por tool, como lista explícita en cada una:
  `ha_save_lovelace_dashboard` → `config`; `fs_write_file` → `content`;
  `ha_create_or_update_automation`, `ha_create_or_update_script` y
  `ha_create_or_update_scene` → `config`. El destino (`url_path`, `path`,
  `automation_id`, `script_id`, `scene_id`) nunca es omitible y es obligatorio
  en las dos llamadas.
- **FR-003**: En la confirmación, un argumento omitible ausente (o `null`,
  salvo `content` en `fs_write_file`, ver casos límite) se
  toma del guardado; uno presente se usa tal cual. El `action_hash` se comprueba
  sobre los argumentos resultantes, así que un argumento con otro valor o uno
  que no estaba en la vista previa da «confirmation_token does not match this
  action», como hoy, y el token no se gasta.
- **FR-004**: Confirmar con todos los argumentos, como en 1.1.1, sigue
  funcionando y produce el mismo `action_hash`.
- **FR-005**: Si se omite un argumento omitible y el token no lo tiene
  guardado, la confirmación se rechaza con un error que pide repetir la llamada
  con todos sus argumentos; el token no se gasta.
- **FR-006**: En las cinco tools el documento pasa a ser opcional en la firma y
  en el esquema de entrada MCP; el destino sigue siendo obligatorio. Sin token y
  sin documento, la respuesta es `{"error": "invalid_argument", "field": …,
  "detail": …}` y no se emite token.
- **FR-007**: Cuando el documento se ha guardado, la respuesta de la vista
  previa añade `confirm_with` (lista ordenada de los argumentos que bastan,
  `confirmation_token` incluido), `omit_on_confirm` (lista de los omitibles
  guardados) y `confirm_hint` (texto en inglés). El guardián de
  `response_max_bytes` nunca los quita al recortar una vista previa.
- **FR-008**: Las instrucciones de conexión (`INSTRUCTIONS`), los temas
  `security`, `files` y `workflows` de `hermes_guide` y las descripciones de las
  cinco tools dejan de pedir «la MISMA llamada con los MISMOS argumentos» y
  explican la omisión.
- **FR-009**: El documento guardado se borra del fichero del token al
  completarlo (éxito o fallo), conservando estado y `cached_result`; el fichero
  entero se borra al detectar la caducidad. Cada vista previa nueva barre los
  tokens caducados, y la limpieza periódica pasa de cada hora a cada 60 s; solo
  registra `confirmations_cleaned` cuando ha limpiado algo (> 0), para que una
  limpieza cada minuto no llene el log.
- **FR-010**: Ningún evento de log contiene el documento; los eventos nuevos
  llevan como mucho la tool, los nombres de los argumentos guardados y su
  tamaño en bytes.
- **FR-011**: La suma de los bytes de los documentos guardados en los tokens
  vigentes no pasa de 16 MiB.
  Si un documento nuevo lo superase, el token se emite sin documento guardado,
  sin `omit_on_confirm`, con `confirm_with` igual a todos los argumentos más el
  token y un `confirm_hint` que pide reenviarlos, y se registra
  `confirmation_args_not_stored` con `reason` y bytes.
- **FR-012**: La comprobación del token y el paso de `pending` a `executing`
  siguen sin ningún `await` entre medias, para que dos confirmaciones
  simultáneas no ejecuten dos veces.
- **FR-013**: El principio IV se enmienda en `docs/PRINCIPIOS.md` y en
  `.specify/memory/constitution.md` en el mismo cambio: la segunda llamada ya
  no tiene que repetir los documentos que la tool declare omitibles, y la
  garantía es que el token sigue atado a la tool y a sus argumentos, guardados
  en el servidor. La constitución pasa a la versión 1.1.0.
- **FR-014**: Versión 1.1.2 en `hermes/config.yaml`,
  `hermes/src/hermes/__init__.py` y `HA_CORE_LAST_TESTED_IN_HERMES`; entrada
  `## [1.1.2] — 2026-11-14` en `hermes/CHANGELOG.md`; `SECURITY.md` dice que
  los argumentos de la vista previa se guardan en el servidor y cuándo se
  borran; `docs/HOJA-DE-RUTA.md` pasa el problema conocido a resuelto en 1.1.2
  y deja la prueba en vivo de dashboards grandes como pendiente. `README.md`,
  `README.es.md` y `hermes/DOCS.md` no cambian: no dicen que haya que repetir
  los argumentos.
- **FR-015**: Cada requisito anterior tiene un test de regresión, y cada
  arreglo, su control negativo anotado (principio VII).

### Entidades clave

- **Token de confirmación**: fichero por token en el almacenamiento del add-on
  con su `action_hash`, estado, caducidad y, desde esta versión, los
  argumentos omitibles guardados y su tamaño.
- **Omitibles de una tool**: lista fija, declarada en la propia tool, de los
  argumentos que se pueden omitir al confirmar.

## Supuestos

- **S-01**: Una regla genérica («cualquier argumento ausente se toma del
  guardado») funcionaría, porque el hash ata todo, pero obliga a guardar todos
  los argumentos de todas las tools con token y cambia el comportamiento de
  las demás tools con token, que no tienen el problema. La lista explícita deja el cambio en las
  cinco y hace imposible omitir un destino aunque una tool futura lo declare
  opcional.
- **S-02**: Comprobar «lo que se manda coincide con lo guardado» y comprobar el
  `action_hash` sobre los argumentos resultantes es equivalente: el hash cubre
  la tool y todos los argumentos. Por eso basta con guardar los omitibles y se
  conserva el mensaje de error de hoy.
- **S-03**: Cada documento cabe en una petición (`max_request_body_bytes`, 4 MiB
  por defecto) y el techo global es de 120 peticiones por minuto; sin tope, un
  cliente podría dejar unos 480 MiB en `/data` durante un minuto. 16 MiB caben
  cuatro documentos del tamaño máximo y cientos de dashboards reales.
- **S-04**: El almacenamiento del add-on entra en sus backups. Un documento
  pendiente podría acabar en un backup hecho en ese minuto; es el mismo
  contenido que se va a escribir en `/config`, que también entra en los
  backups, así que no amplía la exposición. El borrado temprano de FR-009 la
  acota.
- **S-05**: Los clientes MCP actuales (Claude) siguen la pista de la respuesta
  y la guía; lo confirma la prueba en vivo pendiente (SC-005).

## Fuera de alcance

- Cambiar el TTL de 60 s o hacerlo configurable.
- Omitir argumentos en otras tools con token (helpers, `fs_set_secret`,
  `sv_set_addon_options`…): sus argumentos son pequeños.
- Usar el `cached_result` para devolver el resultado de un reintento en vez de
  «already used».
- Cifrar lo guardado en `/data`.

## Criterios de éxito *(obligatorio)*

- **SC-001**: Un dashboard de 41 KB y uno de 1 MB se guardan con confirmación
  aunque el agente tarde en escribir; lo que el agente escribe en la
  confirmación no depende del tamaño del documento (menos de 1 KB).
- **SC-002**: Ningún token ejecuta una acción distinta de la previsualizada:
  otro destino, otro documento, un argumento añadido u otra tool se rechazan
  en el 100 % de los casos probados.
- **SC-003**: Tras completar o fallar el token no queda copia del documento en
  el almacenamiento del add-on; tras caducar, a lo sumo 60 s; nunca en el log.
- **SC-004**: Quien confirma reenviando todo, como en 1.1.1, no nota ningún
  cambio: los tests de confirmación existentes pasan sin tocarlos, salvo los
  que afirman textos que esta versión cambia a propósito.
- **SC-005**: Tras publicar, la prueba en vivo con el dashboard de 41 KB que
  falló en la 1.1.1 guarda a la primera.
- **SC-006**: La suite completa pasa y cada arreglo tiene su control negativo
  escrito.
