# Plan de implementación: escritura en el Marketplace (026)

**Rama**: `feat/026-marketplace-escritura` (sale de `feat/cobertura-total`,
punta `f108af0`, 314 tools) · **Spec**: [spec.md](spec.md) · **Paraguas**:
[008](../008-cobertura-total/plan.md), tarea T025, «M, 2 tramos».

## Resumen

> **DESVIACIÓN DV-1 (spec.md, «Requisitos»)**: lo que sigue es el plan
> original de nueve tools. Por decisión del supervisor, las cuatro que
> exigen el aviso de riesgos aceptado por el usuario de Hermes
> (`ha_marketplace_install`, `ha_marketplace_set_version`,
> `ha_marketplace_set_beta`, `ha_marketplace_add_repository`) no se
> construyen y sus cinco comandos (`install`, `version`, `beta`, `detect`,
> `add`) quedan en `deny` con el motivo de la duda D-29. Quedan cinco tools:
> el tramo 1 hace las cuatro de `marketplace_manage` (reconocer, ignorar,
> quitar, refrescar) con el módulo común `tools/_marketplace_write.py`; el
> tramo 2, solo `ha_marketplace_uninstall` con su backup previo. FR-018 no
> aplica (los textos de lectura siguen siendo verdad). Donde el diseño de
> abajo habla de las cuatro que exigen el aviso, de `comprobar_aviso`, de la
> URL de GitHub o de `version_check`, ya no aplica.
>
> Desviaciones de implementación del tramo 1: las lecturas de las vistas
> previas no usan `_list_catalog` de `tools/marketplace.py` (cae a HACS, y
> la escritura no debe probar `hacs/*`): el módulo común lee por categorías
> solo de `marketplace/*`, con su propia lista cerrada de lecturas
> (`_READ_SUFFIXES`). En el generador de la tabla, una fila A con `_Deny` en
> `_DEDICADAS_INICIALES` sale `deny` con su motivo (mismo mecanismo que la
> 031 para `hassio/*`).

Nueve tools nuevas, todas en dos pasos, en dos familias nuevas:
`marketplace_manage` (añadir y quitar repositorios personalizados, refrescar,
ignorar un retirado y reconocer un aviso crítico) y `marketplace_install`
(instalar, desinstalar, fijar versión y mostrar betas, con backup parcial
previo al instalar y desinstalar). Las 10 entradas «pendiente de tool dedicada
(spec 026)» pasan a `dedicated`. Las tools de lectura de la 1.1.2 solo cambian
el texto que decía que Hermes no instala nada.

Hallazgo que limita el alcance (research R-2): HA 2026.11.1 exige que el
usuario de HA del comando haya aceptado el aviso de riesgos para instalar,
fijar versión, betas y añadir; el de Hermes es el usuario del Supervisor, que
nadie puede aceptar y Hermes nunca acepta. Esas cuatro rechazan sin token y lo
explican; las otras cinco funcionan. Duda D-1.

## Contexto técnico

**Lenguaje**: Python 3.13. **Dependencias**: las de Hermes; ninguna nueva.
**Pruebas**: pytest + `unittest` asíncrono con HA simulado (`ws_send`) y
Supervisor simulado (`sv_request`), como `tests/test_tools_marketplace.py`;
banco de Core (010) para reconocer un crítico y el contrato de cargas.
**Plataforma**: add-on de HAOS; tests en Windows y en el CI de Linux.
**Restricciones**: `response_max_bytes` (131072); mensajes WS por categoría
(hallazgo R-1 de la 006); proxy WS del Supervisor (sin `hassio/` ni
`supervisor/`).

**Escala**: 9 tools en 2 módulos nuevos (`tools/marketplace_manage.py`,
`tools/marketplace_install.py`) y un módulo común sin tools
(`tools/_marketplace_write.py`); cambios en `tool_families.py`,
`command_table.py` (10 líneas), `scripts/inventario/generar_tabla.py`
(`_DEDICADAS_INICIALES`), `tools/__init__.py`, `tools/_annotations.py`,
`tools/guide.py`, `tools/marketplace.py` y `tools/hacs.py` (solo textos);
`tests/banco/cobertura_026.py` (nuevo), `tests/banco/cobertura_escrituras.py`,
`tests/test_banco_cobertura_escrituras.py`, un test del banco nuevo y una
semilla `tests/banco/ha_config/.storage/marketplace.critical`; una fixture y 4
ficheros de test nuevos; ajustes en `tests/test_command_table.py`,
`tests/test_generar_tabla.py`, `tests/test_tools_registration.py`,
`tests/test_tool_families.py`, `tests/test_config_validation.py`,
`tests/test_tools_guide.py`, `tests/test_tools_marketplace.py`,
`tests/test_tools_hacs.py`, `tests/test_confirmation_args_inventory.py`;
documentación (`CHANGELOG`, `HOJA-DE-RUTA`, `DOCS`, `README`s, `SECURITY.md`,
matriz de la 008).

## Comprobación de la constitución

Contra la constitución 1.2.0 (con las enmiendas de la 011).

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Instalar, actualizar y quitar código de terceros van en dos pasos con vista previa honesta (repositorio, versión, código de terceros sin revisar, sustituye a una integración de HA, reinicio, backup); lista cerrada de comandos de escritura con guarda; nunca `github/connect` ni `warning/accept`; ningún comando con `hassio/` ni `supervisor/`; argumentos validados antes de llamar (FR-001…FR-005, FR-012, FR-013). | OK |
| II. Secretos | Credenciales de la URL tapadas enteras en vista previa, respuestas, errores, fichero del token y log, y nunca enviadas a HA (solo `owner/repo`); errores por `redact_secrets` y `redactar_mensaje`; evento de log sin repositorios, URLs ni textos; centinelas en tests (FR-006, FR-007, FR-012; SC-004). | OK |
| III. Fail-closed | Todo lo que HA rechazaría y Hermes sabe antes, sin token (SC-003); estado releído al confirmar, y si no se puede leer el token no vale; backup fallido → no se instala ni desinstala (SC-005); HACS → `marketplace_write_unsupported` sin probar comandos que no se pueden verificar. | OK |
| IV. Dos pasos | Las nueve con `create_confirmation_token`, token atado a los argumentos (URL completa, versión, categoría, `replace_built_in`, `backup`, `show_beta`) y a `estado` (`full_name`, categoría, versiones) (FR-004; data-model «Estado atado»); inventario de la 033 con las nueve. | OK |
| V. Nombre y descripción | Las cuatro que exigen el aviso lo dicen primero y rechazan sin token cuando falta; anotaciones por nombre exacto, ninguna `readOnlyHint` por prefijo; las tools de lectura dejan de decir «Hermes does not install anything» (FR-003, FR-018, FR-021). | OK |
| VI. Lo que no se puede probar | Unitarios con HA y Supervisor simulados con la forma de 2026.11.1. En el banco (sin internet, sin catálogo) solo se ejecuta reconocer un crítico; las otras ocho, `NO_EJECUTABLES_026` con motivo concreto y fila «instalación real / pendiente» en la matriz (con el motivo del banco en la nota); test de contrato de las 9 cargas contra HA real; prueba en vivo pendiente (FR-023, SC-007; research R-11, R-12). | OK con pendiente declarado |
| VII. Control negativo | T013 y T028 con recuentos: guarda de comandos, aviso sin aceptar, credenciales, estado atado, backup fallido, `replaces_built_in`, retirado/crítico, `dedicated` en la tabla, anotación por prefijo. | OK |
| VIII. Privacidad | Fixtures con `ejemplo/tarjeta`, `ejemplo/tarjeta-critica`, ids `"123456"`, `https://usuario:centinela-026@github.com/…`; nombre de backup sin repositorio; revisión del diff en cada tramo. | OK |
| IX. Cambios mínimos | `tools/marketplace.py` no envía comandos nuevos (se importan sus ayudantes sin moverlos); las tools de lectura solo cambian textos; se reutilizan `_store.py`, `create_confirmation_token` con `estado`, `_LONG_OP_TIMEOUT`, el formato de `_third_party_text`. | OK |
| X. Comentarios en español | Comentarios con el porqué en español; descripciones, errores y eventos en inglés. | OK |
| XI. Versionado | Sin subida de versión; sección propia en `## [1.2.0] — <fecha de publicación>`. | OK |

**Lecturas de la 008 aplicadas** (no desviaciones): la opción
`marketplace_write_enabled` de research CAP-075 la sustituyen las familias
(decisión de la 008); «backup previo» se aplica a instalar y desinstalar, las
que cambian ficheros (research R-6); `refresh` e `ignore` llevan
`_repository` en el nombre y se añade `set_beta` (research R-3, R-4).
**Limitación de HA declarada**: R-2 (D-1).

**Tras el diseño**: sin cambios en la tabla de cumplimiento.

## Diseño

### Tramo 1 — catálogo y avisos (familia `marketplace_manage`)

- `tool_families.py`: familia `marketplace_manage` (1.2.0, desactivable,
  módulo `marketplace_manage`), con el porqué (research R-3).
- `tools/_marketplace_write.py` (sin tools): `_WRITE_SUFFIXES` y
  `ws_escritura(ha_client, sufijo, carga)` con la guarda y la traducción de
  `unknown_command` → `marketplace_write_unsupported`, `not_loaded` →
  `marketplace_not_loaded` y los códigos de HA a los de data-model;
  `cargas` públicas por comando; `repositorio_por_id` (lista por categorías
  con `_list_catalog` de `tools/marketplace.py`, guardando también el bruto
  para `config_flow`); `comprobar_aviso(ha_client, github=False)` con
  `marketplace/info`; validadores (`repository_id`, `version`, `category`,
  booleanos, `owner/repo`, URL de GitHub); `resumen_para_preview`; evento
  `marketplace_write`; envoltura de salida con `tapar_en_estructura`. Su test
  propio de funciones puras.
- `tools/marketplace_manage.py`: las cinco tools (FR-008…FR-012), con
  `create_confirmation_token(..., estado=…)` y
  `resolve_confirmation_token(..., estado=…)` como la 030, y
  `complete_confirmation_token` en éxito y en fallo.
- `tools/__init__.py`: registro dentro de la comprobación de la familia.
- `tools/_annotations.py`: las cinco en `_DESTRUCTIVE_EXACT` (y `_OPEN_WORLD`
  refrescar y añadir), con un comentario que recuerda la regla del prefijo.
- Tabla: las seis entradas del tramo 1 (data-model) a `dedicated` por
  `_DEDICADAS_INICIALES` del generador (`detect` con `_ConMatiz`); regenerar
  y comprobar que no cambia.
- Guía: tema `marketplace_manage` (FR-011 de la 008: un tema por familia
  nueva) con las cinco y la condición del aviso; índice y alias;
  instrucciones del servidor con la familia activa.
- Banco: `tests/banco/cobertura_026.py` (`MODULOS_026`, `PROBADAS_026` con
  `ha_marketplace_acknowledge_critical`, `NO_EJECUTABLES_026` con las cuatro
  del tramo y el motivo de research R-11); suma en el invariante y en
  `TOOLS_EXIGIDAS_DEL_JOB`; semilla `.storage/marketplace.critical`;
  `tests/banco/test_banco_marketplace.py` (reconocer con lector; estado del
  Marketplace del banco leído con `marketplace/info`; contrato de las seis
  cargas del tramo 1). Filas de la matriz.
- Inventario de la 033 con las cinco.
- Documentación del tramo (CHANGELOG, DOCS, READMEs, SECURITY, HOJA «en
  curso: tramo 1»).

### Tramo 2 — código instalado (familia `marketplace_install`)

- `tool_families.py`: familia `marketplace_install` (módulo
  `marketplace_install`).
- `tools/_marketplace_write.py`: `backup_previo(ha_client, accion)` (POST
  `/backups/new/partial` con `homeassistant: true`,
  `homeassistant_exclude_database: true`, `background: false`, espera larga,
  nombre genérico) y `reinicio_probable(repo, bruto, cargada)`; cargas de
  instalar, desinstalar, versión y betas.
- `tools/marketplace_install.py`: las cuatro tools (FR-013…FR-017): aviso,
  `manifest/get` para `replaces_built_in`, `repository/releases` para
  `version_check`, `config_entries/get` del `domain` para `repository_in_use`
  y para «cargada», backup antes del comando, repositorio releído.
- `tools/marketplace.py` y `tools/hacs.py`: `_HOW_TO_UPDATE` y las
  descripciones de las dos `*_list_updates` (FR-018); ningún cambio de
  esquema ni de comandos; `TestOnlyAllowedCommands` y la instantánea de
  esquemas en verde.
- Tabla: las cuatro entradas del tramo 2 a `dedicated`; ninguna con «spec
  026»; regenerar sin cambios.
- Guía: tema `marketplace_install` (cuatro tools, condición del aviso,
  backup, reinicio, `replace_built_in`); el tema `marketplace` sin «Hermes NO
  instala», remitiendo a los dos temas nuevos, y con su huella actualizada.
- Banco: las cuatro a `NO_EJECUTABLES_026`; contrato de las cuatro cargas.
  Filas de la matriz.
- Inventario de la 033; documentación final (estado «hecha», fila CAP-075 de
  la matriz de la 008).

## Pruebas

| Qué | Dónde | Tramo |
|---|---|---|
| Funciones puras (validadores, URL, cargas, guarda, errores) | `tests/test_marketplace_write_comun.py` | 1 (y 2 para backup y reinicio) |
| Las cinco de catálogo y avisos | `tests/test_tools_marketplace_manage.py` | 1 |
| Las cuatro de código instalado | `tests/test_tools_marketplace_install.py` | 2 |
| Fixture HA 2026.11.1 del Marketplace (lista por categoría, info, críticos, retirados, versiones, manifiestos, entradas) y Supervisor (backups) | `tests/fixtures/marketplace_escritura.py` | 1 (ampliada en 2) |
| Tabla, generador, familias, opción, registro, anotaciones, inventario 033 | ficheros existentes | 1 y 2 |
| Textos de lectura (FR-018) | `tests/test_tools_marketplace.py`, `tests/test_tools_hacs.py` | 2 |
| Banco: reconocer, estado del Marketplace, contrato de cargas | `tests/banco/test_banco_marketplace.py` | 1 y 2 |

## Riesgos

- **Semilla del banco**: si la entrada del Marketplace no carga en el banco,
  el aviso de Repairs no existe; el test lo admite (comprueba el aviso solo si
  estaba) y lo principal (`acknowledged`) no depende de la entrada (reconocer
  no usa el decorador). Si el storage sembrado no se lee, es un problema del
  banco y no de HA: la tool pasa a `NO_EJECUTABLES_026` con ese motivo, sin
  `xfail`. Si HA falla al reconocer, es un HALLAZGO: `xfail` estricto que
  espera ese fallo (patrón de la 028; el banco tiene hoy 0 `xfail`). En los
  dos casos se anota en las notas del tramo.
- **Forma de `repositories/list`**: el id es texto de dígitos en 2026.11.1; se
  compara como texto, como la lectura.
- **Tiempo del backup**: con la base de datos fuera suele ser corto; si pasa
  de la espera larga, no se instala (fail-closed) y se devuelve el `job_id`.
- **D-1**: si el mantenedor decide quitar las cuatro tools que exigen el
  aviso, es borrar `ha_marketplace_set_version`, `set_beta`, `install` y
  `add_repository` y devolver sus cinco entradas a `deny` con motivo; el resto
  no cambia.

## Estructura de la documentación de la feature

```text
specs/026-marketplace-escritura/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/tools.md
├── checklists/requirements.md
└── tasks.md
```
