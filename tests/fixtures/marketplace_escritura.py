"""HA simulado con la forma del Marketplace de Core 2026.11.1 (spec 026).

Formas sacadas de `homeassistant/components/marketplace/` de HA Core
2026.11.1, no inventadas:

- `repositories/list` → `repository_summary` de `websocket/repositories.py`
  (id como texto de dígitos, `custom = not is_default`, `config_flow`,
  `local_path`, `authors`, `topics`…), filtrado por `categories` en el
  servidor; sin `categories` HA manda el catálogo entero, que pasa del tope de
  mensaje WS (hallazgo R-1 de la 006): el simulador falla igual.
- `repositories/removed` → `RemovedRepository.to_json` de `base.py`
  (`repository`, `reason`, `link`, `removal_type`, `acknowledged`), sin los
  ignorados.
- `critical/list` → lo guardado en `marketplace.critical` por
  `async_handle_critical_repositories` (`repository`, `reason`, `link`,
  `acknowledged`); `critical/acknowledge` lo marca y devuelve la lista entera
  (`critical.py`), sin decorador (nunca `not_loaded`).
- Errores con el `code` de HA: `repository_not_found`, `repository_installed`,
  `github_rate_limited`, `not_loaded`, `unknown_command`.

Datos ficticios: `ejemplo/*`, ids `"123456"`, `"234567"`, `"345678"`.
"""

from __future__ import annotations

import copy
from typing import Any

from hermes.ha import HAConnectionError

ID_PERSONALIZADO = "234567"     # ejemplo/tarjeta, plugin, personalizado, no instalado
ID_INSTALADO = "123456"         # ejemplo/integracion, integration, instalado, retirado
ID_CATALOGO = "345678"          # ejemplo/tema, theme, del catálogo, no instalado
ID_CRITICO = "456789"           # ejemplo/otra-critica, plugin, retirado como crítico


def error(code: str, mensaje: str = "") -> HAConnectionError:
    return HAConnectionError(f"HA WS command failed: {mensaje or code}", code=code)


def _resumen(rid: str, full_name: str, category: str, **extra: Any) -> dict[str, Any]:
    """`repository_summary` de HA 2026.11.1, con sus 27 claves."""
    base = {
        "authors": ["@ejemplo"],
        "available_version": "1.2.0",
        "can_install": True,
        "category": category,
        "config_flow": False,
        "custom": False,
        "description": f"Descripción de {full_name}",
        "domain": None,
        "downloads": 10,
        "file_name": f"{full_name.split('/')[1]}.js",
        "full_name": full_name,
        "hide": False,
        "homeassistant": None,
        "id": rid,
        "installed": False,
        "installed_version": None,
        "integration_categories": [],
        "last_updated": "2026-10-01T00:00:00Z",
        "local_path": f"/config/www/community/{full_name.split('/')[1]}",
        "name": full_name.split("/")[1],
        "new": False,
        "pending_upgrade": False,
        "stars": 3,
        "status": "default",
        "topics": ["ejemplo"],
    }
    base.update(extra)
    return base


def repositorios_base() -> list[dict[str, Any]]:
    return [
        _resumen(ID_PERSONALIZADO, "ejemplo/tarjeta", "plugin", custom=True),
        _resumen(ID_INSTALADO, "ejemplo/integracion", "integration",
                 installed=True, installed_version="1.1.0", domain="ejemplo",
                 config_flow=True, status="installed"),
        _resumen(ID_CATALOGO, "ejemplo/tema", "theme"),
        _resumen(ID_CRITICO, "ejemplo/otra-critica", "plugin"),
    ]


def retirados_base() -> list[dict[str, Any]]:
    return [
        {"repository": "ejemplo/integracion", "reason": "Archivado por su autor",
         "link": "https://example.com/retirada", "removal_type": "archived",
         "acknowledged": False},
        {"repository": "ejemplo/otra-critica", "reason": "Código malicioso",
         "link": "https://example.com/critica", "removal_type": "critical",
         "acknowledged": False},
    ]


def criticos_base() -> list[dict[str, Any]]:
    return [
        {"repository": "Ejemplo/Tarjeta-Critica", "reason": "Roba el token",
         "link": "https://example.com/aviso", "acknowledged": False},
        {"repository": "ejemplo/otra-critica", "reason": "Código malicioso",
         "link": "https://example.com/critica", "acknowledged": True},
    ]


class MarketplaceSimulado:
    """`ws_send` simulado del Marketplace de HA 2026.11.1.

    `errores[tipo]` fuerza que ese tipo responda la excepción (o la llame con
    la carga si es callable); `enviados` apunta todo lo enviado, en orden.
    Las escrituras cambian el estado como HA, para que la relectura y el
    `estado` atado vean lo que vería Hermes contra HA real.
    """

    def __init__(self) -> None:
        self.repos = repositorios_base()
        self.retirados = retirados_base()
        self.criticos = criticos_base()
        self.ignorados: set[str] = set()
        self.errores: dict[str, Any] = {}
        self.enviados: list[dict[str, Any]] = []

    @property
    def tipos(self) -> list[str]:
        return [p["type"] for p in self.enviados]

    def escrituras(self) -> list[dict[str, Any]]:
        lecturas = {"marketplace/repositories/list", "marketplace/repositories/removed",
                    "marketplace/critical/list"}
        return [p for p in self.enviados if p["type"] not in lecturas]

    def repo(self, rid: str) -> dict[str, Any]:
        return next(r for r in self.repos if r["id"] == rid)

    async def __call__(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.enviados.append(copy.deepcopy(payload))
        tipo = payload["type"]
        forzado = self.errores.get(tipo)
        if callable(forzado) and not isinstance(forzado, BaseException):
            forzado = forzado(payload)
        if isinstance(forzado, BaseException):
            raise forzado
        manejador = {
            "marketplace/repositories/list": self._lista,
            "marketplace/repositories/removed": self._retirados,
            "marketplace/critical/list": lambda p: copy.deepcopy(self.criticos),
            "marketplace/critical/acknowledge": self._reconocer,
            "marketplace/repository/ignore": self._ignorar,
            "marketplace/repositories/remove": self._quitar,
            "marketplace/repository/refresh": self._refrescar,
        }.get(tipo)
        if manejador is None:
            raise error("unknown_command", "Unknown command.")
        return manejador(payload)

    # ── lecturas ──
    def _lista(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        if "categories" not in p:
            raise HAConnectionError("WebSocket error en la conexión de HA.")
        return [copy.deepcopy(r) for r in self.repos if r["category"] in p["categories"]]

    def _retirados(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        return [copy.deepcopy(r) for r in self.retirados
                if r["repository"] not in self.ignorados]

    # ── escrituras (como los manejadores de HA) ──
    def _por_id(self, rid: Any) -> dict[str, Any]:
        for r in self.repos:
            if r["id"] == str(rid):
                return r
        raise error("repository_not_found", f"Repository {rid} not found")

    def _reconocer(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        for c in self.criticos:
            if c["repository"] == p["repository"]:
                c["acknowledged"] = True
        return copy.deepcopy(self.criticos)

    def _ignorar(self, p: dict[str, Any]) -> None:
        self.ignorados.add(self._por_id(p["repository"])["full_name"])

    def _quitar(self, p: dict[str, Any]) -> None:
        repo = self._por_id(p["repository"])
        if repo["installed"]:
            raise error("repository_installed", "Repository is installed")
        self.repos.remove(repo)

    def _refrescar(self, p: dict[str, Any]) -> None:
        self._por_id(p["repository"])["available_version"] = "1.3.0"
