"""Invariante de las escrituras en el banco de Core (spec 028, FR-003, FR-004).

Suite normal (no necesita HA): TODA tool que modifica del registro de
producción está en una de estas listas, sin solaparse: probada en el banco por
la 010 (helpers), hallazgo de la 010 que falla contra HA real
(`FALLAN_EN_BANCO`), probada en el banco por la 028, no ejecutable con su
motivo, o fuera del banco (`fs_*` y `sv_*`) con su motivo. Una tool nueva que modifica
y no está en ninguna hace caer `test_todas_las_escrituras_clasificadas`, que la
nombra. Contrato: `specs/028-pruebas-escrituras-core/contracts/`.

Control negativo (T008, anotado en el commit del tramo A): quitar
`ha_fire_event` de `PROBADAS_028` hace caer
`test_todas_las_escrituras_clasificadas` nombrándola; moverla a
`FUERA_DEL_BANCO` hace caer `test_fuera_del_banco_solo_fs_y_sv`; vaciar el
motivo de `sv_reboot_host` hace caer `test_motivos_no_vacios`; poner
`ha_get_state` en `PROBADAS_028` hace caer el primero («declaradas que no
modifican»).

Control negativo del cierre (T022, tramo B): quitar `ha_ignore_repair` de
`PROBADAS_028` hace caer `test_todas_las_escrituras_clasificadas`
nombrándola (y `test_recuento_028`: 52).

Desde la convergencia (T030) ya no hay comprobación textual («el nombre de la
tool aparece en un fichero del banco»): la sustituye la de EJECUCIÓN de la 010
(`tests/banco/obligatorio.py`), a la que la 028 suma `PROBADAS_028` en
`TOOLS_EXIGIDAS_DEL_JOB`. Aquí se comprueba que la suma está hecha y que los
`xfail` de hallazgos de la 028 están bien formados.
"""

from __future__ import annotations

import importlib
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from tests.banco import cobertura, cobertura_012 as c012, cobertura_015 as c015
from tests.banco import cobertura_016 as c016
from tests.banco import cobertura_017 as c017
from tests.banco import cobertura_020 as c020
from tests.banco import cobertura_021 as c021
from tests.banco import cobertura_023 as c023
from tests.banco import cobertura_031 as c031
from tests.banco import cobertura_024 as c024
from tests.banco.cobertura_024 import LECTURAS_EN_BANCO_024
from tests.banco import cobertura_026 as c026
from tests.banco import cobertura_escrituras as c028

RAIZ = Path(__file__).resolve().parent.parent


def _modifican() -> set[str]:
    """Tools del registro de producción sin `readOnlyHint` (research R-0)."""
    from hermes.__main__ import _build_mcp
    from hermes.config import HermesConfig
    from hermes.tools._annotations import classify

    # Sin la clasificación automática de `ha_call_service`: al registrarse
    # programa una tarea en el bucle, y este test es síncrono. No cambia qué
    # tools se registran (igual que en la 010).
    mcp = _build_mcp(HermesConfig(call_service_auto_classify_dangerous=False), MagicMock())
    return {
        t.name for t in mcp._tool_manager.list_tools() if not classify(t.name).read_only_hint
    }


def _listas() -> dict[str, set[str]]:
    """Cada lista del inventario con su nombre, para los mensajes de fallo."""
    return {
        "cobertura.PROBADAS_EN_BANCO (010)": set(cobertura.PROBADAS_EN_BANCO),
        "cobertura.NO_EJECUTABLES (010)": set(cobertura.NO_EJECUTABLES),
        "cobertura.FALLAN_EN_BANCO (010)": set(cobertura.FALLAN_EN_BANCO),
        "cobertura.PROBADAS_GENERICAS (011)": set(cobertura.PROBADAS_GENERICAS),
        "cobertura.NO_EJECUTABLES_GENERICAS (011)": set(cobertura.NO_EJECUTABLES_GENERICAS),
        "PROBADAS_028": set(c028.PROBADAS_028),
        "NO_EJECUTABLES_028": set(c028.NO_EJECUTABLES_028),
        "FUERA_DEL_BANCO": set(c028.FUERA_DEL_BANCO),
        # Spec 012 (contrato de la 028): sus escrituras, en su propio módulo.
        "PROBADAS_012": set(c012.PROBADAS_012),
        "NO_EJECUTABLES_012": set(c012.NO_EJECUTABLES_012),
        # Spec 016: sus escrituras, en su propio módulo.
        "PROBADAS_016": set(c016.PROBADAS_016),
        "NO_EJECUTABLES_016": set(c016.NO_EJECUTABLES_016),
        # Spec 015: sus escrituras, en su propio módulo.
        "PROBADAS_015": set(c015.PROBADAS_015),
        "NO_EJECUTABLES_015": set(c015.NO_EJECUTABLES_015),
        # Spec 017 (contrato de la 028): blueprints.
        "PROBADAS_017": set(c017.PROBADAS_017),
        "NO_EJECUTABLES_017": set(c017.NO_EJECUTABLES_017),
        # Spec 020 (contrato de la 028): mantenimiento de estadísticas.
        "PROBADAS_020": set(c020.PROBADAS_020),
        "NO_EJECUTABLES_020": set(c020.NO_EJECUTABLES_020),
        # Spec 021: sus escrituras, en su propio módulo.
        "PROBADAS_021": set(c021.PROBADAS_021),
        "NO_EJECUTABLES_021": set(c021.NO_EJECUTABLES_021),
        # Spec 023: su escritura, en su propio módulo.
        "PROBADAS_023": set(c023.PROBADAS_023),
        "NO_EJECUTABLES_023": set(c023.NO_EJECUTABLES_023),
        # Spec 031: agentes y ajustes de los backups de HA (tramo 1).
        "PROBADAS_031": set(c031.PROBADAS_031),
        "NO_EJECUTABLES_031": set(c031.NO_EJECUTABLES_031),
        # Spec 024 (contrato de la 028): restablecer un dashboard.
        "PROBADAS_024": set(c024.PROBADAS_024),
        "NO_EJECUTABLES_024": set(c024.NO_EJECUTABLES_024),
        # Spec 026 (contrato de la 028): mantenimiento del Marketplace.
        "PROBADAS_026": set(c026.PROBADAS_026),
        "NO_EJECUTABLES_026": set(c026.NO_EJECUTABLES_026),
    }


class TestInventarioDeEscrituras(unittest.TestCase):
    def test_todas_las_escrituras_clasificadas(self) -> None:
        reales = _modifican()
        declaradas: set[str] = set().union(*_listas().values())
        sin_clasificar = sorted(reales - declaradas)
        no_modifican = sorted(declaradas - reales)
        self.assertFalse(
            sin_clasificar or no_modifican,
            "inventario de escrituras desalineado (tests/banco/cobertura_escrituras.py "
            "o el módulo de cobertura de su sub-feature): tools que modifican sin "
            f"clasificar: {sin_clasificar}; declaradas que no modifican o no existen: "
            f"{no_modifican}",
        )
        # Las 124 de la 1.1.2, las 2 genéricas de escritura de la 011, las
        # 3 de la 012 (2 de logs del tramo A y el descarte de notificaciones
        # del tramo B), las 5 de la 015 (`sv_check_for_updates` y
        # `sv_update_core` del tramo 1, `sv_update_os` y `sv_update_supervisor`
        # del 2 y `ha_install_update` del 3), las 12 de la 016 (2 del tramo A,
        # 7 del B y 3 del C), las 7 de la 019 (5 de montajes y 2 de ajustes
        # de backup) y las 5 de la 030 (4 de repositorios de la tienda del
        # tramo 1 y `sv_rebuild_addon` del tramo 2), y las 3 de la 017 (guardar
        # y borrar blueprints del tramo A e importar del tramo B), y las 6 de la
        # 020 (5 de estadísticas de los tramos 1 y 2 y la de energía del 3), y
        # las 8 de la 022 (7 de control de Core y del Supervisor del tramo 1 y
        # la de aplicar sugerencias del tramo 2), y las 9 de la 021 (3 del
        # tramo a, núcleo y exposición; 3 del b, usuarios; y 3 del c, red y
        # HTTP), y las 7 de la 032 (4 del tramo 1, control del host, y 3 del
        # tramo 2, red del host), y la de la 023 (`ha_process_conversation`),
        # y las 5 de la 031 (tramo 1: `ha_update_backup_config`; tramo 2:
        # crear, crear con los ajustes automáticos y borrar; tramo 3:
        # restaurar, no ejecutable), y la de la 024 (restablecer un dashboard,
        # tramo 2), y las 5 de la 026 (las 4 de mantenimiento del Marketplace
        # del tramo 1 y desinstalar del tramo 2).
        self.assertEqual(len(reales), 203)

    def test_listas_disjuntas(self) -> None:
        listas = _listas()
        nombres = list(listas)
        repetidas = []
        for i, a in enumerate(nombres):
            for b in nombres[i + 1:]:
                comunes = sorted(listas[a] & listas[b])
                if comunes:
                    repetidas.append(f"{comunes} en {a} y {b}")
        self.assertFalse(repetidas, f"tools en dos listas a la vez: {repetidas}")

    def test_fuera_del_banco_solo_fs_y_sv(self) -> None:
        otras = sorted(t for t in c028.FUERA_DEL_BANCO if not t.startswith(("fs_", "sv_")))
        self.assertFalse(
            otras,
            "FUERA_DEL_BANCO solo admite fs_* y sv_*; una ha_* que no se pueda "
            f"ejecutar va a NO_EJECUTABLES_028 con un motivo concreto: {otras}",
        )

    def test_motivos_no_vacios(self) -> None:
        sin_motivo = sorted(
            f"{nombre}: {tool}"
            for nombre, lista in (
                ("NO_EJECUTABLES_028", c028.NO_EJECUTABLES_028),
                ("NO_EJECUTABLES_012", c012.NO_EJECUTABLES_012),
                ("NO_EJECUTABLES_017", c017.NO_EJECUTABLES_017),
                ("NO_EJECUTABLES_021", c021.NO_EJECUTABLES_021),
                ("NO_EJECUTABLES_031", c031.NO_EJECUTABLES_031),
                ("NO_EJECUTABLES_024", c024.NO_EJECUTABLES_024),
                ("FUERA_DEL_BANCO", c028.FUERA_DEL_BANCO),
                ("NO_EJECUTABLES_016", c016.NO_EJECUTABLES_016),
                ("NO_EJECUTABLES_015", c015.NO_EJECUTABLES_015),
                ("NO_EJECUTABLES_023", c023.NO_EJECUTABLES_023),
            )
            for tool, motivo in lista.items()
            if not str(motivo).strip()
        )
        self.assertFalse(sin_motivo, f"tools sin motivo: {sin_motivo}")

    def test_recuento_028(self) -> None:
        total = len(c028.PROBADAS_028) + len(c028.NO_EJECUTABLES_028)
        self.assertEqual(total, 53, f"las listas de la 028 suman {total}, no 53")
        # 24 de la 1.1.2, 7 de la 019 (5 de montajes y 2 de ajustes) y 5 de
        # la 030: las cuatro de repositorios de la tienda (`_SV_TIENDA`) y
        # `sv_rebuild_addon` (`_SV_APPS_TIENDA`), FR-022 de la 030, y 8 de la
        # 022: 7 del tramo 1 (control de Core y del Supervisor) y 1 del tramo 2
        # (aplicar sugerencias), y 7 de la 032: 4 del control del host
        # (`_SV_HOST`) y 3 de la red del host (`_SV_RED`).
        self.assertEqual(len(c028.FUERA_DEL_BANCO), 51)

    def test_el_job_exige_por_ejecucion_las_probadas_de_la_028(self) -> None:
        # El plugin del job (010) solo exige lo que le pasa el conftest. Si la
        # 028 no sumara su lista, sus 53 tools podrían dejar de ejecutarse sin
        # que nada se pusiera en rojo.
        from tests.banco import obligatorio

        self.assertEqual(
            c028.TOOLS_EXIGIDAS_DEL_JOB,
            cobertura.PROBADAS_EN_BANCO | cobertura.PROBADAS_GENERICAS | c028.PROBADAS_028
            | cobertura.PROBADAS_EN_BANCO_029 | c012.PROBADAS_012 | c015.PROBADAS_015
            | c016.PROBADAS_016 | c017.PROBADAS_017 | c020.PROBADAS_020
            | c020.LECTURAS_020 | c021.PROBADAS_021 | c021.LECTURAS_021
            | c021.VISTA_PREVIA_021 | c023.PROBADAS_023 | c023.LECTURAS_023
            | c031.PROBADAS_031 | c031.LECTURAS_EN_BANCO_031
            # Spec 024: las dos de imagen leen, pero se exigen por ejecución;
            # restablecer un dashboard modifica.
            | LECTURAS_EN_BANCO_024 | c024.PROBADAS_024
            # Spec 026: reconocer el aviso crítico sembrado.
            | c026.PROBADAS_026,
        )
        self.assertEqual(
            c028.XFAIL_DEL_JOB, {**cobertura.XFAIL_PERMITIDOS, **c028.XFAIL_PERMITIDOS_028,
                                 **c023.XFAIL_PERMITIDOS_023, **c031.XFAIL_PERMITIDOS_031}
        )
        conftest = (RAIZ / "tests" / "banco" / "conftest.py").read_text(encoding="utf-8")
        self.assertIn("tools_exigidas=TOOLS_EXIGIDAS_DEL_JOB", conftest)
        self.assertIn("xfail_permitidos=XFAIL_DEL_JOB", conftest)
        # Y el plugin nombra la tool que falta, sin decir que es de la 010.
        plugin = obligatorio.ComprobacionDelJob(
            carpeta=RAIZ / "tests" / "banco",
            xfail_permitidos=c028.XFAIL_DEL_JOB,
            tools_exigidas=c028.TOOLS_EXIGIDAS_DEL_JOB,
            tomar_tools_del_test=set,
        )
        plugin.xfail_vistos = set(c028.XFAIL_DEL_JOB)
        plugin.tools_probadas = set(c028.TOOLS_EXIGIDAS_DEL_JOB) - {"ha_fire_event"}
        self.assertEqual(len(plugin.calcular_problemas()), 1)
        self.assertIn("['ha_fire_event']", plugin.calcular_problemas()[0])
        self.assertIn("PROBADAS_028", plugin.calcular_problemas()[0])

    def test_hallazgos_de_la_028_con_su_xfail(self) -> None:
        # Como el T038 de la 010: cada hallazgo tiene su xfail en la lista del
        # job y cada xfail de la lista documenta un hallazgo, apunta a un test
        # que existe, es estricto, espera una excepción concreta y dice
        # HALLAZGO. La tool sigue en PROBADAS_028: su camino normal funciona.
        self.assertEqual(set(c028.XFAIL_PERMITIDOS_028.values()), set(c028.HALLAZGOS_028))
        self.assertLessEqual(set(c028.HALLAZGOS_028), set(c028.PROBADAS_028))
        for tool, motivo in c028.HALLAZGOS_028.items():
            self.assertIn("HALLAZGO", motivo, tool)
            self.assertIn("spec 033", motivo, tool)
        for nodeid in c028.XFAIL_PERMITIDOS_028:
            ruta, clase, metodo = nodeid.split("::")
            self.assertTrue((RAIZ / ruta).is_file(), nodeid)
            modulo = importlib.import_module(ruta.removesuffix(".py").replace("/", "."))
            prueba = getattr(getattr(modulo, clase), metodo)
            marcas = [m for m in getattr(prueba, "pytestmark", []) if m.name == "xfail"]
            self.assertEqual(len(marcas), 1, nodeid)
            self.assertIs(marcas[0].kwargs.get("strict"), True, nodeid)
            self.assertIn("HALLAZGO", marcas[0].kwargs.get("reason", ""), nodeid)
            excepcion = marcas[0].kwargs.get("raises")
            self.assertNotIn(excepcion, (None, AssertionError, Exception, BaseException), nodeid)

    def test_031_sin_xfail_ni_tools_de_hassio(self) -> None:
        # El HALLAZGO del tramo 1 (el proxy WebSocket del Supervisor rechaza
        # `hassio/*` a las apps) se resolvió quitando las dos tools de
        # `hassio/update/config/*`: no queda ningún `xfail` de la 031 ni
        # ninguna de las dos en sus listas.
        self.assertEqual(c031.XFAIL_PERMITIDOS_031, {})
        quitadas = {"ha_get_update_backup_settings", "ha_set_update_backup_settings"}
        self.assertFalse(quitadas & (set(c031.PROBADAS_031) | set(c031.LECTURAS_EN_BANCO_031)
                                     | set(c031.NO_EJECUTABLES_031)))


if __name__ == "__main__":
    unittest.main()
