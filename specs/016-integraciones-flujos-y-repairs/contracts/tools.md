# Contratos: tools de integraciones, flujos y Repairs (016)

Las formas de respuesta están en [data-model.md](../data-model.md). Aquí:
firmas, anotaciones, guía, tabla y banco.

## Firmas (esquema de entrada MCP)

| Tool | Argumentos | Modifica | Token |
|---|---|---|---|
| `ha_list_discovered_integrations` | `domain: str \| None = None` | no | no |
| `ha_ignore_discovery` | `flow_id: str`, `title: str \| None = None` | sí | no |
| `ha_list_config_flow_domains` | `type: str \| None = None` | no | no |
| `ha_update_config_entry` | `entry_id: str`, `title: str \| None = None`, `pref_disable_polling: bool \| None = None`, `pref_disable_new_entities: bool \| None = None`, `confirmation_token: str \| None = None` | sí | solo al pasar una preferencia a `true` |
| `ha_list_config_subentries` | `entry_id: str` | no | no |
| `ha_start_subentry_flow` | `entry_id: str`, `subentry_type: str`, `subentry_id: str \| None = None` | sí (abre un flujo) | no |
| `ha_continue_subentry_flow` | `flow_id: str`, `user_input: dict[str, Any]` | sí | no |
| `ha_abort_subentry_flow` | `flow_id: str` | sí (cierra un flujo) | no |
| `ha_update_subentry` | `entry_id: str`, `subentry_id: str`, `title: str` | sí | no |
| `ha_delete_subentry` | `entry_id: str`, `subentry_id: str`, `confirmation_token: str \| None = None` | sí | sí |
| `ha_start_reconfigure_flow` | `entry_id: str` | sí (abre un flujo) | no |
| `ha_get_repair` | `domain: str`, `issue_id: str` | no | no |
| `ha_start_repair_fix` | `domain: str`, `issue_id: str` | sí (abre un flujo; ver D-3) | no |
| `ha_continue_repair_fix` | `domain: str`, `issue_id: str`, `flow_id: str`, `user_input: dict[str, Any] \| None = None`, `confirmation_token: str \| None = None` | sí | sí |
| `ha_abort_repair_fix` | `flow_id: str` | sí (cierra un flujo) | no |

Tools existentes que cambian (sin tocar su esquema de entrada):

| Tool | Cambio |
|---|---|
| `ha_list_repairs` | cada aviso gana `title`, `description`, `description_truncated`; la raíz, `language`, `translations_unavailable`, `_third_party_text` |
| `ha_ignore_repair` | la vista previa gana `title` (traducido) |
| `ha_list_configured_domains` | solo la docstring (principio V: ya existe la lista de dominios configurables) |

Todas las nuevas con `@ready` (`requires_ready`) y `response_max_bytes` donde
listan o devuelven datos de HA. Docstrings en inglés que dicen lo que hacen y
lo que no (por ejemplo: que ignorar se deshace borrando la entrada `ignore`;
que el reconfigure se continúa con `ha_continue_config_entry_flow`; que abrir
un flujo de reparación puede terminarlo en algunas integraciones; que cada
envío de un paso de reparación pide token porque puede aplicar el arreglo).

## Anotaciones (`tools/_annotations.py`)

| Tool | readOnly | destructive | idempotent | openWorld | Dónde |
|---|---|---|---|---|---|
| `ha_list_discovered_integrations`, `ha_list_config_flow_domains`, `ha_list_config_subentries`, `ha_get_repair` | sí | no | sí | no | prefijo (ya cubierto) |
| `ha_ignore_discovery` | no | no | sí | no | por defecto |
| `ha_update_config_entry` | no | sí | sí | no | `_DESTRUCTIVE_EXACT`, con comentario |
| `ha_start_subentry_flow`, `ha_start_reconfigure_flow`, `ha_start_repair_fix` | no | no | no | no | `_NON_IDEMPOTENT_EXACT`, con comentario |
| `ha_continue_subentry_flow` | no | no | no | no | `_NON_IDEMPOTENT_EXACT` |
| `ha_continue_repair_fix` | no | sí | no | no | `_DESTRUCTIVE_EXACT` y `_NON_IDEMPOTENT_EXACT` |
| `ha_abort_subentry_flow`, `ha_abort_repair_fix` | no | no | sí | no | por defecto (como `ha_abort_config_entry_flow`) |
| `ha_update_subentry` | no | no | sí | no | por defecto |
| `ha_delete_subentry` | no | sí | sí | no | prefijo `ha_delete_` |

Comentarios:

- `ha_update_config_entry`: puede pedir token (desactivar el sondeo recarga la
  integración y deja sus entidades sin actualizar; desactivar las entidades
  nuevas hace que lo que se añada entre deshabilitado); invariante «pide token
  ⇔ destructiva».
- `ha_continue_repair_fix`: cada envío puede aplicar el arreglo de una
  integración, con efectos propios de cada una.
- No idempotentes: cada llamada abre un flujo nuevo o avanza el flujo un
  paso; repetirla no deja el mismo estado. Las de la 1.1.2
  (`ha_start_config_entry_flow`, `ha_continue_*_flow`) no se tocan (D-4).

## Errores

Ver la tabla de data-model.md. Ninguna comprobación previa fallida emite token
ni hace la llamada que modifica.

## Guía (`tools/guide.py`)

- Tema `integration_flows` (alias `discovery`, `discovered`, `subentries`,
  `subentry`, `reconfigure`): descubiertos (listar, configurar con
  `ha_continue_config_entry_flow`, ignorar y deshacer); dominios configurables;
  título y preferencias (qué pide token y por qué); subentries (tipos, crear,
  reconfigurar, renombrar, borrar con token); reconfigure de la entrada;
  flujos OAuth abortados e informados.
- Tema `repair_flows` (alias `repair_fix`, `fix`): `ha_get_repair` →
  `ha_start_repair_fix` → `ha_continue_repair_fix` (vista previa y token en
  cada paso) → `ha_abort_repair_fix`; qué hace HA al terminar; el caso de los
  flujos que terminan al abrirse; receta «arreglar un aviso de Repairs».
- `helpers`: sección «Helpers por config entry» (CAP-037, FR-016 de la spec).
- `config_entries`: una línea que remite a `integration_flows`.
- `diagnostics`: una línea que remite a `repair_flows` y menciona `title` y
  `description` en `ha_list_repairs`.
- Test: cada tool registrada de las dos familias aparece nombrada en su tema;
  el índice los lista.

## Tabla (`command_table.py`)

Las siete entradas de data-model.md a `dedicated`, con `cap` y la familia de
su tool; comentario sobre `frontend/get_translations`. `_DEDICADAS_INICIALES`
en `scripts/inventario/generar_tabla.py` con las mismas siete. Regenerar no
cambia nada (`git diff` vacío en la tabla).

## Banco

- `tests/banco/ha_config/configuration.yaml`: `banco_flujos:` con comentario.
- `tests/banco/ha_config/custom_components/banco_flujos/`: `manifest.json`,
  `__init__.py`, `config_flow.py`, `sensor.py`, `repairs.py`,
  `translations/en.json` (research R-9). Sin red ni requisitos.
- `tests/banco/test_banco_integraciones.py` (tramos A y B) y
  `tests/banco/test_banco_repairs.py` (tramo C).
- `tests/banco/cobertura_016.py`: `PROBADAS_016` (las once tools que
  modifican) y `NO_EJECUTABLES_016 = {}`; una línea en la unión de
  `tests/test_banco_cobertura_escrituras.py` (o test propio si la 028 no está,
  S-02).
