"""Estimación de lo que borraría la retención de los backups automáticos de HA.

Spec 031 (FR-003; data-model sección 4). Función pura: no habla con HA. La
usan las vistas previas que cambian la retención o crean un backup con los
ajustes automáticos, para decir QUÉ backups borraría Home Assistant y CUÁNDO.

POR QUÉ SE REPRODUCEN LAS REGLAS DE HA Y NO SE PREGUNTA A HA
-------------------------------------------------------------
HA no tiene ningún comando que diga qué borraría: aplica la retención por su
cuenta (por días, un día después de cambiarla; por copias, al terminar el
siguiente backup automático). Una vista previa que no dijera nada escondería
justo lo destructivo de cambiar la retención (principio IV). Por eso se copia
la lógica de `homeassistant/components/backup/config.py` de Core 2026.11.1:

- por copias, `delete_backups_exceeding_configured_count`;
- por días, el `_delete_filter` de `RetentionConfig._schedule_next`.

Se presenta siempre como ESTIMACIÓN: lo que pase hasta entonces (otro backup,
otro cambio de ajustes) cambia el resultado.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

# Cuándo borraría HA cada backup.
POR_DIAS = "within_24h"
POR_COPIAS = "after_next_automatic_backup"


def _fecha(valor: Any) -> datetime | None:
    """Fecha ISO de HA, o None si no se puede leer (o no lleva zona)."""
    if not isinstance(valor, str) or not valor:
        return None
    try:
        fecha = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    # Sin zona no se puede comparar con «ahora» sin inventarse una.
    return fecha if fecha.tzinfo is not None else None


def _agentes(backup: Mapping[str, Any]) -> list[str]:
    agentes = backup.get("agents")
    if isinstance(agentes, Mapping):
        return [a for a in agentes if isinstance(a, str)]
    if isinstance(agentes, list):
        return [a for a in agentes if isinstance(a, str)]
    return []


def _entero(valor: Any) -> int | None:
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


def estimar_retencion(
    config: Mapping[str, Any],
    backups: Iterable[Mapping[str, Any]],
    ahora: datetime,
) -> list[dict[str, Any]]:
    """Backups que la retención de `config` borraría, ordenados por fecha.

    `config` tiene la forma de la configuración por lista blanca de
    `tools/ha_backups.py` (`retention`, `agents.<id>.retention`,
    `create_backup.agent_ids`); `backups`, la de `_backup_permitido`
    (`backup_id`, `name`, `date`, `agents`, `with_automatic_settings`).

    Devuelve `[{backup_id, name, date, agents, when}]`, con `agents` los
    agentes de los que se borraría y `when` `within_24h` (por días) o
    `after_next_automatic_backup` (por copias). Un backup que sale por las dos
    reglas va una vez, con `within_24h`, que es lo que llega antes.
    """
    retencion = config.get("retention") if isinstance(config.get("retention"), Mapping) else {}
    copias_globales = _entero(retencion.get("copies"))
    dias_globales = _entero(retencion.get("days"))

    # Retención propia de cada agente. En HA, `AgentConfig.retention` es None
    # (usa la global) o un objeto, que es «verdadero» aunque sus dos campos
    # sean None: entonces ese agente guarda para siempre.
    retencion_agentes: dict[str, Mapping[str, Any] | None] = {}
    agentes_config = config.get("agents")
    if isinstance(agentes_config, Mapping):
        for agente, datos in agentes_config.items():
            if isinstance(datos, Mapping):
                r = datos.get("retention")
                retencion_agentes[str(agente)] = r if isinstance(r, Mapping) else None
    hay_retencion_agente = any(r is not None for r in retencion_agentes.values())

    # Regla de HA: solo los backups hechos con los ajustes automáticos
    # (`_automatic_backups_filter`). Los de fecha ilegible no se estiman: no
    # se puede decir dónde caen, y mejor no prometer un borrado (fail-closed).
    automaticos: list[tuple[Mapping[str, Any], datetime]] = []
    for b in backups:
        if not isinstance(b, Mapping) or b.get("with_automatic_settings") is not True:
            continue
        if not isinstance(b.get("backup_id"), str):
            continue
        fecha = _fecha(b.get("date"))
        if fecha is not None:
            automaticos.append((b, fecha))
    automaticos.sort(key=lambda par: par[1])

    por_dias = _por_dias(automaticos, dias_globales, retencion_agentes,
                         hay_retencion_agente, ahora)
    por_copias = _por_copias(automaticos, copias_globales, retencion_agentes,
                             hay_retencion_agente, config)

    salida: list[dict[str, Any]] = []
    for b, _fecha_b in automaticos:
        bid = b["backup_id"]
        if bid in por_dias:
            agentes = por_dias[bid] | por_copias.get(bid, set())
            cuando = POR_DIAS
        elif bid in por_copias:
            agentes = por_copias[bid]
            cuando = POR_COPIAS
        else:
            continue
        salida.append({
            "backup_id": bid,
            "name": b.get("name") if isinstance(b.get("name"), str) else None,
            "date": b.get("date"),
            "agents": sorted(agentes),
            "when": cuando,
        })
    return salida


def _por_dias(
    automaticos: list[tuple[Mapping[str, Any], datetime]],
    dias_globales: int | None,
    retencion_agentes: Mapping[str, Mapping[str, Any] | None],
    hay_retencion_agente: bool,
    ahora: datetime,
) -> dict[str, set[str]]:
    """El `_delete_filter` del borrado por días (backup → agentes)."""
    hay_dias_agente = any(
        r is not None and _entero(r.get("days")) is not None
        for r in retencion_agentes.values()
    )
    if dias_globales is None and not hay_dias_agente:
        return {}
    salida: dict[str, set[str]] = {}
    if dias_globales is not None and not hay_retencion_agente:
        # La rama corta de HA: el backup entero, de todos sus agentes.
        for b, fecha in automaticos:
            if fecha + timedelta(days=dias_globales) < ahora:
                salida[b["backup_id"]] = set(_agentes(b))
        return salida
    for b, fecha in automaticos:
        borrar: set[str] = set()
        for agente in _agentes(b):
            r = retencion_agentes.get(agente)
            if r is None:
                # Sin retención propia: la global, si la hay.
                if dias_globales is None:
                    continue
                dias = dias_globales
            elif (dias_agente := _entero(r.get("days"))) is None:
                # Retención propia sin días: ese agente no borra por días.
                continue
            else:
                dias = dias_agente
            if fecha + timedelta(days=dias) < ahora:
                borrar.add(agente)
        if borrar:
            salida[b["backup_id"]] = borrar
    return salida


def _por_copias(
    automaticos: list[tuple[Mapping[str, Any], datetime]],
    copias_globales: int | None,
    retencion_agentes: Mapping[str, Mapping[str, Any] | None],
    hay_retencion_agente: bool,
    config: Mapping[str, Any],
) -> dict[str, set[str]]:
    """`delete_backups_exceeding_configured_count` (backup → agentes).

    HA lo ejecuta al terminar el SIGUIENTE backup automático, cuando el nuevo
    ya cuenta. Por eso, de los que hay ahora, se quedan los `copies - 1` más
    recientes.
    """
    hay_copias_agente = any(
        r is not None and _entero(r.get("copies")) is not None
        for r in retencion_agentes.values()
    )
    if copias_globales is None and not hay_copias_agente:
        return {}
    if copias_globales is not None and not hay_retencion_agente:
        # La rama corta de HA: cuenta backups, no agentes; el nuevo suma uno.
        sobran = max(len(automaticos) + 1 - copias_globales, 0)
        return {b["backup_id"]: set(_agentes(b)) for b, _f in automaticos[:sobran]}

    # Por agente. El nuevo backup solo llega a los agentes de
    # `create_backup.agent_ids`; si no se sabe cuáles son, se supone que a
    # todos (estima borrar más, nunca menos).
    cb = config.get("create_backup") if isinstance(config.get("create_backup"), Mapping) else {}
    destinos = cb.get("agent_ids")
    destinos_conocidos = isinstance(destinos, list)

    por_agente: dict[str, list[str]] = {}
    for b, _f in automaticos:
        for agente in _agentes(b):
            por_agente.setdefault(agente, []).append(b["backup_id"])

    salida: dict[str, set[str]] = {}
    for agente, ids in por_agente.items():
        r = retencion_agentes.get(agente)
        if r is None:
            if copias_globales is None:
                continue
            copias = copias_globales
        elif (copias_agente := _entero(r.get("copies"))) is None:
            continue
        else:
            copias = copias_agente
        nuevo = 1 if (not destinos_conocidos or agente in destinos) else 0
        sobran = max(len(ids) + nuevo - copias, 0)
        for bid in ids[:sobran]:
            salida.setdefault(bid, set()).add(agente)
    return salida
