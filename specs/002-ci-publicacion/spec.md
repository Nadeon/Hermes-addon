# Especificación: publicación de la imagen con las actions nuevas de Home Assistant

**Rama de la funcionalidad**: no se crea rama (`002-ci-publicacion` es solo el directorio de la especificación)

**Creada**: 2026-11-14

**Estado**: Borrador

**Entrada**: descripción del mantenedor: «Migrar la publicación de la imagen de Hermes desde `home-assistant/builder@master` (deprecado) a las actions compuestas nuevas de `home-assistant/builder` fijadas a una release; mantener los nombres de imagen `hermes-{arch}`; Dockerfile con `BUILD_FROM` por defecto y labels `io.hass.*`; borrar `build.yaml`; `timeout: 20` en `config.yaml`; compilación sin push en `pull_request`».

## Contexto

Hermes publica una imagen precompilada por arquitectura (`amd64` y `aarch64`) en
el registro de contenedores de GitHub. El Supervisor de Home Assistant la
descarga al instalar o actualizar la app (antes «add-on»); sin ella, el equipo
del usuario tiene que compilarla desde fuente, entre cinco y diez minutos en un
x86 y bastante más en una Raspberry Pi.

La publicación depende hoy de una action que Home Assistant ha dado por
retirada (post del blog de desarrolladores del 2026-04-02, «Migrating app
builds to Docker BuildKit») y que, según su propio README, dejará de existir
«pronto». Cuando desaparezca, la siguiente versión de Hermes se etiquetará sin
imagen, y la tienda anunciará una actualización que no se puede instalar
(principio XI de la constitución). Además, el fichero `build.yaml` que esa
action leía está deprecado: el Supervisor avisa al leerlo y lo retirará.

## User Scenarios & Testing *(mandatory)*

### Historia 1 — El mantenedor publica una versión y la imagen aparece (Prioridad: P1)

El mantenedor lanza «Etiquetar versión» con la versión nueva. Igual que hoy, la
etiqueta dispara «Publicar imagen», que compila y publica una imagen por
arquitectura con los MISMOS nombres de siempre, sin pasos manuales nuevos y sin
depender de la action retirada.

**Por qué esta prioridad**: es lo que evita la rotura. Sin imagen publicada,
ninguna instalación nueva ni actualización funciona.

**Prueba independiente**: etiquetar una versión en GitHub y comprobar que
existen `ghcr.io/nadeon/hermes-amd64:<versión>` y
`ghcr.io/nadeon/hermes-aarch64:<versión>`, y que un Home Assistant con
`image: ghcr.io/nadeon/hermes-{arch}` instala esa versión.

**Escenarios de aceptación**:

1. **Dado** un `version:` en `hermes/config.yaml` y una etiqueta `v<versión>` que coincide, **cuando** se sube la etiqueta, **entonces** se publican las dos imágenes por arquitectura con la etiqueta `<versión>` (y `latest`) bajo los nombres actuales.
2. **Dada** una etiqueta que NO coincide con el manifiesto, **cuando** se lanza la publicación, **entonces** falla antes de compilar y no publica nada (comportamiento actual, se conserva).
3. **Dada** una versión cuya imagen ya existe en el registro, **cuando** se relanza la publicación, **entonces** la imagen existente no se sobrescribe y el workflow avisa.
4. **Dado** que no existe el secreto `RELEASE_TOKEN`, **cuando** el mantenedor lanza la publicación a mano con la versión, **entonces** funciona igual que hoy.

---

### Historia 2 — Una PR que toca la imagen demuestra que compila, sin publicar (Prioridad: P2)

Quien abre una PR que cambia el Dockerfile, las dependencias, el código que
viaja en la imagen o el propio workflow ve en la PR si la imagen de ambas
arquitecturas compila con exactamente el mismo flujo que se usará al publicar.
Nada se sube al registro.

**Por qué esta prioridad**: hoy el flujo de publicación solo se ejecuta al
etiquetar; un error en él se descubre con la versión ya anunciada. Validarlo en
la PR, y en particular validar ESTA migración antes de la primera release que
la use, es la única red antes de producción.

**Prueba independiente**: abrir una PR que toque `hermes/Dockerfile` y
comprobar que aparecen dos comprobaciones de compilación (una por arquitectura)
que terminan en verde y que el registro no recibe ninguna etiqueta nueva.

**Escenarios de aceptación**:

1. **Dada** una PR que modifica un fichero que entra en la imagen, **cuando** se abre o actualiza, **entonces** se compila la imagen de `amd64` y de `aarch64` sin publicarla.
2. **Dada** una PR desde un fork, **cuando** se ejecuta la validación, **entonces** funciona con permisos de solo lectura y no necesita secretos.
3. **Dada** una PR que solo toca documentación, **cuando** se abre, **entonces** no se lanza la compilación.

---

### Historia 3 — Apagado sin SIGKILL prematuro (Prioridad: P3)

Al parar o actualizar la app, el Supervisor da a Hermes tiempo suficiente para
su apagado ordenado (cerrar conexiones MCP y borrar temporales) antes de
matarlo.

**Por qué esta prioridad**: hoy el plazo del Supervisor (10 s por defecto) es
igual al margen interno de s6 (10 s); la carrera puede dejar temporales en
`/data`. Es un riesgo bajo pero real.

**Prueba independiente**: leer `hermes/config.yaml` y comprobar que el plazo de
parada declarado supera el margen interno de s6 fijado en el Dockerfile; la
validación automática del workflow lo comprueba en cada PR que toca la imagen.

**Escenarios de aceptación**:

1. **Dado** el manifiesto, **cuando** se valida, **entonces** su plazo de parada (20 s) es mayor que el margen interno de s6 (10 s).

---

### Historia 4 — Compilar en local sin ficheros deprecados (Prioridad: P3)

Quien desarrolla quita la línea `image:` del manifiesto, como indica
CONTRIBUTING, y el Supervisor compila la imagen a partir del Dockerfile solo,
sin `build.yaml` y sin el aviso de fichero deprecado.

**Prueba independiente**: con `build.yaml` borrado, el Dockerfile declara por sí
mismo la imagen base por defecto, así que `docker build hermes/` no necesita
argumentos.

**Escenarios de aceptación**:

1. **Dado** el repositorio sin `build.yaml`, **cuando** el Supervisor o `docker build` compilan sin argumentos, **entonces** usan la imagen base Python 3.13 sobre Alpine 3.24 declarada en el Dockerfile.

### Edge Cases

- La action retirada desaparece antes de fusionar esta migración: la publicación actual falla; esta especificación es la corrección.
- El propietario del repositorio en GitHub tiene mayúsculas y los nombres de imagen tienen que ir en minúsculas: el nombre se toma del manifiesto, no del propietario.
- La imagen `latest` existente no está firmada: la verificación de la caché falla de forma tolerada y la compilación sigue sin caché del registro.
- El nombre de imagen del manifiesto deja de contener `{arch}`: la validación falla con un mensaje claro en vez de publicar con un nombre inesperado.
- Un fork de la PR no puede escribir en el registro ni firmar: la validación no lo necesita.
- Cambia el `timeout` o el margen de s6 y el primero deja de superar al segundo: la validación falla.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: La publicación MUST dejar de usar la action retirada `home-assistant/builder@master` y usar las actions de compilación nuevas publicadas por Home Assistant.
- **FR-002**: Toda action de terceros nueva MUST quedar fijada a una release concreta e inmutable (un SHA de commit con la release anotada), nunca a una rama.
- **FR-003**: Los nombres publicados MUST seguir siendo `ghcr.io/nadeon/hermes-amd64` y `ghcr.io/nadeon/hermes-aarch64`, y derivarse del campo `image:` de `hermes/config.yaml` tal como está (DECISIÓN 11). Las imágenes ya publicadas no se tocan.
- **FR-004**: Cada imagen publicada MUST llevar la etiqueta `<versión>` (y `latest`), y no se MUST sobrescribir una `<versión>` que ya exista en el registro.
- **FR-005**: La publicación MUST seguir comprobando, antes de compilar, que la versión de la etiqueta o de la entrada manual coincide con `version:` de `hermes/config.yaml`.
- **FR-006**: El workflow `etiquetar.yml` MUST seguir disparando la publicación sin cambios.
- **FR-007**: Los permisos MUST ser los mínimos por job: lectura por defecto; escritura en el registro y emisión de identidad para firmar solo en el job que publica.
- **FR-008**: Las imágenes publicadas MUST quedar firmadas con el mecanismo de firma que incorporan las actions nuevas.
- **FR-009**: En `pull_request` que toque ficheros que entran en la imagen o el workflow, MUST compilarse la imagen de ambas arquitecturas con las mismas actions y sin publicar, con permisos de solo lectura.
- **FR-010**: El Dockerfile MUST declarar una imagen base por defecto (Python 3.13 sobre Alpine 3.24, multi-arquitectura) y las labels `io.hass.*` necesarias, con `io.hass.type="app"`.
- **FR-011**: `hermes/build.yaml` MUST borrarse, ya que el flujo nuevo no lo lee.
- **FR-012**: `hermes/config.yaml` MUST declarar `timeout: 20`; no se cambia ninguna otra clave de ese fichero.
- **FR-013**: La validación previa MUST fallar si el plazo de parada del manifiesto no supera el margen interno de s6 del Dockerfile, o si `image:` no contiene `{arch}`.
- **FR-014**: La documentación para contribuir MUST explicar que las PR que tocan la imagen la compilan sin publicarla.

### Key Entities

- **Imagen por arquitectura**: `ghcr.io/nadeon/hermes-<arch>:<versión>`, una por cada arquitectura declarada en `arch:` del manifiesto.
- **Manifiesto de la app** (`hermes/config.yaml`): fuente de la versión, de las arquitecturas, del nombre de imagen y de los metadatos (`name`, `description`, `url`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: La próxima versión etiquetada publica sus 2 imágenes sin ninguna intervención manual más allá de lanzar «Etiquetar versión».
- **SC-002**: 0 referencias a la action retirada y 0 actions nuevas fijadas a una rama en los workflows.
- **SC-003**: El 100 % de las PR que tocan la imagen muestran el resultado de compilar las 2 arquitecturas antes de fusionarse, sin publicar nada.
- **SC-004**: Las instalaciones existentes, que apuntan a `hermes-{arch}`, siguen actualizando sin cambiar nada en su configuración.
- **SC-005**: El plazo de parada que concede el Supervisor es al menos un 50 % mayor que el margen interno de apagado.

## Assumptions

- **Supuesto (manifiesto multi-arquitectura)**: no se publica el manifiesto multi-arquitectura `ghcr.io/nadeon/hermes`. La action de Home Assistant que lo crea solo sabe combinar imágenes llamadas `<arch>-<nombre>`, y DECISIÓN 11 obliga a mantener `hermes-<arch>`. Como `image:` usa `{arch}`, el manifiesto no hace falta. Se deja para una especificación futura si se decide cambiar el nombre de imagen.
- **Supuesto (versión fijada)**: se fija la release más reciente de las actions de Home Assistant en el momento de escribir esto, la misma que usa su repositorio de ejemplo.
- **Supuesto (imagen base)**: se usa la etiqueta `3.13-alpine3.24` de la imagen base multi-arquitectura, que existe en el registro de Home Assistant; recibe los parches de seguridad de esa combinación sin cambiar de Python ni de Alpine.
- **Supuesto (compilación nativa)**: la arquitectura `aarch64` se compila en un runner ARM nativo de GitHub en vez de emular con QEMU, como hace el flujo de referencia de Home Assistant; el repositorio es público, donde esos runners están disponibles.
- **Supuesto (test del timeout)**: la comprobación automática del `timeout` vive en el workflow de validación y no en la suite de Python, porque esta especificación no toca `tests/` (otra especificación trabaja en paralelo sobre el código). Se recomienda añadir el test equivalente en una especificación futura.
- No se publica ninguna versión nueva como parte de este cambio: subir la versión sigue siendo decisión del mantenedor (principio XI).
- Docker no está disponible en el entorno de desarrollo; la compilación real solo se verá en GitHub.
