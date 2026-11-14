# Investigación: pruebas de las escrituras de Core en el banco (spec 028)

Fuentes: código de Hermes en la rama base (registro de producción,
`hermes/src/hermes/tools/_annotations.py` y los módulos de tools), el banco de
la 010 (`tests/banco/`, `specs/010-banco-de-pruebas-core/`) y el código de
Home Assistant Core 2026.11.1 (solo leído).

## R-0. Recuento exacto

**Decisión**: el universo es el registro de producción
(`hermes.__main__._build_mcp(HermesConfig(), …)`) filtrado por
`classify(nombre).read_only_hint is False`.

**Resultado** (rama base, 216 tools): **124** modifican = **100** `ha_*` +
**5** `fs_*` + **19** `sv_*`. De las 100 `ha_*`, **47** son de los 11 dominios
de helpers (inventario de la 010, `tests/banco/cobertura.py`) y **53** son de
la 028.

**Por qué las anotaciones y no el prefijo**: la 010 filtra por «no empieza por
`ha_list_`/`ha_get_`» porque sus módulos solo tienen esas lecturas. Para el
registro entero eso falla: `ha_render_template`, `ha_search_related` o
`ha_wait_for_event` leen y no tienen ese prefijo, y `sv_get_job_status` o
`sv_check_core_config` escriben aunque lo parezca. La tabla de anotaciones es
la fuente única que ya vigila un test y la que ve el cliente.

**Alternativa descartada**: lista escrita a mano de las 124: se desalinea con
la primera tool nueva sin que nadie lo vea.

## R-1. Dispositivos, reparaciones y flujo de opciones sin hardware: `kitchen_sink`

**Decisión**: añadir `kitchen_sink:` a la configuración del banco.

**Por qué**: es la integración de demostración de Core. Al cargarse por YAML
importa su config entry (`async_step_import`), crea entidades con dispositivos
(botón, ventilador, cerradura, sensores, interruptores…), crea avisos de
reparación propios (`transmogrifier_deprecated`, `unfixable_problem`,
`cold_tea`…), tiene flujo de opciones (`options_1`, con una sección que lleva
un booleano y un entero) y permite borrar a mano cualquier dispositivo salvo
`statistics_issues` (`async_remove_config_entry_device`). Es exactamente lo que
necesitan `ha_update_device`, `ha_remove_device`,
`ha_remove_device_from_config_entry`, `ha_ignore_repair`,
`ha_start_options_flow` y `ha_continue_options_flow`. Todo es local.

**Riesgos y cómo se cubren**:

- Importa módulos de `recorder` y `labs`; si `recorder` no está cargado, se
  salta la parte de estadísticas (`if "recorder" in hass.config.components`).
  No se añade `recorder:`.
- No se ha podido leer su `manifest.json` (no viene en las fuentes
  descargadas): si declara una dependencia que no carga sin internet, el primer
  paso del tramo B lo detecta (`config_entries/get` con `domain:
  kitchen_sink` y estado `loaded`) y se avisa al supervisor (S-02 de la spec).
- Su flujo de opciones recarga la entrada (oyente de actualización) y puede
  volver a crear dispositivos borrados: las comprobaciones de borrado se hacen
  justo después de confirmar (spec, casos límite).

**Alternativas descartadas**: `demo` (más pesada y con plataformas que no hacen
falta); MQTT u otras integraciones con dispositivos reales (hardware o
broker); crear dispositivos a mano (HA no tiene API para eso).

## R-2. Flujos de configuración y ciclo de vida de una config entry: `uptime`

**Decisión**: `uptime`, creada por las propias tools de flujo durante el test.

**Por qué**: `async_step_user` muestra un formulario con esquema vacío y, al
continuar con `{}`, crea la entrada «Uptime». Su sensor guarda la hora de
creación de la entidad (`dt_util.utcnow()` en `__init__`), así que **una
recarga cambia el estado del sensor**: es la comprobación del efecto de
`ha_reload_config_entry`. Crea además un dispositivo de servicio. No necesita
nada externo. Es de una sola instancia: el test la borra al terminar.

**Uso**: abrir flujo → `ha_abort_config_entry_flow` → el flujo ya no está en
`config_entries/flow/progress`; abrir otro → `ha_continue_config_entry_flow`
→ entrada `loaded`; `ha_reload_config_entry` → el sensor cambia;
`ha_disable_config_entry` (dos pasos) → `disabled_by: user`;
`ha_enable_config_entry` → otra vez `loaded`; `ha_delete_config_entry` (dos
pasos) → la entrada no existe.

**Alternativas descartadas**: usar `kitchen_sink` (solo tiene paso de
importación, no de usuario) o las entradas que crea el onboarding (`met`,
`radio_browser`, `google_translate`, que buscan internet y quedan en
reintento).

## R-3. Configuración de HA del banco

**Decisión**: añadir a `tests/banco/ha_config/configuration.yaml`:

- `automation: !include automations.yaml`, `script: !include scripts.yaml` y
  `scene: !include scenes.yaml`, con `automations.yaml` (`[]`),
  `scripts.yaml` (`{}`) y `scenes.yaml` (`[]`) versionados en la misma
  carpeta. Las tools de configuración guardan por los endpoints
  `config/<dominio>/config/<id>` de HA, que escriben en esos ficheros; sin el
  `!include`, HA no recargaría lo guardado.
- `frontend:`: registra Lovelace (dashboards y recursos por WebSocket, en modo
  almacenamiento) y arrastra `repairs`. No sale a internet: sirve ficheros de
  la propia imagen.
- `kitchen_sink:` (R-1), en el tramo B.

El job de la 010 copia la carpeta entera a `$RUNNER_TEMP`, así que los YAML
nuevos llegan solos. El comentario de cabecera ya prevé que las sub-features
añadan dominios.

**Alternativa descartada**: `default_config:` (la 010 ya explicó por qué no).

## R-4. Inventario propio, sin tocar el de la 010

**Decisión**: fichero nuevo `tests/banco/cobertura_escrituras.py` y test nuevo
`tests/test_banco_cobertura_escrituras.py`. El de la 010 no se toca.

**Por qué**: el tramo B de la 010 está en curso en otra rama; cambiar su
inventario provocaría conflictos. El invariante nuevo importa las listas de la
010 y las suma (el de la 010 sigue comprobando su parte con su recuento de 47).

**Listas**: `PROBADAS_028`, `NO_EJECUTABLES_028` (vacía),
`FUERA_DEL_BANCO` (24 con motivo) y, solo entre el tramo A y el B,
`PENDIENTES_TRAMO_B` (las 27 del tramo B con el motivo «se prueba en el tramo B
de la 028»), para que el invariante esté en verde al terminar el tramo A. El
tramo B la vacía y la borra; si quedase algo, el invariante falla.

**Sub-features posteriores**: añaden su propia lista y la suman en el
invariante (una línea), como pide FR-015 de la 008.

## R-5. Por qué `fs_*` y `sv_*` quedan fuera

- **`fs_*`** (`fs_write_file`, `fs_delete_file`, `fs_move_file`,
  `fs_restore_file_backup`, `fs_set_secret`): FR-014 de la 008 es solo para
  `ha_*`. Escriben en el `/config` de Hermes (`HERMES_CONFIG_BASE`), que en el
  banco es `$RUNNER_TEMP/hermes_config`, no la carpeta de HA; no hablan con HA.
  La suite normal ya las ejecuta contra un sistema de ficheros real (bloqueos,
  copias, symlinks, tokens).
- **`sv_*`** (19): el Supervisor del banco es un simulado que solo reenvía a
  Core (contrato de la 010). Backups, add-ons, reinicios, avisos y la
  validación de configuración del Supervisor no existen ahí. Se prueban con
  simuladores en la suite normal y van a la matriz y la VM de la 014.

## R-6. Política ante un fallo contra HA real

**Decisión**: `@pytest.mark.xfail(strict=True, raises=<excepción>, reason=…)`
en el test, comentario `HALLAZGO` con qué hace HA, la tool sigue en
`PROBADAS_028`, nota en «Notas del tramo» de `tasks.md` y en el informe al
supervisor. Mismo patrón que la 010 con `ha_reload_counters`.

**Por qué estricto**: si la tool empieza a funcionar (HA cambia o alguien la
arregla), el test pasa a «XPASS(strict)» y el CI se pone en rojo para quitar
la marca; un fallo esperado no estricto se olvidaría.

**Excepción**: arreglo trivial (definición en la spec). Entra con su test
unitario en `tests/` (no solo el del banco, que no corre en local), control
negativo local y línea en «Correcciones» del CHANGELOG.

**Alternativa descartada**: saltar el test (`skip`): escondería el fallo y el
job del banco trata un salto como fallo.

## R-7. `ha_cancel_wait`: el efecto está en Hermes

`ha_wait_for_event` y `ha_cancel_wait` gestionan una espera que vive en Hermes
(suscripción temporal al bus). El lector no puede ver la espera. La
comprobación es la propia espera: se lanza `ha_wait_for_event` con un tipo de
evento único y tope de 60 s en una tarea, se espera (por sondeo) a que
`ha_list_active_waits` la muestre, se llama a `ha_cancel_wait` y la tarea
termina en menos de 10 s con `reason: cancelled`; después
`ha_list_active_waits` ya no la tiene. Para no comprobar Hermes solo con
Hermes, el lector lanza después ese evento y la espera, ya terminada, no lo
recoge (su resultado sigue siendo `cancelled`).

## R-8. `ha_call_service` en sus dos caminos

- Directo: `input_boolean.turn_on` sobre un helper creado por el lector (el
  humo de la 010 ya lo hace; la 028 lo incluye en su inventario con un test
  propio para que figure en sus ficheros).
- Dos pasos: un servicio de la denylist que no hace daño en el banco,
  `input_boolean.reload`. Vista previa: el lector no ve `input_boolean.reload`
  en el bus; confirmación: lo ve exactamente una vez.
- `ha_call_service_response`: `schedule.get_schedule` (Core registra la
  respuesta como `SupportsResponse.ONLY`) sobre un horario creado por el
  lector; la respuesta trae su `entity_id` y sus franjas.

Nunca `homeassistant.restart` ni `homeassistant.stop` (spec, casos límite).

## R-9. El Supervisor simulado basta

Las 53 tools usan `ws_send`, `call_service`, `config_read`/`config_save`/
`config_delete` (REST `GET`/`POST`/`DELETE` en `/api/config/…`),
`fire_event` y `_request_json` (flujos de config entries, `GET`/`POST`/
`DELETE`). Ninguna llama a `sv_request` ni usa `PUT` o `PATCH`. El proxy del
simulado de la 010 (REST `GET`/`POST`/`DELETE` y WebSocket) las cubre. Si
alguna resultara usar una ruta que no tiene, el simulado responde 404 a la
vista y el test falla: se añade la ruta replicando al Supervisor real, con
test de contrato.

## R-10. Lector: lo que falta

El lector de la 010 tiene `listar`, `estado`, `esperar`, `servicios_llamados`,
`eventos`, `crear` y `borrar`. Para la 028 hacen falta dos operaciones
genéricas, sin tocar las existentes:

- `comando(mensaje)`: cualquier comando WebSocket (`config/area_registry/list`,
  `config_entries/get`, `lovelace/config`, `repairs/list_issues`…). Envuelve
  el `_comando` privado que ya existe.
- `rest(metodo, ruta, cuerpo=None)`: REST directo a Core con el token de larga
  duración; devuelve `(estado, cuerpo)` (configuración de automatizaciones,
  scripts y escenas en `/api/config/<dominio>/config/<id>`; flujos de opciones
  en `/api/config/config_entries/options/flow`).

Con un test de la suite normal contra el doble de Core de la 010.

## R-11. Reparto en tramos

| Tramo | Dominios | Tools | Necesita |
|---|---|---|---|
| A | automatizaciones (6), scripts (4), escenas (5), servicios y eventos (3), esperas (1), Lovelace (7) | 26 | `automation:`, `script:`, `scene:`, `frontend:`; lector ampliado; inventario y su invariante |
| B | áreas, plantas, etiquetas y categorías (12), dispositivos (3), entidades (2), reparaciones (1), config entries (4), flujos (5) | 27 | `kitchen_sink:`; `uptime` por flujo |

El tramo A lleva lo común (lector, inventario) porque el B depende de ello.

## R-12. Control negativo en el CI

Una rama desechable (`prueba/028-control-<tramo>`) con un commit que rompe a
propósito una tool en `hermes/src/`; push, ver en rojo el test del banco
correspondiente en `gh run watch` y borrar la rama. Solo si el encargo del
tramo no permite empujar otras ramas, como hizo la 010 (T021): commit de
control en la rama de la sub-feature y `git revert` en el siguiente. El cambio
de control nunca queda en la punta de la rama ni en un PR (desviación acotada
de la puerta 3, justificada en la comprobación de la constitución del plan).

- Tramo A: `ha_activate_scene` (que llama a `scene.turn_on`) manda un
  `entity_id` de escena inexistente → el `input_boolean` de la escena no se
  enciende y cae el test de escenas.
- Tramo B: `ha_create_area` crea el área con el nombre cambiado → cae el test
  de áreas.
