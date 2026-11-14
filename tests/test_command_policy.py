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

import hashlib
import json
import unittest
from unittest import mock

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

    def test_read_puede_salir_a_internet(self) -> None:
        # T047: una `read` puede salir a internet (fuentes de medios
        # remotas); la honestidad de la anotación la ata test_command_table.
        e = Entrada(category="read", reason="x", family="generic_commands",
                    open_world=True)
        self.assertTrue(e.open_world)

    def test_response(self) -> None:
        with self.assertRaises(ValueError):
            Entrada(category="read", reason="x", family="generic_commands",
                    response="xml")


# ── Resumen de la carga (T018, FR-010) ───────────────────────────────────────

# Centinela: si aparece en el resumen serializado, un valor tapado se ha
# colado en la vista previa (principio II).
_CENTINELA = "centinela-secreto-0xC0FFEE"


def _filas(resumen: dict) -> dict[str, dict]:
    return {f["path"]: f for f in resumen["rows"]}


class TestResumirCarga(unittest.TestCase):
    """Regla medible de FR-010: una fila por clave a cualquier profundidad; el
    valor solo si es un escalar corto, de ruta no sensible y que
    `redact_secrets` no cambia.

    Control negativo (T028 c): mostrar el valor aunque la clave sea sensible →
    caen `test_clave_sensible`, `test_hijo_de_ancestro_sensible`,
    `test_redact_extra` y `test_ningun_tapado_en_el_resultado`.
    """

    def test_escalar_corto_visible(self) -> None:
        r = cp.resumir_carga({"name": "Llavero azul"})
        f = _filas(r)["name"]
        self.assertEqual(f["value"], "Llavero azul")
        self.assertEqual(f["type"], "string")
        self.assertNotIn("hidden", f)

    def test_limite_de_64_caracteres(self) -> None:
        r = _filas(cp.resumir_carga({"a": "x" * 64, "b": "x" * 65}))
        # Se cuenta el texto sin comillas: 64 cabe, 65 no.
        self.assertEqual(r["a"]["value"], "x" * 64)
        self.assertNotIn("value", r["b"])
        self.assertEqual(r["b"]["hidden"], "too_long")

    def test_valor_largo_ensena_inicio_tamano_y_hash(self) -> None:
        # T045: un valor largo no sensible se enseña por su inicio (32
        # caracteres), su tamaño y un hash corto, para que quien confirma sepa
        # qué aprueba (enmienda E-1). Control negativo comprobado: sin las
        # dos líneas de `head`/`sha256` en `resumir_carga`, este test cae.
        texto = "Descripción del evento: " + "ñ" * 60
        f = _filas(cp.resumir_carga({"d": texto}))["d"]
        self.assertEqual(f["hidden"], "too_long")
        self.assertNotIn("value", f)
        self.assertEqual(f["head"], texto[:32])
        self.assertEqual(
            f["sha256"], hashlib.sha256(texto.encode("utf-8")).hexdigest()[:12]
        )
        self.assertEqual(f["bytes"], len(json.dumps(texto, ensure_ascii=False).encode("utf-8")))
        # Un número largo: el inicio y el hash son los de su JSON.
        n = _filas(cp.resumir_carga({"n": 10 ** 70}))["n"]
        self.assertEqual(n["head"], "1" + "0" * 31)
        self.assertEqual(n["sha256"], hashlib.sha256(str(10 ** 70).encode()).hexdigest()[:12])

    def test_valor_largo_inicio_pasa_por_redact_secrets(self) -> None:
        # El texto entero no casa con ningún patrón, pero el inicio cortado
        # sí puede: se redacta igual. Se simula con un `redact_secrets` que
        # solo cambia textos de 32 caracteres o menos.
        texto = "a" * 80
        con_parche = mock.patch.object(
            cp, "redact_secrets",
            side_effect=lambda t: "***" if len(t) <= 32 else t,
        )
        with con_parche:
            f = _filas(cp.resumir_carga({"d": texto}))["d"]
        self.assertEqual(f["hidden"], "too_long")
        self.assertEqual(f["head"], "***")

    def test_valor_largo_sensible_no_ensena_inicio_ni_hash(self) -> None:
        # Un valor sensible sigue tapado por completo aunque sea largo: ni
        # inicio ni hash (un hash de un secreto corto se puede invertir).
        largo = _CENTINELA * 4
        r = _filas(cp.resumir_carga(
            {"password": largo, "credentials": {"x": largo}}
        ))
        for ruta in ("password", "credentials.x"):
            with self.subTest(ruta=ruta):
                self.assertEqual(r[ruta]["hidden"], "sensitive")
                self.assertNotIn("head", r[ruta])
                self.assertNotIn("sha256", r[ruta])
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJh" * 2
        f = _filas(cp.resumir_carga({"nota": jwt}))["nota"]
        self.assertEqual(f["hidden"], "sensitive")
        self.assertNotIn("head", f)

    def test_numero_largo(self) -> None:
        largo = 10 ** 70
        r = _filas(cp.resumir_carga({"n": largo, "m": 12345}))
        self.assertEqual(r["n"]["hidden"], "too_long")
        self.assertEqual(r["n"]["type"], "integer")
        self.assertEqual(r["m"]["value"], 12345)

    def test_clave_sensible(self) -> None:
        for clave in ("password", "api_key", "network-key", "Api-Key", "mqtt_password"):
            with self.subTest(clave=clave):
                f = _filas(cp.resumir_carga({clave: "abc"}))[clave]
                self.assertEqual(f["hidden"], "sensitive")
                self.assertNotIn("value", f)

    def test_numero_bajo_clave_sensible(self) -> None:
        f = _filas(cp.resumir_carga({"pin_token": 1234}))["pin_token"]
        self.assertEqual(f["hidden"], "sensitive")

    def test_hijo_de_ancestro_sensible(self) -> None:
        r = _filas(cp.resumir_carga(
            {"credentials": {"username": "usuario-ficticio", "extra": [1, "dos"]}}
        ))
        # El contenedor dice que es contenedor (va antes que `sensitive`)...
        self.assertEqual(r["credentials"]["hidden"], "container")
        # ...y todo lo de dentro hereda la sensibilidad.
        self.assertEqual(r["credentials.username"]["hidden"], "sensitive")
        self.assertEqual(r["credentials.extra[0]"]["hidden"], "sensitive")
        self.assertEqual(r["credentials.extra[1]"]["hidden"], "sensitive")

    def test_redact_extra(self) -> None:
        carga = {"pin": "1234", "nombre": "x"}
        self.assertEqual(_filas(cp.resumir_carga(carga))["pin"]["value"], "1234")
        r = _filas(cp.resumir_carga(carga, redact_extra=("pin",)))
        self.assertEqual(r["pin"]["hidden"], "sensitive")
        self.assertEqual(r["nombre"]["value"], "x")

    def test_texto_que_redact_secrets_cambia(self) -> None:
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJh"
        for texto in (jwt, "password=x", f"Bearer {jwt}"):
            with self.subTest(texto=texto):
                f = _filas(cp.resumir_carga({"nota": texto}))["nota"]
                self.assertEqual(f["hidden"], "sensitive")

    def test_contenedores_y_rutas(self) -> None:
        r = _filas(cp.resumir_carga({"a": {"b": [{"c": 1}, 2]}, "l": []}))
        self.assertEqual(
            sorted(r), ["a", "a.b", "a.b[0]", "a.b[0].c", "a.b[1]", "l"]
        )
        self.assertEqual(r["a"]["type"], "object")
        self.assertEqual(r["a"]["hidden"], "container")
        self.assertEqual(r["a.b"]["type"], "array")
        self.assertEqual(r["a.b"]["hidden"], "container")
        self.assertEqual(r["l"]["hidden"], "container")
        self.assertEqual(r["a.b[0].c"]["value"], 1)
        self.assertEqual(r["a.b[1]"]["value"], 2)

    def test_tipos_json(self) -> None:
        r = _filas(cp.resumir_carga(
            {"i": 3, "f": 1.5, "t": True, "n": None, "s": "x"}
        ))
        self.assertEqual(
            {k: v["type"] for k, v in r.items()},
            {"i": "integer", "f": "number", "t": "boolean", "n": "null", "s": "string"},
        )
        self.assertIs(r["t"]["value"], True)
        self.assertIsNone(r["n"]["value"])
        self.assertIn("value", r["n"])

    def test_bytes_de_cada_fila_y_total(self) -> None:
        import json
        carga = {"name": "Llavero azul ñ", "lista": [1, 2]}
        r = cp.resumir_carga(carga)
        f = _filas(r)
        self.assertEqual(f["name"]["bytes"], len(json.dumps("Llavero azul ñ", ensure_ascii=False).encode()))
        self.assertEqual(f["lista"]["bytes"], len(b"[1, 2]"))
        self.assertEqual(r["bytes"], len(json.dumps(carga, ensure_ascii=False).encode()))
        self.assertEqual(r["keys"], 4)

    def test_carga_vacia(self) -> None:
        r = cp.resumir_carga({})
        self.assertEqual(r["rows"], [])
        self.assertEqual(r["keys"], 0)
        self.assertEqual(r["bytes"], 2)

    def test_ningun_tapado_en_el_resultado(self) -> None:
        import json
        carga = {
            "password": _CENTINELA,
            "credentials": {"user": _CENTINELA, "lista": [_CENTINELA]},
            "pin": _CENTINELA,
            # Un valor largo NO sensible enseña su inicio desde T045 (E-1);
            # uno largo sensible sigue tapado entero.
            "api_key": _CENTINELA * 5,
            "nota": f"token={_CENTINELA}",
        }
        texto = json.dumps(cp.resumir_carga(carga, redact_extra=("pin",)))
        self.assertNotIn(_CENTINELA, texto)
        # Sí está el nombre de la clave: el resumen dice qué se manda.
        self.assertIn("password", texto)


if __name__ == "__main__":
    unittest.main()
