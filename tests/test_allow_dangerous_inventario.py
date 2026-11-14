"""Quién levanta la guarda de la denylist del cliente (spec 018, T027).

`HAClient.call_service` y `HAClient.call_service_response` rechazan un
servicio de la denylist salvo que el llamador pase `allow_dangerous=True`.
`SECURITY.md` dice quién lo hace y que siempre es después de validar su
`confirmation_token`. Este test recorre el código por AST y comprueba:

- que los sitios que pasan `allow_dangerous` con algo distinto de `False`
  son exactamente los de `SITIOS` (función y módulo);
- que en cada uno se llama a `validate_confirmation_token` antes;
- que las tools que llegan a esos sitios son exactamente las de `SITIOS`;
- que `SECURITY.md` nombra todas esas tools.

Así, un sitio nuevo (o una tool nueva que use un helper) hace fallar el test
hasta que se declare aquí y se documente, y el documento no se queda viejo
otra vez.

«Antes» es por número de línea dentro de la misma función, no por flujo de
control: basta para el patrón del proyecto (validar y, debajo, llamar).

Control negativo comprobado (T027), uno a uno:
(a) `allow_dangerous=True` en `ha_enable_automation` (sitio no declarado) →
    caen `test_los_sitios_son_los_declarados` y `test_todos_validan_el_token_antes`;
(b) `allow_dangerous=True` en la llamada directa (sin token) de
    `guarded_entity_invoke` → cae `test_todos_validan_el_token_antes`;
(c) `ha_run_script` fuera de `SECURITY.md` → cae `test_security_md_nombra_todas`;
(d) `ha_run_script` fuera de `SITIOS` → cae
    `test_las_tools_de_los_helpers_son_las_declaradas`.
Antes del arreglo de `SECURITY.md`, `test_security_md_nombra_todas` fallaba
con las 9 tools que la frase antigua no nombraba.
"""

from __future__ import annotations

import ast
import pathlib

_RAIZ = pathlib.Path(__file__).resolve().parents[1]
_SRC = _RAIZ / "hermes" / "src" / "hermes"
_SECURITY_MD = _RAIZ / "SECURITY.md"

# (módulo relativo a hermes/src/hermes, función) → tools que llegan a ese
# sitio. Para las tools es la propia función; para los helpers de
# `_common.py`, las tools que los llaman.
SITIOS: dict[tuple[str, str], frozenset[str]] = {
    ("tools/ha.py", "ha_call_service"): frozenset({"ha_call_service"}),
    ("tools/ha.py", "ha_call_service_response"): frozenset({"ha_call_service_response"}),
    ("tools/_common.py", "guarded_reload"): frozenset({
        "ha_reload_automations", "ha_reload_counters", "ha_reload_scenes",
        "ha_reload_schedules", "ha_reload_scripts", "ha_reload_timers",
        "ha_reload_zones",
    }),
    ("tools/_common.py", "guarded_entity_invoke"): frozenset({
        "ha_run_script", "ha_trigger_automation",
    }),
}

_FUNCIONES = (ast.AsyncFunctionDef, ast.FunctionDef)


def _levanta(llamada: ast.Call) -> bool:
    """`allow_dangerous=<algo que no es el literal False>`: una variable
    cuenta, porque puede valer True."""
    return any(
        kw.arg == "allow_dangerous"
        and not (isinstance(kw.value, ast.Constant) and kw.value.value is False)
        for kw in llamada.keywords
    )


def _es_llamada_a(nodo: ast.AST, nombre: str) -> bool:
    if not isinstance(nodo, ast.Call):
        return False
    f = nodo.func
    return (isinstance(f, ast.Name) and f.id == nombre) or (
        isinstance(f, ast.Attribute) and f.attr == nombre)


def _funciones_con_padre(arbol: ast.AST):
    """Pares (función más interna, nodo) para cada nodo dentro de una función."""
    def visitar(nodo: ast.AST, actual: ast.AST | None):
        for hijo in ast.iter_child_nodes(nodo):
            if isinstance(hijo, _FUNCIONES):
                yield from visitar(hijo, hijo)
            else:
                if actual is not None:
                    yield actual, hijo
                yield from visitar(hijo, actual)
    yield from visitar(arbol, None)


def sitios(fuentes: dict[str, str]) -> dict[tuple[str, str], bool]:
    """Sitios que levantan la guarda → si se valida el token antes.

    `fuentes`: módulo → código fuente."""
    encontrados: dict[tuple[str, str], bool] = {}
    for modulo, codigo in fuentes.items():
        arbol = ast.parse(codigo)
        for funcion, nodo in _funciones_con_padre(arbol):
            if not (isinstance(nodo, ast.Call) and _levanta(nodo)):
                continue
            valida_antes = any(
                _es_llamada_a(sub, "validate_confirmation_token")
                and sub.lineno < nodo.lineno
                for sub in ast.walk(funcion)
            )
            clave = (modulo, funcion.name)
            encontrados[clave] = encontrados.get(clave, True) and valida_antes
    return encontrados


def _nombre_de_tool(nodo: ast.AST) -> str | None:
    if not isinstance(nodo, _FUNCIONES):
        return None
    for deco in nodo.decorator_list:
        llamada = deco if isinstance(deco, ast.Call) else None
        f = llamada.func if llamada else deco
        if isinstance(f, ast.Attribute) and f.attr == "tool":
            for kw in (llamada.keywords if llamada else []):
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    return str(kw.value.value)
            return nodo.name
    return None


def tools_que_llaman(fuentes: dict[str, str], helper: str) -> set[str]:
    tools: set[str] = set()
    for codigo in fuentes.values():
        for nodo in ast.walk(ast.parse(codigo)):
            nombre = _nombre_de_tool(nodo)
            if nombre and any(_es_llamada_a(s, helper) for s in ast.walk(nodo)):
                tools.add(nombre)
    return tools


def _fuentes_reales() -> dict[str, str]:
    return {
        p.relative_to(_SRC).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(_SRC.rglob("*.py"))
    }


class TestInventario:
    def test_los_sitios_son_los_declarados(self):
        encontrados = sitios(_fuentes_reales())
        assert set(encontrados) == set(SITIOS), (
            "Los sitios que pasan allow_dangerous a HAClient han cambiado. "
            "Declara el nuevo en SITIOS de este test y en el párrafo de la "
            "denylist de SECURITY.md (o quítalo si sobra)."
        )

    def test_todos_validan_el_token_antes(self):
        sin_validar = sorted(k for k, v in sitios(_fuentes_reales()).items() if not v)
        assert sin_validar == []

    def test_las_tools_de_los_helpers_son_las_declaradas(self):
        fuentes = _fuentes_reales()
        for (modulo, funcion), tools in SITIOS.items():
            if modulo == "tools/_common.py":
                assert tools_que_llaman(fuentes, funcion) == set(tools), funcion

    def test_security_md_nombra_todas(self):
        texto = _SECURITY_MD.read_text(encoding="utf-8")
        faltan = sorted(
            t for tools in SITIOS.values() for t in tools if f"`{t}`" not in texto)
        assert faltan == [], f"SECURITY.md no nombra: {faltan}"


class TestControlSintetico:
    _MALO = (
        "async def sin_validar(c):\n"
        "    await c.call_service('a', 'b', allow_dangerous=True)\n"
        "    await validate_confirmation_token('t', 'x', {})\n"
        "async def con_variable(c, peligro):\n"
        "    await validate_confirmation_token('t', 'x', {})\n"
        "    await c.call_service('a', 'b', allow_dangerous=peligro)\n"
        "async def con_false(c):\n"
        "    await c.call_service('a', 'b', allow_dangerous=False)\n"
    )

    def test_control_sintetico_sitios(self):
        assert sitios({"m.py": self._MALO}) == {
            ("m.py", "sin_validar"): False,
            ("m.py", "con_variable"): True,
        }

    def test_control_sintetico_anidada(self):
        # Una tool anidada dentro de `register` cuenta como la tool, no como
        # `register`.
        codigo = (
            "def register(mcp, c):\n"
            "    @mcp.tool()\n"
            "    async def ha_algo():\n"
            "        await validate_confirmation_token('t', 'x', {})\n"
            "        await c.call_service('a', 'b', allow_dangerous=True)\n"
        )
        assert sitios({"m.py": codigo}) == {("m.py", "ha_algo"): True}
