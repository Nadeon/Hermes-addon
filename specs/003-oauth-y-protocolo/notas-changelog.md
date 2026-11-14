<!-- Notas de la spec 003 para `hermes/CHANGELOG.md`. La integración final de
     la 1.1.0 las copia bajo `## [1.1.0] — AAAA-MM-DD`, junto a las de las
     specs 004 y 005, y borra este fichero. Mismo formato que el CHANGELOG. -->

### Added — Clientes con documento de metadatos (CIMD)

Claude Code, y cualquier cliente que publique un *Client ID Metadata Document*,
se identifica ahora con la URL de ese documento en lugar de registrarse por
DCR. Hermes lo descarga, comprueba su forma y sus `redirect_uris`, y la
pantalla de autorización muestra el host de esa URL, el nombre que declara el
cliente y a dónde irá el código. Los documentos válidos se guardan en memoria
según su `Cache-Control` (entre 5 min y 24 h); si una recarga dice que el
documento ya no es válido, se revocan los refresh tokens de ese cliente.

DCR sigue funcionando igual: los clientes y tokens que ya existían siguen
valiendo. La opción nueva `oauth_cimd_enabled` (por defecto `true`) desactiva
CIMD si un cliente falla con él.

### Added — Parámetro `iss` en las redirecciones (RFC 9207)

Toda redirección de vuelta al cliente, de éxito o de error, lleva `iss` con el
mismo valor que `issuer` en los metadatos, que ahora anuncian
`authorization_response_iss_parameter_supported`. El cliente puede comprobar
así que la respuesta viene de Hermes y no de otro servidor.

### Added — Metadatos OAuth y audiencia de los tokens

Los metadatos del recurso protegido anuncian `scopes_supported: ["mcp"]` y el
`WWW-Authenticate` de los 401 lleva `scope="mcp"`. Los tokens emitidos desde
esta versión quedan ligados al recurso `/mcp` de Hermes; los de versiones
anteriores se aceptan hasta que caduquen y su renovación ya sale ligada.

### Added — Redacción de red en el log

La opción nueva `log_redact_network` (por defecto `true`) sustituye en el log
el `public_hostname`, cualquier nombre `*.ts.net` y las IPs que no sean de
loopback por marcadores. Las IPs pasan a un seudónimo con su clase (`tailnet`,
`private`, `public`…) que cambia en cada arranque, de modo que las líneas de
una misma ejecución se pueden correlacionar sin revelar la dirección. Cubre
también los mensajes del SDK de MCP, uvicorn y aiohttp, y las líneas que
devuelve `sv_get_addon_logs` sobre el propio Hermes, incluidas las escritas
antes de actualizar. Así el log se puede pegar al pedir ayuda. Con la opción
desactivada, el arranque lo avisa con `log_network_redaction_disabled`; los
secretos se redactan siempre.

### Added — Datos del servidor MCP

El servidor anuncia su versión en `serverInfo`, cada tool lleva un `title`
legible y las respuestas con `error` salen marcadas con `isError: true`, con el
mismo contenido que antes. Los nombres, parámetros y anotaciones de las tools
no cambian.

### Changed — Límites alineados con los de Claude

`response_max_bytes` pasa de 1 MiB a **128 KiB** por defecto, con un máximo
efectivo de **512 KiB**; `wait_for_event_max_seconds` admite como mucho **220 s**
(el defecto sigue en 90).

Si tenías valores guardados: la interfaz guarda el valor por defecto aunque
nadie lo toque, así que un `response_max_bytes` de `1048576` se trata como no
personalizado y pasa a `131072`. Un valor por encima de `524288`, o un
`wait_for_event_max_seconds` por encima de `220`, se recorta al máximo. El
add-on arranca igual y lo anota en el log (`config_legacy_default_replaced` o
`config_value_clamped`, con el valor guardado y el aplicado). Si necesitas
respuestas más grandes, sube `response_max_bytes` hasta `524288`.

Claude Code corta una llamada si no recibe ningún byte en 60 s. Hermes manda
un *ping* cada 15 s, así que una espera larga no se corta; si el proxy de
delante almacena la respuesta, DOCS.md explica cómo ampliar el plazo en Claude
Code.

### Changed — El protocolo MCP usa las listas de versiones nuevas del SDK

El middleware de versión de protocolo obtiene las versiones admitidas de
`HANDSHAKE_PROTOCOL_VERSIONS` y `MODERN_PROTOCOL_VERSIONS` en lugar del alias
deprecado. El conjunto admitido no cambia.

### Security — Descargas de CIMD acotadas contra SSRF

Con CIMD, quien llama al endpoint público `/oauth/authorize` elige una URL que
Hermes descarga. Para que eso no convierta a Hermes en un proxy hacia tu red:
la forma de la URL se comprueba antes de descargar nada; Hermes resuelve el
host y rechaza la petición si **alguna** dirección es de uso especial
(loopback, privadas, link-local, CGNAT y por tanto la tailnet, ULA,
multicast…), y conecta a las direcciones ya validadas sin volver a resolver.
Sin redirecciones ni proxies del entorno, 5 s en total, 5 120 bytes como
mucho, 4 descargas a la vez y 30 por minuto. Cada rechazo queda en el log como
`oauth_cimd_rejected` con el motivo y el host, nunca con el documento.

### Security — El log ya no expone tu hostname ni tus IPs

Ver *Added — Redacción de red en el log*. Hasta la 1.0.12 el hostname de
Tailscale, que identifica la tailnet, y las IPs de los clientes salían en claro
en un log que se suele compartir al pedir ayuda.
