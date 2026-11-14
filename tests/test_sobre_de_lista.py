"""Sobre común de listas (spec 018, US3: FR-012…FR-015; CAP-023).

Toda tool de lista NUEVA de la 1.2.0 devuelve `{..., "count", "items",
"truncated"}` armado con `sobre_de_lista` de `tools/_common.py`. Las de la
1.1.2 conservan su forma (D-07: cambiarla rompería a sus clientes).

- El constructor: forma, cabecera, cabecera reservada y su paso por el tope
  central (`recortar_a_bytes`).
- Las genéricas de la 011 lo usan sin cambiar su respuesta.
- El test transversal: por AST, toda tool nueva `ha_list_*` o `sv_list_*`
  llama a `sobre_de_lista` en su función, o figura en `EXCEPCIONES_SOBRE` con
  su motivo. Una tool nueva de lista cuya función no encuentra el AST se
  señala igual (fail-closed). Hoy no hay ninguna tool nueva de lista, así
  que el control negativo va dentro del propio fichero, con fuentes
  sintéticas.

Control negativo (T023): con `count` fijo a 0 en `sobre_de_lista` caen
`test_forma_basica`, `test_cabecera_y_truncated` y `test_pasa_por_el_tope_central`;
con `incumplen` devolviendo siempre `[]` cae
`test_control_sintetico_lista_suelta_se_senala`.

Control negativo (T029): sin el `malas.update(...)` de las no encontradas,
cae `test_control_sintetico_no_encontrada_se_senala` (las dos aserciones).
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

from hermes.tools._common import recortar_a_bytes, sobre_de_lista, tam_json
from hermes.tools.generic_commands import _respuesta

_TOOLS_DIR = pathlib.Path(__file__).resolve().parents[1] / "hermes" / "src" / "hermes" / "tools"
_ESQUEMAS_1_1_2 = pathlib.Path(__file__).resolve().parent / "fixtures" / "esquemas_1_1_2.json"

# Tools nuevas de lista que NO usan el sobre, con su motivo. Cada entrada se
# justifica aquí; una que ya no exista o no sea nueva hace fallar el test, para
# que la lista no envejezca.
EXCEPCIONES_SOBRE: dict[str, str] = {}

_PREFIJOS_DE_LISTA = ("ha_list_", "sv_list_")


# ── Constructor ───────────────────────────────────────────────────────────────

class TestConstructor:
    def test_forma_basica(self):
        a, b = {"id": "a"}, {"id": "b"}
        assert sobre_de_lista([a, b]) == {"count": 2, "items": [a, b], "truncated": False}

    def test_cabecera_y_truncated(self):
        sobre = sobre_de_lista([1, 2, 3], truncated=True, command="x/list", category="core")
        assert sobre == {"command": "x/list", "category": "core",
                         "count": 3, "items": [1, 2, 3], "truncated": True}
        # La cabecera va delante: el cliente la lee antes que la lista.
        assert list(sobre) == ["command", "category", "count", "items", "truncated"]

    def test_lista_vacia(self):
        assert sobre_de_lista([]) == {"count": 0, "items": [], "truncated": False}

    @pytest.mark.parametrize("clave", ["count", "items"])
    def test_cabecera_reservada(self, clave):
        # Error de programación, no de uso: una cabecera que pise el sobre
        # mentiría sobre la lista. `truncated` no puede llegar a la cabecera:
        # es el propio argumento.
        with pytest.raises(ValueError, match=clave):
            sobre_de_lista([1], **{clave: 5})

    def test_pasa_por_el_tope_central(self):
        items = [{"id": i, "relleno": "x" * 200} for i in range(50)]
        sobre = sobre_de_lista(items, command="x/list")
        tope = 2000
        assert tam_json(sobre) > tope
        recortado = recortar_a_bytes(sobre, tope)
        assert recortado["truncated"] is True
        assert recortado["count"] == len(recortado["items"]) < len(items)
        assert recortado["_response_limit"]["total"] == len(items)
        assert recortado["command"] == "x/list"
        assert tam_json(recortado) <= tope


class TestGenericasSinCambios:
    """Las genéricas de la 011 usan el constructor y responden igual que antes
    (forma de `specs/011-politica-de-comandos/contracts/tools.md`)."""

    def test_lista(self):
        cab = {"command": "tag/list", "category": "core"}
        r = _respuesta(cab, [{"id": "t1"}])
        assert r == {"command": "tag/list", "category": "core",
                     "count": 1, "items": [{"id": "t1"}], "truncated": False}
        assert list(r) == ["command", "category", "count", "items", "truncated"]

    def test_objeto(self):
        cab = {"command": "x/info", "category": "core"}
        assert _respuesta(cab, {"a": 1}) == {"command": "x/info", "category": "core",
                                             "result": {"a": 1}}


# ── Test transversal (FR-014, research R-4) ──────────────────────────────────

def _es_decorador_tool(deco: ast.expr) -> bool:
    if isinstance(deco, ast.Call):
        deco = deco.func
    return isinstance(deco, ast.Attribute) and deco.attr == "tool"


def _nombre_de_tool(nodo: ast.AsyncFunctionDef | ast.FunctionDef) -> str | None:
    """Nombre con el que se registra la tool (el de la función, o `name=`)."""
    for deco in nodo.decorator_list:
        if not _es_decorador_tool(deco):
            continue
        if isinstance(deco, ast.Call):
            for kw in deco.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    return str(kw.value.value)
        return nodo.name
    return None


def _llama_al_sobre(nodo: ast.AST) -> bool:
    for sub in ast.walk(nodo):
        if isinstance(sub, ast.Call):
            f = sub.func
            if (isinstance(f, ast.Name) and f.id == "sobre_de_lista") or (
                isinstance(f, ast.Attribute) and f.attr == "sobre_de_lista"
            ):
                return True
    return False


def incumplen(fuentes: dict[str, str], nuevas: set[str]) -> list[str]:
    """Tools de `nuevas` con nombre de lista cuya función no llama a
    `sobre_de_lista`, o cuya función no se encuentra en `fuentes`.
    `fuentes`: módulo → código fuente.

    Lo segundo cierra el agujero del AST (spec 018, T029): una tool
    registrada con un nombre dinámico, por una factoría o fuera de
    `hermes/src/hermes/tools/` no aparece en el recorrido, y sin esta regla
    pasaría aunque devolviera una lista suelta. Lo que no se puede comprobar
    se señala, no se da por bueno."""
    malas: set[str] = set()
    encontradas: set[str] = set()
    for codigo in fuentes.values():
        for nodo in ast.walk(ast.parse(codigo)):
            if not isinstance(nodo, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            nombre = _nombre_de_tool(nodo)
            if nombre is None or nombre not in nuevas:
                continue
            encontradas.add(nombre)
            if nombre.startswith(_PREFIJOS_DE_LISTA) and not _llama_al_sobre(nodo):
                malas.add(nombre)
    malas.update(
        n for n in nuevas if n.startswith(_PREFIJOS_DE_LISTA) and n not in encontradas
    )
    return sorted(malas)


def _fuentes_reales() -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(_TOOLS_DIR.glob("*.py"))}


def _tools_nuevas() -> set[str]:
    from tests.test_tools_registration import _real_registry

    de_la_1_1_2 = set(json.loads(_ESQUEMAS_1_1_2.read_text(encoding="utf-8")))
    return set(_real_registry()) - de_la_1_1_2


class TestTransversal:
    def test_las_listas_nuevas_usan_el_sobre(self):
        nuevas = _tools_nuevas() - set(EXCEPCIONES_SOBRE)
        malas = incumplen(_fuentes_reales(), nuevas)
        assert malas == [], (
            "Tools de lista nuevas de la 1.2.0 sin el sobre común, o cuya "
            f"función no encuentra el análisis AST: {malas}. Devuelve "
            "`sobre_de_lista(items, truncated=..., **cabecera)` de "
            "`hermes.tools._common` (spec 018, FR-014) desde una función "
            "decorada con `@mcp.tool` en hermes/src/hermes/tools/, o añade la "
            "tool a EXCEPCIONES_SOBRE de tests/test_sobre_de_lista.py con su motivo."
        )

    def test_las_excepciones_son_tools_nuevas_registradas(self):
        nuevas = _tools_nuevas()
        sobran = sorted(n for n in EXCEPCIONES_SOBRE if n not in nuevas)
        assert sobran == [], f"EXCEPCIONES_SOBRE nombra tools que no son nuevas: {sobran}"
        sin_motivo = sorted(n for n, m in EXCEPCIONES_SOBRE.items() if not m.strip())
        assert sin_motivo == [], f"EXCEPCIONES_SOBRE sin motivo: {sin_motivo}"

    def test_las_listas_de_la_1_1_2_no_se_vigilan(self):
        # `ha_list_areas` es de la 1.1.2 y conserva su forma (FR-015). Si
        # contara como nueva, el transversal la señalaría (y así se comprueba
        # que lee las fuentes reales); no la señala porque no es nueva.
        assert "ha_list_areas" not in _tools_nuevas()
        assert incumplen(_fuentes_reales(), {"ha_list_areas"}) == ["ha_list_areas"]


class TestControlSintetico:
    """El transversal pasa vacío hoy; esto prueba que sabe fallar."""

    _MALA = (
        "def register(mcp):\n"
        "    @mcp.tool()\n"
        "    async def ha_list_algo() -> object:\n"
        "        return [1, 2]\n"
    )
    _BUENA = (
        "from hermes.tools._common import sobre_de_lista\n"
        "def register(mcp):\n"
        "    @mcp.tool()\n"
        "    async def sv_list_algo() -> object:\n"
        "        return sobre_de_lista([1, 2])\n"
    )

    def test_control_sintetico_lista_suelta_se_senala(self):
        assert incumplen({"sintetico": self._MALA}, {"ha_list_algo"}) == ["ha_list_algo"]

    def test_control_sintetico_con_sobre_no_se_senala(self):
        assert incumplen({"sintetico": self._BUENA}, {"sv_list_algo"}) == []

    def test_control_sintetico_no_encontrada_se_senala(self):
        # Fail-closed (T029): una tool de lista del registro cuya función no
        # aparece en las fuentes (aquí, registrada con nombre dinámico) se
        # señala aunque no se pueda ver qué devuelve.
        dinamica = (
            "def register(mcp, sufijo):\n"
            "    @mcp.tool(name='ha_list_' + sufijo)\n"
            "    async def fabricada() -> object:\n"
            "        return [1, 2]\n"
        )
        fuentes = {"buena": self._BUENA, "dinamica": dinamica}
        assert incumplen(fuentes, {"sv_list_algo", "ha_list_fabricada"}) == [
            "ha_list_fabricada"]
        # Sin fuente ninguna, también.
        assert incumplen({}, {"sv_list_fantasma"}) == ["sv_list_fantasma"]

    def test_no_encontrada_sin_nombre_de_lista_no_se_senala(self):
        # La regla es solo para las de lista: el resto de tools nuevas no
        # tiene por qué estar en `hermes/src/hermes/tools/`.
        assert incumplen({}, {"ha_get_fantasma"}) == []

    def test_solo_las_de_nombre_de_lista(self):
        otra = self._MALA.replace("ha_list_algo", "ha_get_algo")
        assert incumplen({"sintetico": otra}, {"ha_get_algo"}) == []
