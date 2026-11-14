"""Guardas puras de la política de comandos (spec 011, FR-003, FR-004, FR-012;
T007).

Todo con tablas inyectadas: lo que se prueba aquí es la decisión, no cómo
quede clasificado un comando concreto en la tabla real (eso lo vigila
`test_command_table.py`). Las genéricas del tramo 2 solo aplican lo que
decide `decidir`; si esta función deja pasar algo, ninguna otra capa lo para.

Control negativo (T007/T016 e), anotado en el commit con los recuentos:
- `decidir` tratando `dedicated` como permitido → caen los de `dedicated`.
- sin la regla «gana el literal» en `casar_ruta` → cae el de precedencia.
- sin la guarda `core_proxy` en `validar_ruta` → caen los de `/core/api`.
"""

from __future__ import annotations

import unittest

from hermes import command_policy as cp
from hermes.command_policy import Entrada, Permitido, Rechazo


def _e(category: str, **kw) -> Entrada:
    kw.setdefault("reason", f"motivo {category}")
    kw.setdefault("family", "generic_commands")
    if category == "dedicated":
        kw.setdefault("tool", "ha_tool_ficticia")
    return Entrada(category=category, **kw)


_CORE = {
    "demo/list": _e("read", cap="CAP-066"),
    "demo/create": _e("confirm", cap="CAP-066"),
    "demo/secreto": _e("deny", reason="devuelve una clave (clase D)"),
    "demo/dedicada": _e("dedicated", tool="ha_get_demo", family="lovelace"),
}

_SV = {
    ("GET", "/addons/{app}/info"): _e("read"),
    ("GET", "/addons/self/info"): _e("deny", reason="literal"),
    ("POST", "/addons/{app}/restart"): _e("confirm"),
    ("GET", "/store/{a}/x"): _e("read"),
    ("GET", "/store/{b}/x"): _e("read"),
    ("GET", "/demo/{slug}"): _e("read"),
    ("GET", "/core/api/{path}"): _e("deny", reason="proxy"),
}


class TestBuscarCore(unittest.TestCase):
    def test_exacto(self) -> None:
        self.assertIs(cp.buscar_core("demo/list", tabla=_CORE), _CORE["demo/list"])

    def test_sin_prefijos_ni_mayusculas(self) -> None:
        for t in ("demo", "demo/lis", "demo/list/x", "DEMO/LIST", "Demo/list",
                  " demo/list", "demo/list "):
            with self.subTest(t=t):
                self.assertIsNone(cp.buscar_core(t, tabla=_CORE))

    def test_tabla_real_por_defecto(self) -> None:
        from hermes import command_table
        self.assertIs(cp.buscar_core("tag/list"), command_table.CORE_WS["tag/list"])


class TestCasarRuta(unittest.TestCase):
    def test_parametro(self) -> None:
        clave, entrada = cp.casar_ruta("GET", "/addons/core_ssh/info", tabla=_SV)
        self.assertEqual(clave, ("GET", "/addons/{app}/info"))
        self.assertIs(entrada, _SV[clave])
        self.assertEqual(cp.parametros(clave[1], "/addons/core_ssh/info"),
                         {"app": "core_ssh"})

    def test_gana_el_literal(self) -> None:
        clave, entrada = cp.casar_ruta("GET", "/addons/self/info", tabla=_SV)
        self.assertEqual(clave, ("GET", "/addons/self/info"))
        self.assertEqual(entrada.category, "deny")

    def test_empate_no_casa(self) -> None:
        self.assertIsNone(cp.casar_ruta("GET", "/store/algo/x", tabla=_SV))

    def test_metodo_distinto_no_casa(self) -> None:
        self.assertIsNone(cp.casar_ruta("POST", "/addons/core_ssh/info", tabla=_SV))
        self.assertIsNone(cp.casar_ruta("DELETE", "/addons/core_ssh/restart", tabla=_SV))

    def test_metodo_en_minusculas_se_normaliza(self) -> None:
        self.assertIsNotNone(cp.casar_ruta("get", "/demo/a", tabla=_SV))

    def test_parametros_que_no_casan(self) -> None:
        for seg in ("", ".", "..", "a" * 65, "con espacio", "a:b", "a%2e", "ñ",
                    "a+b", "a@b", "a~b"):
            with self.subTest(seg=seg):
                self.assertIsNone(cp.casar_ruta("GET", f"/demo/{seg}", tabla=_SV))

    def test_parametro_de_64_casa(self) -> None:
        self.assertIsNotNone(cp.casar_ruta("GET", "/demo/" + "a" * 64, tabla=_SV))
        self.assertIsNotNone(cp.casar_ruta("GET", "/demo/a.b-c_D9", tabla=_SV))

    def test_longitud_distinta_no_casa(self) -> None:
        self.assertIsNone(cp.casar_ruta("GET", "/demo", tabla=_SV))
        self.assertIsNone(cp.casar_ruta("GET", "/demo/a/b", tabla=_SV))


class TestValidarRuta(unittest.TestCase):
    def _regla(self, path: str) -> str | None:
        r = cp.validar_ruta(path)
        if r is None:
            return None
        self.assertIsInstance(r, Rechazo)
        self.assertEqual(r.codigo, "path_not_allowed")
        return r.campos["rule"]

    def test_validas(self) -> None:
        for p in ("/addons/core_ssh/info", "/dns/logs", "/store/addons/a.b-c_1"):
            with self.subTest(p=p):
                self.assertIsNone(cp.validar_ruta(p))

    def test_forma(self) -> None:
        for p in ("addons/x/info", "", "//addons/x", "/addons//x", "/addons/x/",
                  "/", "/addons\\x", "/addons/../host/reboot", "/addons/./x",
                  "/addons/%2e%2e/host", "/addons/%2E%2E/host", "/addons/x%20y",
                  "/addons/x?a=1", "/addons/x#f", "/addons/x\r\nHost: y",
                  "/addons/x\x00", "http://x/addons", "https://x/core/api"):
            with self.subTest(p=p):
                self.assertEqual(self._regla(p), "shape")

    def test_no_texto(self) -> None:
        self.assertEqual(self._regla(None), "shape")  # type: ignore[arg-type]

    def test_proxy_de_core(self) -> None:
        for p in ("/core/api", "/core/api/states", "/core/api/services/x/y",
                  "/homeassistant/api", "/homeassistant/api/x"):
            with self.subTest(p=p):
                self.assertEqual(self._regla(p), "core_proxy")

    def test_rutas_de_core_que_no_son_el_proxy(self) -> None:
        self.assertIsNone(cp.validar_ruta("/core/info"))
        self.assertIsNone(cp.validar_ruta("/core/logs/latest"))


def _es_hermes(slug: str) -> bool:
    # Mismo criterio que `tools/addons._es_hermes` (el tramo 2 pasa esa).
    s = slug.lower()
    return s in ("hermes", "self", "f00ba4_hermes") or s.endswith("_hermes")


class TestDecidir(unittest.TestCase):
    def _d(self, tool: str, entrada: Entrada | None, **kw):
        return cp.decidir(tool, entrada, **kw)

    def test_sin_entrada(self) -> None:
        for tool in cp.GENERICAS:
            r = self._d(tool, None)
            self.assertEqual(r.codigo, "command_not_classified")
            self.assertIn("hermes_guide", r.campos["hint"])

    def test_deny(self) -> None:
        for tool in cp.GENERICAS:
            r = self._d(tool, _CORE["demo/secreto"])
            self.assertEqual(r.codigo, "command_denied")
            self.assertEqual(r.campos["reason"], "devuelve una clave (clase D)")

    def test_dedicated_familia_activa(self) -> None:
        for tool in cp.GENERICAS:
            r = self._d(tool, _CORE["demo/dedicada"])
            self.assertIsInstance(r, Rechazo)
            self.assertEqual(r.codigo, "use_dedicated_tool")
            self.assertEqual(r.campos, {
                "tool": "ha_get_demo", "family": "lovelace", "family_disabled": False,
            })

    def test_dedicated_familia_desactivada(self) -> None:
        for tool in cp.GENERICAS:
            r = self._d(tool, _CORE["demo/dedicada"],
                        familias_desactivadas=frozenset({"lovelace"}))
            self.assertEqual(r.codigo, "use_dedicated_tool")
            self.assertIs(r.campos["family_disabled"], True)

    def test_dedicated_familia_de_la_tool(self) -> None:
        # La familia que cuenta es la de la tool dedicada, si se da.
        r = self._d("ha_read_ws_command", _CORE["demo/dedicada"],
                    familias_desactivadas=frozenset({"backups"}),
                    familia_de_tool=lambda t: "backups")
        self.assertEqual(r.campos["family"], "backups")
        self.assertIs(r.campos["family_disabled"], True)

    def test_read_por_la_de_escritura(self) -> None:
        r = self._d("ha_call_ws_command", _CORE["demo/list"])
        self.assertEqual((r.codigo, r.campos), ("wrong_generic_tool",
                                                {"use_tool": "ha_read_ws_command"}))
        r = self._d("sv_call_api", _SV[("GET", "/demo/{slug}")])
        self.assertEqual(r.campos, {"use_tool": "sv_read_api"})

    def test_confirm_por_la_de_lectura(self) -> None:
        r = self._d("ha_read_ws_command", _CORE["demo/create"])
        self.assertEqual((r.codigo, r.campos), ("wrong_generic_tool",
                                                {"use_tool": "ha_call_ws_command"}))
        r = self._d("sv_read_api", _SV[("POST", "/addons/{app}/restart")])
        self.assertEqual(r.campos, {"use_tool": "sv_call_api"})

    def test_familia_desactivada(self) -> None:
        apagada = frozenset({"generic_commands"})
        for tool, entrada in (("ha_read_ws_command", _CORE["demo/list"]),
                              ("ha_call_ws_command", _CORE["demo/create"]),
                              ("sv_read_api", _SV[("GET", "/demo/{slug}")]),
                              ("sv_call_api", _SV[("POST", "/addons/{app}/restart")])):
            with self.subTest(tool=tool):
                r = self._d(tool, entrada, familias_desactivadas=apagada)
                self.assertEqual((r.codigo, r.campos),
                                 ("family_disabled", {"family": "generic_commands"}))

    def test_permitido(self) -> None:
        for tool, entrada in (("ha_read_ws_command", _CORE["demo/list"]),
                              ("ha_call_ws_command", _CORE["demo/create"]),
                              ("sv_read_api", _SV[("GET", "/demo/{slug}")]),
                              ("sv_call_api", _SV[("POST", "/addons/{app}/restart")])):
            with self.subTest(tool=tool):
                r = self._d(tool, entrada,
                            familias_desactivadas=frozenset({"lovelace"}))
                self.assertIsInstance(r, Permitido)
                self.assertIs(r.entrada, entrada)

    def test_tool_desconocida(self) -> None:
        with self.assertRaises(ValueError):
            self._d("ha_call_service", _CORE["demo/list"])

    def test_self_target(self) -> None:
        entrada = _SV[("POST", "/addons/{app}/restart")]
        for app in ("self", "SELF", "f00ba4_hermes", "algo_hermes", "hermes"):
            with self.subTest(app=app):
                r = self._d("sv_call_api", entrada, parametros={"app": app},
                            es_hermes=_es_hermes)
                self.assertEqual((r.codigo, r.campos),
                                 ("path_not_allowed", {"rule": "self_target"}))

    def test_self_target_antes_que_la_categoria(self) -> None:
        # Aunque la entrada sea de la otra genérica o `deny`, el rechazo por
        # apuntar a Hermes va primero: es la guarda más fuerte.
        r = self._d("sv_read_api", _SV[("POST", "/addons/{app}/restart")],
                    parametros={"app": "self"}, es_hermes=_es_hermes)
        self.assertEqual(r.campos, {"rule": "self_target"})

    def test_otra_app_pasa(self) -> None:
        r = self._d("sv_call_api", _SV[("POST", "/addons/{app}/restart")],
                    parametros={"app": "core_ssh"}, es_hermes=_es_hermes)
        self.assertIsInstance(r, Permitido)

    def test_sin_parametro_app_no_aplica(self) -> None:
        r = self._d("sv_read_api", _SV[("GET", "/demo/{slug}")],
                    parametros={"slug": "self"}, es_hermes=_es_hermes)
        self.assertIsInstance(r, Permitido)


class TestEntrada(unittest.TestCase):
    def test_categoria_invalida(self) -> None:
        with self.assertRaises(ValueError):
            Entrada(category="write", reason="x", family="generic_commands")

    def test_motivo_vacio(self) -> None:
        with self.assertRaises(ValueError):
            Entrada(category="deny", reason=" ", family="generic_commands")

    def test_tool_solo_en_dedicated(self) -> None:
        with self.assertRaises(ValueError):
            Entrada(category="dedicated", reason="x", family="lovelace")
        with self.assertRaises(ValueError):
            Entrada(category="read", reason="x", family="generic_commands", tool="t")

    def test_one_shot_solo_en_read(self) -> None:
        with self.assertRaises(ValueError):
            Entrada(category="confirm", reason="x", family="generic_commands",
                    one_shot=True)

    def test_read_no_sale_a_internet(self) -> None:
        with self.assertRaises(ValueError):
            Entrada(category="read", reason="x", family="generic_commands",
                    open_world=True)

    def test_response(self) -> None:
        with self.assertRaises(ValueError):
            Entrada(category="read", reason="x", family="generic_commands",
                    response="xml")


if __name__ == "__main__":
    unittest.main()
