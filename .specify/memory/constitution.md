# Constitución de Hermes

Hermes es un add-on de Home Assistant que expone **una casa entera** —estados,
servicios, ficheros de configuración, add-ons, backups y el host— a un modelo de
lenguaje, a través de internet, con una sola contraseña como frontera. Esta
constitución recoge las reglas que gobiernan su desarrollo con spec-kit.

Los principios I a VI son los de [docs/PRINCIPIOS.md](../../docs/PRINCIPIOS.md) y
conservan su numeración, porque otros documentos los citan así («principio V»,
«principio VI»). Los principios VII a XI codifican las normas de trabajo del
proyecto. Si docs/PRINCIPIOS.md y este documento discrepan en los principios I–VI,
manda docs/PRINCIPIOS.md y este fichero se corrige.

## Core Principles

### I. La seguridad es el primer pilar, no una capa

- Ante cualquier disyuntiva entre comodidad, rendimiento o elegancia y seguridad,
  gana la seguridad. Un límite que estorba pero acota el daño se queda.
- Ningún dato que salga hacia el cliente MCP se devuelve en crudo: toda respuesta
  del Supervisor, de Home Assistant o del sistema de ficheros pasa por una
  decisión explícita sobre qué contiene y qué se puede exponer.

Razón: una herramienta que reenvía la respuesta del Supervisor tal cual acaba,
antes o después, devolviendo la contraseña de otro add-on.

### II. Los secretos son de larga duración; los tokens, no

- Todo secreto que Hermes pueda tocar —el suyo, el de otro add-on, el de una
  integración— se trata como si fuera a acabar en un log, en el contexto de un
  modelo y en una transcripción.
- Un secreto no llega nunca a un log, a un mensaje de error ni a un retorno. Los
  mensajes de error describen la regla que falla, nunca el valor que la incumple.
- Un secreto expuesto a quien ya está autenticado sigue siendo un fallo crítico.

Razón: un token se revoca; una contraseña, una API key o una clave privada
sobreviven a la revocación y a la reinstalación.

### III. Fail-closed

- Ante la duda, se deniega. Si el estado no se puede determinar, si la validación
  no se puede completar o si el fichero de estado está corrupto, la acción se
  bloquea y se explica por qué.
- Si la configuración obligatoria falta o es inválida, Hermes no arranca a medias.

Razón: un falso negativo cuesta una llamada más; un falso positivo puede costar
la instalación.

### IV. Lo destructivo se confirma en dos pasos, y el token va atado

- Toda acción que borre datos, interrumpa el servicio o toque secretos exige
  `confirmation_token`: la primera llamada devuelve un `preview`; la segunda,
  con los mismos argumentos y el token, ejecuta.
- El token está atado a la tool **y a sus argumentos**, caduca y es de un solo
  uso. Un token obtenido para una acción no puede ejecutar otra.
- El `preview` no puede mentir: describe exactamente lo que hará la ejecución
  confirmada, sin omitir efectos ni anunciar efectos que no ocurren.

Razón: el `preview` es la única revisión humana real antes de una acción grave.

### V. El nombre y la descripción no mienten

- El nombre, el `docstring` y las `ToolAnnotations` (`readOnlyHint`,
  `destructiveHint`, `idempotentHint`, `openWorldHint`) de una tool describen lo
  que hace, ni más ni menos. Una tool `readOnlyHint` no modifica nada; una tool
  `update` no crea.
- Si cambia lo que hace una tool, su `docstring` y sus anotaciones cambian en el
  mismo commit.

Razón: el cliente elige la herramienta por su nombre y su descripción; uno que
oculta lo que hace es un fallo de seguridad, no de estilo.

### VI. Lo que no se puede probar, no está arreglado

- Cada fallo corregido deja un test que lo reproduce, y cada invariante que
  importa se verifica automáticamente, no por convención.
- La suite corre contra las mismas versiones que se despliegan.

Razón: un test que valida una versión que producción no ejecuta no prueba nada.

### VII. Regresión con control negativo (NO NEGOCIABLE)

- Todo arreglo lleva un test de regresión.
- Antes de dar el arreglo por bueno se deshace, se ejecuta la suite y se
  comprueba que el test falla sin el arreglo. El resultado se deja escrito en el
  commit o en el PR («con la guarda quitada caen N tests»).
- La suite completa debe pasar antes de cada commit que se vaya a publicar.

Razón: un test que pasa esté o no la guarda no protege nada; este repositorio ya
ha tenido tests que afirmaban el comportamiento viejo en lugar del correcto.

### VIII. Privacidad: el repositorio es público (NO NEGOCIABLE)

- Ningún fichero, mensaje de commit, issue, PR, comentario ni release contiene
  datos personales del mantenedor ni de ninguna instalación: contraseñas,
  tokens, claves, `auth_password`, hostnames reales, IPs (públicas, de tailnet o
  de LAN), slugs o hashes de instalación, nombres de red, de dispositivos o de
  entidades, rutas de máquinas personales, correos ni extractos de logs sin
  anonimizar.
- Se usan siempre marcadores genéricos: `homeassistant.tailXXXX.ts.net`,
  `<slug>`, `192.0.2.x`.
- Ningún artefacto del repositorio contiene identificadores de modelos de IA.
- Antes de cada push o publicación se revisa el diff completo buscando estos
  datos. Ante la duda, no se publica y se pregunta.

Razón: Hermes lo usa más gente; lo que se publica no se puede despublicar.

### IX. Cambios mínimos, sin ampliar el alcance

- Lo que no está en la especificación no se hace. Un hallazgo fuera de alcance
  se anota para otra especificación, no se arregla de paso.
- Un solo asunto por cambio; no se reformatea ni se traduce código existente
  que no forme parte del arreglo.
- Se sigue el estilo del fichero que se edita.

Razón: un cambio que mezcla asuntos no se puede revisar bien ni revertir
limpiamente.

### X. Comentarios en español que explican el porqué

- Los comentarios, los `docstring` internos y los mensajes de error de arranque
  están en español; los identificadores, los nombres de tools, los eventos de log
  y las descripciones que ve el cliente MCP, en inglés.
- Un comentario explica **por qué** el código es así (la amenaza que evita, el
  fallo que corrige, la restricción externa), no qué hace línea a línea.
- Los mensajes de commit explican también el porqué.

Razón: lo que cambió se ve en el diff; por qué tenía que cambiar, no.

### XI. Versionado y publicación coherentes

- La versión vive en `hermes/config.yaml` (`version:`) y en
  `hermes/src/hermes/__init__.py` (`__version__`), y ambas coinciden.
  `HA_CORE_LAST_TESTED_IN_HERMES` (`hermes/src/hermes/config.py`) es igual a la
  versión.
- Cada versión tiene entrada en `hermes/CHANGELOG.md` con el formato
  `## [x.y.z] — AAAA-MM-DD`.
- `README.md` y `README.es.md` se mantienen sincronizados; `hermes/DOCS.md` se
  actualiza si cambia la instalación o la configuración.
- Se fusiona a `main` con squash y se etiqueta con el workflow `etiquetar.yml`.
  Nunca se fusiona a `main` una versión nueva sin publicar su imagen a la vez,
  porque la tienda de Home Assistant lee la versión de `main`.

Razón: una versión anunciada en `main` sin imagen publicada rompe la
instalación y la actualización de quien use la tienda.

## Alcance y límites conocidos

- Hermes es un add-on de Home Assistant OS y usa la API del Supervisor. Código en
  Python 3.13; el add-on vive en `hermes/`, el paquete en `hermes/src/hermes/` y
  los tests en `tests/`.
- No termina TLS: siempre hay un proxy inverso delante (Tailscale Funnel,
  Cloudflare Tunnel, Nginx…) y escucha HTTP plano en `mcp_bind`, por defecto en
  loopback.
- La IP de origen limita, nunca autoriza: ninguna decisión de acceso depende de
  ella. La defensa contra fuerza bruta combina un freno por IP y un techo global.
- El modelo de amenaza asume un solo usuario legítimo y un cliente MCP
  potencialmente manipulable por el contenido que lee.
- Los fallos de seguridad se reportan por el canal privado descrito en
  `SECURITY.md`, nunca en issues ni PRs públicos.

## Flujo de trabajo y puertas de calidad

1. Cada arreglo parte de una especificación en `specs/NNN-nombre/` (spec, plan y
   tareas). El trabajo se hace en la rama que indique el mantenedor; spec-kit no
   crea ramas por sí mismo.
2. El plan incluye una comprobación explícita contra esta constitución; cualquier
   desviación se justifica por escrito o se rechaza.
3. Antes de cada commit: la suite completa pasa, el test nuevo tiene control
   negativo documentado (principio VII) y el diff se ha revisado buscando datos
   personales (principio VIII).
4. CI debe quedar en verde (`Tests`, `SAST (Semgrep)` y, en el repositorio
   público, `CodeQL`). Un falso positivo de Semgrep se suprime con
   `# nosemgrep` en la línea exacta y una justificación, nunca debilitando la
   regla.
5. Si el cambio altera el comportamiento, la documentación (README.md,
   README.es.md, DOCS.md, CHANGELOG) se actualiza en el mismo cambio. Subir la
   versión es una decisión de publicación del mantenedor (principio XI).

## Governance

- Esta constitución prevalece sobre cualquier otra práctica del proyecto. Una
  propuesta que la contradiga se rechaza o modifica la constitución de forma
  explícita, nunca implícita.
- Los principios I–VI se enmiendan en `docs/PRINCIPIOS.md` y se reflejan aquí en
  el mismo cambio, conservando su numeración.
- Versionado semántico de este documento: MAJOR si se elimina o redefine un
  principio de forma incompatible; MINOR si se añade un principio o sección o se
  amplía materialmente; PATCH para aclaraciones y redacción.
- Toda especificación, plan, revisión y PR verifica el cumplimiento. Los
  hallazgos se clasifican por su impacto sobre estos principios, no por la
  dificultad de explotación.
- La guía operativa para contribuir está en `CONTRIBUTING.es.md` y
  `CONTRIBUTING.md`; la política de seguridad, en `SECURITY.md`.

**Version**: 1.0.0 | **Ratified**: 2026-11-14 | **Last Amended**: 2026-11-14
