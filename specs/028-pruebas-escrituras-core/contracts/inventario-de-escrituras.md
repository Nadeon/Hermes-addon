# Contrato: inventario de escrituras y su invariante (spec 028, FR-003, FR-004)

Es el contrato entre el banco y el resto del programa: qué tiene que hacer
quien añade una tool que modifica para que el CI siga en verde.

## Módulo `tests/banco/cobertura_escrituras.py`

```python
PROBADAS_028: frozenset[str]          # se ejecutan en tests/banco/test_banco_escrituras_*.py
NO_EJECUTABLES_028: dict[str, str]    # ha_* → motivo concreto; vacío hoy
FUERA_DEL_BANCO: dict[str, str]       # fs_* y sv_* → motivo
PENDIENTES_TRAMO_B: dict[str, str]    # solo entre tramos; el tramo B lo borra
```

Docstring con el invariante y con la regla para las sub-features siguientes
(sección de abajo). Comentarios en español con el porqué de cada motivo.

## Test `tests/test_banco_cobertura_escrituras.py` (suite normal)

Sin HA ni Docker; corre en Windows y en Linux.

| Test | Comprueba | Falla nombrando |
|---|---|---|
| `test_todas_las_escrituras_clasificadas` | `modifican(registro) == unión de todas las listas` (data-model) | las que sobran y las que faltan, y el fichero a tocar |
| `test_listas_disjuntas` | ninguna tool en dos listas | las repetidas y en qué listas |
| `test_fuera_del_banco_solo_fs_y_sv` | `FUERA_DEL_BANCO` no tiene `ha_*` ni otros prefijos | las que no son `fs_*`/`sv_*` |
| `test_motivos_no_vacios` | `NO_EJECUTABLES_028`, `FUERA_DEL_BANCO` y `PENDIENTES_TRAMO_B` sin motivos vacíos | las que no tienen motivo |
| `test_recuento_028` | las listas de la 028 suman 53 | el recuento real |
| `test_cada_probada_aparece_en_un_test_del_banco` | cada nombre de `PROBADAS_028` está entre comillas en algún `tests/banco/test_banco_escrituras_*.py` | las ausentes |

Definiciones:

- `modifican(registro)`: nombres de `_build_mcp(HermesConfig(call_service_auto_classify_dangerous=False), MagicMock())._tool_manager.list_tools()`
  con `classify(nombre).read_only_hint` falso (`hermes.tools._annotations`).
  Desactivar la clasificación automática solo evita una tarea en segundo plano
  en un test síncrono; no cambia qué tools se registran (lo mismo hace la 010).
- La lista de la 010 se importa de `tests/banco/cobertura.py` sin modificarla.

## Regla para las sub-features siguientes

Una sub-feature que añade una tool que modifica:

1. Si es de Core, la ejecuta en el banco (FR-015 de la 008) y la pone en su
   propia lista de probadas, en su propio módulo `tests/banco/cobertura_<NNN>.py`.
2. Si no se puede ejecutar en el banco, la pone en su lista de no ejecutables
   con motivo concreto; si es `sv_*` o `fs_*`, en `FUERA_DEL_BANCO`.
3. Suma su lista a la unión de `test_todas_las_escrituras_clasificadas` (una
   línea) y a `test_listas_disjuntas`.

Si no lo hace, este test cae en su rama nombrando la tool.

## Tests del banco de la 028 (`tests/banco/test_banco_escrituras_*.py`)

- `pytestmark = pytest.mark.banco`; cada clase llama a `exigir_banco()` en
  `setUpClass` (la base de la 010 ya lo hace).
- Un `async with` por test con el lector y Hermes conectado (patrón de
  `tests/banco/base_helpers.py`); lo que se crea se apunta y se limpia con el
  lector al cerrar, pase lo que pase.
- Tools con token: primera llamada → vista previa con `confirmation_token`; el
  lector comprueba que HA no cambió; segunda llamada con el token → efecto.
- Fallo contra HA real: `@pytest.mark.xfail(strict=True, raises=…, reason=…)`
  y comentario `HALLAZGO` (research R-6).
