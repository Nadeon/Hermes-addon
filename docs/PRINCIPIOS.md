<!-- Estos principios guían el desarrollo de Hermes. Se publican porque, en
     un add-on que expone una casa entera a un modelo de lenguaje, saber
     bajo qué reglas está escrito es parte de poder confiar en él. -->

# Principios de Hermes

Hermes expone **una casa entera** —estados, servicios, ficheros de configuración,
add-ons, backups, el host— a un modelo de lenguaje, a través de internet, con una
sola contraseña como frontera. Ese es el contexto que justifica todo lo que sigue.

## Principios

### I. La seguridad es el primer pilar, no una capa

Ante cualquier disyuntiva entre comodidad, rendimiento o elegancia y seguridad,
gana la seguridad. Una función que es más limpia pero filtra un secreto es peor
función. Un límite que estorba pero acota el daño se queda.

Corolario operativo: **ningún dato que salga hacia el cliente MCP se devuelve en
crudo**. Toda respuesta que provenga del Supervisor, de Home Assistant o del
sistema de ficheros pasa por una decisión explícita sobre qué contiene y qué se
puede exponer. Una herramienta que reenvía la respuesta del Supervisor tal cual acaba,
antes o después, devolviendo la contraseña de otro add-on. Este principio
existe para impedir exactamente eso.

### II. Los secretos son de larga duración; los tokens, no

Un token OAuth se revoca; una contraseña, una API key o una clave privada
sobreviven a la revocación y a la reinstalación. Por eso un secreto filtrado es
siempre más grave que un acceso indebido puntual, aunque quien lo lea ya
estuviera autenticado.

Todo secreto que Hermes pueda llegar a tocar —el suyo, el de otro add-on, el de
una integración— se trata como si fuera a acabar en un log, en el contexto de un
modelo y en una transcripción, porque es exactamente lo que pasa.

### III. Fail-closed

Ante la duda, denegar. Si el estado no se puede determinar, si la validación no
se puede completar, si el fichero de estado está corrupto: se bloquea la acción
y se explica por qué. Un falso negativo cuesta una llamada más; un falso
positivo puede costar la instalación.

Aplica también al arranque: si la configuración obligatoria falta o es
inválida, Hermes no arranca a medias.

### IV. Lo destructivo se confirma en dos pasos, y el token va atado

Toda acción que borre datos, interrumpa el servicio o toque secretos exige
`confirmation_token`: primera llamada devuelve `preview`, segunda ejecuta. El
token está atado a la tool **y a sus argumentos**, caduca y es de un solo uso.
Un token obtenido para una acción no puede ejecutar otra.

### V. El nombre y la descripción no mienten

El cliente elige la herramienta por su nombre antes de leer nada más. Un nombre
que oculta lo que hace es un fallo de seguridad, no de estilo: una herramienta
llamada `update` que además crea autoriza una acción que quien la aprobó no
esperaba. Lo mismo vale para las anotaciones MCP: si una tool se declara
`readOnlyHint`, no puede modificar nada.

### VI. Lo que no se puede probar, no está arreglado

Cada fallo de seguridad corregido deja un test que lo reproduce. Cada invariante
que importa se verifica automáticamente, no por convención. La suite corre
contra **las mismas versiones que se despliegan**: un test que valida
una versión que producción no ejecuta no prueba nada.

## Alcance y límites conocidos

- Hermes es un add-on de **Home Assistant OS**: usa la API del Supervisor.
- **No termina TLS**: siempre hay un proxy inverso delante (Tailscale Funnel,
  Cloudflare Tunnel, Nginx…). Escucha HTTP plano en `mcp_bind`, por defecto en
  loopback.
- **La IP de origen limita, nunca autoriza.** Según cómo se publique Hermes, la
  IP real del cliente llega o no llega: depende de si el proxy está en el
  loopback y reescribe `X-Forwarded-For`. Un límite "por IP" puede acabar siendo
  global sin que se note, así que ninguna decisión de acceso puede depender de
  ella. La defensa contra fuerza bruta es global a propósito: un techo por IP se
  evade rotando el origen.
- El modelo de amenaza asume **un solo usuario legítimo** y un cliente MCP
  potencialmente manipulable por el contenido que lee.

## Cómo se aplican

Esta constitución prevalece sobre cualquier otra práctica del proyecto. Una
propuesta que la contradiga se rechaza o cambia la constitución explícitamente,
nunca de forma implícita.

Los hallazgos de seguridad se clasifican por **impacto sobre estos principios**,
no por dificultad de explotación: un secreto expuesto a quien ya está
autenticado sigue siendo crítico por el Principio II.

