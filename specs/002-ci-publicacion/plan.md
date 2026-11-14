# Plan de implementación: publicación con las actions nuevas de HA

**Rama**: no se crea (directorio `002-ci-publicacion`) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md)

**Entrada**: especificación de `specs/002-ci-publicacion/spec.md`

## Resumen

Sustituir el paso `home-assistant/builder@master` de `publicar-imagen.yml` por la
action compuesta `home-assistant/builder/actions/build-image`, fijada por SHA a
la release `2026.09.0`, compilando cada arquitectura en un runner nativo. El job
de comprobación pasa a derivar del manifiesto (`hermes/config.yaml`) la versión,
las arquitecturas, el nombre de imagen (`image:` con `{arch}`) y los metadatos
de las labels, y valida que `timeout` supere `S6_KILL_GRACETIME`. El mismo
workflow se dispara en `pull_request` (con filtro de rutas) y compila sin
publicar en un job aparte con permisos de solo lectura. El Dockerfile declara
`ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.13-alpine3.24` y
`io.hass.type="app"`; `build.yaml` se borra; `config.yaml` gana `timeout: 20`.

No se usa `publish-multi-arch-manifest` (ver research.md, R3): solo combina
imágenes `<arch>-<nombre>` y DECISIÓN 11 mantiene `hermes-<arch>`.

## Technical Context

**Language/Version**: YAML de GitHub Actions; Dockerfile (BuildKit); el add-on sigue en Python 3.13.

**Primary Dependencies**: `home-assistant/builder/actions/build-image@7412f0023ea9b6e58e8bb5059f1660f51376f49a` (2026.09.0), que a su vez fija `docker/login-action`, `docker/setup-buildx-action`, `docker/build-push-action`, `sigstore/cosign-installer` y `cosign-verify` por SHA; `actions/checkout@v5` (la que ya usa el repo).

**Storage**: registro `ghcr.io` (imágenes `ghcr.io/nadeon/hermes-{amd64,aarch64}`).

**Testing**: `actionlint` en local para la sintaxis; la suite de pytest existente (incluye tests que leen `config.yaml` y el Dockerfile); en GitHub, el job de validación de PR compila ambas arquitecturas.

**Target Platform**: runners `ubuntu-latest` (comprobación), `ubuntu-24.04` (amd64) y `ubuntu-24.04-arm` (aarch64).

**Project Type**: app de Home Assistant (contenedor) + CI.

**Performance Goals**: sin QEMU, la compilación de aarch64 deja de ser emulada; la caché de GHA se mantiene por arquitectura.

**Constraints**: permisos mínimos por job; ninguna action a rama; nombres de imagen invariables; `etiquetar.yml` sin cambios; solo se tocan los ficheros permitidos (workflows, Dockerfile, build.yaml, la clave `timeout` de config.yaml, CONTRIBUTING*).

**Scale/Scope**: 1 workflow reescrito, 1 comentario en `tests.yml`, Dockerfile, borrado de build.yaml, 1 clave en config.yaml, 1 párrafo en cada CONTRIBUTING.

## Constitution Check

*GATE: antes de la fase 0 y otra vez tras la fase 1.*

| Principio | Cumplimiento |
|---|---|
| I. Seguridad primero | Permisos mínimos por job: `contents: read` global; `id-token`/`packages: write` solo en el job que publica. Las entradas del usuario (`inputs.version`) pasan por variables de entorno, no interpoladas en el shell. Actions fijadas por SHA. Firma cosign activada. |
| II. Secretos | Solo `GITHUB_TOKEN`; el job de PR no recibe secretos. |
| III. Fail-closed | La comprobación aborta si la versión no coincide, si `image:` no tiene `{arch}`, si el prefijo no es el del propietario al publicar o si `timeout` no supera el margen de s6. `skip-existing` impide sobrescribir una versión publicada. |
| IV, V | No aplican (no cambia ninguna tool). |
| VI. Lo que no se prueba no está arreglado | La invariante `timeout > S6_KILL_GRACETIME` se comprueba en CI; el flujo de publicación se ejecuta en cada PR que toca la imagen. Desviación justificada: no se añade test de pytest porque `tests/` queda fuera del alcance permitido (otra spec trabaja en paralelo); se anota para una spec futura. |
| VII. Control negativo | No hay arreglo de código Python. Control negativo de la validación: se ejecuta en local el script de comprobación con `timeout: 10` y con `image:` sin `{arch}` y debe fallar (ver quickstart). |
| VIII. Privacidad | Solo nombres públicos (`ghcr.io/nadeon/...`, ya presentes en el repo). Sin rutas de máquina ni identificadores de modelos. Grep previo al commit. |
| IX. Cambios mínimos | Solo los ficheros permitidos; no se actualizan otras actions (`checkout@v5` se queda) ni se renombra la imagen. |
| X. Comentarios en español con el porqué | Los comentarios del workflow y del Dockerfile explican el porqué. |
| XI. Versionado | No se sube la versión; la cadena etiquetar → publicar se conserva. |

**Resultado**: PASA (con la desviación de VI justificada).

## Project Structure

### Documentación (esta funcionalidad)

```text
specs/002-ci-publicacion/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── imagen-publicada.md
├── checklists/requirements.md
└── tasks.md
```

### Código fuente (raíz del repositorio)

```text
.github/workflows/
├── publicar-imagen.yml   # reescrito: comprobar → validar (PR) | construir (tag/dispatch)
└── tests.yml             # solo el comentario que citaba build.yaml
hermes/
├── Dockerfile            # ARG BUILD_FROM con valor por defecto, io.hass.type="app"
├── build.yaml            # BORRADO
└── config.yaml           # + timeout: 20
CONTRIBUTING.md / CONTRIBUTING.es.md   # un párrafo sobre la compilación en PR
```

**Decisión de estructura**: un solo workflow para la validación y la publicación, para que la PR ejecute exactamente las mismas actions y entradas que la release; dos jobs separados (`validar` y `construir`) porque los permisos de GitHub Actions son estáticos por job y la validación no debe tener permisos de escritura.

## Diseño del workflow

1. **Disparadores**: `push` de etiquetas `v*.*.*` (lo que sube `etiquetar.yml` con `RELEASE_TOKEN`), `workflow_dispatch` con `version`, y `pull_request` con filtro de rutas (`hermes/Dockerfile`, `hermes/requirements.txt`, `hermes/run.sh`, `hermes/src/**`, `hermes/config.yaml`, el propio workflow).
2. **`comprobar`** (`contents: read`): lee el manifiesto con `yq` (preinstalado en los runners Ubuntu); en tag/dispatch exige versión = manifiesto; exige `{arch}` en `image:` y, al publicar, el prefijo `ghcr.io/<propietario en minúsculas>/`; exige `timeout*1000 > S6_KILL_GRACETIME`; emite `version`, `matrix` (arch, os, image) y `name`/`description`/`url` para las labels.
3. **`validar`** (solo `pull_request`, `contents: read`): `build-image` con `push: "false"`.
4. **`construir`** (tag/dispatch; `contents: read`, `id-token: write`, `packages: write`): `build-image` con `push: "true"`, `image-tags` = versión y `latest`, `skip-existing` = versión y cosign por defecto.

## Complexity Tracking

| Desviación | Por qué hace falta | Alternativa más simple descartada |
|---|---|---|
| Matriz propia en vez de `prepare-multi-arch-matrix` | Esa action genera `<prefijo>/<arch>-<nombre>`, incompatible con `hermes-<arch>` | Usarla y renombrar la imagen: rompe DECISIÓN 11 |
| Dos jobs casi iguales (`validar` y `construir`) | Permisos por job; la PR no debe poder escribir en el registro ni pedir un token OIDC | Un job con permisos de escritura también en PR |
