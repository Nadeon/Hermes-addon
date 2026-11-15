# Especificación: Hermes 1.2.0 — escritura en el Marketplace (sub-feature 026)

**Directorio de la spec**: `specs/026-marketplace-escritura`

**Creada**: 2026-11-15

**Estado**: Hecha (tramos 1 y 2; alcance reducido por la DESVIACIÓN DV-1,
ver «Requisitos»; desinstalar en `marketplace_manage` por la DECISIÓN D-2)

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T025 de su `tasks.md` y cubre **CAP-075** (escritura en
el Marketplace), es decir, **FR-091** de la 008. Depende de la 030 (tienda de
apps: patrón de textos de terceros, credenciales de URL tapadas y vista previa
de código de terceros), ya integrada en `feat/cobertura-total`.

**Entrada**: `specs/008-cobertura-total/` (spec FR-091, plan con la matriz de
trazabilidad, research CAP-075 e `inventario/core-ws.tsv`), la 004 (Marketplace
de solo lectura: FR-018, FR-019, S-08), la 011 (`command_table.py`,
`tool_families.py`), la 014 (matriz de pruebas), la 028 (inventario de
escrituras del banco), la 030 (`tools/_store.py`, `tools/store_repositories.py`)
y el código de Hermes: `tools/marketplace.py` (`_ws_read`, `_list_catalog`,
`_summary`, `_third_party`, `_THIRD_PARTY_WARNING`, `_REPOSITORY_ID_RE`,
`_HOW_TO_UPDATE`), `tools/hacs.py`, `tools/_annotations.py`,
`tools/guide.py`, `security.py` (`create_confirmation_token` con `estado`,
`resolve_confirmation_token`, `complete_confirmation_token`), `tools/backups.py`
(`POST /backups/new/partial`) y `ha.py`. Contrastado con el código de HA Core
2026.11.1 (`homeassistant/components/marketplace/`: `__init__.py`,
`websocket/__init__.py`, `websocket/decorators.py`, `websocket/repository.py`,
`websocket/repositories.py`, `websocket/critical.py`, `critical.py`,
`base.py`, `repositories/base.py`, `repositories/integration.py`,
`repositories/plugin.py`, `utils/regex.py`, `utils/validate.py`,
`utils/storage.py`), con `homeassistant/bootstrap.py`
(`DEFAULT_INTEGRATIONS`) y con el proxy del Supervisor 2026.11.0
(`supervisor/api/proxy.py`).

## Clarificaciones

### Sesión 2026-11-15

Decisiones vinculantes del programa (ya están en la 008 y en la 011):

- CAP-075 va por **tools dedicadas** (vía D de la matriz de la 008) y es de
  riesgo **alto**: instalar o actualizar descarga código de terceros y lo
  ejecuta dentro de Home Assistant.
- Las tools nuevas van en **familias nuevas** de la 1.2.0 (FR-010 de la 008),
  distintas de la familia `marketplace` de lectura de la 1.1.2; con las
  familias de la 1.2.0 desactivadas, la lista de tools vuelve a ser la de la
  1.1.2. Todas activas por defecto (decisión «todas activas» de la 008; su
  riesgo es la duda D-03 de la 008). La opción `marketplace_write_enabled` que
  proponía research CAP-075 la sustituyen las familias (`tool_families_disabled`).
- **Nunca** conectar GitHub (`marketplace/github/connect`) ni aceptar el aviso
  de riesgos (`marketplace/warning/accept`): clase D, siguen `deny` (FR-091).
- Las anotaciones de las tools del Marketplace van **por nombre exacto**,
  nunca por el prefijo `ha_marketplace_` (FR-091; FR-018 de la 004).
- `repository/info`, `repositories/clear_new` y `subscribe` son clase B y
  siguen `deny`.

Decisiones tomadas al especificar (no había a quién preguntar; se justifican
en [research.md](research.md)):

- P: ¿El Marketplace de 2026.11 es de Core o externo? → R: **de Core**:
  `homeassistant/components/marketplace/`, en `DEFAULT_INTEGRATIONS` de
  `bootstrap.py` (se carga siempre, salvo en modo de recuperación). Los 9
  comandos de escritura y los 4 de lectura que usan las vistas previas están
  en `fuentes/core` y en el inventario; ninguno lleva `hassio/` ni
  `supervisor/` (research R-1).
- P: ¿Y con HACS 2.x (HA ≤ 2026.10)? → R: **no se escribe**. HACS es externo:
  sus comandos de escritura no están en las fuentes y no se pueden comprobar.
  Las tools nuevas solo hablan con `marketplace/*`; si HA no lo conoce,
  responden `marketplace_write_unsupported` sin probar `hacs/*`. Las tools de
  lectura siguen cayendo a HACS como hoy (research R-1).
- P: ¿Puede Hermes instalar de verdad? → R: **HALLAZGO que limita el
  alcance**. HA 2026.11.1 exige que el **usuario de HA con el que llega el
  comando** haya aceptado el aviso de riesgos del Marketplace para `install`,
  `version`, `beta`, `repositories/detect` y `repositories/add`
  (`marketplace_command(requires_accepted_warning=True)`), y añadir además
  exige GitHub conectado. Hermes llega por el proxy del Supervisor, así que el
  usuario es el del **Supervisor** (usuario de sistema): nadie puede aceptar
  el aviso por él en la interfaz y Hermes no lo acepta nunca. Decisión: las
  tools se construyen igual (FR-091) y su **vista previa comprueba antes la
  condición** con `marketplace/info` (`warning_accepted`, `github_connected`,
  que son del mismo usuario que ejecutará): si no se cumple, no hay token y
  la respuesta lo explica sin rodeos. Las descripciones lo dicen. Desinstalar,
  quitar un repositorio, refrescar, ignorar y reconocer avisos críticos **no**
  lo exigen y funcionan. Duda para el final D-1 (research R-2). **Resuelta
  por el supervisor con la DESVIACIÓN DV-1** (ver «Requisitos»): las tools
  que exigen el aviso no se publican.
- P: ¿Cuántas tools y en qué familias? → R: **nueve** en **dos familias**,
  una por tramo: `marketplace_install` (instalar, desinstalar, fijar versión,
  mostrar betas: tocan el código instalado) y `marketplace_manage` (añadir y
  quitar repositorios personalizados, refrescar, ignorar un retirado y
  reconocer un aviso crítico: tocan el catálogo y los avisos). Así se puede
  apagar lo que instala código sin perder el mantenimiento (research R-3).
  **Cambiado por la DECISIÓN D-2** (ver «Requisitos»): tras la DV-1 solo
  queda desinstalar, que va en `marketplace_manage`; no hay
  `marketplace_install`.
- P: ¿`repository/beta` tiene tool? → R: **sí**, `ha_marketplace_set_beta`.
  CAP-075 lo incluye y su vía es D: la genérica no lo puede abrir sin pasar
  por `confirm` provisional, y en la tabla ninguna entrada de una CAP de vía D
  queda «pendiente». `repositories/detect` no tiene tool propia: lo usa la
  vista previa de `ha_marketplace_add_repository` y pasa a `dedicated`
  apuntando a ella, con el matiz (research R-4).
- P: ¿Todas confirman? → R: **sí, las nueve**, en dos pasos (criterio del
  supervisor: todo lo que escribe). Ignorar y reconocer no tienen comando que
  los deshaga en 2026.11.1; refrescar escribe en el storage y sale a GitHub.
  Todas, con `destructiveHint` (invariante de la 1.1.2: lo que se hace
  confirmar no se anuncia inofensivo) (research R-9).
- P: ¿Backup previo? → R: **en instalar y desinstalar**, que son las que
  cambian ficheros de `/config` (`custom_components/`, `www/community/`,
  `themes/`): argumento `backup=True` por defecto, atado al token; al
  confirmar, Hermes pide al Supervisor un backup **parcial** de la
  configuración de Home Assistant **sin la base de datos** y solo si sale bien
  envía el comando; si falla, no envía nada. Las otras siete no cambian
  ficheros (solo el storage del Marketplace) y no hacen backup; la vista
  previa lo dice (research R-6).
- P: ¿Qué dice la vista previa de instalar? → R: repositorio (`full_name`,
  categoría, `custom`), versión instalada y versión que se instalará, si está
  en las versiones publicadas y si es prerelease (cuando se pide una
  concreta), que es **código de terceros sin revisar** por Home Assistant ni
  por Hermes, si **sustituye a una integración de Home Assistant**
  (`manifest/get` → `is_built_in`; exige `replace_built_in=true`), si hará
  falta **reiniciar Core** (por categoría, con lo que decide HA), el backup y
  los textos de terceros marcados (research R-7, R-8).
- P: ¿Qué ata el token? → R: los argumentos (repositorio, versión,
  `replace_built_in`, `backup`, `show_beta`, URL completa y categoría) y, con
  `estado` de la 018, lo leído en la vista previa que decide el efecto:
  `full_name`, categoría, versión instalada y versión destino. Si cambia entre
  la vista previa y la confirmación, el token no vale (research R-9).
- P: ¿Qué se envía al añadir un repositorio con credenciales en la URL? → R:
  se valida que sea `owner/repo` o una URL `https://github.com/owner/repo`
  (con `.git` o `/` final opcionales); la parte de usuario se tapa entera en
  la vista previa, las respuestas, los errores y el log, como en la 030; el
  token se ata a la **URL completa**; y a HA se le envía solo `owner/repo`
  (lo único que HA usa: su `extract_repository_from_url` descarta el resto),
  así que **las credenciales nunca salen de Hermes** (research R-5).
- P: ¿Ignorar cualquier repositorio? → R: **no**: solo uno que está en la
  lista de retirados del catálogo y no es crítico; ignorar es lo que hace que
  HA deje de avisar de que lo retiraron y no lo quite de la lista. Un crítico
  se reconoce con `ha_marketplace_acknowledge_critical` (research R-10).
- P: ¿Quitar cualquier repositorio? → R: solo uno **personalizado** y **no
  instalado** (HA rechaza el instalado; uno del catálogo por defecto
  volvería con la siguiente descarga del catálogo) (research R-10).
- P: ¿Banco? → R: el banco **no tiene internet**: el Marketplace se carga
  (integración por defecto) pero no descarga el catálogo, así que no hay nada
  que instalar, refrescar, ignorar ni quitar. `ha_marketplace_acknowledge_critical`
  sí se ejecuta en el banco, con un aviso crítico sembrado en el storage del
  banco. Las otras ocho van a `NO_EJECUTABLES_026` con el motivo concreto y
  a la matriz de la 014 como «instalación real / pendiente» con el motivo. Además, un test
  de contrato en el banco envía la carga exacta de cada comando de escritura
  con un repositorio inexistente y comprueba que HA la acepta (responde un
  error del manejador, nunca `invalid_format` ni `unknown_command`)
  (research R-11).

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es el administrador de Home Assistant que gestiona las
integraciones, tarjetas, temas y plantillas de la comunidad (el Marketplace,
antes HACS) desde un cliente MCP.

### Historia 1 — Mantener el catálogo y atender los avisos (Prioridad: P1)

Quien tiene repositorios de la comunidad instalados recibe avisos: uno se ha
retirado del catálogo, otro es crítico (malicioso o peligroso), uno
personalizado ya no se usa. Quiere atenderlos sin abrir la interfaz: reconocer
el aviso crítico, ignorar la retirada de uno que sigue queriendo, refrescar la
información de un repositorio, quitar un personalizado y añadir otro.

**Prueba independiente**: con un HA simulado con la forma de 2026.11.1, las
cinco tools de `marketplace_manage` dan una vista previa honesta, rechazan sin
token lo que HA rechazaría y, con el token, envían exactamente el comando y la
carga esperados.

**Escenarios de aceptación**:

1. **Dado** un aviso crítico sin reconocer, **cuando** el agente llama a
   `ha_marketplace_acknowledge_critical(repository)`, **entonces** recibe una
   vista previa con el repositorio, el motivo y el enlace (marcados como texto
   de terceros), que no se puede deshacer, y un token; con el token, Hermes
   envía `marketplace/critical/acknowledge` y devuelve la entrada reconocida.
2. **Dado** un repositorio que no está en la lista de críticos, o ya
   reconocido, **cuando** pide la vista previa, **entonces** recibe
   `not_critical` o `already_acknowledged` sin token.
3. **Dado** un repositorio instalado y retirado del catálogo (no crítico),
   **cuando** llama a `ha_marketplace_ignore_repository(repository_id)`,
   **entonces** la vista previa dice el motivo de la retirada (texto de
   terceros), que HA dejará de avisar y no lo quitará, y que no hay comando
   para deshacerlo; con el token se envía `marketplace/repository/ignore`.
   Si no está retirado, `repository_not_removed` sin token; si es crítico,
   `critical_repository` sin token con la pista de reconocerlo.
4. **Dado** un repositorio personalizado no instalado, **cuando** llama a
   `ha_marketplace_remove_repository`, **entonces** vista previa y, con token,
   `marketplace/repositories/remove`; si está instalado, `repository_installed`
   sin token con la pista de desinstalarlo; si no es personalizado,
   `not_custom_repository` sin token.
5. **Dado** un repositorio conocido, **cuando** llama a
   `ha_marketplace_refresh_repository`, **entonces** la vista previa dice que
   HA lo consultará en GitHub (gasta su límite) y no instala nada; con el
   token se envía `marketplace/repository/refresh`; si GitHub limita,
   `github_rate_limited` con la explicación.
6. **Dado** `https://usuario:centinela@github.com/ejemplo/tarjeta` y la
   categoría `plugin`, **cuando** llama a `ha_marketplace_add_repository`,
   **entonces**, si el aviso de riesgos está aceptado y GitHub conectado para
   el usuario de Hermes, la vista previa enseña la URL con la parte de usuario
   tapada, `full_name: "ejemplo/tarjeta"`, las categorías que detecta HA y el
   aviso de código de terceros, y el centinela no aparece en ninguna parte;
   con el token se envía `marketplace/repositories/add` con
   `repository: "ejemplo/tarjeta"`.
7. **Dado** que el usuario de HA con el que se conecta Hermes no ha aceptado
   el aviso de riesgos (lo normal: es el usuario del Supervisor), **cuando**
   pide la vista previa de añadir, **entonces** recibe
   `marketplace_warning_not_accepted` sin token, con la explicación de por qué
   Hermes no puede hacerlo y de que se hace desde la interfaz del Marketplace.

---

### Historia 2 — Instalar, actualizar o quitar código de terceros (Prioridad: P1)

Quien quiere instalar una integración o una tarjeta de la comunidad, pasar a
otra versión o desinstalarla necesita saber antes, sin ambigüedad, qué
repositorio y qué versión va a entrar, que es código de terceros sin revisar,
si sustituye a una integración de Home Assistant, si habrá que reiniciar Core
y que hay un backup al que volver.

**Prueba independiente**: con HA y Supervisor simulados, las cuatro tools de
`marketplace_install` comprueban la condición del aviso de riesgos, dan una
vista previa honesta, hacen el backup antes de enviar el comando y no emiten
token para nada que HA rechazaría.

**Escenarios de aceptación**:

1. **Dado** el aviso aceptado para el usuario de Hermes y un repositorio de
   categoría `integration` no instalado, **cuando** el agente llama a
   `ha_marketplace_install(repository_id)`, **entonces** recibe una vista
   previa con `full_name`, categoría, `custom`, versión destino, `third_party:
   true` con el aviso, `replaces_built_in`, `restart` (Core tendrá que
   reiniciarse para cargarla; Hermes no reinicia) y `backup` (parcial, sin la
   base de datos), más el token.
2. **Dado** ese token, **cuando** confirma, **entonces** Hermes pide el backup
   parcial al Supervisor, espera a que termine y solo entonces envía
   `marketplace/repository/install` con `repository` (y `version` y
   `confirm_replace_built_in` si toca); responde con el estado releído
   (`pending-restart` si HA lo pide) y el `slug` del backup.
3. **Dado** que el backup falla, **cuando** confirma, **entonces** no se envía
   el comando de instalar y el error lo dice; el token queda consumido como
   fallido.
4. **Dado** una integración cuyo `domain` es de una integración de Home
   Assistant, **cuando** pide la vista previa sin `replace_built_in=true`,
   **entonces** recibe `replaces_built_in` sin token, con la pista.
5. **Dado** una versión concreta que no está entre las publicadas o que es
   prerelease, **cuando** pide la vista previa, **entonces** se le dice en
   `version_check` (aviso, no rechazo: puede ser una rama o un commit); si las
   versiones no se pueden consultar, `version_check.checked: false`.
6. **Dado** que entre la vista previa y la confirmación cambia la versión
   instalada o la disponible, **cuando** confirma, **entonces** el token no
   vale y no se envía nada.
7. **Dado** una integración instalada con entradas de configuración, **cuando**
   pide desinstalarla, **entonces** recibe `repository_in_use` sin token, con
   la pista de borrar antes sus entradas; sin entradas, vista previa con el
   backup y el reinicio, y con el token, backup y
   `marketplace/repository/uninstall`.
8. **Dado** `ha_marketplace_set_version` o `ha_marketplace_set_beta`,
   **cuando** pide la vista previa, **entonces** se le dice que cambia la
   versión que HA sigue y ofrece como actualización (o si muestra betas), que
   no instala nada y que lo instala después `ha_marketplace_install` o la
   entidad `update`.
9. **Dado** el aviso de riesgos sin aceptar para el usuario de Hermes,
   **cuando** pide la vista previa de instalar, fijar versión o mostrar betas,
   **entonces** recibe `marketplace_warning_not_accepted` sin token y sin
   ninguna otra llamada de escritura; desinstalar funciona igual.

---

### Historia 3 — Nada de lo que funciona hoy cambia y la lectura dice la verdad (Prioridad: P1)

Las siete `ha_marketplace_*` de lectura y los alias `ha_hacs_*` siguen con el
mismo nombre, esquema, anotaciones y comportamiento. Lo que cambia es el texto
que decía que Hermes no instala nada del Marketplace, que deja de ser verdad.

**Prueba independiente**: instantánea de esquemas de la 1.1.2, anotaciones,
la guarda de la lista cerrada de comandos de `tools/marketplace.py` y las
descripciones y la guía.

**Escenarios de aceptación**:

1. **Dado** la configuración por defecto, **cuando** se listan las tools,
   **entonces** todas las de antes (314 en `f108af0`) siguen igual y hay
   nueve más; con
   `tool_families_disabled: [marketplace_manage]` (D-2: no hay
   `marketplace_install`), la lista es la de antes.
2. **Dado** `tools/marketplace.py`, **cuando** se buscan los comandos que
   envía, **entonces** siguen siendo solo los de lectura (`_ALLOWED_SUFFIXES`):
   la escritura vive en otros módulos.
3. **Dado** la descripción de `ha_marketplace_list_updates`, su
   `how_to_update`, la de `ha_hacs_list_updates` y el tema `marketplace` de la
   guía, **cuando** se leen, **entonces** ya no dicen que Hermes no instala
   nada: nombran `ha_marketplace_install` y la entidad `update`, y que las dos
   exigen el aviso aceptado por el usuario de HA de Hermes, que Hermes nunca
   acepta.

---

### Casos límite

- `marketplace/*` responde `not_loaded` (Marketplace sin configurar o caído):
  `marketplace_not_loaded`, sin token, como la lectura.
- HA no conoce `marketplace/*` (HA ≤ 2026.10 con HACS, o modo de
  recuperación): `marketplace_write_unsupported`, sin probar `hacs/*`.
- `repository_id` con caracteres fuera de `[A-Za-z0-9_-]{1,64}`, `version` que
  HA no admite (vacía, con `?`, `#`, `%`, `\`, espacios, o que empieza por
  `.`), `category` fuera de las cuatro del Marketplace, `show_beta` o `backup`
  que no son booleanos: `invalid_argument` sin ninguna llamada a HA.
- Repositorio inexistente en la lista: `repository_not_found` sin token.
- Instalar un repositorio que HA marca `can_install: false` (HA demasiado
  antiguo): `cannot_install` sin token, con la versión de HA que pide.
- Instalar mientras HA está instalando ese repositorio (`repository_busy`):
  el error de HA se traduce, el token queda fallido.
- Desinstalar uno no instalado: `repository_not_installed` sin token.
- Añadir uno que ya está (también renombrado): `repository_already_added` sin
  token. Una URL que no es de GitHub, con esquema distinto de `https`, con
  puerto no numérico (`https://u:p/ss@github.com/…`), de más de 2048
  caracteres o con una ruta que no es exactamente `owner/repo`:
  `invalid_argument` sin copiar el valor y sin llamadas.
- Un repositorio de Core (`home-assistant/core`) o de apps
  (`hassio-addons/…`): HA lo rechaza (`core_repository`, `app_repository`) en
  la detección de la vista previa; se devuelve sin token.
- GitHub limita (`github_rate_limited`) en la vista previa o en la
  confirmación: se explica que basta con esperar; en la confirmación el token
  queda fallido.
- El backup tarda más que la espera larga: la confirmación responde con el
  `job_id` y no envía el comando (el backup no consta como terminado).
- Un error de HA o del Supervisor que repite la URL con credenciales: se tapa
  antes de responder, de guardarlo en el token y de llevarlo al log.
- Textos de terceros (`name`, `description`, `reason`, `link`,
  `removal_type`, nombres de versiones) con instrucciones: se devuelven
  recortados y marcados en `_third_party_text`.

## Requisitos *(obligatorio)*

> **DESVIACIÓN DV-1 (HALLAZGO de la spec, decisión del supervisor del
> programa al validarla; desviación PARCIAL de FR-091 de la 008)**: HA Core
> 2026.11.1 exige que el usuario de HA que manda el comando haya aceptado el
> aviso de riesgos del Marketplace (`marketplace_command(
> requires_accepted_warning=True)`, `warning_accepted(connection.user.id)` en
> `base.py`) para `repository/install`, `repository/version`,
> `repository/beta`, `repositories/detect` y `repositories/add`. El usuario de
> Hermes es el del Supervisor: no puede aceptarlo en la interfaz, y Hermes
> NUNCA lo acepta en nombre de una persona (clase D). Igual que en la 031
> (DV-1), no se publican tools que no pueden funcionar: **no existen**
> `ha_marketplace_install`, `ha_marketplace_set_version`,
> `ha_marketplace_set_beta` ni `ha_marketplace_add_repository`, y esos cinco
> comandos quedan en `deny` con el motivo «HA exige que el usuario que lo
> pide haya aceptado el aviso de riesgos del Marketplace; el usuario de
> Hermes no puede aceptarlo (duda D-29)», también en una generación de la
> tabla desde cero (`_Deny` en una fila A de `_DEDICADAS_INICIALES`). La
> duda D-1 queda resuelta así. Comprobado en `fuentes/core` que
> `critical/acknowledge` (sin decorador), `repository/ignore`,
> `repositories/remove`, `repository/refresh` y `repository/uninstall`
> (`marketplace_command()` sin argumentos) **no** exigen el aviso.
>
> Consecuencias en esta spec: donde dice «nueve» tools son **cinco** (cuatro
> en el tramo 1 y `ha_marketplace_uninstall` en el tramo 2); FR-003, FR-012,
> FR-013, FR-015 y FR-016, el escenario 6 y 7 de la historia 1 y los
> escenarios 1-6, 8 y 9 de la historia 2 **no aplican**; en FR-017 el backup
> previo es solo de desinstalar; en FR-019, las cuatro entradas del tramo 1
> pasan a `dedicated`, las cinco anteriores a `deny` con el motivo de arriba
> y `repository/uninstall` a `dedicated` en el tramo 2; FR-018 no aplica
> (los textos de lectura que dicen que Hermes no instala nada siguen siendo
> verdad); en FR-022 el tema de la familia del tramo 1 explica lo que Hermes
> no puede hacer y por qué; en FR-023 el contrato del banco cubre los
> comandos de las tools que existen; SC-001, SC-003, SC-005 y SC-007 se leen
> con esas cinco tools. Decisiones del supervisor al validar: todas
> confirman en dos pasos y son destructivas por nombre exacto; el token se
> ata al repositorio, a la categoría y a lo leído (`estado`); la vista previa
> dice si el repositorio es de terceros y no está revisado.
>
> **DECISIÓN D-2 (supervisor, tramo 2)**: `ha_marketplace_uninstall` va en
> la familia `marketplace_manage` (módulo `tools/marketplace_manage.py`), no
> en una familia de una sola tool: **no existe** `marketplace_install`. En
> FR-020 hay una sola familia nueva y en FR-022 un solo tema
> (`marketplace_manage`, que explica también desinstalar, su backup y el
> reinicio). Decisiones del supervisor para desinstalar: confirma en dos
> pasos y es destructiva; el token ata el repositorio, la categoría y lo
> leído (y `backup`); rechaza sin token `repository_not_installed` y
> `repository_in_use`; antes de desinstalar hace un backup parcial sin la
> base de datos y, si falla, no se envía nada a HA y la respuesta lo dice;
> ese backup no se cifra (los safety backups cifrados de la 031 no están en
> esta rama, y no se promete cifrado); la vista previa dice qué se quita, si
> habrá que reiniciar Core y qué puede quedar roto (HA no dice qué
> entidades o tarjetas usan un repositorio: se dice lo que implica su
> categoría, y que HA no lo lista).

Cada FR traza a la 008: **FR-091 / CAP-075** salvo donde se dice otra cosa.

### Requisitos funcionales

#### Común a las nueve tools

- **FR-001**: Las nueve tools solo envían comandos `marketplace/*` (más
  `manifest/get` y `config_entries/get` para sus vistas previas, y
  `POST /backups/new/partial` del Supervisor para el
  backup; ningún otro). Si HA responde `unknown_command`, devuelven
  `marketplace_write_unsupported` sin probar `hacs/*`; si responde
  `not_loaded`, `marketplace_not_loaded`. Ningún comando lleva el prefijo
  `hassio/` ni `supervisor/` (FR-091; regla del proxy del Supervisor).
- **FR-002**: Las nueve confirman en dos pasos con
  `create_confirmation_token`. La vista previa nunca envía un comando que
  escriba: solo lee (`info`, `repositories/list`, `repositories/removed`,
  `critical/list`, `repository/releases`, `repositories/detect`,
  `manifest/get`, `config_entries/get`). Todo lo que HA rechazaría y Hermes
  puede saber antes se rechaza **sin token** (FR-091; FR-018 de la 008).
- **FR-003**: Las tools que necesitan el aviso de riesgos aceptado
  (`ha_marketplace_install`, `ha_marketplace_set_version`,
  `ha_marketplace_set_beta`, `ha_marketplace_add_repository`) leen
  `marketplace/info` en la vista previa y, si `warning_accepted` no es `true`,
  responden `marketplace_warning_not_accepted` sin token, con un `detail` que
  dice que el aviso es por usuario de HA, que Hermes se conecta con el usuario
  del Supervisor, que Hermes nunca lo acepta y que la operación se hace desde
  la interfaz del Marketplace. `ha_marketplace_add_repository` responde además
  `github_not_connected` si `github_connected` no es `true`, con la pista de
  conectarlo desde la interfaz (Hermes nunca lo conecta). Si HA devuelve
  `warning_not_accepted` o `github_not_connected` al confirmar, se traduce
  igual y el token queda fallido (FR-091; research R-2).
- **FR-004**: El token ata los argumentos tal como se envían (normalizados) y,
  con `estado`, lo leído en la vista previa que decide el efecto (data-model
  «Estado atado»). Al confirmar se relee y, si no coincide o no se puede leer,
  el token no vale y no se envía nada (fail-closed) (FR-091; principio IV).
- **FR-005**: Los textos de terceros (`name`, `description`, `reason`,
  `link`, `removal_type`, `name` de las versiones) salen recortados (300
  caracteres) y marcados con `_third_party_text`, con el aviso de
  `tools/marketplace.py`. Cada vista previa de una tool que instala o añade
  código lleva además `third_party: true` y un aviso propio: el código no lo
  revisan Home Assistant ni Hermes y se ejecuta dentro de Home Assistant
  (FR-091).
- **FR-006**: Los errores de HA y del Supervisor se traducen a códigos
  estables (data-model «Errores») y pasan por `redact_secrets` y por el tapado
  de credenciales de URL de `tools/_store.py` antes de responder, de
  guardarse en el token y de llegar al log (FR-019 de la 008).
- **FR-007**: Cada llamada escribe un evento `marketplace_write` con `tool`,
  `outcome` (`preview`, `ok`, `rejected:<código>`, `error`) y `category`;
  nunca nombres de repositorio, ids, URLs, versiones ni textos de terceros (el
  log se pega en issues públicos; principio VIII).

#### Catálogo y avisos (familia `marketplace_manage`, tramo 1)

- **FR-008**: `ha_marketplace_acknowledge_critical(repository,
  confirmation_token=None)`: `repository` es el `full_name` de una entrada de
  `marketplace/critical/list`. Vista previa con la entrada (`repository`,
  `reason`, `link`, `acknowledged`) y el efecto (HA lo marca como visto y
  quita el aviso de Repairs; no hay comando para deshacerlo; no instala ni
  desinstala nada). Rechazos sin token: `not_critical`,
  `already_acknowledged`. Con token, `marketplace/critical/acknowledge` y la
  entrada tal como queda.
- **FR-009**: `ha_marketplace_ignore_repository(repository_id,
  confirmation_token=None)`: vista previa con el repositorio, su entrada de
  retirados (`reason`, `removal_type`, `link`) y el efecto. Rechazos sin
  token: `repository_not_found`, `repository_not_removed`,
  `critical_repository`. Con token, `marketplace/repository/ignore` con
  `repository`.
- **FR-010**: `ha_marketplace_remove_repository(repository_id,
  confirmation_token=None)`: solo personalizados no instalados. Rechazos sin
  token: `repository_not_found`, `not_custom_repository`,
  `repository_installed` (con la pista de `ha_marketplace_uninstall`). Con
  token, `marketplace/repositories/remove` con `repository`.
- **FR-011**: `ha_marketplace_refresh_repository(repository_id,
  confirmation_token=None)`: vista previa con el repositorio y el efecto
  (consulta GitHub a través de HA y gasta su límite; actualiza la información
  guardada; no instala nada). Con token, `marketplace/repository/refresh`;
  `github_rate_limited` explicado.
- **FR-012**: `ha_marketplace_add_repository(repository, category,
  confirmation_token=None)`: valida `repository` (data-model «URL de
  repositorio») y `category` (`integration`, `plugin`, `template`, `theme`)
  sin llamar a HA; comprueba FR-003; rechaza `repository_already_added` si el
  `full_name` ya está en la lista; pide `marketplace/repositories/detect` con
  `owner/repo` y rechaza `category_not_detected` (con las detectadas) si la
  categoría no está entre ellas; traduce `core_repository` y
  `app_repository`. Vista previa con la URL tapada, `full_name`,
  `credentials_hidden`, `credentials_sent: false`, las categorías detectadas,
  `third_party` y el aviso. El token ata la URL completa y la categoría; con
  token se envía `marketplace/repositories/add` con `repository: <owner/repo>`
  y `category`, y se relee el repositorio añadido. Las credenciales de la URL
  nunca se envían a HA ni salen en respuestas, errores, token guardado ni log.

#### Código instalado (tramo 2; familia `marketplace_manage` por la D-2)

- **FR-013**: `ha_marketplace_install(repository_id, version=None,
  replace_built_in=False, backup=True, confirmation_token=None)`: comprueba
  FR-003; rechazos sin token: `repository_not_found`, `cannot_install`,
  `replaces_built_in` (integración cuyo `domain` es de Home Assistant según
  `manifest/get` y sin `replace_built_in=true`). Vista previa (data-model
  «Vista previa de instalar»): repositorio, versión instalada y destino,
  `action` (`install`, `reinstall` o `change_version`), `version_check`,
  `third_party`, `replaces_built_in`, `restart`, `backup`. Con token: backup
  (si `backup`), después `marketplace/repository/install` con `repository`,
  `version` si se pidió y `confirm_replace_built_in: true` solo si
  `replace_built_in`; respuesta con el repositorio releído (`status`,
  `installed_version`, `restart_required`) y el backup.
- **FR-014**: `ha_marketplace_uninstall(repository_id, backup=True,
  confirmation_token=None)`: rechazos sin token: `repository_not_found`,
  `repository_not_installed`, `repository_in_use` (integración con entradas
  de configuración del `domain`, con la pista de `ha_delete_config_entry`).
  Vista previa con lo que se borra (los ficheros del repositorio en
  `/config`; para una tarjeta, también su recurso de Lovelace), `restart`,
  `backup`. Con token: backup y `marketplace/repository/uninstall`.
- **FR-015**: `ha_marketplace_set_version(repository_id, version,
  confirmation_token=None)`: comprueba FR-003; vista previa con la versión
  instalada, la que HA ofrece ahora y la nueva selección (la rama por defecto
  quita la selección), que no instala nada y cómo se instala después. Con token,
  `marketplace/repository/version`.
- **FR-016**: `ha_marketplace_set_beta(repository_id, show_beta,
  confirmation_token=None)`: comprueba FR-003; vista previa con el cambio y
  su efecto (las betas pasan o dejan de pasar a ser la versión ofrecida; no
  instala nada). Con token, `marketplace/repository/beta`.
- **FR-017**: El backup de FR-013 y FR-014 es un backup parcial del Supervisor
  con la configuración de Home Assistant, sin apps, sin carpetas y sin la base
  de datos, con un nombre genérico (`hermes_marketplace_<acción>_<fecha UTC>`,
  sin el repositorio), y se espera a que termine. Si falla o no termina en la
  espera larga, no se envía el comando de HA, el token queda fallido y la
  respuesta dice el `job_id` si lo hay. Con `backup=false`, la vista previa
  dice que no habrá backup y el aviso de que el Marketplace solo conserva los
  ficheros anteriores mientras dura la instalación.

#### Lectura existente, tabla, familias, guía, banco y documentación

- **FR-018**: Las descripciones de `ha_marketplace_list_updates` y
  `ha_hacs_list_updates`, el texto `how_to_update` y el tema `marketplace` de
  la guía dejan de decir que Hermes no instala nada: nombran
  `ha_marketplace_install` y `update.install`, y que las dos exigen el aviso
  aceptado por el usuario de HA de Hermes, que Hermes nunca acepta. Ningún
  esquema, anotación ni comando de las tools de lectura cambia
  (FR-091; FR-020 de la 008).
- **FR-019**: Las 10 entradas «pendiente de tool dedicada (spec 026)» de
  `command_table.py` pasan a `dedicated` con su tool (data-model «Tabla»),
  por el mecanismo del generador (`_DEDICADAS_INICIALES` de
  `scripts/inventario/generar_tabla.py`), y la tabla regenerada sale
  idéntica. `github/connect` y `warning/accept` siguen `deny` (clase D);
  `repository/info`, `repositories/clear_new` y `subscribe`, `deny` (clase B)
  (FR-012 de la 008).
- **FR-020**: Familia `marketplace_manage` (desde 1.2.0, desactivable, un
  módulo); `tool_families_disabled` la admite (FR-010 de la 008). (La
  familia `marketplace_install` del diseño original no existe: D-2.)
- **FR-021**: Anotaciones por nombre exacto (contracts/tools.md): las nueve
  sin `readOnlyHint` y con `destructiveHint`; `openWorldHint` las que hacen
  que HA hable con GitHub. Ninguna entra por un prefijo (FR-091; FR-018 de la
  008).
- **FR-022**: Guía: un tema por familia nueva, con el nombre de la familia:
  `marketplace_manage` (sus cinco tools, ignorar frente a reconocer, las
  credenciales de la URL; tras la D-2, también desinstalar, el backup y el
  reinicio) y `marketplace_install` (no existe: D-2); explica la condición del
  aviso de riesgos y del usuario del Supervisor; alias de búsqueda; el índice
  los nombra y el tema `marketplace` remite a ellos (con su huella
  actualizada); las instrucciones del servidor nombran cada tema solo con su
  familia activa (FR-011 de la 008).
- **FR-023**: Banco: `ha_marketplace_acknowledge_critical` se ejecuta en el
  banco contra HA Core 2026.11.1 (en `PROBADAS_026`, exigida por ejecución)
  con un aviso crítico sembrado y su efecto leído de vuelta; las otras ocho en
  `NO_EJECUTABLES_026` con su motivo; un test de contrato del banco envía la
  carga de cada uno de los 9 comandos de escritura con un repositorio
  inexistente y comprueba que HA la acepta. Las nueve en la matriz de la 014
  (FR-015 y FR-016 de la 008).
- **FR-024**: Inventario de argumentos atados (033) con las nueve; ninguna usa
  `allow_dangerous` (018); ninguna lista nueva (no aplica `sobre_de_lista`).
- **FR-025**: Documentación en el mismo cambio: sección «Escritura en el
  Marketplace» en `## [1.2.0]` del CHANGELOG; estado de la 026 en la tabla del
  programa de `docs/HOJA-DE-RUTA.md` y su viñeta de pendientes; `hermes/DOCS.md`
  (las dos familias); `README.md` y `README.es.md` sincronizados; `SECURITY.md`
  (código de terceros); fila CAP-075 de la matriz de la 008 (FR-023 de la
  008).

### Entidades clave

- **Repositorio del Marketplace**: `id` (texto de dígitos en 2026.11.1),
  `full_name` (`owner/repo`), categoría, `custom`, `installed`,
  `installed_version`, `available_version`, `can_install`, `domain`,
  `status`. Se lee de `marketplace/repositories/list` por categoría (nunca el
  catálogo entero de una vez: hallazgo R-1 de la 006).
- **Aviso crítico**: `repository` (`full_name`), `reason`, `link`,
  `acknowledged`.
- **Retirado**: `repository`, `reason`, `link`, `removal_type`.
- **Estado atado**: lo leído en la vista previa que decide el efecto.
- **Backup previo**: backup parcial del Supervisor de la configuración de HA.

## Fuera de alcance

- Conectar GitHub y aceptar el aviso de riesgos (clase D, FR-091).
- Escribir con HACS 2.x (HA ≤ 2026.10).
- Reiniciar Core tras instalar (lo hace `sv_restart_core`, que ya valida la
  configuración).
- Quitar la marca «nuevo» (`clear_new`, clase B) y suscribirse a eventos
  (clase B).
- Cambiar la forma o el comportamiento de las tools de lectura.
- Deshacer «ignorar» (HA 2026.11.1 no tiene comando).

## Supuestos

- HA Core 2026.11.1 es la referencia; el Marketplace es la integración de
  Core `marketplace`.
- Hermes se conecta a Core por el proxy del Supervisor con `SUPERVISOR_TOKEN`
  (`ha.py`), así que el usuario de los comandos es el del Supervisor.
- El Supervisor permite a Hermes crear backups parciales (ya lo hace
  `sv_create_backup_partial`).
- `repositories/list` filtra por categoría y devuelve el resumen que ya
  proyecta `tools/marketplace.py`.

## Criterios de éxito *(obligatorio)*

- **SC-001**: Las nueve tools están registradas por defecto con las
  anotaciones de contracts/tools.md, y ninguna con sus familias desactivadas;
  con las familias de la 1.2.0 desactivadas, la lista es la de la 1.1.2.
- **SC-002**: Las 10 entradas de FR-019 son `dedicated` y apuntan a una tool
  registrada; ninguna entrada dice «spec 026»; la tabla regenerada no cambia.
- **SC-003**: En el 100 % de los casos probados que HA rechazaría y Hermes
  puede saber antes (aviso sin aceptar, GitHub sin conectar, inexistente, no
  instalado, en uso, instalado, no personalizado, no retirado, crítico, ya
  añadido, categoría no detectada, sustituye a una de HA sin permiso, no
  instalable), no se emite token ni se envía ningún comando de escritura.
- **SC-004**: Ningún centinela de credenciales de una URL aparece en una
  respuesta, una vista previa, un error, el fichero del token ni el log, y
  nunca se envía a HA.
- **SC-005**: Con token, instalar y desinstalar no envían el comando de HA si
  el backup no terminó bien.
- **SC-006**: La suite pasa en el CI de Linux al final de cada tramo, con los
  6 fallos conocidos de Windows y ninguno más; el banco, con 0 `xfail`.
- **SC-007**: Las nueve tienen fila en la matriz de la 014: una «banco de
  Core / ok» y ocho «instalación real / pendiente» con el motivo del banco en la nota.
