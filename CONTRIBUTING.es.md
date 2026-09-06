# Contribuir a Hermes

> Read this in: [English](CONTRIBUTING.md) | [Español](CONTRIBUTING.es.md)

Gracias por estar aquí. Hermes le da a un modelo de lenguaje control de
administrador sobre la casa de alguien, así que las contribuciones se leen con
eso en mente: el listón está menos en el estilo y más en *qué pasa cuando esto
está mal*.

Al abrir un pull request aceptas que tu contribución se publique bajo la licencia
del proyecto, [PolyForm Noncommercial 1.0.0](LICENSE). La participación se rige
por el [Código de Conducta](CODE_OF_CONDUCT.md) *(en inglés)*.

**Nunca reportes un fallo de seguridad por un issue ni por un pull request.** Usa
el [formulario privado de avisos](../../security/advisories/new); ver
[SECURITY.md](SECURITY.md) *(en inglés)*.

---

## Antes de escribir código

Dos cosas de este código que no se ven desde fuera:

- **Los comentarios, los `docstring` y los mensajes de error de arranque están en
  español.** Los identificadores, los nombres de las herramientas, los nombres de
  evento de log y las descripciones que ve el cliente MCP están en inglés.
  Mantén el código nuevo consistente con el fichero que estés editando en vez de
  convertirlo; a un pull request que traduzca comentarios existentes se le pedirá
  que quite esa parte, porque entierra el cambio de verdad bajo ruido.
- **El proyecto tiene una constitución escrita**:
  [docs/PRINCIPIOS.md](docs/PRINCIPIOS.md). Cuando aparece una duda de diseño en
  la revisión, es ese documento el que la resuelve. Con leer los dos primeros
  principios se entienden casi todos los comentarios de revisión.

Para cualquier cosa más grande que un arreglo puntual, abre antes un issue y
describe el enfoque. Sale más barato redirigir un plan que una rama terminada.

## Reportar una incidencia

Abre un [issue nuevo](../../issues/new). Lo que hace que un reporte sea
accionable:

- **La versión de Hermes** (Ajustes → Add-ons → Hermes, o el campo `version:` de
  `hermes/config.yaml`).
- **`network_mode`** y cómo expones Hermes (Tailscale Funnel, Cloudflare Tunnel,
  proxy inverso clásico).
- **La versión de Home Assistant** y si usas HAOS o Supervised.
- **Las líneas de log relevantes**, incluida la línea `hermes_started` del
  arranque. Pon `log_level: debug` si el nivel por defecto no enseña el fallo.
- **El `X-Request-ID`** de la respuesta que falla, si lo tienes. Ata la petición
  a sus líneas de log.

> [!CAUTION]
> Los logs redactan los secretos conocidos, pero la redacción no es una garantía
> para valores que Hermes no ha visto nunca. Lee lo que vas a pegar antes de
> pegarlo, sobre todo lo que rodee a `secrets.yaml`, a tokens, o a hostnames que
> prefieras no publicar.

Si el reporte va de una herramienta que hace algo que no debe, incluye el nombre
de la herramienta y los argumentos con los que la llamó Claude. Los dos salen en
el log.

## Montar el entorno

La suite se ejecuta sin Home Assistant delante y sin desplegar nada:

```bash
python -m venv .venv
.venv/bin/pip install -r hermes/requirements.txt
.venv/bin/pip install pytest pytest-asyncio aioresponses httpx
.venv/bin/pytest
```

En Windows, `.venv\Scripts\` en vez de `.venv/bin/`.

`pytest.ini` fija las rutas de importación, así que no hace falta exportar
`PYTHONPATH` y `pytest` y `python -m pytest` se comportan igual. Las dependencias
de test están fuera de `hermes/requirements.txt` a propósito: ese fichero es lo
que el add-on necesita para **arrancar**, y acaba dentro de la imagen.

**Estructura**: la raíz del repositorio es un repositorio de add-ons de Home
Assistant (`repository.yaml`); el add-on vive entero en `hermes/`, el paquete
Python en `hermes/src/hermes/`, y los tests en `tests/` en la raíz.

Para probar cambios contra un Home Assistant de verdad, copia el contenido de
`hermes/` a `/addons/hermes` en el host y **borra la línea `image:`** del
`config.yaml` que dejes ahí — si no, el Supervisor se descarga la imagen
publicada en vez de construir tus cambios. Después `ha apps rebuild local_hermes`
(si tocaste el `Dockerfile` o las dependencias), `ha apps restart local_hermes`
(solo Python), y `ha apps logs local_hermes -f`.

## Las tres convenciones que importan

Casi todos los comentarios de revisión de este proyecto se reducen a una de
estas.

### 1. Un arreglo de seguridad viene con un test que falla sin el arreglo

Un test de regresión que pasa esté o no la guarda no protege nada. Antes de abrir
el pull request, deshaz tu arreglo, ejecuta la suite, y comprueba que tu test se
pone rojo de verdad. Dilo en la descripción del PR —«con la guarda quitada caen N
tests»— porque esa frase es lo que si no tendría que reproducir a mano quien
revise.

Esto vale también para los tests: en este repositorio se han encontrado varios
que afirmaban el comportamiento viejo y flojo en vez del correcto.

### 2. El `docstring` de una herramienta es el contrato, no decoración

El `docstring` de una herramienta MCP es lo que lee Claude para decidir si la
llama. Un `docstring` que exagera lo que hace una herramienta, o que se calla que
es destructiva, es un bug aunque el código sea perfecto: hará que se llame a la
herramienta equivocada sobre la casa de alguien.

Si cambias lo que hace una herramienta, cambia su `docstring` y sus
`ToolAnnotations` (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
`openWorldHint`) en el mismo commit.

### 3. Un secreto no llega nunca a un log, a un mensaje de error ni a un retorno

Todo lo que Hermes pueda tocar —su propia contraseña, la de otro add-on, la de
una integración— se trata como si fuera a acabar en un log, en el contexto de un
modelo y en una transcripción, porque es exactamente lo que pasa. Los mensajes de
error describen la regla que falla, nunca el valor que la incumple.

## Pull requests

1. **Rama desde `main`** con un nombre que diga algo: `fix/…`, `feat/…`,
   `docs/…`, `test/…`.
2. **Un solo asunto por PR.** Un pull request que arregla un bug y de paso
   reformatea cuatro ficheros no se puede revisar bien, ni revertir limpiamente.
3. **Escribe el *por qué* en el mensaje de commit.** Lo que cambió se ve en el
   diff; por qué tenía que cambiar, no, y eso es lo que necesita quien lo lea
   dentro de seis meses. Incluye la medición si el cambio se apoya en una.
4. **Ejecuta la suite entera antes de empujar.** CI la corre en Python 3.12 y
   3.13, y los tests que solo van en Linux —los de escape por symlink, que
   dependen de `O_NOFOLLOW`— se saltan en Windows, así que CI cubre caminos que
   tu máquina puede no cubrir.
5. **CI tiene que quedar en verde.** Dos comprobaciones obligatorias: `Tests` y
   `SAST (Semgrep)` (en el repositorio público se les suma `CodeQL`, que ahí
   es gratis). Semgrep va en modo bloqueante; si marca una línea que has
   revisado y consideras falso positivo, suprímela con `# nosemgrep` en la línea
   exacta más una línea de justificación, no debilitando la regla.
6. **Actualiza la documentación en el mismo PR** cuando cambie el
   comportamiento: `README.md` y `README.es.md`, `hermes/DOCS.md` si afecta a la
   instalación o a la configuración, y una entrada en `hermes/CHANGELOG.md`.

Los dos README se mantienen sincronizados. Si solo hablas uno de los dos idiomas,
cambia ese y dilo en la descripción del PR: alguien del proyecto se encarga del
otro lado en vez de dejar el cambio esperando.

### Subir la versión

`hermes/config.yaml` lleva la versión del add-on, y el workflow que publica la
imagen se niega a ejecutarse cuando un tag `v*.*.*` no coincide con ella. Subir
la versión es una decisión de publicación: déjasela a quien mantiene el proyecto,
salvo que tu PR sea la publicación.

## Revisión

Espera preguntas sobre modos de fallo más que sobre estilo. No hay una puerta de
formateo automático; sigue el estilo del fichero que estés editando.

A un pull request se le puede pedir que encoja. Eso no es un rechazo del trabajo:
suele significar que dos cambios buenos se están peleando por una sola revisión,
y separados entran los dos antes.

## Dudas

Para cualquier cosa que no sea un issue ni un pull request, escribe a
`[CONTACT_EMAIL]`. Los reportes de seguridad **no** van ahí: van al
[formulario privado de avisos](../../security/advisories/new).
