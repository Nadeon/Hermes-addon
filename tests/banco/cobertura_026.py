"""Inventario de las escrituras de la spec 026 en el banco de Core.

Contrato de la 028 («Regla para las sub-features siguientes»): cada tool
nueva que modifica se ejecuta en el banco y va en `PROBADAS_026`, o en
`NO_EJECUTABLES_026` con un motivo concreto. Las dos listas se suman a la
unión de `tests/test_banco_cobertura_escrituras.py` y `PROBADAS_026` a lo que
el job exige por ejecución (`cobertura_escrituras.TOOLS_EXIGIDAS_DEL_JOB`).

Tramo 1 (familia `marketplace_manage`): `ha_marketplace_acknowledge_critical`
se ejecuta en `tests/banco/test_banco_marketplace.py` contra un aviso crítico
sembrado en el storage del banco (`ha_config/.storage/marketplace.critical`),
con el efecto leído por el lector (`marketplace/critical/list`). Las otras
tres necesitan un repositorio en la lista del Marketplace, y el banco no la
tiene: van a `NO_EJECUTABLES_026`. Su carga exacta sí se envía a HA real en
el test de contrato del mismo fichero (HA la acepta y responde un error del
manejador, nunca `invalid_format` ni `unknown_command`).

Tramo 2 (misma familia, decisión D-2): `ha_marketplace_uninstall` necesita
un repositorio INSTALADO desde el Marketplace, y sin catálogo no se puede
instalar ninguno (ni Hermes puede: instalar exige el aviso de riesgos): va a
`NO_EJECUTABLES_026`. Su carga se envía a HA real en el mismo test de
contrato, y el backup previo, que es del Supervisor (simulado en el banco),
se prueba con el Supervisor simulado de la suite normal.

Añadir, instalar, fijar versión y mostrar betas no tienen tool (DESVIACIÓN
DV-1 de la 026): HA exige el aviso de riesgos aceptado por el usuario de
Hermes, que no puede aceptarlo.
"""

from __future__ import annotations

MODULOS_026: tuple[str, ...] = ("marketplace_manage",)

PROBADAS_026: frozenset[str] = frozenset({
    "ha_marketplace_acknowledge_critical",
})

_SIN_CATALOGO = (
    "Marketplace: el banco no tiene internet, así que el Marketplace no "
    "descarga el catálogo y su lista de repositorios está vacía; no hay ningún "
    "repositorio sobre el que actuar (HA respondería repository_not_found). Se "
    "prueba con HA simulado con la forma de 2026.11.1 en la suite normal, y su "
    "carga exacta contra HA real en el test de contrato del banco "
    "(tests/banco/test_banco_marketplace.py)"
)

NO_EJECUTABLES_026: dict[str, str] = {
    "ha_marketplace_ignore_repository": _SIN_CATALOGO,
    "ha_marketplace_remove_repository": _SIN_CATALOGO,
    "ha_marketplace_refresh_repository": _SIN_CATALOGO,
    "ha_marketplace_uninstall": (
        _SIN_CATALOGO + "; además, desinstalar necesita uno instalado desde el "
        "Marketplace, y sin catálogo no se puede instalar ninguno (instalar exige "
        "también el aviso de riesgos, que el usuario de Hermes no puede aceptar)"
    ),
}
