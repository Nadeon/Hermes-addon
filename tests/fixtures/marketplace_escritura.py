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
- Tramo 2: `repository/uninstall` como `marketplace_repository_uninstall` de
  `websocket/repository.py` (`repository_not_found`,
  `repository_not_installed`, `repository_in_use` si la integración tiene
  entradas del `domain`, también ignoradas; al desinstalar, `installed`
  falso, sin versión y `status` `pending-restart` si
  `async_post_uninstall` de `repositories/integration.py` pide reiniciar:
  cargada en esta ejecución o sin `config_flow`); `config_entries/get` con
  `domain` como `config_entries_get` de `components/config` (todas las
  entradas, también las ignoradas). Y `SupervisorSimulado`: `POST
  /backups/new/partial` como `_do_backup_partial` de `supervisor/api/
  backups.py` con `background: false` (`{"job_id", "slug"}`, o el
  `APIError` «An error occurred while making backup, check job '…'», que
  `HAClient.sv_request` convierte en `HAConnectionError("Supervisor error:
  …")`).

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
        # Tramo 2: entradas de configuración por `domain` y dominios que esta
        # ejecución de Core ya cargó (`_known_to_the_loader` de HA).
        self.entradas: dict[str, list[dict[str, Any]]] = {}
        self.cargadas: set[str] = set()
        self.errores: dict[str, Any] = {}
        self.enviados: list[dict[str, Any]] = []

    @property
    def tipos(self) -> list[str]:
        return [p["type"] for p in self.enviados]

    def escrituras(self) -> list[dict[str, Any]]:
        lecturas = {"marketplace/repositories/list", "marketplace/repositories/removed",
                    "marketplace/critical/list", "config_entries/get"}
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
            "marketplace/repository/uninstall": self._desinstalar,
            "config_entries/get": self._entradas,
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

    def _entradas(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        return copy.deepcopy(self.entradas.get(p.get("domain"), []))

    def _desinstalar(self, p: dict[str, Any]) -> None:
        repo = self._por_id(p["repository"])
        if not repo["installed"]:
            raise error("repository_not_installed", "Repository is not installed")
        dominio = repo.get("domain")
        if repo["category"] == "integration" and dominio and self.entradas.get(dominio):
            raise error("repository_in_use", "Repository is in use")
        reiniciar = repo["category"] == "integration" and (
            dominio in self.cargadas or not repo.get("config_flow"))
        repo.update(installed=False, installed_version=None, new=False,
                    status="pending-restart" if reiniciar else "default")


JOB = "0123456789abcdef0123456789abcdef"
SLUG = "a1b2c3d4"


class SupervisorSimulado:
    """`sv_request` simulado del Supervisor 2026.11.0 para el backup previo.

    `modo`: `"ok"` (`{"job_id", "slug"}`), `"error"` (el `APIError` de
    `_do_backup_partial`, ya convertido por `HAClient.sv_request`), `"lento"`
    (`TimeoutError`: no terminó en la espera) o `"sin_slug"` (`{"job_id"}`,
    como con `background: true`). `llamadas` apunta cada petición.
    """

    def __init__(self, ha: MarketplaceSimulado | None = None) -> None:
        self.modo = "ok"
        self.mensaje_error = (
            f"Supervisor error: An error occurred while making backup, check job "
            f"'{JOB}' or supervisor logs for details"
        )
        self.llamadas: list[dict[str, Any]] = []
        # Para comprobar el orden: lo enviado a HA cuando llegó el backup.
        self._ha = ha
        self.enviados_a_ha_antes: list[str] | None = None

    async def __call__(
        self,
        method: str,
        sv_path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        timeout_seconds: float = 60.0,
    ) -> Any:
        self.llamadas.append({"method": method, "path": sv_path,
                              "json_body": copy.deepcopy(json_body),
                              "timeout_seconds": timeout_seconds})
        if self._ha is not None:
            self.enviados_a_ha_antes = list(self._ha.tipos)
        if self.modo == "error":
            raise HAConnectionError(self.mensaje_error)
        if self.modo == "lento":
            raise TimeoutError()
        if self.modo == "sin_slug":
            return {"job_id": JOB}
        return {"job_id": JOB, "slug": SLUG}
