"""Estimación de la retención de los backups automáticos (spec 031, FR-003, T002).

`estimar_retencion` reproduce las dos reglas de borrado de la integración
`backup` de Home Assistant Core 2026.11.1 (`homeassistant/components/backup/
config.py`):

- por copias: `delete_backups_exceeding_configured_count`, que HA ejecuta
  DESPUÉS de crear un backup automático (el nuevo ya cuenta);
- por días: `RetentionConfig._schedule_next` → `_delete_backups`, que HA
  programa un día después de aplicar la retención.

Las dos solo miran los backups con `with_automatic_settings` (el
`_automatic_backups_filter` de HA) y, si algún agente tiene retención propia,
deciden por (backup, agente). Los casos de abajo están copiados de esas ramas.

Control negativo (T015 a), comprobado: sin el filtro de
`with_automatic_settings` cae `test_solo_automaticos` (1 de 14); contando
`copies` en vez de `copies - 1` en la rama global caen `test_copias_globales`,
`test_las_dos_reglas_una_vez_con_within_24h` y `test_solo_automaticos` (3 de
14).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any

from hermes.backup_retention_estimate import estimar_retencion

_AHORA = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


def _b(bid: str, dia: int, agentes: tuple[str, ...] = ("hassio.local",),
       automatico: bool = True, fecha: str | None = None) -> dict[str, Any]:
    return {
        "backup_id": bid,
        "name": f"Automatic backup {bid}",
        "date": fecha if fecha is not None else f"2026-11-{dia:02d}T04:30:00+00:00",
        "agents": {a: {"protected": True, "size": 10} for a in agentes},
        "with_automatic_settings": automatico,
    }


def _config(copies: int | None = None, days: int | None = None,
            agentes: dict[str, Any] | None = None,
            agent_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "retention": {"copies": copies, "days": days},
        "agents": agentes or {},
        "create_backup": {"agent_ids": agent_ids if agent_ids is not None
                          else ["hassio.local", "hassio.nas_backups"]},
    }


def _ids(estimacion: list[dict[str, Any]]) -> list[str]:
    return [e["backup_id"] for e in estimacion]


class TestReglasGlobales(unittest.TestCase):
    def test_sin_retencion_no_borra_nada(self) -> None:
        backups = [_b(f"b{i}", i) for i in range(1, 6)]
        self.assertEqual(estimar_retencion(_config(), backups, _AHORA), [])

    def test_copias_globales(self) -> None:
        # Cinco automáticos y `copies=3`: tras el próximo automático habrá
        # seis; HA deja los tres más recientes, así que se borran los tres
        # más antiguos de los que hay ahora (los `copies - 1` más recientes
        # se quedan).
        backups = [_b(f"b{i}", i) for i in (5, 1, 3, 2, 4)]
        estimacion = estimar_retencion(_config(copies=3), backups, _AHORA)
        self.assertEqual(_ids(estimacion), ["b1", "b2", "b3"])
        self.assertTrue(all(e["when"] == "after_next_automatic_backup" for e in estimacion))
        self.assertEqual(estimacion[0], {
            "backup_id": "b1", "name": "Automatic backup b1",
            "date": "2026-11-01T04:30:00+00:00", "agents": ["hassio.local"],
            "when": "after_next_automatic_backup",
        })

    def test_copias_que_sobran_no_borran(self) -> None:
        backups = [_b("b1", 1), _b("b2", 2)]
        self.assertEqual(estimar_retencion(_config(copies=3), backups, _AHORA), [])

    def test_solo_automaticos(self) -> None:
        # Un backup manual (sin `with_automatic_settings`) ni cuenta ni se
        # borra: HA filtra antes con `_automatic_backups_filter`.
        backups = [_b("manual", 1, automatico=False), _b("b2", 2), _b("b3", 3)]
        self.assertEqual(_ids(estimar_retencion(_config(copies=2), backups, _AHORA)), ["b2"])
        backups = [_b("manual", 1, automatico=False)]
        self.assertEqual(estimar_retencion(_config(days=1), backups, _AHORA), [])

    def test_dias_globales(self) -> None:
        # `days=7` con «ahora» el 15 a las 12:00: se borran los de antes del
        # 8 a las 12:00 (fecha + días < ahora, estricto como en HA).
        backups = [_b(f"b{i}", i) for i in (1, 7, 8, 14)]
        estimacion = estimar_retencion(_config(days=7), backups, _AHORA)
        self.assertEqual(_ids(estimacion), ["b1", "b7", "b8"])
        self.assertTrue(all(e["when"] == "within_24h" for e in estimacion))

    def test_las_dos_reglas_una_vez_con_within_24h(self) -> None:
        backups = [_b(f"b{i}", i) for i in (1, 2, 13, 14)]
        estimacion = estimar_retencion(_config(copies=2, days=7), backups, _AHORA)
        # b1 y b2 salen por días y por copias; b13 solo por copias.
        self.assertEqual(_ids(estimacion), ["b1", "b2", "b13"])
        self.assertEqual([e["when"] for e in estimacion],
                         ["within_24h", "within_24h", "after_next_automatic_backup"])

    def test_fechas_ilegibles_no_se_estiman(self) -> None:
        # Fail-closed: sin fecha legible no se puede decir si se borraría.
        backups = [_b("raro", 1, fecha="ayer"), _b("nulo", 1, fecha=""),
                   _b("b2", 2), _b("b3", 3)]
        backups[1]["date"] = None
        estimacion = estimar_retencion(_config(copies=1, days=1), backups, _AHORA)
        self.assertNotIn("raro", _ids(estimacion))
        self.assertNotIn("nulo", _ids(estimacion))
        self.assertEqual(_ids(estimacion), ["b2", "b3"])

    def test_orden_por_fecha(self) -> None:
        backups = [_b(f"b{i}", i) for i in (9, 3, 6)]
        self.assertEqual(_ids(estimar_retencion(_config(days=1), backups, _AHORA)),
                         ["b3", "b6", "b9"])


class TestRetencionPorAgente(unittest.TestCase):
    def test_agente_sustituye_a_la_global(self) -> None:
        # El NAS guarda 1 copia; el local, la global (3). Con cuatro
        # automáticos en los dos: en el NAS se borran los cuatro de ahora
        # (queda solo el nuevo); en local, los dos más antiguos.
        agentes = ("hassio.local", "hassio.nas_backups")
        backups = [_b(f"b{i}", i, agentes) for i in (1, 2, 3, 4)]
        config = _config(copies=3, agentes={
            "hassio.nas_backups": {"protected": True, "retention": {"copies": 1, "days": None}},
        })
        estimacion = estimar_retencion(config, backups, _AHORA)
        por_id = {e["backup_id"]: e["agents"] for e in estimacion}
        self.assertEqual(por_id, {
            "b1": ["hassio.local", "hassio.nas_backups"],
            "b2": ["hassio.local", "hassio.nas_backups"],
            "b3": ["hassio.nas_backups"],
            "b4": ["hassio.nas_backups"],
        })

    def test_copias_por_agente(self) -> None:
        backups = [_b(f"b{i}", i, ("hassio.nas_backups",)) for i in (1, 2, 3)]
        config = _config(agentes={
            "hassio.nas_backups": {"protected": True, "retention": {"copies": 2, "days": None}},
        })
        self.assertEqual(_ids(estimar_retencion(config, backups, _AHORA)), ["b1", "b2"])

    def test_agente_que_no_recibe_el_automatico(self) -> None:
        # Si el agente no está en `create_backup.agent_ids`, el próximo
        # automático no le llega: no cuenta uno de más en él.
        backups = [_b(f"b{i}", i, ("cloud.cloud",)) for i in (1, 2, 3)]
        config = _config(agent_ids=["hassio.local"], agentes={
            "cloud.cloud": {"protected": True, "retention": {"copies": 2, "days": None}},
        })
        self.assertEqual(_ids(estimar_retencion(config, backups, _AHORA)), ["b1"])

    def test_dias_none_en_el_agente_no_borra_por_dias(self) -> None:
        agentes = ("hassio.local", "hassio.nas_backups")
        backups = [_b("b1", 1, agentes)]
        config = _config(days=3, agentes={
            "hassio.nas_backups": {"protected": True, "retention": {"copies": None, "days": None}},
        })
        estimacion = estimar_retencion(config, backups, _AHORA)
        self.assertEqual(estimacion[0]["agents"], ["hassio.local"])
        self.assertEqual(estimacion[0]["when"], "within_24h")

    def test_dias_del_agente_sin_global(self) -> None:
        backups = [_b("b1", 1, ("hassio.local", "cloud.cloud")), _b("b14", 14, ("cloud.cloud",))]
        config = _config(agentes={
            "cloud.cloud": {"protected": True, "retention": {"copies": None, "days": 5}},
        })
        estimacion = estimar_retencion(config, backups, _AHORA)
        self.assertEqual(estimacion, [{
            "backup_id": "b1", "name": "Automatic backup b1",
            "date": "2026-11-01T04:30:00+00:00", "agents": ["cloud.cloud"],
            "when": "within_24h",
        }])

    def test_agente_con_retencion_en_blanco_guarda_para_siempre(self) -> None:
        # Retención propia con los dos a None: ese agente no borra nada, ni
        # por la global.
        backups = [_b(f"b{i}", i, ("hassio.nas_backups",)) for i in (1, 2, 3)]
        config = _config(copies=1, days=1, agentes={
            "hassio.nas_backups": {"protected": True, "retention": {"copies": None, "days": None}},
        })
        self.assertEqual(estimar_retencion(config, backups, _AHORA), [])


if __name__ == "__main__":
    unittest.main()
