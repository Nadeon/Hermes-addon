"""Hermes — Resolver de includes YAML para /config.

Implementa HAIncludeCollector (subclase de yaml.SafeLoader) que colecciona
todos los ficheros referenciados por los tags de include de Home Assistant:
  !include, !include_dir_list, !include_dir_merge_list,
  !include_dir_named, !include_dir_merge_named, !secret, !env_var

La función principal get_yaml_executable_paths() devuelve el set de paths
YAML en el árbol de includes, o FAIL_CLOSED_MARKER si el parsing falla.

FAIL_CLOSED: si configuration.yaml o cualquier fichero del árbol es
sintácticamente inválido, se trata como si TODOS los .yaml/.yml fueran
ejecutables por indirección.

Cache: el árbol se parsea una sola vez y se cachea en memoria. El caché
se invalida llamando a invalidate_include_cache() tras cualquier escritura
en configuration.yaml o en ficheros del árbol.
"""

from __future__ import annotations

import asyncio
import fnmatch
from pathlib import Path
from typing import Any

import structlog
import yaml

import hermes.fs as _fs

logger = structlog.get_logger(__name__)

# ── Sentinel para fail-closed ─────────────────────────────────────────────────


class _FailClosedMarker:
    """Singleton que indica que el resolver falló y estamos en modo fail-closed."""
    _instance: "_FailClosedMarker | None" = None

    def __new__(cls) -> "_FailClosedMarker":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "FAIL_CLOSED_MARKER"


FAIL_CLOSED_MARKER: _FailClosedMarker = _FailClosedMarker()

# ── Cache ─────────────────────────────────────────────────────────────────────

_cache_lock = asyncio.Lock()
_cached_paths: set[str] | _FailClosedMarker | None = None  # None = not yet computed
_cache_fail_reason: str = ""


def invalidate_include_cache() -> None:
    """Invalida el caché del árbol de includes."""
    global _cached_paths, _cache_fail_reason
    _cached_paths = None
    _cache_fail_reason = ""


# ── HAIncludeCollector ────────────────────────────────────────────────────────

# Tope de anidamiento de !include. Home Assistant no anida ni de lejos tanto;
# está para que un árbol patológico (o un ciclo que la marca de visitados no
# viera) tope aquí en vez de en el límite de recursión del intérprete.
_MAX_INCLUDE_DEPTH = 25


def _build_collector(
    config_base: Path,
    collected: set[str],
    errors: list[str],
    visited: set[str],
) -> type:
    """Construye una clase HAIncludeCollector con el config_base dado.

    `visited` lleva los ficheros ya cargados en este recorrido. Lo aporta el
    llamador para poder sembrarlo con configuration.yaml, que se abre fuera de
    los constructores.
    """

    config_base_resolved = config_base.resolve()
    # Profundidad actual del recorrido. Lista de un elemento porque los
    # constructores son closures y necesitan mutarla.
    depth = [0]

    class HAIncludeCollector(yaml.SafeLoader):
        pass

    def _contained(candidate: Path, ref: str) -> Path | None:
        """Resuelve `candidate` y exige que caiga dentro de config_base.

        POR QUÉ: el argumento de `!include` es texto de un fichero de
        configuración, no una ruta validada. Sin resolver y comprobar
        contención, un `!include ../../etc/hostname` hacía que el resolver
        abriera un fichero de fuera del sandbox — y el resolver corre en
        CUALQUIER preview de escritura o borrado, así que bastaba con tener ese
        include puesto para que Hermes leyera lo que le dijeran.

        Devuelve None (se ignora la referencia) si escapa o no se puede
        resolver.

        DECISIÓN (issue #4): una referencia que escapa se SALTA con aviso;
        no se trata como FAIL_CLOSED_MARKER. El set que sale de aquí solo
        decide qué escrituras exigen confirmación, y un fichero de fuera de
        /config no puede hacer «ejecutable» a uno de dentro ni Hermes puede
        escribirlo. Fallar cerrado obligaría a pedir token para TODA
        escritura en .yaml hasta corregir la referencia, sin ganar nada en
        seguridad: sería fricción pura. El aviso `yaml_include_outside_sandbox`
        queda en el log para que el dueño lo vea y lo corrija.
        """
        try:
            resolved = candidate.resolve()
        except (OSError, ValueError, RuntimeError):
            logger.warning("yaml_include_unresolvable", ref=ref)
            return None
        try:
            resolved.relative_to(config_base_resolved)
        except ValueError:
            logger.warning(
                "yaml_include_outside_sandbox", ref=ref, resolved=str(resolved)
            )
            return None
        return resolved

    def _target(rel: str, ref: str) -> Path | None:
        """Destino de un tag de include, ya resuelto y contenido."""
        return _contained(config_base_resolved / rel, ref)

    def _load_nested(path: Path, tag: str) -> Any:
        """Carga un fichero del árbol con freno de ciclos y de profundidad.

        POR QUÉ el freno: `!include` no tenía detección de ciclos. Un
        configuration.yaml que se incluyera a sí mismo recursaba hasta
        RecursionError, y ese error subía por get_yaml_executable_paths() →
        check_executable_by_indirection() → _build_write_preview(), o sea que
        rompía TODAS las escrituras y borrados — incluido el que habría
        arreglado el configuration.yaml roto. Un fichero ya visitado no se
        vuelve a abrir: su ruta ya está en `collected`, que es lo único que se
        busca aquí.
        """
        key = str(path)
        if key in visited:
            return None
        if depth[0] >= _MAX_INCLUDE_DEPTH:
            errors.append(
                f"{tag} {path}: include depth limit ({_MAX_INCLUDE_DEPTH}) exceeded"
            )
            return None
        visited.add(key)
        depth[0] += 1
        try:
            with open(path, encoding="utf-8") as f:
                return yaml.load(f, Loader=HAIncludeCollector)
        except FileNotFoundError:
            errors.append(f"{tag} {path}: file not found")
            return None
        except (OSError, yaml.YAMLError) as exc:
            errors.append(f"{tag} {path}: {exc}")
            return None
        finally:
            depth[0] -= 1

    def _dir_entries(loader: yaml.SafeLoader, node: yaml.Node, tag: str) -> list[Path]:
        """Ficheros .yaml de un directorio de include, resueltos y contenidos."""
        rel = loader.construct_scalar(node)
        d = _target(rel, f"{tag} {rel}")
        if d is None:
            return []
        collected.add(str(d))
        try:
            candidates = sorted(d.glob("*.yaml"))
        except OSError as exc:
            errors.append(f"{tag} {d}: {exc}")
            return []
        # Cada entrada se vuelve a comprobar: un symlink dentro del directorio
        # apunta a donde quiera.
        files = []
        for f in candidates:
            safe = _contained(f, f"{tag} {f}")
            if safe is None:
                continue
            collected.add(str(safe))
            files.append(safe)
        return files

    def _include(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
        rel = loader.construct_scalar(node)
        p = _target(rel, f"!include {rel}")
        if p is None:
            return None
        collected.add(str(p))
        return _load_nested(p, "!include")

    def _include_dir_list(loader: yaml.SafeLoader, node: yaml.Node) -> list[Any]:
        tag = "!include_dir_list"
        return [_load_nested(f, tag) for f in _dir_entries(loader, node, tag)]

    def _include_dir_merge_list(loader: yaml.SafeLoader, node: yaml.Node) -> list[Any]:
        tag = "!include_dir_merge_list"
        result: list[Any] = []
        for f in _dir_entries(loader, node, tag):
            parsed = _load_nested(f, tag)
            if isinstance(parsed, list):
                result.extend(parsed)
            elif parsed is not None:
                result.append(parsed)
        return result

    def _include_dir_named(loader: yaml.SafeLoader, node: yaml.Node) -> dict[str, Any]:
        tag = "!include_dir_named"
        return {f.stem: _load_nested(f, tag) for f in _dir_entries(loader, node, tag)}

    def _include_dir_merge_named(loader: yaml.SafeLoader, node: yaml.Node) -> dict[str, Any]:
        tag = "!include_dir_merge_named"
        result: dict[str, Any] = {}
        for f in _dir_entries(loader, node, tag):
            parsed = _load_nested(f, tag)
            if isinstance(parsed, dict):
                result.update(parsed)
        return result

    def _secret(loader: yaml.SafeLoader, node: yaml.Node) -> str:
        return "__SECRET__"

    def _env_var(loader: yaml.SafeLoader, node: yaml.Node) -> str:
        return "__ENV_VAR__"

    HAIncludeCollector.add_constructor("!include", _include)
    HAIncludeCollector.add_constructor("!include_dir_list", _include_dir_list)
    HAIncludeCollector.add_constructor("!include_dir_merge_list", _include_dir_merge_list)
    HAIncludeCollector.add_constructor("!include_dir_named", _include_dir_named)
    HAIncludeCollector.add_constructor("!include_dir_merge_named", _include_dir_merge_named)
    HAIncludeCollector.add_constructor("!secret", _secret)
    HAIncludeCollector.add_constructor("!env_var", _env_var)

    return HAIncludeCollector


def _collect_include_paths_sync(config_base: Path) -> set[str] | _FailClosedMarker:
    """Parsea configuration.yaml y recopila todos los paths del árbol de includes.

    Ejecución síncrona — llamar desde asyncio.to_thread.

    Los paths se guardan YA RESUELTOS. Tiene que ser así porque el consumidor
    (check_executable_by_indirection) compara contra un path que viene de
    normalize_path(), que sí resuelve: guardando aquí `config_base / rel` sin
    resolver, un include alcanzado por `..` o por un symlink
    (`/config/sub/../sub/t.yaml`) no casaba nunca y el fichero se reportaba como
    NO ejecutable por indirección — la señal de seguridad fallando en abierto.

    Returns:
        set[str] de paths absolutos resueltos, o FAIL_CLOSED_MARKER si falla.
    """
    collected: set[str] = set()
    errors: list[str] = []

    try:
        config_base_resolved = config_base.resolve()
    except (OSError, ValueError, RuntimeError) as exc:
        logger.warning("yaml_resolver_fail_closed", reason=f"config base: {exc}")
        return FAIL_CLOSED_MARKER

    main = config_base_resolved / "configuration.yaml"
    if not main.exists():
        logger.warning("yaml_resolver_fail_closed", reason="configuration.yaml not found")
        return FAIL_CLOSED_MARKER

    # configuration.yaml se abre aquí, fuera de los constructores, así que hay
    # que sembrarlo a mano en `visited`: si no, un fichero que se incluye a sí
    # mismo daría una vuelta de más antes de que el freno de ciclos lo viera.
    visited: set[str] = {str(main)}
    Loader = _build_collector(config_base_resolved, collected, errors, visited)

    try:
        with open(main, encoding="utf-8") as f:
            yaml.load(f, Loader=Loader)
    except yaml.YAMLError as exc:
        reason = f"configuration.yaml syntax error: {exc}"
        logger.warning("yaml_resolver_fail_closed", reason=reason)
        return FAIL_CLOSED_MARKER
    except OSError as exc:
        reason = f"configuration.yaml read error: {exc}"
        logger.warning("yaml_resolver_fail_closed", reason=reason)
        return FAIL_CLOSED_MARKER
    except Exception as exc:  # noqa: BLE001
        # Red de seguridad deliberadamente amplia. Este recorrido se dispara en
        # CUALQUIER preview de escritura o borrado: lo que salga de aquí sin
        # capturar (un RecursionError, un error raro de PyYAML con un fichero
        # manipulado) no rompe solo esta función, rompe todas las escrituras,
        # incluida la que repararía el fichero culpable. Degradar a fail-closed
        # mantiene la protección (todo .yaml pasa a exigir confirmación) y deja
        # la herramienta utilizable.
        reason = f"configuration.yaml walk error: {type(exc).__name__}: {exc}"
        logger.warning("yaml_resolver_fail_closed", reason=reason)
        return FAIL_CLOSED_MARKER

    if errors:
        # Errors in includes → fail-closed (could indicate broken config)
        reason = f"{len(errors)} include error(s): {errors[0]}"
        logger.warning("yaml_resolver_fail_closed", reason=reason, errors=errors)
        return FAIL_CLOSED_MARKER

    # Only keep .yaml and .yml files (directories are collected too, filter them out)
    yaml_paths: set[str] = {
        p for p in collected
        if p.endswith(".yaml") or p.endswith(".yml")
    }
    logger.debug(
        "yaml_resolver_ok",
        paths=len(yaml_paths),
    )
    return yaml_paths


async def get_yaml_executable_paths() -> set[str] | _FailClosedMarker:
    """Devuelve el set de paths YAML del árbol de includes.

    Si el parseo falla → FAIL_CLOSED_MARKER. En ese caso, el caller
    debe tratar TODOS los .yaml/.yml como ejecutables por indirección.

    Los resultados se cachean hasta que se llame a invalidate_include_cache().
    """
    global _cached_paths, _cache_fail_reason

    async with _cache_lock:
        if _cached_paths is not None:
            return _cached_paths

        config_base = _fs.CONFIG_BASE
        result = await asyncio.to_thread(_collect_include_paths_sync, config_base)
        _cached_paths = result
        return result



# ── Sets hardcoded de paths ejecutables por indirección ───────────────────────

ALWAYS_EXECUTABLE_NAMES: frozenset[str] = frozenset({
    "configuration.yaml",
    "automations.yaml",
    "scripts.yaml",
    "scenes.yaml",
})

ALWAYS_EXECUTABLE_PATTERNS: list[str] = [
    "python_scripts/**",
    "blueprints/**",
    "packages/**",
    "custom_components/**",
    "deps/**",
    "www/**",
]

# Mensajes de advertencia específicos por patrón
_PATTERN_WARNINGS: dict[str, str] = {
    "custom_components/**": (
        "WARNING: this path contains custom integration code with full HA runtime access. "
        "Modifications can execute arbitrary Python via integration reload. "
        "Confirmation required."
    ),
    "www/**": (
        "WARNING: /www/** is publicly served by HA core at /local/ WITHOUT authentication. "
        "Anyone with the URL can download files placed here. "
        "Use confirmation_token to confirm you understand this risk."
    ),
}


def _is_in_always_executable(path: Path) -> bool:
    """Comprueba si el path está en los sets hardcoded de ejecutables."""
    config_base = _fs.CONFIG_BASE
    try:
        rel = path.relative_to(config_base)
    except ValueError:
        return False

    rel_str = rel.as_posix()
    name = rel.parts[0] if rel.parts else ""

    # Nombre exacto
    if rel_str in ALWAYS_EXECUTABLE_NAMES:
        return True

    # Patrones glob
    for pat in ALWAYS_EXECUTABLE_PATTERNS:
        if fnmatch.fnmatch(rel_str, pat):
            return True

    return False


def get_executable_warning(path: Path) -> str | None:
    """Devuelve el mensaje de advertencia específico para el path, si aplica."""
    config_base = _fs.CONFIG_BASE
    try:
        rel = path.relative_to(config_base)
    except ValueError:
        return None
    rel_str = rel.as_posix()
    for pat, warning in _PATTERN_WARNINGS.items():
        if fnmatch.fnmatch(rel_str, pat):
            return warning
    return None


async def check_executable_by_indirection(path: Path) -> bool:
    """Async: comprueba si el path es ejecutable por indirección (hardcoded + dinámico).

    También retorna True si el resolver está en fail-closed y el path es .yaml/.yml.
    """
    # 1. Hardcoded siempre
    if _is_in_always_executable(path):
        return True

    # 2. Set dinámico del árbol de includes
    exec_paths = await get_yaml_executable_paths()

    if exec_paths is FAIL_CLOSED_MARKER:
        # Fail-closed: cualquier .yaml/.yml es ejecutable
        return path.suffix.lower() in (".yaml", ".yml")

    return str(path) in exec_paths


async def is_fail_closed() -> bool:
    """Devuelve True si el resolver está en modo fail-closed."""
    result = await get_yaml_executable_paths()
    return result is FAIL_CLOSED_MARKER
