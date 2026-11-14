# Tareas: publicación con las actions nuevas de HA

**Entrada**: documentos de diseño de `specs/002-ci-publicacion/`

**Requisitos previos**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: la spec no pide tests de pytest nuevos (tests/ está fuera del alcance de esta spec); la validación es actionlint, la suite existente y el control negativo del script de comprobación.

## Formato: `[ID] [P?] [Historia] Descripción`

## Fase 1: Preparación

- [X] T001 Instalar actionlint en un entorno temporal fuera del repositorio y ejecutarlo sobre `.github/workflows/*.yml` para tener la línea base

---

## Fase 2: Base (bloquea todas las historias)

- [X] T002 Reescribir el job `comprobar` de `.github/workflows/publicar-imagen.yml`: `permissions: contents: read` a nivel de workflow; leer `hermes/config.yaml` con `yq`; en tag o dispatch exigir que la versión pedida (por `env`, nunca interpolada en el script) coincida con `version:`; exigir que `image:` contenga `{arch}` y, al publicar, que empiece por `ghcr.io/<propietario en minúsculas>/`; mapear `arch:` a runner (`amd64` → `ubuntu-24.04`, `aarch64` → `ubuntu-24.04-arm`, cualquier otra aborta) y emitir `matrix` (`{arch, os, image}`), `version`, `publicar`, `name`, `description` y `url`

---

## Fase 3: Historia 1 — Publicar una versión con los nombres de siempre (P1) 🎯 MVP

**Objetivo**: la etiqueta `v<versión>` publica `ghcr.io/nadeon/hermes-{amd64,aarch64}:<versión>` con las actions nuevas, firmadas.

**Prueba independiente**: etiquetar en GitHub y comprobar las dos imágenes (quickstart, «En GitHub», 2–5).

- [X] T003 [US1] Sustituir el job `construir` de `.github/workflows/publicar-imagen.yml` por uno que, solo fuera de `pull_request`, recorra la matriz de `comprobar` en `runs-on: ${{ matrix.os }}` y llame a `home-assistant/builder/actions/build-image@7412f0023ea9b6e58e8bb5059f1660f51376f49a # 2026.09.0` con `context: hermes`, `image: ${{ matrix.image }}`, `image-tags` = versión y `latest`, `version`, labels `io.hass.type=app`/`io.hass.name`/`io.hass.description`/`io.hass.url`, `push: "true"`, `skip-existing` = versión y `container-registry-password: ${{ secrets.GITHUB_TOKEN }}`; permisos `contents: read`, `id-token: write`, `packages: write`; quitar QEMU y el login manual
- [X] T004 [US1] Conservar en `.github/workflows/publicar-imagen.yml` los disparadores `push: tags: v*.*.*` y `workflow_dispatch` con `version`, y comprobar que `.github/workflows/etiquetar.yml` no necesita cambios
- [X] T005 [P] [US1] `hermes/Dockerfile`: `ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.13-alpine3.24`, `FROM ${BUILD_FROM}`, `io.hass.type="app"` y comentarios con el porqué
- [X] T006 [P] [US1] Borrar `hermes/build.yaml` y actualizar el comentario que lo citaba en `.github/workflows/tests.yml`

---

## Fase 4: Historia 2 — La PR compila sin publicar (P2)

**Objetivo**: en `pull_request` se compilan ambas arquitecturas con las mismas actions, sin push y con permisos de lectura.

**Prueba independiente**: abrir una PR que toque `hermes/Dockerfile` (quickstart, «En GitHub», 1).

- [X] T007 [US2] Añadir a `.github/workflows/publicar-imagen.yml` el disparador `pull_request` con filtro de rutas (`hermes/Dockerfile`, `hermes/requirements.txt`, `hermes/run.sh`, `hermes/src/**`, `hermes/config.yaml`, el propio workflow) y el job `validar` (solo en `pull_request`, `permissions: contents: read`) con la misma llamada a `build-image` que T003 pero `push: "false"` y sin `skip-existing`
- [X] T008 [P] [US2] Documentar en `CONTRIBUTING.md` y `CONTRIBUTING.es.md` (sección de versión) que las PR que tocan la imagen la compilan para las dos arquitecturas sin publicarla

---

## Fase 5: Historia 3 — Apagado sin SIGKILL prematuro (P3)

**Objetivo**: `timeout` del Supervisor > margen de s6.

**Prueba independiente**: la comprobación de `comprobar` falla con `timeout: 10` y pasa con `timeout: 20`.

- [X] T009 [US3] Añadir `timeout: 20` con su comentario en la sección «Ciclo de vida» de `hermes/config.yaml` (ninguna otra clave cambia)
- [X] T010 [US3] Añadir al job `comprobar` de `.github/workflows/publicar-imagen.yml` la comprobación `timeout × 1000 > S6_KILL_GRACETIME` (leído de `hermes/Dockerfile`)

---

## Fase 6: Historia 4 — Compilar en local sin ficheros deprecados (P3)

**Objetivo**: el Dockerfile se basta solo. Lo cubren T005 y T006.

- [X] T011 [US4] Verificar que `hermes/Dockerfile` no necesita ningún `--build-arg` obligatorio (todos los `ARG` usados tienen valor por defecto o solo alimentan labels) y que ningún fichero del repositorio cita ya `build.yaml`

---

## Fase 7: Pulido y verificación

- [X] T012 Ejecutar actionlint sobre `.github/workflows/*.yml` → sin errores
- [X] T013 Control negativo: extraer el script de `comprobar` y ejecutarlo en local contra el manifiesto real (pasa, 2 filas), contra uno con `timeout: 10` y contra uno sin `{arch}` (fallan)
- [X] T014 Ejecutar la suite completa de pytest desde la raíz del repositorio → todo en verde
- [X] T015 Revisar el diff en busca de datos personales e identificadores de modelos (principio VIII) y hacer commit con el mensaje `ci: publicación con las actions nuevas de HA (spec 002)`

---

## Dependencias

- T002 bloquea T003, T007 y T010 (mismo fichero, usan sus salidas).
- T003 → T007 (`validar` replica la llamada de `construir`).
- T005, T006, T008 y T009 son independientes entre sí ([P]).
- T012–T015 al final.

## Ejecución en paralelo

- Tras T002: T005, T006, T008 y T009 en paralelo; T003 → T007 → T010 en serie (mismo fichero).

## Estrategia

MVP = Fase 2 + Historia 1 (sin ella la próxima release se queda sin imagen). Historia 2 se añade en el mismo cambio porque es la única forma de validar la migración antes de la release.
