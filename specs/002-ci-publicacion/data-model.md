# Modelo de datos: publicación de la imagen

No hay datos persistentes nuevos. Las «entidades» son los artefactos que el CI
lee y produce.

## Manifiesto (`hermes/config.yaml`; solo lectura, salvo `timeout`)

| Campo | Uso en el CI | Validación |
|---|---|---|
| `version` | Etiqueta de la imagen y `BUILD_VERSION` | En tag o dispatch, debe coincidir con la versión pedida |
| `arch` | Filas de la matriz | Solo `amd64` (runner `ubuntu-24.04`) y `aarch64` (`ubuntu-24.04-arm`); cualquier otra aborta |
| `image` | Nombre por arquitectura (se sustituye `{arch}`) | Debe contener `{arch}`; al publicar, empezar por `ghcr.io/<propietario en minúsculas>/` |
| `name`, `description`, `url` | Labels `io.hass.name/description/url` | — |
| `timeout` | — | `timeout × 1000 > S6_KILL_GRACETIME` del Dockerfile |

## Fila de la matriz

`{arch, os, image}`, p. ej. `{"arch":"aarch64","os":"ubuntu-24.04-arm","image":"ghcr.io/nadeon/hermes-aarch64"}`.

## Imagen publicada

Ver [contracts/imagen-publicada.md](contracts/imagen-publicada.md).
