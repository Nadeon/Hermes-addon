# Investigación: publicación con las actions nuevas de HA

Fecha: 2026-11-14. Fuentes leídas en clones superficiales de los repositorios
públicos y en el registro `ghcr.io` (lectura anónima).

## Fuentes

| Fuente | Qué se usa |
|---|---|
| `https://github.com/home-assistant/builder` — `README.md` | La action `home-assistant/builder` está «deprecated and no longer maintained» (última release 2026.02.1) y se retirará; la sustituyen `prepare-multi-arch-matrix`, `build-image`, `publish-multi-arch-manifest` y `cosign-verify`. Los jobs que firman necesitan `id-token: write` y `packages: write`. |
| `home-assistant/builder`, etiqueta `2026.09.0` = commit `7412f0023ea9b6e58e8bb5059f1660f51376f49a` — `actions/build-image/action.yml` | Entradas y comportamiento de `build-image` (abajo). |
| Ídem — `actions/publish-multi-arch-manifest/action.yml` y `actions/prepare-multi-arch-matrix/action.yml` | Ambas construyen nombres `<prefijo>/<arch>-<nombre>`. |
| `https://github.com/home-assistant/apps-example` — `.github/workflows/build-app.yaml` y `builder.yaml` | Flujo de referencia: fija `@2026.09.0`; `push: ${{ inputs.publish }}` (falso en PR); labels `io.hass.type=app`, `io.hass.name`, `io.hass.description` e `io.hass.url` por la entrada `labels`; `id-token: write` + `packages: write` en el job que compila. |
| `https://github.com/home-assistant/developers.home-assistant` — `blog/2026-04-02-builder-migration.md` («Migrating app builds to Docker BuildKit») | `build.yaml` deja de usarse; `build_from` pasa a `FROM` en el Dockerfile; los args, a `ARG` con valor por defecto; las actions nuevas no añaden `io.hass.type/name/description/url`; `{arch}` en `image:` sigue soportado por compatibilidad. |
| `https://github.com/home-assistant/supervisor` — `supervisor/apps/build.py`, `supervisor/const.py` | Sin `build.yaml` el Supervisor no pasa `BUILD_FROM` (el Dockerfile debe traer su base); al compilar en local pone `io.hass.type=app` y pasa `BUILD_ARCH`/`BUILD_VERSION`. `META_ADDON = "addon"` es legado; `META_APP = "app"`, el valor actual. |
| Ídem — `supervisor/apps/validate.py` (`timeout`, por defecto 10 s) | Plazo de parada del contenedor. |
| `ghcr.io/v2/home-assistant/base-python` (consulta anónima) | `3.13-alpine3.24` existe y es un índice OCI multi-plataforma (linux/amd64 y linux/arm64). Hay también etiquetas fechadas (`3.13-alpine3.24-2026.10.3`, la más reciente). |

## R1. Qué action sustituye al builder y a qué versión se fija

- **Decisión**: `home-assistant/builder/actions/build-image@7412f0023ea9b6e58e8bb5059f1660f51376f49a # 2026.09.0`.
- **Razón**: es la release más reciente (etiquetas: …, 2026.06.0, 2026.09.0) y la que usa el repositorio de ejemplo de HA. Fijarla por SHA, con la release en un comentario, hace la referencia inmutable aunque alguien mueva la etiqueta; la propia action fija así sus dependencias. Entre `2026.09.0` y la rama principal solo cambian versiones de dependencias (`login-action` 4.6→4.8, `setup-buildx-action` 4.3→4.4.1, `cosign-installer` 4.1.2→4.1.3, `build-push-action` 7.3→7.4); ninguna entrada nueva.
- **Alternativas**: `@master` (prohibido: es justo lo que se rompe); la etiqueta sin SHA (mutable).

### Entradas de `build-image` que se usan

| Entrada | Valor | Nota |
|---|---|---|
| `arch` | `amd64` / `aarch64` | Pasa `BUILD_ARCH` y la label `io.hass.arch`. |
| `image` | `ghcr.io/nadeon/hermes-<arch>` | Nombre completo sin etiqueta: admite cualquier nombre, así que DECISIÓN 11 se mantiene. |
| `image-tags` | `<versión>` y `latest` | Como publicaba el builder antiguo. |
| `version` | `<versión>` | Pasa `BUILD_VERSION` y las labels `io.hass.version` y `org.opencontainers.image.version`. |
| `context` | `hermes` | El Dockerfile por defecto es `<context>/Dockerfile`. |
| `labels` | `io.hass.type=app`, `io.hass.name`, `io.hass.description`, `io.hass.url` | Sacadas del manifiesto, como en apps-example. |
| `push` | `"true"` al publicar, `"false"` en PR | Con `false` no hace login, no firma y no exporta la imagen. |
| `skip-existing` | `<versión>` al publicar | Si `image:<versión>` existe, compila pero no sube ni firma (deja un aviso). |
| `container-registry-password` | `secrets.GITHUB_TOKEN` | Obligatoria aunque con `push: false` no se use. |
| `cosign` | por defecto, `"true"` | Firma `image@digest` sin clave (identidad OIDC del workflow) solo si publica. Verifica la caché `image:latest` con `allow-failure`: las imágenes actuales no están firmadas, así que la primera vez no se usa la caché del registro. |

Salida: `digest`.

## R2. Compilación de aarch64

- **Decisión**: runner nativo `ubuntu-24.04-arm` (amd64 en `ubuntu-24.04`), los mismos que asigna `prepare-multi-arch-matrix`.
- **Razón**: `build-image` no pasa `--platform` y compila para la plataforma del runner. Así se elimina QEMU. El repositorio es público, y ahí los runners ARM están disponibles.
- **Alternativa**: QEMU en `ubuntu-latest`: exigiría pasar la plataforma, que la action no expone.

## R3. Manifiesto multi-arquitectura

- **Decisión**: no publicarlo en esta spec. Tampoco se usa `prepare-multi-arch-matrix`: la matriz se arma en el job `comprobar` a partir de `arch:` e `image:` del manifiesto.
- **Razón**: `publish-multi-arch-manifest` y `prepare-multi-arch-matrix` construyen `<prefijo>/<arch>-<nombre>`, sin opción para cambiar el orden. Hermes publica `hermes-<arch>` (DECISIÓN 11) e `image:` usa `{arch}`, así que el Supervisor no necesita manifiesto.
- **Alternativas**: renombrar a `<arch>-hermes` (rompe DECISIÓN 11 y obliga a mantener los nombres viejos); `docker buildx imagetools create` a mano (fuera de alcance).

## R4. Imagen base y labels del Dockerfile

- **Decisión**: `ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.13-alpine3.24` y `FROM ${BUILD_FROM}`; `LABEL io.hass.type="app"` junto a `io.hass.version`/`io.hass.arch`, a partir de `BUILD_VERSION`/`BUILD_ARCH`.
- **Razón**: la imagen existe y es multi-arquitectura; mantiene Python 3.13 y sube Alpine de 3.23 a 3.24, la versión por defecto de docker-base. La etiqueta sin fecha recibe los parches de esa combinación. `io.hass.type="app"` es el valor vigente (el Supervisor acepta los dos).
- **Alternativas**: etiqueta fechada `3.13-alpine3.24-2026.10.3` (reproducible, pero sin parches salvo cambio manual); Python 3.14 (cambio de runtime, fuera de alcance).

## R5. `build.yaml`

- **Decisión**: borrarlo.
- **Razón**: el flujo nuevo no lo lee, y el Supervisor avisa de que está deprecado cuando lo encuentra en una compilación local; con `BUILD_FROM` por defecto el Dockerfile se basta solo.

## R6. `timeout` de parada

- **Decisión**: `timeout: 20` en `hermes/config.yaml` y comprobación en CI de `timeout × 1000 > S6_KILL_GRACETIME`.
- **Razón**: el Supervisor espera `timeout` (10 s por defecto) antes del SIGKILL de Docker, lo mismo que el margen de s6 (`S6_KILL_GRACETIME=10000`): la carrera puede cortar el apagado ordenado.

## R7. Validación en PR

- **Decisión**: el mismo workflow, disparado en `pull_request` con filtro de rutas, con un job `validar` de solo lectura y `push: "false"`.
- **Razón**: ejecuta exactamente las mismas actions y entradas que la release; los permisos son por job y la PR no debe poder escribir.

## R8. Herramientas del runner

- `yq` (mikefarah) y `jq` vienen preinstalados en las imágenes Ubuntu de GitHub; se usan para leer el manifiesto y construir la matriz.
