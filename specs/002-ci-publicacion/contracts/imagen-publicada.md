# Contrato: imagen publicada de Hermes

Lo que el Supervisor y las instalaciones existentes esperan, y que esta
migración no puede cambiar.

| Aspecto | Contrato |
|---|---|
| Nombres | `ghcr.io/nadeon/hermes-amd64` y `ghcr.io/nadeon/hermes-aarch64` (de `image: ghcr.io/nadeon/hermes-{arch}`) |
| Etiquetas | `<version>` de `hermes/config.yaml`, sin `v`; además, `latest` |
| Inmutabilidad | Una `<version>` ya publicada no se sobrescribe |
| Plataforma | `linux/amd64` para `hermes-amd64`; `linux/arm64` para `hermes-aarch64` |
| Labels | `io.hass.type=app`, `io.hass.version=<version>`, `io.hass.arch=<arch>`, `io.hass.name`, `io.hass.description`, `io.hass.url` |
| Firma | Firma cosign sin clave (OIDC de GitHub Actions) sobre el digest de cada imagen publicada |
| Arranque | `CMD ["/app/run.sh"]` sobre el s6-overlay de la imagen base (`init: false`); `S6_KILL_GRACETIME=10000` |
