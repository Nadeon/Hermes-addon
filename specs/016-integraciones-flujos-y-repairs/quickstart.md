# Quickstart: validar integraciones, flujos y Repairs (016)

Todo con la suite y el banco; nada contra una instalación real (las pruebas en
vivo quedan para después de publicar, como en el resto del programa).

## Suite

```bash
export MSYS_NO_PATHCONV=1   # solo en Git Bash de Windows
HERMES_CONFIG_BASE=<carpeta temporal propia> python -m pytest -q -p no:cacheprovider
```

Ficheros nuevos que deben pasar: `tests/test_tools_integration_setup.py`
(A), `tests/test_tools_config_subentries.py` (B), `tests/test_tools_translations.py`
y `tests/test_tools_repair_flows.py` (C); y los cambios en
`tests/test_tools_repairs.py`, `tests/test_tool_families.py`,
`tests/test_tools_registration.py`, `tests/test_command_table.py`,
`tests/test_generar_tabla.py`, `tests/test_tools_guide.py` y
`tests/test_tools_generic_commands.py`. En Windows fallan exactamente los 6
conocidos; la referencia es el CI de Linux.

## Tabla

```bash
python scripts/inventario/generar_tabla.py
git diff --exit-code -- hermes/src/hermes/command_table.py
```

Sin diferencias tras cada tramo: las entradas `dedicated` de la 016 las
conserva el generador y su mapa las produce iguales en una primera generación
(`test_generar_tabla.py`).

## Banco

En el job `banco-core` del CI (no en local sin Docker). La integración de
prueba `banco_flujos` vive en `tests/banco/ha_config/custom_components/` y se
carga con `banco_flujos:` en `configuration.yaml`. Qué comprueba:

- A: el descubrimiento de `banco_flujos` aparece en
  `ha_list_discovered_integrations`; `ha_ignore_discovery` crea la entrada
  `ignore` (el lector la ve) y la limpieza la borra; `ha_list_config_flow_domains`
  incluye `banco_flujos` y, con `type="helper"`, `template`;
  `ha_update_config_entry` cambia el título sin token y desactiva el sondeo en
  dos pasos (el lector ve las preferencias).
- B: subentry `elemento` creada por su flujo (el lector la ve con su sensor),
  reconfigurada, renombrada y borrada en dos pasos (el lector ya no ve la
  subentry ni el sensor); flujo de subentry abierto y abortado; reconfigure de
  la entrada.
- C: el aviso reparable de `banco_flujos` sale en `ha_list_repairs` con
  `title` y `description` traducidos; `ha_get_repair` con sus datos;
  `ha_start_repair_fix` → `ha_continue_repair_fix` (vista previa, el lector ve
  que el aviso sigue; confirmación, el lector ya no lo ve); otro flujo abierto
  y abortado (el aviso sigue); reautenticación de una entrada (servicio
  `banco_flujos.pedir_reauth`) por `ha_continue_config_entry_flow`, con la
  vista previa sin cambios y el token aplicándola (decisión del supervisor).

`tests/test_banco_cobertura_escrituras.py` (suite normal) falla si alguna de
las doce tools nuevas que modifican no está en `tests/banco/cobertura_016.py`.

## Comprobaciones manuales (después de publicar; a la matriz de la 014)

- Ignorar un descubrimiento real (por ejemplo, un dispositivo de la red) y
  dejar de ignorarlo con `ha_delete_config_entry`.
- Subentries de una integración real que las use (por ejemplo, un agente de
  conversación con varios modelos).
- Un flujo de reparación real de varias integraciones, incluido uno del
  Supervisor (que puede terminar al abrirse) y uno con varios pasos.
- Textos traducidos en un idioma distinto del inglés.
- Una reautenticación real (por ejemplo, tras cambiar la contraseña de un
  servicio) por `ha_continue_config_entry_flow`, con token.
