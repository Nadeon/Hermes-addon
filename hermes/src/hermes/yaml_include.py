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


def _build_collector(config_base: Path, collected: set[str], errors: list[str]) -> type:
    """Construye una clase HAIncludeCollector con el config_base dado."""

    class HAIncludeCollector(yaml.SafeLoader):
        pass

    def _include(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
        rel = loader.construct_scalar(node)
        p = config_base / rel
        collected.add(str(p))
        try:
            with open(p, encoding="utf-8") as f:
                return yaml.load(f, Loader=HAIncludeCollector)
        except FileNotFoundError:
            errors.append(f"!include {p}: file not found")
            return None
        except yaml.YAMLError as exc:
            errors.append(f"!include {p}: {exc}")
            return None

    def _include_dir_list(loader: yaml.SafeLoader, node: yaml.Node) -> list[Any]:
        d = config_base / loader.construct_scalar(node)
        collected.add(str(d))
        result: list[Any] = []
        try:
            for f in sorted(d.glob("*.yaml")):
                collected.add(str(f))
                try:
                    with open(f, encoding="utf-8") as fh:
                        result.append(yaml.load(fh, Loader=HAIncludeCollector))
                except (FileNotFoundError, yaml.YAMLError) as exc:
                    errors.append(f"!include_dir_list {f}: {exc}")
        except OSError as exc:
            errors.append(f"!include_dir_list {d}: {exc}")
        return result

    def _include_dir_merge_list(loader: yaml.SafeLoader, node: yaml.Node) -> list[Any]:
        d = config_base / loader.construct_scalar(node)
        collected.add(str(d))
        result: list[Any] = []
        try:
            for f in sorted(d.glob("*.yaml")):
                collected.add(str(f))
                try:
                    with open(f, encoding="utf-8") as fh:
                        parsed = yaml.load(fh, Loader=HAIncludeCollector)
                        if isinstance(parsed, list):
                            result.extend(parsed)
                        elif parsed is not None:
                            result.append(parsed)
                except (FileNotFoundError, yaml.YAMLError) as exc:
                    errors.append(f"!include_dir_merge_list {f}: {exc}")
        except OSError as exc:
            errors.append(f"!include_dir_merge_list {d}: {exc}")
        return result

    def _include_dir_named(loader: yaml.SafeLoader, node: yaml.Node) -> dict[str, Any]:
        d = config_base / loader.construct_scalar(node)
        collected.add(str(d))
        result: dict[str, Any] = {}
        try:
            for f in sorted(d.glob("*.yaml")):
                collected.add(str(f))
                try:
                    with open(f, encoding="utf-8") as fh:
                        result[f.stem] = yaml.load(fh, Loader=HAIncludeCollector)
                except (FileNotFoundError, yaml.YAMLError) as exc:
                    errors.append(f"!include_dir_named {f}: {exc}")
        except OSError as exc:
            errors.append(f"!include_dir_named {d}: {exc}")
        return result

    def _include_dir_merge_named(loader: yaml.SafeLoader, node: yaml.Node) -> dict[str, Any]:
        d = config_base / loader.construct_scalar(node)
        collected.add(str(d))
        result: dict[str, Any] = {}
        try:
            for f in sorted(d.glob("*.yaml")):
                collected.add(str(f))
                try:
                    with open(f, encoding="utf-8") as fh:
                        parsed = yaml.load(fh, Loader=HAIncludeCollector)
                        if isinstance(parsed, dict):
                            result.update(parsed)
                except (FileNotFoundError, yaml.YAMLError) as exc:
                    errors.append(f"!include_dir_merge_named {f}: {exc}")
        except OSError as exc:
            errors.append(f"!include_dir_merge_named {d}: {exc}")
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

    Returns:
        set[str] de paths absolutos, o FAIL_CLOSED_MARKER si el parsing falla.
    """
    collected: set[str] = set()
    errors: list[str] = []

    main = config_base / "configuration.yaml"
    if not main.exists():
        logger.warning("yaml_resolver_fail_closed", reason="configuration.yaml not found")
        return FAIL_CLOSED_MARKER

    Loader = _build_collector(config_base, collected, errors)

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
