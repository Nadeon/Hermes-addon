"""Inventario de cobertura del banco de la spec 023 (Assist y conversación).

Lo suma el invariante de escrituras (`tests/test_banco_cobertura_escrituras.py`)
y lo descubre la matriz de la 014 (`tests/test_matriz_pruebas.py`) por la
convención de nombres.

`ha_process_conversation` es la única tool de la 023 que modifica. Está en
`PROBADAS_023`: se ejecuta en el banco (`tests/banco/test_banco_conversacion.py`)
contra el agente integrado de HA Core real, con una automatización de
disparador de frase que crea el propio test, y el lector independiente ve su
efecto; el plugin del job (`tests/banco/obligatorio.py`) exige que se llame
con éxito (lo suma `cobertura_escrituras.TOOLS_EXIGIDAS_DEL_JOB`). El camino
«otro agente» (un LLM) solo se prueba en unitarios: el banco no tiene ninguno.

Las tres de lectura (`LECTURAS_023`) también se exigen por ejecución, como las
de la 029: las llama el mismo test con éxito.

`XFAIL_PERMITIDOS_023` está vacío: ningún comando de Assist falló en el banco.
Un fallo real de HA sería un hallazgo, con su `xfail` estricto aquí.

Control negativo (T016 f): sacar `ha_process_conversation` de `PROBADAS_023`
hace caer `test_todas_las_escrituras_clasificadas` nombrándola.
"""

from __future__ import annotations

PROBADAS_023: frozenset[str] = frozenset({"ha_process_conversation"})

NO_EJECUTABLES_023: dict[str, str] = {}

LECTURAS_023: frozenset[str] = frozenset({
    "ha_list_conversation_agents",
    "ha_list_conversation_sentences",
    "ha_debug_conversation",
})

XFAIL_PERMITIDOS_023: dict[str, str] = {}
