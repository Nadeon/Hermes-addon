# Política de seguridad de Hermes

Hermes expone Home Assistant **completo** a un cliente MCP (Claude) a través de
internet, detrás de un proxy inverso (Tailscale Funnel, Cloudflare Tunnel o
similar). Es un componente sensible: la seguridad es un requisito de primer
nivel, no un extra.

## Reportar una vulnerabilidad

**No abras un issue público.** Usa el canal privado de GitHub:

**[Security → Report a vulnerability](../../security/advisories/new)**

Es un formulario privado entre quien reporta y el mantenedor. No hay correo de
por medio, no queda indexado, y GitHub se encarga de coordinar la publicación
del aviso cuando el fallo esté corregido.

Incluye, si puedes: descripción, pasos de reproducción, impacto y versión de
Hermes. El `X-Request-ID` de la respuesta y las líneas del log alrededor del
fallo ayudan mucho.

Se agradece la divulgación responsable y se da crédito a quien lo desee.

## Modelo de seguridad

- **TLS** lo termina siempre el proxy de delante; Hermes habla HTTP plano en
  `mcp_bind:8765` (por defecto `127.0.0.1`) y nunca gestiona certificados.
  El bind por defecto lo hace inalcanzable desde fuera del host: la única
  vía de entrada es el proxy. **No lo pongas en `0.0.0.0`**: eso publicaría
  Hermes sin cifrar en toda la red local, saltándose el TLS.
- **Autenticación**: OAuth 2.1 con PKCE obligatorio (S256), Dynamic Client
  Registration, tokens opacos de alta entropía almacenados solo como hash
  SHA-256, auth codes de un solo uso, y revocación (RFC 7009).
- **La contraseña del add-on (`auth_password`) es el único secreto que protege
  todo el sistema.** Debe ser larga y aleatoria. Hermes exige un mínimo de
  12 caracteres al arrancar y aplica un *throttle* con backoff exponencial ante
  intentos de login fallidos.
- **Defensa en profundidad** sobre las acciones:
  - `confirmation_token` para toda operación destructiva (escribir/borrar
    ficheros, reiniciar, desinstalar add-ons, restaurar backups, servicios
    peligrosos…).
  - Denylist de servicios + sanitización recursiva de `service_data` +
    auto-clasificación de scripts/automations peligrosos.
  - Filesystem `/config`: anti-traversal (resolve + boundary check), blacklist
    de secretos, allowlist *default-deny* para `.storage/`, *managed paths*
    nunca escribibles, backup automático antes de cada escritura.
  - Validación de identificadores (slug/entry_id/…) antes de interpolarlos en
    URLs, más un guard central anti path-injection en el cliente HA.
- **Redacción de secretos** en todos los logs (propios y de add-ons).
- **Cabeceras de seguridad** (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, CSP) y límite de tamaño de cuerpo (incl. `chunked`).

## Supuestos y limitaciones conocidas

Estos puntos son **inherentes al diseño**; se documentan para que el operador
los conozca y los tenga en cuenta:

1. **Confianza en el cliente MCP.** El `confirmation_token` se entrega al propio
   cliente (Claude), que puede reenviarlo. No es una aprobación humana forzada:
   el "humano en el bucle" real es el *preview* que el cliente MCP muestra antes
   de confirmar. Trata el acceso a Hermes como acceso de administrador a HA.
2. **Token de Supervisor con rol admin.** El add-on usa el `SUPERVISOR_TOKEN`
   para operar; quien supere la autenticación tiene capacidades de
   administrador sobre Home Assistant. Por eso la fortaleza de `auth_password`
   es crítica.
3. **La IP de origen sirve para limitar, nunca para autorizar.** Con
   `network_mode: tailscale`, la IP real del cliente sí llega a Hermes: el proxy
   entrega la petición desde el loopback y el servidor confía en su
   `X-Forwarded-For`, que ese proxy reescribe. Con `network_mode: reverse_proxy`
   y `mcp_bind` en la red puente, la cabecera se ignora y el límite por IP pasa a
   ser un techo global. En ningún caso la IP concede acceso: solo alimenta el
   rate limit y los logs. La defensa específica contra fuerza bruta es el
   *throttle* de fallos de login, que es global a propósito.
4. **Contenedor como root.** Como la mayoría de add-ons de HAOS, el contenedor
   necesita acceso a `/config` y `/data` y se ejecuta como root dentro de su
   espacio aislado por el Supervisor.

## Recomendaciones de despliegue

- Usa una `auth_password` generada por un gestor de contraseñas (≥ 24 caracteres
  recomendados).
- Mantén actualizado el add-on que publica el hostname (Tailscale,
  Cloudflared…) y revisa periódicamente qué está expuesto.
- Un túnel (Tailscale Funnel o Cloudflare Tunnel) no abre puertos en tu
  router; un proxy inverso clásico exige abrir el 443 y deja tu instalación
  directamente expuesta. A igualdad de todo lo demás, prefiere el túnel.
- Revisa los logs (`ha addons logs hermes -f`) ante eventos
  `oauth_login_locked`, `oauth_login_throttled` o `auth_rejected` repetidos.

## Versiones soportadas

Se da soporte de seguridad a la **última versión** publicada. Consulta
[CHANGELOG.md](CHANGELOG.md).
