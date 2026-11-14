"""Extrae los inventarios de comandos WebSocket de Core y de rutas del
Supervisor desde su código fuente (spec 011, FR-007; método de research R-0
de la 008).

USO (mantenedor; nunca en el CI ni dentro del add-on)
-----------------------------------------------------
    python -m scripts.inventario.extraer --core-src <raíz de core>
        --supervisor-src <raíz de supervisor> [--comprobar]
        [--core-tsv TSV] [--supervisor-tsv TSV]

`<raíz de core>` es la carpeta que contiene `homeassistant/`;
`<raíz de supervisor>`, la que contiene `supervisor/api/__init__.py`. Sin
`--comprobar` reescribe los dos TSV de `specs/008-cobertura-total/inventario/`;
con `--comprobar` solo dice qué cambiaría. En los dos casos imprime las filas
nuevas, las que desaparecen y lo que no ha sabido resolver.

Después: clasificar a mano las filas nuevas (clase, nota, CAP) y regenerar la
tabla con `scripts/inventario/generar_tabla.py` (quickstart.md de la 011).

POR QUÉ ASÍ
-----------
- **Solo AST y texto, nunca importar ni ejecutar**: el código de HA es
  contenido descargado; importarlo ejecutaría lo que traiga (principio de
  la 008: leer sin ejecutar). Además, Core no se puede importar sin sus
  dependencias. Lo vigila un test con un módulo de ejemplo que lanza al
  importarse.
- **Core**: un comando es la clave `type` (`X.Required("type")` u `Optional`)
  de un diccionario que se pasa a `websocket_command(...)` o a
  `BASE_COMMAND_MESSAGE_SCHEMA.extend(...)`. Un `grep` de cadenas da falsos
  positivos (tipos de fuentes de energía o de selectores, que usan la misma
  clave en otros esquemas). Las constantes se resuelven entre módulos
  (`from .const import X`, f-strings con `DOMAIN`). Las colecciones de
  almacenamiento (`StorageCollectionWebsocket` y subclases) registran sus
  comandos con `f"{self.api_prefix}/…"`: se expanden con el prefijo de cada
  instancia.
- **Supervisor**: rutas de la API V1 (la activa) desde los métodos
  `_register_*` de `supervisor/api/__init__.py`, con un mini intérprete que
  sigue las ramas `if app is self.versions[AppVersion.V1]` y expande
  `_register_advanced_logs`. Los parámetros con expresión regular
  (`{path:.+}`) se escriben sin ella (`{path}`), como en el inventario. Las
  rutas de método comodín (`hdrs.METH_ANY`, el proxy de ingress) no caben en
  el inventario por método: se listan aparte.
- **Fusión**: las filas que ya existían se conservan tal cual (todas sus
  columnas, que se revisaron a mano); las nuevas entran con las columnas
  extraídas y las manuales vacías (sin clase: el generador las convierte en
  `deny` «sin revisar»); las que ya no existen se quitan y se listan.
"""

from __future__ import annotations

import argparse
import ast
import csv
import io
import pathlib
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field

_RAIZ = pathlib.Path(__file__).resolve().parents[2]
_INVENTARIO = _RAIZ / "specs" / "008-cobertura-total" / "inventario"

COLUMNAS_CORE = ("comando", "integracion", "fichero", "cobertura", "clase", "nota", "cap")
COLUMNAS_SV = ("metodo", "ruta", "area", "cobertura", "clase", "rol_admin", "nota", "cap")

_COLECCION_BASE = "StorageCollectionWebsocket"
_FICHERO_COLECCION = "homeassistant/helpers/collection.py"
_METODOS_WEB = {"get": "GET", "post": "POST", "put": "PUT", "delete": "DELETE",
                "patch": "PATCH"}
_PARAM_CON_REGEX = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*):[^}]*\}")
# `except A, B:` sin paréntesis (PEP 758, Python 3.14): Core 2026.11 lo usa y
# el `ast` de un Python anterior no lo entiende. Se reescribe a
# `except (A, B):` solo para analizarlo; el texto no se ejecuta nunca.
_EXCEPT_SIN_PARENTESIS = re.compile(
    r"^(?P<i>[ \t]*except\*?[ \t]+)(?P<t>[^(\n:#][^\n:#]*,[^\n:#]*?)[ \t]*:",
    re.MULTILINE,
)


def analizar(texto: str, nombre: str) -> ast.Module:
    """`ast.parse` que admite la sintaxis de excepciones de Python 3.14."""
    try:
        return ast.parse(texto, filename=nombre)
    except SyntaxError:
        return ast.parse(_EXCEPT_SIN_PARENTESIS.sub(r"\g<i>(\g<t>):", texto), filename=nombre)


@dataclass
class Resultado:
    """Lo extraído: clave → columnas extraídas, y avisos para el mantenedor."""

    filas: dict = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)


# ── Core ─────────────────────────────────────────────────────────────────────

def _nombre_llamada(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _nombre_base(base: ast.expr) -> str:
    if isinstance(base, ast.Subscript):
        base = base.value
    return _nombre_llamada(base)


def _es_clave_type(clave: ast.expr | None, resolver=None) -> bool:
    """`"type"`, `Required("type")` u `Optional(...)`, también con la clave en
    una constante (`Required(TYPE)`, `Required(WS_TYPE)`) si `resolver` la
    resuelve a «type»."""
    if isinstance(clave, ast.Constant):
        return clave.value == "type"
    if not (isinstance(clave, ast.Call)
            and _nombre_llamada(clave.func) in ("Required", "Optional")
            and clave.args):
        return False
    arg = clave.args[0]
    if isinstance(arg, ast.Constant):
        return arg.value == "type"
    return resolver is not None and resolver(arg) == "type"


def _usa_api_prefix(nodo: ast.expr) -> bool:
    return any(
        isinstance(n, ast.Attribute) and n.attr == "api_prefix"
        and isinstance(n.value, ast.Name) and n.value.id == "self"
        for n in ast.walk(nodo)
    )


class _Modulo:
    def __init__(self, nombre: str, ruta_rel: str, arbol: ast.Module) -> None:
        self.nombre = nombre
        self.ruta_rel = ruta_rel
        self.arbol = arbol
        self.asignaciones: dict[str, ast.expr] = {}
        self.importados: dict[str, tuple[str, str]] = {}
        es_paquete = ruta_rel.endswith("__init__.py")
        for nodo in arbol.body:
            if isinstance(nodo, ast.Assign):
                for destino in nodo.targets:
                    if isinstance(destino, ast.Name):
                        self.asignaciones[destino.id] = nodo.value
            elif isinstance(nodo, ast.AnnAssign) and isinstance(nodo.target, ast.Name) \
                    and nodo.value is not None:
                self.asignaciones[nodo.target.id] = nodo.value
            elif isinstance(nodo, ast.ImportFrom):
                origen = self._absoluto(nodo, es_paquete)
                for alias in nodo.names:
                    self.importados[alias.asname or alias.name] = (origen, alias.name)

    def _absoluto(self, nodo: ast.ImportFrom, es_paquete: bool) -> str:
        if not nodo.level:
            return nodo.module or ""
        partes = self.nombre.split(".")
        if not es_paquete:
            partes = partes[:-1]
        if nodo.level > 1:
            partes = partes[: len(partes) - (nodo.level - 1)]
        return ".".join(partes + ([nodo.module] if nodo.module else []))


class _Core:
    def __init__(self, raiz: pathlib.Path) -> None:
        self.raiz = raiz
        self.modulos: dict[str, _Modulo] = {}
        self.sin_analizar: list[str] = []
        base = raiz / "homeassistant"
        for ruta in sorted(base.rglob("*.py")):
            rel = ruta.relative_to(raiz).as_posix()
            try:
                arbol = analizar(ruta.read_text(encoding="utf-8"), rel)
            except (SyntaxError, UnicodeDecodeError) as exc:
                # No se calla: un fichero sin analizar son comandos perdidos.
                self.sin_analizar.append(f"{rel}: {exc}")
                continue
            nombre = rel[:-3].replace("/", ".")
            if nombre.endswith(".__init__"):
                nombre = nombre[: -len(".__init__")]
            self.modulos[nombre] = _Modulo(nombre, rel, arbol)

    def valor(self, modulo: _Modulo, nodo: ast.expr, _visto: frozenset = frozenset()):
        """Valor de texto de `nodo` (constante, nombre o f-string) o None."""
        if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
            return nodo.value
        if isinstance(nodo, ast.JoinedStr):
            trozos = []
            for parte in nodo.values:
                if isinstance(parte, ast.Constant):
                    trozos.append(str(parte.value))
                elif isinstance(parte, ast.FormattedValue):
                    v = self.valor(modulo, parte.value, _visto)
                    if v is None:
                        return None
                    trozos.append(v)
            return "".join(trozos)
        if isinstance(nodo, ast.Name):
            return self.nombre(modulo, nodo.id, _visto)
        return None

    def nombre(self, modulo: _Modulo, nombre: str, _visto: frozenset = frozenset()):
        clave = (modulo.nombre, nombre)
        if clave in _visto:
            return None
        _visto = _visto | {clave}
        if nombre in modulo.asignaciones:
            return self.valor(modulo, modulo.asignaciones[nombre], _visto)
        if nombre in modulo.importados:
            origen, original = modulo.importados[nombre]
            destino = self.modulos.get(origen)
            if destino is not None:
                return self.nombre(destino, original, _visto)
        return None

    def dict_de(self, modulo: _Modulo, nodo: ast.expr) -> ast.Dict | None:
        if isinstance(nodo, ast.Dict):
            return nodo
        if isinstance(nodo, ast.Name) and isinstance(modulo.asignaciones.get(nodo.id), ast.Dict):
            return modulo.asignaciones[nodo.id]  # type: ignore[return-value]
        return None


def _es_llamada_de_comando(llamada: ast.Call) -> bool:
    nombre = _nombre_llamada(llamada.func)
    if nombre == "websocket_command":
        return True
    return (
        nombre == "extend"
        and isinstance(llamada.func, ast.Attribute)
        and _nombre_llamada(llamada.func.value) == "BASE_COMMAND_MESSAGE_SCHEMA"
    )


def _integracion(ruta_rel: str) -> str:
    partes = ruta_rel.split("/")
    if len(partes) > 3 and partes[1] == "components":
        return partes[2]
    return pathlib.PurePosixPath(ruta_rel).stem


def extraer_core(raiz: pathlib.Path) -> Resultado:
    """Comandos WebSocket de Core: comando → {integracion, fichero}."""
    core = _Core(raiz)
    res = Resultado()
    res.avisos += [f"Core: fichero sin analizar {x}" for x in core.sin_analizar]

    # 1) Clases de colección y las plantillas `f"{self.api_prefix}…"` de
    #    cada una, por nombre de clase (las bases se buscan por nombre).
    bases: dict[str, list[str]] = {}
    plantillas: dict[str, list[tuple[str, str]]] = {}
    for modulo in core.modulos.values():
        for clase in ast.walk(modulo.arbol):
            if not isinstance(clase, ast.ClassDef):
                continue
            bases[clase.name] = [_nombre_base(b) for b in clase.bases]
            propias = []
            for nodo in ast.walk(clase):
                if isinstance(nodo, ast.Dict):
                    for k, v in zip(nodo.keys, nodo.values):
                        if _es_clave_type(k) and isinstance(v, ast.JoinedStr) \
                                and _usa_api_prefix(v):
                            sufijo = "".join(
                                str(p.value) if isinstance(p, ast.Constant) else "{}"
                                for p in v.values)
                            propias.append((sufijo, modulo.ruta_rel))
            if propias:
                plantillas.setdefault(clase.name, []).extend(propias)

    def linaje(nombre: str, visto: frozenset = frozenset()) -> list[str]:
        if nombre in visto or nombre not in bases:
            return [nombre] if nombre not in visto else []
        out = [nombre]
        for b in bases[nombre]:
            out += linaje(b, visto | {nombre})
        return out

    colecciones = {n for n in bases if _COLECCION_BASE in linaje(n)}

    # 2) Comandos literales y colecciones instanciadas.
    for modulo in core.modulos.values():
        for nodo in ast.walk(modulo.arbol):
            if not isinstance(nodo, ast.Call):
                continue
            if _es_llamada_de_comando(nodo):
                def resolver(n: ast.expr, m: _Modulo = modulo) -> str | None:
                    return core.valor(m, n)

                # El diccionario puede ir directo, en una constante o
                # envuelto (`All(Schema({...}), ...)`): se miran todos.
                dicts = [d for arg in nodo.args for d in (
                    [core.dict_de(modulo, arg)] if isinstance(arg, ast.Name)
                    else [n for n in ast.walk(arg) if isinstance(n, ast.Dict)])
                    if d is not None]
                for dic in dicts:
                    for k, v in zip(dic.keys, dic.values):
                        if not _es_clave_type(k, resolver) or _usa_api_prefix(v):
                            continue
                        comando = core.valor(modulo, v)
                        if comando is None:
                            # `str`, `cv.string` o `In(...)`: un campo `type`
                            # de la carga, no el comando. Solo se avisa de lo
                            # que parece un comando sin resolver.
                            if isinstance(v, ast.JoinedStr) or (
                                    isinstance(v, ast.Name) and v.id.isupper()):
                                res.avisos.append(
                                    f"Core: tipo sin resolver en {modulo.ruta_rel}:"
                                    f"{getattr(v, 'lineno', '?')} ({ast.unparse(v)})")
                            continue
                        res.filas.setdefault(comando, {
                            "integracion": _integracion(modulo.ruta_rel),
                            "fichero": modulo.ruta_rel,
                        })
            elif _nombre_llamada(nodo.func) in colecciones:
                prefijo_nodo = nodo.args[1] if len(nodo.args) > 1 else next(
                    (kw.value for kw in nodo.keywords if kw.arg == "api_prefix"), None)
                prefijo = core.valor(modulo, prefijo_nodo) if prefijo_nodo is not None else None
                if prefijo is None:
                    res.avisos.append(
                        f"Core: prefijo de colección sin resolver en "
                        f"{modulo.ruta_rel}:{nodo.lineno}")
                    continue
                for clase in linaje(_nombre_llamada(nodo.func)):
                    for sufijo, fichero in plantillas.get(clase, []):
                        comando = sufijo.replace("{}", prefijo, 1)
                        if fichero == _FICHERO_COLECCION:
                            fichero = f"{fichero} ({_COLECCION_BASE})"
                        res.filas.setdefault(comando, {
                            "integracion": _integracion(modulo.ruta_rel),
                            "fichero": fichero,
                        })
    return res


# ── Supervisor ───────────────────────────────────────────────────────────────

def _rama_v1(test: ast.expr) -> bool | None:
    """True/False si `test` es `app is self.versions[AppVersion.V1|V2]`."""
    if isinstance(test, ast.Compare) and len(test.ops) == 1 \
            and isinstance(test.ops[0], (ast.Is, ast.IsNot)):
        texto = ast.unparse(test.comparators[0])
        if "AppVersion.V1" in texto or "AppVersion.V2" in texto:
            es_v1 = "AppVersion.V1" in texto
            return es_v1 if isinstance(test.ops[0], ast.Is) else not es_v1
    return None


def _texto(nodo: ast.expr, entorno: dict[str, str]) -> str | None:
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return nodo.value
    if isinstance(nodo, ast.Name):
        return entorno.get(nodo.id)
    if isinstance(nodo, ast.JoinedStr):
        trozos = []
        for parte in nodo.values:
            if isinstance(parte, ast.Constant):
                trozos.append(str(parte.value))
            else:
                v = _texto(parte.value, entorno)  # type: ignore[union-attr]
                if v is None:
                    return None
                trozos.append(v)
        return "".join(trozos)
    return None


def extraer_supervisor(raiz: pathlib.Path) -> Resultado:
    """Rutas de la API V1 del Supervisor: (método, ruta) → {}."""
    ruta = raiz / "supervisor" / "api" / "__init__.py"
    arbol = analizar(ruta.read_text(encoding="utf-8"), str(ruta))
    res = Resultado()
    metodos: dict[str, ast.FunctionDef] = {
        n.name: n for n in ast.walk(arbol)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    def anotar(metodo: str, plantilla: str, donde: int) -> None:
        plantilla = _PARAM_CON_REGEX.sub(r"{\1}", plantilla)
        res.filas.setdefault((metodo, plantilla), {})

    def ruta_de(llamada: ast.Call, entorno: dict[str, str]) -> None:
        nombre = _nombre_llamada(llamada.func)
        if nombre in _METODOS_WEB and llamada.args:
            texto = _texto(llamada.args[0], entorno)
            if texto is None:
                res.avisos.append(f"Supervisor: ruta sin resolver en la línea {llamada.lineno}")
            else:
                anotar(_METODOS_WEB[nombre], texto, llamada.lineno)
        elif nombre == "route" and len(llamada.args) >= 2:
            metodo = llamada.args[0]
            texto = _texto(llamada.args[1], entorno)
            literal = metodo.value if isinstance(metodo, ast.Constant) else None
            if isinstance(literal, str) and literal.upper() in _METODOS_WEB.values():
                if texto is not None:
                    anotar(literal.upper(), texto, llamada.lineno)
            else:
                res.avisos.append(
                    f"Supervisor: ruta de método comodín omitida "
                    f"({ast.unparse(metodo)} {texto}) en la línea {llamada.lineno}")

    def interpretar(cuerpo: Iterable[ast.stmt], entorno: dict[str, str]) -> None:
        for sentencia in cuerpo:
            if isinstance(sentencia, ast.If):
                rama = _rama_v1(sentencia.test)
                if rama is True:
                    interpretar(sentencia.body, entorno)
                elif rama is False:
                    interpretar(sentencia.orelse, entorno)
                else:
                    # Condición que no es de versión: las dos ramas pueden
                    # registrar rutas reales.
                    interpretar(sentencia.body, entorno)
                    interpretar(sentencia.orelse, entorno)
                continue
            if isinstance(sentencia, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for nodo in ast.walk(sentencia):
                if not isinstance(nodo, ast.Call):
                    continue
                nombre = _nombre_llamada(nodo.func)
                if nombre == "add_routes":
                    for elemento in ast.walk(nodo):
                        if isinstance(elemento, ast.Call) and elemento is not nodo:
                            ruta_de(elemento, entorno)
                elif nombre.startswith("_register_") and nombre in metodos \
                        and isinstance(nodo.func, ast.Attribute):
                    llamar(metodos[nombre], nodo, entorno)
                elif nombre == "StaticResourceConfig" and nodo.args:
                    prefijo = _texto(nodo.args[0], entorno)
                    if prefijo is not None:
                        # aiohttp sirve un recurso estático como
                        # `<prefijo>/{filename}` y solo para GET.
                        anotar("GET", f"{prefijo}/{{filename}}", nodo.lineno)

    def llamar(funcion: ast.FunctionDef, llamada: ast.Call, entorno: dict[str, str]) -> None:
        parametros = [a.arg for a in funcion.args.args if a.arg != "self"]
        nuevo: dict[str, str] = {}
        for nombre, arg in zip(parametros, llamada.args):
            v = _texto(arg, entorno)
            if v is not None:
                nuevo[nombre] = v
        for kw in llamada.keywords:
            v = _texto(kw.value, entorno) if kw.arg else None
            if kw.arg and v is not None:
                nuevo[kw.arg] = v
        interpretar(funcion.body, nuevo)

    carga = metodos.get("load")
    if carga is None:
        res.avisos.append("Supervisor: no se encuentra `load` en api/__init__.py")
        return res
    interpretar(carga.body, {})
    return res


# ── TSV y fusión ─────────────────────────────────────────────────────────────

def leer_tsv(ruta: pathlib.Path) -> list[dict[str, str]]:
    return leer_tsv_texto(ruta.read_text(encoding="utf-8"))


def leer_tsv_texto(texto: str) -> list[dict[str, str]]:
    # QUOTE_NONE: las notas llevan comillas y acentos graves tal cual.
    return list(csv.DictReader(io.StringIO(texto, newline=""), delimiter="\t",
                               quoting=csv.QUOTE_NONE))


def escribir_tsv(ruta: pathlib.Path, columnas: tuple[str, ...],
                 filas: list[dict[str, str]]) -> None:
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, delimiter="\t",
                           lineterminator="\n", quoting=csv.QUOTE_NONE,
                           escapechar="\\")
        w.writeheader()
        for fila in filas:
            w.writerow({c: fila.get(c, "") for c in columnas})


def fusionar(previas: list[dict[str, str]], extraidas: dict, columnas: tuple[str, ...],
             clave) -> tuple[list[dict[str, str]], list, list]:
    """Filas fusionadas (en el orden previo, las nuevas al final en orden de
    clave), claves nuevas y claves quitadas.

    Una fila que sigue existiendo se conserva entera: sus columnas manuales
    (clase, nota, CAP…) son decisiones revisadas que el extractor no puede
    rehacer. Una nueva lleva solo lo extraído.
    """
    por_clave = {clave(f): f for f in previas}
    filas = [f for f in previas if clave(f) in extraidas]
    quitadas = [clave(f) for f in previas if clave(f) not in extraidas]
    nuevas = sorted(k for k in extraidas if k not in por_clave)
    for k in nuevas:
        fila = {c: "" for c in columnas}
        if isinstance(k, tuple):
            fila["metodo"], fila["ruta"] = k
        else:
            fila["comando"] = k
        fila.update(extraidas[k])
        filas.append(fila)
    return filas, nuevas, quitadas


def _clave_core(fila: dict[str, str]) -> str:
    return fila["comando"]


def _clave_sv(fila: dict[str, str]) -> tuple[str, str]:
    return (fila["metodo"], fila["ruta"])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--core-src", type=pathlib.Path)
    p.add_argument("--supervisor-src", type=pathlib.Path)
    p.add_argument("--core-tsv", type=pathlib.Path, default=_INVENTARIO / "core-ws.tsv")
    p.add_argument("--supervisor-tsv", type=pathlib.Path,
                   default=_INVENTARIO / "supervisor-rutas.tsv")
    p.add_argument("--comprobar", action="store_true",
                   help="no escribe nada; solo informa de lo que cambiaría")
    a = p.parse_args(argv)
    cambios = False
    trabajos = []
    if a.core_src:
        trabajos.append(("Core", extraer_core(a.core_src), a.core_tsv, COLUMNAS_CORE, _clave_core))
    if a.supervisor_src:
        trabajos.append(("Supervisor", extraer_supervisor(a.supervisor_src),
                         a.supervisor_tsv, COLUMNAS_SV, _clave_sv))
    for nombre, res, tsv, columnas, clave in trabajos:
        previas = leer_tsv(tsv) if tsv.exists() else []
        filas, nuevas, quitadas = fusionar(previas, res.filas, columnas, clave)
        print(f"{nombre}: {len(res.filas)} extraídas, {len(nuevas)} nuevas, "
              f"{len(quitadas)} quitadas.")
        for k in nuevas:
            print(f"  + {k}")
        for k in quitadas:
            print(f"  - {k}")
        for aviso in res.avisos:
            print(f"  ! {aviso}")
        cambios = cambios or bool(nuevas or quitadas)
        if not a.comprobar:
            escribir_tsv(tsv, columnas, filas)
    return 1 if (a.comprobar and cambios) else 0


if __name__ == "__main__":
    sys.exit(main())
