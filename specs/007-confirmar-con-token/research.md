# Investigación: Hermes 1.1.2 — confirmar solo con el token

Cada apartado: decisión, motivo y alternativas. Las referencias a código son
de la punta de la rama sobre 1.1.1.

## R-1 — Por qué caduca hoy

- **Hallazgo**: `create_confirmation_token` (`hermes/src/hermes/security.py`)
  guarda solo `action_hash`, estado y caducidad (`CONFIRMATION_TTL_SECONDS` =
  60). `validate_confirmation_token` recalcula el hash con los argumentos de la
  segunda llamada, así que el cliente tiene que volver a escribir el documento
  entero. A unos 0,4 KB/s, un documento de 41 KB tarda más de 100 s solo en
  escribirse; la caducidad se mide desde la vista previa.
- **Decisión** (del mantenedor): el servidor guarda el documento en la vista
  previa y la confirmación puede omitirlo.
- **Alternativa descartada**: alargar el TTL. El documento se seguiría
  escribiendo dos veces (coste y tiempo para el cliente) y el tope solo se
  movería de sitio.

## R-2 — Lista explícita de omitibles frente a regla genérica

- **Decisión**: cada tool declara sus omitibles en la llamada a
  `create_confirmation_token(..., omitibles=("config",))` y en la de
  resolución. Solo las cinco tools del problema los declaran.
- **Motivo**: hay 19 ficheros de tools que piden token (51 llamadas a `validate_confirmation_token`). Con la regla
  genérica habría que guardar todos los argumentos de todas ellas, lo que
  incluye valores sensibles (`sv_set_addon_options`, `fs_set_secret`), y
  cualquier argumento opcional de cualquiera pasaría a poder omitirse sin que
  nadie lo haya revisado. La lista explícita acota el cambio y su revisión.
- **Alternativa descartada**: genérica con lista negra de destinos. Fail-open
  ante una tool nueva que olvide declarar su destino (principio III).

## R-3 — Qué se guarda y cómo se comprueba

- **Decisión**: se guardan solo los omitibles presentes en la vista previa
  (`stored_args`). En la confirmación se construyen los argumentos
  resultantes: los que el cliente manda, más los omitibles que faltan tomados
  de `stored_args`. El `action_hash` se recalcula sobre los resultantes y se
  compara con el guardado, como hoy.
- **Motivo**: el hash cubre la tool y todos los argumentos, así que un valor
  distinto, un destino distinto o un argumento añadido cambian el hash y dan
  «does not match this action» sin código nuevo (spec S-02). Guardar el resto
  no aporta seguridad y sí exposición en disco.
- **Omisión sin valor guardado** (token emitido con el tope lleno, o por la
  1.1.1 justo antes de actualizar): error propio, «confirmation_token has no
  stored value for: config. Repeat the call with all its arguments.», sin
  tocar el estado del token, para que el cliente pueda reintentar completo
  dentro del TTL.
- **Omisión**: argumento ausente o `null`. `""` y `{}` son valores. En
  `fs_write_file`, solo la ausencia: `content` se anota `str` (no `str | None`)
  porque el SDK MCP hace `json.loads` de los argumentos de texto con otra
  anotación, y un contenido `{"a": 1}` o `[1, 2]` dejaba de ser texto (revisión
  de la 1.1.2).

## R-4 — Interfaz de `security.py`

- **Decisión**: función nueva `resolve_confirmation_token(token, tool_name,
  args, *, omitibles=()) -> tuple[bool, str, dict[str, Any]]` con toda la
  lógica de hoy más la fusión; `validate_confirmation_token` queda como
  envoltorio que devuelve `(ok, error)` con `omitibles=()`.
- **Motivo**: las otras 46 llamadas a `validate_confirmation_token` no se
  tocan (principio IX). Las cinco tools necesitan los argumentos resueltos
  para ejecutar.
- **Concurrencia**: el cuerpo sigue sin `await` entre leer el fichero y
  escribir `executing`; en un solo bucle de eventos eso es atómico frente a
  otra confirmación del mismo token.

## R-5 — Esquema MCP y firma de las tools

- **Hallazgo**: el SDK deriva el esquema de entrada de la firma. Con
  `config: dict[str, Any] | None = None` el argumento sale de `required`;
  `url_path: str | None` sin valor por defecto sigue en `required` (admite
  `null`). Las llamadas posicionales de los tests (`(None, config)`) siguen
  valiendo porque el orden no cambia.
- **Decisión**: el documento con `= None` en las cinco firmas; el destino sin
  valor por defecto. Sin token y sin documento: `invalid_argument` con `field`.
  `ha_create_or_update_scene` también: la escena nueva no pide token, así que
  sin `config` es siempre `invalid_argument`.
- **Validación del documento**: solo cuando viene. El guardado ya se validó
  (y se normalizó, en automatizaciones, scripts y escenas) en la vista previa;
  se ejecuta lo guardado tal cual.

## R-6 — Qué dice la vista previa

- **Decisión**: con documento guardado, `confirm_with`, `omit_on_confirm` y
  `confirm_hint` en el primer nivel de la respuesta, junto a
  `confirmation_token`. Sin documento guardado (tope), `confirm_with` con todos
  los argumentos y un `confirm_hint` que pide reenviarlos; sin
  `omit_on_confirm`. Tools sin omitibles: respuesta idéntica a 1.1.1.
- **Guardián de tamaño**: `_recortar_vista_previa` (`tools/_common.py`) trata
  como intocables `confirmation_token` y `expires_in_seconds`; se añaden los
  tres campos nuevos y se incluyen en el mínimo de último recurso. Sin eso,
  una vista previa enorme podría perder justo la pista que evita reenviar el
  documento.
- **Guía**: `INSTRUCTIONS` (punto 1), temas `security`, `files` y `workflows`
  de `hermes/src/hermes/tools/guide.py`. Hoy dicen «Repite la MISMA llamada
  con los MISMOS argumentos».

## R-7 — Disco: borrado, tope y reinicio

- **Borrado al completar**: `complete_confirmation_token` quita `stored_args`
  y `stored_bytes` y conserva `state`, `cached_result` / `cached_error` y la
  prórroga de 60 s para «already used».
- **Borrado al caducar**: `validate`/`resolve` ya borran el fichero al
  detectar la caducidad. Se añade un barrido de caducados al crear cada token
  (el mismo código que `cleanup_expired_confirmations`, sacado a una función
  síncrona) y la limpieza periódica de `__main__.py`
  (`CONFIRMATIONS_CLEANUP_INTERVAL_SECONDS`) pasa de 3600 a 60 s. Un token en
  `executing` tras un fallo a mitad conserva su `expires_at` original, así que
  también se barre.
- **Tope**: `CONFIRMATION_STORED_MAX_BYTES = 16 MiB`: la suma de los bytes de
  los documentos guardados en los tokens vigentes (`stored_bytes`), más los del
  documento nuevo. Se suma en el mismo barrido de caducados, que ya lee cada
  fichero para mirar su `expires_at`, así que no añade lecturas. Si
  el documento nuevo no cabe, se emite el token sin guardarlo (R-6) y se
  registra `confirmation_args_not_stored` con `tool`, `reason="storage_cap"`
  y `bytes`. Sin tope, 120 peticiones/min × 4 MiB dejan hasta ~480 MiB en
  `/data` durante un minuto.
- **Por petición**: no hace falta tope propio; el documento llega en una
  petición acotada por `max_request_body_bytes` (4 MiB por defecto).
- **Reinicio**: el fichero vive en `/data/pending_confirmations` y sobrevive a
  un reinicio; dentro del TTL la confirmación sin documento funciona. Si se
  perdió, «expired or lost across restart», como hoy. `cleanup_expired_confirmations`
  ya se ejecuta al arrancar.
- **Escritura**: un documento de 4 MiB se escribe de forma síncrona en el
  bucle de eventos (unos milisegundos); hoy ya se canonicaliza y se hashea
  entero en la misma llamada. Se acepta.

## R-8 — Log

- **Hallazgo**: `security.py` no registra argumentos; las tools registran
  `url_path`, `automation_id`, `reason`… nunca el documento.
- **Decisión**: los eventos nuevos (`confirmation_args_not_stored`) llevan
  solo `tool`, `reason`, nombres de claves y `bytes`. Test que captura el log
  de vista previa, confirmación, tope y caducidad con un contenido centinela
  ficticio y comprueba que no aparece.

## R-9 — Principio IV

- **Hallazgo**: la constitución dice «la segunda, con los mismos argumentos y
  el token, ejecuta»; `docs/PRINCIPIOS.md` dice «primera llamada devuelve
  `preview`, segunda ejecuta» y que el token está atado a la tool y a sus
  argumentos.
- **Decisión**: enmienda explícita en el mismo cambio (Governance). Nuevo
  texto: la segunda llamada lleva el token y repite los argumentos, salvo los
  documentos que la tool declare omitibles, que el servidor guardó en la vista
  previa; lo que se repite tiene que coincidir. El token sigue atado a la tool
  y a sus argumentos —los de la vista previa, guardados en el servidor—,
  caduca y es de un solo uso. Versión de la constitución 1.0.0 → 1.1.0 (MINOR:
  amplía el principio sin romper lo anterior, porque repetirlo todo sigue
  valiendo). `Last Amended`: 2026-11-14.

## R-10 — Documentación

- `README.md` / `README.es.md`: «no hacen nada hasta que se les vuelve a llamar
  con ese token»; sigue siendo cierto, no se tocan.
- `hermes/DOCS.md`: no habla de repetir argumentos; no se toca.
- `SECURITY.md`: «The token is bound to the tool and its arguments» sigue
  siendo cierto; se añade que los argumentos grandes de la vista previa se
  guardan en el almacenamiento del add-on hasta completar o caducar.
- `hermes/CHANGELOG.md`: `## [1.1.2] — 2026-11-14` con «Fixed» (el problema) y
  «Changed» (documento opcional en cinco tools, campos nuevos de la vista
  previa, limpieza cada 60 s), al estilo de la 1.1.1.
- `docs/HOJA-DE-RUTA.md`: «Problemas conocidos de 1.1.1» → resuelto en 1.1.2;
  la prueba en vivo del dashboard grande, en «Pruebas manuales pendientes».
